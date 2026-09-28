"""FastAPI application: REST API + server-rendered HTML pages (Jinja2)."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.core.errors import BusinessError, register_handlers
from app.core.logging_setup import setup_logging
from app.core.security import CurrentUser, create_token, get_current_user_optional
from app.core.utils import fmt_date, today
from app.database import get_db

import app.services.registry  # noqa: F401  (registers all screens)
from app.api import auth as auth_api
from app.api import domain as domain_api
from app.api import masters as masters_api
from app.services import masters
from app.services.registry import menu

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.filters["ddmmyyyy"] = fmt_date


class SecurityHeaders(BaseHTTPMiddleware):
    """Security headers + last-resort error handler (no stack traces to users)."""

    async def dispatch(self, request, call_next):
        try:
            resp = await call_next(request)
        except Exception:  # noqa: BLE001
            ref = uuid.uuid4().hex[:10]
            logging.getLogger("erp.errors").exception("Unhandled error ref=%s path=%s", ref, request.url.path)
            resp = JSONResponse({"detail": f"An unexpected error occurred. Reference: {ref}", "code": "SERVER_ERROR"}, 500)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:; img-src 'self' data: blob:; "
            "connect-src 'self'")
        return resp


def create_app() -> FastAPI:
    s = get_settings()
    setup_logging()
    app = FastAPI(title=f"{s.app_name} API", version="1.0.0",
                  description="Transport & Logistics ERP — REST API. Authenticate via POST /api/auth/login and send "
                              "`Authorization: Bearer <token>`.")
    app.add_middleware(SecurityHeaders)
    register_handlers(app)
    app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
    app.include_router(auth_api.router)
    app.include_router(masters_api.router)
    app.include_router(masters_api.docs_router)
    app.include_router(domain_api.router)
    _pages(app)
    return app


def _ctx(request: Request, user: CurrentUser | None, **extra) -> dict:
    s = get_settings()
    nav = []
    if user:
        for group, items in menu():
            allowed = [i for i in items if user.has(i[3])]
            if allowed:
                nav.append((group, allowed))
    return {"request": request, "user": user, "nav": nav, "app_name": s.app_name, "brand_company_name": s.company_name,
            "today": fmt_date(today()), "csrf": request.cookies.get("erp_csrf", ""), **extra}


def _page(template: str, perm: str | None = None, **extra):
    def handler(request: Request, user: CurrentUser | None = Depends(get_current_user_optional)):
        if not user:
            return RedirectResponse(f"/login?next={request.url.path}", 303)
        if perm and not user.has(perm):
            return templates.TemplateResponse(request, "pages/forbidden.html", _ctx(request, user, perm=perm), 403)
        return templates.TemplateResponse(request, template, _ctx(request, user, **extra))
    return handler


def _pages(app: FastAPI) -> None:
    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    def login_page(request: Request, next: str = "/"):
        return templates.TemplateResponse(request, "pages/login.html", _ctx(request, None, next=next, error=None))

    @app.post("/login", response_class=HTMLResponse, include_in_schema=False)
    def login_post(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/"),
                   db: Session = Depends(get_db)):
        try:
            u = auth_api.authenticate(db, request, username, password)
        except BusinessError as exc:
            return templates.TemplateResponse(request, "pages/login.html",
                                              _ctx(request, None, next=next, error=exc.message), 401)
        target = next if next.startswith("/") and not next.startswith("//") else "/"
        if u.must_change_password:
            target = "/account/password"
        resp = RedirectResponse(target, 303)
        auth_api.set_session_cookies(resp, create_token(u.id, u.token_version))
        return resp

    @app.get("/logout", include_in_schema=False)
    def logout():
        resp = RedirectResponse("/login", 303)
        resp.delete_cookie("erp_session", path="/")
        resp.delete_cookie("erp_csrf", path="/")
        return resp

    app.get("/", response_class=HTMLResponse, include_in_schema=False)(_page("pages/dashboard.html", "dashboard.view"))
    app.get("/account/password", response_class=HTMLResponse, include_in_schema=False)(_page("pages/password.html"))
    app.get("/imports", response_class=HTMLResponse, include_in_schema=False)(_page("pages/import.html", "import.view"))
    app.get("/finance/reconciliation", response_class=HTMLResponse, include_in_schema=False)(
        _page("pages/reconciliation.html", "finance.view"))
    app.get("/tyres/dashboard", response_class=HTMLResponse, include_in_schema=False)(
        _page("pages/tyre_dashboard.html", "tyre.view"))
    app.get("/compliance", response_class=HTMLResponse, include_in_schema=False)(
        _page("pages/compliance.html", "compliance.view"))
    app.get("/reports", response_class=HTMLResponse, include_in_schema=False)(_page("pages/reports.html", "report.view"))

    @app.get("/imports/batches/{bid}", response_class=HTMLResponse, include_in_schema=False)
    def batch_page(bid: int, request: Request, user: CurrentUser | None = Depends(get_current_user_optional)):
        return _page("pages/import.html", "import.view", batch_id=bid)(request, user)

    @app.get("/masters/{key}", response_class=HTMLResponse, include_in_schema=False)
    def master_page(key: str, request: Request, user: CurrentUser | None = Depends(get_current_user_optional)):
        spec = masters.REGISTRY.get(key)
        if not spec:
            return templates.TemplateResponse(request, "pages/forbidden.html",
                                              _ctx(request, user, perm="(unknown screen)"), 404)
        return _page("pages/master.html", spec.perm("view"), spec=spec)(request, user)


app = create_app()
