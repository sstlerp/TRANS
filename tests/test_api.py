"""API, authentication, CSRF, RBAC, branch restriction, audit, documents, exports, pages."""
from datetime import date

from sqlalchemy import select

from app.core.security import hash_password
from app.models.system import AuditLog, Role, User
from tests.conftest import login
from tests.factories import dmy


def make_user(db, username, role, branch_ids=None):
    u = User(username=username, full_name=username.title(), password_hash=hash_password("Passw0rd!"),
             all_branches=branch_ids is None)
    u.roles = [db.execute(select(Role).where(Role.code == role)).scalar_one()]
    db.add(u)
    db.flush()
    if branch_ids:
        from app.models.system import user_branches
        for b in branch_ids:
            db.execute(user_branches.insert().values(user_id=u.id, branch_id=b))
    return u


def bearer(client, username):
    return {"Authorization": "Bearer " + login(client, username, "Passw0rd!")["access_token"]}


def test_login_logout_and_bad_password(client):
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    assert client.get("/api/masters/vehicles").status_code == 401
    tok = login(client)
    assert tok["token_type"] == "bearer"
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer " + tok["access_token"]})
    assert r.status_code == 200 and r.json()["username"] == "admin"


def test_account_lockout(client, db):
    make_user(db, "locky", "VIEWER")
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "locky", "password": "nope"})
    r = client.post("/api/auth/login", json={"username": "locky", "password": "Passw0rd!"})
    assert r.status_code == 423


def test_cookie_session_requires_csrf_for_writes(client):
    tok = login(client)
    client.cookies.set("erp_session", tok["access_token"])
    client.cookies.set("erp_csrf", tok["csrf_token"])
    assert client.get("/api/masters/states?size=5").status_code == 200
    body = {"code": "ZZ", "name": "Test State"}
    assert client.post("/api/masters/states", json=body).status_code == 403
    assert client.post("/api/masters/states", json=body, headers={"X-CSRF-Token": tok["csrf_token"]}).status_code == 200


def test_rbac_viewer_cannot_create_or_see_admin(client, db, fleet):
    make_user(db, "viewer", "VIEWER")
    h = bearer(client, "viewer")
    assert client.get("/api/masters/vehicles", headers=h).status_code == 200
    r = client.post("/api/masters/vehicles", headers=h, json={"vehicle_code": "X"})
    assert r.status_code == 403 and "vehicles" not in r.text.lower() or r.json()["code"] == "FORBIDDEN"
    assert client.get("/api/masters/users", headers=h).status_code == 403
    assert client.get("/api/masters/audit_logs", headers=h).status_code == 403
    meta = client.get("/api/masters/vehicles/meta", headers=h).json()
    assert meta["perms"]["create"] is False and meta["perms"]["view"] is True


def test_rbac_sensitive_actions(client, db, fleet):
    make_user(db, "ops", "OPERATIONS")
    h = bearer(client, "ops")
    # operations can view finance? no
    assert client.get("/api/masters/bank_transactions", headers=h).status_code == 403
    # cannot approve
    assert client.get("/api/masters/approval_requests", headers=h).status_code == 200
    meta = client.get("/api/masters/approval_requests/meta", headers=h).json()
    assert not any(a["allowed"] for a in meta["actions"])


def test_branch_restriction(client, db, fleet):
    make_user(db, "b1user", "OPERATIONS", branch_ids=[fleet.branch.id])
    h = bearer(client, "b1user")
    regs = {v["registration_number"] for v in client.get("/api/masters/vehicles?size=100", headers=h).json()["items"]}
    assert "TN01AA0001" in regs and "TN01AA0005" not in regs  # T-PET belongs to branch 2


def test_master_crud_audit_and_soft_delete(client, auth, db):
    r = client.post("/api/masters/units", headers=auth, json={"code": "BOX", "name": "Box", "unit_type": "COUNT"})
    uid = r.json()["id"]
    client.put(f"/api/masters/units/{uid}", headers=auth, json={"name": "Carton Box"})
    r = client.delete(f"/api/masters/units/{uid}?reason=unused", headers=auth)
    assert r.status_code == 200
    got = client.get(f"/api/masters/units/{uid}", headers=auth).json()
    assert got["is_active"] is False and got["deleted_at"]  # soft delete keeps history
    acts = [a["action"] for a in client.get(f"/api/masters/units/{uid}/audit", headers=auth).json()]
    assert set(acts) >= {"CREATE", "UPDATE", "SOFT_DELETE"}
    upd = db.execute(select(AuditLog).where(AuditLog.entity_type == "units", AuditLog.action == "UPDATE")).scalars().first()
    assert upd.old_values == {"name": "Box"} and upd.new_values == {"name": "Carton Box"}


def test_validation_errors_are_friendly(client, auth):
    r = client.post("/api/masters/companies", headers=auth, json={"code": "", "name": "", "gstin": "BAD"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION" and {e["field"] for e in body["errors"]} >= {"code", "name", "gstin"}
    assert "Traceback" not in r.text


def test_search_filter_sort_paginate(client, auth, fleet):
    r = client.get("/api/masters/vehicles?q=AA000&sort=registration_number&dir=desc&size=2&page=1", headers=auth).json()
    assert r["total"] == 5 and len(r["items"]) == 2 and r["items"][0]["registration_number"] == "TN01AA0005"
    r = client.get(f"/api/masters/vehicles?f_sub_category_id={fleet.subs['OPEN_BODY']}", headers=auth).json()
    assert r["total"] == 3
    r = client.get("/api/masters/vehicles?q=TN01AA0001&exact=1", headers=auth).json()
    assert r["total"] == 1


def test_exports(client, auth, fleet):
    for fmt, ct in (("xlsx", "spreadsheetml"), ("csv", "text/csv"), ("pdf", "application/pdf")):
        r = client.get(f"/api/masters/vehicles/export?fmt={fmt}", headers=auth)
        assert r.status_code == 200 and ct in r.headers["content-type"]
    r = client.get("/api/reports/profitability/export?fmt=csv", headers=auth)
    assert r.status_code == 200 and "Net Contribution" in r.content.decode("utf-8-sig")
    client.post("/api/masters/drivers", headers=auth, json={"driver_code": "EXP1", "name": "Export Driver",
                                                           "license_expiry_date": "31/01/2040"})
    csv_text = client.get("/api/masters/drivers/export?fmt=csv", headers=auth).content.decode("utf-8-sig")
    assert "31/01/2040" in csv_text  # exports use DD/MM/YYYY


def test_document_upload_download_access(client, auth, db, fleet):
    vid = fleet.v.lpg["id"]
    r = client.post("/api/documents", headers=auth, data={"entity_type": "vehicles", "entity_id": vid, "document_type": "RC"},
                    files={"file": ("rc.pdf", b"%PDF-1.4 rc", "application/pdf")})
    assert r.status_code == 200
    did = r.json()["id"]
    assert client.get(f"/api/documents?entity_type=vehicles&entity_id={vid}", headers=auth).json()[0]["id"] == did
    dl = client.get(f"/api/documents/{did}/download", headers=auth)
    assert dl.status_code == 200 and dl.content.startswith(b"%PDF")
    make_user(db, "nofleet", "FINANCE")
    h = bearer(client, "nofleet")
    assert client.post("/api/documents", headers=h, data={"entity_type": "vehicles", "entity_id": vid, "document_type": "RC"},
                       files={"file": ("rc.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 403


def test_dates_accept_ddmmyyyy_and_return_iso(client, auth, fleet):
    r = client.post("/api/masters/drivers", headers=auth, json={"driver_code": "DRV1", "name": "Test Driver",
                                                                 "license_number": "TN01X", "license_issue_date": "01/02/2020",
                                                                 "license_expiry_date": "31/01/2040"})
    assert r.status_code == 200 and r.json()["license_expiry_date"] == "2040-01-31"
    r = client.post("/api/masters/drivers", headers=auth, json={"driver_code": "DRV2", "name": "X", "license_expiry_date": "31/02/2040"})
    assert r.status_code == 422


def test_pages_render(client, fleet):
    tok = login(client)
    client.cookies.set("erp_session", tok["access_token"])
    for url in ("/", "/dashboard", "/m/fleet", "/m/tyres", "/m/admin", "/masters/vehicles", "/masters/tyres", "/imports", "/finance/reconciliation", "/tyres/dashboard",
                "/compliance", "/reports", "/account/password", "/masters/import_templates", "/docs"):
        r = client.get(url)
        assert r.status_code == 200, url
    assert client.get("/masters/nope").status_code == 404
    assert client.get("/m/nope").status_code == 404
    home = client.get("/").text
    assert 'href="/m/fleet"' in home and 'href="/m/finance"' in home          # module cards
    fleet_page = client.get("/m/fleet").text
    assert 'href="/masters/vehicles"' in fleet_page                              # form cards
    assert 'href="/m/fleet"' in client.get("/masters/vehicles").text             # back to its module
    client.cookies.clear()
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_dashboard_and_reports_api(client, auth, fleet):
    d = client.get("/api/dashboard", headers=auth).json()
    assert d["fleet"]["total"] == 5 and "unmatched_credits" in d["finance"]
    for r in client.get("/api/reports", headers=auth).json():
        res = client.get(f"/api/reports/{r['key']}", headers=auth)
        assert res.status_code == 200, r["key"]


def test_global_search(client, auth, fleet):
    hits = client.get("/api/search?q=TN01AA0003", headers=auth).json()
    assert hits and hits[0]["kind"] == "Vehicle"


def test_import_wizard_api_flow(client, auth, db, fleet):
    from app.sample_files import bank_hdfc
    t = client.get("/api/imports/templates?statement_type=BANK", headers=auth).json()
    tid = next(x["id"] for x in t if x["template_name"].startswith("HDFC"))
    assert client.post("/api/imports/sheets", headers=auth, files={"file": ("s.xlsx", bank_hdfc())}).json()["sheets"] == ["Statement"]
    r = client.post("/api/imports/preview", headers=auth, data={"template_id": tid, "bank_account_id": fleet.acc1.id},
                    files={"file": ("hdfc.xlsx", bank_hdfc())})
    assert r.status_code == 200, r.text
    bid = r.json()["batch"]["id"]
    assert r.json()["status_counts"]["VALID"] == 11
    rows = client.get(f"/api/imports/batches/{bid}/rows?status=VALID&size=5", headers=auth).json()
    assert rows["total"] == 11 and rows["items"][0]["raw"]["B"]
    r = client.post(f"/api/imports/batches/{bid}/commit", headers=auth, json={})
    assert r.json()["batch"]["status"] == "COMPLETED"
    sug = client.get("/api/masters/bank_transactions?f_import_batch_id=%d&size=50" % bid, headers=auth).json()
    tid0 = sug["items"][0]["id"]
    assert client.get(f"/api/recon/{tid0}", headers=auth).status_code == 200
    assert client.get(f"/api/recon/{tid0}/suggestions", headers=auth).status_code == 200
