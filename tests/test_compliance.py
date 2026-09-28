"""Compliance: multiple renewals, PESO rules, insurance policies, reminders, history, documents
(acceptance criteria 8-11)."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.errors import BusinessError
from app.models.compliance import (InsuranceHistory, InsurancePolicy, RenewalHistory, VehicleRenewal,
                                   VehicleRenewalAssignment)
from app.models.system import Notification
from app.services import documents, masters, renewals
from tests.factories import dmy

PDF = b"%PDF-1.4 test certificate"


def _renewal(ctx, f, vehicle_id, rtype, days, label="PRIMARY", assignment=None):
    return masters.save_record(ctx, masters.get_spec("vehicle_renewals"), {
        "vehicle_id": vehicle_id, "renewal_type_id": f.rt[rtype], "assignment_id": assignment, "reference_label": label,
        "certificate_number": f"{rtype}-{label}-{days}", "start_date": dmy(date.today() + timedelta(days=days - 365)),
        "expiry_date": dmy(date.today() + timedelta(days=days)), "amount": "1000", "tax_amount": "180"})


def test_peso_rule_creates_multiple_slots_for_lpg(ctx, fleet):
    slots = ctx.db.execute(select(VehicleRenewalAssignment).where(
        VehicleRenewalAssignment.vehicle_id == fleet.v.lpg["id"], VehicleRenewalAssignment.renewal_type_id == fleet.rt["PESO"])).scalars().all()
    assert sorted(s.reference_label for s in slots) == ["PESO #1", "PESO #2"]
    # not applicable to open-body trucks
    assert not ctx.db.execute(select(VehicleRenewalAssignment).where(
        VehicleRenewalAssignment.vehicle_id == fleet.v.open["id"], VehicleRenewalAssignment.renewal_type_id == fleet.rt["PESO"])).first()


def test_multiple_peso_certificates_and_statuses(ctx, fleet):
    slots = {s.reference_label: s.id for s in ctx.db.execute(select(VehicleRenewalAssignment).where(
        VehicleRenewalAssignment.vehicle_id == fleet.v.lpg["id"], VehicleRenewalAssignment.renewal_type_id == fleet.rt["PESO"])).scalars()}
    a = _renewal(ctx, fleet, fleet.v.lpg["id"], "PESO", 5, assignment=slots["PESO #1"])
    b = _renewal(ctx, fleet, fleet.v.lpg["id"], "PESO", 200, assignment=slots["PESO #2"])
    c = _renewal(ctx, fleet, fleet.v.lpg["id"], "FITNESS", -2)
    d = _renewal(ctx, fleet, fleet.v.lpg["id"], "QTAX", 20)
    assert (a["status"], b["status"], c["status"], d["status"]) == ("DUE", "NOT_DUE", "EXPIRED", "UPCOMING")
    assert a["total_amount"] == "1180.00"
    # a second current record for the same slot is refused — use Renew instead
    with pytest.raises(BusinessError):
        _renewal(ctx, fleet, fleet.v.lpg["id"], "PESO", 300, assignment=slots["PESO #1"])


def test_renew_keeps_history_and_supports_documents(ctx, fleet):
    r = _renewal(ctx, fleet, fleet.v.open["id"], "QTAX", 3)
    doc = documents.upload(ctx.db, ctx.user, "vehicle_renewals", r["id"], "TAX_RECEIPT", "qtax.pdf", PDF)
    res = masters.run_action(ctx, masters.get_spec("vehicle_renewals"), r["id"], "renew", {
        "certificate_number": "QT-NEW", "start_date": dmy(date.today() + timedelta(days=4)),
        "expiry_date": dmy(date.today() + timedelta(days=95)), "amount": "1500"})
    old, new = ctx.db.get(VehicleRenewal, r["id"]), ctx.db.get(VehicleRenewal, res["new_id"])
    assert old.status == "RENEWED" and not old.is_current
    assert new.is_current and new.previous_renewal_id == old.id and new.status == "NOT_DUE"
    hist = ctx.db.execute(select(RenewalHistory).where(RenewalHistory.renewal_id.in_([old.id, new.id]))).scalars().all()
    assert {h.action for h in hist} >= {"CREATE", "RENEWED"}
    assert documents.list_for(ctx.db, "vehicle_renewals", old.id)[0].id == doc.id
    documents.upload(ctx.db, ctx.user, "vehicle_renewals", new.id, "TAX_RECEIPT", "qtax2.pdf", PDF)
    assert documents.has_document(ctx.db, "vehicle_renewals", new.id)


def test_renewal_date_validation(ctx, fleet):
    with pytest.raises(BusinessError):
        masters.save_record(ctx, masters.get_spec("vehicle_renewals"), {
            "vehicle_id": fleet.v.open["id"], "renewal_type_id": fleet.rt["PUCC"],
            "start_date": dmy(date.today()), "expiry_date": dmy(date.today() - timedelta(days=1))})


def test_multiple_insurance_policies_and_renewal(ctx, fleet):
    spec = masters.get_spec("insurance_policies")
    ins = fleet.prov["INS_ICICI"]
    pols = [masters.save_record(ctx, spec, {"vehicle_id": fleet.v.lpg["id"], "provider_id": ins, "policy_type": t,
                                            "policy_number": f"POL-{t}", "start_date": dmy(date.today() - timedelta(days=300)),
                                            "expiry_date": dmy(date.today() + timedelta(days=d)), "premium": "10000",
                                            "tax_amount": "1800"}) for t, d in (("VEHICLE", 10), ("CLL", 60), ("PLI", 65))]
    assert len({p["id"] for p in pols}) == 3 and pols[0]["renewal_status"] == "UPCOMING" and pols[0]["total_premium"] == "11800.00"
    res = masters.run_action(ctx, spec, pols[0]["id"], "renew", {"policy_number": "POL-VEHICLE-2",
                                                               "start_date": dmy(date.today() + timedelta(days=11)),
                                                               "expiry_date": dmy(date.today() + timedelta(days=375)),
                                                               "premium": "11000"})
    assert ctx.db.get(InsurancePolicy, pols[0]["id"]).renewal_status == "RENEWED"
    assert ctx.db.get(InsurancePolicy, res["new_id"]).previous_policy_id == pols[0]["id"]
    assert ctx.db.execute(select(InsuranceHistory).where(InsuranceHistory.policy_id == pols[0]["id"])).scalars().all()
    active = ctx.db.execute(select(InsurancePolicy).where(InsurancePolicy.vehicle_id == fleet.v.lpg["id"],
                                                          InsurancePolicy.is_current.is_(True))).scalars().all()
    assert {p.policy_type for p in active} == {"VEHICLE", "CLL", "PLI"}


def test_expiry_alerts_use_configurable_reminders(ctx, fleet):
    r = _renewal(ctx, fleet, fleet.v.open["id"], "FITNESS", 6)
    e = _renewal(ctx, fleet, fleet.v.cng["id"], "FITNESS", -1)
    n = renewals.scan_alerts(ctx.db)
    assert n >= 2
    keys = {x.dedupe_key for x in ctx.db.execute(select(Notification)).scalars()}
    assert f"renewal:{r['id']}:7" in keys and f"renewal:{e['id']}:expired" in keys
    assert renewals.scan_alerts(ctx.db) == 0  # idempotent (no duplicate reminders)
    # per-slot override of reminder days
    a = ctx.db.get(VehicleRenewalAssignment, r["assignment_id"])
    a.reminder_days = "10"
    ctx.db.flush()
    renewals.scan_alerts(ctx.db)
    assert ctx.db.execute(select(Notification).where(Notification.dedupe_key == f"renewal:{r['id']}:10")).first()


def test_renewal_dashboard_counts(ctx, fleet):
    _renewal(ctx, fleet, fleet.v.open["id"], "PUCC", 0)
    _renewal(ctx, fleet, fleet.v.cng["id"], "PUCC", -3)
    d = renewals.dashboard(ctx.db)
    assert d["due_today"] >= 1 and d["expired"] >= 1 and d["pending_documents"] >= 2


def test_document_upload_validation(ctx, fleet):
    with pytest.raises(BusinessError):
        documents.upload(ctx.db, ctx.user, "vehicles", fleet.v.lpg["id"], "RC", "evil.exe", b"MZ....")
    with pytest.raises(BusinessError):
        documents.upload(ctx.db, ctx.user, "vehicles", fleet.v.lpg["id"], "RC", "fake.pdf", b"not a pdf")
    d = documents.upload(ctx.db, ctx.user, "vehicles", fleet.v.lpg["id"], "RC", "../../etc/rc.pdf", PDF)
    assert d.file_name == "rc.pdf" and ".." not in d.storage_key
    v2 = documents.upload(ctx.db, ctx.user, "vehicles", fleet.v.lpg["id"], "RC", "rc_v2.pdf", PDF, replaces_id=d.id)
    assert v2.version == 2 and v2.previous_document_id == d.id
