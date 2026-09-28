"""Fleet: categories, sub-categories, attributes, cost centers, classification history,
multiple fuels, odometer control (acceptance criteria 1-7, 26, 45, 55)."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.errors import BusinessError, OverrideRequired
from app.models.fleet import CostCenter, OdometerReading, Vehicle, VehicleCostCenterHistory, VehicleFuel
from app.services import masters, vehicles
from tests.factories import dmy


def test_admin_creates_categories_subcategories_and_attributes(ctx):
    cat = masters.save_record(ctx, masters.get_spec("cost_categories"), {"code": "TIPPER", "name": "Tipper", "applies_to": "VEHICLE"})
    sub = masters.save_record(ctx, masters.get_spec("sub_categories"), {"cost_category_id": cat["id"], "code": "ROCK", "name": "Rock Body"})
    attr = masters.save_record(ctx, masters.get_spec("sub_category_attributes"), {
        "sub_category_id": sub["id"], "code": "BODY_L", "name": "Body Length", "data_type": "DECIMAL", "is_mandatory": True})
    assert attr["data_type"] == "DECIMAL" and attr["is_mandatory"] is True
    # duplicate codes are rejected with a friendly message
    with pytest.raises(BusinessError) as e:
        masters.save_record(ctx, masters.get_spec("cost_categories"), {"code": "TIPPER", "name": "Tipper 2"})
    assert "Duplicate" in e.value.message


def test_vehicle_becomes_cost_center_and_attributes_are_stored(ctx, fleet):
    v = fleet.v.lpg
    cc = ctx.db.get(CostCenter, v["cost_center_id"])
    assert cc.cc_type == "VEHICLE" and cc.vehicle_id == v["id"]
    assert v["attributes"]  # tank capacity + axle count
    h = ctx.db.execute(select(VehicleCostCenterHistory).where(VehicleCostCenterHistory.vehicle_id == v["id"])).scalars().all()
    assert len(h) == 1 and h[0].effective_to is None


def test_mandatory_attribute_enforced(ctx, fleet):
    spec = masters.get_spec("vehicles")
    with pytest.raises(BusinessError) as e:
        masters.save_record(ctx, spec, {"vehicle_code": "X1", "registration_number": "TN99ZZ0001",
                                        "cost_category_id": fleet.cats["TRUCK"], "sub_category_id": fleet.subs["LPG"],
                                        "vehicle_status": "ACTIVE", "fuels": [{"fuel_type_id": fleet.fuels["DIESEL"], "is_active": True}],
                                        "attributes": {}})
    assert "attributes" in e.value.message.lower() or e.value.errors


def test_subcategory_must_belong_to_category(ctx, fleet):
    with pytest.raises(BusinessError):
        masters.save_record(ctx, masters.get_spec("vehicles"), {
            "vehicle_code": "X2", "registration_number": "TN99ZZ0002", "cost_category_id": fleet.cats["TRAILER"],
            "sub_category_id": fleet.subs["LPG"], "vehicle_status": "ACTIVE",
            "fuels": [{"fuel_type_id": fleet.fuels["DIESEL"], "is_active": True}]})


def test_non_vehicle_cost_centers(ctx):
    cc = masters.save_record(ctx, masters.get_spec("cost_centers"), {"code": "CC-HR", "name": "HR Department", "cc_type": "NON_VEHICLE"})
    assert cc["cc_type"] == "NON_VEHICLE" and cc["vehicle_id"] is None


def test_reclassification_preserves_history(ctx, fleet):
    v = fleet.v.lpg
    eff = date.today() - timedelta(days=30)
    res = masters.run_action(ctx, masters.get_spec("vehicles"), v["id"], "reclassify", {
        "effective_from": dmy(eff), "cost_category_id": fleet.cats["TRUCK"], "sub_category_id": fleet.subs["CONTAINER"],
        "reason": "Tank removed; converted to container carrier"})
    assert "history preserved" in res["message"]
    hist = ctx.db.execute(select(VehicleCostCenterHistory).where(VehicleCostCenterHistory.vehicle_id == v["id"])
                          .order_by(VehicleCostCenterHistory.effective_from)).scalars().all()
    assert len(hist) == 2
    assert hist[0].new_sub_category_id == fleet.subs["LPG"] and hist[0].effective_to == eff - timedelta(days=1)
    assert hist[1].new_sub_category_id == fleet.subs["CONTAINER"] and hist[1].effective_to is None
    # the classification as at an earlier date is still LPG
    assert vehicles.classification_at(ctx.db, v["id"], eff - timedelta(days=5)).new_sub_category_id == fleet.subs["LPG"]
    assert vehicles.classification_at(ctx.db, v["id"], date.today()).new_sub_category_id == fleet.subs["CONTAINER"]
    assert ctx.db.get(Vehicle, v["id"]).sub_category_id == fleet.subs["CONTAINER"]
    # history can never be rewritten backwards
    with pytest.raises(BusinessError):
        masters.run_action(ctx, masters.get_spec("vehicles"), v["id"], "reclassify", {
            "effective_from": dmy(eff - timedelta(days=60)), "cost_category_id": fleet.cats["TRUCK"],
            "sub_category_id": fleet.subs["LPG"], "reason": "backdate"})


def test_category_fields_locked_on_edit(ctx, fleet):
    v = fleet.v.open
    rec = masters.save_record(ctx, masters.get_spec("vehicles"), {"sub_category_id": fleet.subs["LPG"], "remarks": "x"}, v["id"])
    assert rec["sub_category_id"] == fleet.subs["OPEN_BODY"]  # ignored: must use the reclassify action


def test_multiple_fuel_types_per_vehicle(ctx, fleet):
    fuels = ctx.db.execute(select(VehicleFuel).where(VehicleFuel.vehicle_id == fleet.v.dual["id"])).scalars().all()
    assert {f.fuel_type_id for f in fuels} == {fleet.fuels["DIESEL"], fleet.fuels["CNG"]}
    assert sum(f.is_primary for f in fuels) == 1
    assert vehicles.allowed_fuel_type_ids(ctx.db, fleet.v.dual["id"]) == {fleet.fuels["DIESEL"], fleet.fuels["CNG"]}


def test_vehicle_requires_a_fuel_configuration(ctx, fleet):
    with pytest.raises(BusinessError):
        masters.save_record(ctx, masters.get_spec("vehicles"), {"fuels": []}, fleet.v.open["id"])


def test_vehicle_number_normalised_and_unique(ctx, fleet):
    with pytest.raises(BusinessError):
        masters.save_record(ctx, masters.get_spec("vehicles"), {
            "vehicle_code": "DUP", "registration_number": "tn-01 aa 0001", "cost_category_id": fleet.cats["TRUCK"],
            "sub_category_id": fleet.subs["OPEN_BODY"], "vehicle_status": "ACTIVE",
            "fuels": [{"fuel_type_id": fleet.fuels["DIESEL"], "is_active": True}], "attributes": {}})
    assert vehicles.find_vehicle_by_number(ctx.db, "TN 01 AA 0001").id == fleet.v.lpg["id"]


def test_odometer_decrease_requires_authorised_override(ctx, fleet):
    vid = fleet.v.open["id"]
    vehicles.record_odometer(ctx, vid, 101000, datetime.now() - timedelta(days=2), "MANUAL")
    with pytest.raises(OverrideRequired):
        vehicles.record_odometer(ctx, vid, 100500, datetime.now() - timedelta(days=1), "MANUAL")
    ctx.override = True
    r = vehicles.record_odometer(ctx, vid, 100500, datetime.now() - timedelta(days=1), "MANUAL", reason="Meter replaced")
    assert r.is_override and r.override_reason == "Meter replaced"
    from app.models.system import AuditLog
    assert ctx.db.execute(select(AuditLog).where(AuditLog.action == "OVERRIDE", AuditLog.entity_type == "odometer")).first()


def test_odometer_warn_mode_is_configurable(ctx, fleet):
    from app.services.rules import set_rule
    set_rule(ctx.db, "ODOMETER_DECREASE_MODE", "WARN")
    vid = fleet.v.cng["id"]
    vehicles.record_odometer(ctx, vid, 105000, datetime.now() - timedelta(days=2), "MANUAL")
    vehicles.record_odometer(ctx, vid, 104000, datetime.now() - timedelta(days=1), "MANUAL")
    assert any("lower" in w for w in ctx.warnings)
