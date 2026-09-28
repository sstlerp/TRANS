"""Bank statements, classification, reconciliation, allocation and no double counting
(acceptance criteria 12-23, 46; spec §13-§25, §64)."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import BusinessError, PermissionDenied
from app.models.finance import (ApprovalRequest, BankTransaction, BankTransactionAllocation, FinancialTransactionLink,
                                Invoice, ReconciliationHistory)
from app.models.imports import StatementImportTemplate
from app.models.system import AuditLog
from app.sample_files import bank_hdfc, bank_sbi
from app.services import approvals, bank, import_engine, masters, reports
from tests.factories import bank_txn, dmy, fuel_txn, make_invoice

T = date.today()


def tpl(db, name):
    return db.execute(select(StatementImportTemplate).where(StatementImportTemplate.template_name == name)).scalar_one().id


def import_file(ctx, name, data, account_id, fname="statement.xlsx"):
    b = import_engine.create_preview(ctx, tpl(ctx.db, name), data, fname, bank_account_id=account_id)
    return b


def prof_row(res, vehicle_reg):
    return next(r for r in res["rows"] if r["vehicle"] == vehicle_reg)


# ───────────────────────── import ─────────────────────────
def test_bank_import_credits_and_debits_all_unclassified(ctx, fleet):
    b = import_file(ctx, "HDFC Current Account Statement", bank_hdfc(), fleet.acc1.id)
    assert b.status == "PREVIEWED" and b.total_rows == 11 and b.error_rows == 0
    import_engine.commit_batch(ctx, b.id, auto_suggest=False)
    rows = ctx.db.execute(select(BankTransaction).where(BankTransaction.import_batch_id == b.id)).scalars().all()
    assert len(rows) == 11
    assert sum(r.direction == "CR" for r in rows) == 5 and sum(r.direction == "DR" for r in rows) == 6
    assert all(r.classification == "UNCLASSIFIED" and r.recon_status == "UNMATCHED" for r in rows)
    first = min(rows, key=lambda r: r.source_row)
    assert first.source_file == "statement.xlsx" and first.source_sheet == "Statement" and first.source_row == 5
    assert first.credit == Decimal("100000.00") and first.balance == Decimal("1100000.00")
    assert ctx.db.get(type(fleet.acc1), fleet.acc1.id).closing_balance is not None


def test_duplicate_bank_import_is_flagged_not_inserted(ctx, fleet):
    b1 = import_file(ctx, "HDFC Current Account Statement", bank_hdfc(), fleet.acc1.id)
    import_engine.commit_batch(ctx, b1.id, auto_suggest=False)
    b2 = import_file(ctx, "HDFC Current Account Statement", bank_hdfc(), fleet.acc1.id)
    assert b2.duplicate_rows == 11
    import_engine.commit_batch(ctx, b2.id, auto_suggest=False)
    assert ctx.db.execute(select(func.count()).select_from(BankTransaction).where(
        BankTransaction.bank_account_id == fleet.acc1.id)).scalar_one() == 11


def test_second_bank_layout_amount_with_drcr(ctx, fleet):
    b = import_file(ctx, "SBI Account Statement (Amount + Dr/Cr)", bank_sbi(), fleet.acc2.id)
    import_engine.commit_batch(ctx, b.id, auto_suggest=False)
    rows = ctx.db.execute(select(BankTransaction).where(BankTransaction.import_batch_id == b.id)).scalars().all()
    assert len(rows) == 4 and {r.direction for r in rows} == {"CR", "DR"}
    assert any(r.utr == "UTR000000123456" for r in rows)


def test_wrong_layout_fails_header_validation(ctx, fleet):
    b = import_file(ctx, "SBI Account Statement (Amount + Dr/Cr)", bank_hdfc(), fleet.acc2.id)
    assert b.summary["header_ok"] is False
    with pytest.raises(BusinessError):
        import_engine.commit_batch(ctx, b.id)


def test_manual_bank_entry_uses_same_table_and_detects_duplicates(ctx, fleet):
    t = bank_txn(ctx, fleet.acc1.id, 1234, "DR", "MANUAL CHARGE")
    assert t["source_type"] == "MANUAL" and t["recon_status"] == "UNMATCHED"
    with pytest.raises(BusinessError):
        bank_txn(ctx, fleet.acc1.id, 1234, "DR", "MANUAL CHARGE")


# ───────────────────────── contract income matching ─────────────────────────
def _alloc3(f, total):
    a = Decimal(total)
    return [(f.v.lpg["id"], a * Decimal("0.4")), (f.v.open["id"], a * Decimal("0.3")), (f.v.cng["id"], a * Decimal("0.3"))]


def test_one_to_one_contract_receipt_no_double_income(ctx, fleet):
    inv = make_invoice(ctx, fleet, "INV-1", 100000, _alloc3(fleet, 100000))
    t = bank_txn(ctx, fleet.acc1.id, 100000, "CR", "NEFT SOUTHERN GAS INV-1")
    bt = ctx.db.get(BankTransaction, t["id"])
    bank.link(ctx, bt, "INVOICE_RECEIPT", [{"type": "INVOICE", "id": inv["id"], "amount": 100000}])
    i = ctx.db.get(Invoice, inv["id"])
    assert (i.status, i.outstanding_amount, bt.recon_status) == ("PAID", Decimal("0.00"), "MATCHED")
    assert bt.classification == "INVOICE_RECEIPT"
    res = reports.profitability(ctx.db, T - timedelta(days=30), T)
    assert prof_row(res, "TN01AA0001")["contract_income"] == Decimal("40000.00")
    assert sum(r["contract_income"] for r in res["rows"]) == Decimal("100000.00")  # not 200,000


def test_partial_receipt_and_many_receipts_to_one_invoice(ctx, fleet):
    inv = make_invoice(ctx, fleet, "INV-2", 100000, _alloc3(fleet, 100000))
    t1 = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 40000, "CR", "PART 1")["id"])
    bank.link(ctx, t1, "INVOICE_RECEIPT", [{"type": "INVOICE", "id": inv["id"], "amount": 40000}])
    i = ctx.db.get(Invoice, inv["id"])
    assert (i.status, i.received_amount, i.outstanding_amount) == ("PARTIALLY_PAID", Decimal("40000.00"), Decimal("60000.00"))
    t2 = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 60000, "CR", "PART 2")["id"])
    bank.link(ctx, t2, "INVOICE_RECEIPT", [{"type": "INVOICE", "id": inv["id"], "amount": 60000}])
    assert ctx.db.get(Invoice, inv["id"]).status == "PAID"


def test_one_receipt_to_many_invoices(ctx, fleet):
    a = make_invoice(ctx, fleet, "INV-3A", 100000, _alloc3(fleet, 100000))
    b = make_invoice(ctx, fleet, "INV-3B", 50000, [(fleet.v.lpg["id"], 50000)])
    t = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 150000, "CR", "BULK RECEIPT")["id"])
    links = bank.link(ctx, t, "INVOICE_RECEIPT", [{"type": "INVOICE", "id": a["id"], "amount": 100000},
                                                  {"type": "INVOICE", "id": b["id"], "amount": 50000}])
    assert len(links) == 2 and t.recon_status == "MATCHED"
    assert {ctx.db.get(Invoice, a["id"]).status, ctx.db.get(Invoice, b["id"]).status} == {"PAID"}


def test_overpayment_blocked_unless_authorised(ctx, fleet):
    inv = make_invoice(ctx, fleet, "INV-4", 10000, [(fleet.v.lpg["id"], 10000)])
    t = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 12000, "CR", "OVERPAY")["id"])
    with pytest.raises(BusinessError) as e:
        bank.link(ctx, t, "INVOICE_RECEIPT", [{"type": "INVOICE", "id": inv["id"], "amount": 12000}])
    assert e.value.code == "OVERPAYMENT"
    bank.link(ctx, t, "INVOICE_RECEIPT", [{"type": "INVOICE", "id": inv["id"], "amount": 12000}], allow_overpayment=True)
    i = ctx.db.get(Invoice, inv["id"])
    assert i.status == "OVERPAID" and i.outstanding_amount == Decimal("-2000.00")


def test_income_allocation_must_balance(ctx, fleet):
    with pytest.raises(BusinessError):
        make_invoice(ctx, fleet, "INV-BAD", 100000, [(fleet.v.lpg["id"], 50000)])


def test_contract_allocation_percentages_generate_invoice_split(ctx, fleet):
    c = masters.save_record(ctx, masters.get_spec("contracts"), {
        "customer_id": fleet.cust.id, "contract_number": "CT-1", "start_date": dmy(T - timedelta(days=100)), "status": "ACTIVE",
        "vehicles": [{"vehicle_id": fleet.v.lpg["id"], "allocation_percent": "40"},
                     {"vehicle_id": fleet.v.open["id"], "allocation_percent": "30"},
                     {"vehicle_id": fleet.v.cng["id"], "allocation_percent": "30"}]})
    inv = masters.save_record(ctx, masters.get_spec("invoices"), {
        "invoice_number": "INV-CT", "customer_id": fleet.cust.id, "contract_id": c["id"], "invoice_date": dmy(T - timedelta(days=3)),
        "taxable_amount": "100000", "tax_amount": "18000"})
    assert sorted(Decimal(a["amount"]) for a in inv["allocations"]) == [Decimal("30000.00"), Decimal("30000.00"), Decimal("40000.00")]
    assert inv["total_amount"] == "118000.00"


# ───────────────────────── refunds / cashback / transfers ─────────────────────────
def test_refund_reduces_expense_not_revenue(ctx, fleet):
    job = masters.save_record(ctx, masters.get_spec("job_cards"), {
        "job_card_number": "JC-1", "vehicle_id": fleet.v.open["id"], "job_date": dmy(T - timedelta(days=8)),
        "maintenance_type_id": fleet.mt["GEN"], "other_amount": "50000", "tax_amount": "0"})
    pay = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 50000, "DR", "AUTOCARE", T - timedelta(days=7))["id"])
    bank.link(ctx, pay, "MAINTENANCE_PAYMENT", [{"type": "MAINTENANCE", "id": job["id"], "amount": 50000}])
    ref = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 5000, "CR", "REFUND AUTOCARE", T - timedelta(days=6))["id"])
    bank.link(ctx, ref, "REFUND", [{"type": "MAINTENANCE", "id": job["id"], "amount": 5000}])
    assert ref.recon_status == "MATCHED" and ref.classification != "UNCLASSIFIED"
    row = prof_row(reports.profitability(ctx.db, T - timedelta(days=30), T), "TN01AA0002")
    assert row["maintenance"] == Decimal("45000.00")  # 50,000 − 5,000 refund; bank payment not double counted
    assert row["contract_income"] == 0 and row["other_income"] == 0
    with pytest.raises(BusinessError):  # cannot refund more than the original
        more = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 46000, "CR", "BIG REFUND")["id"])
        bank.link(ctx, more, "REFUND", [{"type": "MAINTENANCE", "id": job["id"], "amount": 46000}])


def test_cashback_classified_separately(ctx, fleet):
    f1 = fuel_txn(ctx, fleet, fleet.v.lpg, "DIESEL", 100, 90)
    cb = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 250, "CR", "CASHBACK FLEET CARD")["id"])
    bank.link(ctx, cb, "CASHBACK", [{"type": "FUEL", "id": f1["id"], "amount": 250}])
    assert cb.classification == "CASHBACK"  # default credit type for CASHBACK link, never contract income
    row = prof_row(reports.profitability(ctx.db, T - timedelta(days=30), T), "TN01AA0001")
    assert row["contract_income"] == 0 and row["other_income"] == Decimal("250.00")  # CASHBACK type → other income
    # re-classify as fuel-card cashback (expense reduction) → reduces fuel cost instead
    bank.classify(ctx, cb, {"credit_type_id": fleet.ct["FUEL_CASHBACK"]})
    row = prof_row(reports.profitability(ctx.db, T - timedelta(days=30), T), "TN01AA0001")
    assert row["fuel"] == Decimal("8750.00") and row["other_income"] == 0


def test_internal_transfer_matching_is_neither_income_nor_expense(ctx, fleet):
    d = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 500000, "DR", "TRF TO SBI SELF", T - timedelta(days=4), "UTR1")["id"])
    c = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc2.id, 500000, "CR", "BY TRANSFER HDFC", T - timedelta(days=4), "UTR1")["id"])
    sug = bank.suggest(ctx.db, d)["candidates"]
    assert sug and sug[0]["type"] == "BANK" and sug[0]["id"] == c.id and "same UTR" in sug[0]["reasons"]
    bank.link(ctx, d, "INTERNAL_TRANSFER", [{"type": "BANK", "id": c.id, "amount": 500000}])
    assert (d.recon_status, c.recon_status) == ("MATCHED", "MATCHED")
    assert d.classification == c.classification == "INTERNAL_TRANSFER"
    res = reports.profitability(ctx.db, T - timedelta(days=30), T)
    assert not res["totals"] or res["totals"]["total_cost"] == 0 and res["totals"]["total_income"] == 0
    with pytest.raises(BusinessError):  # same-account "transfer" rejected
        x = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 100, "DR", "X")["id"])
        y = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 100, "CR", "Y")["id"])
        bank.link(ctx, x, "INTERNAL_TRANSFER", [{"type": "BANK", "id": y.id, "amount": 100}])


# ───────────────────────── unmatched + allocation ─────────────────────────
def test_unmatched_credit_is_not_income_and_unmatched_debit_stays_pending(ctx, fleet):
    c = bank_txn(ctx, fleet.acc1.id, 7777, "CR", "NEFT UNKNOWN PARTY")
    d = bank_txn(ctx, fleet.acc1.id, 3333, "DR", "UNKNOWN DEBIT")
    assert (c["recon_status"], c["classification"]) == ("UNMATCHED", "UNCLASSIFIED")
    assert d["recon_status"] == "UNMATCHED"
    bank.auto_suggest(ctx, [c["id"], d["id"]])
    assert ctx.db.get(BankTransaction, d["id"]).recon_status == "UNMATCHED"  # never randomly allocated
    res = reports.profitability(ctx.db, T - timedelta(days=30), T)
    assert sum(r["total_income"] for r in res["rows"]) == 0 and sum(r["total_cost"] for r in res["rows"]) == 0


def test_multi_cost_center_allocation(ctx, fleet):
    t = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 100000, "DR", "COMMON VENDOR BILL")["id"])
    et = fleet.et["VENDOR"]
    bank.allocate(ctx, t, [{"cost_center_id": fleet.v.lpg["cost_center_id"], "amount": 40000, "expense_type_id": et},
                           {"cost_center_id": fleet.v.open["cost_center_id"], "amount": 30000, "expense_type_id": et},
                           {"cost_center_id": fleet.cc["CC-WORKSHOP"], "amount": 20000, "expense_type_id": et},
                           {"cost_center_id": fleet.cc["CC-COMMON"], "amount": 10000, "expense_type_id": et}])
    assert t.recon_status == "ALLOCATED" and t.unmatched_amount == 0
    lines = ctx.db.execute(select(BankTransactionAllocation).where(BankTransactionAllocation.bank_transaction_id == t.id)).scalars().all()
    assert sorted(l.amount for l in lines) == [Decimal("10000.00"), Decimal("20000.00"), Decimal("30000.00"), Decimal("40000.00")]
    assert prof_row(reports.profitability(ctx.db, T - timedelta(days=30), T), "TN01AA0001")["other_direct"] == Decimal("40000.00")


def test_over_allocation_and_unbalanced_allocation_prevented(ctx, fleet):
    t = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 1000, "DR", "X")["id"])
    line = lambda a: {"cost_center_id": fleet.cc["CC-ADMIN"], "amount": a, "expense_type_id": fleet.et["OFFICE"]}  # noqa: E731
    with pytest.raises(BusinessError) as e:
        bank.allocate(ctx, t, [line(600), line(401)])
    assert e.value.code == "OVER_ALLOCATION"
    with pytest.raises(BusinessError) as e:
        bank.allocate(ctx, t, [line(600)])
    assert e.value.code == "ALLOCATION_MISMATCH"
    assert ctx.db.execute(select(func.count()).select_from(BankTransactionAllocation).where(
        BankTransactionAllocation.bank_transaction_id == t.id)).scalar_one() == 0  # nothing partially saved
    from app.services.rules import set_rule
    set_rule(ctx.db, "BANK_ALLOW_PARTIAL_ALLOCATION", "true")
    bank.allocate(ctx, t, [line(600)], allow_partial=True)
    assert t.recon_status == "PARTIALLY_MATCHED" and t.unmatched_amount == Decimal("400.00")
    with pytest.raises(BusinessError):
        bank.link(ctx, t, "OTHER", [{"type": "EXPENSE", "id": 1, "amount": 500}])


def test_reverse_and_unlink_are_audited(ctx, fleet):
    t = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 500, "DR", "X")["id"])
    [a] = bank.allocate(ctx, t, [{"cost_center_id": fleet.cc["CC-ADMIN"], "amount": 500, "expense_type_id": fleet.et["OFFICE"]}])
    bank.reverse_allocation(ctx, a.id, "Wrong cost center")
    assert t.recon_status == "UNMATCHED"
    acts = [h.action for h in ctx.db.execute(select(ReconciliationHistory).where(ReconciliationHistory.bank_transaction_id == t.id))
            .scalars()]
    assert "ALLOCATE" in acts and "REVERSE_ALLOCATION" in acts
    assert ctx.db.execute(select(AuditLog).where(AuditLog.action == "REVERSE")).first()


# ───────────────────────── no double counting ─────────────────────────
def test_no_double_counting_fuel_and_toll(ctx, fleet):
    f1 = fuel_txn(ctx, fleet, fleet.v.lpg, "DIESEL", 500, 100)  # ₹50,000
    toll = masters.save_record(ctx, masters.get_spec("toll_transactions"), {
        "provider_id": fleet.prov["TOLL_A"], "txn_date": dmy(T - timedelta(days=2)), "vehicle_id": fleet.v.lpg["id"], "amount": "10000"})
    p1 = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 50000, "DR", "IOCL SETTLEMENT")["id"])
    p2 = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 10000, "DR", "FASTAG")["id"])
    bank.link(ctx, p1, "FUEL_PAYMENT", [{"type": "FUEL", "id": f1["id"], "amount": 50000}])
    bank.link(ctx, p2, "TOLL_PAYMENT", [{"type": "TOLL", "id": toll["id"], "amount": 10000}])
    row = prof_row(reports.profitability(ctx.db, T - timedelta(days=30), T), "TN01AA0001")
    assert row["fuel"] == Decimal("50000.00") and row["toll"] == Decimal("10000.00")
    assert row["total_cost"] == Decimal("60000.00")
    with pytest.raises(BusinessError):  # the same fuel bill cannot be settled twice
        p3 = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 50000, "DR", "IOCL AGAIN")["id"])
        bank.link(ctx, p3, "FUEL_PAYMENT", [{"type": "FUEL", "id": f1["id"], "amount": 50000}])


# ───────────────────────── suggestions & approvals ─────────────────────────
def test_suggestions_never_become_final_without_acceptance(ctx, fleet):
    inv = make_invoice(ctx, fleet, "GAS-777", 25000, [(fleet.v.lpg["id"], 25000)])
    t = ctx.db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 25000, "CR", "NEFT SOUTHERN GAS GAS-777")["id"])
    res = bank.auto_suggest(ctx, [t.id])
    assert res == {"suggested": 1, "auto_matched": 0}
    assert t.recon_status == "AUTO_SUGGESTED" and ctx.db.get(Invoice, inv["id"]).status == "OPEN"
    ln = ctx.db.execute(select(FinancialTransactionLink).where(FinancialTransactionLink.source_transaction_id == t.id)).scalar_one()
    bank.accept_suggestion(ctx, ln.id)
    assert t.recon_status == "MATCHED" and ctx.db.get(Invoice, inv["id"]).status == "PAID"


def test_large_allocation_requires_approval(ctx, fleet, db):
    from app.core.security import hash_password, load_user
    from app.models.system import Role, User
    from app.services.masters import Ctx
    fin = User(username="fin", full_name="Finance User", password_hash=hash_password("Finance123"))
    fin.roles = [db.execute(select(Role).where(Role.code == "FINANCE")).scalar_one()]
    db.add(fin)
    db.flush()
    fctx = Ctx(db, load_user(db, fin.id))
    t = db.get(BankTransaction, bank_txn(ctx, fleet.acc1.id, 600000, "DR", "BIG PAYMENT")["id"])
    bank.allocate(fctx, t, [{"cost_center_id": fleet.cc["CC-COMMON"], "amount": 600000, "expense_type_id": fleet.et["OFFICE"]}])
    assert t.recon_status == "PENDING_APPROVAL"
    req = db.execute(select(ApprovalRequest).where(ApprovalRequest.entity_id == t.id)).scalar_one()
    with pytest.raises(PermissionDenied):
        approvals.decide(db, fctx.user, req.id, True)  # finance role cannot approve its own request
    approvals.decide(db, ctx.user, req.id, True, "ok")
    assert req.status == "APPROVED" and t.recon_status == "ALLOCATED"
