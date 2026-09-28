"""Maintenance job cards: parts/labour totals, cost center, odometer, next due, approval, history (criterion 34)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import OverrideRequired
from app.models.finance import ApprovalRequest
from app.models.operations import MaintenanceJobCard
from app.services import maintenance, masters
from tests.factories import dmy

T = date.today()


def job(ctx, f, number, vid, days_ago=5, odo=None, **extra):
    return masters.save_record(ctx, masters.get_spec("job_cards"), {
        "job_card_number": number, "vehicle_id": vid, "job_date": dmy(T - timedelta(days=days_ago)),
        "maintenance_type_id": f.mt["PM-10K"], "odometer": odo, "vendor_id": f.vendor.id, **extra})


def test_job_card_totals_cost_center_and_next_due(ctx, fleet):
    j = job(ctx, fleet, "JC-100", fleet.v.open["id"], odo="100900", tax_amount="0",
            parts=[{"part_name": "Oil filter", "quantity": "2", "rate": "450"}, {"part_name": "Engine oil", "quantity": "15", "rate": "300"}],
            labour=[{"description": "Service labour", "hours": "3", "rate": "500"}], other_amount="200")
    assert (j["parts_amount"], j["labour_amount"], j["total_amount"]) == ("5400.00", "1500.00", "7100.00")
    assert j["cost_center_id"] == fleet.v.open["cost_center_id"]
    assert Decimal(j["next_due_km"]) == Decimal("110900.0")  # interval from the maintenance type (configurable)
    res = masters.run_action(ctx, masters.get_spec("job_cards"), j["id"], "complete", {"work_performed": "10k service"})
    assert res["record"]["status"] == "COMPLETED"


def test_maintenance_history_per_vehicle(ctx, fleet):
    for i in range(3):
        job(ctx, fleet, f"JC-H{i}", fleet.v.lpg["id"], days_ago=30 - i * 10, other_amount="1000")
    rows = masters.list_records(ctx, masters.get_spec("job_cards"), {"f_vehicle_id": str(fleet.v.lpg["id"])})
    assert rows["total"] == 3


def test_job_card_odometer_is_validated(ctx, fleet):
    job(ctx, fleet, "JC-O1", fleet.v.cng["id"], days_ago=5, odo="101000", other_amount="10")
    with pytest.raises(OverrideRequired):
        job(ctx, fleet, "JC-O2", fleet.v.cng["id"], days_ago=2, odo="100500", other_amount="10")


def test_large_job_card_needs_approval(ctx, fleet):
    j = job(ctx, fleet, "JC-BIG", fleet.v.open["id"], other_amount="250000")
    assert j["approval_status"] == "PENDING"
    req = ctx.db.execute(select(ApprovalRequest).where(ApprovalRequest.entity_id == j["id"],
                                                       ApprovalRequest.action_type == "MAINTENANCE_APPROVAL")).scalar_one()
    masters.run_action(ctx, masters.get_spec("approval_requests"), req.id, "approve", {"reason": "OK"})
    assert ctx.db.get(MaintenanceJobCard, j["id"]).approval_status == "APPROVED"


def test_maintenance_due_alert(ctx, fleet):
    from app.services.vehicles import record_odometer
    from datetime import datetime
    job(ctx, fleet, "JC-D", fleet.v.dual["id"], days_ago=40, odo="100100", other_amount="10")
    record_odometer(ctx, fleet.v.dual["id"], 109800, datetime.now(), "MANUAL")  # within 500 km of 110100
    assert maintenance.due_alerts(ctx.db) == 1
