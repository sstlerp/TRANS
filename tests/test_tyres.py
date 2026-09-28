"""Tyre lifecycle: purchase → stock → install → shift → transfer → remove → godown → retread →
reinstall → warranty → scrap; occupancy & odometer controls; dashboard; cost/km (criteria 35-44)."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import BusinessError, OverrideRequired
from app.models.tyres import Tyre, TyreFitment, TyreMovement, TyreRetreading, TyreWarrantyClaim
from app.services import masters, tyres
from tests.factories import new_tyre

SPEC = "tyres"
D0 = datetime.now().replace(second=0, microsecond=0) - timedelta(days=60)


def act(ctx, tyre_id, action, **data):
    return masters.run_action(ctx, masters.get_spec(SPEC), tyre_id, action, data)


def at(days):
    return (D0 + timedelta(days=days)).strftime("%d/%m/%Y %H:%M")


def movements(db, tid):
    return [m.movement_type for m in db.execute(select(TyreMovement).where(TyreMovement.tyre_id == tid)
                                                .order_by(TyreMovement.movement_date, TyreMovement.id)).scalars()]


def test_full_lifecycle(ctx, fleet):
    db = ctx.db
    t = new_tyre(ctx, fleet, "SN-100")
    assert t["current_status"] == "IN_STOCK" and t["current_location"] == "Main Tyre Godown"      # purchase → stock
    lpg, opn = fleet.v.lpg, fleet.v.open
    act(ctx, t["id"], "install", vehicle_id=lpg["id"], position_id=fleet.pos["FL"], date=at(0), odometer="100100", tread_depth="16")
    tt = db.get(Tyre, t["id"])
    assert (tt.current_status, tt.current_vehicle_id, tt.current_position_id) == ("INSTALLED", lpg["id"], fleet.pos["FL"])
    act(ctx, t["id"], "shift", position_id=fleet.pos["FR"], date=at(10), odometer="102100")              # position change
    assert tt.current_position_id == fleet.pos["FR"] and tt.current_status == "SHIFTED"
    act(ctx, t["id"], "transfer", to_vehicle_id=opn["id"], position_id=fleet.pos["R1LO"], date=at(20),
        from_odometer="104100", to_odometer="100300")                                                   # vehicle transfer
    assert tt.current_vehicle_id == opn["id"] and tt.total_km == Decimal("4000.0")
    res = act(ctx, t["id"], "remove", date=at(30), odometer="101300", tread_depth="9", to_location_id=fleet.tl["GODOWN"])
    assert Decimal(res["running_km"]) == Decimal("1000.0")                                            # removal − install
    assert tt.current_status == "IN_GODOWN" and tt.total_km == Decimal("5000.0") and tt.current_vehicle_id is None
    act(ctx, t["id"], "send_retread", vendor_id=fleet.retreader.id, date=at(31)[:10], tread_depth="3")
    assert tt.current_status == "SENT_FOR_RETREADING"
    act(ctx, t["id"], "receive_retread", date=at(40)[:10], cost="6000", gst_amount="0", new_tread_depth="14",
        to_location_id=fleet.tl["GODOWN"])
    assert tt.current_status == "RETREADED" and tt.retread_count == 1 and tt.current_tread_depth == Decimal("14")
    act(ctx, t["id"], "install", vehicle_id=lpg["id"], position_id=fleet.pos["R1LO"], date=at(41), odometer="104500")
    assert tt.current_status == "FITTED_AFTER_RETREAD"                                                 # reinstallation
    act(ctx, t["id"], "remove", date=at(50), odometer="105500", to_location_id=fleet.tl["WORKSHOP"], new_status="DAMAGED")
    act(ctx, t["id"], "warranty", claim_number="WC-1", date=at(51)[:10], failure_reason="Sidewall bulge", claim_amount="8000")
    assert tt.current_status == "WARRANTY"
    claim = db.execute(select(TyreWarrantyClaim).where(TyreWarrantyClaim.claim_number == "WC-1")).scalar_one()
    masters.run_action(ctx, masters.get_spec("tyre_warranty_claims"), claim.id, "resolve",
                       {"status": "APPROVED", "resolution_type": "CREDIT", "approved_amount": "5000"})
    assert tt.current_status == "SCRAPPED"                                                             # final disposal
    assert movements(db, t["id"]) == ["PURCHASE", "INSTALL", "SHIFT", "TRANSFER", "REMOVE", "SEND_RETREAD", "RECEIVE_RETREAD",
                                      "INSTALL", "REMOVE", "SEND_WARRANTY", "WARRANTY_RESOLVED"]
    fits = db.execute(select(TyreFitment).where(TyreFitment.tyre_id == t["id"])).scalars().all()
    assert len(fits) == 4 and all(f.current_slot is None for f in fits)
    c = tyres.tyre_cost(db, tt)
    assert c["net_cost"] == Decimal("31000.00") and c["km"] == Decimal("6000.0")  # 30000 + 6000 − 5000 warranty
    assert c["cost_per_km"] == Decimal("5.1667")
    tl = tyres.timeline(db, t["id"])
    assert tl[3]["from_vehicle"] == "TN01AA0001" and tl[3]["to_vehicle"] == "TN01AA0002"


def test_duplicate_position_occupancy_prevented(ctx, fleet):
    a, b = new_tyre(ctx, fleet, "SN-200"), new_tyre(ctx, fleet, "SN-201")
    act(ctx, a["id"], "install", vehicle_id=fleet.v.lpg["id"], position_id=fleet.pos["FL"], date=at(0), odometer="100100")
    with pytest.raises(BusinessError) as e:
        act(ctx, b["id"], "install", vehicle_id=fleet.v.lpg["id"], position_id=fleet.pos["FL"], date=at(1), odometer="100200")
    assert e.value.code == "POSITION_OCCUPIED"
    with pytest.raises(BusinessError):  # an installed tyre cannot be installed again
        act(ctx, a["id"], "install", vehicle_id=fleet.v.open["id"], position_id=fleet.pos["FL"], date=at(1), odometer="100200")


def test_database_enforces_single_occupancy(ctx, fleet):
    from sqlalchemy.exc import IntegrityError
    a, b = new_tyre(ctx, fleet, "SN-300"), new_tyre(ctx, fleet, "SN-301")
    ctx.db.add(TyreFitment(tyre_id=a["id"], vehicle_id=fleet.v.lpg["id"], position_id=fleet.pos["FR"],
                           installed_at=D0, install_odometer=1, current_slot=1))
    ctx.db.flush()
    with pytest.raises(IntegrityError):
        with ctx.db.begin_nested():
            ctx.db.add(TyreFitment(tyre_id=b["id"], vehicle_id=fleet.v.lpg["id"], position_id=fleet.pos["FR"],
                                   installed_at=D0, install_odometer=1, current_slot=1))
            ctx.db.flush()


def test_position_must_exist_in_vehicle_layout(ctx, fleet):
    t = new_tyre(ctx, fleet, "SN-400")
    with pytest.raises(BusinessError):  # trailer position on a truck layout
        act(ctx, t["id"], "install", vehicle_id=fleet.v.lpg["id"], position_id=fleet.pos["T1LO"], date=at(0), odometer="100100")


def test_shift_swap(ctx, fleet):
    a, b = new_tyre(ctx, fleet, "SN-500"), new_tyre(ctx, fleet, "SN-501")
    act(ctx, a["id"], "install", vehicle_id=fleet.v.lpg["id"], position_id=fleet.pos["FL"], date=at(0), odometer="100100")
    act(ctx, b["id"], "install", vehicle_id=fleet.v.lpg["id"], position_id=fleet.pos["FR"], date=at(0), odometer="100100")
    with pytest.raises(BusinessError):
        act(ctx, a["id"], "shift", position_id=fleet.pos["FR"], date=at(5), odometer="100600")
    act(ctx, a["id"], "shift", position_id=fleet.pos["FR"], swap=True, date=at(5), odometer="100600")
    assert ctx.db.get(Tyre, a["id"]).current_position_id == fleet.pos["FR"]
    assert ctx.db.get(Tyre, b["id"]).current_position_id == fleet.pos["FL"]


def test_removal_odometer_below_installation_requires_override(ctx, fleet):
    t = new_tyre(ctx, fleet, "SN-600")
    act(ctx, t["id"], "install", vehicle_id=fleet.v.open["id"], position_id=fleet.pos["FL"], date=at(0), odometer="100500")
    with pytest.raises(OverrideRequired):
        act(ctx, t["id"], "remove", date=at(3), odometer="100400", to_location_id=fleet.tl["GODOWN"])
    ctx.override = True
    res = masters.run_action(ctx, masters.get_spec(SPEC), t["id"], "remove", {
        "date": at(3), "odometer": "100400", "to_location_id": fleet.tl["GODOWN"], "reason": "Meter replaced", "override": True})
    assert "Removed" in res["message"]


def test_scrap_and_invalid_transitions(ctx, fleet):
    t = new_tyre(ctx, fleet, "SN-700")
    with pytest.raises(BusinessError):  # not fitted → cannot remove
        act(ctx, t["id"], "remove", date=at(1), odometer="1", to_location_id=fleet.tl["GODOWN"])
    act(ctx, t["id"], "scrap", date=at(2)[:10], reason="Cut beyond repair", scrap_value="500")
    assert ctx.db.get(Tyre, t["id"]).current_status == "SCRAPPED"
    with pytest.raises(BusinessError):
        act(ctx, t["id"], "install", vehicle_id=fleet.v.lpg["id"], position_id=fleet.pos["FL"], date=at(3), odometer="100100")


def test_lifecycle_fields_not_directly_editable_and_correction_audited(ctx, fleet):
    t = new_tyre(ctx, fleet, "SN-800")
    with pytest.raises(BusinessError):
        masters.save_record(ctx, masters.get_spec(SPEC), {"retread_count": 5}, t["id"])
    act(ctx, t["id"], "correct", retread_count=1, reason="Legacy tyre was retreaded once before go-live")
    assert ctx.db.get(Tyre, t["id"]).retread_count == 1
    assert movements(ctx.db, t["id"])[-1] == "CORRECTION"


def test_inspection_and_dashboard(ctx, fleet):
    t = new_tyre(ctx, fleet, "SN-900")
    act(ctx, t["id"], "install", vehicle_id=fleet.v.lpg["id"], position_id=fleet.pos["R1LI"], date=at(0), odometer="100100")
    res = act(ctx, t["id"], "inspect", date=at(5)[:10], tread_depth="2.5", pressure_psi="110", condition="WORN")
    assert "threshold" in " ".join(res["warnings"])
    d = tyres.vehicle_tyres(ctx.db, fleet.v.lpg["id"])
    pos = {p["code"]: p for p in d["positions"]}
    assert set(pos) >= {"FL", "FR", "R1LO", "R1LI", "R1RI", "R1RO", "R2LO", "SP1"}
    assert pos["R1LI"]["tyre"]["serial"] == "SN-900" and pos["R1LI"]["tyre"]["low_tread"] is True
    assert pos["FL"]["tyre"] is None
