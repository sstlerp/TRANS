"""Trips & freight, e-way bills, driver advances and settlements (business rules).

Trip life cycle:  PLANNED → (start) IN_TRANSIT → (deliver) DELIVERED → (POD) POD_RECEIVED → (invoice) INVOICED → CLOSED,
or CANCELLED from PLANNED / IN_TRANSIT. Status changes only through actions (each audited).
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, inspect as sa_inspect, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.errors import BusinessError
from app.core.utils import money, now, today
from app.models.compliance import Driver
from app.models.finance import Invoice
from app.models.fleet import Vehicle
from app.models.operations import FuelTransaction, TollTransaction
from app.models.org import Company, Customer, State
from app.models.trips import DriverAdvance, DriverSettlement, EwayBill, Trip, TripExpense
from app.services.rules import rule
from app.services.vehicles import cost_center_for, record_odometer

ZERO = Decimal("0.00")
TRIP_STATUSES = ["PLANNED", "IN_TRANSIT", "DELIVERED", "POD_RECEIVED", "INVOICED", "CLOSED", "CANCELLED"]
EWB_STATUSES = ["ACTIVE", "EXTENDED", "CLOSED", "EXPIRED", "CANCELLED"]
EWB_LIVE = ("ACTIVE", "EXTENDED")
GSTIN_RE = r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]"
# trip expense head → report group of the cost ledger
EXPENSE_GROUP = {"TOLL_CASH": "TOLL", "FUEL_CASH": "FUEL", "REPAIR": "MAINTENANCE", "TYRE_PUNCTURE": "TYRE"}


def next_number(db: Session, model, attr: str, prefix: str, on: date | None = None) -> str:
    """PREFIX/YYMM/0001 — sequence per prefix and month."""
    stem = f"{prefix}/{(on or today()):%y%m}/"
    col = getattr(model, attr)
    last = db.execute(select(func.max(col)).where(col.like(stem + "%"))).scalar()
    seq = int(last.rsplit("/", 1)[1]) + 1 if last and last.rsplit("/", 1)[1].isdigit() else 1
    return f"{stem}{seq:04d}"


def _changed(obj, names) -> list[str]:
    st = sa_inspect(obj)
    return [n for n in names if st.attrs[n].history.has_changes()]


# ═════════════════════════════ trips ═════════════════════════════
_TRIP_LOCKED = ("customer_id", "contract_id", "vehicle_id", "freight_basis", "freight_rate", "freight_amount",
                "loading_charges", "unloading_charges", "detention_charges", "other_charges", "advance_received",
                "weight_tonnes", "planned_km")


def compute_freight(t: Trip) -> None:
    if t.freight_basis in ("PER_TONNE", "PER_KM"):
        qty = t.weight_tonnes if t.freight_basis == "PER_TONNE" else (t.actual_km or t.planned_km)
        if t.freight_rate is None or qty is None:
            raise BusinessError(f"Freight basis {t.freight_basis.replace('_', ' ').lower()} needs a rate and the "
                                f"{'weight' if t.freight_basis == 'PER_TONNE' else 'distance (km)'}")
        t.freight_amount = money(Decimal(t.freight_rate) * Decimal(qty))
    t.freight_amount = money(t.freight_amount)
    for a in ("loading_charges", "unloading_charges", "detention_charges", "other_charges", "advance_received"):
        setattr(t, a, money(getattr(t, a)))
    t.total_freight = t.freight_amount + t.loading_charges + t.unloading_charges + t.detention_charges + t.other_charges
    if t.advance_received > t.total_freight:
        raise BusinessError("Advance received from the customer cannot exceed the total freight")
    t.balance_freight = t.total_freight - t.advance_received


def trip_before_save(ctx, t: Trip, data: dict, is_new: bool) -> None:
    db = ctx.db
    if is_new:
        t.status = "PLANNED"
        t.trip_date = t.trip_date or today()
        t.trip_number = t.trip_number or next_number(db, Trip, "trip_number", rule(db, "TRIP_NUMBER_PREFIX"), t.trip_date)
    elif t.status in ("INVOICED", "CLOSED", "CANCELLED") and _changed(t, _TRIP_LOCKED):
        raise BusinessError(f"Trip is {t.status.replace('_', ' ').lower()} — customer, vehicle and freight can no longer "
                            "be changed (use a credit/debit note for freight corrections)")
    if t.lr_number:
        t.lr_number = t.lr_number.strip().upper()
    if t.origin and t.destination and t.origin.strip().lower() == t.destination.strip().lower():
        ctx.warnings.append("Origin and destination are the same")
    if t.contract_id and t.customer_id:
        from app.models.finance import Contract
        c = db.get(Contract, t.contract_id)
        if c and c.customer_id != t.customer_id:
            raise BusinessError("The contract belongs to a different customer")
    if t.customer_id and not t.consignor_name and not t.consignee_name:
        cu = db.get(Customer, t.customer_id)
        t.consignor_name = cu.name if cu else None
    compute_freight(t)
    t.cost_center_id = cost_center_for(db, t.vehicle_id, t.trip_date)
    if t.start_odometer is not None and t.end_odometer is not None:
        if t.end_odometer < t.start_odometer:
            raise BusinessError("End odometer cannot be lower than start odometer")
        t.actual_km = Decimal(t.end_odometer) - Decimal(t.start_odometer)


def _busy(db, model, attr, value, exclude_id) -> Trip | None:
    return db.execute(select(Trip).where(getattr(Trip, attr) == value, Trip.status == "IN_TRANSIT",
                                         Trip.id != exclude_id)).scalars().first() if value else None


def live_ewb(db: Session, trip_id: int, at: datetime | None = None) -> EwayBill | None:
    """E-way bill of the trip that is valid now, or — with `at` — valid at that (possibly past) time. A bill entered
    afterwards is already EXPIRED by today's clock but was valid when the trip ran."""
    if at:
        q = select(EwayBill).where(EwayBill.trip_id == trip_id, EwayBill.status.in_(EWB_LIVE + ("EXPIRED",)),
                                   EwayBill.generated_at <= at + timedelta(minutes=5),
                                   (EwayBill.valid_until.is_(None)) | (EwayBill.valid_until >= at))
    else:
        q = select(EwayBill).where(EwayBill.trip_id == trip_id, EwayBill.status.in_(EWB_LIVE))
    return db.execute(q.order_by(EwayBill.valid_until.desc())).scalars().first()


def start_trip(ctx, t: Trip, data: dict) -> dict:
    db = ctx.db
    if t.status != "PLANNED":
        raise BusinessError(f"Only planned trips can be started (trip is {t.status})")
    at = data.get("actual_start") or now()
    other = _busy(db, Trip, "vehicle_id", t.vehicle_id, t.id)
    if other:
        raise BusinessError(f"Vehicle is already on trip {other.trip_number} (in transit) — deliver or cancel it first")
    if t.driver_id is None:
        raise BusinessError("Assign a driver before starting the trip")
    if _busy(db, Trip, "driver_id", t.driver_id, t.id):
        ctx.warnings.append("This driver is also on another trip that is in transit")
    d = db.get(Driver, t.driver_id)
    if d and d.license_expiry_date and d.license_expiry_date < at.date():
        ctx.warnings.append(f"Driver licence expired on {d.license_expiry_date:%d/%m/%Y}")
    threshold = Decimal(rule(db, "EWAY_BILL_THRESHOLD"))
    mode = rule(db, "EWAY_CHECK_MODE")
    if mode != "IGNORE" and threshold > 0 and (t.goods_value or 0) >= threshold and not live_ewb(db, t.id, at):
        msg = (f"Goods value ₹{money(t.goods_value):,} needs a valid e-way bill (threshold ₹{threshold:,}) — "
               "add it under E-way Bills first")
        if mode == "ERROR":
            raise BusinessError(msg)
        ctx.warnings.append(msg)
    if data.get("start_odometer") is not None:
        t.start_odometer = data["start_odometer"]
        record_odometer(ctx, t.vehicle_id, t.start_odometer, at, "trip_start", t.id, ctx.reason)
    t.actual_start, t.status = at, "IN_TRANSIT"
    audit(db, ctx.user, "TRIP_START", "trips", t.id, {"status": "PLANNED"},
          {"status": "IN_TRANSIT", "actual_start": at, "start_odometer": t.start_odometer})
    return {"message": f"Trip {t.trip_number} started"}


def deliver_trip(ctx, t: Trip, data: dict) -> dict:
    db = ctx.db
    if t.status != "IN_TRANSIT":
        raise BusinessError(f"Only trips in transit can be delivered (trip is {t.status})")
    at = data.get("actual_end") or now()
    if t.actual_start and at < t.actual_start:
        raise BusinessError("Delivery time is before the trip start")
    if data.get("end_odometer") is not None:
        end = Decimal(data["end_odometer"])
        if t.start_odometer is not None and end < Decimal(t.start_odometer):
            raise BusinessError("End odometer cannot be lower than start odometer")
        record_odometer(ctx, t.vehicle_id, end, at, "trip_end", t.id, ctx.reason)
        t.end_odometer = end
        if t.start_odometer is not None:
            t.actual_km = end - Decimal(t.start_odometer)
    t.actual_end, t.status = at, "DELIVERED"
    for f in ("delivered_packages", "shortage_damage"):
        if data.get(f) is not None:
            setattr(t, f, data[f])
    if t.packages and t.delivered_packages is not None and t.delivered_packages < t.packages:
        ctx.warnings.append(f"Short delivery: {t.packages - t.delivered_packages} package(s) — record the reason")
    if t.freight_basis == "PER_KM" and t.actual_km:
        compute_freight(t)
    # the journey is complete: close the bills that covered it (incl. ones expired by today's clock but valid then)
    for e in db.execute(select(EwayBill).where(EwayBill.trip_id == t.id, EwayBill.status.in_(EWB_LIVE + ("EXPIRED",)))
                        ).scalars():
        if e.status in EWB_LIVE or (e.valid_until and e.valid_until >= at):
            e.status, e.closed_at = "CLOSED", at
        else:
            ctx.warnings.append(f"E-way bill {e.ewb_number} had expired before delivery "
                                f"({e.valid_until:%d/%m/%Y %H:%M})")
    audit(db, ctx.user, "TRIP_DELIVER", "trips", t.id, {"status": "IN_TRANSIT"},
          {"status": "DELIVERED", "actual_end": at, "end_odometer": t.end_odometer, "actual_km": t.actual_km})
    return {"message": f"Trip {t.trip_number} delivered"}


def pod_trip(ctx, t: Trip, data: dict) -> dict:
    if t.status not in ("DELIVERED", "INVOICED"):
        raise BusinessError(f"Proof of delivery is recorded after delivery (trip is {t.status})")
    t.pod_received_date = data.get("pod_received_date") or today()
    if t.actual_end and t.pod_received_date < t.actual_end.date():
        raise BusinessError("POD date cannot be before the delivery date")
    t.pod_remarks = data.get("pod_remarks") or t.pod_remarks
    if t.status == "DELIVERED":
        t.status = "POD_RECEIVED"
    audit(ctx.db, ctx.user, "TRIP_POD", "trips", t.id, None, {"pod_received_date": t.pod_received_date})
    return {"message": "Proof of delivery recorded — attach the scanned POD under Documents"}


def invoice_trip(ctx, t: Trip, data: dict) -> dict:
    """Raise the customer invoice for the trip freight (income is recognised from the invoice only)."""
    from app.services import masters
    if t.status not in ("DELIVERED", "POD_RECEIVED"):
        raise BusinessError(f"Only delivered trips can be invoiced (trip is {t.status})")
    if t.invoice_id:
        raise BusinessError("This trip is already invoiced")
    if not t.customer_id:
        raise BusinessError("Set the customer on the trip before invoicing")
    if t.total_freight <= 0:
        raise BusinessError("Total freight must be greater than zero")
    rate = Decimal(str(data.get("gst_rate") or 0))
    ref = " / ".join(x for x in (t.trip_number, f"LR {t.lr_number}" if t.lr_number else None,
                                 f"{t.origin} → {t.destination}") if x)
    rec = masters.save_record(ctx, masters.get_spec("invoices"), {
        "invoice_number": data["invoice_number"], "invoice_type": "INVOICE", "customer_id": t.customer_id,
        "contract_id": t.contract_id, "invoice_date": data.get("invoice_date") or today(),
        "period_from": t.actual_start.date() if t.actual_start else t.trip_date,
        "period_to": t.actual_end.date() if t.actual_end else t.trip_date,
        "taxable_amount": t.total_freight, "tax_amount": money(t.total_freight * rate / 100),
        "remarks": f"Freight: {ref}", "allocations": [{"vehicle_id": t.vehicle_id, "amount": t.total_freight,
                                                        "remarks": t.trip_number}]})
    t.invoice_id, old = rec["id"], t.status
    t.status = "INVOICED"
    audit(ctx.db, ctx.user, "TRIP_INVOICE", "trips", t.id, {"status": old},
          {"status": "INVOICED", "invoice_id": t.invoice_id})
    return {"message": f"Invoice {data['invoice_number']} created for ₹{t.total_freight:,}"}


def close_trip(ctx, t: Trip, data: dict) -> dict:
    if t.status not in ("POD_RECEIVED", "INVOICED"):
        raise BusinessError(f"Trips are closed after POD / invoicing (trip is {t.status})")
    if t.freight_payment == "TBB" and not t.invoice_id:
        raise BusinessError("Freight is 'to be billed' — raise the invoice before closing")
    if not t.pod_received_date:
        ctx.warnings.append("Closed without a proof-of-delivery date")
    old, t.status = t.status, "CLOSED"
    audit(ctx.db, ctx.user, "TRIP_CLOSE", "trips", t.id, {"status": old}, {"status": "CLOSED"}, reason=data.get("reason"))
    return {"message": f"Trip {t.trip_number} closed"}


def cancel_trip(ctx, t: Trip, data: dict) -> dict:
    db = ctx.db
    if t.status not in ("PLANNED", "IN_TRANSIT"):
        raise BusinessError(f"A {t.status.replace('_', ' ').lower()} trip cannot be cancelled")
    if db.execute(select(func.count()).select_from(DriverAdvance).where(
            DriverAdvance.trip_id == t.id, DriverAdvance.status != "CANCELLED")).scalar_one():
        ctx.warnings.append("Driver advances on this trip stay open — recover them in the driver settlement")
    if live_ewb(db, t.id):
        ctx.warnings.append("Cancel the e-way bill(s) on the GST portal (allowed within 24 hours) and here")
    old, t.status, t.cancel_reason = t.status, "CANCELLED", data.get("reason")
    audit(db, ctx.user, "CANCEL", "trips", t.id, {"status": old}, {"status": "CANCELLED"}, reason=data.get("reason"))
    return {"message": f"Trip {t.trip_number} cancelled"}


def trip_extra(ctx, t: Trip, row: dict) -> None:
    db = ctx.db
    e = live_ewb(db, t.id)
    row["eway_bill"] = e.ewb_number if e else None
    row["eway_valid_until"] = e.valid_until.isoformat() if e and e.valid_until else None
    row["expenses_total"] = str(db.execute(select(func.coalesce(func.sum(TripExpense.amount), 0)).where(
        TripExpense.trip_id == t.id)).scalar_one())
    if t.invoice_id:
        inv = db.get(Invoice, t.invoice_id)
        row["invoice_label"] = inv.invoice_number if inv else None


# ═════════════════════════════ e-way bills ═════════════════════════════
def eway_validity(db: Session, generated_at: datetime, distance_km: int | None, odc: bool) -> datetime:
    """Validity ends at midnight of the last day; one day per 200 km (ODC: 20 km), counted from the day after
    generation (CGST Rule 138(10))."""
    per_day = int(rule(db, "EWAY_ODC_KM_PER_DAY" if odc else "EWAY_KM_PER_DAY"))
    days = max(1, math.ceil((distance_km or 0) / per_day)) if per_day > 0 else 1
    return datetime.combine(generated_at.date() + timedelta(days=days), time(23, 59, 59))


def eway_before_save(ctx, e: EwayBill, data: dict, is_new: bool) -> None:
    db = ctx.db
    e.ewb_number = (e.ewb_number or "").replace(" ", "")
    if not (e.ewb_number.isdigit() and len(e.ewb_number) == 12):
        raise BusinessError("E-way bill number must be 12 digits", "VALIDATION",
                            [{"field": "ewb_number", "message": "12 digits"}])
    if not is_new and e.status in ("CLOSED", "CANCELLED") and _changed(e, ("trip_id", "generated_at", "distance_km")):
        raise BusinessError(f"E-way bill is {e.status.lower()}")
    t = db.get(Trip, e.trip_id) if e.trip_id else None
    if t:
        e.vehicle_id = e.vehicle_id or t.vehicle_id
        e.goods_value = e.goods_value if e.goods_value is not None else t.goods_value
        e.from_place = e.from_place or t.origin
        e.to_place = e.to_place or t.destination
        e.doc_number = e.doc_number or t.goods_invoice_number
        e.doc_date = e.doc_date or t.goods_invoice_date
        if e.distance_km is None and (t.planned_km or 0) > 0:
            e.distance_km = int(Decimal(t.planned_km).to_integral_value(ROUND_HALF_UP))
        if t.status == "CANCELLED" and is_new:
            raise BusinessError("The trip is cancelled")
    if e.generated_at is None:
        e.generated_at = now()
    if e.generated_at > now() + timedelta(minutes=5):
        raise BusinessError("Generation time cannot be in the future")
    if e.valid_until is None or (not is_new and _changed(e, ("generated_at", "distance_km", "is_odc"))
                                 and "valid_until" not in data):
        e.valid_until = eway_validity(db, e.generated_at, e.distance_km, e.is_odc)
    if e.valid_until <= e.generated_at:
        raise BusinessError("Valid-until must be after the generation time")
    if is_new:
        e.status = "EXPIRED" if e.valid_until < now() else "ACTIVE"
    if e.transporter_gstin:
        e.transporter_gstin = e.transporter_gstin.upper()


def eway_extend(ctx, e: EwayBill, data: dict) -> dict:
    if e.status not in ("ACTIVE", "EXTENDED", "EXPIRED"):
        raise BusinessError(f"E-way bill is {e.status.lower()}")
    hours = Decimal(rule(ctx.db, "EWAY_EXTEND_WINDOW_HOURS"))
    if e.valid_until and abs((now() - e.valid_until).total_seconds()) > float(hours) * 3600:
        ctx.warnings.append(f"The GST portal allows extension only within {hours} hours before/after expiry")
    old = e.valid_until
    if data.get("valid_until"):
        new = data["valid_until"]
    else:  # validity of the remaining distance, counted from the extension (as on the portal)
        new = eway_validity(ctx.db, now(), data.get("remaining_km"), e.is_odc)
    if old and new <= old:
        raise BusinessError("The new validity must be later than the current one — enter the remaining distance or "
                            "the new valid-until time")
    e.valid_until, e.status = new, "EXTENDED"
    e.extension_count = (e.extension_count or 0) + 1
    e.last_extension_reason = data.get("reason")
    audit(ctx.db, ctx.user, "EWB_EXTEND", "eway_bills", e.id, {"valid_until": old}, {"valid_until": new},
          reason=data.get("reason"))
    return {"message": f"Validity extended to {new:%d/%m/%Y %H:%M}"}


def eway_update_vehicle(ctx, e: EwayBill, data: dict) -> dict:
    if e.status not in EWB_LIVE:
        raise BusinessError(f"E-way bill is {e.status.lower()}")
    old, e.vehicle_id = e.vehicle_id, data["vehicle_id"]
    audit(ctx.db, ctx.user, "EWB_PART_B", "eway_bills", e.id, {"vehicle_id": old}, {"vehicle_id": e.vehicle_id},
          reason=data.get("reason"))
    return {"message": "Vehicle (Part-B) updated — update it on the GST portal too"}


def eway_cancel(ctx, e: EwayBill, data: dict) -> dict:
    if e.status in ("CANCELLED", "CLOSED"):
        raise BusinessError(f"E-way bill is {e.status.lower()}")
    if now() - e.generated_at > timedelta(hours=24):
        raise BusinessError("An e-way bill can be cancelled only within 24 hours of generation (GST rule)")
    old, e.status, e.cancel_reason = e.status, "CANCELLED", data.get("reason")
    audit(ctx.db, ctx.user, "CANCEL", "eway_bills", e.id, {"status": old}, {"status": "CANCELLED"}, reason=e.cancel_reason)
    return {"message": "E-way bill cancelled"}


def eway_close(ctx, e: EwayBill, data: dict) -> dict:
    if e.status not in EWB_LIVE + ("EXPIRED",):
        raise BusinessError(f"E-way bill is {e.status.lower()}")
    old, e.status, e.closed_at = e.status, "CLOSED", now()
    audit(ctx.db, ctx.user, "UPDATE", "eway_bills", e.id, {"status": old}, {"status": "CLOSED"})
    return {"message": "E-way bill closed"}


def eway_extra(ctx, e: EwayBill, row: dict) -> None:
    if e.valid_until and e.status in EWB_LIVE:
        row["hours_left"] = round((e.valid_until - now()).total_seconds() / 3600, 1)


def nic_eway_json(db: Session, t: Trip) -> dict:
    """E-way bill data for the trip in the layout of the GST portal's bulk-generation JSON (check the field list
    against the current portal schema before uploading)."""
    co = db.execute(select(Company).where(Company.is_active.is_(True)).order_by(Company.id)).scalars().first()
    v = db.get(Vehicle, t.vehicle_id)
    st = lambda sid: (db.get(State, sid).gst_code if sid and db.get(State, sid) else None)  # noqa: E731
    stc = lambda sid: int(st(sid)) if st(sid) and st(sid).isdigit() else None  # noqa: E731
    value = float(money(t.goods_value or 0))
    bill = {
        "userGstin": co.gstin if co else None, "supplyType": "O", "subSupplyType": 1, "docType": "INV",
        "docNo": t.goods_invoice_number, "docDate": f"{t.goods_invoice_date:%d/%m/%Y}" if t.goods_invoice_date else None,
        "fromGstin": t.consignor_gstin or "URP", "fromTrdName": t.consignor_name, "fromAddr1": t.consignor_address,
        "fromPlace": t.origin, "fromPincode": int(t.from_pincode) if t.from_pincode else None,
        "fromStateCode": stc(t.from_state_id), "actFromStateCode": stc(t.from_state_id),
        "toGstin": t.consignee_gstin or "URP", "toTrdName": t.consignee_name, "toAddr1": t.consignee_address,
        "toPlace": t.destination, "toPincode": int(t.to_pincode) if t.to_pincode else None,
        "toStateCode": stc(t.to_state_id), "actToStateCode": stc(t.to_state_id),
        "totalValue": value, "cgstValue": 0, "sgstValue": 0, "igstValue": 0, "cessValue": 0, "totInvValue": value,
        "transMode": 1, "transDistance": int(t.planned_km or 0), "transporterId": co.gstin if co else None,
        "transporterName": co.name if co else None, "transDocNo": t.lr_number,
        "transDocDate": f"{t.lr_date:%d/%m/%Y}" if t.lr_date else None,
        "vehicleNo": v.registration_number if v else None, "vehicleType": "R",
        "mainHsnCode": int(t.hsn_code) if t.hsn_code and t.hsn_code.isdigit() else None,
        "itemList": [{"itemNo": 1, "productName": t.goods_description, "productDesc": t.goods_description,
                      "hsnCode": int(t.hsn_code) if t.hsn_code and t.hsn_code.isdigit() else None,
                      "quantity": float(t.weight_tonnes or 0), "qtyUnit": "MTS", "taxableAmount": value}]}
    missing = [k for k in ("userGstin", "docNo", "docDate", "fromPincode", "toPincode", "fromStateCode", "toStateCode",
                           "mainHsnCode", "vehicleNo") if not bill.get(k)]
    return {"version": "1.0.0621", "billLists": [bill], "_missing": missing}


# ═════════════════════════════ driver advances ═════════════════════════════
def advance_before_save(ctx, a: DriverAdvance, data: dict, is_new: bool) -> None:
    db = ctx.db
    if not is_new and a.status != "OPEN":
        raise BusinessError(f"Advance is {a.status.lower()} and cannot be changed")
    if is_new:
        a.status = "OPEN"
        a.advance_date = a.advance_date or today()
        a.advance_number = a.advance_number or next_number(db, DriverAdvance, "advance_number", "ADV", a.advance_date)
    a.amount = money(a.amount)
    if a.amount <= 0:
        raise BusinessError("Advance amount must be greater than zero")
    if a.trip_id:
        t = db.get(Trip, a.trip_id)
        if t and t.driver_id and t.driver_id != a.driver_id:
            ctx.warnings.append("The trip has a different driver")
        if t and t.status == "CANCELLED":
            ctx.warnings.append("The trip is cancelled")
    limit = Decimal(rule(db, "DRIVER_ADVANCE_LIMIT"))
    if limit > 0:
        open_total = db.execute(select(func.coalesce(func.sum(DriverAdvance.amount), 0)).where(
            DriverAdvance.driver_id == a.driver_id, DriverAdvance.status == "OPEN",
            DriverAdvance.id != (a.id or 0))).scalar_one()
        if Decimal(open_total) + a.amount > limit:
            ctx.warnings.append(f"Open advances for this driver will be ₹{Decimal(open_total) + a.amount:,} "
                                f"(limit ₹{limit:,})")


def cancel_advance(ctx, a: DriverAdvance, data: dict) -> dict:
    if a.status != "OPEN" or a.settlement_id:
        raise BusinessError("Only open advances that are not in a settlement can be cancelled")
    a.status = "CANCELLED"
    audit(ctx.db, ctx.user, "CANCEL", "driver_advances", a.id, {"status": "OPEN"}, {"status": "CANCELLED"},
          reason=data.get("reason"))
    return {"message": "Advance cancelled"}


# ═════════════════════════════ driver settlements ═════════════════════════════
def settlement_before_save(ctx, s: DriverSettlement, data: dict, is_new: bool) -> None:
    db = ctx.db
    if not is_new and s.status != "DRAFT":
        raise BusinessError(f"Settlement is {s.status.lower()} and cannot be changed")
    if is_new:
        s.status = "DRAFT"
        s.settlement_date = s.settlement_date or today()
        s.settlement_number = s.settlement_number or next_number(db, DriverSettlement, "settlement_number", "STL",
                                                                 s.settlement_date)
    if s.period_from and s.period_to and s.period_from > s.period_to:
        raise BusinessError("Period 'from' is after 'to'")
    t = db.get(Trip, s.trip_id) if s.trip_id else None
    if t:
        if t.driver_id != s.driver_id:
            raise BusinessError("The trip was driven by a different driver")
        if t.status in ("PLANNED", "IN_TRANSIT"):
            ctx.warnings.append("The trip is not delivered yet")
        if s.trip_days is None and t.actual_start:
            end = t.actual_end or now()
            s.trip_days = Decimal(max(1, math.ceil((end - t.actual_start).total_seconds() / 86400)))
    if s.allowance_per_day is None:
        d = Decimal(rule(db, "DRIVER_ALLOWANCE_PER_DAY"))
        s.allowance_per_day = d if d > 0 else None
    if s.allowance_per_day is not None and s.trip_days is not None and "allowance_amount" not in data:
        s.allowance_amount = money(Decimal(s.allowance_per_day) * Decimal(s.trip_days))
    for f in ("allowance_amount", "other_earnings", "deductions"):
        setattr(s, f, money(getattr(s, f)))
        if getattr(s, f) < 0:
            raise BusinessError("Allowance, earnings and deductions cannot be negative")
    drv = db.get(Driver, s.driver_id)
    s.cost_center_id = (t.cost_center_id if t else None) or (drv.cost_center_id if drv else None)


def _link_candidates(db: Session, s: DriverSettlement) -> tuple[list[DriverAdvance], list[TripExpense]]:
    aq = select(DriverAdvance).where(DriverAdvance.driver_id == s.driver_id, DriverAdvance.status == "OPEN",
                                     (DriverAdvance.settlement_id.is_(None)) | (DriverAdvance.settlement_id == s.id))
    eq = select(TripExpense).join(Trip, Trip.id == TripExpense.trip_id).where(
        Trip.driver_id == s.driver_id, Trip.status != "CANCELLED", TripExpense.paid_by == "DRIVER",
        (TripExpense.settlement_id.is_(None)) | (TripExpense.settlement_id == s.id))
    if s.trip_id:
        aq, eq = aq.where(DriverAdvance.trip_id == s.trip_id), eq.where(TripExpense.trip_id == s.trip_id)
    else:
        aq = aq.where(DriverAdvance.advance_date <= s.settlement_date)
        day = func.coalesce(TripExpense.expense_date, Trip.trip_date)
        eq = eq.where(day <= s.period_to if s.period_to else day <= s.settlement_date)
        if s.period_from:
            aq, eq = aq.where(DriverAdvance.advance_date >= s.period_from), eq.where(day >= s.period_from)
        if s.period_to:
            aq = aq.where(DriverAdvance.advance_date <= s.period_to)
    return list(db.execute(aq).scalars()), list(db.execute(eq).scalars())


def settlement_after_save(ctx, s: DriverSettlement, data: dict, is_new: bool) -> None:
    """(Re)link the driver's open advances and driver-paid trip expenses, then compute the net."""
    db = ctx.db
    for a in db.execute(select(DriverAdvance).where(DriverAdvance.settlement_id == s.id)).scalars():
        a.settlement_id = None
    for e in db.execute(select(TripExpense).where(TripExpense.settlement_id == s.id)).scalars():
        e.settlement_id = None
    db.flush()
    advs, exps = _link_candidates(db, s)
    for a in advs:
        a.settlement_id = s.id
    for e in exps:
        e.settlement_id = s.id
    s.total_advances = money(sum((a.amount for a in advs), ZERO))
    s.total_expenses = money(sum((e.amount for e in exps), ZERO))
    s.net_payable = s.total_expenses + s.allowance_amount + s.other_earnings - s.deductions - s.total_advances
    s.settle_amount = abs(s.net_payable)
    if not advs and not exps and not s.allowance_amount and not s.other_earnings:
        ctx.warnings.append("Nothing to settle: no open advances, driver-paid expenses or allowance found")


def approve_settlement(ctx, s: DriverSettlement, data: dict) -> dict:
    if s.status != "DRAFT":
        raise BusinessError(f"Settlement is {s.status.lower()}")
    settlement_after_save(ctx, s, {}, False)  # final recompute (items added since the draft)
    ctx.db.flush()  # the session does not autoflush: write the new links before reading them back
    s.status, s.approved_by, s.approved_at = "APPROVED", ctx.user.id, now()
    for a in ctx.db.execute(select(DriverAdvance).where(DriverAdvance.settlement_id == s.id)).scalars():
        a.status = "SETTLED"
    audit(ctx.db, ctx.user, "APPROVE", "driver_settlements", s.id, {"status": "DRAFT"},
          {"status": "APPROVED", "net_payable": s.net_payable})
    who = "pay the driver" if s.net_payable > 0 else "recover from the driver" if s.net_payable < 0 else "nothing due"
    return {"message": f"Settlement approved — {who}{'' if not s.net_payable else f' ₹{abs(s.net_payable):,}'}"}


def pay_settlement(ctx, s: DriverSettlement, data: dict) -> dict:
    if s.status != "APPROVED":
        raise BusinessError("Only approved settlements can be marked paid")
    s.paid_date = data.get("paid_date") or today()
    s.payment_mode, s.payment_reference, s.status = data.get("payment_mode"), data.get("payment_reference"), "PAID"
    audit(ctx.db, ctx.user, "UPDATE", "driver_settlements", s.id, {"status": "APPROVED"},
          {"status": "PAID", "paid_date": s.paid_date})
    return {"message": "Settlement marked as paid / recovered"}


def cancel_settlement(ctx, s: DriverSettlement, data: dict) -> dict:
    db = ctx.db
    if s.status not in ("DRAFT", "APPROVED"):
        raise BusinessError(f"A {s.status.lower()} settlement cannot be cancelled")
    db.flush()
    for a in db.execute(select(DriverAdvance).where(DriverAdvance.settlement_id == s.id)).scalars():
        a.settlement_id, a.status = None, "OPEN"
    for e in db.execute(select(TripExpense).where(TripExpense.settlement_id == s.id)).scalars():
        e.settlement_id = None
    old, s.status = s.status, "CANCELLED"
    audit(db, ctx.user, "CANCEL", "driver_settlements", s.id, {"status": old}, {"status": "CANCELLED"},
          reason=data.get("reason"))
    return {"message": "Settlement cancelled — its advances and expenses are open again"}


def settlement_delete_check(ctx, s: DriverSettlement) -> None:
    if s.status != "DRAFT":
        raise BusinessError("Only draft settlements can be deleted (cancel it instead)")


# ═════════════════════════════ reporting / alerts ═════════════════════════════
def ledger_lines(db: Session, start: date, end: date, Line) -> list:
    """Cost lines for the profitability ledger: trip expenses and approved driver allowances."""
    out = []
    day = func.coalesce(TripExpense.expense_date, Trip.trip_date)
    for cc, d, head, s in db.execute(select(Trip.cost_center_id, day, TripExpense.expense_head,
                                            func.sum(TripExpense.amount)).join(Trip, Trip.id == TripExpense.trip_id)
                                     .where(day.between(start, end), Trip.status != "CANCELLED")
                                     .group_by(Trip.cost_center_id, day, TripExpense.expense_head)).all():
        out.append(Line(d, cc, EXPENSE_GROUP.get(head, "OTHER_DIRECT"), money(s), source="trip_expense"))
    for cc, d, s in db.execute(select(DriverSettlement.cost_center_id, DriverSettlement.settlement_date,
                                      func.sum(DriverSettlement.allowance_amount + DriverSettlement.other_earnings
                                               - DriverSettlement.deductions))
                               .where(DriverSettlement.settlement_date.between(start, end),
                                      DriverSettlement.status.in_(["APPROVED", "PAID"]))
                               .group_by(DriverSettlement.cost_center_id, DriverSettlement.settlement_date)).all():
        if s:
            out.append(Line(d, cc, "DRIVER", money(s), source="driver_settlement"))
    return out


def _window_sum(db, model, amount_col, vehicle_id, start: datetime, end: datetime) -> Decimal:
    q = select(func.coalesce(func.sum(amount_col), 0)).where(
        model.vehicle_id == vehicle_id,
        func.coalesce(model.txn_datetime, model.txn_date) >= start,
        func.coalesce(model.txn_datetime, model.txn_date) <= end)
    if model is TollTransaction:
        q = q.where(model.txn_kind != "RECHARGE", model.status.notin_(["DUPLICATE", "ERROR"]))
    else:
        q = q.where(model.status != "CANCELLED")
    return money(db.execute(q).scalar_one())


def trip_profitability(db: Session, start: date, end: date, vehicle_id=None, customer_id=None) -> list[dict]:
    """Per trip: freight vs fuel and toll in the trip window, trip expenses and driver allowance."""
    day = func.coalesce(func.date(Trip.actual_start), Trip.trip_date)
    q = select(Trip).where(Trip.status != "CANCELLED", day.between(start, end))
    if vehicle_id:
        q = q.where(Trip.vehicle_id == vehicle_id)
    if customer_id:
        q = q.where(Trip.customer_id == customer_id)
    rows = []
    for t in db.execute(q.order_by(Trip.trip_date, Trip.id)).scalars():
        fuel = toll = ZERO
        if t.actual_start:
            w_end = t.actual_end or now()
            fuel = _window_sum(db, FuelTransaction, FuelTransaction.total_amount, t.vehicle_id, t.actual_start, w_end)
            toll = _window_sum(db, TollTransaction, TollTransaction.amount, t.vehicle_id, t.actual_start, w_end)
        exp = money(db.execute(select(func.coalesce(func.sum(TripExpense.amount), 0)).where(
            TripExpense.trip_id == t.id)).scalar_one())
        drv = money(db.execute(select(func.coalesce(func.sum(
            DriverSettlement.allowance_amount + DriverSettlement.other_earnings - DriverSettlement.deductions), 0)).where(
            DriverSettlement.trip_id == t.id, DriverSettlement.status.in_(["APPROVED", "PAID"]))).scalar_one())
        cost = fuel + toll + exp + drv
        km = t.actual_km or t.planned_km
        v, c = db.get(Vehicle, t.vehicle_id), db.get(Customer, t.customer_id) if t.customer_id else None
        rows.append({"trip": t.trip_number, "lr": t.lr_number, "date": t.trip_date, "vehicle": v.registration_number if v else "",
                     "customer": c.name if c else "", "route": f"{t.origin} → {t.destination}", "status": t.status,
                     "freight": t.total_freight, "fuel": fuel, "toll": toll, "expenses": exp, "driver": drv,
                     "cost": cost, "margin": t.total_freight - cost,
                     "margin_pct": ((t.total_freight - cost) / t.total_freight * 100).quantize(Decimal("0.1"))
                     if t.total_freight else None, "km": km,
                     "cost_per_km": (cost / Decimal(km)).quantize(Decimal("0.01")) if km else None})
    return rows


def refresh_eway_status(db: Session) -> int:
    n = 0
    for e in db.execute(select(EwayBill).where(EwayBill.status.in_(EWB_LIVE), EwayBill.valid_until < now())).scalars():
        e.status = "EXPIRED"
        n += 1
    return n


def daily_alerts(db: Session) -> dict:
    from app.services.notifications import notify
    expired = refresh_eway_status(db)
    hrs = Decimal(rule(db, "EWAY_ALERT_HOURS"))
    soon = 0
    for e, t in db.execute(select(EwayBill, Trip).join(Trip, Trip.id == EwayBill.trip_id).where(
            EwayBill.status.in_(EWB_LIVE + ("EXPIRED",)), Trip.status == "IN_TRANSIT",
            EwayBill.valid_until <= now() + timedelta(hours=float(hrs)))).all():
        soon += 1
        gone = e.status == "EXPIRED"
        notify(db, "EWAY_EXPIRED" if gone else "EWAY_EXPIRING",
               f"E-way bill {e.ewb_number} ({t.trip_number}) {'EXPIRED' if gone else 'expires'} "
               f"{e.valid_until:%d/%m/%Y %H:%M} — vehicle still in transit", severity="CRITICAL" if gone else "WARNING",
               entity_type="eway_bills", entity_id=e.id, link_url=f"/masters/eway_bills?id={e.id}",
               dedupe_key=f"ewb:{e.id}:{e.status}:{e.valid_until:%Y%m%d%H}")
    pod_days = int(rule(db, "POD_PENDING_DAYS"))
    pods = db.execute(select(Trip).where(Trip.status == "DELIVERED",
                                         Trip.actual_end <= now() - timedelta(days=pod_days))).scalars().all()
    for t in pods:
        notify(db, "POD_PENDING", f"POD pending for {t.trip_number} (delivered {t.actual_end:%d/%m/%Y})",
               severity="WARNING", entity_type="trips", entity_id=t.id, link_url=f"/masters/trips?id={t.id}",
               dedupe_key=f"pod:{t.id}:{today():%Y%m%d}")
    adv_days = int(rule(db, "ADVANCE_ALERT_DAYS"))
    old = db.execute(select(Driver.name, func.count(), func.sum(DriverAdvance.amount)).join(
        Driver, Driver.id == DriverAdvance.driver_id).where(
        DriverAdvance.status == "OPEN", DriverAdvance.settlement_id.is_(None),
        DriverAdvance.advance_date <= today() - timedelta(days=adv_days)).group_by(Driver.name)).all()
    for name, n, amt in old:
        notify(db, "ADVANCE_UNSETTLED", f"{name}: {n} advance(s) ₹{money(amt):,} unsettled for over {adv_days} days",
               severity="WARNING", link_url="/masters/driver_advances?f_status=OPEN",
               dedupe_key=f"adv:{name}:{today():%Y%m%d}")
    return {"eway_expired": expired, "eway_alerts": soon, "pod_pending": len(pods), "advance_alerts": len(old)}


def dashboard_counts(db: Session) -> dict:
    cnt = lambda q: db.execute(select(func.count()).select_from(Trip).where(q)).scalar_one()  # noqa: E731
    hrs = Decimal(rule(db, "EWAY_ALERT_HOURS"))
    ewb_soon = db.execute(select(func.count()).select_from(EwayBill).join(Trip, Trip.id == EwayBill.trip_id).where(
        EwayBill.status.in_(EWB_LIVE), Trip.status == "IN_TRANSIT",
        EwayBill.valid_until <= now() + timedelta(hours=float(hrs)))).scalar_one()
    ewb_expired = db.execute(select(func.count()).select_from(EwayBill).join(Trip, Trip.id == EwayBill.trip_id).where(
        Trip.status == "IN_TRANSIT", (EwayBill.status == "EXPIRED") |
        ((EwayBill.status.in_(EWB_LIVE)) & (EwayBill.valid_until < now())))).scalar_one()
    adv = db.execute(select(func.count(), func.coalesce(func.sum(DriverAdvance.amount), 0)).where(
        DriverAdvance.status == "OPEN")).one()
    month = today().replace(day=1)
    freight = db.execute(select(func.coalesce(func.sum(Trip.total_freight), 0)).where(
        Trip.status != "CANCELLED", Trip.trip_date >= month)).scalar_one()
    return {"planned": cnt(Trip.status == "PLANNED"), "in_transit": cnt(Trip.status == "IN_TRANSIT"),
            "pod_pending": cnt(Trip.status == "DELIVERED"),
            "to_invoice": cnt((Trip.status == "POD_RECEIVED") & (Trip.freight_payment == "TBB")),
            "eway_expiring": ewb_soon, "eway_expired_in_transit": ewb_expired,
            "open_advances": adv[0], "open_advance_amount": money(adv[1]),
            "settlements_pending": db.execute(select(func.count()).select_from(DriverSettlement).where(
                DriverSettlement.status == "DRAFT")).scalar_one(),
            "einvoice_pending": db.execute(select(func.count()).select_from(Invoice).where(
                Invoice.einvoice_status == "PENDING", Invoice.status != "CANCELLED")).scalar_one(),
            "freight_mtd": money(freight)}
