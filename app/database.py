"""Database engine / session management (MySQL via PyMySQL)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def make_engine(url: str) -> Engine:
    kwargs: dict = {"echo": get_settings().db_echo, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_pre_ping=True, pool_recycle=1800, pool_size=get_settings().db_pool_size)
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):  # pragma: no cover - development/test fallback only
        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.isolation_level = None  # let SQLAlchemy manage BEGIN/SAVEPOINT correctly
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(eng, "begin")
        def _begin(conn):
            conn.exec_driver_sql("BEGIN")
    return eng


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
        SessionLocal.configure(bind=_engine)
    return _engine


def set_engine(engine: Engine) -> None:
    """Used by tests to point the app at a different database."""
    global _engine
    _engine = engine
    SessionLocal.configure(bind=engine)


def get_db() -> Iterator[Session]:
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts/background jobs."""
    get_engine()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
