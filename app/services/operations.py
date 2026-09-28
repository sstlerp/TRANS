"""Fuel and toll processing shared by manual entry, Excel import and API feeds
(spec §26-§28). One code path → one normalised table per domain."""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import audit, snapshot
from app.core.errors import BusinessError, Conflict, OverrideRequired
from app.core.utils import money, normalize_text, normalize_vehicle_number, now, sha256_of
from app.models.fleet import FuelType, OdometerReading, Vehicle
from app.models.imports import ValueMapping
from app.models.operations import FuelCard, FuelStation, FuelTransaction, TollPlaza, TollTransaction, TollVehicleMapping
from app.services.rules import rule
from app.services.vehicles import allowed_fuel_type_ids, cost_center_for, record_odometer


# ───────────────────────── shared matching ─────────────────────────
def mapped_value(db: Session, mapping_type: str, provider_id: int | None, source: str) -> ValueMapping | None:
    src = normalize_text(source)
    rows = db.execute(select(ValueMapping).where(ValueMapping.mapping_type == mapping_type,
                                                 ValueMapping.is_active.is_(True),
                                                 func.upper(ValueMapping.source_value) == src)).scalars().all()
    specific = [r for r in rows if r.provider_id == provider_id]
    return (specific or [r for r in rows if r.provider_id is None] or [None])[0]


def match_vehicle(db: Session, provider_id: int | None, raw_number: str | None, on: date | None = None,
                  fastag: str | None = None, card: str | None = None) -> int | None:
    """Deterministic vehicle matching; returns None rather than guessing."""
    on = on or date.today()
    norm = normalize_vehicle_number(raw_number)
    eff = lambda M: and_(or_(M.effective_from.is_(None), M.effective_from <= on),  # noqa: E731
                         or_(M.effective_to.is_(None), M.effective_to >= on))
    if provider_id and (norm or fastag):
        conds = []
        if norm:
            conds.append(func.upper(func.replace(func.replace(TollVehicleMapping.external_vehicle_number, " ", ""),
                                                 "-", "")) == norm)
        if fastag:
            conds.append(TollVehicleMapping.fastag_id == fastag)
        m = db.execute(select(TollVehicleMapping.vehicle_id).where(
            TollVehicleMapping.provider_id == provider_id, TollVehicleMapping.is_active.is_(True),
            or_(*conds), eff(TollVehicleMapping))).first()
        if m:
            return m[0]
    if card and provider_id:
        c = db.execute(select(FuelCard.vehicle_id).where(FuelCard.provider_id == provider_id,
                                                         FuelCard.card_number == card.strip(),
                                                         FuelCard.is_active.is_(True), eff(FuelCard))).first()
        if c and c[0]:
            return c[0]
    if norm:
        v = db.execute(select(Vehicle.id).where(Vehicle.registration_normalized == norm)).first()
        if v:
            return v[0]
        vm = mapped_value(db, "VEHICLE", provider_id, norm)
        if vm and vm.target_id:
            return vm.target_id
    return None


# ───────────────────────── fuel ─────────────────────────
def match_fuel_type(db: Session, provider_id: int | None, raw: str | None) -> int | None:
    if not raw:
        return None
    s = normalize_text(raw)
    ft = db.execute(select(FuelType.id).where(or_(func.upper(FuelType.code) == s, func.upper(FuelType.name) == s))
                    ).first()
    if ft:
        return ft[0]
    vm = mapped_value(db, "FUEL_TYPE", provider_id, s)
    if vm:
        if vm.target_id:
            return vm.target_id
        if vm.target_value:
            ft = db.execute(select(FuelType.id).where(func.upper(FuelType.code) == vm.target_value.upper())).first()
            return ft[0] if ft else None
    return None


def match_station(db: Session, provider_id: int | None, code: str | None, name: str | None) -> int | None:
    if code:
        q = select(FuelStation.id).where(FuelStation.station_code == code.strip())
        if provider_id:
            q = q.where(or_(FuelStation.provider_id == provider_id, FuelStation.provider_id.is_(None)))
        r = db.execute(q).first()
        if r:
            return r[0]
    if name:
        r = db.execute(select(FuelStation.id).where(func.upper(FuelStation.name) == normalize_text(name))).first()
        if r:
            return r[0]
        vm = mapped_value(db, "FUEL_STATION", provider_id, name)
        if vm and vm.target_id:
            return vm.target_id
    return None


def fuel_hash(t: FuelTransaction) -> str:
    return sha256_of("FUEL", t.provider_id, t.provider_transaction_id, t.vehicle_id or t.vehicle_number_raw,
                     t.txn_datetime, t.quantity, t.amount)


def process_fuel(ctx, t: FuelTransaction, mode: str = "MANUAL") -> list[str]:
    """Match, validate and enrich a fuel transaction.

    mode=MANUAL: rule violations raise OverrideRequired unless an authorised
    override with reason is supplied.  mode=IMPORT: provider data is recorded
    as-is and violations set status FLAGGED for review.
    """
    db = ctx.db
    flags: list[str] = []
    if t.txn_datetime is None:
        raise BusinessError("Transaction date/time is required")
    t.txn_date = t.txn_datetime.date()
    if t.vehicle_id is None:
        t.vehicle_id = match_vehicle(db, t.provider_id, t.vehicle_number_raw, t.txn_date, card=t.card_number)
    if t.vehicle_id is None:
        flags.append("VEHICLE_UNMATCHED")
    if t.fuel_type_id is None and t.fuel_type_raw:
        t.fuel_type_id = match_fuel_type(db, t.provider_id, t.fuel_type_raw)
    if t.fuel_type_id is None:
        flags.append("FUEL_TYPE_UNMATCHED")
    if t.fuel_station_id is None and t.station_raw:
        t.fuel_station_id = match_station(db, t.provider_id, None, t.station_raw)
    if t.unit_id is None and t.fuel_type_id:
        ft = db.get(FuelType, t.fuel_type_id)
        t.unit_id = ft.default_unit_id if ft else None
    if t.quantity is None or t.quantity <= 0:
        raise BusinessError("Quantity must be greater than zero")
    t.tax_amount = t.tax_amount or Decimal("0")
    t.discount_amount = t.discount_amount or Decimal("0")
    if t.amount is None and t.rate is not None:
        t.amount = (t.quantity * t.rate).quantize(Decimal("0.01"))
    if t.amount is None:
        raise BusinessError("Amount is required")
    t.amount = money(t.amount)
    if t.total_amount is None:
        t.total_amount = t.amount + money(t.tax_amount) - money(t.discount_amount)
    t.total_amount = money(t.total_amount)
    if t.rate is None and t.quantity:
        t.rate = (t.amount / t.quantity).quantize(Decimal("0.0001"))

    problems: list[tuple[str, str, str]] = []  # (flag, message, override permission)
    # quantity × rate ≈ amount (configurable tolerance for tax / discount / rounding / fees)
    expected = (t.quantity * t.rate).quantize(Decimal("0.01"))
    diff = abs(expected - t.amount)
    tol = max(Decimal(rule(db, "FUEL_AMOUNT_TOLERANCE_ABS")),
              t.amount * Decimal(rule(db, "FUEL_AMOUNT_TOLERANCE_PCT")) / 100)
    if diff > tol:
        problems.append(("AMOUNT_MISMATCH", f"Quantity × rate = {expected} differs from amount {t.amount} "
                                            f"by {diff} (tolerance {tol.quantize(Decimal('0.01'))})", "fuel.override"))
    # fuel type vs vehicle configuration
    if t.vehicle_id and t.fuel_type_id:
        allowed = allowed_fuel_type_ids(db, t.vehicle_id, t.txn_date)
        mode_c = rule(db, "FUEL_COMPATIBILITY_MODE")
        if allowed and t.fuel_type_id not in allowed and mode_c != "IGNORE":
            ft = db.get(FuelType, t.fuel_type_id)
            msg = f"Fuel type {ft.name if ft else t.fuel_type_id} is not configured for this vehicle"
            if mode_c == "WARN":
                ctx.warnings.append(msg)
                flags.append("FUEL_TYPE_INCOMPATIBLE")
            else:
                problems.append(("FUEL_TYPE_INCOMPATIBLE", msg, "fuel.override"))
    if mode == "MANUAL" and problems:
        if not (ctx.override and ctx.reason):
            p = problems[0]
            raise OverrideRequired("; ".join(x[1] for x in problems) + ". Authorised users may override with a reason.",
                                   p[0], p[2])
        for p in problems:
            ctx.user.require(p[2])
        t.override_reason = ctx.reason
        t.override_by = ctx.user.id
        audit(db, ctx.user, "OVERRIDE", "fuel_transactions", t.id, new={"flags": [p[0] for p in problems]},
              reason=ctx.reason)
    flags += [p[0] for p in problems]

    if t.vehicle_id:
        t.cost_center_id = cost_center_for(db, t.vehicle_id, t.txn_date)
        if t.id:
            db.execute(delete(OdometerReading).where(OdometerReading.source_module == "FUEL",
                                                     OdometerReading.source_entity_id == t.id))
        if t.odometer is not None:
            saved_override = ctx.override
            try:
                if mode == "IMPORT":
                    ctx_w = list(ctx.warnings)
                    try:
                        t._odo = record_odometer(ctx, t.vehicle_id, t.odometer, t.txn_datetime, "FUEL", t.id)
                    except OverrideRequired as exc:
                        flags.append("ODOMETER_INCONSISTENT")
                        ctx.warnings[:] = ctx_w + [exc.message]
                else:
                    t._odo = record_odometer(ctx, t.vehicle_id, t.odometer, t.txn_datetime, "FUEL", t.id,
                                             reason=ctx.reason)
            finally:
                ctx.override = saved_override
        _efficiency(db, t, flags)
    else:
        t.cost_center_id = t.cost_center_id  # stays None → pending allocation / review
    t.validation_flags = flags or None
    if "VEHICLE_UNMATCHED" in flags:
        t.status = "VEHICLE_UNMATCHED"
    elif problems and mode == "MANUAL":
        t.status = "OVERRIDDEN"
    elif any(f for f in flags if f not in ("EFFICIENCY_LOW", "EFFICIENCY_HIGH")):
        t.status = "FLAGGED"
    else:
        t.status = "VALIDATED"
    t.txn_hash = fuel_hash(t)
    return flags


def _efficiency(db: Session, t: FuelTransaction, flags: list[str]) -> None:
    t.km_since_last = t.efficiency = None
    t.efficiency_flag = "NA"
    if not rule(db, "FUEL_EFFICIENCY_ENABLED") or t.odometer is None or not t.fuel_type_id:
        return
    prev = db.execute(select(FuelTransaction).where(
        FuelTransaction.vehicle_id == t.vehicle_id, FuelTransaction.fuel_type_id == t.fuel_type_id,
        FuelTransaction.odometer.is_not(None), FuelTransaction.txn_datetime < t.txn_datetime,
        FuelTransaction.status != "CANCELLED", FuelTransaction.id != (t.id or 0))
        .order_by(FuelTransaction.txn_datetime.desc())).scalars().first()
    if not prev or t.odometer <= prev.odometer or not t.quantity:
        return
    t.km_since_last = t.odometer - prev.odometer
    t.efficiency = (t.km_since_last / t.quantity).quantize(Decimal("0.001"))
    ft = db.get(FuelType, t.fuel_type_id)
    t.efficiency_flag = "NORMAL"
    if ft and ft.min_efficiency is not None and t.efficiency < ft.min_efficiency:
        t.efficiency_flag = "LOW"
        flags.append("EFFICIENCY_LOW")
    elif ft and ft.max_efficiency is not None and t.efficiency > ft.max_efficiency:
        t.efficiency_flag = "HIGH"
        flags.append("EFFICIENCY_HIGH")


def fuel_before_save(ctx, t: FuelTransaction, data: dict, is_new: bool) -> None:
    if is_new:
        t.source_type = t.source_type or "MANUAL"
    if t.txn_datetime is None and data.get("txn_date"):
        from app.core.utils import parse_date
        t.txn_datetime = datetime.combine(parse_date(data["txn_date"]), time())
    ctx.override = bool(data.get("override"))
    ctx.reason = data.get("override_reason") or data.get("reason")
    process_fuel(ctx, t, "MANUAL")
    if not t.provider_transaction_id:
        dup = ctx.db.execute(select(FuelTransaction.id).where(FuelTransaction.txn_hash == t.txn_hash,
                                                              FuelTransaction.id != (t.id or 0))).first()
        if dup:
            raise Conflict(f"Possible duplicate of fuel transaction #{dup[0]} (same vehicle, time, quantity, amount)",
                           "DUPLICATE")


def link_odometer(t) -> None:
    r = getattr(t, "_odo", None)
    if r is not None and t.id:
        r.source_entity_id = t.id


def fuel_after_save(ctx, t: FuelTransaction, data: dict, is_new: bool) -> None:
    link_odometer(t)


def fuel_efficiency_report(db: Session, start: date, end: date, vehicle_id: int | None = None) -> list[dict]:
    q = select(FuelTransaction.vehicle_id, FuelTransaction.fuel_type_id, func.sum(FuelTransaction.km_since_last),
               func.sum(FuelTransaction.quantity), func.sum(FuelTransaction.total_amount), func.count(),
               func.sum(case((FuelTransaction.efficiency_flag.in_(["LOW", "HIGH"]), 1), else_=0))).where(
        FuelTransaction.txn_date.between(start, end), FuelTransaction.vehicle_id.is_not(None),
        FuelTransaction.status != "CANCELLED")
    if vehicle_id:
        q = q.where(FuelTransaction.vehicle_id == vehicle_id)
    rows = db.execute(q.group_by(FuelTransaction.vehicle_id, FuelTransaction.fuel_type_id)).all()
    out = []
    for vid, ftid, km, qty_eff, amt, n, unusual in rows:
        v, ft = db.get(Vehicle, vid), db.get(FuelType, ftid) if ftid else None
        # efficiency uses only fills that had a valid previous odometer (km_since_last not null)
        eff_qty = db.execute(select(func.sum(FuelTransaction.quantity)).where(
            FuelTransaction.vehicle_id == vid, FuelTransaction.fuel_type_id == ftid,
            FuelTransaction.txn_date.between(start, end), FuelTransaction.km_since_last.is_not(None))).scalar()
        out.append({"vehicle": v.registration_number if v else vid, "fuel_type": ft.name if ft else "-",
                    "unit": ft.efficiency_label if ft else "", "fills": n, "quantity": qty_eff, "amount": amt,
                    "km": km, "efficiency": (km / eff_qty).quantize(Decimal("0.01")) if km and eff_qty else None,
                    "unusual_fills": int(unusual or 0)})
    return out


# ───────────────────────── toll ─────────────────────────
def match_plaza(db: Session, provider_id: int | None, ext_id: str | None, code: str | None,
                name: str | None) -> int | None:
    if ext_id:
        r = db.execute(select(TollPlaza.id).where(TollPlaza.external_plaza_id == ext_id.strip())).first()
        if r:
            return r[0]
    if code:
        r = db.execute(select(TollPlaza.id).where(func.upper(TollPlaza.plaza_code) == normalize_text(code))).first()
        if r:
            return r[0]
    for raw in (ext_id, code, name):
        if raw:
            vm = mapped_value(db, "TOLL_PLAZA", provider_id, raw)
            if vm and vm.target_id:
                return vm.target_id
    if name:
        r = db.execute(select(TollPlaza.id).where(func.upper(TollPlaza.name) == normalize_text(name))).all()
        if len(r) == 1:  # ambiguous names are never guessed
            return r[0][0]
    return None


def toll_hash(t: TollTransaction) -> str:
    return sha256_of("TOLL", t.provider_id, t.transaction_id)


def process_toll(ctx, t: TollTransaction) -> list[str]:
    db = ctx.db
    if t.amount is None:
        raise BusinessError("Amount is required")
    if t.txn_datetime and not t.txn_date:
        t.txn_date = t.txn_datetime.date()
    if t.txn_date and t.txn_time and not t.txn_datetime:
        t.txn_datetime = datetime.combine(t.txn_date, t.txn_time)
    if t.txn_datetime and not t.txn_time:
        t.txn_time = t.txn_datetime.time()
    t.registration_normalized = normalize_vehicle_number(t.registration_raw) or None
    if t.vehicle_id is None:
        t.vehicle_id = match_vehicle(db, t.provider_id, t.registration_raw, t.txn_date, fastag=t.fastag_id)
    if t.toll_plaza_id is None:
        t.toll_plaza_id = match_plaza(db, t.provider_id, t.plaza_external_id_raw, t.plaza_code_raw, t.plaza_name_raw)
    t.vehicle_match_status = "VEHICLE_MATCHED" if t.vehicle_id else "VEHICLE_UNMATCHED"
    t.plaza_match_status = "PLAZA_MATCHED" if t.toll_plaza_id else "PLAZA_UNMATCHED"
    t.cost_center_id = cost_center_for(db, t.vehicle_id, t.txn_date) if t.vehicle_id else None
    if not t.vehicle_id:
        t.status = "VEHICLE_UNMATCHED"
    elif not t.toll_plaza_id and rule(db, "TOLL_PLAZA_REQUIRED"):
        t.status = "PLAZA_UNMATCHED"
    elif not t.toll_plaza_id:
        t.status = "VEHICLE_MATCHED"
    else:
        t.status = "VALIDATED"
    t.txn_hash = toll_hash(t)
    return [s for s in (t.vehicle_match_status, t.plaza_match_status) if s.endswith("UNMATCHED")]


def toll_before_save(ctx, t: TollTransaction, data: dict, is_new: bool) -> None:
    if is_new:
        t.source_type = t.source_type or "MANUAL"
        if not t.transaction_id:
            t.transaction_id = f"MAN-{now():%Y%m%d%H%M%S}-{ctx.user.id}"
        dup = ctx.db.execute(select(TollTransaction.id).where(TollTransaction.provider_id == t.provider_id,
                                                              TollTransaction.transaction_id == t.transaction_id)).first()
        if dup:
            raise Conflict(f"Duplicate: provider already has transaction {t.transaction_id}", "DUPLICATE")
    process_toll(ctx, t)


def toll_resolve(ctx, t: TollTransaction, data: dict) -> dict:
    """Authorised manual resolution of an unmatched toll row; optionally learn a mapping."""
    db = ctx.db
    old = snapshot(t)
    if data.get("vehicle_id"):
        t.vehicle_id = int(data["vehicle_id"])
        if data.get("create_mapping") and (t.registration_raw or t.fastag_id):
            db.add(TollVehicleMapping(provider_id=t.provider_id, external_vehicle_number=t.registration_raw,
                                      fastag_id=t.fastag_id, vehicle_id=t.vehicle_id, created_by=ctx.user.id))
    if data.get("toll_plaza_id"):
        t.toll_plaza_id = int(data["toll_plaza_id"])
        raw = t.plaza_external_id_raw or t.plaza_code_raw or t.plaza_name_raw
        if data.get("create_mapping") and raw and not mapped_value(db, "TOLL_PLAZA", t.provider_id, raw):
            db.add(ValueMapping(mapping_type="TOLL_PLAZA", provider_id=t.provider_id, source_value=raw,
                                target_id=t.toll_plaza_id, created_by=ctx.user.id))
    t.review_notes = data.get("reason")
    process_toll(ctx, t)
    audit(db, ctx.user, "RESOLVE", "toll_transactions", t.id, old, snapshot(t), reason=data.get("reason"))
    return {"message": f"Status now {t.status}"}


def fuel_resolve(ctx, t: FuelTransaction, data: dict) -> dict:
    db = ctx.db
    old = snapshot(t)
    if data.get("vehicle_id"):
        t.vehicle_id = int(data["vehicle_id"])
        if data.get("create_mapping") and t.vehicle_number_raw and not mapped_value(
                db, "VEHICLE", t.provider_id, normalize_vehicle_number(t.vehicle_number_raw)):
            db.add(ValueMapping(mapping_type="VEHICLE", provider_id=t.provider_id,
                                source_value=normalize_vehicle_number(t.vehicle_number_raw), target_id=t.vehicle_id,
                                created_by=ctx.user.id))
    if data.get("fuel_type_id"):
        t.fuel_type_id = int(data["fuel_type_id"])
    ctx.override = True
    ctx.reason = data.get("reason")
    process_fuel(ctx, t, "IMPORT")
    if data.get("accept") and t.status == "FLAGGED":
        ctx.user.require("fuel.override")
        t.status = "OVERRIDDEN"
        t.override_reason, t.override_by = data.get("reason"), ctx.user.id
    audit(db, ctx.user, "RESOLVE", "fuel_transactions", t.id, old, snapshot(t), reason=data.get("reason"))
    return {"message": f"Status now {t.status}"}


def rematch_unmatched(ctx, kind: str) -> dict:
    """Re-run matching for unresolved rows (e.g. after adding vehicles, plazas or mappings)."""
    db = ctx.db
    n_before = n_after = 0
    if kind == "toll":
        rows = db.execute(select(TollTransaction).where(TollTransaction.status.in_(
            ["VEHICLE_UNMATCHED", "PLAZA_UNMATCHED", "VEHICLE_MATCHED", "IMPORTED"]))).scalars().all()
        for t in rows:
            n_before += 1
            process_toll(ctx, t)
            n_after += t.status == "VALIDATED"
    else:
        rows = db.execute(select(FuelTransaction).where(FuelTransaction.status == "VEHICLE_UNMATCHED")).scalars().all()
        for t in rows:
            n_before += 1
            process_fuel(ctx, t, "IMPORT")
            n_after += t.status != "VEHICLE_UNMATCHED"
    db.flush()
    return {"checked": n_before, "resolved": n_after}
