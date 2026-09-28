"""Tyre lifecycle engine (spec §30-§36).

Every state change goes through a function here, which (atomically):
validates the allowed transition, validates position occupancy and odometer
consistency, writes a `tyre_movements` row (authoritative history), opens or
closes a `tyre_fitments` period, updates the tyre's denormalised current
state and writes the audit log.  Direct edits of lifecycle fields through the
master screen are blocked.
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit, snapshot
from app.core.errors import BusinessError, NotFound, OverrideRequired
from app.core.utils import add_months, money, now, today
from app.models.fleet import Vehicle
from app.models.tyres import (Tyre, TyreFitment, TyreInspection, TyreLocation, TyreMaintenance, TyreMovement,
                              TyrePosition, TyreRetreading, TyreWarrantyClaim, VehicleTyrePositionConfiguration)
from app.services.rules import rule
from app.services.vehicles import record_odometer

FITTED = {"INSTALLED", "SHIFTED", "FITTED_AFTER_RETREAD"}
STOCK = {"NEW", "IN_STOCK", "REMOVED", "IN_GODOWN", "RETREADED", "UNDER_INSPECTION"}
FINAL = {"SOLD", "LOST"}
LOCKED_FIELDS = {"current_status", "current_vehicle_id", "current_position_id", "current_location_id",
                 "current_install_odometer", "current_odometer", "total_km", "retread_count", "scrap_date",
                 "scrap_reason"}


def _dt(d) -> datetime:
    if isinstance(d, datetime):
        return d
    return datetime.combine(d or today(), time(12, 0))


def _require_status(t: Tyre, allowed: set[str], action: str) -> None:
    if t.current_status not in allowed:
        raise BusinessError(f"Cannot {action}: tyre {t.serial_number} is {t.current_status}. "
                            f"Allowed from: {', '.join(sorted(allowed))}", "INVALID_TRANSITION")


def _current_fitment(db: Session, t: Tyre) -> TyreFitment | None:
    return db.execute(select(TyreFitment).where(TyreFitment.tyre_id == t.id, TyreFitment.current_slot == 1)
                      ).scalar_one_or_none()


def _occupant(db: Session, vehicle_id: int, position_id: int) -> TyreFitment | None:
    return db.execute(select(TyreFitment).where(TyreFitment.vehicle_id == vehicle_id,
                                                TyreFitment.position_id == position_id,
                                                TyreFitment.current_slot == 1)).scalar_one_or_none()


def _check_position(db: Session, vehicle: Vehicle, position_id: int) -> None:
    pos = db.get(TyrePosition, position_id)
    if not pos or not pos.is_active:
        raise BusinessError("Invalid tyre position")
    if vehicle.tyre_layout_id:
        ok = db.execute(select(VehicleTyrePositionConfiguration.id).where(
            VehicleTyrePositionConfiguration.layout_id == vehicle.tyre_layout_id,
            VehicleTyrePositionConfiguration.position_id == position_id)).first()
        if not ok:
            raise BusinessError(f"Position {pos.code} is not part of this vehicle's tyre layout")


def _check_free(db: Session, vehicle_id: int, position_id: int, ignore_tyre: int | None = None) -> None:
    occ = _occupant(db, vehicle_id, position_id)
    if occ and occ.tyre_id != ignore_tyre:
        other = db.get(Tyre, occ.tyre_id)
        pos = db.get(TyrePosition, position_id)
        raise BusinessError(f"Position {pos.code} is already occupied by tyre {other.serial_number}. "
                            "Remove or shift it first.", "POSITION_OCCUPIED")


def _odo(ctx, vehicle_id: int, reading, at: datetime, data: dict) -> None:
    if reading is None:
        raise BusinessError("Odometer reading is required")
    record_odometer(ctx, vehicle_id, reading, at, "TYRE", reason=data.get("override_reason") or data.get("reason"))


def _move(ctx, t: Tyre, mtype: str, at: datetime, before: str, **kw) -> TyreMovement:
    m = TyreMovement(tyre_id=t.id, movement_type=mtype, movement_date=at, status_before=before,
                     status_after=t.current_status, created_by=ctx.user.id, updated_by=ctx.user.id, **kw)
    ctx.db.add(m)
    ctx.db.flush()
    audit(ctx.db, ctx.user, "TYRE_MOVEMENT", "tyres", t.id, {"status": before},
          {"status": t.current_status, "movement": mtype, "movement_id": m.id}, reason=kw.get("reason"))
    return m


def _open_fitment(ctx, t: Tyre, vehicle_id: int, position_id: int, at: datetime, odo, tread) -> TyreFitment:
    f = TyreFitment(tyre_id=t.id, vehicle_id=vehicle_id, position_id=position_id, installed_at=at,
                    install_odometer=odo, install_tread_depth=tread, current_slot=1)
    ctx.db.add(f)
    ctx.db.flush()  # the unique indexes enforce single occupancy here as a last line of defence
    return f


def _close_fitment(ctx, t: Tyre, f: TyreFitment, at: datetime, odo, tread, data: dict) -> Decimal:
    odo = Decimal(odo)
    if odo < f.install_odometer:
        msg = (f"Removal odometer {odo} is lower than installation odometer {f.install_odometer} "
               f"({f.installed_at:%d/%m/%Y})")
        if rule(ctx.db, "TYRE_ODOMETER_DECREASE_MODE") == "WARN":
            ctx.warnings.append(msg)
        elif ctx.override and data.get("reason"):
            ctx.user.require("tyre.override")
            audit(ctx.db, ctx.user, "OVERRIDE", "tyres", t.id, new={"problem": msg}, reason=data.get("reason"))
        else:
            raise OverrideRequired(msg + ". An authorised user may override with a reason.", "TYRE_ODOMETER",
                                   "tyre.override")
    if at < f.installed_at:
        raise BusinessError(f"Date is before the installation date {f.installed_at:%d/%m/%Y}")
    running = max(odo - f.install_odometer, Decimal("0"))
    f.removed_at, f.removal_odometer, f.removal_tread_depth, f.running_km = at, odo, tread, running
    f.current_slot = None
    t.total_km = (t.total_km or 0) + running
    ctx.db.flush()
    return running


def _set_fitted(t: Tyre, vehicle_id, position_id, odo, tread, status=None):
    t.current_status = status or ("FITTED_AFTER_RETREAD" if t.retread_count else "INSTALLED")
    t.current_vehicle_id, t.current_position_id, t.current_location_id = vehicle_id, position_id, None
    t.current_install_odometer = odo
    t.current_odometer = odo
    if tread is not None:
        t.current_tread_depth = tread


def _clear_fitted(t: Tyre):
    t.current_vehicle_id = t.current_position_id = t.current_install_odometer = None


# ───────────────────────── master hooks ─────────────────────────
def tyre_before_save(ctx, t: Tyre, data: dict, is_new: bool) -> None:
    locked = LOCKED_FIELDS & set(data)
    if locked and not is_new:
        raise BusinessError("Lifecycle fields change only through tyre operations (install, remove, retread …). "
                            "Use 'Correction' for audited corrections.")
    t.cost = money(t.cost) if t.cost is not None else None
    if t.cost is not None:
        t.total_cost = money(t.cost) + money(t.gst_amount) - money(t.discount_amount)
    if t.purchase_date and t.warranty_months and not t.warranty_expiry_date:
        t.warranty_expiry_date = add_months(t.purchase_date, t.warranty_months)
    if t.original_tread_depth is not None and is_new:
        t.current_tread_depth = t.original_tread_depth
    if is_new:
        t.current_status = "NEW"
        t.retread_count = 0
        t.total_km = 0


def tyre_after_save(ctx, t: Tyre, data: dict, is_new: bool) -> None:
    if not is_new:
        return
    loc = int(data["initial_location_id"]) if data.get("initial_location_id") else None
    before = t.current_status
    if loc:
        t.current_status, t.current_location_id = "IN_STOCK", loc
    _move(ctx, t, "PURCHASE", _dt(t.purchase_date), before, to_location_id=loc, reference=t.invoice_number,
          reason="Purchase / opening stock", tread_depth=t.original_tread_depth)


# ───────────────────────── operations ─────────────────────────
def install(ctx, t: Tyre, data: dict) -> dict:
    db = ctx.db
    _require_status(t, STOCK, "install")
    v = db.get(Vehicle, int(data["vehicle_id"]))
    pos = int(data["position_id"])
    at = _dt(data.get("date"))
    _check_position(db, v, pos)
    _check_free(db, v.id, pos)
    _odo(ctx, v.id, data.get("odometer"), at, data)
    before, from_loc = t.current_status, t.current_location_id
    _open_fitment(ctx, t, v.id, pos, at, data["odometer"], data.get("tread_depth"))
    _set_fitted(t, v.id, pos, data["odometer"], data.get("tread_depth"))
    _move(ctx, t, "INSTALL", at, before, to_vehicle_id=v.id, to_position_id=pos, from_location_id=from_loc,
          odometer=data["odometer"], tread_depth=data.get("tread_depth"), performed_by=data.get("performed_by"),
          reference=data.get("reference"), reason=data.get("reason"), remarks=data.get("remarks"))
    return {"message": f"Tyre {t.serial_number} installed on {v.registration_number}"}


def shift(ctx, t: Tyre, data: dict) -> dict:
    """Position change on the same vehicle (optionally swapping with the occupant)."""
    db = ctx.db
    _require_status(t, FITTED, "shift")
    f = _current_fitment(db, t)
    v = db.get(Vehicle, f.vehicle_id)
    to_pos = int(data["position_id"])
    if to_pos == f.position_id:
        raise BusinessError("Tyre is already in that position")
    at = _dt(data.get("date"))
    odo = data.get("odometer")
    _check_position(db, v, to_pos)
    occ = _occupant(db, v.id, to_pos)
    if occ and not data.get("swap"):
        _check_free(db, v.id, to_pos)
    _odo(ctx, v.id, odo, at, data)
    from_pos = f.position_id
    moved = [(t, f, to_pos)]
    if occ:
        other = db.get(Tyre, occ.tyre_id)
        moved.append((other, occ, from_pos))
    closed = []
    for tyre, fit, _ in moved:  # close all first so the unique occupancy index never trips
        closed.append(_close_fitment(ctx, tyre, fit, at, odo, data.get("tread_depth") if tyre is t else None, data))
    for (tyre, fit, new_pos), running in zip(moved, closed):
        before = tyre.current_status
        _open_fitment(ctx, tyre, v.id, new_pos, at, odo, data.get("tread_depth") if tyre is t else None)
        _set_fitted(tyre, v.id, new_pos, odo, data.get("tread_depth") if tyre is t else None, "SHIFTED")
        _move(ctx, tyre, "SHIFT", at, before, from_vehicle_id=v.id, to_vehicle_id=v.id, from_position_id=fit.position_id,
              to_position_id=new_pos, odometer=odo, to_odometer=odo, running_km=running,
              tread_depth=data.get("tread_depth") if tyre is t else None, reason=data.get("reason") or
              ("Swap" if tyre is not t else None), performed_by=data.get("performed_by"),
              reference=data.get("reference"))
    return {"message": "Position changed" + (" (swapped)" if occ else "")}


def transfer(ctx, t: Tyre, data: dict) -> dict:
    db = ctx.db
    _require_status(t, FITTED, "transfer")
    f = _current_fitment(db, t)
    src = db.get(Vehicle, f.vehicle_id)
    dst = db.get(Vehicle, int(data["to_vehicle_id"]))
    if dst.id == src.id:
        raise BusinessError("Use 'Shift position' for moves on the same vehicle")
    to_pos = int(data["position_id"])
    at = _dt(data.get("date"))
    _check_position(db, dst, to_pos)
    _check_free(db, dst.id, to_pos)
    _odo(ctx, src.id, data.get("from_odometer"), at, data)
    _odo(ctx, dst.id, data.get("to_odometer"), at, data)
    before = t.current_status
    running = _close_fitment(ctx, t, f, at, data["from_odometer"], data.get("tread_depth"), data)
    _open_fitment(ctx, t, dst.id, to_pos, at, data["to_odometer"], data.get("tread_depth"))
    _set_fitted(t, dst.id, to_pos, data["to_odometer"], data.get("tread_depth"))
    _move(ctx, t, "TRANSFER", at, before, from_vehicle_id=src.id, to_vehicle_id=dst.id, from_position_id=f.position_id,
          to_position_id=to_pos, odometer=data["from_odometer"], to_odometer=data["to_odometer"], running_km=running,
          tread_depth=data.get("tread_depth"), reason=data.get("reason"), reference=data.get("reference"),
          performed_by=data.get("performed_by"))
    return {"message": f"Transferred {src.registration_number} → {dst.registration_number}; ran {running} km"}


def remove(ctx, t: Tyre, data: dict) -> dict:
    db = ctx.db
    _require_status(t, FITTED, "remove")
    f = _current_fitment(db, t)
    at = _dt(data.get("date"))
    _odo(ctx, f.vehicle_id, data.get("odometer"), at, data)
    loc = db.get(TyreLocation, int(data["to_location_id"])) if data.get("to_location_id") else None
    if not loc:
        raise BusinessError("Select the destination (godown / workshop / retreader / scrap yard …)")
    before = t.current_status
    running = _close_fitment(ctx, t, f, at, data["odometer"], data.get("tread_depth"), data)
    _clear_fitted(t)
    t.current_location_id = loc.id
    t.current_odometer = None
    if data.get("tread_depth") is not None:
        t.current_tread_depth = data["tread_depth"]
    t.current_status = data.get("new_status") or ("IN_GODOWN" if loc.location_type == "GODOWN" else "REMOVED")
    if t.current_status not in {"REMOVED", "IN_GODOWN", "UNDER_INSPECTION", "DAMAGED"}:
        raise BusinessError("Invalid status after removal")
    _move(ctx, t, "REMOVE", at, before, from_vehicle_id=f.vehicle_id, from_position_id=f.position_id,
          to_location_id=loc.id, odometer=data["odometer"], tread_depth=data.get("tread_depth"), running_km=running,
          reason=data.get("reason"), reference=data.get("reference"), performed_by=data.get("performed_by"))
    return {"message": f"Removed after {running} km", "running_km": str(running)}


def move_location(ctx, t: Tyre, data: dict) -> dict:
    _require_status(t, STOCK | {"DAMAGED"}, "move")
    before, frm = t.current_status, t.current_location_id
    t.current_location_id = int(data["to_location_id"])
    if data.get("new_status"):
        if data["new_status"] not in {"IN_STOCK", "IN_GODOWN", "UNDER_INSPECTION", "DAMAGED", "REMOVED"}:
            raise BusinessError("Invalid status")
        t.current_status = data["new_status"]
    _move(ctx, t, "MOVE_LOCATION", _dt(data.get("date")), before, from_location_id=frm,
          to_location_id=t.current_location_id, reason=data.get("reason"), reference=data.get("reference"))
    return {"message": "Location updated"}


def send_retread(ctx, t: Tyre, data: dict) -> dict:
    _require_status(t, STOCK | {"DAMAGED"}, "send for retreading")
    at = _dt(data.get("date"))
    r = TyreRetreading(tyre_id=t.id, vendor_id=data.get("vendor_id"), sent_date=at.date(),
                       tread_condition=data.get("tread_condition"), tread_depth=data.get("tread_depth"),
                       retread_type=data.get("retread_type"), status="SENT", remarks=data.get("remarks"),
                       created_by=ctx.user.id, updated_by=ctx.user.id)
    ctx.db.add(r)
    before, frm = t.current_status, t.current_location_id
    t.current_status = "SENT_FOR_RETREADING"
    t.current_location_id = data.get("to_location_id") or t.current_location_id
    ctx.db.flush()
    _move(ctx, t, "SEND_RETREAD", at, before, from_location_id=frm, to_location_id=t.current_location_id,
          tread_depth=data.get("tread_depth"), reference=f"RETREAD#{r.id}", reason=data.get("reason"))
    return {"message": "Sent for retreading", "retread_id": r.id}


def receive_retread(ctx, t: Tyre, data: dict) -> dict:
    db = ctx.db
    _require_status(t, {"SENT_FOR_RETREADING"}, "receive from retreading")
    r = db.execute(select(TyreRetreading).where(TyreRetreading.tyre_id == t.id, TyreRetreading.status == "SENT")
                   .order_by(TyreRetreading.id.desc())).scalars().first()
    if not r:
        raise NotFound("Open retreading record")
    at = _dt(data.get("date"))
    before = t.current_status
    r.return_date = at.date()
    r.cost, r.gst_amount, r.invoice_number = data.get("cost"), data.get("gst_amount"), data.get("invoice_number")
    r.new_tread_depth, r.new_pattern, r.retread_serial = (data.get("new_tread_depth"), data.get("new_pattern"),
                                                          data.get("retread_serial"))
    r.warranty_km, r.warranty_months = data.get("warranty_km"), data.get("warranty_months")
    if data.get("rejected"):
        r.status = "REJECTED"
        t.current_status = "DAMAGED"
    else:
        r.status = "RETURNED"
        t.retread_count = (t.retread_count or 0) + 1  # only ever incremented here (controlled lifecycle)
        t.current_status = "RETREADED"
        if r.new_tread_depth is not None:
            t.current_tread_depth = r.new_tread_depth
        if r.new_pattern:
            t.pattern = r.new_pattern
    t.current_location_id = data.get("to_location_id") or t.current_location_id
    _move(ctx, t, "RECEIVE_RETREAD", at, before, to_location_id=t.current_location_id,
          tread_depth=r.new_tread_depth, reference=f"RETREAD#{r.id} {r.invoice_number or ''}".strip(),
          reason="Rejected by retreader" if data.get("rejected") else data.get("reason"))
    return {"message": "Retreading rejected" if data.get("rejected") else f"Retreaded (count {t.retread_count})"}


def inspect(ctx, t: Tyre, data: dict) -> dict:
    db = ctx.db
    f = _current_fitment(db, t)
    ins = TyreInspection(tyre_id=t.id, inspection_date=data.get("date") or today(),
                         vehicle_id=f.vehicle_id if f else None, position_id=f.position_id if f else None,
                         odometer=data.get("odometer"), tread_depth=data.get("tread_depth"),
                         pressure_psi=data.get("pressure_psi"), condition=data.get("condition"),
                         damage=data.get("damage"), recommended_action=data.get("recommended_action"),
                         inspector=data.get("inspector"), remarks=data.get("remarks"), created_by=ctx.user.id)
    db.add(ins)
    if data.get("tread_depth") is not None:
        t.current_tread_depth = data["tread_depth"]
    if f and data.get("odometer") is not None:
        record_odometer(ctx, f.vehicle_id, data["odometer"], _dt(data.get("date")), "TYRE",
                        reason=data.get("reason"))
        t.current_odometer = data["odometer"]
    thr = Decimal(rule(db, "TYRE_MIN_TREAD_MM"))
    if t.current_tread_depth is not None and Decimal(t.current_tread_depth) <= thr:
        from app.services.notifications import notify
        notify(db, "TYRE_TREAD_LOW", f"Tyre {t.serial_number}: tread {t.current_tread_depth} mm ≤ {thr} mm",
               data.get("recommended_action"), severity="WARNING", entity_type="tyres", entity_id=t.id,
               link_url=f"/tyres/dashboard?tyre={t.id}", dedupe_key=f"tread:{t.id}:{t.current_tread_depth}")
        ctx.warnings.append("Tread depth at or below threshold")
    db.flush()
    audit(db, ctx.user, "CREATE", "tyre_inspections", ins.id, new=snapshot(ins))
    return {"message": "Inspection recorded"}


def maintain(ctx, t: Tyre, data: dict) -> dict:
    f = _current_fitment(ctx.db, t)
    m = TyreMaintenance(tyre_id=t.id, maintenance_type=data["maintenance_type"],
                        maintenance_date=data.get("date") or today(), vehicle_id=f.vehicle_id if f else None,
                        position_id=f.position_id if f else None, odometer=data.get("odometer"),
                        vendor_id=data.get("vendor_id"), cost=money(data.get("cost")),
                        gst_amount=money(data.get("gst_amount")), invoice_number=data.get("invoice_number"),
                        remarks=data.get("remarks"), created_by=ctx.user.id)
    ctx.db.add(m)
    ctx.db.flush()
    audit(ctx.db, ctx.user, "CREATE", "tyre_maintenance", m.id, new=snapshot(m))
    return {"message": "Tyre maintenance recorded"}


def raise_warranty(ctx, t: Tyre, data: dict) -> dict:
    _require_status(t, STOCK | {"DAMAGED"}, "raise a warranty claim (remove the tyre first)")
    c = TyreWarrantyClaim(tyre_id=t.id, warranty_provider_id=data.get("warranty_provider_id") or t.supplier_id,
                          vendor_id=data.get("vendor_id") or t.supplier_id, claim_number=data["claim_number"],
                          claim_date=data.get("date") or today(), failure_date=data.get("failure_date"),
                          failure_reason=data.get("failure_reason"), evidence=data.get("evidence"),
                          km_at_failure=t.total_km, tread_depth_at_failure=t.current_tread_depth,
                          claim_amount=data.get("claim_amount"), status="SUBMITTED", remarks=data.get("remarks"),
                          created_by=ctx.user.id)
    ctx.db.add(c)
    before = t.current_status
    t.current_status = "WARRANTY"
    ctx.db.flush()
    _move(ctx, t, "SEND_WARRANTY", _dt(c.claim_date), before, reference=c.claim_number,
          reason=c.failure_reason)
    return {"message": "Warranty claim raised", "claim_id": c.id}


def resolve_warranty(ctx, c: TyreWarrantyClaim, data: dict) -> dict:
    db = ctx.db
    if c.status in ("REJECTED", "SETTLED"):
        raise BusinessError("Claim already closed")
    t = db.get(Tyre, c.tyre_id)
    c.status = data["status"]
    c.approved_amount = data.get("approved_amount")
    c.resolution_type = data.get("resolution_type")
    c.replacement_tyre_id = data.get("replacement_tyre_id")
    c.resolution_date = data.get("resolution_date") or today()
    c.remarks = data.get("remarks") or c.remarks
    before = t.current_status
    if c.status in ("APPROVED", "SETTLED"):
        t.current_status = "SCRAPPED"
        t.scrap_date, t.scrap_reason = c.resolution_date, f"Warranty {c.resolution_type or ''} {c.claim_number}"
    elif c.status == "REJECTED":
        t.current_status = "DAMAGED"
    if before != t.current_status:
        _move(ctx, t, "WARRANTY_RESOLVED", _dt(c.resolution_date), before, reference=c.claim_number,
              reason=f"{c.status} {c.resolution_type or ''}".strip())
    audit(db, ctx.user, "UPDATE", "tyre_warranty_claims", c.id, new=snapshot(c))
    return {"message": f"Claim {c.status}"}


def scrap(ctx, t: Tyre, data: dict) -> dict:
    _require_status(t, STOCK | {"DAMAGED", "WARRANTY"}, "scrap")
    before = t.current_status
    t.current_status = "SCRAPPED"
    t.scrap_date = data.get("date") or today()
    t.scrap_reason = data.get("reason")
    t.scrap_value = data.get("scrap_value")
    t.current_location_id = data.get("to_location_id") or t.current_location_id
    _move(ctx, t, "SCRAP", _dt(t.scrap_date), before, to_location_id=t.current_location_id, reason=t.scrap_reason)
    return {"message": "Tyre scrapped"}


def dispose(ctx, t: Tyre, data: dict) -> dict:
    kind = data["disposal"]  # SOLD / LOST
    if kind == "SOLD":
        _require_status(t, STOCK | {"DAMAGED", "SCRAPPED"}, "sell")
        t.scrap_value = data.get("sale_value") or t.scrap_value
    elif kind == "LOST":
        if t.current_status in FINAL:
            raise BusinessError("Tyre already disposed")
        f = _current_fitment(ctx.db, t)
        if f:
            raise BusinessError("Remove the tyre from the vehicle before marking it lost")
    else:
        raise BusinessError("Invalid disposal")
    before = t.current_status
    t.current_status = kind
    _move(ctx, t, "SELL" if kind == "SOLD" else "LOST", _dt(data.get("date")), before, reason=data.get("reason"),
          reference=data.get("reference"))
    return {"message": f"Tyre marked {kind}"}


def correct(ctx, t: Tyre, data: dict) -> dict:
    """Audited correction of counters (retread count, tread, total km). Requires permission + reason."""
    ctx.user.require("tyre.correct")
    old = snapshot(t)
    for f in ("retread_count", "current_tread_depth", "total_km"):
        if data.get(f) is not None:
            setattr(t, f, data[f])
    _move(ctx, t, "CORRECTION", now(), t.current_status, reason=data["reason"], is_override=True,
          override_reason=data["reason"], remarks=str({k: data.get(k) for k in ("retread_count", "current_tread_depth",
                                                                                "total_km") if data.get(k) is not None}))
    audit(ctx.db, ctx.user, "OVERRIDE", "tyres", t.id, old, snapshot(t), reason=data["reason"])
    from app.services import approvals
    r = approvals.requires_approval(ctx.db, "TYRE_CORRECTION")
    if r:
        approvals.create_request(ctx.db, ctx.user, r, "TYRE_CORRECTION", "tyres", t.id,
                                 f"Tyre {t.serial_number} correction: {data['reason']}")
    return {"message": "Correction recorded"}


# ───────────────────────── queries ─────────────────────────
def vehicle_tyres(db: Session, vehicle_id: int) -> dict:
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise NotFound("Vehicle")
    positions = []
    if v.tyre_layout_id:
        rows = db.execute(select(VehicleTyrePositionConfiguration, TyrePosition).join(
            TyrePosition, TyrePosition.id == VehicleTyrePositionConfiguration.position_id).where(
            VehicleTyrePositionConfiguration.layout_id == v.tyre_layout_id)
            .order_by(VehicleTyrePositionConfiguration.display_row, VehicleTyrePositionConfiguration.display_col)).all()
        positions = [{"position_id": p.id, "code": p.code, "name": p.name, "row": c.display_row, "col": c.display_col,
                      "spare": c.is_spare} for c, p in rows]
    fits = db.execute(select(TyreFitment, Tyre).join(Tyre, Tyre.id == TyreFitment.tyre_id).where(
        TyreFitment.vehicle_id == vehicle_id, TyreFitment.current_slot == 1)).all()
    by_pos = {}
    cur_odo = v.current_odometer
    for f, t in fits:
        running = (Decimal(cur_odo) - f.install_odometer) if cur_odo is not None else None
        by_pos[f.position_id] = {
            "tyre_id": t.id, "serial": t.serial_number, "brand": t.brand, "model": t.model, "size": t.size,
            "tread_depth": t.current_tread_depth, "installed_at": f.installed_at.isoformat(),
            "install_odometer": f.install_odometer, "current_odometer": cur_odo, "running_km": running,
            "total_km": (t.total_km or 0) + (running or 0), "status": t.current_status, "retread_count": t.retread_count,
            "low_tread": t.current_tread_depth is not None and Decimal(t.current_tread_depth) <= Decimal(
                rule(db, "TYRE_MIN_TREAD_MM"))}
    known = {p["position_id"] for p in positions}
    for pid in by_pos:
        if pid not in known:  # fitted to a position outside the layout (legacy data) → still shown
            p = db.get(TyrePosition, pid)
            positions.append({"position_id": pid, "code": p.code, "name": p.name, "row": 99, "col": len(positions) + 1,
                              "spare": False})
    for p in positions:
        p["tyre"] = by_pos.get(p["position_id"])
    return {"vehicle": {"id": v.id, "registration_number": v.registration_number, "current_odometer": cur_odo,
                        "layout_id": v.tyre_layout_id}, "positions": positions}


_LABELS = {"PURCHASE": "Purchased", "INSTALL": "Installed", "SHIFT": "Position changed", "TRANSFER": "Transferred",
           "REMOVE": "Removed", "MOVE_LOCATION": "Moved", "SEND_RETREAD": "Sent for retreading",
           "RECEIVE_RETREAD": "Received from retreading", "SEND_WARRANTY": "Warranty claim",
           "WARRANTY_RESOLVED": "Warranty resolved", "SCRAP": "Scrapped", "SELL": "Sold", "LOST": "Lost",
           "CORRECTION": "Correction"}


def timeline(db: Session, tyre_id: int) -> list[dict]:
    from app.core.utils import jsonable
    vehicles, positions, locations = {}, {}, {}

    def name(M, cache, i, attr):
        if not i:
            return None
        if i not in cache:
            o = db.get(M, i)
            cache[i] = getattr(o, attr) if o else f"#{i}"
        return cache[i]

    out = []
    for m in db.execute(select(TyreMovement).where(TyreMovement.tyre_id == tyre_id)
                        .order_by(TyreMovement.movement_date, TyreMovement.id)).scalars():
        out.append({**{c.key: jsonable(getattr(m, c.key)) for c in TyreMovement.__table__.columns},
                    "label": _LABELS.get(m.movement_type, m.movement_type),
                    "from_vehicle": name(Vehicle, vehicles, m.from_vehicle_id, "registration_number"),
                    "to_vehicle": name(Vehicle, vehicles, m.to_vehicle_id, "registration_number"),
                    "from_position": name(TyrePosition, positions, m.from_position_id, "code"),
                    "to_position": name(TyrePosition, positions, m.to_position_id, "code"),
                    "from_location": name(TyreLocation, locations, m.from_location_id, "name"),
                    "to_location": name(TyreLocation, locations, m.to_location_id, "name")})
    return out


def tyre_cost(db: Session, t: Tyre) -> dict:
    inc_gst = rule(db, "TYRE_COST_INCLUDE_GST")
    purchase = money(t.cost) + (money(t.gst_amount) if inc_gst else 0) - money(t.discount_amount)
    retreads = db.execute(select(func.coalesce(func.sum(TyreRetreading.cost), 0),
                                 func.coalesce(func.sum(TyreRetreading.gst_amount), 0)).where(
        TyreRetreading.tyre_id == t.id, TyreRetreading.status == "RETURNED")).one()
    retread = money(retreads[0]) + (money(retreads[1]) if inc_gst else 0)
    maint = db.execute(select(func.coalesce(func.sum(TyreMaintenance.cost), 0),
                              func.coalesce(func.sum(TyreMaintenance.gst_amount), 0)).where(
        TyreMaintenance.tyre_id == t.id)).one()
    repair = money(maint[0]) + (money(maint[1]) if inc_gst else 0)
    warranty = money(db.execute(select(func.coalesce(func.sum(TyreWarrantyClaim.approved_amount), 0)).where(
        TyreWarrantyClaim.tyre_id == t.id, TyreWarrantyClaim.status.in_(["APPROVED", "SETTLED"]))).scalar_one()) \
        if rule(db, "TYRE_COST_DEDUCT_WARRANTY") else Decimal("0")
    scrap_v = money(t.scrap_value) if rule(db, "TYRE_COST_DEDUCT_SCRAP") and t.current_status in (
        "SCRAPPED", "SOLD") else Decimal("0")
    net = purchase + retread + repair - warranty - scrap_v
    km = Decimal(t.total_km or 0)
    f = db.execute(select(TyreFitment).where(TyreFitment.tyre_id == t.id, TyreFitment.current_slot == 1)).scalar_one_or_none()
    if f:
        v = db.get(Vehicle, f.vehicle_id)
        if v and v.current_odometer is not None and v.current_odometer > f.install_odometer:
            km += Decimal(v.current_odometer) - f.install_odometer
    return {"purchase": purchase, "retreading": retread, "repairs": repair, "warranty_credit": warranty,
            "scrap_value": scrap_v, "net_cost": net, "km": km,
            "cost_per_km": (net / km).quantize(Decimal("0.0001")) if km > 0 else None}


def tyre_extra(ctx, t: Tyre, row: dict) -> None:
    v = ctx.db.get(Vehicle, t.current_vehicle_id) if t.current_vehicle_id else None
    p = ctx.db.get(TyrePosition, t.current_position_id) if t.current_position_id else None
    loc = ctx.db.get(TyreLocation, t.current_location_id) if t.current_location_id else None
    row["current_vehicle"] = v.registration_number if v else None
    row["current_position"] = p.code if p else None
    row["current_location"] = loc.name if loc else None


def claim_for_tyre(db: Session, claim_id: int) -> TyreWarrantyClaim:
    c = db.get(TyreWarrantyClaim, claim_id)
    if not c:
        raise NotFound("Warranty claim")
    return c
