"""Authentication endpoints."""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.audit import audit
from app.core.errors import BusinessError
from app.core.security import (COOKIE_NAME, CSRF_COOKIE, CurrentUser, create_token, get_current_user, hash_password,
                               load_user, login_limiter, new_csrf_token, validate_password_strength, verify_password)
from app.core.utils import now
from app.database import get_db
from app.models.system import User

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("erp.auth")
MAX_FAILED = 5


class LoginIn(BaseModel):
    username: str
    password: str


def set_session_cookies(resp: Response, token: str) -> str:
    s = get_settings()
    csrf = new_csrf_token()
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                    max_age=s.access_token_minutes * 60, path="/")
    resp.set_cookie(CSRF_COOKIE, csrf, httponly=False, samesite="strict", secure=s.cookie_secure,
                    max_age=s.access_token_minutes * 60, path="/")
    return csrf


def authenticate(db: Session, request: Request, username: str, password: str) -> User:
    s = get_settings()
    ip = request.client.host if request.client else "?"
    if not login_limiter.hit(f"login:{ip}", s.login_rate_limit, s.login_rate_window_sec):
        log.warning("Login rate limit hit ip=%s", ip)
        raise BusinessError("Too many login attempts. Please wait a few minutes.", "RATE_LIMIT", status_code=429)
    u = db.execute(select(User).where(func.lower(User.username) == username.strip().lower())).scalar_one_or_none()
    if u and u.locked_until and u.locked_until > now():
        raise BusinessError("Account temporarily locked after repeated failures. Try later or contact an admin.",
                            "LOCKED", status_code=423)
    if not u or not u.is_active or not verify_password(password, u.password_hash):
        if u:
            u.failed_attempts = (u.failed_attempts or 0) + 1
            if u.failed_attempts >= MAX_FAILED:
                u.locked_until = now() + timedelta(minutes=15)
            db.commit()
        log.info("Login failed user=%s ip=%s", username, ip)
        raise BusinessError("Invalid username or password", "AUTH_FAILED", status_code=401)
    u.failed_attempts, u.locked_until, u.last_login_at = 0, None, now()
    audit(db, load_user(db, u.id), "LOGIN", "users", u.id)
    db.commit()
    log.info("Login ok user=%s ip=%s", u.username, ip)
    return u


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    u = authenticate(db, request, body.username, body.password)
    token = create_token(u.id, u.token_version)
    csrf = set_session_cookies(response, token)
    return {"access_token": token, "token_type": "bearer", "csrf_token": csrf,
            "must_change_password": u.must_change_password}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "full_name": user.full_name, "is_superuser": user.is_superuser,
            "permissions": sorted(user.permissions), "branch_ids": sorted(user.branch_ids) if user.branch_ids else None}


class PwIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(body: PwIn, response: Response, user: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    u = db.get(User, user.id)
    if not verify_password(body.current_password, u.password_hash):
        raise BusinessError("Current password is incorrect")
    validate_password_strength(body.new_password)
    u.password_hash = hash_password(body.new_password)
    u.token_version += 1
    u.must_change_password = False
    audit(db, user, "PASSWORD_CHANGE", "users", u.id)
    db.commit()
    set_session_cookies(response, create_token(u.id, u.token_version))
    return {"ok": True}
