"""Generic metadata-driven CRUD API + document and audit-history endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import or_, select

from app.api.deps import commit, ctx_dep
from app.core.errors import NotFound, PermissionDenied
from app.core.utils import jsonable, today
from app.models.system import AuditLog, Document
from app.services import documents, masters
from app.services.masters import Ctx, get_spec

router = APIRouter(prefix="/api/masters", tags=["masters"])
docs_router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("/{key}/meta")
def meta(key: str, ctx: Ctx = Depends(ctx_dep)):
    spec = get_spec(key)
    ctx.user.require(spec.perm("view"))
    return masters.spec_meta(spec, ctx.user)


@router.get("/{key}")
def list_(key: str, request: Request, ctx: Ctx = Depends(ctx_dep)):
    return masters.list_records(ctx, get_spec(key), dict(request.query_params))


@router.get("/{key}/options")
def options(key: str, request: Request, ctx: Ctx = Depends(ctx_dep)):
    spec = get_spec(key)
    p = dict(request.query_params)
    q, limit, inc = p.pop("q", ""), int(p.pop("limit", 50)), p.pop("include_id", None)
    return masters.options(ctx, spec, q, min(limit, 500), p, int(inc) if inc else None)


@router.get("/{key}/export")
def export(key: str, request: Request, fmt: str = "xlsx", ctx: Ctx = Depends(ctx_dep)):
    spec = get_spec(key)
    ctx.user.require("report.export") if not ctx.user.has(spec.perm("view")) else None
    headers, rows = masters.export_rows(ctx, spec, dict(request.query_params))
    fname = f"{spec.key}_{today():%d-%m-%Y}"
    if fmt == "csv":
        return Response(masters.to_csv(headers, rows), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})
    if fmt == "pdf":
        return Response(masters.to_pdf(spec.title, headers, rows), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.pdf"'})
    return Response(masters.to_xlsx(spec.title, headers, rows),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'})


@router.get("/{key}/{rid}")
def get(key: str, rid: int, ctx: Ctx = Depends(ctx_dep)):
    return masters.get_record(ctx, get_spec(key), rid)


@router.post("/{key}")
def create(key: str, data: dict[str, Any] = Body(...), ctx: Ctx = Depends(ctx_dep)):
    rec = masters.save_record(ctx, get_spec(key), data)
    commit(ctx)
    return rec


@router.put("/{key}/{rid}")
def update(key: str, rid: int, data: dict[str, Any] = Body(...), ctx: Ctx = Depends(ctx_dep)):
    ctx.reason = data.pop("_reason", None)
    rec = masters.save_record(ctx, get_spec(key), data, rid)
    commit(ctx)
    return rec


@router.post("/{key}/{rid}/active")
def set_active(key: str, rid: int, data: dict[str, Any] = Body(...), ctx: Ctx = Depends(ctx_dep)):
    rec = masters.set_active(ctx, get_spec(key), rid, bool(data.get("active")), data.get("reason"))
    commit(ctx)
    return rec


@router.delete("/{key}/{rid}")
def delete(key: str, rid: int, reason: str | None = None, ctx: Ctx = Depends(ctx_dep)):
    masters.delete_record(ctx, get_spec(key), rid, reason)
    commit(ctx)
    return {"ok": True}


@router.post("/{key}/{rid}/actions/{action}")
def action(key: str, rid: int, action: str, data: dict[str, Any] = Body(default={}), ctx: Ctx = Depends(ctx_dep)):
    res = masters.run_action(ctx, get_spec(key), rid, action, data)
    commit(ctx)
    return res


@router.get("/{key}/{rid}/audit")
def history(key: str, rid: int, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("audit.view")
    spec = get_spec(key)
    rows = ctx.db.execute(select(AuditLog).where(AuditLog.entity_type == spec.etype, AuditLog.entity_id == str(rid))
                          .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(300)).scalars()
    return [{c.key: jsonable(getattr(a, c.key)) for c in AuditLog.__table__.columns} for a in rows]


# ───────────────────────── documents ─────────────────────────
def _entity_perm(ctx: Ctx, entity_type: str, action: str) -> None:
    spec = next((s for s in masters.REGISTRY.values() if s.etype == entity_type), None)
    ctx.user.require(spec.perm(action) if spec else f"document.{action}")


@docs_router.get("")
def list_docs(entity_type: str, entity_id: int, ctx: Ctx = Depends(ctx_dep)):
    _entity_perm(ctx, entity_type, "view")
    return [{"id": d.id, "file_name": d.file_name, "document_type": d.document_type, "version": d.version,
             "size_bytes": d.size_bytes, "uploaded_at": jsonable(d.uploaded_at), "remarks": d.remarks,
             "content_type": d.content_type} for d in documents.list_for(ctx.db, entity_type, entity_id)]


@docs_router.post("")
async def upload(entity_type: str = Form(...), entity_id: int = Form(...), document_type: str = Form(...),
                 remarks: str | None = Form(None), replaces_id: int | None = Form(None),
                 file: UploadFile = File(...), ctx: Ctx = Depends(ctx_dep)):
    _entity_perm(ctx, entity_type, "edit")
    data = await file.read()
    d = documents.upload(ctx.db, ctx.user, entity_type, entity_id, document_type, file.filename or "file", data,
                         remarks, replaces_id)
    commit(ctx)
    return {"id": d.id, "file_name": d.file_name, "version": d.version}


@docs_router.get("/{doc_id}/download")
def download(doc_id: int, inline: bool = False, ctx: Ctx = Depends(ctx_dep)):
    d = ctx.db.get(Document, doc_id)
    if not d:
        raise NotFound("Document")
    _entity_perm(ctx, d.entity_type, "view")
    data = documents.read_bytes(d.storage_key)
    disp = "inline" if inline and (d.content_type or "").startswith(("image/", "application/pdf")) else "attachment"
    return Response(data, media_type=d.content_type or "application/octet-stream",
                    headers={"Content-Disposition": f'{disp}; filename="{d.file_name}"',
                             "X-Content-Type-Options": "nosniff"})


@docs_router.delete("/{doc_id}")
def remove(doc_id: int, reason: str | None = None, ctx: Ctx = Depends(ctx_dep)):
    d = ctx.db.get(Document, doc_id)
    if not d:
        raise NotFound("Document")
    _entity_perm(ctx, d.entity_type, "edit")
    d.is_active = False
    from app.core.audit import audit
    audit(ctx.db, ctx.user, "SOFT_DELETE", "document", d.id, reason=reason)
    commit(ctx)
    return {"ok": True}
