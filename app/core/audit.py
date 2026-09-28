"""Audit trail helper. Every important change calls `audit(...)` inside the same
DB transaction as the change, so audit and data commit or roll back together."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.utils import jsonable, now

log = logging.getLogger("erp.audit")
_SENSITIVE = {"password_hash", "password", "secret", "token", "credential"}


def snapshot(obj: Any) -> dict | None:
    if obj is None:
        return None
    data = {}
    for attr in sa_inspect(obj).mapper.column_attrs:
        k = attr.key
        if any(s in k for s in _SENSITIVE):
            continue
        data[k] = jsonable(getattr(obj, k))
    return data


def diff(old: dict | None, new: dict | None) -> tuple[dict | None, dict | None]:
    if not old or not new:
        return old, new
    changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k) and k not in ("updated_at",)}
    return {k: old.get(k) for k in changed}, {k: new.get(k) for k in changed}


def audit(db: Session, user, action: str, entity_type: str, entity_id: Any = None,
          old: dict | None = None, new: dict | None = None, reason: str | None = None,
          only_changes: bool = True) -> None:
    from app.models.system import AuditLog
    if only_changes and action == "UPDATE":
        old, new = diff(old, new)
        if old == {} and new == {}:
            return
    db.add(AuditLog(
        user_id=getattr(user, "id", None), username=getattr(user, "username", None) or "system",
        action=action, entity_type=entity_type, entity_id=None if entity_id is None else str(entity_id),
        old_values=jsonable(old), new_values=jsonable(new), reason=reason,
        ip_address=getattr(user, "ip", None), user_agent=getattr(user, "user_agent", None), created_at=now(),
    ))
    db.flush()
    if action in {"ALLOCATE", "MATCH", "UNMATCH", "APPROVE", "REVERSE", "OVERRIDE", "IMPORT"}:
        log.info("financial-op action=%s entity=%s id=%s user=%s", action, entity_type, entity_id,
                 getattr(user, "username", "system"))
