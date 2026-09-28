"""Test fixtures.

Runs against MySQL when ERP_TEST_DATABASE_URL is set (recommended, e.g.
mysql+pymysql://erp:erp_pass@127.0.0.1/trans_erp_test), otherwise against a
temporary SQLite file.  Reference data is seeded once per session; every test
runs inside a transaction that is rolled back (SAVEPOINT per commit).
"""
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("ERP_SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ["ERP_ENV"] = "test"
os.environ.setdefault("ERP_STORAGE_DIR", tempfile.mkdtemp(prefix="erp-storage-"))
os.environ.setdefault("ERP_LOG_DIR", tempfile.mkdtemp(prefix="erp-logs-"))
os.environ.setdefault("ERP_LOGIN_RATE_LIMIT", "1000")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

TEST_URL = os.environ.get("ERP_TEST_DATABASE_URL") or f"sqlite:///{tempfile.mkdtemp()}/erp_test.db"


@pytest.fixture(scope="session")
def engine():
    from app.database import make_engine, set_engine
    from app.models import Base
    from app.seed import seed_providers_and_templates, seed_reference, seed_security
    eng = make_engine(TEST_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    set_engine(eng)
    with Session(eng) as s:
        seed_security(s)
        seed_reference(s)
        seed_providers_and_templates(s)
        s.commit()
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    conn = engine.connect()
    trans = conn.begin()
    sess = Session(bind=conn, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False)
    try:
        yield sess
    finally:
        sess.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def admin(db):
    from app.core.security import load_user
    from app.models.system import User
    u = db.execute(select(User).where(User.username == "admin")).scalar_one()
    return load_user(db, u.id)


@pytest.fixture
def ctx(db, admin):
    import app.services.registry  # noqa: F401
    from app.services.masters import Ctx
    return Ctx(db, admin)


@pytest.fixture
def fleet(ctx):
    from tests.factories import build_fleet
    return build_fleet(ctx)


@pytest.fixture
def client(db):
    from app.database import get_db
    from app.main import app

    def _override():
        yield db
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def login(client, username="admin", password=None):
    password = password or os.environ.get("ERP_ADMIN_PASSWORD", "Admin@12345")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def auth(client):
    tok = login(client)["access_token"]
    return {"Authorization": f"Bearer {tok}"}
