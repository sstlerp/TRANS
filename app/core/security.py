"""Authentication, RBAC, CSRF and login rate limiting.

* Passwords: bcrypt.
* Sessions: signed JWT in an HttpOnly, SameSite=Lax cookie (browser) or an
  `Authorization: Bearer` header (API clients).  Tokens carry the user's
  `token_version`, so changing a password / deactivating a user revokes them.
* CSRF: double-submit token.  Browser requests authenticated by cookie must
  send the `erp_csrf` cookie value back in the `X-CSRF-Token` header for any
  state-changing method.  Bearer-token clients are not subject to CSRF.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import PermissionDenied
from app.database import get_db

COOKIE_NAME = "erp_session"
CSRF_COOKIE = "erp_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode())
    except ValueError:
        return False


def validate_password_strength(pw: str) -> None:
    from app.core.errors import BusinessError
    if len(pw) < 8 or pw.isalpha() or pw.isdigit():
        raise BusinessError("Password must be at least 8 characters and contain letters and digits")


def create_token(user_id: int, token_version: int) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id), "tv": token_version,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.access_token_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    s = get_settings()
    try:
        return jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError:
        return None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class CurrentUser:
    id: int
    username: str
    full_name: str
    is_superuser: bool
    permissions: set[str] = field(default_factory=set)
    branch_ids: set[int] | None = None  # None = all branches
    ip: str | None = None
    user_agent: str | None = None
    via_cookie: bool = False

    def has(self, perm: str) -> bool:
        if self.is_superuser:
            return True
        if perm in self.permissions:
            return True
        module = perm.split(".")[0]
        return f"{module}.*" in self.permissions

    def require(self, perm: str) -> None:
        if not self.has(perm):
            raise PermissionDenied(f"Missing permission: {perm}")

    def can_access_branch(self, branch_id: int | None) -> bool:
        return self.branch_ids is None or branch_id is None or branch_id in self.branch_ids


def load_user(db: Session, user_id: int, token_version: int | None = None) -> CurrentUser | None:
    from app.models.system import User
    u = db.get(User, user_id)
    if not u or not u.is_active:
        return None
    if token_version is not None and u.token_version != token_version:
        return None
    perms = {p.code for r in u.roles if r.is_active for p in r.permissions}
    branches = None if (u.is_superuser or u.all_branches) else {b for b in _user_branch_ids(db, u.id)}
    return CurrentUser(u.id, u.username, u.full_name, u.is_superuser, perms, branches)


def _user_branch_ids(db: Session, user_id: int) -> list[int]:
    from sqlalchemy import select
    from app.models.system import user_branches
    return list(db.execute(select(user_branches.c.branch_id).where(user_branches.c.user_id == user_id)).scalars())


def _extract_token(request: Request) -> tuple[str | None, bool]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), False
    return request.cookies.get(COOKIE_NAME), True


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> CurrentUser | None:
    token, via_cookie = _extract_token(request)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user = load_user(db, int(payload["sub"]), payload.get("tv"))
    if user:
        user.ip = request.client.host if request.client else None
        user.user_agent = (request.headers.get("user-agent") or "")[:255]
        user.via_cookie = via_cookie
        request.state.user = user
    return user


def get_current_user(request: Request, user: CurrentUser | None = Depends(get_current_user_optional)) -> CurrentUser:
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.via_cookie and request.method not in SAFE_METHODS:
        sent = request.headers.get("x-csrf-token")
        expected = request.cookies.get(CSRF_COOKIE)
        if not sent or not expected or not secrets.compare_digest(sent, expected):
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    return user


def require(perm: str):
    """FastAPI dependency factory: `user = Depends(require("fleet.edit"))`."""
    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        user.require(perm)
        return user
    return _dep


class RateLimiter:
    """Simple in-process sliding-window limiter (use a shared store behind a load balancer)."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


login_limiter = RateLimiter()
