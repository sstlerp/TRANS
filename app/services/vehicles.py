"""Vehicle domain: cost-center creation, effective-dated reclassification,
configurable technical attributes, fuel configuration and odometer control."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.errors import BusinessError, NotFound, OverrideRequired
from app.core.utils import normalize_vehicle_number, now, parse_date, to_decimal, today
from app.models.fleet import (CostCategory, CostCenter, OdometerReading, SubCategoryAttribute, Vehicle,
                              VehicleAttributeValue, VehicleCostCenterHistory, VehicleFuel, VehicleSubCategory)
from app.services.rules import rule


# ───────────────────────── lookup helpers ─────────────────────────
def find_vehicle_by_number(db: Session, raw: str | None) -> Vehicle | None:
    norm = normalize_vehicle_number(raw)
    if not norm:
        return None
    return db.execute(select(Vehicle).where(Vehicle.registration_normalized == norm)).scalar_one_or_none()


def cost_center_for(db: Session, vehicle_id: int | None, on: date | None = None) -> int | None:
    """Cost center applicable to a vehicle on a date (history-aware)."""
    if not vehicle_id:
        return None
    if on:
        h = classification_at(db, vehicle_id, on)
        if h:
            return h.new_cost_center_id
    v = db.get(Vehicle, vehicle_id)
    return v.cost_center_id if v else None


def classification_at(db: Session, vehicle_id: int, on: date) -> VehicleCostCenterHistory | None:
    return db.execute(
        select(VehicleCostCenterHistory).where(
            VehicleCostCenterHistory.vehicle_id == vehicle_id,
            VehicleCostCenterHistory.effective_from <= on,
            or_(VehicleCostCenterHistory.effective_to.is_(None), VehicleCostCenterHistory.effective_to >= on),
        ).order_by(VehicleCostCenterHistory.effective_from.desc())
    ).scalars().first()


# ───────────────────────── master hooks ─────────────────────────
def before_save(ctx, v: Vehicle, data: dict, is_new: bool) -> None:
    db = ctx.db
    v.registration_number = (v.registration_number or "").strip().upper()
    v.registration_normalized = normalize_vehicle_number(v.registration_number)
    if len(v.registration_normalized) < 4:
        raise BusinessError("Registration number looks invalid", "VALIDATION",
                            [{"field": "registration_number", "message": "Invalid registration number"}])
    sub = db.get(VehicleSubCategory, v.sub_category_id)
    if not sub or sub.cost_category_id != v.cost_category_id:
        raise BusinessError("Sub-category does not belong to the selected category", "VALIDATION",
                            [{"field": "sub_category_id", "message": "Not under selected category"}])
    cat = db.get(CostCategory, v.cost_category_id)
    if cat and cat.applies_to == "NON_VEHICLE":
        raise BusinessError("Selected cost category is for non-vehicle cost centers")
    if is_new and not v.tyre_layout_id and sub.default_tyre_layout_id:
        v.tyre_layout_id = sub.default_tyre_layout_id
    if is_new and v.current_odometer is not None:
        v.odometer_updated_at = now()


def after_save(ctx, v: Vehicle, data: dict, is_new: bool) -> None:
    db = ctx.db
    if is_new:
        cc = None
        if data.get("cost_center_id"):
            cc = db.get(CostCenter, int(data["cost_center_id"]))
            if cc and cc.vehicle_id and cc.vehicle_id != v.id:
                raise BusinessError("That cost center already belongs to another vehicle")
        if cc is None:
            cc = CostCenter(code=f"VCC-{v.vehicle_code}"[:30], name=f"{v.registration_number} ({v.vehicle_code})",
                            cc_type="VEHICLE", cost_category_id=v.cost_category_id, branch_id=v.branch_id,
                            created_by=ctx.user.id, updated_by=ctx.user.id)
            db.add(cc)
            db.flush()
        cc.vehicle_id = v.id
        v.cost_center_id = cc.id
        db.add(VehicleCostCenterHistory(
            vehicle_id=v.id, new_cost_category_id=v.cost_category_id, new_sub_category_id=v.sub_category_id,
            new_cost_center_id=cc.id, effective_from=v.purchase_date or today(), reason="Initial classification",
            changed_by=ctx.user.id, changed_at=now()))
        if v.current_odometer is not None:
            # the opening reading is dated at purchase (if known) so later-dated history can follow it
            at = datetime.combine(v.purchase_date, datetime.min.time()) if v.purchase_date else now()
            v.odometer_updated_at = at
            db.add(OdometerReading(vehicle_id=v.id, reading_at=at, reading=v.current_odometer,
                                   source_module="MANUAL", remarks="Opening reading", created_by=ctx.user.id))
        ensure_renewal_assignments(ctx, v)
    else:
        cc = db.get(CostCenter, v.cost_center_id) if v.cost_center_id else None
        if cc and cc.cc_type == "VEHICLE":
            cc.name = f"{v.registration_number} ({v.vehicle_code})"
            cc.branch_id = v.branch_id
    if "attributes" in data:
        save_attributes(ctx, v, data.get("attributes") or {})
    _validate_fuels(db, v)


def ensure_renewal_assignments(ctx, v: Vehicle) -> int:
    from app.services.renewals import apply_rules_to_vehicle
    return apply_rules_to_vehicle(ctx, v)


def _validate_fuels(db: Session, v: Vehicle) -> None:
    fuels = db.execute(select(VehicleFuel).where(VehicleFuel.vehicle_id == v.id, VehicleFuel.is_active.is_(True))
                       ).scalars().all()
    if not fuels:
        raise BusinessError("Configure at least one fuel type for the vehicle", "VALIDATION",
                            [{"field": "fuels", "message": "At least one fuel type"}])
    seen = set()
    for f in fuels:
        if f.fuel_type_id in seen and not f.effective_to:
            raise BusinessError("The same fuel type is configured twice")
        seen.add(f.fuel_type_id)
    if sum(1 for f in fuels if f.is_primary and not f.effective_to) > 1:
        raise BusinessError("Only one primary fuel type is allowed")
    if not any(f.is_primary for f in fuels):
        fuels[0].is_primary = True


def allowed_fuel_type_ids(db: Session, vehicle_id: int, on: date | None = None) -> set[int]:
    on = on or today()
    rows = db.execute(select(VehicleFuel).where(VehicleFuel.vehicle_id == vehicle_id,
                                                VehicleFuel.is_active.is_(True))).scalars()
    return {r.fuel_type_id for r in rows
            if (r.effective_from is None or r.effective_from <= on) and (r.effective_to is None or r.effective_to >= on)}


# ───────────────────────── attributes ─────────────────────────
def attribute_definitions(db: Session, sub_category_id: int) -> list[SubCategoryAttribute]:
    return list(db.execute(select(SubCategoryAttribute).where(
        SubCategoryAttribute.sub_category_id == sub_category_id, SubCategoryAttribute.is_active.is_(True)
    ).order_by(SubCategoryAttribute.display_order, SubCategoryAttribute.id)).scalars())


def save_attributes(ctx, v: Vehicle, values: dict) -> None:
    db = ctx.db
    defs = attribute_definitions(db, v.sub_category_id)
    errors = []
    for d in defs:
        raw = values.get(str(d.id), values.get(d.id, values.get(d.code)))
        if raw in (None, ""):
            if d.is_mandatory:
                errors.append({"field": f"attr_{d.id}", "message": f"{d.name} is required"})
            continue
        row = db.execute(select(VehicleAttributeValue).where(VehicleAttributeValue.vehicle_id == v.id,
                                                             VehicleAttributeValue.attribute_id == d.id)
                         ).scalar_one_or_none() or VehicleAttributeValue(vehicle_id=v.id, attribute_id=d.id)
        row.value_text = row.value_number = row.value_bool = row.value_date = None
        try:
            if d.data_type in ("INTEGER", "DECIMAL"):
                n = to_decimal(raw)
                if d.data_type == "INTEGER" and n != n.to_integral_value():
                    raise ValueError("must be a whole number")
                if d.min_value is not None and n < d.min_value or d.max_value is not None and n > d.max_value:
                    raise ValueError(f"must be between {d.min_value} and {d.max_value}")
                row.value_number = n
            elif d.data_type == "BOOLEAN":
                row.value_bool = raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "y")
            elif d.data_type == "DATE":
                row.value_date = parse_date(raw)
            elif d.data_type == "DROPDOWN":
                opts = [o.strip() for o in (d.dropdown_options or "").replace("\n", ",").split(",") if o.strip()]
                if str(raw) not in opts:
                    raise ValueError(f"must be one of {', '.join(opts)}")
                row.value_text = str(raw)
            else:
                row.value_text = str(raw)[:500]
        except (ValueError, ArithmeticError) as exc:
            errors.append({"field": f"attr_{d.id}", "message": f"{d.name}: {exc}"})
            continue
        row.updated_at = now()
        db.add(row)
    if errors:
        raise BusinessError("Invalid technical attributes", "VALIDATION", errors, 422)


def attribute_values(db: Session, vehicle_id: int) -> dict[int, object]:
    out = {}
    for r in db.execute(select(VehicleAttributeValue).where(VehicleAttributeValue.vehicle_id == vehicle_id)).scalars():
        v = r.value_text
        if r.value_number is not None:
            v = format(r.value_number.normalize(), "f")
        elif r.value_bool is not None:
            v = r.value_bool
        elif r.value_date is not None:
            v = r.value_date.isoformat()
        out[r.attribute_id] = v
    return out


# ───────────────────────── reclassification (history preserving) ─────────────────────────
def reclassify(ctx, v: Vehicle, data: dict) -> dict:
    db = ctx.db
    eff: date = data["effective_from"]
    new_cat = int(data["cost_category_id"])
    new_sub = int(data["sub_category_id"])
    new_cc = int(data.get("cost_center_id") or v.cost_center_id)
    sub = db.get(VehicleSubCategory, new_sub)
    if not sub or sub.cost_category_id != new_cat:
        raise BusinessError("Sub-category does not belong to the selected category")
    cc = db.get(CostCenter, new_cc)
    if not cc or (cc.vehicle_id and cc.vehicle_id != v.id):
        raise BusinessError("Cost center is invalid or belongs to another vehicle")
    if (new_cat, new_sub, new_cc) == (v.cost_category_id, v.sub_category_id, v.cost_center_id):
        raise BusinessError("Nothing changed")
    current = db.execute(select(VehicleCostCenterHistory).where(
        VehicleCostCenterHistory.vehicle_id == v.id, VehicleCostCenterHistory.effective_to.is_(None)
    ).order_by(VehicleCostCenterHistory.effective_from.desc())).scalars().first()
    if current and eff <= current.effective_from:
        raise BusinessError(f"Effective date must be after {current.effective_from:%d/%m/%Y} "
                            "(the start of the current classification). Historical periods are never rewritten.")
    if current:
        current.effective_to = eff - timedelta(days=1)
    hist = VehicleCostCenterHistory(
        vehicle_id=v.id, old_cost_category_id=v.cost_category_id, new_cost_category_id=new_cat,
        old_sub_category_id=v.sub_category_id, new_sub_category_id=new_sub, old_cost_center_id=v.cost_center_id,
        new_cost_center_id=new_cc, effective_from=eff, reason=data.get("reason"), changed_by=ctx.user.id,
        changed_at=now())
    db.add(hist)
    old = {"cost_category_id": v.cost_category_id, "sub_category_id": v.sub_category_id,
           "cost_center_id": v.cost_center_id}
    if eff <= today():
        v.cost_category_id, v.sub_category_id, v.cost_center_id = new_cat, new_sub, new_cc
    if cc.cc_type == "VEHICLE" and cc.vehicle_id is None:
        cc.vehicle_id = v.id
    db.flush()
    audit(db, ctx.user, "COST_CENTER_CHANGE", "vehicles", v.id, old,
          {"cost_category_id": new_cat, "sub_category_id": new_sub, "cost_center_id": new_cc,
           "effective_from": eff}, reason=data.get("reason"))
    apply_rules = ensure_renewal_assignments(ctx, v)
    missing = [d.name for d in attribute_definitions(db, new_sub) if d.is_mandatory
               and d.id not in attribute_values(db, v.id)]
    if missing:
        ctx.warnings.append("Enter technical attributes for the new sub-category: " + ", ".join(missing))
    return {"message": "Classification changed; history preserved", "new_renewal_slots": apply_rules}


def apply_scheduled_classifications(db: Session) -> int:
    """Daily job: future-dated reclassifications become current on their effective date."""
    n = 0
    for h in db.execute(select(VehicleCostCenterHistory).where(
            VehicleCostCenterHistory.effective_to.is_(None),
            VehicleCostCenterHistory.effective_from <= today())).scalars():
        v = db.get(Vehicle, h.vehicle_id)
        if v and (v.cost_category_id, v.sub_category_id, v.cost_center_id) != (
                h.new_cost_category_id, h.new_sub_category_id, h.new_cost_center_id):
            v.cost_category_id, v.sub_category_id, v.cost_center_id = (
                h.new_cost_category_id, h.new_sub_category_id, h.new_cost_center_id)
            n += 1
    return n


# ───────────────────────── odometer ─────────────────────────
def record_odometer(ctx, vehicle_id: int, reading: Decimal | None, at: datetime, source_module: str,
                    source_entity_id: int | None = None, reason: str | None = None,
                    override_perm: str = "fleet.odometer_override", mode_rule: str = "ODOMETER_DECREASE_MODE"
                    ) -> OdometerReading | None:
    """Validate chronological consistency and log the reading.

    A reading lower than an earlier reading (or higher than a later one) is an
    error or a warning depending on configuration. An authorised user may
    override an error with a mandatory reason; the override is audited.
    """
    if reading is None:
        return None
    db = ctx.db
    reading = Decimal(reading)
    if reading < 0:
        raise BusinessError("Odometer cannot be negative")
    tol = Decimal(rule(db, "ODOMETER_TOLERANCE_KM"))
    prev = db.execute(select(OdometerReading).where(OdometerReading.vehicle_id == vehicle_id,
                                                    OdometerReading.reading_at <= at)
                      .order_by(OdometerReading.reading_at.desc(), OdometerReading.id.desc())).scalars().first()
    nxt = db.execute(select(OdometerReading).where(OdometerReading.vehicle_id == vehicle_id,
                                                   OdometerReading.reading_at > at)
                     .order_by(OdometerReading.reading_at.asc())).scalars().first()
    problems = []
    if prev and reading + tol < prev.reading:
        problems.append(f"Odometer {reading} is lower than the previous reading {prev.reading} "
                        f"on {prev.reading_at:%d/%m/%Y}")
    if nxt and reading > nxt.reading + tol:
        problems.append(f"Odometer {reading} is higher than a later reading {nxt.reading} on {nxt.reading_at:%d/%m/%Y}")
    if prev and not problems:
        days = max((at - prev.reading_at).total_seconds() / 86400, 1)
        if (reading - prev.reading) / Decimal(str(days)) > rule(db, "ODOMETER_MAX_DAILY_KM"):
            ctx.warnings.append(f"Unusual odometer jump: {reading - prev.reading} km since "
                                f"{prev.reading_at:%d/%m/%Y}")
    is_override = False
    if problems:
        mode = rule(db, mode_rule)
        if mode == "WARN":
            ctx.warnings.extend(problems)
        elif ctx.override and reason:
            ctx.user.require(override_perm)
            is_override = True
            audit(db, ctx.user, "OVERRIDE", "odometer", vehicle_id, new={"reading": reading, "problems": problems},
                  reason=reason)
            _review_override(ctx, "ODOMETER_OVERRIDE", "vehicles", vehicle_id, "; ".join(problems))
        else:
            raise OverrideRequired("; ".join(problems) + ". An authorised user may override with a reason.",
                                   "ODOMETER_INCONSISTENT", override_perm)
    r = OdometerReading(vehicle_id=vehicle_id, reading_at=at, reading=reading, source_module=source_module,
                        source_entity_id=source_entity_id, is_override=is_override,
                        override_reason=reason if is_override else None, created_by=ctx.user.id)
    db.add(r)
    v = db.get(Vehicle, vehicle_id)
    if v and (nxt is None) and (v.odometer_updated_at is None or at >= v.odometer_updated_at):
        v.current_odometer = reading
        v.odometer_updated_at = at
    db.flush()
    return r


def previous_odometer(db: Session, vehicle_id: int, at: datetime, exclude_module_id: tuple | None = None):
    q = select(OdometerReading).where(OdometerReading.vehicle_id == vehicle_id, OdometerReading.reading_at < at)
    return db.execute(q.order_by(OdometerReading.reading_at.desc())).scalars().first()


def _review_override(ctx, action_type: str, entity_type: str, entity_id: int, summary: str) -> None:
    from app.services import approvals
    r = approvals.requires_approval(ctx.db, action_type)
    if r:
        approvals.create_request(ctx.db, ctx.user, r, action_type, entity_type, entity_id,
                                 f"Override review: {summary}")


def odometer_action(ctx, v: Vehicle, data: dict) -> dict:
    record_odometer(ctx, v.id, data["reading"], data.get("reading_at") or now(), "MANUAL",
                    reason=data.get("reason"))
    return {"message": "Odometer recorded"}


def vehicle_label(db: Session, vehicle_id: int | None) -> str:
    if not vehicle_id:
        return ""
    v = db.get(Vehicle, vehicle_id)
    return v.registration_number if v else ""
