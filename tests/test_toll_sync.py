"""Toll plaza master from internet sources: OpenStreetMap (Overpass), data.gov.in and custom JSON APIs.
The HTTP layer is replaced by recorded-style responses; toll ID, name, place and state are compulsory."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.errors import BusinessError
from app.models.operations import ApiIntegration, TollPlaza, TollPlazaSyncRun
from app.models.org import State
from app.services import toll_sync
from tests.conftest import login

# Overpass output for Tamil Nadu: each toll booth is followed by the place nodes around it
OSM_TN = {"elements": [
    {"type": "node", "id": 101, "lat": 12.5, "lon": 78.2,
     "tags": {"barrier": "toll_booth", "name": "Krishnagiri Toll Plaza", "addr:city": "Krishnagiri", "operator": "NHAI"}},
    {"type": "node", "id": 9001, "lat": 12.51, "lon": 78.21, "tags": {"place": "town", "name": "Krishnagiri"}},
    {"type": "way", "id": 202, "center": {"lat": 12.95, "lon": 79.95},
     "tags": {"barrier": "toll_booth", "name:en": "Sriperumbudur Toll Plaza", "name": "ஸ்ரீபெரும்புதூர் சுங்கச்சாவடி"}},
    {"type": "node", "id": 9002, "lat": 12.97, "lon": 79.94, "tags": {"place": "town", "name": "Sriperumbudur"}},
    {"type": "node", "id": 9003, "lat": 13.10, "lon": 80.10, "tags": {"place": "city", "name": "Chennai"}},
    {"type": "node", "id": 103, "lat": 11.0, "lon": 77.0, "tags": {"barrier": "toll_booth"}},  # no name → skipped
    {"type": "node", "id": 9004, "lat": 11.01, "lon": 77.01, "tags": {"place": "village", "name": "Chettipalayam"}},
    {"type": "node", "id": 104, "lat": 10.0, "lon": 78.0, "tags": {"barrier": "toll_booth", "name": "Lonely Toll"}},  # no place
]}
OSM_KA = {"elements": [
    {"type": "node", "id": 301, "lat": 13.0, "lon": 77.6,
     "tags": {"barrier": "toll_booth", "name": "Electronic City Toll Plaza", "addr:city": "Bengaluru"}},
]}


def osm_integration(db) -> ApiIntegration:
    return db.execute(select(ApiIntegration).where(ApiIntegration.code == "TOLL-OSM")).scalar_one()


@pytest.fixture
def fake_osm(monkeypatch):
    calls = []

    def http(url, *, params=None, data=None, headers=None, timeout=60, retries=3, backoff=2.0):
        q = data["data"]
        calls.append(q)
        if "IN-(TN)" in q:
            return OSM_TN
        if "IN-(KA)" in q:
            return OSM_KA
        raise BusinessError("Source returned HTTP 504 Gateway Timeout.")
    monkeypatch.setattr(toll_sync, "http_json", http)
    monkeypatch.setattr(toll_sync.time, "sleep", lambda s: None)
    return calls


def test_overpass_query_and_parse():
    q = toll_sync.overpass_query("OD", 8000, 120)
    assert 'IN-(OR|OD)' in q and 'barrier"="toll_booth' in q and "around.t:8000" in q and "[timeout:120]" in q
    recs = {f.record.toll_id: f.record for f in toll_sync.parse_overpass(OSM_TN, "TN")}
    assert recs["OSM-N101"].place == "Krishnagiri" and recs["OSM-N101"].state == "Tamil Nadu"
    sp = recs["OSM-W202"]  # way: centre coordinates, English name preferred, place = nearest town
    assert sp.name == "Sriperumbudur Toll Plaza" and sp.place == "Sriperumbudur" and sp.latitude == 12.95
    assert recs["OSM-N103"].missing() == ["toll plaza name"]
    assert recs["OSM-N104"].missing() == ["place"]
    # optional: name from the place when the source has none
    fb = {f.record.toll_id: f.record for f in toll_sync.parse_overpass(OSM_TN, "TN", name_fallback=True)}
    assert fb["OSM-N103"].name == "Chettipalayam Toll Plaza"


def test_state_names_from_sources():
    assert toll_sync.state_key("Orissa") == "OD" and toll_sync.state_key("IN-TS") == "TG"
    assert toll_sync.state_key("Jammu & Kashmir") == "JK" and toll_sync.state_key("IN-CT") == "CG"
    assert toll_sync.state_key("Atlantis") is None
    assert len(toll_sync.requested_states(None)) == 36
    with pytest.raises(BusinessError):
        toll_sync.requested_states(["Atlantis"])


def test_osm_sync_creates_updates_and_skips(ctx, fleet, fake_osm):
    db = ctx.db
    tn = db.execute(select(State).where(State.code == "TN")).scalar_one()
    # a plaza keyed in by hand earlier (no source) is linked, not duplicated
    manual = db.execute(select(TollPlaza).where(TollPlaza.name == "Krishnagiri Toll Plaza")).scalar_one()
    manual.state_id = tn.id
    db.flush()
    integ = osm_integration(db)
    run = toll_sync.run_now(db, integ, ["TN", "KA"], False, ctx.user.id)
    assert run.status == "SUCCESS" and run.states_done == 2
    assert (run.fetched, run.created, run.updated, run.skipped) == (5, 2, 1, 2)
    assert any("missing toll plaza name" in s for s in run.skipped_samples)
    assert any("OSM node/104" in s and "missing place" in s for s in run.skipped_samples)
    db.refresh(manual)
    assert manual.external_plaza_id == "OSM-N101" and manual.api_source == "OSM_OVERPASS" and manual.place == "Krishnagiri"
    assert manual.plaza_code == "PLZ-C"  # own code kept
    ec = db.execute(select(TollPlaza).where(TollPlaza.external_plaza_id == "OSM-N301")).scalar_one()
    assert (ec.name, ec.place, ec.state_name, ec.plaza_code) == ("Electronic City Toll Plaza", "Bengaluru", "Karnataka", "OSM-N301")
    assert ec.state_id == db.execute(select(State.id).where(State.code == "KA")).scalar_one()
    # every stored plaza from the source has all four compulsory values
    for p in db.execute(select(TollPlaza).where(TollPlaza.api_source == "OSM_OVERPASS")).scalars():
        assert p.external_plaza_id and p.name and p.place and p.state_id
    # second run: nothing new; a renamed plaza at the source is updated
    OSM_KA["elements"][0]["tags"]["name"] = "Electronic City Phase 1 Toll Plaza"
    try:
        run2 = toll_sync.run_now(db, integ, ["TN", "KA"], False, ctx.user.id)
    finally:
        OSM_KA["elements"][0]["tags"]["name"] = "Electronic City Toll Plaza"
    assert (run2.created, run2.updated, run2.unchanged) == (0, 1, 2)
    db.refresh(ec)
    assert ec.name == "Electronic City Phase 1 Toll Plaza"
    assert db.get(ApiIntegration, integ.id).last_sync_status == "SUCCESS"


def test_one_state_failing_keeps_the_others(ctx, fake_osm):
    run = toll_sync.run_now(ctx.db, osm_integration(ctx.db), ["KA", "KL"], False, ctx.user.id)
    assert run.status == "PARTIAL" and run.created == 1 and "KL: Source returned HTTP 504" in run.error_message
    run = toll_sync.run_now(ctx.db, osm_integration(ctx.db), ["KL"], False, ctx.user.id)
    assert run.status == "FAILED"


def test_dry_run_saves_nothing_but_keeps_the_run(ctx, fake_osm):
    db = ctx.db
    before = db.query(TollPlaza).count()
    run = toll_sync.run_now(db, osm_integration(db), ["KA"], True, ctx.user.id)
    assert run.dry_run and run.created == 1 and run.status == "SUCCESS"
    assert db.query(TollPlaza).count() == before
    assert db.get(TollPlazaSyncRun, run.id).created == 1


def test_data_gov_in_adapter(ctx, monkeypatch):
    db = ctx.db
    integ = db.execute(select(ApiIntegration).where(ApiIntegration.code == "TOLL-DATAGOV")).scalar_one()
    integ.is_active = True
    integ.settings = {**integ.settings, "resource_id": "abc-123", "page_size": 2}
    db.flush()
    monkeypatch.delenv("ERP_DATA_GOV_IN_API_KEY", raising=False)
    with pytest.raises(BusinessError, match="ERP_DATA_GOV_IN_API_KEY"):
        toll_sync.run_now(db, integ, [], False, ctx.user.id)
    monkeypatch.setenv("ERP_DATA_GOV_IN_API_KEY", "k-test")
    pages = {0: [{"toll_plaza_id": "7001", "toll_plaza_name": "Paranur Toll Plaza", "location": "Paranur", "state": "Tamil Nadu",
                  "nh_no_": "NH32"},
                 {"toll_plaza_id": "7002", "toll_plaza_name": "Talegaon Toll Plaza", "location": "Talegaon", "state": "Maharashtra"}],
             2: [{"toll_plaza_id": "7003", "toll_plaza_name": "Kherki Daula", "location": "Gurugram", "state": "Haryana"},
                 {"toll_plaza_id": "7004", "toll_plaza_name": "Nameless", "location": "", "state": "Orissa"}],
             4: [{"toll_plaza_id": "7005", "toll_plaza_name": "Cuttack Toll", "location": "Cuttack", "state": "Orissa"}]}
    seen = []

    def http(url, *, params=None, data=None, headers=None, timeout=60, retries=3, backoff=2.0):
        seen.append((url, dict(params)))
        return {"total": 5, "count": 2, "records": pages[params["offset"]]}
    monkeypatch.setattr(toll_sync, "http_json", http)
    run = toll_sync.run_now(db, integ, [], False, ctx.user.id)
    assert seen[0][0] == "https://api.data.gov.in/resource/abc-123" and seen[0][1]["api-key"] == "k-test"
    assert [p["offset"] for _, p in seen] == [0, 2, 4]
    assert (run.fetched, run.created, run.skipped, run.status) == (5, 4, 1, "SUCCESS")
    ct = db.execute(select(TollPlaza).where(TollPlaza.external_plaza_id == "7005")).scalar_one()
    assert ct.state_id == db.execute(select(State.id).where(State.code == "OD")).scalar_one() and ct.state_name == "Orissa"
    assert db.execute(select(TollPlaza).where(TollPlaza.external_plaza_id == "7001")).scalar_one().highway == "NH32"


def test_custom_json_adapter_with_api_key(ctx, monkeypatch):
    db = ctx.db
    integ = ApiIntegration(code="TOLL-FASTAG", name="FASTag partner", integration_type="TOLL_PLAZA_MASTER", is_active=True,
                           base_url="https://partner.example/api/plazas", auth_type="API_KEY", credential_env_var="ERP_TEST_TOLL_KEY",
                           settings={"adapter": "CUSTOM_JSON", "records_path": "data.items", "pagination": "none",
                                     "field_map": {"toll_id": "plazaCode", "name": "plazaName", "place": "address.city",
                                                   "state": "address.state"}})
    db.add(integ)
    db.flush()
    monkeypatch.setenv("ERP_TEST_TOLL_KEY", "secret-1")
    got = {}

    def http(url, *, params=None, data=None, headers=None, timeout=60, retries=3, backoff=2.0):
        got.update(url=url, headers=headers)
        return {"data": {"items": [{"plazaCode": "FT-9", "plazaName": "Vaniyambadi Toll", "address": {"city": "Vaniyambadi",
                                                                                                    "state": "TN"}}]}}
    monkeypatch.setattr(toll_sync, "http_json", http)
    run = toll_sync.run_now(db, integ, [], False, ctx.user.id)
    assert got["headers"] == {"X-API-Key": "secret-1"} and run.created == 1
    p = db.execute(select(TollPlaza).where(TollPlaza.external_plaza_id == "FT-9")).scalar_one()
    assert (p.name, p.place, p.api_source) == ("Vaniyambadi Toll", "Vaniyambadi", "CUSTOM_JSON")


def test_sync_api_and_permissions(client, db, fake_osm, monkeypatch):
    from tests.test_api import make_user
    h = {"Authorization": "Bearer " + login(client)["access_token"]}
    srcs = client.get("/api/toll-plazas/sync/sources", headers=h).json()
    assert {s["code"] for s in srcs} >= {"TOLL-OSM", "TOLL-DATAGOV"}
    assert len(client.get("/api/toll-plazas/sync/states", headers=h).json()) == 36
    r = client.post("/api/toll-plazas/sync", json={"states": ["Karnataka"], "wait": True}, headers=h)
    assert r.status_code == 200 and r.json()["created"] == 1 and r.json()["states"] == "KA"
    rid = r.json()["id"]
    assert client.get(f"/api/toll-plazas/sync/runs/{rid}", headers=h).json()["status"] == "SUCCESS"
    assert client.get("/api/toll-plazas/sync/runs", headers=h).json()[0]["id"] == rid
    assert client.get("/api/masters/toll_plaza_sync_runs", headers=h).json()["total"] >= 1
    # background mode returns the queued run at once
    monkeypatch.setattr(toll_sync, "run_background", lambda run_id: None)
    q = client.post("/api/toll-plazas/sync", json={"states": ["KA"]}, headers=h).json()
    assert q["status"] == "QUEUED"
    assert client.post("/api/toll-plazas/sync", json={"states": ["Atlantis"], "wait": True}, headers=h).status_code == 400
    make_user(db, "viewer1", "VIEWER")
    hv = {"Authorization": "Bearer " + login(client, "viewer1", "Passw0rd!")["access_token"]}
    assert client.post("/api/toll-plazas/sync", json={"wait": True}, headers=hv).status_code == 403
    assert client.get("/api/toll-plazas/sync/runs", headers=hv).status_code == 200


def test_manual_plaza_needs_place_and_state(client, db):
    h = {"Authorization": "Bearer " + login(client)["access_token"]}
    r = client.post("/api/masters/toll_plazas", json={"plaza_code": "PLZ-X", "name": "Test Plaza"}, headers=h)
    assert r.status_code in (400, 422)
    fields = {e.get("field") for e in r.json().get("errors", [])}
    assert {"place", "state_id"} <= fields
    tn = db.execute(select(State.id).where(State.code == "TN")).scalar_one()
    r = client.post("/api/masters/toll_plazas", json={"plaza_code": "PLZ-X", "name": "Test Plaza", "place": "Hosur",
                                                      "state_id": tn}, headers=h)
    assert r.status_code == 200, r.text


def test_integration_settings_json_is_validated(client):
    h = {"Authorization": "Bearer " + login(client)["access_token"]}
    body = {"code": "T-JSON", "name": "x", "integration_type": "TOLL_PLAZA_MASTER", "settings": "{not json"}
    r = client.post("/api/masters/api_integrations", json=body, headers=h)
    assert r.status_code in (400, 422) and "not valid JSON" in r.text
    body["settings"] = '{"adapter": "OSM_OVERPASS"}'
    r = client.post("/api/masters/api_integrations", json=body, headers=h)
    assert r.status_code == 200 and r.json()["settings"] == {"adapter": "OSM_OVERPASS"}


def test_user_edits_are_kept_by_later_fetches(client, db, fake_osm):
    """Editing a fetched plaza locks it; the next fetch keeps the user's values until the lock is removed."""
    h = {"Authorization": "Bearer " + login(client)["access_token"]}
    assert client.post("/api/toll-plazas/sync", json={"states": ["KA"], "wait": True}, headers=h).json()["created"] == 1
    p = db.execute(select(TollPlaza).where(TollPlaza.external_plaza_id == "OSM-N301")).scalar_one()
    assert p.details_locked is False
    r = client.put(f"/api/masters/toll_plazas/{p.id}", json={"place": "Electronic City"}, headers=h)
    assert r.status_code == 200 and r.json()["details_locked"] is True
    assert any("kept" in w for w in r.json()["_warnings"])
    run = client.post("/api/toll-plazas/sync", json={"states": ["KA"], "wait": True}, headers=h).json()
    assert (run["locked"], run["updated"]) == (1, 0)
    db.refresh(p)
    assert p.place == "Electronic City"
    # unticking "Keep My Changes" lets the internet source update it again
    r = client.put(f"/api/masters/toll_plazas/{p.id}", json={"details_locked": False}, headers=h)
    assert r.json()["details_locked"] is False
    run = client.post("/api/toll-plazas/sync", json={"states": ["KA"], "wait": True}, headers=h).json()
    assert (run["locked"], run["updated"]) == (0, 1)
    db.refresh(p)
    assert p.place == "Bengaluru"
    # plazas keyed in by hand are never locked automatically
    tn = db.execute(select(State.id).where(State.code == "TN")).scalar_one()
    m = client.post("/api/masters/toll_plazas", json={"plaza_code": "PLZ-M", "name": "Manual Plaza", "place": "Hosur",
                                                      "state_id": tn}, headers=h).json()
    assert client.put(f"/api/masters/toll_plazas/{m['id']}", json={"place": "Hosur Bypass"}, headers=h).json()["details_locked"] is False


def test_directory_summary_and_map(client, db, fake_osm):
    h = {"Authorization": "Bearer " + login(client)["access_token"]}
    client.post("/api/toll-plazas/sync", json={"states": ["TN", "KA"], "wait": True}, headers=h)
    s = client.get("/api/toll-plazas/summary", headers=h).json()
    assert s["total"] >= 3 and s["from_internet"] == 3 and s["total"] == s["from_internet"] + s["entered_by_hand"]
    ka = next(r for r in s["by_state"] if r["code"] == "KA")
    assert (ka["total"], ka["from_internet"], ka["name"]) == (1, 1, "Karnataka")
    pts = client.get(f"/api/toll-plazas/map?state_id={ka['state_id']}", headers=h).json()
    assert [(p["toll_id"], p["name"], p["place"], p["state"], p["lat"]) for p in pts] == \
        [("OSM-N301", "Electronic City Toll Plaza", "Bengaluru", "Karnataka", 13.0)]
    assert [p["toll_id"] for p in client.get("/api/toll-plazas/map?q=sriperumbudur", headers=h).json()] == ["OSM-W202"]
    manual = client.get("/api/toll-plazas/map?source=MANUAL", headers=h).json()
    assert all(p["source"] is None for p in manual)
    client.cookies.set("erp_session", login(client)["access_token"])
    page = client.get("/toll/plazas/directory")
    assert page.status_code == 200 and "td-map" in page.text and "tile.openstreetmap.org" in page.headers["content-security-policy"]
    assert 'href="/toll/plazas/directory"' in client.get("/m/toll").text
