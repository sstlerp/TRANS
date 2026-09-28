"""Database URL handling: passwords with URL-special characters work without manual escaping."""
import pytest
from sqlalchemy.engine import make_url

from app.config import Settings, normalize_db_url


@pytest.mark.parametrize("password", ["Pks@3115", "a:b/c#d?e", "p@ss:w0rd!", "plain_pass", "semi;colon&amp"])
def test_special_characters_in_password(password):
    raw = f"mysql+pymysql://root:{password}@127.0.0.1:3306/ERP_LOGISTICS?charset=utf8mb4"
    u = make_url(normalize_db_url(raw))
    assert (u.username, u.password, u.host, u.port, u.database) == ("root", password, "127.0.0.1", 3306, "ERP_LOGISTICS")


def test_already_encoded_url_unchanged_and_idempotent():
    enc = "mysql+pymysql://root:Pks%403115@127.0.0.1:3306/ERP_LOGISTICS?charset=utf8mb4"
    assert normalize_db_url(enc) == enc
    assert normalize_db_url(normalize_db_url(enc)) == enc


def test_settings_apply_normalisation(monkeypatch):
    monkeypatch.setenv("ERP_DATABASE_URL", '"mysql+pymysql://root:x@y@db.local:3307/ERP_LOGISTICS"')
    u = make_url(Settings().database_url)
    assert (u.password, u.host, u.port) == ("x@y", "db.local", 3307)


def test_timezone_falls_back_without_tz_database():
    """Windows without the tzdata package: IST must still work (fixed +05:30 offset)."""
    from datetime import timedelta
    from unittest import mock
    from zoneinfo import ZoneInfoNotFoundError

    from app.core import utils

    utils._zone.cache_clear()
    try:
        with mock.patch.object(utils, "ZoneInfo", side_effect=ZoneInfoNotFoundError("no tz data")):
            zone = utils._zone("Asia/Kolkata")
            assert zone.utcoffset(None) == timedelta(hours=5, minutes=30)
    finally:
        utils._zone.cache_clear()
