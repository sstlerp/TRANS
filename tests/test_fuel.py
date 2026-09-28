"""Fuel: fuel types, multiple fuels, compatibility, qty×rate validation, efficiency,
odometer, duplicates, provider layouts, manual = import table (criteria 24-27, 33)."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import BusinessError, OverrideRequired
from app.models.imports import StatementImportTemplate
from app.models.operations import FuelTransaction
from app.sample_files import fuel_bpcl, fuel_iocl
from app.services import import_engine, masters, reports
from tests.factories import fuel_txn

NOW = datetime.now().replace(second=0, microsecond=0)


def tpl(db, name):
    return db.execute(select(StatementImportTemplate).where(StatementImportTemplate.template_name == name)).scalar_one().id


@pytest.mark.parametrize("vehicle,fuel,unit", [("lpg", "DIESEL", "L"), ("petrol", "PETROL", "L"), ("cng", "CNG", "KG")])
def test_diesel_petrol_cng_supported(ctx, fleet, vehicle, fuel, unit):
    t = fuel_txn(ctx, fleet, getattr(fleet.v, vehicle), fuel, 50, 90)
    assert t["status"] == "VALIDATED" and t["unit_id__label"].startswith(unit)
    assert t["cost_center_id"] == getattr(fleet.v, vehicle)["cost_center_id"]
    assert t["source_type"] == "MANUAL"


def test_multiple_fuel_types_on_one_vehicle(ctx, fleet):
    assert fuel_txn(ctx, fleet, fleet.v.dual, "DIESEL", 40, 90)["status"] == "VALIDATED"
    assert fuel_txn(ctx, fleet, fleet.v.dual, "CNG", 20, 80, when=NOW - timedelta(days=2))["status"] == "VALIDATED"


def test_invalid_fuel_compatibility_requires_override(ctx, fleet):
    with pytest.raises(OverrideRequired) as e:
        fuel_txn(ctx, fleet, fleet.v.cng, "DIESEL", 50, 90)
    assert e.value.code == "FUEL_TYPE_INCOMPATIBLE"
    t = fuel_txn(ctx, fleet, fleet.v.cng, "DIESEL", 50, 90, override=True, override_reason="Emergency conversion kit")
    assert t["status"] == "OVERRIDDEN" and "FUEL_TYPE_INCOMPATIBLE" in t["validation_flags"]


def test_quantity_rate_amount_tolerance(ctx, fleet):
    ok = fuel_txn(ctx, fleet, fleet.v.lpg, "DIESEL", 100, 89.5, amount="8952.00")  # within ₹5 tolerance (rounding)
    assert ok["status"] == "VALIDATED"
    with pytest.raises(OverrideRequired) as e:
        fuel_txn(ctx, fleet, fleet.v.lpg, "DIESEL", 100, 89.5, amount="9500.00", when=NOW - timedelta(days=1))
    assert e.value.code == "AMOUNT_MISMATCH"
    from app.services.rules import set_rule
    set_rule(ctx.db, "FUEL_AMOUNT_TOLERANCE_PCT", "10")
    assert fuel_txn(ctx, fleet, fleet.v.lpg, "DIESEL", 100, 89.5, amount="9500.00", when=NOW - timedelta(days=1))["status"] == "VALIDATED"


def test_negative_quantity_rejected(ctx, fleet):
    with pytest.raises(BusinessError):
        fuel_txn(ctx, fleet, fleet.v.lpg, "DIESEL", -5, 90)


def test_fuel_efficiency_and_unusual_flag(ctx, fleet):
    fuel_txn(ctx, fleet, fleet.v.open, "DIESEL", 100, 90, odo=100400, when=NOW - timedelta(days=5))
    t2 = fuel_txn(ctx, fleet, fleet.v.open, "DIESEL", 100, 90, odo=100800, when=NOW - timedelta(days=3))
    assert Decimal(t2["efficiency"]) == Decimal("4.000") and t2["efficiency_flag"] == "NORMAL"
    t3 = fuel_txn(ctx, fleet, fleet.v.open, "DIESEL", 50, 90, odo=101300, when=NOW - timedelta(days=1))
    assert Decimal(t3["efficiency"]) == Decimal("10.000") and t3["efficiency_flag"] == "HIGH"  # unusual — not "fraud"
    rep = reports.run(ctx.db, "fuel_efficiency", {})
    assert any(r[0] == "TN01AA0002" for r in rep["rows"])


def test_odometer_validation_on_fuel(ctx, fleet):
    fuel_txn(ctx, fleet, fleet.v.open, "DIESEL", 50, 90, odo=100500, when=NOW - timedelta(days=3))
    with pytest.raises(OverrideRequired):
        fuel_txn(ctx, fleet, fleet.v.open, "DIESEL", 50, 90, odo=100200, when=NOW - timedelta(days=1))


def test_duplicate_manual_fuel_transaction(ctx, fleet):
    fuel_txn(ctx, fleet, fleet.v.lpg, "DIESEL", 60, 90, when=NOW - timedelta(days=4), provider_transaction_id=None)
    with pytest.raises(BusinessError):
        fuel_txn(ctx, fleet, fleet.v.lpg, "DIESEL", 60, 90, when=NOW - timedelta(days=4), provider_transaction_id=None)


def test_fuel_import_two_provider_layouts_same_table(ctx, fleet):
    # align sample vehicle numbers with the test fleet via value mappings (configuration, not code)
    for raw, v in (("TN01AB1234", fleet.v.lpg), ("TN02CD5678", fleet.v.open), ("TN09EF9012", fleet.v.cng),
                   ("TN18GH3456", fleet.v.dual), ("TN20JK7890", fleet.v.lpg)):
        masters.save_record(ctx, masters.get_spec("value_mappings"), {"mapping_type": "VEHICLE", "source_value": raw, "target_id": v["id"]})
    b1 = import_engine.create_preview(ctx, tpl(ctx.db, "IOCL XTRAPOWER Transactions"), fuel_iocl(), "iocl.xlsx")
    assert (b1.total_rows, b1.duplicate_rows) == (7, 1)
    import_engine.commit_batch(ctx, b1.id)
    rows = {t.provider_transaction_id: t for t in ctx.db.execute(select(FuelTransaction).where(
        FuelTransaction.import_batch_id == b1.id)).scalars()}
    assert len(rows) == 6
    assert rows["IO-5001"].fuel_type_raw == "DIESEL" and rows["IO-5001"].status == "VALIDATED"  # HSD mapped → DIESEL
    assert rows["IO-5003"].fuel_type_raw == "DIESEL"  # provider-specific XTRAMILE mapping
    assert rows["IO-5004"].status == "FLAGGED" and "FUEL_TYPE_INCOMPATIBLE" in rows["IO-5004"].validation_flags
    assert rows["IO-5005"].status == "VEHICLE_UNMATCHED" and rows["IO-5005"].vehicle_id is None and rows["IO-5005"].cost_center_id is None
    assert "AMOUNT_MISMATCH" in rows["IO-5006"].validation_flags
    assert rows["IO-5001"].source_row == 2 and rows["IO-5001"].source_type == "EXCEL"
    b2 = import_engine.create_preview(ctx, tpl(ctx.db, "BPCL SmartFleet Statement"), fuel_bpcl(), "bpcl.xlsx")
    import_engine.commit_batch(ctx, b2.id)
    cng = ctx.db.execute(select(FuelTransaction).where(FuelTransaction.provider_transaction_id == "BP-9001")).scalar_one()
    assert cng.quantity == Decimal("20.500") and cng.status == "VALIDATED"
    # the same normalised table holds manual + both providers
    fuel_txn(ctx, fleet, fleet.v.lpg, "DIESEL", 10, 90)
    kinds = set(ctx.db.execute(select(FuelTransaction.source_type)).scalars())
    assert kinds == {"EXCEL", "MANUAL"}
    # resolving an unmatched row later (and learning the mapping)
    masters.run_action(ctx, masters.get_spec("fuel_transactions"), rows["IO-5005"].id, "resolve",
                       {"vehicle_id": fleet.v.open["id"], "create_mapping": True, "reason": "Hired vehicle"})
    assert ctx.db.get(FuelTransaction, rows["IO-5005"].id).vehicle_id == fleet.v.open["id"]
