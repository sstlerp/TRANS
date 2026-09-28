"""Generic renewal engine (spec §8, §9, §44): rule-driven renewal slots per vehicle,
renewal records with history, status computation, insurance policies and
configurable reminders."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import audit, snapshot
from app.core.errors import BusinessError
from app.core.utils import jsonable, money, now, today
from app.models.compliance import (Driver, InsuranceHistory, InsurancePolicy, RenewalHistory, RenewalRule,
                                   RenewalType, VehicleRenewal, VehicleRenewalAssignment)
from app.models.fleet import Vehicle, VehicleFuel
from app.services.rules import reminder_days, rule

STATUSES = ["NOT_DUE", "UPCOMING", "DUE", "EXPIRED", "RENEWED", "CANCELLED", "NOT_APPLICABLE"]


def compute_status(db: Session, expiry: date | None, current_status: str | None = None,
                   is_current: bool = True, on: date | None = None, grace_days: int = 0) -> str:
    if current_status in ("CANCELLED", "NOT_APPLICABLE"):
        return current_status
    if not is_current:
        return "RENEWED" if current_status != "CANCELLED" else "CANCELLED"
    if expiry is None:
        return "NOT_DUE"
    on = on or today()
    days = (expiry - on).days
    if days + grace_days < 0:
        return "EXPIRED"
    if days <= rule(db, "RENEWAL_DUE_DAYS"):
        return "DUE"
    if days <= rule(db, "RENEWAL_UPCOMING_DAYS"):
        return "UPCOMING"
    return "NOT_DUE"


# ───────────────────────── rule → assignment ─────────────────────────
def _rule_applies(db: Session, r: RenewalRule, v: Vehicle) -> bool:
    if r.cost_category_id and r.cost_category_id != v.cost_category_id:
        return False
    if r.sub_category_id and r.sub_category_id != v.sub_category_id:
        return False
    if r.fuel_type_id:
        fuels = {f.fuel_type_id for f in db.execute(select(VehicleFuel).where(
            VehicleFuel.vehicle_id == v.id, VehicleFuel.is_active.is_(True))).scalars()}
        if r.fuel_type_id not in fuels:
            return False
    return True


def apply_rules_to_vehicle(ctx, v: Vehicle) -> int:
    """Create missing renewal slots for every active rule applicable to the vehicle.

    Slots are never deleted automatically: if a rule stops applying (e.g. after
    reclassification) the slot stays for history and a user can mark it NOT_APPLICABLE.
    """
    db = ctx.db
    created = 0
    for r in db.execute(select(RenewalRule).where(RenewalRule.is_active.is_(True))).scalars():
        if not _rule_applies(db, r, v):
            continue
        rt = db.get(RenewalType, r.renewal_type_id)
        n = max(r.instances_required or 1, 1)
        for i in range(1, n + 1):
            label = "PRIMARY" if n == 1 else f"{rt.code} #{i}"
            exists = db.execute(select(VehicleRenewalAssignment.id).where(
                VehicleRenewalAssignment.vehicle_id == v.id,
                VehicleRenewalAssignment.renewal_type_id == r.renewal_type_id,
                VehicleRenewalAssignment.reference_label == label)).first()
            if not exists:
                db.add(VehicleRenewalAssignment(vehicle_id=v.id, renewal_type_id=r.renewal_type_id,
                                                renewal_rule_id=r.id, reference_label=label,
                                                reminder_days=r.reminder_days, created_by=ctx.user.id))
                created += 1
    db.flush()
    return created


def apply_rule_to_fleet(ctx, r: RenewalRule, data: dict | None = None) -> dict:
    n = 0
    for v in ctx.db.execute(select(Vehicle).where(Vehicle.is_active.is_(True))).scalars():
        n += apply_rules_to_vehicle(ctx, v)
    return {"message": f"{n} renewal slot(s) created"}


# ───────────────────────── renewal records ─────────────────────────
def _history(db: Session, user, ren: VehicleRenewal, action: str, old_status: str | None, remarks: str | None = None):
    db.add(RenewalHistory(renewal_id=ren.id, action=action, old_status=old_status, new_status=ren.status,
                          snapshot=jsonable(snapshot(ren)), remarks=remarks, changed_by=getattr(user, "id", None),
                          changed_at=now()))


def _validate_dates(start: date | None, expiry: date | None, issue: date | None = None) -> None:
    if start and expiry and expiry <= start:
        raise BusinessError("Expiry date must be after the start date", "VALIDATION",
                            [{"field": "expiry_date", "message": "Must be after start date"}])
    if issue and expiry and expiry < issue:
        raise BusinessError("Expiry date cannot be before the issue date")


def renewal_before_save(ctx, ren: VehicleRenewal, data: dict, is_new: bool) -> None:
    db = ctx.db
    _validate_dates(ren.start_date, ren.expiry_date, ren.issue_date)
    rt = db.get(RenewalType, ren.renewal_type_id)
    if rt.applies_to == "VEHICLE" and not ren.vehicle_id:
        raise BusinessError("Vehicle is required for this renewal type")
    if rt.applies_to == "DRIVER" and not ren.driver_id:
        raise BusinessError("Driver is required for this renewal type")
    if ren.assignment_id:
        a = db.get(VehicleRenewalAssignment, ren.assignment_id)
        if a.renewal_type_id != ren.renewal_type_id or (a.vehicle_id and a.vehicle_id != ren.vehicle_id):
            raise BusinessError("The renewal slot does not match the vehicle / renewal type")
    elif is_new:
        label = (data.get("reference_label") or "PRIMARY").strip().upper()
        a = db.execute(select(VehicleRenewalAssignment).where(
            VehicleRenewalAssignment.vehicle_id == ren.vehicle_id,
            VehicleRenewalAssignment.driver_id == ren.driver_id,
            VehicleRenewalAssignment.renewal_type_id == ren.renewal_type_id,
            VehicleRenewalAssignment.reference_label == label)).scalar_one_or_none()
        if a is None:
            a = VehicleRenewalAssignment(vehicle_id=ren.vehicle_id, driver_id=ren.driver_id,
                                         renewal_type_id=ren.renewal_type_id, reference_label=label,
                                         created_by=ctx.user.id)
            db.add(a)
            db.flush()
        ren.assignment_id = a.id
    if is_new:
        clash = db.execute(select(VehicleRenewal.id).where(
            VehicleRenewal.assignment_id == ren.assignment_id, VehicleRenewal.is_current.is_(True))).first()
        if clash:
            raise BusinessError("A current record already exists for this renewal slot. Use the 'Renew' action "
                                "so the previous certificate is kept in history, or add a separate slot "
                                "(e.g. a second PESO certificate) with a different reference label.")
        ren.is_current = True
    if ren.amount is not None:
        ren.total_amount = money(ren.amount) + money(ren.tax_amount)
    if ren.vehicle_id and not ren.cost_center_id:
        from app.services.vehicles import cost_center_for
        ren.cost_center_id = cost_center_for(db, ren.vehicle_id, ren.start_date or ren.issue_date)
    ren.status = compute_status(db, ren.expiry_date, ren.status if not is_new else None, ren.is_current)


def renewal_after_save(ctx, ren: VehicleRenewal, data: dict, is_new: bool) -> None:
    _history(ctx.db, ctx.user, ren, "CREATE" if is_new else "UPDATE", None, ctx.reason)


def renew(ctx, old: VehicleRenewal, data: dict) -> dict:
    """Create the next certificate for the same slot; the old one becomes RENEWED (history kept)."""
    db = ctx.db
    if not old.is_current:
        raise BusinessError("Only the current record of a slot can be renewed")
    _validate_dates(data.get("start_date"), data.get("expiry_date"), data.get("issue_date"))
    if old.expiry_date and data.get("expiry_date") and data["expiry_date"] <= old.expiry_date:
        raise BusinessError("New expiry must be later than the current expiry")
    new = VehicleRenewal(
        assignment_id=old.assignment_id, vehicle_id=old.vehicle_id, driver_id=old.driver_id,
        renewal_type_id=old.renewal_type_id, certificate_number=data.get("certificate_number"),
        issue_date=data.get("issue_date"), start_date=data.get("start_date"), expiry_date=data.get("expiry_date"),
        renewal_date=data.get("renewal_date") or today(), amount=data.get("amount"),
        tax_amount=data.get("tax_amount"), provider_id=data.get("provider_id") or old.provider_id,
        authority=data.get("authority") or old.authority, document_number=data.get("document_number"),
        payment_status=data.get("payment_status") or "PENDING", cost_center_id=old.cost_center_id,
        is_current=True, previous_renewal_id=old.id, remarks=data.get("remarks"), created_by=ctx.user.id,
        updated_by=ctx.user.id)
    new.total_amount = money(new.amount) + money(new.tax_amount) if new.amount is not None else None
    old_status = old.status
    old.is_current = False
    old.status = "RENEWED"
    db.flush()  # release the old current flag first
    new.status = compute_status(db, new.expiry_date, None, True)
    db.add(new)
    db.flush()
    _history(db, ctx.user, old, "RENEWED", old_status, f"Superseded by #{new.id}")
    _history(db, ctx.user, new, "CREATE", None, f"Renewal of #{old.id}")
    audit(db, ctx.user, "RENEWAL", "vehicle_renewals", new.id, snapshot(old), snapshot(new), reason=ctx.reason)
    return {"message": "Renewed. Attach the new certificate document.", "new_id": new.id}


def cancel_renewal(ctx, ren: VehicleRenewal, data: dict) -> dict:
    old = ren.status
    ren.status = "CANCELLED"
    _history(ctx.db, ctx.user, ren, "CANCELLED", old, data.get("reason"))
    audit(ctx.db, ctx.user, "CANCEL", "vehicle_renewals", ren.id, {"status": old}, {"status": "CANCELLED"},
          reason=data.get("reason"))
    return {"message": "Cancelled"}


def mark_paid(ctx, ren: VehicleRenewal, data: dict) -> dict:
    ren.payment_status = "PAID"
    _history(ctx.db, ctx.user, ren, "PAID", ren.status, data.get("reason"))
    return {"message": "Marked as paid"}


def mark_not_applicable(ctx, a: VehicleRenewalAssignment, data: dict) -> dict:
    a.is_applicable = not a.is_applicable
    audit(ctx.db, ctx.user, "UPDATE", "vehicle_renewal_assignments", a.id, None,
          {"is_applicable": a.is_applicable}, reason=data.get("reason"))
    return {"message": "Applicability updated"}


def renewal_extra(ctx, ren: VehicleRenewal, row: dict) -> None:
    row["days_left"] = (ren.expiry_date - today()).days if ren.expiry_date else None
    a = ctx.db.get(VehicleRenewalAssignment, ren.assignment_id) if ren.assignment_id else None
    row["reference_label"] = a.reference_label if a else None


# ───────────────────────── insurance ─────────────────────────
def insurance_before_save(ctx, p: InsurancePolicy, data: dict, is_new: bool) -> None:
    _validate_dates(p.start_date, p.expiry_date)
    if not p.vehicle_id and not p.driver_id:
        raise BusinessError("Link the policy to a vehicle and/or a driver")
    if is_new:
        p.is_current = True
    if p.premium is not None:
        p.total_premium = money(p.premium) + money(p.tax_amount)
    if p.vehicle_id and not p.cost_center_id:
        from app.services.vehicles import cost_center_for
        p.cost_center_id = cost_center_for(ctx.db, p.vehicle_id, p.start_date)
    p.renewal_status = compute_status(ctx.db, p.expiry_date, p.renewal_status if not is_new else None, p.is_current)


def insurance_after_save(ctx, p: InsurancePolicy, data: dict, is_new: bool) -> None:
    ctx.db.add(InsuranceHistory(policy_id=p.id, action="CREATE" if is_new else "UPDATE", new_status=p.renewal_status,
                                snapshot=jsonable(snapshot(p)), changed_by=ctx.user.id, changed_at=now()))


def renew_policy(ctx, old: InsurancePolicy, data: dict) -> dict:
    db = ctx.db
    if not old.is_current:
        raise BusinessError("Only the current policy can be renewed")
    _validate_dates(data["start_date"], data["expiry_date"])
    new = InsurancePolicy(
        vehicle_id=old.vehicle_id, driver_id=old.driver_id, provider_id=data.get("provider_id") or old.provider_id,
        policy_type=old.policy_type, policy_number=data["policy_number"], insured_amount=data.get("insured_amount"),
        start_date=data["start_date"], expiry_date=data["expiry_date"], premium=data.get("premium"),
        tax_amount=data.get("tax_amount"), payment_status=data.get("payment_status") or "PENDING",
        payment_reference=data.get("payment_reference"), cost_center_id=old.cost_center_id, is_current=True,
        previous_policy_id=old.id, remarks=data.get("remarks"), created_by=ctx.user.id, updated_by=ctx.user.id)
    new.total_premium = money(new.premium) + money(new.tax_amount) if new.premium is not None else None
    new.renewal_status = compute_status(db, new.expiry_date, None, True)
    prev_status = old.renewal_status
    old.is_current = False
    old.renewal_status = "RENEWED"
    db.add(new)
    db.flush()
    for p, act, st in ((old, "RENEWED", prev_status), (new, "CREATE", None)):
        db.add(InsuranceHistory(policy_id=p.id, action=act, old_status=st, new_status=p.renewal_status,
                                snapshot=jsonable(snapshot(p)), changed_by=ctx.user.id, changed_at=now()))
    audit(db, ctx.user, "RENEWAL", "insurance_policies", new.id, snapshot(old), snapshot(new), reason=ctx.reason)
    return {"message": "Policy renewed", "new_id": new.id}


def insurance_extra(ctx, p: InsurancePolicy, row: dict) -> None:
    row["days_left"] = (p.expiry_date - today()).days if p.expiry_date else None


# ───────────────────────── periodic jobs ─────────────────────────
def refresh_statuses(db: Session) -> int:
    changed = 0
    for r in db.execute(select(VehicleRenewal).where(VehicleRenewal.is_current.is_(True),
                                                     VehicleRenewal.status.notin_(["CANCELLED", "NOT_APPLICABLE"]))
                        ).scalars():
        st = compute_status(db, r.expiry_date, r.status, True)
        if st != r.status:
            old = r.status
            r.status = st
            _history(db, None, r, "STATUS", old, "Automatic status refresh")
            changed += 1
    for p in db.execute(select(InsurancePolicy).where(InsurancePolicy.is_current.is_(True),
                                                      InsurancePolicy.renewal_status != "CANCELLED")).scalars():
        st = compute_status(db, p.expiry_date, p.renewal_status, True)
        if st != p.renewal_status:
            p.renewal_status = st
            changed += 1
    db.flush()
    return changed


def _reminders_for(db: Session, days_left: int, cfg: str | None) -> int | None:
    """Return the reminder bucket crossed (smallest configured day ≥ days_left)."""
    days = reminder_days(cfg, db)
    hits = [d for d in days if days_left <= d]
    return min(hits) if hits else None


def scan_alerts(db: Session) -> int:
    from app.services.notifications import notify
    created = 0
    t = today()
    q = select(VehicleRenewal, RenewalType, VehicleRenewalAssignment).join(
        RenewalType, RenewalType.id == VehicleRenewal.renewal_type_id).outerjoin(
        VehicleRenewalAssignment, VehicleRenewalAssignment.id == VehicleRenewal.assignment_id).where(
        VehicleRenewal.is_current.is_(True), VehicleRenewal.expiry_date.is_not(None),
        VehicleRenewal.status.notin_(["CANCELLED", "NOT_APPLICABLE"]))
    for ren, rt, a in db.execute(q).all():
        left = (ren.expiry_date - t).days
        who = _entity_name(db, ren.vehicle_id, ren.driver_id)
        label = f"{rt.name}{' (' + a.reference_label + ')' if a and a.reference_label != 'PRIMARY' else ''}"
        if left < 0:
            key, sev, title = f"renewal:{ren.id}:expired", "CRITICAL", f"EXPIRED: {label} — {who}"
            ev = "RENEWAL_EXPIRED"
        else:
            bucket = _reminders_for(db, left, (a.reminder_days if a else None) or rt.default_reminder_days)
            if bucket is None:
                continue
            key, sev = f"renewal:{ren.id}:{bucket}", "CRITICAL" if left <= 7 else "WARNING"
            title, ev = f"{label} — {who} expires in {left} day(s)", _event_for(rt.category)
        if notify(db, ev, title, f"Expiry {ren.expiry_date:%d/%m/%Y}. Certificate {ren.certificate_number or '-'}",
                  severity=sev, entity_type="vehicle_renewals", entity_id=ren.id,
                  link_url="/masters/vehicle_renewals", dedupe_key=key):
            created += 1
    for p in db.execute(select(InsurancePolicy).where(InsurancePolicy.is_current.is_(True))).scalars():
        left = (p.expiry_date - t).days
        bucket = _reminders_for(db, left, None)
        if left >= 0 and bucket is None:
            continue
        key = f"insurance:{p.id}:{'expired' if left < 0 else bucket}"
        title = (f"EXPIRED insurance {p.policy_number}" if left < 0 else
                 f"Insurance {p.policy_number} expires in {left} day(s)") + f" — {_entity_name(db, p.vehicle_id, p.driver_id)}"
        if notify(db, "INSURANCE_EXPIRY", title, f"Expiry {p.expiry_date:%d/%m/%Y}",
                  severity="CRITICAL" if left <= 7 else "WARNING", entity_type="insurance_policies",
                  entity_id=p.id, link_url="/masters/insurance_policies", dedupe_key=key):
            created += 1
    for d in db.execute(select(Driver).where(Driver.is_active.is_(True), Driver.license_expiry_date.is_not(None))
                        ).scalars():
        left = (d.license_expiry_date - t).days
        bucket = _reminders_for(db, left, None)
        if left >= 0 and bucket is None:
            continue
        key = f"dl:{d.id}:{d.license_expiry_date}:{'expired' if left < 0 else bucket}"
        if notify(db, "DRIVER_LICENSE_EXPIRY",
                  f"Driving licence of {d.name} {'EXPIRED' if left < 0 else f'expires in {left} day(s)'}",
                  f"Licence {d.license_number} expiry {d.license_expiry_date:%d/%m/%Y}",
                  severity="CRITICAL" if left <= 7 else "WARNING", entity_type="drivers", entity_id=d.id,
                  link_url="/masters/drivers", dedupe_key=key):
            created += 1
    return created


def _event_for(category: str) -> str:
    return {"INSURANCE": "INSURANCE_EXPIRY", "PERMIT": "PERMIT_EXPIRY", "FITNESS": "FITNESS_EXPIRY",
            "PUCC": "PUCC_EXPIRY", "PESO": "PESO_EXPIRY", "HAZMAT": "PESO_EXPIRY",
            "LICENSE": "DRIVER_LICENSE_EXPIRY"}.get(category, "RENEWAL_DUE")


def _entity_name(db: Session, vehicle_id, driver_id) -> str:
    if vehicle_id:
        v = db.get(Vehicle, vehicle_id)
        return v.registration_number if v else f"vehicle #{vehicle_id}"
    if driver_id:
        d = db.get(Driver, driver_id)
        return d.name if d else f"driver #{driver_id}"
    return "-"


# ───────────────────────── dashboard ─────────────────────────
def dashboard(db: Session, category: str | None = None) -> dict:
    from app.models.system import Document
    t = today()
    base = select(VehicleRenewal).join(RenewalType, RenewalType.id == VehicleRenewal.renewal_type_id).where(
        VehicleRenewal.is_current.is_(True), VehicleRenewal.status.notin_(["CANCELLED", "NOT_APPLICABLE"]))
    if category:
        base = base.where(RenewalType.category == category)

    def count(*conds):
        return db.execute(select(func.count()).select_from(base.where(*conds).subquery())).scalar_one()

    e = VehicleRenewal.expiry_date
    has_doc = select(Document.entity_id).where(Document.entity_type == "vehicle_renewals",
                                               Document.is_active.is_(True))
    out = {
        "due_today": count(e == t),
        "due_7": count(e >= t, e <= t + timedelta(days=7)),
        "due_15": count(e >= t, e <= t + timedelta(days=15)),
        "due_30": count(e >= t, e <= t + timedelta(days=30)),
        "expired": count(e < t),
        "renewed_30": db.execute(select(func.count()).select_from(VehicleRenewal).where(
            VehicleRenewal.status == "RENEWED", VehicleRenewal.updated_at >= now() - timedelta(days=30))).scalar_one(),
        "pending_documents": count(RenewalType.requires_document.is_(True), VehicleRenewal.id.notin_(has_doc)),
        "pending_payment": count(VehicleRenewal.payment_status == "PENDING", VehicleRenewal.amount.is_not(None)),
    }
    ins = select(InsurancePolicy).where(InsurancePolicy.is_current.is_(True))
    out["insurance_due_30"] = db.execute(select(func.count()).select_from(ins.where(
        InsurancePolicy.expiry_date >= t, InsurancePolicy.expiry_date <= t + timedelta(days=30)).subquery())).scalar_one()
    out["insurance_expired"] = db.execute(select(func.count()).select_from(ins.where(
        InsurancePolicy.expiry_date < t).subquery())).scalar_one()
    by_cat = db.execute(select(RenewalType.category, VehicleRenewal.status, func.count()).join(
        RenewalType, RenewalType.id == VehicleRenewal.renewal_type_id).where(VehicleRenewal.is_current.is_(True))
        .group_by(RenewalType.category, VehicleRenewal.status)).all()
    out["by_category"] = [{"category": c, "status": s, "count": n} for c, s, n in by_cat]
    return out


def calendar(db: Session, start: date, end: date, category: str | None = None) -> list[dict]:
    q = select(VehicleRenewal, RenewalType.name).join(
        RenewalType, RenewalType.id == VehicleRenewal.renewal_type_id).where(
        VehicleRenewal.is_current.is_(True), VehicleRenewal.expiry_date.between(start, end),
        VehicleRenewal.status.notin_(["CANCELLED", "NOT_APPLICABLE"]))
    if category:
        q = q.where(RenewalType.category == category)
    rows = db.execute(q.order_by(VehicleRenewal.expiry_date)).all()
    out = [{"date": r.expiry_date.isoformat(), "type": n, "entity": _entity_name(db, r.vehicle_id, r.driver_id),
            "status": r.status, "id": r.id, "kind": "renewal"} for r, n in rows]
    for p in db.execute(select(InsurancePolicy).where(InsurancePolicy.is_current.is_(True),
                                                      InsurancePolicy.expiry_date.between(start, end))).scalars():
        if category and category != "INSURANCE":
            break
        out.append({"date": p.expiry_date.isoformat(), "type": f"Insurance {p.policy_type}",
                    "entity": _entity_name(db, p.vehicle_id, p.driver_id), "status": p.renewal_status,
                    "id": p.id, "kind": "insurance"})
    return sorted(out, key=lambda x: x["date"])
