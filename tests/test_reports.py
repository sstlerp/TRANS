"""Reports: history-aware classification, profitability summary, cost/km, common cost allocation."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.services import masters, reports, vehicles
from app.services.rules import set_rule
from tests.factories import bank_txn, dmy, fuel_txn

T = date.today()


def test_historical_classification_in_reports(ctx, fleet):
    v = fleet.v.lpg
    # fuel while LPG (40 days ago), then reclassify to Container (20 days ago), more fuel after
    fuel_txn(ctx, fleet, v, "DIESEL", 100, 90, when=datetime.now() - timedelta(days=40))
    masters.run_action(ctx, masters.get_spec("vehicles"), v["id"], "reclassify", {
        "effective_from": dmy(T - timedelta(days=20)), "cost_category_id": fleet.cats["TRUCK"],
        "sub_category_id": fleet.subs["CONTAINER"], "reason": "Converted"})
    fuel_txn(ctx, fleet, v, "DIESEL", 50, 90, when=datetime.now() - timedelta(days=5))
    rows = {(r["category"], r["sub_category"]): r for r in reports.category_costs(ctx.db, T - timedelta(days=60), T)}
    assert rows[("Truck", "LPG")]["fuel"] == Decimal("9000.00")        # before the change → still LPG
    assert rows[("Truck", "Container")]["fuel"] == Decimal("4500.00")  # after the change → Container
    old = reports.profitability(ctx.db, T - timedelta(days=60), T - timedelta(days=30))
    assert next(r for r in old["rows"] if r["vehicle"] == "TN01AA0001")["sub_category"] == "LPG"


def test_profitability_cost_per_km_and_totals(ctx, fleet):
    v = fleet.v.open
    fuel_txn(ctx, fleet, v, "DIESEL", 100, 90, odo=100500, when=datetime.now() - timedelta(days=10))
    fuel_txn(ctx, fleet, v, "DIESEL", 100, 90, odo=101000, when=datetime.now() - timedelta(days=2))
    res = reports.profitability(ctx.db, T - timedelta(days=30), T)
    row = next(r for r in res["rows"] if r["vehicle"] == "TN01AA0002")
    assert row["fuel"] == Decimal("18000.00") and row["km"] == Decimal("1000.0")
    assert row["cost_per_km"] == Decimal("18.00") and row["fuel_per_km"] == Decimal("18.00")
    assert row["net_contribution"] == Decimal("-18000.00")


def test_common_cost_allocation_is_configurable(ctx, fleet):
    t = ctx.db.get(__import__("app.models.finance", fromlist=["BankTransaction"]).BankTransaction,
                   bank_txn(ctx, fleet.acc1.id, 5000, "DR", "OFFICE RENT")["id"])
    from app.services import bank
    bank.allocate(ctx, t, [{"cost_center_id": fleet.cc["CC-COMMON"], "amount": 5000, "expense_type_id": fleet.et["OFFICE"]}])
    res = reports.profitability(ctx.db, T - timedelta(days=30), T)
    assert sum(r["allocated_common"] for r in res["rows"] if r["cc_type"] == "VEHICLE") == 0
    set_rule(ctx.db, "COMMON_COST_ALLOCATION_BASIS", "EQUAL")
    res = reports.profitability(ctx.db, T - timedelta(days=30), T)
    veh = [r for r in res["rows"] if r["cc_type"] == "VEHICLE"]
    assert sum(r["allocated_common"] for r in veh) == Decimal("5000.00")
    assert res["totals"]["total_cost"] == Decimal("5000.00")  # moved, not duplicated


def test_expense_transaction_split_across_cost_centers(ctx, fleet):
    e = masters.save_record(ctx, masters.get_spec("expenses"), {
        "document_number": "EXP-1", "expense_date": dmy(T - timedelta(days=3)), "expense_type_id": fleet.et["DRIVER_SALARY"],
        "amount": "30000", "allocations": [{"vehicle_id": fleet.v.lpg["id"], "amount": "20000"},
                                           {"vehicle_id": fleet.v.open["id"], "amount": "10000"}]})
    assert e["total_amount"] == "30000.00"
    res = reports.profitability(ctx.db, T - timedelta(days=30), T)
    assert next(r for r in res["rows"] if r["vehicle"] == "TN01AA0001")["driver"] == Decimal("20000.00")
