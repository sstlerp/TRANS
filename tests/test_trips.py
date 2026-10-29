"""Trips & freight (LR), e-way bills, driver advances / settlements and GST e-invoice details on invoices."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import BusinessError
from app.core.utils import now, today
from app.models import trips as TR
from app.models.finance import Invoice
from app.services import masters, reports, trips
from app.services.rules import set_rule
from tests.factories import dmy

T = today()   # company timezone, like the app
NOW = now()
spec = masters.get_spec


def dt(d: datetime) -> str:
    return d.strftime("%d/%m/%Y %H:%M")


def driver(ctx, code="DRV-T1", **kw):
    return masters.save_record(ctx, spec("drivers"), {"driver_code": code, "name": f"Driver {code}", **kw})


def trip(ctx, f, drv=None, **kw):
    data = {"trip_date": dmy(T - timedelta(days=3)), "vehicle_id": f.v.open["id"], "driver_id": drv,
            "customer_id": f.cust.id, "origin": "Chennai", "destination": "Bengaluru", "planned_km": "350",
            "freight_basis": "FIXED", "freight_amount": "30000", **kw}
    return masters.save_record(ctx, spec("trips"), data)


def act(ctx, key, rid, name, data=None):
    return masters.run_action(ctx, spec(key), rid, name, data or {})


def get(ctx, model, rid):
    ctx.db.flush()  # what the request's commit would write
    obj = ctx.db.get(model, rid)
    ctx.db.refresh(obj)
    return obj


# ───────────────────────── trips ─────────────────────────
def test_trip_numbering_and_freight(ctx, fleet):
    t = trip(ctx, fleet, lr_number=" lr-77 ", freight_basis="PER_TONNE", freight_rate="2500", weight_tonnes="12",
             loading_charges="1500", advance_received="5000")
    assert t["trip_number"].startswith("TRP/") and t["trip_number"].endswith("0001") and t["status"] == "PLANNED"
    assert t["lr_number"] == "LR-77"
    assert Decimal(t["freight_amount"]) == Decimal("30000.00") and Decimal(t["total_freight"]) == Decimal("31500.00")
    assert Decimal(t["balance_freight"]) == Decimal("26500.00")
    assert trip(ctx, fleet)["trip_number"].endswith("0002")
    with pytest.raises(BusinessError, match="rate"):
        trip(ctx, fleet, freight_basis="PER_KM", planned_km=None)
    with pytest.raises(BusinessError, match="cannot exceed"):
        trip(ctx, fleet, advance_received="40000")


def test_trip_full_flow_to_invoice_and_close(ctx, fleet):
    d = driver(ctx)
    t = trip(ctx, fleet, d["id"], packages=100, freight_basis="PER_KM", freight_rate="80",
             expenses=[{"expense_head": "LOADING", "amount": "700", "paid_by": "DRIVER"},
                       {"expense_head": "PARKING", "amount": "300", "paid_by": "COMPANY"}])
    assert Decimal(t["freight_amount"]) == Decimal("28000.00")  # 350 planned km × 80
    with pytest.raises(BusinessError, match="Only trips in transit"):
        act(ctx, "trips", t["id"], "deliver", {"actual_end": dt(NOW)})
    act(ctx, "trips", t["id"], "start", {"actual_start": dt(NOW - timedelta(days=2)), "start_odometer": "101000"})
    assert get(ctx, TR.Trip, t["id"]).status == "IN_TRANSIT"
    with pytest.raises(BusinessError, match="End odometer"):
        act(ctx, "trips", t["id"], "deliver", {"actual_end": dt(NOW - timedelta(days=1)), "end_odometer": "100900"})
    res = act(ctx, "trips", t["id"], "deliver", {"actual_end": dt(NOW - timedelta(days=1)), "end_odometer": "101400",
                                                 "delivered_packages": 98})
    tr = get(ctx, TR.Trip, t["id"])
    assert tr.status == "DELIVERED" and tr.actual_km == Decimal("400")
    assert tr.freight_amount == Decimal("32000.00")  # per-km freight recomputed on actual km
    assert any("Short delivery" in w for w in res["warnings"])
    with pytest.raises(BusinessError, match="POD date"):
        act(ctx, "trips", t["id"], "pod", {"pod_received_date": dmy(T - timedelta(days=5))})
    act(ctx, "trips", t["id"], "pod", {"pod_received_date": dmy(T)})
    assert get(ctx, TR.Trip, t["id"]).status == "POD_RECEIVED"
    with pytest.raises(BusinessError, match="to be billed"):
        act(ctx, "trips", t["id"], "close")
    act(ctx, "trips", t["id"], "invoice", {"invoice_number": "INV-T1", "invoice_date": dmy(T), "gst_rate": "12"})
    tr = get(ctx, TR.Trip, t["id"])
    inv = ctx.db.get(Invoice, tr.invoice_id)
    assert tr.status == "INVOICED" and inv.taxable_amount == Decimal("32000.00") and inv.tax_amount == Decimal("3840.00")
    with pytest.raises(BusinessError, match="can no longer"):
        masters.save_record(ctx, spec("trips"), {"freight_amount": "1"}, t["id"])
    act(ctx, "trips", t["id"], "close")
    assert get(ctx, TR.Trip, t["id"]).status == "CLOSED"
    # trip expenses are cost of the vehicle's cost center (whoever paid), income comes from the invoice only
    rows = trips.trip_profitability(ctx.db, T - timedelta(days=10), T)
    row = next(r for r in rows if r["trip"] == tr.trip_number)
    assert row["freight"] == Decimal("32000.00") and row["expenses"] == Decimal("1000.00")


def test_trip_start_checks(ctx, fleet):
    d1, d2 = driver(ctx, "D-A"), driver(ctx, "D-B", license_expiry_date=dmy(T - timedelta(days=30)))
    t0 = trip(ctx, fleet)
    with pytest.raises(BusinessError, match="driver"):
        act(ctx, "trips", t0["id"], "start", {"actual_start": dt(NOW)})
    t1, t2 = trip(ctx, fleet, d1["id"]), trip(ctx, fleet, d2["id"])
    act(ctx, "trips", t1["id"], "start", {"actual_start": dt(NOW - timedelta(hours=3))})
    with pytest.raises(BusinessError, match="already on trip"):
        act(ctx, "trips", t2["id"], "start", {"actual_start": dt(NOW)})
    t3 = trip(ctx, fleet, d2["id"], vehicle_id=fleet.v.lpg["id"], goods_value="90000")
    res = act(ctx, "trips", t3["id"], "start", {"actual_start": dt(NOW)})
    w = " ".join(res["warnings"])
    assert "licence expired" in w and "e-way bill" in w  # default mode WARN
    t4 = trip(ctx, fleet, d2["id"], vehicle_id=fleet.v.cng["id"], goods_value="90000")
    set_rule(ctx.db, "EWAY_CHECK_MODE", "ERROR")
    with pytest.raises(BusinessError, match="e-way bill"):
        act(ctx, "trips", t4["id"], "start", {"actual_start": dt(NOW)})
    masters.save_record(ctx, spec("eway_bills"), {"ewb_number": "3310 0000 0001", "trip_id": t4["id"],
                                                  "generated_at": dt(NOW - timedelta(hours=1))})
    act(ctx, "trips", t4["id"], "start", {"actual_start": dt(NOW)})
    # cancelling: only planned / in transit
    act(ctx, "trips", t2["id"], "cancel", {"reason": "Customer cancelled"})
    with pytest.raises(BusinessError, match="cannot be cancelled"):
        act(ctx, "trips", t2["id"], "cancel", {"reason": "again"})


# ───────────────────────── e-way bills ─────────────────────────
def test_eway_validity_extend_cancel_and_close(ctx, fleet):
    d = driver(ctx)
    t = trip(ctx, fleet, d["id"], planned_km="505", goods_value="420000", goods_invoice_number="GI-1")
    with pytest.raises(BusinessError) as err:
        masters.save_record(ctx, spec("eway_bills"), {"ewb_number": "12345", "trip_id": t["id"],
                                                      "generated_at": dt(NOW)})
    assert err.value.errors[0]["field"] == "ewb_number"
    gen = NOW - timedelta(hours=2)
    e = masters.save_record(ctx, spec("eway_bills"), {"ewb_number": "331000000201", "trip_id": t["id"],
                                                      "generated_at": dt(gen), "transporter_gstin": "33aabct1234f1z5"})
    eb = get(ctx, TR.EwayBill, e["id"])
    assert eb.distance_km == 505 and eb.doc_number == "GI-1" and eb.vehicle_id == fleet.v.open["id"]
    assert eb.valid_until == datetime.combine(gen.date() + timedelta(days=3), datetime.max.time()).replace(microsecond=0)
    assert eb.status == "ACTIVE" and eb.transporter_gstin == "33AABCT1234F1Z5"
    odc = trips.eway_validity(ctx.db, gen, 45, True)
    assert odc.date() == gen.date() + timedelta(days=3)  # 20 km per day for over-dimensional cargo
    with pytest.raises(BusinessError, match="later than"):
        act(ctx, "eway_bills", e["id"], "extend", {"remaining_km": 10, "reason": "Breakdown"})
    act(ctx, "eway_bills", e["id"], "extend", {"valid_until": dt(eb.valid_until + timedelta(days=1)), "reason": "Breakdown"})
    eb = get(ctx, TR.EwayBill, e["id"])
    assert eb.status == "EXTENDED" and eb.extension_count == 1
    act(ctx, "eway_bills", e["id"], "part_b", {"vehicle_id": fleet.v.lpg["id"], "reason": "Transhipment"})
    assert get(ctx, TR.EwayBill, e["id"]).vehicle_id == fleet.v.lpg["id"]
    # 24-hour cancellation rule
    old = masters.save_record(ctx, spec("eway_bills"), {"ewb_number": "331000000202", "trip_id": t["id"],
                                                        "generated_at": dt(NOW - timedelta(hours=30)), "distance_km": 800})
    with pytest.raises(BusinessError, match="24 hours"):
        act(ctx, "eway_bills", old["id"], "cancel", {"reason": "Wrong"})
    act(ctx, "eway_bills", old["id"], "close")
    with pytest.raises(BusinessError, match="future"):
        masters.save_record(ctx, spec("eway_bills"), {"ewb_number": "331000000203", "generated_at": dt(NOW + timedelta(days=1))})
    # delivery closes the live bill of the trip
    act(ctx, "trips", t["id"], "start", {"actual_start": dt(NOW - timedelta(hours=1))})
    act(ctx, "trips", t["id"], "deliver", {"actual_end": dt(NOW)})
    assert get(ctx, TR.EwayBill, e["id"]).status == "CLOSED"


def test_eway_entered_late_counts_for_the_time_it_was_valid(ctx, fleet):
    """A bill keyed in after the journey is EXPIRED by today's clock but covered the trip: delivery closes it."""
    d = driver(ctx)
    t = trip(ctx, fleet, d["id"], planned_km="100", goods_value="90000")
    e = masters.save_record(ctx, spec("eway_bills"), {"ewb_number": "331000000301", "trip_id": t["id"],
                                                      "generated_at": dt(NOW - timedelta(days=6))})
    assert e["status"] == "EXPIRED"
    set_rule(ctx.db, "EWAY_CHECK_MODE", "ERROR")
    act(ctx, "trips", t["id"], "start", {"actual_start": dt(NOW - timedelta(days=6) + timedelta(hours=1))})
    res = act(ctx, "trips", t["id"], "deliver", {"actual_end": dt(NOW - timedelta(days=5))})
    assert get(ctx, TR.EwayBill, e["id"]).status == "CLOSED" and not res.get("warnings")


def test_eway_status_refresh_alerts_and_json(ctx, fleet, client, auth):
    d = driver(ctx)
    t = trip(ctx, fleet, d["id"], goods_value="90000", hsn_code="1905", goods_description="Biscuits", lr_number="LR-J1")
    act(ctx, "trips", t["id"], "start", {"actual_start": dt(NOW - timedelta(hours=2))})  # alerts are for vehicles on the road
    e = masters.save_record(ctx, spec("eway_bills"), {"ewb_number": "331000000401", "trip_id": t["id"],
                                                      "generated_at": dt(NOW - timedelta(hours=3)),
                                                      "valid_until": dt(NOW + timedelta(hours=2))})
    set_rule(ctx.db, "EWAY_ALERT_HOURS", "12")
    res = trips.daily_alerts(ctx.db)
    assert res["eway_alerts"] >= 1
    eb = get(ctx, TR.EwayBill, e["id"])
    eb.valid_until = NOW - timedelta(minutes=1)
    ctx.db.flush()
    assert trips.refresh_eway_status(ctx.db) >= 1 and get(ctx, TR.EwayBill, e["id"]).status == "EXPIRED"
    r = client.get(f"/api/trips/{t['id']}/eway-json", headers=auth)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    body = r.json()
    bill = body["billLists"][0]
    assert bill["mainHsnCode"] == 1905 and bill["transDocNo"] == "LR-J1" and bill["vehicleNo"] == "TN01AA0002"
    assert "docNo" in r.headers["x-missing-fields"] and "_missing" not in body
    assert client.get("/api/trips/999999/eway-json", headers=auth).status_code == 404


# ───────────────────────── driver advances & settlement ─────────────────────────
def test_driver_settlement_links_advances_and_expenses(ctx, fleet):
    d = driver(ctx)
    t = trip(ctx, fleet, d["id"], expenses=[{"expense_head": "LOADING", "amount": "1500", "paid_by": "DRIVER"},
                                            {"expense_head": "POLICE_RTO", "amount": "500", "paid_by": "DRIVER"},
                                            {"expense_head": "PARKING", "amount": "200", "paid_by": "COMPANY"}])
    act(ctx, "trips", t["id"], "start", {"actual_start": dt(NOW - timedelta(days=3))})
    act(ctx, "trips", t["id"], "deliver", {"actual_end": dt(NOW - timedelta(days=1, hours=1))})
    set_rule(ctx.db, "DRIVER_ADVANCE_LIMIT", "6000")
    a1 = masters.save_record(ctx, spec("driver_advances"), {"driver_id": d["id"], "trip_id": t["id"], "amount": "5000",
                                                            "advance_date": dmy(T - timedelta(days=3))})
    assert a1["advance_number"].startswith("ADV/") and a1["status"] == "OPEN"
    a2 = masters.save_record(ctx, spec("driver_advances"), {"driver_id": d["id"], "trip_id": t["id"], "amount": "2000",
                                                            "advance_date": dmy(T - timedelta(days=2))})
    assert any("limit" in w for w in a2["_warnings"])
    with pytest.raises(BusinessError) as err:
        masters.save_record(ctx, spec("driver_advances"), {"driver_id": d["id"], "amount": "0"})
    assert any(e["field"] == "amount" for e in err.value.errors)
    other = driver(ctx, "D-OTHER")
    with pytest.raises(BusinessError, match="different driver"):
        masters.save_record(ctx, spec("driver_settlements"), {"driver_id": other["id"], "trip_id": t["id"],
                                                              "settlement_date": dmy(T)})
    s = masters.save_record(ctx, spec("driver_settlements"), {"driver_id": d["id"], "trip_id": t["id"],
                                                              "settlement_date": dmy(T), "allowance_per_day": "400",
                                                              "deductions": "100"})
    st = get(ctx, TR.DriverSettlement, s["id"])
    assert st.trip_days == Decimal("2") and st.allowance_amount == Decimal("800.00")
    assert st.total_expenses == Decimal("2000.00") and st.total_advances == Decimal("7000.00")
    assert st.net_payable == Decimal("-4300.00") and st.settle_amount == Decimal("4300.00")  # driver returns ₹4,300
    # an advance in a settlement cannot be cancelled; the settlement cannot be edited after approval
    with pytest.raises(BusinessError, match="not in a settlement"):
        act(ctx, "driver_advances", a1["id"], "cancel", {"reason": "x"})
    act(ctx, "driver_settlements", s["id"], "approve")
    assert get(ctx, TR.DriverAdvance, a1["id"]).status == "SETTLED"
    with pytest.raises(BusinessError, match="cannot be changed"):
        masters.save_record(ctx, spec("driver_settlements"), {"deductions": "0"}, s["id"])
    # approved allowance − deductions is driver cost in the ledger
    lines = reports.ledger(ctx.db, T - timedelta(days=10), T)
    assert sum(ln.amount for ln in lines if ln.source == "driver_settlement") == Decimal("700.00")
    assert sum(ln.amount for ln in lines if ln.source == "trip_expense") == Decimal("2200.00")
    # cancelling reopens the advances and expenses
    act(ctx, "driver_settlements", s["id"], "cancel", {"reason": "Recount"})
    assert get(ctx, TR.DriverAdvance, a1["id"]).status == "OPEN"
    assert ctx.db.execute(select(TR.TripExpense).where(TR.TripExpense.settlement_id == s["id"])).first() is None
    with pytest.raises(BusinessError):
        act(ctx, "driver_settlements", s["id"], "pay", {"paid_date": dmy(T)})


def test_period_settlement_and_pay(ctx, fleet):
    d = driver(ctx)
    masters.save_record(ctx, spec("driver_advances"), {"driver_id": d["id"], "amount": "1000",
                                                       "advance_date": dmy(T - timedelta(days=20))})
    masters.save_record(ctx, spec("driver_advances"), {"driver_id": d["id"], "amount": "800",
                                                       "advance_date": dmy(T - timedelta(days=5))})
    s = masters.save_record(ctx, spec("driver_settlements"), {
        "driver_id": d["id"], "settlement_date": dmy(T), "period_from": dmy(T - timedelta(days=10)),
        "period_to": dmy(T), "other_earnings": "2000"})
    st = get(ctx, TR.DriverSettlement, s["id"])
    assert st.total_advances == Decimal("800.00") and st.net_payable == Decimal("1200.00")
    act(ctx, "driver_settlements", s["id"], "approve")
    act(ctx, "driver_settlements", s["id"], "pay", {"paid_date": dmy(T), "payment_reference": "UTR1"})
    assert get(ctx, TR.DriverSettlement, s["id"]).status == "PAID"
    with pytest.raises(BusinessError, match="draft"):
        masters.delete_record(ctx, spec("driver_settlements"), s["id"])


# ───────────────────────── e-invoice on invoices ─────────────────────────
def test_einvoice_irn_validation_lock_and_cancel(ctx, fleet):
    from tests.factories import make_invoice
    inv = make_invoice(ctx, fleet, "EI-1", 10000, [(fleet.v.open["id"], 10000)])
    assert inv["einvoice_status"] == "NOT_APPLICABLE"
    ispec = spec("invoices")
    with pytest.raises(BusinessError, match="64"):
        masters.save_record(ctx, ispec, {"irn": "abc"}, inv["id"])
    irn = "A" * 64
    masters.save_record(ctx, ispec, {"irn": irn, "irn_ack_number": "112410000001",
                                     "irn_ack_date": dt(NOW - timedelta(hours=1))}, inv["id"])
    i = get(ctx, Invoice, inv["id"])
    assert i.einvoice_status == "GENERATED" and i.irn == "a" * 64
    with pytest.raises(BusinessError, match="IRN"), ctx.db.begin_nested():  # savepoint = the request's rollback
        masters.save_record(ctx, ispec, {"taxable_amount": "9000",
                                         "allocations": [{"vehicle_id": fleet.v.open["id"], "amount": "9000"}]}, inv["id"])
    ctx.db.expire_all()
    masters.save_record(ctx, ispec, {"remarks": "ok"}, inv["id"])  # non-amount edits stay allowed
    act(ctx, "invoices", inv["id"], "cancel_irn", {"reason": "Wrong GSTIN"})
    assert get(ctx, Invoice, inv["id"]).einvoice_status == "CANCELLED"
    # applicable → new invoices start as PENDING; IRN older than 24 h cannot be cancelled
    set_rule(ctx.db, "EINVOICE_APPLICABLE", "true")
    inv2 = make_invoice(ctx, fleet, "EI-2", 5000, [(fleet.v.open["id"], 5000)])
    assert inv2["einvoice_status"] == "PENDING"
    masters.save_record(ctx, ispec, {"irn": "b" * 64, "irn_ack_date": dt(NOW - timedelta(hours=30))}, inv2["id"])
    with pytest.raises(BusinessError, match="24 hours"):
        act(ctx, "invoices", inv2["id"], "cancel_irn", {"reason": "late"})


# ───────────────────────── permissions, reports, screens ─────────────────────────
def test_permissions_reports_and_pages(client, auth, db, fleet, ctx):
    from tests.test_api import bearer, make_user
    d = driver(ctx)
    t = trip(ctx, fleet, d["id"])
    s = masters.save_record(ctx, spec("driver_settlements"), {"driver_id": d["id"], "trip_id": t["id"],
                                                              "settlement_date": dmy(T), "other_earnings": "100"})
    make_user(db, "ops", "OPERATIONS")
    make_user(db, "viewer", "VIEWER")
    h = bearer(client, "ops")
    assert client.get("/api/masters/trips", headers=h).status_code == 200
    meta = client.get("/api/masters/driver_settlements/meta", headers=h).json()
    assert meta["perms"]["create"] is True
    assert not next(a for a in meta["actions"] if a["key"] == "approve")["allowed"]  # approval is separate
    r = client.post(f"/api/masters/driver_settlements/{s['id']}/actions/approve", headers=h, json={})
    assert r.status_code == 403
    for key in ("trip_profitability", "lr_register", "pod_pending", "eway_register", "driver_advances",
                "driver_settlements", "einvoice"):
        assert client.get(f"/api/reports/{key}", headers=auth).status_code == 200, key
    from tests.conftest import login
    tok = login(client)
    client.cookies.set("erp_session", tok["access_token"])
    for url in ("/m/trips", "/masters/trips", "/masters/eway_bills", "/masters/driver_advances",
                "/masters/driver_settlements"):
        assert client.get(url).status_code == 200, url
    assert 'href="/m/trips"' in client.get("/").text
    assert "trip_ext.js" in client.get("/masters/trips").text
    hits = client.get("/api/search?q=" + t["trip_number"], headers=auth).json()
    assert hits and hits[0]["kind"] == "Trip / LR"
