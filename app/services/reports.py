"""Report engine (spec §36, §40, §41, §55, §64).

Operating cost comes ONLY from operational records (fuel, toll, maintenance,
tyres, insurance, renewals, expense transactions) plus bank amounts that were
*directly allocated* to cost centers (debits without an underlying operational
record).  Bank rows linked to operational records are settlements and are
never counted again.  Linked refunds/cashbacks reduce cost or count as other
income according to configuration.  Income is recognised from invoices (or
receipts, if configured) — unclassified bank credits are never income.

Aggregation happens in SQL (grouped by cost center, report group and day) so
millions of rows are reduced before reaching Python.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Callable

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.utils import fmt_date, money, parse_date, today
from app.models.compliance import InsurancePolicy, RenewalType, VehicleRenewal
from app.models.finance import (BankTransaction, BankTransactionAllocation, CreditType, ExpenseAllocation,
                                ExpenseTransaction, ExpenseType, FinancialTransactionLink, Invoice, InvoiceAllocation)
from app.models.fleet import (CostCategory, CostCenter, OdometerReading, Vehicle, VehicleCostCenterHistory,
                              VehicleSubCategory)
from app.models.operations import FuelTransaction, MaintenanceJobCard, TollTransaction
from app.models.tyres import Tyre, TyreFitment, TyreMaintenance, TyreMovement, TyreRetreading, TyreWarrantyClaim
from app.services.rules import rule

ZERO = Decimal("0")
GROUPS = ["FUEL", "TOLL", "MAINTENANCE", "TYRE", "INSURANCE", "TAX", "PERMIT", "PESO", "DRIVER", "OTHER_DIRECT"]
_GROUP_ALIAS = {"REPAIR": "MAINTENANCE", "VENDOR": "OTHER_DIRECT", "BANK_CHARGE": "OTHER_DIRECT", "COMMON": "OTHER_DIRECT",
                "HAZMAT": "PESO", "FITNESS": "PERMIT", "PUCC": "OTHER_DIRECT", "REGISTRATION": "TAX",
                "LICENSE": "DRIVER", "OTHER": "OTHER_DIRECT"}


def _grp(code: str | None) -> str:
    c = (code or "OTHER_DIRECT").upper()
    c = _GROUP_ALIAS.get(c, c)
    return c if c in GROUPS else "OTHER_DIRECT"


@dataclass
class Line:
    day: date
    cc: int | None
    group: str
    amount: Decimal
    kind: str = "EXPENSE"  # EXPENSE | INCOME | OTHER_INCOME
    source: str = ""


def _amortize(amount, start: date | None, end: date | None, p_start: date, p_end: date) -> Decimal:
    """Portion of a period cost (insurance premium, permit fee …) falling inside the report period."""
    if not amount or not start:
        return ZERO
    end = end or start
    if end < p_start or start > p_end:
        return ZERO
    total_days = (end - start).days + 1
    overlap = (min(end, p_end) - max(start, p_start)).days + 1
    return money(Decimal(amount) * overlap / total_days)


def ledger(db: Session, start: date, end: date) -> list[Line]:
    inc_tax = rule(db, "EXPENSE_INCLUDE_TAX")
    lines: list[Line] = []
    dt_end = datetime.combine(end, time.max)
    # fuel
    amt = FuelTransaction.total_amount if inc_tax else (FuelTransaction.amount - FuelTransaction.discount_amount)
    for cc, d, s in db.execute(select(FuelTransaction.cost_center_id, FuelTransaction.txn_date, func.sum(amt)).where(
            FuelTransaction.txn_date.between(start, end), FuelTransaction.status != "CANCELLED")
            .group_by(FuelTransaction.cost_center_id, FuelTransaction.txn_date)).all():
        lines.append(Line(d, cc, "FUEL", money(s), source="fuel"))
    # toll (refunds net off, recharges are wallet top-ups — not cost)
    signed = case((TollTransaction.txn_kind == "REFUND", -TollTransaction.amount), else_=TollTransaction.amount)
    for cc, d, s in db.execute(select(TollTransaction.cost_center_id, TollTransaction.txn_date, func.sum(signed)).where(
            TollTransaction.txn_date.between(start, end), TollTransaction.txn_kind != "RECHARGE",
            TollTransaction.status.notin_(["DUPLICATE", "ERROR"]))
            .group_by(TollTransaction.cost_center_id, TollTransaction.txn_date)).all():
        lines.append(Line(d, cc, "TOLL", money(s), source="toll"))
    # maintenance
    m_amt = MaintenanceJobCard.total_amount if inc_tax else MaintenanceJobCard.amount
    for cc, d, s in db.execute(select(MaintenanceJobCard.cost_center_id, MaintenanceJobCard.job_date, func.sum(m_amt))
                               .where(MaintenanceJobCard.job_date.between(start, end),
                                      MaintenanceJobCard.status != "CANCELLED")
                               .group_by(MaintenanceJobCard.cost_center_id, MaintenanceJobCard.job_date)).all():
        lines.append(Line(d, cc, "MAINTENANCE", money(s), source="maintenance"))
    lines += _tyre_lines(db, start, end, inc_tax)
    # insurance premiums amortised over the policy period
    for p in db.execute(select(InsurancePolicy).where(InsurancePolicy.start_date <= end,
                                                      InsurancePolicy.expiry_date >= start,
                                                      InsurancePolicy.renewal_status != "CANCELLED")).scalars():
        a = _amortize(p.total_premium if inc_tax else p.premium, p.start_date, p.expiry_date, start, end)
        if a:
            lines.append(Line(max(p.start_date, start), p.cost_center_id, "INSURANCE", a, source="insurance"))
    # tax / permit / PESO / fitness … amortised over validity
    for r, rt, eg in db.execute(select(VehicleRenewal, RenewalType, ExpenseType.report_group).join(
            RenewalType, RenewalType.id == VehicleRenewal.renewal_type_id).outerjoin(
            ExpenseType, ExpenseType.id == RenewalType.expense_type_id).where(
            VehicleRenewal.amount.is_not(None), VehicleRenewal.status != "CANCELLED",
            func.coalesce(VehicleRenewal.start_date, VehicleRenewal.issue_date, VehicleRenewal.renewal_date) <= end,
            func.coalesce(VehicleRenewal.expiry_date, VehicleRenewal.renewal_date) >= start)).all():
        s0 = r.start_date or r.issue_date or r.renewal_date
        a = _amortize(r.total_amount if inc_tax else r.amount, s0, r.expiry_date, start, end)
        if a:
            lines.append(Line(max(s0, start), r.cost_center_id, _grp(eg or rt.category), a, source="renewal"))
    # generic operational expenses (allocated lines win over header cost center)
    has_alloc = select(ExpenseAllocation.expense_id)
    for cc, d, g, s in db.execute(select(ExpenseTransaction.cost_center_id, ExpenseTransaction.expense_date,
                                         ExpenseType.report_group, func.sum(ExpenseTransaction.amount)).join(
            ExpenseType, ExpenseType.id == ExpenseTransaction.expense_type_id).where(
            ExpenseTransaction.expense_date.between(start, end), ExpenseTransaction.status != "CANCELLED",
            ExpenseType.is_operating.is_(True), ExpenseTransaction.id.notin_(has_alloc))
            .group_by(ExpenseTransaction.cost_center_id, ExpenseTransaction.expense_date, ExpenseType.report_group)).all():
        lines.append(Line(d, cc, _grp(g), money(s), source="expense"))
    for cc, d, g, s in db.execute(select(ExpenseAllocation.cost_center_id, ExpenseTransaction.expense_date,
                                         ExpenseType.report_group, func.sum(ExpenseAllocation.amount)).join(
            ExpenseTransaction, ExpenseTransaction.id == ExpenseAllocation.expense_id).join(
            ExpenseType, ExpenseType.id == ExpenseTransaction.expense_type_id).where(
            ExpenseTransaction.expense_date.between(start, end), ExpenseTransaction.status != "CANCELLED",
            ExpenseType.is_operating.is_(True))
            .group_by(ExpenseAllocation.cost_center_id, ExpenseTransaction.expense_date, ExpenseType.report_group)).all():
        lines.append(Line(d, cc, _grp(g), money(s), source="expense"))
    # bank debits allocated directly (no operational record behind them)
    for cc, d, g, s in db.execute(select(BankTransactionAllocation.cost_center_id, BankTransaction.txn_date,
                                         ExpenseType.report_group, func.sum(BankTransactionAllocation.amount)).join(
            BankTransaction, BankTransaction.id == BankTransactionAllocation.bank_transaction_id).join(
            ExpenseType, ExpenseType.id == BankTransactionAllocation.expense_type_id).where(
            BankTransaction.direction == "DR", BankTransactionAllocation.status == "ACTIVE",
            BankTransaction.txn_date.between(start, end), ExpenseType.is_operating.is_(True))
            .group_by(BankTransactionAllocation.cost_center_id, BankTransaction.txn_date, ExpenseType.report_group)).all():
        lines.append(Line(d, cc, _grp(g), money(s), source="bank_allocation"))
    # bank credits allocated with a credit type
    for cc, d, treat, g, s in db.execute(select(
            BankTransactionAllocation.cost_center_id, BankTransaction.txn_date, CreditType.accounting_treatment,
            ExpenseType.report_group, func.sum(BankTransactionAllocation.amount)).join(
            BankTransaction, BankTransaction.id == BankTransactionAllocation.bank_transaction_id).join(
            CreditType, CreditType.id == BankTransactionAllocation.credit_type_id).outerjoin(
            ExpenseType, ExpenseType.id == BankTransactionAllocation.expense_type_id).where(
            BankTransaction.direction == "CR", BankTransactionAllocation.status == "ACTIVE",
            BankTransaction.txn_date.between(start, end))
            .group_by(BankTransactionAllocation.cost_center_id, BankTransaction.txn_date, CreditType.accounting_treatment,
                      ExpenseType.report_group)).all():
        if treat in ("OPERATING_INCOME", "OTHER_INCOME"):
            lines.append(Line(d, cc, "OTHER_INCOME", money(s), "OTHER_INCOME", "bank_credit"))
        elif treat == "EXPENSE_REDUCTION":
            lines.append(Line(d, cc, _grp(g), -money(s), source="bank_credit"))
    lines += _refund_lines(db, start, end)
    lines += _income_lines(db, start, end)
    return lines


def _tyre_lines(db: Session, start: date, end: date, inc_tax: bool) -> list[Line]:
    """Tyre cost is charged to the vehicle on which the tyre is (re)installed:
    purchase cost at first installation, retreading cost at the first installation
    after the retread, repairs on the repair date, warranty credit / scrap value
    to the last vehicle on resolution/scrap date."""
    from app.services.vehicles import cost_center_for
    out: list[Line] = []
    ds, de = datetime.combine(start, time.min), datetime.combine(end, time.max)
    for m in db.execute(select(TyreMovement).where(TyreMovement.movement_type.in_(["INSTALL", "TRANSFER"]),
                                                   TyreMovement.movement_date.between(ds, de))
                        .order_by(TyreMovement.movement_date)).scalars():
        if m.movement_type != "INSTALL":
            continue
        t = db.get(Tyre, m.tyre_id)
        prev = db.execute(select(TyreMovement).where(
            TyreMovement.tyre_id == m.tyre_id, TyreMovement.id != m.id,
            TyreMovement.movement_type.in_(["INSTALL", "RECEIVE_RETREAD"]),
            or_(TyreMovement.movement_date < m.movement_date,
                and_(TyreMovement.movement_date == m.movement_date, TyreMovement.id < m.id)))
            .order_by(TyreMovement.movement_date.desc(), TyreMovement.id.desc())).scalars().first()
        cc = cost_center_for(db, m.to_vehicle_id, m.movement_date.date())
        if prev is None:  # first ever installation → purchase cost
            amt = money(t.cost) + (money(t.gst_amount) if inc_tax else ZERO) - money(t.discount_amount)
            out.append(Line(m.movement_date.date(), cc, "TYRE", amt, source="tyre_purchase"))
        elif prev.movement_type == "RECEIVE_RETREAD":
            r = db.execute(select(TyreRetreading).where(TyreRetreading.tyre_id == t.id,
                                                        TyreRetreading.status == "RETURNED",
                                                        TyreRetreading.return_date <= m.movement_date.date())
                           .order_by(TyreRetreading.return_date.desc())).scalars().first()
            if r and r.cost:
                out.append(Line(m.movement_date.date(), cc, "TYRE",
                                money(r.cost) + (money(r.gst_amount) if inc_tax else ZERO), source="tyre_retread"))
    tm_amt = TyreMaintenance.cost + (TyreMaintenance.gst_amount if inc_tax else 0)
    for vid, d, s in db.execute(select(TyreMaintenance.vehicle_id, TyreMaintenance.maintenance_date, func.sum(tm_amt))
                                .where(TyreMaintenance.maintenance_date.between(start, end))
                                .group_by(TyreMaintenance.vehicle_id, TyreMaintenance.maintenance_date)).all():
        out.append(Line(d, cost_center_for(db, vid, d) if vid else None, "TYRE", money(s), source="tyre_repair"))

    def last_vehicle(tid):
        f = db.execute(select(TyreFitment).where(TyreFitment.tyre_id == tid).order_by(TyreFitment.installed_at.desc())
                       ).scalars().first()
        return f.vehicle_id if f else None

    if rule(db, "TYRE_COST_DEDUCT_WARRANTY"):
        for c in db.execute(select(TyreWarrantyClaim).where(TyreWarrantyClaim.status.in_(["APPROVED", "SETTLED"]),
                                                            TyreWarrantyClaim.resolution_date.between(start, end))).scalars():
            vid = last_vehicle(c.tyre_id)
            out.append(Line(c.resolution_date, cost_center_for(db, vid, c.resolution_date) if vid else None, "TYRE",
                            -money(c.approved_amount), source="tyre_warranty"))
    if rule(db, "TYRE_COST_DEDUCT_SCRAP"):
        for t in db.execute(select(Tyre).where(Tyre.scrap_date.between(start, end), Tyre.scrap_value.is_not(None))
                            ).scalars():
            vid = last_vehicle(t.id)
            out.append(Line(t.scrap_date, cost_center_for(db, vid, t.scrap_date) if vid else None, "TYRE",
                            -money(t.scrap_value), source="tyre_scrap"))
    return out


def _refund_lines(db: Session, start: date, end: date) -> list[Line]:
    from app.services.bank import TARGETS
    as_income = rule(db, "REFUND_TREATMENT") == "OTHER_INCOME"
    out = []
    q = select(FinancialTransactionLink, BankTransaction, CreditType.accounting_treatment).join(
        BankTransaction, and_(FinancialTransactionLink.source_transaction_type == "BANK",
                              BankTransaction.id == FinancialTransactionLink.source_transaction_id)).outerjoin(
        CreditType, CreditType.id == BankTransaction.credit_type_id).where(
        FinancialTransactionLink.link_type.in_(["REFUND", "CASHBACK", "REBATE"]),
        FinancialTransactionLink.match_status == "MATCHED", BankTransaction.txn_date.between(start, end))
    for ln, bt, treat in db.execute(q).all():
        income = as_income if ln.link_type == "REFUND" else (treat != "EXPENSE_REDUCTION")
        parts: list[tuple[int | None, str, Decimal]] = []
        ttype = ln.target_transaction_type
        if ttype == "BANK":
            allocs = db.execute(select(BankTransactionAllocation, ExpenseType.report_group).outerjoin(
                ExpenseType, ExpenseType.id == BankTransactionAllocation.expense_type_id).where(
                BankTransactionAllocation.bank_transaction_id == ln.target_transaction_id,
                BankTransactionAllocation.status == "ACTIVE")).all()
            tot = sum((a.amount for a, _ in allocs), ZERO)
            for a, g in allocs:
                parts.append((a.cost_center_id, _grp(g), money(ln.linked_amount * a.amount / tot)))
            if not allocs:
                parts.append((None, "OTHER_DIRECT", money(ln.linked_amount)))
        else:
            obj = db.get(TARGETS[ttype].model, ln.target_transaction_id)
            grp = {"FUEL": "FUEL", "TOLL": "TOLL", "MAINTENANCE": "MAINTENANCE", "TYRE": "TYRE", "TYRE_RETREAD": "TYRE",
                   "INSURANCE": "INSURANCE", "RENEWAL": "TAX", "EXPENSE": "OTHER_DIRECT"}.get(ttype, "OTHER_DIRECT")
            cc = getattr(obj, "cost_center_id", None) if obj else None
            if cc is None and obj is not None and getattr(obj, "vehicle_id", None):
                from app.services.vehicles import cost_center_for
                cc = cost_center_for(db, obj.vehicle_id, bt.txn_date)
            parts.append((cc, grp, money(ln.linked_amount)))
        for cc, g, a in parts:
            out.append(Line(bt.txn_date, cc, "OTHER_INCOME" if income else g, a if income else -a,
                            "OTHER_INCOME" if income else "EXPENSE", f"bank_{ln.link_type.lower()}"))
    return out


def _income_lines(db: Session, start: date, end: date) -> list[Line]:
    out = []
    if rule(db, "INCOME_RECOGNITION") == "RECEIPT":
        q = select(FinancialTransactionLink, BankTransaction).join(BankTransaction, and_(
            FinancialTransactionLink.source_transaction_type == "BANK",
            BankTransaction.id == FinancialTransactionLink.source_transaction_id)).where(
            FinancialTransactionLink.link_type == "INVOICE_RECEIPT", FinancialTransactionLink.match_status == "MATCHED",
            BankTransaction.txn_date.between(start, end))
        for ln, bt in db.execute(q).all():
            inv = db.get(Invoice, ln.target_transaction_id)
            ratio = Decimal(ln.linked_amount) / Decimal(inv.total_amount) if inv.total_amount else ZERO
            for a in db.execute(select(InvoiceAllocation).where(InvoiceAllocation.invoice_id == inv.id)).scalars():
                out.append(Line(bt.txn_date, a.cost_center_id, "INCOME", money(a.amount * ratio), "INCOME", "receipt"))
        return out
    sign = case((Invoice.invoice_type == "CREDIT_NOTE", -InvoiceAllocation.amount), else_=InvoiceAllocation.amount)
    for cc, d, s in db.execute(select(InvoiceAllocation.cost_center_id, Invoice.invoice_date, func.sum(sign)).join(
            Invoice, Invoice.id == InvoiceAllocation.invoice_id).where(
            Invoice.invoice_date.between(start, end), Invoice.status != "CANCELLED", Invoice.invoice_type != "ADVANCE")
            .group_by(InvoiceAllocation.cost_center_id, Invoice.invoice_date)).all():
        out.append(Line(d, cc, "INCOME", money(s), "INCOME", "invoice"))
    return out


# ───────────────────────── km ─────────────────────────
def km_in_period(db: Session, vehicle_id: int, start: date, end: date) -> Decimal:
    ds, de = datetime.combine(start, time.min), datetime.combine(end, time.max)
    first_before = db.execute(select(OdometerReading.reading).where(
        OdometerReading.vehicle_id == vehicle_id, OdometerReading.reading_at < ds)
        .order_by(OdometerReading.reading_at.desc())).scalars().first()
    inside = db.execute(select(func.min(OdometerReading.reading), func.max(OdometerReading.reading)).where(
        OdometerReading.vehicle_id == vehicle_id, OdometerReading.reading_at.between(ds, de))).one()
    lo = first_before if first_before is not None else inside[0]
    hi = inside[1]
    if lo is None or hi is None or hi < lo:
        return ZERO
    return Decimal(hi) - Decimal(lo)


# ───────────────────────── profitability ─────────────────────────
def profitability(db: Session, start: date, end: date, cc_type: str | None = None, branch_id: int | None = None,
                  cost_category_id: int | None = None, sub_category_id: int | None = None,
                  vehicle_id: int | None = None) -> dict:
    lines = ledger(db, start, end)
    agg: dict[int | None, dict] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for l in lines:
        key = "income" if l.kind == "INCOME" else "other_income" if l.kind == "OTHER_INCOME" else l.group
        agg[l.cc][key] += l.amount
    ccs = {c.id: c for c in db.execute(select(CostCenter)).scalars()}
    # distribute COMMON cost centers' costs to vehicle cost centers (configurable basis)
    basis = rule(db, "COMMON_COST_ALLOCATION_BASIS")
    vehicle_ccs = [c for c in ccs.values() if c.cc_type == "VEHICLE" and c.is_active]
    km_cache = {c.id: km_in_period(db, c.vehicle_id, start, end) if c.vehicle_id else ZERO for c in vehicle_ccs}
    if basis != "NONE" and vehicle_ccs:
        common_ids = [cid for cid, c in ccs.items() if c.cc_type == "COMMON"]
        pool = sum((sum((v for k, v in agg[cid].items() if k in GROUPS), ZERO) for cid in common_ids), ZERO)
        weights = {c.id: Decimal(1) for c in vehicle_ccs}
        if basis == "KM":
            weights = dict(km_cache)
        elif basis == "REVENUE":
            weights = {c.id: max(agg[c.id]["income"], ZERO) for c in vehicle_ccs}
        wsum = sum(weights.values(), ZERO)
        if pool and wsum:
            for cid, w in weights.items():
                agg[cid]["allocated_common"] += money(pool * w / wsum)
            for cid in common_ids:
                agg[cid]["allocated_out"] = -sum((v for k, v in agg[cid].items() if k in GROUPS), ZERO)
    rows = []
    hist_cache: dict = {}
    for cid in set(agg) | {c.id for c in vehicle_ccs}:
        c = ccs.get(cid)
        if cc_type and (not c or c.cc_type != cc_type):
            continue
        if branch_id and (not c or c.branch_id != branch_id):
            continue
        v = db.get(Vehicle, c.vehicle_id) if c and c.vehicle_id else None
        if vehicle_id and (not v or v.id != vehicle_id):
            continue
        cat = sub = None
        if v:
            h = _class_at(db, v.id, end, hist_cache)
            cat, sub = (h.new_cost_category_id, h.new_sub_category_id) if h else (v.cost_category_id, v.sub_category_id)
        elif c:
            cat = c.cost_category_id
        if cost_category_id and cat != cost_category_id:
            continue
        if sub_category_id and sub != sub_category_id:
            continue
        a = agg[cid]
        direct = sum((a[g] for g in GROUPS), ZERO)
        total_cost = direct + a["allocated_common"] + a["allocated_out"]
        income = a["income"] + a["other_income"]
        km = km_cache.get(cid) if cid in km_cache else (km_in_period(db, v.id, start, end) if v else ZERO)
        per = (lambda x: (x / km).quantize(Decimal("0.01")) if km else None)
        row = {"cost_center_id": cid, "cost_center": f"{c.code} — {c.name}" if c else "UNALLOCATED / PENDING REVIEW",
               "cc_type": c.cc_type if c else "", "vehicle": v.registration_number if v else "",
               "category": _name(db, CostCategory, cat), "sub_category": _name(db, VehicleSubCategory, sub),
               "contract_income": a["income"], "other_income": a["other_income"],
               **{g.lower(): a[g] for g in GROUPS}, "allocated_common": a["allocated_common"] + a["allocated_out"],
               "total_income": income, "total_cost": total_cost, "net_contribution": income - total_cost, "km": km,
               "cost_per_km": per(total_cost), "fuel_per_km": per(a["FUEL"]), "toll_per_km": per(a["TOLL"]),
               "maintenance_per_km": per(a["MAINTENANCE"]), "tyre_per_km": per(a["TYRE"])}
        if c is None and not any(row[k] for k in ("total_income", "total_cost")):
            continue
        rows.append(row)
    rows.sort(key=lambda r: (r["cc_type"] != "VEHICLE", r["cost_center"]))
    totals = {k: sum((r[k] for r in rows if isinstance(r[k], Decimal)), ZERO) for k in rows[0]} if rows else {}
    return {"rows": rows, "totals": totals, "basis": basis}


def _class_at(db, vehicle_id, on, cache):
    key = (vehicle_id, on)
    if key not in cache:
        from app.services.vehicles import classification_at
        cache[key] = classification_at(db, vehicle_id, on)
    return cache[key]


def _name(db, M, i):
    if not i:
        return ""
    o = db.get(M, i)
    return o.name if o else ""


def category_costs(db: Session, start: date, end: date) -> list[dict]:
    """Cost & income by category/sub-category using the classification valid on each
    transaction date (history-aware, spec §55)."""
    ccs = {c.id: c for c in db.execute(select(CostCenter)).scalars()}
    hist: dict = {}
    agg: dict = defaultdict(lambda: defaultdict(lambda: ZERO))
    for l in ledger(db, start, end):
        c = ccs.get(l.cc)
        if c and c.vehicle_id:
            h = _class_at(db, c.vehicle_id, l.day, hist)
            key = (h.new_cost_category_id, h.new_sub_category_id) if h else (None, None)
        elif c:
            key = (c.cost_category_id, None)
        else:
            key = (None, None)
        col = "income" if l.kind in ("INCOME", "OTHER_INCOME") else "cost"
        agg[key][col] += l.amount
        if col == "cost":
            agg[key][l.group] += l.amount
    out = []
    for (cat, sub), a in agg.items():
        out.append({"category": _name(db, CostCategory, cat) or "(unclassified)",
                    "sub_category": _name(db, VehicleSubCategory, sub), "income": a["income"], "cost": a["cost"],
                    **{g.lower(): a[g] for g in GROUPS}, "net": a["income"] - a["cost"]})
    return sorted(out, key=lambda r: (r["category"], r["sub_category"]))


# ───────────────────────── tabular reports ─────────────────────────
@dataclass
class Report:
    key: str
    title: str
    group: str
    fn: Callable[[Session, dict], tuple[list[str], list[list]]]
    params: tuple[str, ...] = ("date_from", "date_to")
    permission: str = "report.view"


REPORTS: dict[str, Report] = {}


def report(key, title, group, params=("date_from", "date_to")):
    def deco(fn):
        REPORTS[key] = Report(key, title, group, fn, params)
        return fn
    return deco


def _period(p: dict) -> tuple[date, date]:
    end = parse_date(p.get("date_to")) or today()
    start = parse_date(p.get("date_from")) or end.replace(day=1)
    if start > end:
        from app.core.errors import BusinessError
        raise BusinessError("'From' date must be on or before 'To' date")
    return start, end


def _i(p, k):
    return int(p[k]) if p.get(k) else None


@report("profitability", "Vehicle Profitability / Cost Center", "Profitability",
        ("date_from", "date_to", "branch_id", "cost_category_id", "sub_category_id", "vehicle_id", "cc_type"))
def _r_profit(db, p):
    s, e = _period(p)
    res = profitability(db, s, e, p.get("cc_type") or None, _i(p, "branch_id"), _i(p, "cost_category_id"),
                        _i(p, "sub_category_id"), _i(p, "vehicle_id"))
    cols = ["Cost Center", "Type", "Vehicle", "Category", "Sub-category", "Contract Income", "Other Income", "Fuel",
            "Toll", "Maintenance", "Tyres", "Insurance", "Tax", "Permit", "PESO", "Driver", "Other Direct",
            "Allocated Common", "Total Income", "Total Cost", "Net Contribution", "KM", "Cost/KM", "Fuel/KM",
            "Toll/KM", "Maint/KM", "Tyre/KM"]
    keys = ["cost_center", "cc_type", "vehicle", "category", "sub_category", "contract_income", "other_income", "fuel",
            "toll", "maintenance", "tyre", "insurance", "tax", "permit", "peso", "driver", "other_direct",
            "allocated_common", "total_income", "total_cost", "net_contribution", "km", "cost_per_km", "fuel_per_km",
            "toll_per_km", "maintenance_per_km", "tyre_per_km"]
    rows = [[r[k] for k in keys] for r in res["rows"]]
    if res["totals"]:
        rows.append(["TOTAL", "", "", "", ""] + [res["totals"].get(k, "") for k in keys[5:22]] + [""] * 5)
    return cols, rows


@report("category_costs", "Category / Sub-category Cost (history-aware)", "Profitability")
def _r_cat(db, p):
    s, e = _period(p)
    rows = category_costs(db, s, e)
    keys = ["category", "sub_category", "income", "cost"] + [g.lower() for g in GROUPS] + ["net"]
    return [k.replace("_", " ").title() for k in keys], [[r[k] for k in keys] for r in rows]


@report("expense_ledger", "Expense & Income Ledger (daily, by source)", "Income & Expenses")
def _r_ledger(db, p):
    s, e = _period(p)
    ccs = {c.id: c.code for c in db.execute(select(CostCenter)).scalars()}
    rows = [[fmt_date(l.day), ccs.get(l.cc, "UNALLOCATED"), l.kind, l.group, l.source, l.amount]
            for l in sorted(ledger(db, s, e), key=lambda l: (l.day, l.cc or 0))]
    return ["Date", "Cost Center", "Kind", "Group", "Source", "Amount"], rows


@report("income", "Income by Invoice / Vehicle", "Income & Expenses", ("date_from", "date_to", "customer_id"))
def _r_income(db, p):
    from app.models.org import Customer
    s, e = _period(p)
    q = select(Invoice, InvoiceAllocation, Customer.name).join(InvoiceAllocation, InvoiceAllocation.invoice_id == Invoice.id
                                                               ).join(Customer, Customer.id == Invoice.customer_id).where(
        Invoice.invoice_date.between(s, e), Invoice.status != "CANCELLED")
    if p.get("customer_id"):
        q = q.where(Invoice.customer_id == int(p["customer_id"]))
    rows = []
    for inv, a, cust in db.execute(q.order_by(Invoice.invoice_date)).all():
        v = db.get(Vehicle, a.vehicle_id) if a.vehicle_id else None
        cc = db.get(CostCenter, a.cost_center_id)
        rows.append([fmt_date(inv.invoice_date), inv.invoice_number, inv.invoice_type, cust,
                     v.registration_number if v else "", cc.code if cc else "",
                     -a.amount if inv.invoice_type == "CREDIT_NOTE" else a.amount, inv.total_amount,
                     inv.received_amount, inv.outstanding_amount, inv.status])
    return ["Date", "Invoice", "Type", "Customer", "Vehicle", "Cost Center", "Allocated Income", "Invoice Total",
            "Received", "Outstanding", "Status"], rows


@report("receivables", "Contract Receivables & Ageing", "Income & Expenses", ("customer_id",))
def _r_recv(db, p):
    from app.services.contracts import receivables
    keys = ["customer", "invoices", "invoiced", "received", "outstanding", "on_account_receipts", "net_receivable",
            "0_30", "31_60", "61_90", "90_plus"]
    return ["Customer", "Invoices", "Invoiced", "Received", "Outstanding", "On-account", "Net Receivable", "0-30",
            "31-60", "61-90", "90+"], [[r[k] for k in keys] for r in receivables(db, _i(p, "customer_id"))]


@report("fuel_efficiency", "Fuel Efficiency (KM/L, KM/KG, KM/kWh)", "Fuel", ("date_from", "date_to", "vehicle_id"))
def _r_fe(db, p):
    from app.services.operations import fuel_efficiency_report
    s, e = _period(p)
    keys = ["vehicle", "fuel_type", "fills", "quantity", "amount", "km", "efficiency", "unit", "unusual_fills"]
    return ["Vehicle", "Fuel Type", "Fills", "Quantity", "Amount", "KM", "Efficiency", "Unit", "Unusual fills"], \
        [[r[k] for k in keys] for r in fuel_efficiency_report(db, s, e, _i(p, "vehicle_id"))]


@report("fuel_summary", "Fuel Cost by Vehicle / Fuel Type / Provider", "Fuel", ("date_from", "date_to", "provider_id"))
def _r_fuel(db, p):
    from app.models.fleet import FuelType
    from app.models.org import Provider
    s, e = _period(p)
    q = select(FuelTransaction.vehicle_id, FuelTransaction.fuel_type_id, FuelTransaction.provider_id, func.count(),
               func.sum(FuelTransaction.quantity), func.sum(FuelTransaction.amount),
               func.sum(FuelTransaction.total_amount)).where(FuelTransaction.txn_date.between(s, e),
                                                             FuelTransaction.status != "CANCELLED")
    if p.get("provider_id"):
        q = q.where(FuelTransaction.provider_id == int(p["provider_id"]))
    rows = []
    for vid, ft, pid, n, qty, amt, tot in db.execute(q.group_by(FuelTransaction.vehicle_id, FuelTransaction.fuel_type_id,
                                                                FuelTransaction.provider_id)).all():
        rows.append([(db.get(Vehicle, vid).registration_number if vid else "UNMATCHED"), _name(db, FuelType, ft),
                     _name(db, Provider, pid), n, qty, amt, tot])
    return ["Vehicle", "Fuel Type", "Provider", "Fills", "Quantity", "Amount", "Total"], rows


@report("toll_summary", "Toll Cost by Vehicle and Plaza", "Toll", ("date_from", "date_to", "provider_id"))
def _r_toll(db, p):
    from app.models.operations import TollPlaza
    s, e = _period(p)
    signed = case((TollTransaction.txn_kind == "REFUND", -TollTransaction.amount), else_=TollTransaction.amount)
    q = select(TollTransaction.vehicle_id, TollTransaction.toll_plaza_id, func.count(), func.sum(signed)).where(
        TollTransaction.txn_date.between(s, e), TollTransaction.txn_kind != "RECHARGE")
    if p.get("provider_id"):
        q = q.where(TollTransaction.provider_id == int(p["provider_id"]))
    rows = []
    for vid, pl, n, amt in db.execute(q.group_by(TollTransaction.vehicle_id, TollTransaction.toll_plaza_id)).all():
        rows.append([(db.get(Vehicle, vid).registration_number if vid else "UNMATCHED VEHICLE"),
                     _name(db, TollPlaza, pl) or "UNMATCHED PLAZA", n, amt])
    return ["Vehicle", "Plaza", "Crossings", "Amount"], rows


@report("toll_review", "Toll — Unmatched Vehicles / Plazas", "Toll", ())
def _r_toll_rev(db, p):
    rows = []
    for t in db.execute(select(TollTransaction).where(TollTransaction.status.in_(
            ["VEHICLE_UNMATCHED", "PLAZA_UNMATCHED", "VEHICLE_MATCHED"])).order_by(TollTransaction.txn_date.desc())
            .limit(5000)).scalars():
        rows.append([t.id, fmt_date(t.txn_date), t.transaction_id, t.registration_raw, t.plaza_name_raw or t.plaza_code_raw,
                     t.amount, t.status, t.source_file, t.source_row])
    return ["ID", "Date", "Txn ID", "Vehicle (raw)", "Plaza (raw)", "Amount", "Status", "File", "Row"], rows


@report("maintenance_summary", "Maintenance Cost by Vehicle / Type", "Maintenance", ("date_from", "date_to", "vehicle_id"))
def _r_maint(db, p):
    from app.models.operations import MaintenanceType
    s, e = _period(p)
    q = select(MaintenanceJobCard.vehicle_id, MaintenanceJobCard.maintenance_type_id, func.count(),
               func.sum(MaintenanceJobCard.parts_amount), func.sum(MaintenanceJobCard.labour_amount),
               func.sum(MaintenanceJobCard.total_amount), func.sum(MaintenanceJobCard.downtime_hours)).where(
        MaintenanceJobCard.job_date.between(s, e), MaintenanceJobCard.status != "CANCELLED")
    if p.get("vehicle_id"):
        q = q.where(MaintenanceJobCard.vehicle_id == int(p["vehicle_id"]))
    rows = [[db.get(Vehicle, vid).registration_number, _name(db, MaintenanceType, mt), n, pa, la, tot, dh]
            for vid, mt, n, pa, la, tot, dh in db.execute(q.group_by(MaintenanceJobCard.vehicle_id,
                                                                     MaintenanceJobCard.maintenance_type_id)).all()]
    return ["Vehicle", "Type", "Job Cards", "Parts", "Labour", "Total", "Downtime (h)"], rows


def _tyre_row(db, t: Tyre) -> list:
    from app.models.tyres import TyreLocation, TyrePosition
    v = db.get(Vehicle, t.current_vehicle_id) if t.current_vehicle_id else None
    pos = db.get(TyrePosition, t.current_position_id) if t.current_position_id else None
    loc = db.get(TyreLocation, t.current_location_id) if t.current_location_id else None
    return [t.serial_number, t.brand, t.model, t.size, t.current_status, v.registration_number if v else "",
            pos.code if pos else "", loc.name if loc else "", t.current_tread_depth, t.total_km, t.retread_count,
            fmt_date(t.purchase_date), t.total_cost]


_TYRE_COLS = ["Serial", "Brand", "Model", "Size", "Status", "Vehicle", "Position", "Location", "Tread (mm)", "Total KM",
              "Retreads", "Purchased", "Cost"]


@report("tyre_master", "Tyre Master / Stock / Installed", "Tyres", ("status", "brand", "size", "vehicle_id"))
def _r_tyres(db, p):
    q = select(Tyre).where(Tyre.is_active.is_(True))
    if p.get("status"):
        q = q.where(Tyre.current_status.in_(p["status"].split(",")))
    for k in ("brand", "size"):
        if p.get(k):
            q = q.where(getattr(Tyre, k) == p[k])
    if p.get("vehicle_id"):
        q = q.where(Tyre.current_vehicle_id == int(p["vehicle_id"]))
    return _TYRE_COLS, [_tyre_row(db, t) for t in db.execute(q.order_by(Tyre.serial_number)).scalars()]


@report("tyre_stock", "Tyre Stock by Location / Status", "Tyres", ())
def _r_tyre_stock(db, p):
    from app.models.tyres import TyreLocation
    rows = []
    for loc, st, brand, size, n in db.execute(select(Tyre.current_location_id, Tyre.current_status, Tyre.brand, Tyre.size,
                                                     func.count()).where(Tyre.current_vehicle_id.is_(None),
                                                                         Tyre.current_status.notin_(["SOLD", "LOST"]))
                                              .group_by(Tyre.current_location_id, Tyre.current_status, Tyre.brand,
                                                        Tyre.size)).all():
        rows.append([_name(db, TyreLocation, loc) or "-", st, brand, size, n])
    return ["Location", "Status", "Brand", "Size", "Count"], rows


@report("tyre_movements", "Tyre Movements / Transfers", "Tyres", ("date_from", "date_to", "movement_type"))
def _r_tyre_mov(db, p):
    s, e = _period(p)
    q = select(TyreMovement, Tyre.serial_number).join(Tyre, Tyre.id == TyreMovement.tyre_id).where(
        TyreMovement.movement_date.between(datetime.combine(s, time.min), datetime.combine(e, time.max)))
    if p.get("movement_type"):
        q = q.where(TyreMovement.movement_type == p["movement_type"])
    rows = []
    for m, serial in db.execute(q.order_by(TyreMovement.movement_date)).all():
        fv = db.get(Vehicle, m.from_vehicle_id) if m.from_vehicle_id else None
        tv = db.get(Vehicle, m.to_vehicle_id) if m.to_vehicle_id else None
        rows.append([fmt_date(m.movement_date), serial, m.movement_type, fv.registration_number if fv else "",
                     tv.registration_number if tv else "", m.odometer, m.to_odometer, m.running_km, m.tread_depth,
                     m.status_before, m.status_after, m.reason])
    return ["Date", "Tyre", "Movement", "From Vehicle", "To Vehicle", "Odometer", "To Odometer", "Running KM",
            "Tread", "Status Before", "Status After", "Reason"], rows


@report("tyre_cost", "Tyre Cost / Cost per KM / Tyre Life", "Tyres", ("brand", "size", "status"))
def _r_tyre_cost(db, p):
    from app.services.tyres import tyre_cost
    q = select(Tyre)
    for k in ("brand", "size"):
        if p.get(k):
            q = q.where(getattr(Tyre, k) == p[k])
    if p.get("status"):
        q = q.where(Tyre.current_status.in_(p["status"].split(",")))
    rows = []
    for t in db.execute(q.order_by(Tyre.brand, Tyre.serial_number)).scalars():
        c = tyre_cost(db, t)
        rows.append([t.serial_number, t.brand, t.model, t.size, t.current_status, t.retread_count, c["purchase"],
                     c["retreading"], c["repairs"], c["warranty_credit"], c["scrap_value"], c["net_cost"], c["km"],
                     c["cost_per_km"]])
    return ["Serial", "Brand", "Model", "Size", "Status", "Retreads", "Purchase", "Retreading", "Repairs",
            "Warranty Credit", "Scrap Value", "Net Cost", "KM", "Cost/KM"], rows


@report("tyre_brand", "Tyre Performance by Brand / Model / Size", "Tyres", ())
def _r_tyre_brand(db, p):
    rows = []
    for b, m, s, n, km, cost, rt in db.execute(select(Tyre.brand, Tyre.model, Tyre.size, func.count(), func.avg(Tyre.total_km),
                                                      func.avg(Tyre.total_cost), func.avg(Tyre.retread_count))
                                               .group_by(Tyre.brand, Tyre.model, Tyre.size)).all():
        rows.append([b, m, s, n, money(km or 0), money(cost or 0), money(rt or 0),
                     money(Decimal(cost) / Decimal(km)) if km and cost else None])
    return ["Brand", "Model", "Size", "Tyres", "Avg KM", "Avg Cost", "Avg Retreads", "Avg Cost/KM"], rows


@report("tyre_retreading", "Tyre Retreading Register", "Tyres", ("date_from", "date_to"))
def _r_retread(db, p):
    from app.models.org import Vendor
    s, e = _period(p)
    rows = [[fmt_date(r.sent_date), fmt_date(r.return_date), serial, _name(db, Vendor, r.vendor_id), r.retread_type,
             r.tread_depth, r.new_tread_depth, r.cost, r.status] for r, serial in db.execute(
        select(TyreRetreading, Tyre.serial_number).join(Tyre, Tyre.id == TyreRetreading.tyre_id).where(
            TyreRetreading.sent_date.between(s, e))).all()]
    return ["Sent", "Returned", "Tyre", "Vendor", "Type", "Tread Before", "Tread After", "Cost", "Status"], rows


@report("tyre_warranty", "Tyre Warranty Claims", "Tyres", ("date_from", "date_to"))
def _r_warranty(db, p):
    s, e = _period(p)
    rows = [[c.claim_number, fmt_date(c.claim_date), serial, c.failure_reason, c.km_at_failure, c.claim_amount,
             c.approved_amount, c.resolution_type, c.status, fmt_date(c.resolution_date)] for c, serial in db.execute(
        select(TyreWarrantyClaim, Tyre.serial_number).join(Tyre, Tyre.id == TyreWarrantyClaim.tyre_id).where(
            TyreWarrantyClaim.claim_date.between(s, e))).all()]
    return ["Claim", "Date", "Tyre", "Reason", "KM", "Claimed", "Approved", "Resolution", "Status", "Resolved"], rows


@report("tyre_inspection", "Tyre Inspections", "Tyres", ("date_from", "date_to"))
def _r_inspect(db, p):
    from app.models.tyres import TyreInspection
    s, e = _period(p)
    rows = [[fmt_date(i.inspection_date), serial, (db.get(Vehicle, i.vehicle_id).registration_number if i.vehicle_id else ""),
             i.odometer, i.tread_depth, i.pressure_psi, i.condition, i.damage, i.recommended_action, i.inspector]
            for i, serial in db.execute(select(TyreInspection, Tyre.serial_number).join(
                Tyre, Tyre.id == TyreInspection.tyre_id).where(TyreInspection.inspection_date.between(s, e))).all()]
    return ["Date", "Tyre", "Vehicle", "Odometer", "Tread", "Pressure", "Condition", "Damage", "Action", "Inspector"], rows


@report("tyre_scrap", "Scrapped / Sold / Lost Tyres (Tyre Life)", "Tyres", ("date_from", "date_to"))
def _r_scrap(db, p):
    s, e = _period(p)
    rows = [[t.serial_number, t.brand, t.size, t.current_status, fmt_date(t.scrap_date), t.scrap_reason, t.total_km,
             t.retread_count, t.total_cost, t.scrap_value] for t in db.execute(select(Tyre).where(
        Tyre.current_status.in_(["SCRAPPED", "SOLD", "LOST"]),
        or_(Tyre.scrap_date.is_(None), Tyre.scrap_date.between(s, e)))).scalars()]
    return ["Serial", "Brand", "Size", "Status", "Date", "Reason", "Life KM", "Retreads", "Cost", "Scrap Value"], rows


@report("compliance", "Compliance / Renewal Register", "Compliance", ("status", "category"))
def _r_comp(db, p):
    q = select(VehicleRenewal, RenewalType).join(RenewalType, RenewalType.id == VehicleRenewal.renewal_type_id).where(
        VehicleRenewal.is_current.is_(True))
    if p.get("status"):
        q = q.where(VehicleRenewal.status.in_(p["status"].split(",")))
    if p.get("category"):
        q = q.where(RenewalType.category == p["category"])
    from app.services.renewals import _entity_name
    rows = [[_entity_name(db, r.vehicle_id, r.driver_id), rt.name, r.certificate_number, fmt_date(r.start_date),
             fmt_date(r.expiry_date), (r.expiry_date - today()).days if r.expiry_date else "", r.status,
             r.payment_status, r.total_amount] for r, rt in db.execute(q.order_by(VehicleRenewal.expiry_date)).all()]
    for pol in db.execute(select(InsurancePolicy).where(InsurancePolicy.is_current.is_(True))).scalars():
        rows.append([_entity_name(db, pol.vehicle_id, pol.driver_id), f"Insurance {pol.policy_type}", pol.policy_number,
                     fmt_date(pol.start_date), fmt_date(pol.expiry_date), (pol.expiry_date - today()).days,
                     pol.renewal_status, pol.payment_status, pol.total_premium])
    return ["Vehicle/Driver", "Type", "Certificate/Policy", "Start", "Expiry", "Days Left", "Status", "Payment",
            "Amount"], rows


@report("bank_recon", "Bank Reconciliation Summary", "Finance", ("date_from", "date_to", "bank_account_id"))
def _r_recon(db, p):
    from app.models.org import BankAccount
    s, e = _period(p)
    q = select(BankTransaction.bank_account_id, BankTransaction.direction, BankTransaction.recon_status, func.count(),
               func.sum(BankTransaction.amount), func.sum(BankTransaction.unmatched_amount)).where(
        BankTransaction.txn_date.between(s, e), BankTransaction.status == "ACTIVE")
    if p.get("bank_account_id"):
        q = q.where(BankTransaction.bank_account_id == int(p["bank_account_id"]))
    rows = []
    for acct, d, st, n, amt, un in db.execute(q.group_by(BankTransaction.bank_account_id, BankTransaction.direction,
                                                         BankTransaction.recon_status)).all():
        a = db.get(BankAccount, acct)
        rows.append([a.code if a else acct, "Credit" if d == "CR" else "Debit", st, n, amt, un])
    return ["Account", "Direction", "Status", "Count", "Amount", "Unmatched Amount"], rows


@report("bank_unmatched", "Unmatched / Partially Matched Bank Transactions", "Finance", ("date_from", "date_to", "bank_account_id"))
def _r_unmatched(db, p):
    s, e = _period(p)
    q = select(BankTransaction).where(BankTransaction.txn_date.between(s, e), BankTransaction.status == "ACTIVE",
                                      BankTransaction.recon_status.in_(["UNMATCHED", "PARTIALLY_MATCHED",
                                                                        "AUTO_SUGGESTED", "PENDING_APPROVAL"]))
    if p.get("bank_account_id"):
        q = q.where(BankTransaction.bank_account_id == int(p["bank_account_id"]))
    rows = [[t.id, fmt_date(t.txn_date), t.direction, t.amount, t.unmatched_amount, t.narration, t.utr,
             t.classification, t.recon_status] for t in db.execute(q.order_by(BankTransaction.txn_date)).scalars()]
    return ["ID", "Date", "Dir", "Amount", "Unmatched", "Narration", "UTR", "Classification", "Status"], rows


@report("vendor_spend", "Vendor-wise Spend", "Income & Expenses", ("date_from", "date_to"))
def _r_vendor(db, p):
    from app.models.org import Vendor
    s, e = _period(p)
    agg: dict = defaultdict(lambda: [ZERO, ZERO, ZERO, ZERO])
    for vid, amt in db.execute(select(MaintenanceJobCard.vendor_id, func.sum(MaintenanceJobCard.total_amount)).where(
            MaintenanceJobCard.job_date.between(s, e), MaintenanceJobCard.status != "CANCELLED")
            .group_by(MaintenanceJobCard.vendor_id)).all():
        agg[vid][0] += money(amt)
    for vid, amt in db.execute(select(Tyre.supplier_id, func.sum(Tyre.total_cost)).where(
            Tyre.purchase_date.between(s, e)).group_by(Tyre.supplier_id)).all():
        agg[vid][1] += money(amt)
    for vid, amt in db.execute(select(ExpenseTransaction.vendor_id, func.sum(ExpenseTransaction.total_amount)).where(
            ExpenseTransaction.expense_date.between(s, e)).group_by(ExpenseTransaction.vendor_id)).all():
        agg[vid][2] += money(amt)
    for vid, amt in db.execute(select(BankTransactionAllocation.vendor_id, func.sum(BankTransactionAllocation.amount))
                               .join(BankTransaction, BankTransaction.id == BankTransactionAllocation.bank_transaction_id)
                               .where(BankTransaction.txn_date.between(s, e), BankTransactionAllocation.status == "ACTIVE",
                                      BankTransaction.direction == "DR").group_by(BankTransactionAllocation.vendor_id)).all():
        agg[vid][3] += money(amt)
    rows = [[_name(db, Vendor, vid) or "(no vendor)", *vals, sum(vals, ZERO)] for vid, vals in agg.items()]
    return ["Vendor", "Maintenance", "Tyres", "Vendor Invoices", "Direct Bank Allocations", "Total"], rows


@report("vehicle_history", "Vehicle Classification History", "Fleet", ("vehicle_id",))
def _r_vhist(db, p):
    q = select(VehicleCostCenterHistory).order_by(VehicleCostCenterHistory.vehicle_id, VehicleCostCenterHistory.effective_from)
    if p.get("vehicle_id"):
        q = q.where(VehicleCostCenterHistory.vehicle_id == int(p["vehicle_id"]))
    rows = []
    for h in db.execute(q).scalars():
        cc = db.get(CostCenter, h.new_cost_center_id)
        rows.append([db.get(Vehicle, h.vehicle_id).registration_number, _name(db, CostCategory, h.new_cost_category_id),
                     _name(db, VehicleSubCategory, h.new_sub_category_id), cc.code if cc else "",
                     fmt_date(h.effective_from), fmt_date(h.effective_to) or "current", h.reason])
    return ["Vehicle", "Category", "Sub-category", "Cost Center", "From", "To", "Reason"], rows


@report("audit", "Audit Log", "Audit", ("date_from", "date_to", "entity_type", "action"))
def _r_audit(db, p):
    from app.models.system import AuditLog
    s, e = _period(p)
    q = select(AuditLog).where(AuditLog.created_at.between(datetime.combine(s, time.min), datetime.combine(e, time.max)))
    if p.get("entity_type"):
        q = q.where(AuditLog.entity_type == p["entity_type"])
    if p.get("action"):
        q = q.where(AuditLog.action == p["action"])
    rows = [[fmt_date(a.created_at), a.username, a.action, a.entity_type, a.entity_id, a.reason,
             str(a.new_values)[:300] if a.new_values else ""] for a in db.execute(
        q.order_by(AuditLog.created_at.desc()).limit(20000)).scalars()]
    return ["When", "User", "Action", "Entity", "ID", "Reason", "Changes"], rows


def run(db: Session, key: str, params: dict) -> dict:
    from app.core.errors import NotFound
    r = REPORTS.get(key)
    if not r:
        raise NotFound("Report")
    cols, rows = r.fn(db, params)
    return {"key": key, "title": r.title, "columns": cols, "rows": rows}


def display_rows(rows: list[list]) -> list[list]:
    out = []
    for r in rows:
        out.append([fmt_date(v) if isinstance(v, (date, datetime)) else v for v in r])
    return out
