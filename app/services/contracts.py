"""Contracts, invoices (income recognition + vehicle income allocation),
receivables and generic expense transactions (spec §10, §15, §37)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.errors import BusinessError
from app.core.utils import money, today
from app.models.finance import (Contract, ContractVehicleAllocation, ExpenseAllocation, ExpenseTransaction, Invoice,
                                InvoiceAllocation)
from app.models.fleet import CostCenter, Vehicle
from app.models.org import Customer
from app.services.vehicles import cost_center_for

ZERO = Decimal("0.00")


def contract_before_save(ctx, c: Contract, data: dict, is_new: bool) -> None:
    if c.end_date and c.start_date and c.end_date < c.start_date:
        raise BusinessError("Contract end date must be after start date")


def contract_after_save(ctx, c: Contract, data: dict, is_new: bool) -> None:
    rows = ctx.db.execute(select(ContractVehicleAllocation).where(ContractVehicleAllocation.contract_id == c.id)
                          ).scalars().all()
    pct = sum((r.allocation_percent or ZERO) for r in rows)
    if rows and any(r.allocation_percent for r in rows) and pct != Decimal("100"):
        raise BusinessError(f"Vehicle allocation percentages must total 100 (currently {pct})")
    for r in rows:
        if not r.vehicle_id and not r.cost_center_id:
            raise BusinessError("Each allocation line needs a vehicle or a cost center")
        if r.vehicle_id and not r.cost_center_id:
            r.cost_center_id = cost_center_for(ctx.db, r.vehicle_id, r.effective_from or c.start_date)


def invoice_before_save(ctx, inv: Invoice, data: dict, is_new: bool) -> None:
    db = ctx.db
    inv.tax_amount = money(inv.tax_amount)
    inv.taxable_amount = money(inv.taxable_amount)
    inv.total_amount = inv.taxable_amount + inv.tax_amount
    if inv.taxable_amount <= 0:
        raise BusinessError("Taxable amount must be greater than zero (use a credit note for reductions)")
    if inv.contract_id:
        c = db.get(Contract, inv.contract_id)
        if c.customer_id != inv.customer_id:
            raise BusinessError("Contract belongs to a different customer")
    if inv.invoice_type == "CREDIT_NOTE":
        if not inv.original_invoice_id:
            raise BusinessError("A credit note must reference the original invoice")
        orig = db.get(Invoice, inv.original_invoice_id)
        if orig.customer_id != inv.customer_id:
            raise BusinessError("Credit note customer differs from the original invoice")
    if inv.due_date is None and inv.invoice_date:
        days = None
        if inv.contract_id:
            days = db.get(Contract, inv.contract_id).payment_terms_days
        days = days if days is not None else (db.get(Customer, inv.customer_id).credit_days or 0)
        from datetime import timedelta
        inv.due_date = inv.invoice_date + timedelta(days=days)
    if not is_new and inv.received_amount and ({"customer_id", "taxable_amount", "tax_amount"} & set(data)):
        if inv.total_amount < inv.received_amount:
            raise BusinessError("Invoice total cannot be reduced below the amount already received")


def invoice_after_save(ctx, inv: Invoice, data: dict, is_new: bool) -> None:
    """Income allocation across vehicles must equal the taxable amount (income excl. GST)."""
    db = ctx.db
    rows = db.execute(select(InvoiceAllocation).where(InvoiceAllocation.invoice_id == inv.id)).scalars().all()
    if not rows and inv.contract_id:
        rows = _allocate_from_contract(db, inv)
    if not rows:
        raise BusinessError("Allocate the invoice income to at least one vehicle / cost center", "VALIDATION",
                            [{"field": "allocations", "message": "Income allocation required"}])
    for r in rows:
        if r.vehicle_id and not r.cost_center_id:
            r.cost_center_id = cost_center_for(db, r.vehicle_id, inv.invoice_date)
        if not r.cost_center_id:
            raise BusinessError("Every allocation line needs a vehicle or cost center")
    total = sum((money(r.amount) for r in rows), ZERO)
    if total != inv.taxable_amount:
        raise BusinessError(f"Income allocation total {total} must equal the taxable amount {inv.taxable_amount}",
                            "ALLOCATION_MISMATCH")
    from app.services.bank import recompute_invoice
    recompute_invoice(db, inv)
    if inv.original_invoice_id:
        recompute_invoice(db, db.get(Invoice, inv.original_invoice_id))


def _allocate_from_contract(db: Session, inv: Invoice) -> list[InvoiceAllocation]:
    on = inv.period_to or inv.invoice_date
    allocs = [a for a in db.execute(select(ContractVehicleAllocation).where(
        ContractVehicleAllocation.contract_id == inv.contract_id)).scalars()
        if (a.effective_from is None or a.effective_from <= on) and (a.effective_to is None or a.effective_to >= on)]
    if not allocs:
        return []
    out, running = [], ZERO
    pct_based = all(a.allocation_percent for a in allocs)
    for i, a in enumerate(allocs):
        if pct_based:
            amt = money(inv.taxable_amount * a.allocation_percent / 100) if i < len(allocs) - 1 \
                else inv.taxable_amount - running
        else:
            amt = money(inv.taxable_amount / len(allocs)) if i < len(allocs) - 1 else inv.taxable_amount - running
        running += amt
        row = InvoiceAllocation(invoice_id=inv.id, vehicle_id=a.vehicle_id,
                                cost_center_id=a.cost_center_id or cost_center_for(db, a.vehicle_id, on), amount=amt,
                                remarks="From contract allocation")
        db.add(row)
        out.append(row)
    db.flush()
    return out


def cancel_invoice(ctx, inv: Invoice, data: dict) -> dict:
    if inv.received_amount and inv.received_amount > 0:
        raise BusinessError("Unmatch receipts before cancelling the invoice")
    old = inv.status
    inv.status = "CANCELLED"
    audit(ctx.db, ctx.user, "CANCEL", "invoices", inv.id, {"status": old}, {"status": "CANCELLED"},
          reason=data.get("reason"))
    return {"message": "Invoice cancelled"}


def invoice_extra(ctx, inv: Invoice, row: dict) -> None:
    row["overdue_days"] = (today() - inv.due_date).days if inv.due_date and inv.outstanding_amount > 0 \
        and inv.due_date < today() else 0


def receivables(db: Session, customer_id: int | None = None) -> list[dict]:
    from app.models.finance import FinancialTransactionLink
    q = select(Invoice.customer_id, func.sum(Invoice.total_amount), func.sum(Invoice.received_amount),
               func.sum(Invoice.outstanding_amount), func.count()).where(
        Invoice.status.notin_(["CANCELLED"]), Invoice.invoice_type != "CREDIT_NOTE").group_by(Invoice.customer_id)
    if customer_id:
        q = q.where(Invoice.customer_id == customer_id)
    out = []
    t = today()
    for cid, total, rec, outst, n in db.execute(q).all():
        c = db.get(Customer, cid)
        on_acct = db.execute(select(func.coalesce(func.sum(FinancialTransactionLink.linked_amount), 0)).join(
            Contract, Contract.id == FinancialTransactionLink.target_transaction_id).where(
            FinancialTransactionLink.target_transaction_type == "CONTRACT", Contract.customer_id == cid,
            FinancialTransactionLink.match_status == "MATCHED")).scalar_one()
        ages = {"0_30": ZERO, "31_60": ZERO, "61_90": ZERO, "90_plus": ZERO}
        for inv in db.execute(select(Invoice).where(Invoice.customer_id == cid, Invoice.outstanding_amount > 0,
                                                    Invoice.status.notin_(["CANCELLED"]))).scalars():
            d = (t - (inv.due_date or inv.invoice_date)).days
            k = "0_30" if d <= 30 else "31_60" if d <= 60 else "61_90" if d <= 90 else "90_plus"
            ages[k] += inv.outstanding_amount
        out.append({"customer": c.name if c else cid, "customer_id": cid, "invoices": n, "invoiced": total,
                    "received": rec, "outstanding": outst, "on_account_receipts": money(on_acct),
                    "net_receivable": money(outst) - money(on_acct), **ages})
    return out


# ───────────────────────── generic expense transactions ─────────────────────────
def expense_before_save(ctx, e: ExpenseTransaction, data: dict, is_new: bool) -> None:
    e.amount = money(e.amount)
    e.tax_amount = money(e.tax_amount)
    e.total_amount = e.amount + e.tax_amount
    if e.amount <= 0:
        raise BusinessError("Amount must be greater than zero")
    if e.vehicle_id and not e.cost_center_id:
        e.cost_center_id = cost_center_for(ctx.db, e.vehicle_id, e.expense_date)
    e.source_type = e.source_type or "MANUAL"


def expense_after_save(ctx, e: ExpenseTransaction, data: dict, is_new: bool) -> None:
    db = ctx.db
    rows = db.execute(select(ExpenseAllocation).where(ExpenseAllocation.expense_id == e.id)).scalars().all()
    if not rows:
        if not e.cost_center_id:
            raise BusinessError("Select a vehicle / cost center or add allocation lines")
        return
    for r in rows:
        cc = db.get(CostCenter, r.cost_center_id)
        if cc and cc.vehicle_id and not r.vehicle_id:
            r.vehicle_id = cc.vehicle_id
    total = sum((money(r.amount) for r in rows), ZERO)
    if total != e.amount:
        raise BusinessError(f"Allocation total {total} must equal the expense amount {e.amount}",
                            "ALLOCATION_MISMATCH")
