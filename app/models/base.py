"""Declarative base, portable column types and audit mixins."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, MetaData, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.utils import now

# BIGINT on MySQL; INTEGER on SQLite so AUTOINCREMENT works in the test fallback.
BigId = BigInteger().with_variant(Integer, "sqlite")

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {int: BigId}


def Money():  # noqa: N802 - column type factory
    return Numeric(18, 2)


def Qty():  # noqa: N802
    return Numeric(18, 3)


def Rate():  # noqa: N802
    return Numeric(18, 4)


def fk(target: str, nullable: bool = True, ondelete: str | None = None, index: bool = True, **kw):
    return mapped_column(BigId, ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index, **kw)


class PKMixin:
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)


class AuditMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigId, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigId, nullable=True)


class ActiveMixin:
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SourceMixin:
    """Provenance of normalised operational/financial rows (spec §39)."""
    source_type: Mapped[str] = mapped_column(String(10), default="MANUAL", nullable=False)  # EXCEL/API/MANUAL/SYSTEM
    source_reference: Mapped[str | None] = mapped_column(String(255))
    source_file: Mapped[str | None] = mapped_column(String(255))
    source_sheet: Mapped[str | None] = mapped_column(String(100))
    source_row: Mapped[int | None] = mapped_column(Integer)
    import_batch_id: Mapped[int | None] = fk("statement_import_batches.id")
    txn_hash: Mapped[str | None] = mapped_column(String(64), index=True)


class MasterBase(PKMixin, AuditMixin, ActiveMixin):
    pass


class TxnBase(PKMixin, AuditMixin):
    pass
