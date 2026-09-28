"""Toll: provider-specific templates, provider-scoped IDs, vehicle/plaza matching, review,
duplicates, manual entry and API feed into one table (criteria 28-32)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import BusinessError
from app.models.imports import StatementImportTemplate
from app.models.operations import TollTransaction
from app.sample_files import toll_fastway, toll_highroad
from app.services import import_engine, masters
from tests.factories import dmy


def tpl(db, name):
    return db.execute(select(StatementImportTemplate).where(StatementImportTemplate.template_name == name)).scalar_one().id


def _map_vehicles(ctx, f):
    for raw, v in (("TN01AB1234", f.v.lpg), ("TN02CD5678", f.v.open), ("TN09EF9012", f.v.cng), ("TN18GH3456", f.v.dual),
                   ("TN20JK7890", f.v.petrol)):
        masters.save_record(ctx, masters.get_spec("value_mappings"), {"mapping_type": "VEHICLE", "source_value": raw, "target_id": v["id"]})


def test_provider_specific_layouts_and_provider_scoped_ids(ctx, fleet):
    _map_vehicles(ctx, fleet)
    a = import_engine.create_preview(ctx, tpl(ctx.db, "FastWay FASTag Statement"), toll_fastway(), "fastway.xlsx")
    assert a.total_rows == 8 and a.duplicate_rows == 1 and a.error_rows == 1  # duplicate FW1002, bad date 31/02
    import_engine.commit_batch(ctx, a.id)
    b = import_engine.create_preview(ctx, tpl(ctx.db, "HighRoad Toll Transactions"), toll_highroad(), "highroad.xlsx")
    assert b.duplicate_rows == 0  # 'FW1001' also exists at provider A — ids are provider-scoped
    import_engine.commit_batch(ctx, b.id)
    fw = ctx.db.execute(select(TollTransaction).where(TollTransaction.transaction_id == "FW1001")).scalars().all()
    assert len(fw) == 2 and len({t.provider_id for t in fw}) == 2
    t = {x.transaction_id: x for x in ctx.db.execute(select(TollTransaction).where(TollTransaction.import_batch_id == a.id)).scalars()}
    assert t["FW1003"].status == "VALIDATED" and t["FW1003"].vehicle_id == fleet.v.open["id"]  # "TN 02 CD 5678" normalised
    assert t["FW1004"].status == "VEHICLE_UNMATCHED" and t["FW1004"].cost_center_id is None  # KA05ZZ9999 unknown
    assert t["FW1005"].plaza_match_status == "PLAZA_UNMATCHED" and t["FW1005"].vehicle_id  # unknown plaza id 9999
    assert t["FW1006"].txn_kind == "REFUND"
    assert t["FW1001"].toll_plaza_id and t["FW1001"].cost_center_id == fleet.v.lpg["cost_center_id"]
    hr = ctx.db.execute(select(TollTransaction).where(TollTransaction.transaction_id == "HR-2004")).scalar_one()
    assert hr.txn_kind == "REFUND" and hr.amount == Decimal("60.00")  # "CR" wording via conditional transformation
    big = ctx.db.execute(select(TollTransaction).where(TollTransaction.transaction_id == "HR-2003")).scalar_one()
    assert big.amount == Decimal("1210.00") and big.txn_datetime.hour == 9


def test_unmatched_rows_reviewed_and_resolved_with_mapping(ctx, fleet):
    _map_vehicles(ctx, fleet)
    a = import_engine.create_preview(ctx, tpl(ctx.db, "FastWay FASTag Statement"), toll_fastway(), "fastway.xlsx")
    import_engine.commit_batch(ctx, a.id)
    row = ctx.db.execute(select(TollTransaction).where(TollTransaction.transaction_id == "FW1004")).scalar_one()
    masters.run_action(ctx, masters.get_spec("toll_transactions"), row.id, "resolve",
                       {"vehicle_id": fleet.v.cng["id"], "create_mapping": True, "reason": "Re-registered vehicle"})
    assert row.status == "VALIDATED" and row.cost_center_id == fleet.v.cng["cost_center_id"]
    plaza = ctx.db.execute(select(TollTransaction).where(TollTransaction.transaction_id == "FW1005")).scalar_one()
    plz = masters.options(ctx, masters.get_spec("toll_plazas"), "Krishnagiri")[0]["id"]
    masters.run_action(ctx, masters.get_spec("toll_transactions"), plaza.id, "resolve",
                       {"toll_plaza_id": plz, "create_mapping": True, "reason": "New plaza id"})
    assert plaza.plaza_match_status == "PLAZA_MATCHED"
    # the learned mappings apply to the next import automatically
    from app.services.operations import match_plaza, match_vehicle
    assert match_vehicle(ctx.db, row.provider_id, "KA05ZZ9999", date.today()) == fleet.v.cng["id"]
    assert match_plaza(ctx.db, row.provider_id, "9999", None, "New Unknown Plaza") == plz


def test_manual_toll_entry_same_table_and_duplicate_rejected(ctx, fleet):
    spec = masters.get_spec("toll_transactions")
    t = masters.save_record(ctx, spec, {"provider_id": fleet.prov["TOLL_A"], "transaction_id": "MANUAL-1",
                                        "txn_date": dmy(date.today()), "registration_raw": "tn01aa0001", "amount": "335",
                                        "plaza_name_raw": "Sriperumbudur Toll Plaza"})
    assert t["source_type"] == "MANUAL" and t["status"] == "VALIDATED" and t["vehicle_id"] == fleet.v.lpg["id"]
    with pytest.raises(BusinessError):
        masters.save_record(ctx, spec, {"provider_id": fleet.prov["TOLL_A"], "transaction_id": "MANUAL-1",
                                        "txn_date": dmy(date.today()), "amount": "335"})
    # the same id at a different provider is fine
    masters.save_record(ctx, spec, {"provider_id": fleet.prov["TOLL_B"], "transaction_id": "MANUAL-1",
                                    "txn_date": dmy(date.today()), "amount": "10"})


def test_api_feed_uses_same_table(client, auth, db, fleet):
    r = client.post(f"/api/integrations/toll/{fleet.prov['TOLL_B']}/transactions", headers=auth, json=[
        {"transaction_id": "API-1", "txn_datetime": "01/08/2025 10:00", "vehicle_number": "TN01AA0002", "plaza_code": "PLZ-A", "amount": "95"},
        {"transaction_id": "API-1", "txn_datetime": "01/08/2025 10:00", "vehicle_number": "TN01AA0002", "plaza_code": "PLZ-A", "amount": "95"}])
    assert r.status_code == 200 and r.json() == {"created": 1, "duplicates": 1}
    t = db.execute(select(TollTransaction).where(TollTransaction.transaction_id == "API-1")).scalar_one()
    assert t.source_type == "API" and t.status == "VALIDATED"
