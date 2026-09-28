"""Maintenance job cards (spec §29) and maintenance-due alerts."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.errors import BusinessError
from app.core.utils import money, now, today
from app.models.fleet import Vehicle
from app.models.operations import MaintenanceJobCard, MaintenanceLabour, MaintenancePart, MaintenanceType
from app.services import approvals
from app.services.rules import rule
from app.services.vehicles import cost_center_for, record_odometer


def before_save(ctx, j: MaintenanceJobCard, data: dict, is_new: bool) -> None:
    if not is_new and j.approval_status == "APPROVED" and {"vehicle_id", "parts", "labour", "other_amount"} & set(data):
        raise BusinessError("Approved job cards are locked. Reopen via a new job card or correction.")
    if j.completion_date and j.completion_date < j.job_date:
        raise BusinessError("Completion date cannot be before job date")
    if j.downtime_start and j.downtime_end:
        if j.downtime_end < j.downtime_start:
            raise BusinessError("Downtime end must be after start")
        j.downtime_hours = Decimal(str(round((j.downtime_end - j.downtime_start).total_seconds() / 3600, 2)))
    j.cost_center_id = j.cost_center_id or cost_center_for(ctx.db, j.vehicle_id, j.job_date)
    j.source_type = j.source_type or "MANUAL"
    mt = ctx.db.get(MaintenanceType, j.maintenance_type_id)
    if mt and j.odometer is not None and mt.interval_km and not j.next_due_km:
        j.next_due_km = Decimal(j.odometer) + mt.interval_km
    if mt and mt.interval_days and not j.next_due_date:
        j.next_due_date = j.job_date + timedelta(days=mt.interval_days)


def after_save(ctx, j: MaintenanceJobCard, data: dict, is_new: bool) -> None:
    db = ctx.db
    parts = db.execute(select(MaintenancePart).where(MaintenancePart.job_card_id == j.id)).scalars().all()
    labour = db.execute(select(MaintenanceLabour).where(MaintenanceLabour.job_card_id == j.id)).scalars().all()
    for p in parts:
        p.amount = money(Decimal(p.quantity or 0) * Decimal(p.rate or 0)) if p.rate else money(p.amount)
    for l in labour:
        if l.hours and l.rate and not l.amount:
            l.amount = money(Decimal(l.hours) * Decimal(l.rate))
    if parts or labour:
        j.parts_amount = sum((money(p.amount) for p in parts), Decimal("0"))
        j.labour_amount = sum((money(l.amount) for l in labour), Decimal("0"))
        line_tax = sum((money(p.tax_amount) for p in parts), Decimal("0")) + sum(
            (money(l.tax_amount) for l in labour), Decimal("0"))
        if line_tax:
            j.tax_amount = line_tax
    j.amount = money(j.parts_amount) + money(j.labour_amount) + money(j.other_amount)
    j.total_amount = j.amount + money(j.tax_amount)
    if j.odometer is not None and (is_new or "odometer" in data):
        record_odometer(ctx, j.vehicle_id, j.odometer, datetime.combine(j.job_date, time(9)), "MAINTENANCE", j.id,
                        reason=data.get("override_reason"))
    if is_new:
        r = approvals.requires_approval(db, "LARGE_TRANSACTION", j.total_amount)
        if r:
            j.approval_status = "PENDING"
            approvals.create_request(db, ctx.user, r, "MAINTENANCE_APPROVAL", "maintenance_job_cards", j.id,
                                     f"Job card {j.job_card_number} ₹{j.total_amount}", j.total_amount)


def complete(ctx, j: MaintenanceJobCard, data: dict) -> dict:
    if j.status in ("COMPLETED", "CANCELLED"):
        raise BusinessError(f"Job card is {j.status}")
    j.status = "COMPLETED"
    j.completion_date = data.get("completion_date") or today()
    if data.get("work_performed"):
        j.work_performed = data["work_performed"]
    audit(ctx.db, ctx.user, "UPDATE", "maintenance_job_cards", j.id, None, {"status": "COMPLETED"})
    return {"message": "Job card completed"}


def cancel(ctx, j: MaintenanceJobCard, data: dict) -> dict:
    j.status = "CANCELLED"
    audit(ctx.db, ctx.user, "CANCEL", "maintenance_job_cards", j.id, None, {"status": "CANCELLED"},
          reason=data.get("reason"))
    return {"message": "Job card cancelled"}


def _approve(db, user, req):
    j = db.get(MaintenanceJobCard, req.entity_id)
    if j:
        j.approval_status, j.approved_by, j.approved_at = "APPROVED", user.id, now()


def _reject(db, user, req):
    j = db.get(MaintenanceJobCard, req.entity_id)
    if j:
        j.approval_status = "REJECTED"


approvals.register("MAINTENANCE_APPROVAL", _approve, _reject)


def due_alerts(db: Session) -> int:
    from app.services.notifications import notify
    alert_km, alert_days = rule(db, "MAINTENANCE_DUE_ALERT_KM"), rule(db, "MAINTENANCE_DUE_ALERT_DAYS")
    latest = select(MaintenanceJobCard.vehicle_id, MaintenanceJobCard.maintenance_type_id,
                    func.max(MaintenanceJobCard.id).label("mid")).where(
        MaintenanceJobCard.status != "CANCELLED").group_by(MaintenanceJobCard.vehicle_id,
                                                           MaintenanceJobCard.maintenance_type_id).subquery()
    n = 0
    for j in db.execute(select(MaintenanceJobCard).join(latest, latest.c.mid == MaintenanceJobCard.id)).scalars():
        v = db.get(Vehicle, j.vehicle_id)
        mt = db.get(MaintenanceType, j.maintenance_type_id)
        due = []
        if j.next_due_km and v.current_odometer is not None and Decimal(v.current_odometer) >= Decimal(
                j.next_due_km) - alert_km:
            due.append(f"at {j.next_due_km} km (now {v.current_odometer})")
        if j.next_due_date and j.next_due_date <= today() + timedelta(days=alert_days):
            due.append(f"on {j.next_due_date:%d/%m/%Y}")
        if due and notify(db, "MAINTENANCE_DUE", f"{mt.name} due for {v.registration_number}", " / ".join(due),
                          severity="WARNING", entity_type="vehicles", entity_id=v.id, link_url="/masters/job_cards",
                          dedupe_key=f"maint:{j.id}"):
            n += 1
    return n
