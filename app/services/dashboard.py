"""Executive dashboard aggregates (spec §48, §65). Everything unresolved is surfaced."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.utils import jsonable, today
from app.models.finance import BankTransaction, FinancialTransactionLink, Invoice, ApprovalRequest
from app.models.fleet import CostCategory, Vehicle
from app.models.imports import StatementImportBatch, StatementImportError
from app.models.operations import FuelTransaction, MaintenanceJobCard, TollTransaction
from app.models.org import BankAccount
from app.models.system import Notification
from app.models.tyres import Tyre
from app.services import renewals
from app.services.rules import rule


def _count(db, q):
    return db.execute(select(func.count()).select_from(q.subquery())).scalar_one()


def summary(db: Session, user) -> dict:
    t = today()
    start = t.replace(day=1)
    out: dict = {}
    vq = select(Vehicle)
    if user.branch_ids is not None:
        vq = vq.where(Vehicle.branch_id.in_(user.branch_ids))
    out["fleet"] = {
        "total": _count(db, vq), "active": _count(db, vq.where(Vehicle.is_active.is_(True))),
        "inactive": _count(db, vq.where(Vehicle.is_active.is_(False))),
        "by_category": [{"label": n, "count": c} for n, c in db.execute(
            select(CostCategory.name, func.count(Vehicle.id)).join(Vehicle, Vehicle.cost_category_id == CostCategory.id)
            .where(Vehicle.is_active.is_(True)).group_by(CostCategory.name)).all()],
        "by_status": [{"label": s, "count": c} for s, c in db.execute(
            select(Vehicle.vehicle_status, func.count()).where(Vehicle.is_active.is_(True))
            .group_by(Vehicle.vehicle_status)).all()],
    }
    out["compliance"] = renewals.dashboard(db)
    for cat in ("PERMIT", "FITNESS", "PUCC", "PESO", "TAX"):
        d = renewals.dashboard(db, cat)
        out["compliance"][f"{cat.lower()}_due_30"] = d["due_30"]
        out["compliance"][f"{cat.lower()}_expired"] = d["expired"]
    bt = select(BankTransaction).where(BankTransaction.status == "ACTIVE")
    unm = ["UNMATCHED", "AUTO_SUGGESTED"]
    out["finance"] = {
        "unmatched_credits": _count(db, bt.where(BankTransaction.direction == "CR", BankTransaction.recon_status.in_(unm))),
        "unmatched_debits": _count(db, bt.where(BankTransaction.direction == "DR", BankTransaction.recon_status.in_(unm))),
        "unmatched_credit_amount": db.execute(select(func.coalesce(func.sum(BankTransaction.unmatched_amount), 0)).where(
            BankTransaction.direction == "CR", BankTransaction.recon_status.in_(unm + ["PARTIALLY_MATCHED"]))).scalar_one(),
        "unmatched_debit_amount": db.execute(select(func.coalesce(func.sum(BankTransaction.unmatched_amount), 0)).where(
            BankTransaction.direction == "DR", BankTransaction.recon_status.in_(unm + ["PARTIALLY_MATCHED"]))).scalar_one(),
        "partially_matched": _count(db, bt.where(BankTransaction.recon_status == "PARTIALLY_MATCHED")),
        "pending_approvals": _count(db, select(ApprovalRequest).where(ApprovalRequest.status == "PENDING")),
        "suggested": _count(db, select(FinancialTransactionLink).where(
            FinancialTransactionLink.match_status == "AUTO_SUGGESTED")),
        "receivables": db.execute(select(func.coalesce(func.sum(Invoice.outstanding_amount), 0)).where(
            Invoice.status.in_(["OPEN", "PARTIALLY_PAID"]))).scalar_one(),
        "overdue_receivables": db.execute(select(func.coalesce(func.sum(Invoice.outstanding_amount), 0)).where(
            Invoice.status.in_(["OPEN", "PARTIALLY_PAID"]), Invoice.due_date < t)).scalar_one(),
        "accounts": [{"code": a.code, "name": a.account_name, "balance": a.closing_balance,
                      "as_of": a.closing_balance_date, "last_import": db.execute(
                          select(func.max(StatementImportBatch.imported_at)).where(
                              StatementImportBatch.bank_account_id == a.id)).scalar()}
                     for a in db.execute(select(BankAccount).where(BankAccount.is_active.is_(True))).scalars()],
        "recent_receipts": [{"date": x.txn_date, "amount": x.amount, "narration": x.narration, "status": x.recon_status}
                            for x in db.execute(bt.where(BankTransaction.direction == "CR").order_by(
                                BankTransaction.txn_date.desc()).limit(6)).scalars()],
        "recent_payments": [{"date": x.txn_date, "amount": x.amount, "narration": x.narration, "status": x.recon_status}
                            for x in db.execute(bt.where(BankTransaction.direction == "DR").order_by(
                                BankTransaction.txn_date.desc()).limit(6)).scalars()],
    }
    fuel = db.execute(select(func.coalesce(func.sum(FuelTransaction.total_amount), 0)).where(
        FuelTransaction.txn_date >= start, FuelTransaction.status != "CANCELLED")).scalar_one()
    toll = db.execute(select(func.coalesce(func.sum(TollTransaction.amount), 0)).where(
        TollTransaction.txn_date >= start, TollTransaction.txn_kind == "DEBIT")).scalar_one()
    maint = db.execute(select(func.coalesce(func.sum(MaintenanceJobCard.total_amount), 0)).where(
        MaintenanceJobCard.job_date >= start, MaintenanceJobCard.status != "CANCELLED")).scalar_one()
    from app.services.reports import profitability
    prof = profitability(db, start, t, cc_type="VEHICLE")
    tot = prof["totals"] or {}
    active = out["fleet"]["active"] or 1
    out["operations"] = {
        "month_start": start, "fuel_cost": fuel, "toll_cost": toll, "maintenance_cost": maint,
        "tyre_cost": tot.get("tyre", 0), "total_cost": tot.get("total_cost", 0),
        "cost_per_vehicle": (Decimal(tot.get("total_cost", 0)) / active).quantize(Decimal("0.01")),
        "km": tot.get("km", 0),
        "cost_per_km": (Decimal(tot["total_cost"]) / Decimal(tot["km"])).quantize(Decimal("0.01"))
        if tot.get("km") else None,
        "top_vehicles": sorted([{"vehicle": r["vehicle"], "cost": r["total_cost"], "net": r["net_contribution"]}
                                for r in prof["rows"]], key=lambda r: -r["cost"])[:8],
    }
    thr = Decimal(rule(db, "TYRE_MIN_TREAD_MM"))
    out["alerts"] = {
        "import_errors": db.execute(select(func.count()).select_from(StatementImportError).where(
            StatementImportError.resolved.is_(False), StatementImportError.severity == "ERROR")).scalar_one(),
        "toll_vehicle_unmatched": _count(db, select(TollTransaction).where(TollTransaction.status == "VEHICLE_UNMATCHED")),
        "toll_plaza_unmatched": _count(db, select(TollTransaction).where(TollTransaction.plaza_match_status == "PLAZA_UNMATCHED")),
        "fuel_vehicle_unmatched": _count(db, select(FuelTransaction).where(FuelTransaction.status == "VEHICLE_UNMATCHED")),
        "fuel_flagged": _count(db, select(FuelTransaction).where(FuelTransaction.status == "FLAGGED")),
        "tyre_low_tread": _count(db, select(Tyre).where(Tyre.current_tread_depth <= thr,
                                                        Tyre.current_status.in_(["INSTALLED", "SHIFTED",
                                                                                 "FITTED_AFTER_RETREAD"]))),
        "tyre_warranty_expiring": _count(db, select(Tyre).where(Tyre.warranty_expiry_date.between(
            t, t + timedelta(days=30)))),
        "maintenance_due": _count(db, select(Notification).where(Notification.event_type == "MAINTENANCE_DUE",
                                                                 Notification.is_read.is_(False))),
        "critical": [jsonable({"title": n.title, "severity": n.severity, "link": n.link_url, "at": n.created_at})
                     for n in db.execute(select(Notification).where(Notification.is_read.is_(False)).order_by(
                         Notification.severity.asc(), Notification.created_at.desc()).limit(10)).scalars()],
    }
    return jsonable(out)
