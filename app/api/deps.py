"""Shared API dependencies."""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.security import CurrentUser, get_current_user
from app.database import get_db
from app.services.masters import Ctx


def ctx_dep(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)) -> Ctx:
    return Ctx(db, user)


def commit(ctx: Ctx) -> None:
    """Commit the unit of work; any exception before this point rolls everything back."""
    try:
        ctx.db.commit()
    except Exception:
        ctx.db.rollback()
        raise
