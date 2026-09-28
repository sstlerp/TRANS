"""Security (users/roles/permissions), audit log, documents, notifications,
business-rule configuration and background jobs."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BigId, MasterBase, PKMixin, TxnBase, fk

role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id", BigId, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", BigId, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)
user_roles = Table(
    "user_roles", Base.metadata,
    Column("user_id", BigId, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", BigId, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)
user_branches = Table(
    "user_branches", Base.metadata,
    Column("user_id", BigId, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("branch_id", BigId, ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base, PKMixin):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(80), unique=True)
    module: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(30))
    description: Mapped[str | None] = mapped_column(String(255))


class Role(Base, MasterBase):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(255))
    permissions: Mapped[list[Permission]] = relationship(secondary=role_permissions, lazy="selectin")


class User(Base, MasterBase):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(50), unique=True)
    full_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(150), unique=True)
    mobile: Mapped[str | None] = mapped_column(String(15))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    all_branches: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")


class AuditLog(Base, PKMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"), Index("ix_audit_at", "created_at"))
    user_id: Mapped[int | None] = mapped_column(BigId, index=True)
    username: Mapped[str | None] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(30), index=True)
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    old_values: Mapped[dict | None] = mapped_column(JSON)
    new_values: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BusinessRule(Base, MasterBase):
    """Key/value business configuration (tolerances, thresholds, reminder days, accounting options)."""
    __tablename__ = "business_rules"
    rule_key: Mapped[str] = mapped_column(String(80), unique=True)
    module: Mapped[str] = mapped_column(String(30), index=True)
    value: Mapped[str] = mapped_column(String(500))
    value_type: Mapped[str] = mapped_column(String(10), default="STRING")  # STRING/INT/DECIMAL/BOOL/LIST/CHOICE
    choices: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(500))


class Document(Base, MasterBase):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_doc_entity", "entity_type", "entity_id"),)
    document_type: Mapped[str] = mapped_column(String(40))  # DOCUMENT_TYPE lookup
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[int] = mapped_column(BigId)
    file_name: Mapped[str] = mapped_column(String(255))  # original, sanitised name shown to users
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)  # opaque; never a raw path
    content_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_document_id: Mapped[int | None] = fk("documents.id")
    uploaded_by: Mapped[int | None] = mapped_column(BigId)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime)
    remarks: Mapped[str | None] = mapped_column(String(500))


class DocumentLink(Base, PKMixin):
    """Link one stored document to additional entities (e.g. one invoice PDF for many tyres)."""
    __tablename__ = "document_links"
    __table_args__ = (Index("ix_doclink_entity", "entity_type", "entity_id"),)
    document_id: Mapped[int] = fk("documents.id", nullable=False, ondelete="CASCADE")
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[int] = mapped_column(BigId)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class NotificationRule(Base, MasterBase):
    __tablename__ = "notification_rules"
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    channels: Mapped[str] = mapped_column(String(100), default="IN_APP")  # IN_APP,EMAIL,SMS,WHATSAPP
    days_before: Mapped[str | None] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(10), default="WARNING")
    recipient_role_id: Mapped[int | None] = fk("roles.id")
    recipient_emails: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(String(255))


class Notification(Base, PKMixin):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notif_read", "is_read", "created_at"),)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(10), default="INFO")  # INFO / WARNING / CRITICAL
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[int | None] = mapped_column(BigId)
    link_url: Mapped[str | None] = mapped_column(String(255))
    user_id: Mapped[int | None] = mapped_column(BigId, index=True)
    role_id: Mapped[int | None] = mapped_column(BigId)
    dedupe_key: Mapped[str | None] = mapped_column(String(150), unique=True)
    channels_sent: Mapped[str | None] = mapped_column(String(100))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_by: Mapped[int | None] = mapped_column(BigId)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BackgroundJob(Base, TxnBase):
    __tablename__ = "background_jobs"
    job_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
