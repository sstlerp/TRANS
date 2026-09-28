"""Domain exceptions and user-friendly error handlers.

Business-rule violations raise `BusinessError` (HTTP 400/409/422) which is
rendered as `{"detail": "...", "code": "...", "errors": [...]}`.  Unexpected
exceptions are logged with a reference id; the client only sees the id, never
a stack trace.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("erp.errors")


class BusinessError(Exception):
    status_code = 400

    def __init__(self, message: str, code: str = "BUSINESS_RULE", errors: list | None = None,
                 status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.errors = errors or []
        if status_code:
            self.status_code = status_code


class NotFound(BusinessError):
    status_code = 404

    def __init__(self, what: str = "Record"):
        super().__init__(f"{what} not found", "NOT_FOUND")


class Conflict(BusinessError):
    status_code = 409


class PermissionDenied(BusinessError):
    status_code = 403

    def __init__(self, message: str = "You do not have permission to perform this action"):
        super().__init__(message, "FORBIDDEN")


class OverrideRequired(BusinessError):
    """Raised when a rule can be overridden by an authorised user with a reason."""
    status_code = 409

    def __init__(self, message: str, code: str, permission: str):
        super().__init__(message, code)
        self.permission = permission


def _wants_html(request: Request) -> bool:
    return not request.url.path.startswith("/api") and "text/html" in request.headers.get("accept", "")


def register_handlers(app) -> None:
    @app.exception_handler(BusinessError)
    async def _biz(request: Request, exc: BusinessError):
        body = {"detail": exc.message, "code": exc.code, "errors": exc.errors}
        if isinstance(exc, OverrideRequired):
            body["override_permission"] = exc.permission
        return JSONResponse(body, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _val(request: Request, exc: RequestValidationError):
        errs = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg")}
                for e in exc.errors()]
        return JSONResponse({"detail": "Validation failed", "code": "VALIDATION", "errors": errs}, 422)

    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError):
        msg = str(exc.orig) if exc.orig else str(exc)
        log.warning("Integrity error on %s: %s", request.url.path, msg)
        friendly = "Duplicate value: a record with the same unique key already exists." \
            if "Duplicate" in msg or "UNIQUE" in msg else \
            "The record is referenced by or references other data and cannot be saved in this state."
        return JSONResponse({"detail": friendly, "code": "INTEGRITY"}, 409)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 401 and _wants_html(request):
            return RedirectResponse(f"/login?next={request.url.path}", 303)
        return JSONResponse({"detail": exc.detail, "code": f"HTTP_{exc.status_code}"}, exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        ref = uuid.uuid4().hex[:10]
        log.exception("Unhandled error ref=%s path=%s", ref, request.url.path)
        return JSONResponse({"detail": f"An unexpected error occurred. Reference: {ref}", "code": "SERVER_ERROR"},
                            500)
