"""Bank transactions, classification, matching, allocation and reconciliation
(spec §13-§25, §38, §54, §64).

Key invariants
--------------
* A bank row is a *settlement*.  Linking a bank debit to a fuel/toll/...
  record never creates a second expense — reports take operating cost from
  operational tables and only take *directly allocated* bank amounts
  (debits with no underlying operational record) as expense.
* Every credit starts UNCLASSIFIED; nothing becomes income automatically.
* A bank row can never be linked/allocated beyond its amount; an operational
  record can never be settled beyond its amount.
* Suggestions are stored as AUTO_SUGGESTED and only become MATCHED by a user
  or by a matching rule explicitly configured to auto-approve.
* All operations run inside the caller's DB transaction (atomic) and write
  reconciliation history + audit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import audit, snapshot
from app.core.errors import BusinessError, Conflict, NotFound
from app.core.utils import jsonable, money, normalize_text, normalize_vehicle_number, now, sha256_of
from app.models.compliance import InsurancePolicy, VehicleRenewal
from app.models.finance import (BankTransaction, BankTransactionAllocation, Contract, CreditType, ExpenseTransaction,
                                ExpenseType, FinancialTransactionLink, Invoice, MatchingRule, ReconciliationHistory)
from app.models.fleet import CostCenter, Vehicle
from app.models.operations import FuelTransaction, MaintenanceJobCard, TollTransaction
from app.models.org import BankAccount, Customer, Provider, Vendor
from app.models.tyres import Tyre, TyreRetreading
from app.services import approvals
from app.services.rules import rule

ZERO = Decimal("0.00")


@dataclass
class Target:
    model: Any
    amount_attr: str
    date_attr: str
    ref_attrs: tuple[str, ...]
    label: str


TARGETS: dict[str, Target] = {
    "INVOICE": Target(Invoice, "total_amount", "invoice_date", ("invoice_number",), "Invoice"),
    "CONTRACT": Target(Contract, "contract_value", "start_date", ("contract_number",), "Contract"),
    "FUEL": Target(FuelTransaction, "total_amount", "txn_date", ("provider_transaction_id", "invoice_number"), "Fuel"),
    "TOLL": Target(TollTransaction, "amount", "txn_date", ("transaction_id",), "Toll"),
    "MAINTENANCE": Target(MaintenanceJobCard, "total_amount", "job_date", ("job_card_number", "invoice_number"),
                          "Maintenance"),
    "TYRE": Target(Tyre, "total_cost", "purchase_date", ("serial_number", "invoice_number"), "Tyre purchase"),
    "TYRE_RETREAD": Target(TyreRetreading, "cost", "sent_date", ("invoice_number",), "Tyre retreading"),
    "INSURANCE": Target(InsurancePolicy, "total_premium", "start_date", ("policy_number", "payment_reference"),
                        "Insurance"),
    "RENEWAL": Target(VehicleRenewal, "total_amount", "renewal_date", ("certificate_number", "document_number"),
                      "Tax/Permit/Compliance"),
    "EXPENSE": Target(ExpenseTransaction, "total_amount", "expense_date", ("document_number", "invoice_number"),
                      "Vendor invoice / expense"),
    "BANK": Target(BankTransaction, "amount", "txn_date", ("utr", "reference_number"), "Bank transaction"),
}

# which link types are allowed from a credit / debit and to which targets
LINK_RULES: dict[str, dict] = {
    "CONTRACT_RECEIPT": {"dir": "CR", "targets": {"CONTRACT"}, "kind": "SETTLE"},
    "INVOICE_RECEIPT": {"dir": "CR", "targets": {"INVOICE"}, "kind": "SETTLE"},
    "REFUND": {"dir": "CR", "targets": {"FUEL", "TOLL", "MAINTENANCE", "TYRE", "TYRE_RETREAD", "INSURANCE", "RENEWAL",
                                       "EXPENSE", "BANK"}, "kind": "REFUND"},
    "CASHBACK": {"dir": "CR", "targets": {"FUEL", "TOLL", "EXPENSE", "BANK"}, "kind": "REFUND"},
    "REBATE": {"dir": "CR", "targets": {"FUEL", "TOLL", "MAINTENANCE", "TYRE", "EXPENSE", "BANK"}, "kind": "REFUND"},
    "REVERSAL": {"dir": "ANY", "targets": {"BANK"}, "kind": "PAIR"},
    "INTERNAL_TRANSFER": {"dir": "DR", "targets": {"BANK"}, "kind": "PAIR"},
    "FUEL_PAYMENT": {"dir": "DR", "targets": {"FUEL"}, "kind": "SETTLE"},
    "TOLL_PAYMENT": {"dir": "DR", "targets": {"TOLL"}, "kind": "SETTLE"},
    "MAINTENANCE_PAYMENT": {"dir": "DR", "targets": {"MAINTENANCE"}, "kind": "SETTLE"},
    "TYRE_PAYMENT": {"dir": "DR", "targets": {"TYRE", "TYRE_RETREAD"}, "kind": "SETTLE"},
    "INSURANCE_PAYMENT": {"dir": "DR", "targets": {"INSURANCE"}, "kind": "SETTLE"},
    "TAX_PAYMENT": {"dir": "DR", "targets": {"RENEWAL"}, "kind": "SETTLE"},
    "PERMIT_PAYMENT": {"dir": "DR", "targets": {"RENEWAL"}, "kind": "SETTLE"},
    "PESO_PAYMENT": {"dir": "DR", "targets": {"RENEWAL"}, "kind": "SETTLE"},
    "VENDOR_PAYMENT": {"dir": "DR", "targets": {"EXPENSE", "MAINTENANCE", "TYRE", "TYRE_RETREAD"}, "kind": "SETTLE"},
    "OTHER": {"dir": "ANY", "targets": set(TARGETS), "kind": "SETTLE"},
}
LIVE = ("MATCHED",)
OPEN_LINK = ("MATCHED", "PENDING_APPROVAL", "AUTO_SUGGESTED")


# ───────────────────────── creation (manual / import / API share this) ─────────────────────────
def bank_hash(account_id: int, d: date, narration: str | None, debit: Decimal, credit: Decimal,
              ref: str | None, utr: str | None, balance: Decimal | None, occurrence: int = 0) -> str:
    """Business uniqueness key.  Balance and in-file occurrence distinguish genuinely
    identical same-day entries; re-importing the same statement yields the same keys."""
    return sha256_of("BANK", account_id, d, normalize_text(narration), money(debit), money(credit),
                     normalize_text(ref), normalize_text(utr), None if balance is None else money(balance), occurrence)


def prepare_bank_txn(t: BankTransaction, occurrence: int = 0) -> None:
    t.credit = money(t.credit)
    t.debit = money(t.debit)
    if t.credit > 0 and t.debit > 0:
        raise BusinessError("A bank row cannot have both debit and credit")
    if t.credit < 0 or t.debit < 0:
        raise BusinessError("Debit/credit must not be negative")
    if t.credit == 0 and t.debit == 0:
        raise BusinessError("Debit or credit amount is required")
    t.direction = "CR" if t.credit > 0 else "DR"
    t.amount = t.credit or t.debit
    t.unmatched_amount = t.amount - (t.matched_amount or ZERO)
    t.matched_amount = t.matched_amount or ZERO
    t.classification = t.classification or "UNCLASSIFIED"
    if not t.utr and t.narration:
        m = re.search(r"\b([A-Z]{4}[A-Z0-9]{2}\d{10,16}|\d{12,22})\b", t.narration.upper())
        t.utr = m.group(1) if m else None
    t.txn_hash = bank_hash(t.bank_account_id, t.txn_date, t.narration, t.debit, t.credit, t.reference_number, t.utr,
                           t.balance, occurrence)


def bank_before_save(ctx, t: BankTransaction, data: dict, is_new: bool) -> None:
    if not is_new:
        if t.recon_status not in ("UNMATCHED", "IGNORED") and ({"credit", "debit", "bank_account_id"} & set(data)):
            raise BusinessError("Amounts of a matched/allocated transaction cannot be changed. Unmatch first.")
    t.source_type = t.source_type or "MANUAL"
    prepare_bank_txn(t)
    dup = ctx.db.execute(select(BankTransaction.id).where(BankTransaction.bank_account_id == t.bank_account_id,
                                                          BankTransaction.txn_hash == t.txn_hash,
                                                          BankTransaction.id != (t.id or 0))).first()
    if dup:
        raise Conflict(f"Duplicate of bank transaction #{dup[0]}", "DUPLICATE")
    if is_new:
        t.recon_status = "UNMATCHED"


def bank_after_save(ctx, t: BankTransaction, data: dict, is_new: bool) -> None:
    recompute(ctx.db, t)
    if is_new:
        _hist(ctx.db, ctx.user, t, "CREATE", None, remarks="Manual entry" if t.source_type == "MANUAL" else None)


# ───────────────────────── status math ─────────────────────────
def _live_links_for_bank(db: Session, t: BankTransaction, statuses=LIVE):
    return db.execute(select(FinancialTransactionLink).where(
        FinancialTransactionLink.match_status.in_(statuses),
        or_(and_(FinancialTransactionLink.source_transaction_type == "BANK",
                 FinancialTransactionLink.source_transaction_id == t.id),
            and_(FinancialTransactionLink.target_transaction_type == "BANK",
                 FinancialTransactionLink.target_transaction_id == t.id,
                 FinancialTransactionLink.link_type.in_(["INTERNAL_TRANSFER", "REVERSAL"]))))).scalars().all()


def recompute(db: Session, t: BankTransaction) -> None:
    db.flush()
    links = _live_links_for_bank(db, t)
    allocs = db.execute(select(BankTransactionAllocation).where(
        BankTransactionAllocation.bank_transaction_id == t.id, BankTransactionAllocation.status == "ACTIVE")).scalars().all()
    link_amt = sum((money(l.linked_amount) for l in links), ZERO)
    alloc_amt = sum((money(a.amount) for a in allocs), ZERO)
    matched = link_amt + alloc_amt
    if matched > t.amount:
        raise BusinessError(f"Over-allocation: {matched} exceeds bank amount {t.amount}", "OVER_ALLOCATION")
    t.matched_amount = matched
    t.unmatched_amount = t.amount - matched
    pending = db.execute(select(func.count()).select_from(FinancialTransactionLink).where(
        FinancialTransactionLink.source_transaction_type == "BANK", FinancialTransactionLink.source_transaction_id == t.id,
        FinancialTransactionLink.match_status == "PENDING_APPROVAL")).scalar_one() + db.execute(
        select(func.count()).select_from(BankTransactionAllocation).where(
            BankTransactionAllocation.bank_transaction_id == t.id,
            BankTransactionAllocation.status == "PENDING_APPROVAL")).scalar_one()
    suggested = db.execute(select(func.count()).select_from(FinancialTransactionLink).where(
        FinancialTransactionLink.source_transaction_type == "BANK", FinancialTransactionLink.source_transaction_id == t.id,
        FinancialTransactionLink.match_status == "AUTO_SUGGESTED")).scalar_one()
    if t.recon_status == "IGNORED" and matched == 0:
        return
    if matched >= t.amount:
        t.recon_status = "ALLOCATED" if alloc_amt and not link_amt else "MATCHED"
    elif matched > 0:
        t.recon_status = "PARTIALLY_MATCHED"
    elif pending:
        t.recon_status = "PENDING_APPROVAL"
    elif suggested:
        t.recon_status = "AUTO_SUGGESTED"
    else:
        t.recon_status = "UNMATCHED"
    if any(l.link_type == "INTERNAL_TRANSFER" for l in links):
        t.classification = "INTERNAL_TRANSFER"


def recompute_invoice(db: Session, inv: Invoice) -> None:
    db.flush()
    received = db.execute(select(func.coalesce(func.sum(FinancialTransactionLink.linked_amount), 0)).where(
        FinancialTransactionLink.target_transaction_type == "INVOICE",
        FinancialTransactionLink.target_transaction_id == inv.id,
        FinancialTransactionLink.match_status.in_(LIVE))).scalar_one()
    credit_notes = db.execute(select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
        Invoice.original_invoice_id == inv.id, Invoice.invoice_type == "CREDIT_NOTE",
        Invoice.status != "CANCELLED")).scalar_one()
    inv.received_amount = money(received)
    if inv.invoice_type == "CREDIT_NOTE":
        inv.outstanding_amount = ZERO
        inv.status = "CANCELLED" if inv.status == "CANCELLED" else "APPLIED"
        return
    inv.outstanding_amount = money(inv.total_amount) - money(received) - money(credit_notes)
    if inv.status == "CANCELLED":
        return
    if inv.outstanding_amount < 0:
        inv.status = "OVERPAID"
    elif inv.outstanding_amount == 0:
        inv.status = "PAID"
    elif inv.received_amount > 0 or credit_notes:
        inv.status = "PARTIALLY_PAID"
    else:
        inv.status = "OPEN"


def target_obj(db: Session, ttype: str, tid: int):
    tg = TARGETS.get(ttype)
    if not tg:
        raise BusinessError(f"Unknown target type {ttype}")
    obj = db.get(tg.model, tid)
    if obj is None:
        raise NotFound(tg.label)
    return tg, obj


def target_linked(db: Session, ttype: str, tid: int, kind: str, exclude_link: int | None = None) -> Decimal:
    types = [k for k, v in LINK_RULES.items() if v["kind"] == kind]
    q = select(func.coalesce(func.sum(FinancialTransactionLink.linked_amount), 0)).where(
        FinancialTransactionLink.target_transaction_type == ttype, FinancialTransactionLink.target_transaction_id == tid,
        FinancialTransactionLink.match_status.in_(OPEN_LINK[:2]), FinancialTransactionLink.link_type.in_(types))
    if exclude_link:
        q = q.where(FinancialTransactionLink.id != exclude_link)
    return money(db.execute(q).scalar_one())


def _hist(db: Session, user, t: BankTransaction, action: str, old_status: str | None, amount=None,
          link_id=None, allocation_id=None, remarks=None) -> None:
    db.add(ReconciliationHistory(bank_transaction_id=t.id, action=action, old_status=old_status,
                                 new_status=t.recon_status, amount=amount, link_id=link_id,
                                 allocation_id=allocation_id, snapshot=jsonable(snapshot(t)), remarks=remarks,
                                 performed_by=getattr(user, "id", None), performed_at=now()))
    db.flush()


# ───────────────────────── classification ─────────────────────────
def classify(ctx, t: BankTransaction, data: dict) -> dict:
    db = ctx.db
    old = snapshot(t)
    if t.direction == "CR":
        ct = db.get(CreditType, int(data["credit_type_id"])) if data.get("credit_type_id") else None
        t.credit_type_id = ct.id if ct else None
        t.classification = ct.code if ct else "UNCLASSIFIED"
    else:
        et = db.get(ExpenseType, int(data["expense_type_id"])) if data.get("expense_type_id") else None
        t.expense_type_id = et.id if et else None
        t.classification = et.code if et else "UNCLASSIFIED"
    t.remarks = data.get("remarks") or t.remarks
    _hist(db, ctx.user, t, "CLASSIFY", t.recon_status, remarks=t.classification)
    audit(db, ctx.user, "CLASSIFY", "bank_transactions", t.id, old, snapshot(t), reason=data.get("remarks"))
    db.flush()
    return {"message": f"Classified as {t.classification}"}


# ───────────────────────── linking ─────────────────────────
def link(ctx, t: BankTransaction, link_type: str, targets: list[dict], remarks: str | None = None,
         method: str = "MANUAL", score: int | None = None, allow_overpayment: bool = False,
         force_status: str | None = None) -> list[FinancialTransactionLink]:
    """Link one bank row to one or many targets atomically (one-to-one / one-to-many).

    Many-to-one (several receipts → one invoice) is simply several calls with
    the same target; target capacity is enforced across all of them.
    """
    db = ctx.db
    if t.status != "ACTIVE":
        raise BusinessError("Transaction is void")
    lr = LINK_RULES.get(link_type)
    if not lr:
        raise BusinessError(f"Unknown link type {link_type}")
    if lr["dir"] != "ANY" and lr["dir"] != t.direction:
        raise BusinessError(f"{link_type.replace('_', ' ').title()} applies to bank "
                            f"{'credits' if lr['dir'] == 'CR' else 'debits'} only")
    if not targets:
        raise BusinessError("Select at least one transaction to match")
    total = sum((money(x.get("amount")) for x in targets), ZERO)
    if any(money(x.get("amount")) <= 0 for x in targets):
        raise BusinessError("Linked amounts must be greater than zero")
    recompute(db, t)
    if total > t.unmatched_amount:
        raise BusinessError(f"Over-allocation prevented: linking {total} but only {t.unmatched_amount} is unmatched",
                            "OVER_ALLOCATION")
    status = force_status or "MATCHED"
    appr_rule = None
    if status == "MATCHED" and method != "AUTO":
        appr_rule = approvals.requires_approval(db, "BANK_MATCH", total)
        if appr_rule:
            status = "PENDING_APPROVAL"
    created = []
    for x in targets:
        ttype, tid, amt = x["type"], int(x["id"]), money(x["amount"])
        if ttype not in lr["targets"]:
            raise BusinessError(f"{link_type} cannot target {ttype}")
        tg, obj = target_obj(db, ttype, tid)
        if ttype == "BANK":
            _validate_bank_pair(db, t, obj, link_type, amt)
        elif lr["kind"] in ("SETTLE", "REFUND"):
            cap = money(getattr(obj, tg.amount_attr) or 0)
            if ttype == "INVOICE":
                recompute_invoice(db, obj)
                if obj.status == "CANCELLED":
                    raise BusinessError(f"Invoice {obj.invoice_number} is cancelled")
                cap = money(obj.outstanding_amount)
                if amt > cap and not allow_overpayment:
                    raise BusinessError(f"Invoice {obj.invoice_number}: receipt {amt} exceeds outstanding {cap}. "
                                        "Tick 'allow overpayment' to record the excess.", "OVERPAYMENT")
            elif ttype == "CONTRACT":
                cap = None  # on-account receipts are not capped by a contract value
            else:
                already = target_linked(db, ttype, tid, lr["kind"])
                if cap is not None and already + amt > cap:
                    raise BusinessError(f"{tg.label} #{tid}: {'settled' if lr['kind'] == 'SETTLE' else 'refunded'} "
                                        f"amount would exceed its value ({already} + {amt} > {cap})",
                                        "TARGET_OVER_ALLOCATION")
        ln = FinancialTransactionLink(
            source_transaction_type="BANK", source_transaction_id=t.id, target_transaction_type=ttype,
            target_transaction_id=tid, linked_amount=amt, link_type=link_type, match_status=status,
            matching_method=method, match_score=score, matched_by=getattr(ctx.user, "id", None), matched_at=now(),
            approved_by=getattr(ctx.user, "id", None) if status == "MATCHED" and method != "AUTO" else None,
            approved_at=now() if status == "MATCHED" else None, remarks=remarks, created_at=now(), updated_at=now())
        db.add(ln)
        db.flush()
        created.append(ln)
        if ttype == "INVOICE":
            recompute_invoice(db, obj)
        if ttype == "BANK":
            recompute(db, obj)
            if link_type == "INTERNAL_TRANSFER":
                obj.classification = "INTERNAL_TRANSFER"
                _hist(db, ctx.user, obj, "MATCH", None, amt, ln.id, remarks="Internal transfer counterpart")
    old_status = t.recon_status
    if link_type == "INTERNAL_TRANSFER":
        t.classification = "INTERNAL_TRANSFER"
    elif t.direction == "CR" and t.classification == "UNCLASSIFIED":
        ct = db.execute(select(CreditType).where(CreditType.default_link_type == link_type,
                                                 CreditType.is_active.is_(True))).scalars().first()
        if ct:
            t.credit_type_id, t.classification = ct.id, ct.code
    recompute(db, t)
    for ln in created:
        _hist(db, ctx.user, t, "MATCH" if status == "MATCHED" else status, old_status, ln.linked_amount, ln.id,
              remarks=f"{link_type} → {ln.target_transaction_type} #{ln.target_transaction_id}")
    audit(db, ctx.user, "MATCH", "bank_transactions", t.id, new={
        "link_type": link_type, "targets": targets, "status": status, "method": method}, reason=remarks)
    if appr_rule:
        approvals.create_request(db, ctx.user, appr_rule, "BANK_MATCH", "bank_transactions", t.id,
                                 f"{link_type} of ₹{total} on bank txn #{t.id}", total,
                                 {"link_ids": [l.id for l in created]})
    return created


def _validate_bank_pair(db: Session, src: BankTransaction, other: BankTransaction, link_type: str, amt: Decimal):
    if other.id == src.id:
        raise BusinessError("A transaction cannot be linked to itself")
    if link_type == "INTERNAL_TRANSFER":
        if src.direction != "DR" or other.direction != "CR":
            raise BusinessError("Internal transfer links a debit (source account) to a credit (destination account)")
        if src.bank_account_id == other.bank_account_id:
            raise BusinessError("Internal transfer must be between two different own bank accounts")
        if src.amount != other.amount or amt != src.amount:
            raise BusinessError("Internal transfer debit and credit amounts must be equal")
        tol = rule(db, "BANK_MATCH_DATE_TOLERANCE_DAYS")
        if abs((src.txn_date - other.txn_date).days) > tol:
            raise BusinessError(f"Dates differ by more than {tol} day(s)")
        recompute(db, other)
        if other.unmatched_amount < amt:
            raise BusinessError("The counterpart credit is already matched")
    elif link_type == "REVERSAL":
        if src.direction == other.direction:
            raise BusinessError("A reversal links opposite directions")
        recompute(db, other)
        if amt > other.unmatched_amount:
            raise BusinessError("Reversal exceeds the unmatched amount of the original transaction")
    else:  # REFUND / CASHBACK / REBATE of a bank debit
        if other.direction != "DR":
            raise BusinessError("Refunds are linked to an original debit")
        already = target_linked(db, "BANK", other.id, "REFUND")
        if already + amt > other.amount:
            raise BusinessError(f"Refunds ({already} + {amt}) would exceed the original payment {other.amount}")


def unlink(ctx, link_id: int, reason: str) -> dict:
    db = ctx.db
    if not reason:
        raise BusinessError("A reason is required to unmatch")
    ln = db.get(FinancialTransactionLink, link_id)
    if not ln or ln.match_status not in OPEN_LINK:
        raise NotFound("Active link")
    old = ln.match_status
    ln.match_status = "REVERSED" if old == "MATCHED" else "REJECTED"
    ln.updated_at = now()
    ln.remarks = ((ln.remarks or "") + f" | Unmatched: {reason}")[:500]
    db.flush()
    t = db.get(BankTransaction, ln.source_transaction_id) if ln.source_transaction_type == "BANK" else None
    for bt in filter(None, [t, db.get(BankTransaction, ln.target_transaction_id)
                            if ln.target_transaction_type == "BANK" else None]):
        prev = bt.recon_status
        recompute(db, bt)
        if ln.link_type == "INTERNAL_TRANSFER" and not _live_links_for_bank(db, bt):
            bt.classification = "UNCLASSIFIED"
        _hist(db, ctx.user, bt, "UNMATCH", prev, ln.linked_amount, ln.id, remarks=reason)
    if ln.target_transaction_type == "INVOICE":
        recompute_invoice(db, db.get(Invoice, ln.target_transaction_id))
    audit(db, ctx.user, "UNMATCH", "financial_transaction_links", ln.id, {"match_status": old},
          {"match_status": ln.match_status}, reason=reason)
    return {"message": "Unmatched"}


def accept_suggestion(ctx, link_id: int) -> dict:
    db = ctx.db
    ln = db.get(FinancialTransactionLink, link_id)
    if not ln or ln.match_status != "AUTO_SUGGESTED":
        raise NotFound("Suggestion")
    t = db.get(BankTransaction, ln.source_transaction_id)
    tg, obj = target_obj(db, ln.target_transaction_type, ln.target_transaction_id)
    ln.match_status = "REJECTED"  # re-create through the validated path
    ln.remarks = "Accepted → re-validated as new link"
    db.flush()
    created = link(ctx, t, ln.link_type, [{"type": ln.target_transaction_type, "id": ln.target_transaction_id,
                                           "amount": ln.linked_amount}], remarks="Accepted suggestion",
                   method="SUGGESTED", score=ln.match_score)
    return {"message": "Suggestion accepted", "link_id": created[0].id}


def reject_suggestion(ctx, link_id: int, reason: str | None = None) -> dict:
    ln = ctx.db.get(FinancialTransactionLink, link_id)
    if not ln or ln.match_status != "AUTO_SUGGESTED":
        raise NotFound("Suggestion")
    ln.match_status = "REJECTED"
    ln.updated_at = now()
    t = ctx.db.get(BankTransaction, ln.source_transaction_id)
    prev = t.recon_status
    recompute(ctx.db, t)
    _hist(ctx.db, ctx.user, t, "REJECT_SUGGESTION", prev, ln.linked_amount, ln.id, remarks=reason)
    return {"message": "Suggestion rejected"}


# ───────────────────────── allocation to cost centers ─────────────────────────
def allocate(ctx, t: BankTransaction, lines: list[dict], allow_partial: bool = False,
             remarks: str | None = None) -> list[BankTransactionAllocation]:
    """Allocate (part of) an unmatched bank amount to one or many cost centers."""
    db = ctx.db
    if t.status != "ACTIVE":
        raise BusinessError("Transaction is void")
    if not lines:
        raise BusinessError("Add at least one allocation line")
    recompute(db, t)
    total = ZERO
    clean = []
    for i, ln in enumerate(lines, 1):
        amt = money(ln.get("amount"))
        if amt <= 0:
            raise BusinessError(f"Line {i}: amount must be greater than zero")
        cc = db.get(CostCenter, int(ln.get("cost_center_id") or 0)) if ln.get("cost_center_id") else None
        if not cc or not cc.is_active:
            raise BusinessError(f"Line {i}: select an active cost center")
        if t.direction == "DR" and not ln.get("expense_type_id"):
            raise BusinessError(f"Line {i}: expense type is required for a debit allocation")
        if t.direction == "CR" and not ln.get("credit_type_id"):
            raise BusinessError(f"Line {i}: credit type is required for a credit allocation")
        total += amt
        clean.append((cc, amt, ln))
    if total > t.unmatched_amount:
        raise BusinessError(f"Over-allocation prevented: {total} exceeds unmatched amount {t.unmatched_amount}",
                            "OVER_ALLOCATION")
    partial_ok = allow_partial and (rule(db, "BANK_ALLOW_PARTIAL_ALLOCATION") or t.allow_partial)
    if total < t.unmatched_amount and not partial_ok:
        raise BusinessError(f"Allocation total {total} must equal the unmatched amount {t.unmatched_amount} "
                            "(partial allocation is not enabled)", "ALLOCATION_MISMATCH")
    appr_rule = approvals.requires_approval(db, "BANK_ALLOCATION", total)
    status = "PENDING_APPROVAL" if appr_rule else "ACTIVE"
    out = []
    for cc, amt, ln in clean:
        a = BankTransactionAllocation(
            bank_transaction_id=t.id, cost_center_id=cc.id, amount=amt,
            expense_type_id=int(ln["expense_type_id"]) if ln.get("expense_type_id") else None,
            credit_type_id=int(ln["credit_type_id"]) if ln.get("credit_type_id") else None,
            vendor_id=int(ln["vendor_id"]) if ln.get("vendor_id") else None,
            vehicle_id=cc.vehicle_id if cc.cc_type == "VEHICLE" else (int(ln["vehicle_id"]) if ln.get("vehicle_id") else None),
            status=status, remarks=(ln.get("remarks") or remarks), created_by=ctx.user.id, updated_by=ctx.user.id)
        db.add(a)
        out.append(a)
    db.flush()
    prev = t.recon_status
    if t.direction == "CR" and t.classification == "UNCLASSIFIED" and len({c[2].get("credit_type_id") for c in clean}) == 1:
        ct = db.get(CreditType, int(clean[0][2]["credit_type_id"]))
        t.credit_type_id, t.classification = ct.id, ct.code
    recompute(db, t)
    for a in out:
        _hist(db, ctx.user, t, "ALLOCATE" if status == "ACTIVE" else "ALLOCATE_PENDING", prev, a.amount,
              allocation_id=a.id, remarks=a.remarks)
    audit(db, ctx.user, "ALLOCATE", "bank_transactions", t.id, new={
        "lines": [{"cost_center_id": a.cost_center_id, "amount": a.amount, "expense_type_id": a.expense_type_id,
                   "credit_type_id": a.credit_type_id} for a in out], "status": status}, reason=remarks)
    if appr_rule:
        approvals.create_request(db, ctx.user, appr_rule, "BANK_ALLOCATION", "bank_transactions", t.id,
                                 f"Allocation of ₹{total} on bank txn #{t.id} to {len(out)} cost center(s)", total,
                                 {"allocation_ids": [a.id for a in out]})
    return out


def reverse_allocation(ctx, allocation_id: int, reason: str) -> dict:
    db = ctx.db
    if not reason:
        raise BusinessError("A reason is required")
    a = db.get(BankTransactionAllocation, allocation_id)
    if not a or a.status == "REVERSED":
        raise NotFound("Active allocation")
    a.status = "REVERSED"
    a.remarks = ((a.remarks or "") + f" | Reversed: {reason}")[:255]
    t = db.get(BankTransaction, a.bank_transaction_id)
    prev = t.recon_status
    recompute(db, t)
    _hist(db, ctx.user, t, "REVERSE_ALLOCATION", prev, a.amount, allocation_id=a.id, remarks=reason)
    audit(db, ctx.user, "REVERSE", "bank_transaction_allocations", a.id, {"status": "ACTIVE"},
          {"status": "REVERSED"}, reason=reason)
    return {"message": "Allocation reversed"}


def set_ignored(ctx, t: BankTransaction, ignored: bool, reason: str) -> dict:
    if not reason:
        raise BusinessError("A reason is required")
    prev = t.recon_status
    if ignored:
        if t.matched_amount:
            raise BusinessError("Unmatch/reverse existing links before ignoring")
        t.recon_status = "IGNORED"
    else:
        t.recon_status = "UNMATCHED"
        recompute(ctx.db, t)
    _hist(ctx.db, ctx.user, t, "IGNORE" if ignored else "UNIGNORE", prev, remarks=reason)
    audit(ctx.db, ctx.user, "UPDATE", "bank_transactions", t.id, {"recon_status": prev},
          {"recon_status": t.recon_status}, reason=reason)
    return {"message": f"Status {t.recon_status}"}


def keep_unmatched(ctx, t: BankTransaction, reason: str | None) -> dict:
    t.remarks = reason or t.remarks
    _hist(ctx.db, ctx.user, t, "KEEP_UNMATCHED", t.recon_status, remarks=reason)
    return {"message": "Left unmatched"}


# ───────────────────────── approval handlers ─────────────────────────
def _approve_match(db, user, req):
    for lid in (req.payload or {}).get("link_ids", []):
        ln = db.get(FinancialTransactionLink, lid)
        if ln and ln.match_status == "PENDING_APPROVAL":
            ln.match_status, ln.approved_by, ln.approved_at, ln.updated_at = "MATCHED", user.id, now(), now()
            _refresh_link_sides(db, user, ln, "APPROVED")


def _reject_match(db, user, req):
    for lid in (req.payload or {}).get("link_ids", []):
        ln = db.get(FinancialTransactionLink, lid)
        if ln and ln.match_status == "PENDING_APPROVAL":
            ln.match_status, ln.updated_at = "REJECTED", now()
            _refresh_link_sides(db, user, ln, "REJECTED")


def _refresh_link_sides(db, user, ln, action):
    db.flush()
    for kind, tid in ((ln.source_transaction_type, ln.source_transaction_id),
                      (ln.target_transaction_type, ln.target_transaction_id)):
        if kind == "BANK":
            bt = db.get(BankTransaction, tid)
            prev = bt.recon_status
            recompute(db, bt)
            _hist(db, user, bt, action, prev, ln.linked_amount, ln.id)
        elif kind == "INVOICE":
            recompute_invoice(db, db.get(Invoice, tid))


def _approve_alloc(db, user, req, new_status="ACTIVE"):
    t = None
    for aid in (req.payload or {}).get("allocation_ids", []):
        a = db.get(BankTransactionAllocation, aid)
        if a and a.status == "PENDING_APPROVAL":
            a.status = new_status
            t = db.get(BankTransaction, a.bank_transaction_id)
    if t:
        prev = t.recon_status
        recompute(db, t)
        _hist(db, user, t, "APPROVED" if new_status == "ACTIVE" else "REJECTED", prev)


approvals.register("BANK_MATCH", _approve_match, _reject_match)
approvals.register("BANK_ALLOCATION", _approve_alloc, lambda db, u, r: _approve_alloc(db, u, r, "REVERSED"))


# ───────────────────────── suggestions ─────────────────────────
def _narr(t: BankTransaction) -> str:
    return normalize_text(t.narration)


def _contains(narr: str, token: str | None) -> bool:
    tok = normalize_text(token)
    return bool(tok) and len(tok) >= 3 and tok in narr


def _keywords_hit(narr: str, keywords: str | None) -> bool:
    return any(_contains(narr, k) for k in (keywords or "").split(",") if k.strip())


def suggest(db: Session, t: BankTransaction, limit: int = 15) -> dict:
    """Ranked candidate matches (never applied automatically here)."""
    narr = _narr(t)
    tol = rule(db, "BANK_MATCH_DATE_TOLERANCE_DAYS")
    amt = t.unmatched_amount if t.unmatched_amount is not None else t.amount
    cands: list[dict] = []

    def add(ttype, obj, link_type, remaining, score, why, party=None):
        tg = TARGETS[ttype]
        cands.append({"type": ttype, "id": obj.id, "link_type": link_type, "score": min(score, 100),
                      "reasons": why, "amount": str(remaining),
                      "suggested_amount": str(min(remaining, amt)) if remaining else str(amt),
                      "date": getattr(obj, tg.date_attr).isoformat() if getattr(obj, tg.date_attr, None) else None,
                      "reference": " / ".join(str(getattr(obj, a)) for a in tg.ref_attrs if getattr(obj, a, None)),
                      "party": party, "label": tg.label})

    def amount_score(remaining):
        if remaining == amt:
            return 40, "amount equal"
        if remaining and abs(remaining - amt) <= max(Decimal("1"), amt * Decimal("0.005")):
            return 30, "amount within tolerance"
        if remaining and amt < remaining:
            return 10, "partial amount"
        return 0, None

    if t.direction == "CR":
        for inv, cust in db.execute(select(Invoice, Customer).join(Customer, Customer.id == Invoice.customer_id).where(
                Invoice.status.in_(["OPEN", "PARTIALLY_PAID"]), Invoice.invoice_type != "CREDIT_NOTE")
                .order_by(Invoice.invoice_date.desc()).limit(500)).all():
            s, why = 0, []
            a, r = amount_score(money(inv.outstanding_amount))
            if r:
                s += a
                why.append(r)
            if _contains(narr, inv.invoice_number):
                s += 35
                why.append("invoice no. in narration")
            if _contains(narr, cust.name) or _keywords_hit(narr, cust.match_keywords):
                s += 20
                why.append("customer in narration")
            if inv.invoice_date <= t.txn_date:
                s += 5
            if s >= 30:
                add("INVOICE", inv, "INVOICE_RECEIPT", money(inv.outstanding_amount), s, why, cust.name)
        for c, cust in db.execute(select(Contract, Customer).join(Customer, Customer.id == Contract.customer_id).where(
                Contract.status == "ACTIVE", Contract.is_active.is_(True))).all():
            if _contains(narr, c.contract_number):
                add("CONTRACT", c, "CONTRACT_RECEIPT", amt, 55, ["contract no. in narration"], cust.name)
    # internal transfer / reversal counterparts in other accounts
    other_dir = "DR" if t.direction == "CR" else "CR"
    for o in db.execute(select(BankTransaction).where(
            BankTransaction.direction == other_dir, BankTransaction.id != t.id, BankTransaction.status == "ACTIVE",
            BankTransaction.amount == t.amount, BankTransaction.recon_status.in_(["UNMATCHED", "AUTO_SUGGESTED"]),
            BankTransaction.txn_date.between(t.txn_date - timedelta(days=tol), t.txn_date + timedelta(days=tol)))
            .limit(50)).scalars():
        s, why = 40, ["amount equal"]
        if t.utr and o.utr and t.utr == o.utr:
            s += 40
            why.append("same UTR")
        if abs((o.txn_date - t.txn_date).days) <= 1:
            s += 15
            why.append("same/next day")
        if o.bank_account_id != t.bank_account_id:
            s += 5
            lt = "INTERNAL_TRANSFER"
        else:
            lt = "REVERSAL"
        if t.direction == "DR" or lt == "REVERSAL":
            add("BANK", o, lt, o.amount, s, why)
        else:  # for a credit, the transfer link is created from the debit side
            cands.append({"type": "BANK", "id": o.id, "link_type": "INTERNAL_TRANSFER_FROM_DEBIT", "score": s,
                          "reasons": why, "amount": str(o.amount), "suggested_amount": str(o.amount),
                          "date": o.txn_date.isoformat(), "reference": o.utr or o.reference_number,
                          "label": "Bank debit (other account)"})
    if t.direction == "DR":
        start, end = t.txn_date - timedelta(days=60), t.txn_date + timedelta(days=tol)
        for ttype, lt, prov_attr in (("FUEL", "FUEL_PAYMENT", "provider_id"), ("TOLL", "TOLL_PAYMENT", "provider_id"),
                                     ("MAINTENANCE", "MAINTENANCE_PAYMENT", "vendor_id"),
                                     ("INSURANCE", "INSURANCE_PAYMENT", "provider_id"),
                                     ("RENEWAL", "TAX_PAYMENT", "provider_id"), ("EXPENSE", "VENDOR_PAYMENT", "vendor_id"),
                                     ("TYRE", "TYRE_PAYMENT", "supplier_id")):
            tg = TARGETS[ttype]
            M = tg.model
            q = select(M).where(getattr(M, tg.date_attr).between(start, end), getattr(M, tg.amount_attr) > 0)
            for obj in db.execute(q.limit(400)).scalars():
                total = money(getattr(obj, tg.amount_attr))
                remaining = total - target_linked(db, ttype, obj.id, "SETTLE")
                if remaining <= 0:
                    continue
                s, why = 0, []
                a, r = amount_score(remaining)
                if r:
                    s += a
                    why.append(r)
                if any(_contains(narr, getattr(obj, ra, None)) for ra in tg.ref_attrs):
                    s += 35
                    why.append("reference in narration")
                party = None
                pid = getattr(obj, prov_attr, None)
                if pid:
                    P = Vendor if prov_attr in ("vendor_id", "supplier_id") else Provider
                    p = db.get(P, pid)
                    party = p.name if p else None
                    if p and (_contains(narr, p.name) or _keywords_hit(narr, getattr(p, "match_keywords", None))):
                        s += 20
                        why.append("party in narration")
                if s >= 40:
                    lt2 = lt
                    if ttype == "RENEWAL":
                        from app.models.compliance import RenewalType
                        rt = db.get(RenewalType, obj.renewal_type_id)
                        lt2 = {"PERMIT": "PERMIT_PAYMENT", "PESO": "PESO_PAYMENT", "HAZMAT": "PESO_PAYMENT"}.get(
                            rt.category if rt else "", "TAX_PAYMENT")
                    add(ttype, obj, lt2, remaining, s, why, party)
    cands.sort(key=lambda c: -c["score"])
    return {"candidates": cands[:limit], "hints": classification_hints(db, t)}


def classification_hints(db: Session, t: BankTransaction) -> dict:
    """Suggested vendor / cost center / expense or credit type from narration keywords."""
    narr = _narr(t)
    hints: dict = {}
    for r in db.execute(select(MatchingRule).where(MatchingRule.is_active.is_(True)).order_by(MatchingRule.priority)
                        ).scalars():
        if r.narration_keywords and _keywords_hit(narr, r.narration_keywords):
            hints.setdefault("rule", {"code": r.code, "name": r.name, "link_type": r.link_type})
            break
    if t.direction == "CR":
        for ct in db.execute(select(CreditType).where(CreditType.is_active.is_(True))).scalars():
            if _contains(narr, ct.code.replace("_", " ")) or _contains(narr, ct.name):
                hints["credit_type"] = {"id": ct.id, "label": ct.name}
                break
    else:
        for et in db.execute(select(ExpenseType).where(ExpenseType.is_active.is_(True))).scalars():
            if _contains(narr, et.name) or _contains(narr, et.code.replace("_", " ")):
                hints["expense_type"] = {"id": et.id, "label": et.name}
                break
        for v in db.execute(select(Vendor).where(Vendor.is_active.is_(True))).scalars():
            if _contains(narr, v.name) or _keywords_hit(narr, v.match_keywords):
                hints["vendor"] = {"id": v.id, "label": v.name}
                break
    compact = normalize_vehicle_number(t.narration)
    if compact:
        for v in db.execute(select(Vehicle).where(Vehicle.is_active.is_(True))).scalars():
            if v.registration_normalized and v.registration_normalized in compact:
                hints["cost_center"] = {"id": v.cost_center_id, "label": v.registration_number}
                break
    return hints


def auto_suggest(ctx, txn_ids: list[int]) -> dict:
    """Store the best candidate for each unmatched row as AUTO_SUGGESTED (or auto-match only
    when a matching rule explicitly allows auto-approval above its score threshold)."""
    db = ctx.db
    made = auto = 0
    rules = {r.link_type: r for r in db.execute(select(MatchingRule).where(MatchingRule.is_active.is_(True))).scalars()}
    for tid in txn_ids:
        t = db.get(BankTransaction, tid)
        if not t or t.recon_status != "UNMATCHED":
            continue
        best = next((c for c in suggest(db, t, 5)["candidates"] if c["link_type"] in LINK_RULES), None)
        if not best:
            continue
        r = rules.get(best["link_type"])
        min_score = r.min_score if r else 60
        if best["score"] < min_score:
            continue
        amount = Decimal(best["suggested_amount"])
        if r and r.auto_approve and best["score"] >= r.auto_approve_min_score:
            link(ctx, t, best["link_type"], [{"type": best["type"], "id": best["id"], "amount": amount}],
                 remarks=f"Auto-matched by rule {r.code} (score {best['score']})", method="AUTO", score=best["score"])
            auto += 1
        else:
            ln = FinancialTransactionLink(
                source_transaction_type="BANK", source_transaction_id=t.id, target_transaction_type=best["type"],
                target_transaction_id=best["id"], linked_amount=amount, link_type=best["link_type"],
                match_status="AUTO_SUGGESTED", matching_method="SUGGESTED", match_score=best["score"],
                remarks="; ".join(best["reasons"]), created_at=now(), updated_at=now())
            db.add(ln)
            db.flush()
            prev = t.recon_status
            recompute(db, t)
            _hist(db, ctx.user, t, "AUTO_SUGGESTED", prev, amount, ln.id, remarks="; ".join(best["reasons"]))
            made += 1
    return {"suggested": made, "auto_matched": auto}


def describe_target(db: Session, ttype: str, tid: int) -> dict:
    try:
        tg, obj = target_obj(db, ttype, tid)
    except (NotFound, BusinessError):
        return {"type": ttype, "id": tid, "label": f"{ttype} #{tid}"}
    return {"type": ttype, "id": tid, "label": tg.label,
            "reference": " / ".join(str(getattr(obj, a)) for a in tg.ref_attrs if getattr(obj, a, None)),
            "date": jsonable(getattr(obj, tg.date_attr, None)), "amount": jsonable(getattr(obj, tg.amount_attr, None))}


def links_of(db: Session, t: BankTransaction) -> list[dict]:
    rows = db.execute(select(FinancialTransactionLink).where(or_(
        and_(FinancialTransactionLink.source_transaction_type == "BANK", FinancialTransactionLink.source_transaction_id == t.id),
        and_(FinancialTransactionLink.target_transaction_type == "BANK", FinancialTransactionLink.target_transaction_id == t.id)
    )).order_by(FinancialTransactionLink.id.desc())).scalars().all()
    out = []
    for l in rows:
        other = (l.target_transaction_type, l.target_transaction_id) if l.source_transaction_id == t.id and \
            l.source_transaction_type == "BANK" else (l.source_transaction_type, l.source_transaction_id)
        out.append({**{c.key: jsonable(getattr(l, c.key)) for c in FinancialTransactionLink.__table__.columns},
                    "other": describe_target(db, *other)})
    return out


def unsettled_targets(db: Session, ttype: str, params: dict, limit: int = 200) -> list[dict]:
    """Operational records with remaining settlement capacity (for manual multi-select matching)."""
    tg = TARGETS[ttype]
    M = tg.model
    q = select(M)
    if params.get("date_from"):
        from app.core.utils import parse_date
        q = q.where(getattr(M, tg.date_attr) >= parse_date(params["date_from"]))
    if params.get("date_to"):
        from app.core.utils import parse_date
        q = q.where(getattr(M, tg.date_attr) <= parse_date(params["date_to"]))
    for k in ("provider_id", "vendor_id", "customer_id", "vehicle_id"):
        if params.get(k) and hasattr(M, k):
            q = q.where(getattr(M, k) == int(params[k]))
    if ttype == "INVOICE":
        q = q.where(Invoice.status.in_(["OPEN", "PARTIALLY_PAID"]), Invoice.invoice_type != "CREDIT_NOTE")
    if params.get("q"):
        q = q.where(or_(*[getattr(M, a).ilike(f"%{params['q']}%") for a in tg.ref_attrs]))
    kind = "REFUND" if params.get("kind") == "REFUND" else "SETTLE"
    out = []
    for obj in db.execute(q.order_by(getattr(M, tg.date_attr).desc()).limit(limit)).scalars():
        total = money(getattr(obj, tg.amount_attr) or 0)
        if ttype == "INVOICE":
            remaining = money(obj.outstanding_amount)
        elif ttype == "CONTRACT":
            remaining = total
        else:
            remaining = total - target_linked(db, ttype, obj.id, kind)
        if remaining <= 0 and ttype != "CONTRACT":
            continue
        row = {"type": ttype, "id": obj.id, "date": jsonable(getattr(obj, tg.date_attr)), "total": str(total),
               "remaining": str(remaining),
               "reference": " / ".join(str(getattr(obj, a)) for a in tg.ref_attrs if getattr(obj, a, None))}
        if getattr(obj, "vehicle_id", None):
            v = db.get(Vehicle, obj.vehicle_id)
            row["vehicle"] = v.registration_number if v else None
        out.append(row)
    return out
