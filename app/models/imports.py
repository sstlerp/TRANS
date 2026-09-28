"""Generic statement import engine tables (spec §12)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigId, MasterBase, PKMixin, TxnBase, fk


class StatementImportTemplate(Base, MasterBase):
    __tablename__ = "statement_import_templates"
    __table_args__ = (UniqueConstraint("provider_id", "template_name", "version"),)
    provider_id: Mapped[int] = fk("providers.id", nullable=False)
    template_name: Mapped[str] = mapped_column(String(100))
    statement_type: Mapped[str] = mapped_column(String(30), index=True)  # BANK/TOLL/FUEL/FASTAG/FUEL_CARD/GPS/MAINTENANCE/INSURANCE
    file_format: Mapped[str] = mapped_column(String(10), default="XLSX")  # XLSX / CSV
    sheet_name: Mapped[str | None] = mapped_column(String(100))
    header_row: Mapped[int] = mapped_column(Integer, default=1)
    data_start_row: Mapped[int] = mapped_column(Integer, default=2)
    stop_at_blank_rows: Mapped[int] = mapped_column(Integer, default=3)
    skip_footer_keywords: Mapped[str | None] = mapped_column(String(255))  # e.g. "Closing Balance,Total"
    date_format: Mapped[str | None] = mapped_column(String(30))  # strftime, e.g. %d/%m/%Y
    datetime_format: Mapped[str | None] = mapped_column(String(40))
    amount_mode: Mapped[str] = mapped_column(String(20), default="SEPARATE")  # SEPARATE / SIGNED / WITH_TYPE
    duplicate_key_fields: Mapped[str | None] = mapped_column(String(255))  # overrides default key
    version: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)


class StatementTemplateColumn(Base, PKMixin):
    __tablename__ = "statement_template_columns"
    template_id: Mapped[int] = fk("statement_import_templates.id", nullable=False, ondelete="CASCADE")
    source_column: Mapped[str | None] = mapped_column(String(10))  # letter (A) or 1-based index
    source_header: Mapped[str | None] = mapped_column(String(150))
    target_field: Mapped[str] = mapped_column(String(60))
    data_type: Mapped[str] = mapped_column(String(20), default="TEXT")
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    transformation: Mapped[str | None] = mapped_column(String(500))  # pipeline DSL, see services/transforms.py
    default_value: Mapped[str | None] = mapped_column(String(150))
    lookup_rule: Mapped[str | None] = mapped_column(String(60))
    validation_rule: Mapped[str | None] = mapped_column(String(255))
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class ValueMapping(Base, MasterBase):
    """Provider-specific value translation (fuel names, provider names, vehicle aliases, plazas ...)."""
    __tablename__ = "value_mappings"
    __table_args__ = (UniqueConstraint("mapping_type", "provider_id", "source_value"),)
    mapping_type: Mapped[str] = mapped_column(String(30), index=True)  # FUEL_TYPE/PROVIDER/VEHICLE/TOLL_PLAZA/FUEL_STATION/GENERIC
    provider_id: Mapped[int | None] = fk("providers.id")
    source_value: Mapped[str] = mapped_column(String(150))
    target_value: Mapped[str | None] = mapped_column(String(150))
    target_id: Mapped[int | None] = mapped_column(BigId)
    remarks: Mapped[str | None] = mapped_column(String(255))


class StatementImportBatch(Base, TxnBase):
    __tablename__ = "statement_import_batches"
    __table_args__ = (Index("ix_sib_hash", "file_hash"),)
    provider_id: Mapped[int] = fk("providers.id", nullable=False)
    template_id: Mapped[int] = fk("statement_import_templates.id", nullable=False)
    statement_type: Mapped[str] = mapped_column(String(30), index=True)
    bank_account_id: Mapped[int | None] = fk("bank_accounts.id")
    file_name: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(255))
    sheet_name: Mapped[str | None] = mapped_column(String(100))
    imported_at: Mapped[datetime | None] = mapped_column(DateTime)
    imported_by: Mapped[int | None] = mapped_column(BigId)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    successful_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    warning_rows: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_rows: Mapped[int] = mapped_column(Integer, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0)
    # UPLOADED → PREVIEWED → QUEUED → PROCESSING → COMPLETED / COMPLETED_WITH_ERRORS / FAILED / CANCELLED
    status: Mapped[str] = mapped_column(String(30), default="UPLOADED", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict | None] = mapped_column(JSON)


class StatementImportRow(Base, PKMixin):
    """Staging row: original values + normalised values + outcome. Preserves the source."""
    __tablename__ = "statement_import_rows"
    __table_args__ = (Index("ix_sir_batch_row", "batch_id", "source_row"),)
    batch_id: Mapped[int] = fk("statement_import_batches.id", nullable=False, index=False, ondelete="CASCADE")
    source_row: Mapped[int] = mapped_column(Integer)
    raw_values: Mapped[dict | None] = mapped_column(JSON)
    normalized_values: Mapped[dict | None] = mapped_column(JSON)
    row_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # VALID/WARNING/ERROR/DUPLICATE/IMPORTED/SKIPPED
    target_table: Mapped[str | None] = mapped_column(String(60))
    target_id: Mapped[int | None] = mapped_column(BigId)
    messages: Mapped[str | None] = mapped_column(Text)


class StatementImportError(Base, PKMixin):
    __tablename__ = "statement_import_errors"
    batch_id: Mapped[int] = fk("statement_import_batches.id", nullable=False, ondelete="CASCADE")
    source_row: Mapped[int | None] = mapped_column(Integer)
    source_column: Mapped[str | None] = mapped_column(String(20))
    target_field: Mapped[str | None] = mapped_column(String(60))
    original_value: Mapped[str | None] = mapped_column(String(500))
    error_type: Mapped[str] = mapped_column(String(30))  # REQUIRED/FORMAT/LOOKUP/VALIDATION/DUPLICATE/HEADER/UNMATCHED
    error_message: Mapped[str] = mapped_column(String(500))
    suggested_correction: Mapped[str | None] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(10), default="ERROR")  # ERROR / WARNING / INFO
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolved_by: Mapped[int | None] = mapped_column(BigId)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolution_notes: Mapped[str | None] = mapped_column(String(500))
