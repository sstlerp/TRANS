"""Domain endpoints: vehicles, compliance, reconciliation, imports, tyres, reports, dashboard, jobs, integrations."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import commit, ctx_dep
from app.config import get_settings
from app.core.errors import BusinessError, NotFound
from app.core.utils import jsonable, parse_date, today
from app.models.finance import BankTransaction, BankTransactionAllocation, ReconciliationHistory
from app.models.fleet import SubCategoryAttribute, Vehicle
from app.models.imports import (StatementImportBatch, StatementImportError, StatementImportRow,
                                StatementImportTemplate, StatementTemplateColumn)
from app.models.system import Notification
from app.models.tyres import Tyre
from app.services import (bank, dashboard, import_engine, maintenance, masters, operations, renewals, reports, tyres,
                          vehicles)
from app.services.masters import Ctx, get_spec
from app.services.rules import rule

router = APIRouter(prefix="/api", tags=["domain"])


# ───────────────────────── vehicles ─────────────────────────
@router.get("/vehicles/attribute-definitions/{sub_category_id}")
def attr_defs(sub_category_id: int, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("fleet.view")
    return [{"id": d.id, "code": d.code, "name": d.name, "data_type": d.data_type, "is_mandatory": d.is_mandatory,
             "options": [o.strip() for o in (d.dropdown_options or "").replace("\n", ",").split(",") if o.strip()],
             "unit": d.unit_id and _unit(ctx, d.unit_id), "min": jsonable(d.min_value), "max": jsonable(d.max_value)}
            for d in vehicles.attribute_definitions(ctx.db, sub_category_id)]


def _unit(ctx, uid):
    from app.models.org import Unit
    u = ctx.db.get(Unit, uid)
    return u.code if u else None


@router.get("/vehicles/{vid}/classification")
def classification(vid: int, on: str | None = None, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("fleet.view")
    h = vehicles.classification_at(ctx.db, vid, parse_date(on) or today())
    return jsonable({c.key: getattr(h, c.key) for c in h.__table__.columns}) if h else None


# ───────────────────────── compliance ─────────────────────────
@router.get("/compliance/dashboard")
def compliance_dash(category: str | None = None, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("compliance.view")
    return jsonable(renewals.dashboard(ctx.db, category))


@router.get("/compliance/calendar")
def compliance_cal(date_from: str | None = None, date_to: str | None = None, category: str | None = None,
                   ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("compliance.view")
    s = parse_date(date_from) or today() - timedelta(days=30)
    e = parse_date(date_to) or today() + timedelta(days=90)
    return renewals.calendar(ctx.db, s, e, category or None)


# ───────────────────────── reconciliation ─────────────────────────
def _txn(ctx: Ctx, tid: int, lock: bool = False) -> BankTransaction:
    t = ctx.db.get(BankTransaction, tid, with_for_update=lock)
    if not t:
        raise NotFound("Bank transaction")
    return t


class TargetIn(BaseModel):
    type: str
    id: int
    amount: Decimal = Field(gt=0)


class LinkIn(BaseModel):
    link_type: str
    targets: list[TargetIn]
    remarks: str | None = None
    allow_overpayment: bool = False


class AllocLine(BaseModel):
    cost_center_id: int
    amount: Decimal = Field(gt=0)
    expense_type_id: int | None = None
    credit_type_id: int | None = None
    vendor_id: int | None = None
    vehicle_id: int | None = None
    remarks: str | None = None


class AllocIn(BaseModel):
    lines: list[AllocLine]
    allow_partial: bool = False
    remarks: str | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


@router.get("/recon/{tid}")
def recon_detail(tid: int, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.view")
    t = _txn(ctx, tid)
    spec = get_spec("bank_transactions")
    allocs = ctx.db.execute(select(BankTransactionAllocation).where(
        BankTransactionAllocation.bank_transaction_id == t.id).order_by(BankTransactionAllocation.id)).scalars().all()
    arow = masters.serialize_many(ctx, get_spec("bank_allocations"), allocs)
    hist = ctx.db.execute(select(ReconciliationHistory).where(ReconciliationHistory.bank_transaction_id == t.id)
                          .order_by(ReconciliationHistory.id.desc())).scalars().all()
    return {"txn": masters.serialize_many(ctx, spec, [t])[0], "links": bank.links_of(ctx.db, t), "allocations": arow,
            "history": [{c.key: jsonable(getattr(h, c.key)) for c in ReconciliationHistory.__table__.columns
                         if c.key != "snapshot"} for h in hist]}


@router.get("/recon/{tid}/suggestions")
def recon_suggest(tid: int, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.view")
    return jsonable(bank.suggest(ctx.db, _txn(ctx, tid)))


@router.get("/recon/targets/{ttype}")
def recon_targets(ttype: str, request: Request, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.view")
    if ttype == "BANK":
        p = dict(request.query_params)
        q = select(BankTransaction).where(BankTransaction.status == "ACTIVE",
                                          BankTransaction.recon_status.in_(["UNMATCHED", "PARTIALLY_MATCHED",
                                                                            "AUTO_SUGGESTED"]))
        if p.get("direction"):
            q = q.where(BankTransaction.direction == p["direction"])
        if p.get("exclude_account"):
            q = q.where(BankTransaction.bank_account_id != int(p["exclude_account"]))
        if p.get("amount"):
            q = q.where(BankTransaction.amount == Decimal(p["amount"]))
        if p.get("date_from"):
            q = q.where(BankTransaction.txn_date >= parse_date(p["date_from"]))
        if p.get("date_to"):
            q = q.where(BankTransaction.txn_date <= parse_date(p["date_to"]))
        return [{"type": "BANK", "id": t.id, "date": jsonable(t.txn_date), "total": str(t.amount),
                 "remaining": str(t.unmatched_amount), "reference": f"{t.direction} {t.utr or ''} {t.narration or ''}"[:120]}
                for t in ctx.db.execute(q.order_by(BankTransaction.txn_date.desc()).limit(200)).scalars()]
    return bank.unsettled_targets(ctx.db, ttype.upper(), dict(request.query_params))


@router.post("/recon/{tid}/link")
def recon_link(tid: int, body: LinkIn, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.match")
    t = _txn(ctx, tid, lock=True)
    if body.link_type == "INTERNAL_TRANSFER" and t.direction == "CR":
        # the link is always stored debit → credit; flip when started from the credit side
        if len(body.targets) != 1 or body.targets[0].type != "BANK":
            raise BusinessError("Select the matching debit in the other account")
        debit = _txn(ctx, body.targets[0].id, lock=True)
        links = bank.link(ctx, debit, "INTERNAL_TRANSFER", [{"type": "BANK", "id": t.id, "amount": body.targets[0].amount}],
                          body.remarks)
    else:
        links = bank.link(ctx, t, body.link_type, [x.model_dump() for x in body.targets], body.remarks,
                          allow_overpayment=body.allow_overpayment)
    commit(ctx)
    return {"links": [l.id for l in links], "status": [l.match_status for l in links]}


@router.post("/recon/links/{link_id}/unlink")
def recon_unlink(link_id: int, body: ReasonIn, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.match")
    res = bank.unlink(ctx, link_id, body.reason or "")
    commit(ctx)
    return res


@router.post("/recon/links/{link_id}/accept")
def recon_accept(link_id: int, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.match")
    res = bank.accept_suggestion(ctx, link_id)
    commit(ctx)
    return res


@router.post("/recon/links/{link_id}/reject")
def recon_reject(link_id: int, body: ReasonIn, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.match")
    res = bank.reject_suggestion(ctx, link_id, body.reason)
    commit(ctx)
    return res


@router.post("/recon/{tid}/allocate")
def recon_allocate(tid: int, body: AllocIn, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.allocate")
    t = _txn(ctx, tid, lock=True)
    out = bank.allocate(ctx, t, [l.model_dump() for l in body.lines], body.allow_partial, body.remarks)
    commit(ctx)
    return {"allocations": [a.id for a in out], "status": t.recon_status}


@router.post("/recon/allocations/{aid}/reverse")
def recon_reverse(aid: int, body: ReasonIn, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.allocate")
    res = bank.reverse_allocation(ctx, aid, body.reason or "")
    commit(ctx)
    return res


@router.post("/recon/{tid}/classify")
def recon_classify(tid: int, data: dict[str, Any] = Body(...), ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.match")
    res = bank.classify(ctx, _txn(ctx, tid, lock=True), data)
    commit(ctx)
    return res


@router.post("/recon/{tid}/ignore")
def recon_ignore(tid: int, data: dict[str, Any] = Body(...), ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.match")
    res = bank.set_ignored(ctx, _txn(ctx, tid, lock=True), bool(data.get("ignored", True)), data.get("reason") or "")
    commit(ctx)
    return res


@router.post("/recon/{tid}/keep-unmatched")
def recon_keep(tid: int, body: ReasonIn, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.match")
    res = bank.keep_unmatched(ctx, _txn(ctx, tid), body.reason)
    commit(ctx)
    return res


@router.post("/recon/auto-suggest")
def recon_auto(data: dict[str, Any] = Body(default={}), ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("finance.match")
    q = select(BankTransaction.id).where(BankTransaction.recon_status == "UNMATCHED", BankTransaction.status == "ACTIVE")
    if data.get("bank_account_id"):
        q = q.where(BankTransaction.bank_account_id == int(data["bank_account_id"]))
    res = bank.auto_suggest(ctx, list(ctx.db.execute(q.limit(5000)).scalars()))
    commit(ctx)
    return res


# ───────────────────────── imports ─────────────────────────
@router.get("/imports/target-fields/{statement_type}")
def target_fields(statement_type: str, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("import.view")
    f = import_engine.TARGET_FIELDS.get(statement_type)
    if f is None:
        raise NotFound("Statement type")
    return [{"field": k, "type": v[0], "required": v[1], "description": v[2]} for k, v in f.items()]


@router.get("/imports/templates")
def templates(provider_id: int | None = None, statement_type: str | None = None, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("import.view")
    q = select(StatementImportTemplate).where(StatementImportTemplate.is_active.is_(True))
    if provider_id:
        q = q.where(StatementImportTemplate.provider_id == provider_id)
    if statement_type:
        q = q.where(StatementImportTemplate.statement_type.in_(statement_type.split(",")))
    out = []
    for t in ctx.db.execute(q.order_by(StatementImportTemplate.template_name, StatementImportTemplate.version.desc())).scalars():
        cols = ctx.db.execute(select(StatementTemplateColumn).where(StatementTemplateColumn.template_id == t.id)
                              .order_by(StatementTemplateColumn.display_order)).scalars()
        out.append({**{c.key: jsonable(getattr(t, c.key)) for c in t.__table__.columns},
                    "columns": [{c.key: getattr(x, c.key) for c in x.__table__.columns} for x in cols]})
    return out


@router.post("/imports/sheets")
async def sheets(file: UploadFile = File(...), ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("import.run")
    return {"sheets": import_engine.list_sheets(await file.read(), file.filename or "")}


@router.post("/imports/preview")
async def preview(background: BackgroundTasks, template_id: int = Form(...), sheet: str | None = Form(None),
                  bank_account_id: int | None = Form(None), file: UploadFile = File(...), ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("import.run")
    data = await file.read()
    b = import_engine.create_preview(ctx, template_id, data, file.filename or "upload.xlsx", sheet or None,
                                     bank_account_id)
    commit(ctx)
    return batch_view(b.id, ctx=ctx)


@router.get("/imports/batches/{bid}")
def batch_view(bid: int, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("import.view")
    b = ctx.db.get(StatementImportBatch, bid)
    if not b:
        raise NotFound("Batch")
    spec = get_spec("import_batches")
    header_errs = ctx.db.execute(select(StatementImportError).where(StatementImportError.batch_id == bid,
                                                                    StatementImportError.error_type == "HEADER")).scalars()
    return {"batch": masters.serialize_many(ctx, spec, [b])[0],
            "header_errors": [{"column": e.source_column, "field": e.target_field, "message": e.error_message,
                               "severity": e.severity} for e in header_errs],
            "status_counts": dict(ctx.db.execute(select(StatementImportRow.status, func.count()).where(
                StatementImportRow.batch_id == bid).group_by(StatementImportRow.status)).all())}


@router.get("/imports/batches/{bid}/rows")
def batch_rows(bid: int, status: str | None = None, page: int = 1, size: int = 50, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("import.view")
    q = select(StatementImportRow).where(StatementImportRow.batch_id == bid)
    if status:
        q = q.where(StatementImportRow.status.in_(status.split(",")))
    total = ctx.db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    size = min(max(size, 1), 500)
    rows = ctx.db.execute(q.order_by(StatementImportRow.source_row).offset((page - 1) * size).limit(size)).scalars()
    return {"total": total, "page": page, "size": size, "items": [
        {"id": r.id, "source_row": r.source_row, "status": r.status, "raw": r.raw_values, "values": r.normalized_values,
         "messages": r.messages, "target_table": r.target_table, "target_id": r.target_id} for r in rows]}


@router.get("/imports/batches/{bid}/errors")
def batch_errors(bid: int, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("import.view")
    rows = ctx.db.execute(select(StatementImportError).where(StatementImportError.batch_id == bid)
                          .order_by(StatementImportError.source_row).limit(5000)).scalars()
    return [{c.key: jsonable(getattr(e, c.key)) for c in e.__table__.columns} for e in rows]


@router.post("/imports/batches/{bid}/commit")
def batch_commit(bid: int, background: BackgroundTasks, data: dict[str, Any] = Body(default={}),
                 ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("import.run")
    b = ctx.db.get(StatementImportBatch, bid)
    if not b:
        raise NotFound("Batch")
    if b.total_rows > get_settings().async_import_threshold:
        if b.status != "PREVIEWED":
            raise BusinessError(f"Batch is {b.status}")
        b.status = "QUEUED"
        commit(ctx)
        background.add_task(import_engine.run_commit_job, bid, ctx.user.id)
        return {"queued": True, "batch_id": bid}
    import_engine.commit_batch(ctx, bid, auto_suggest=data.get("auto_suggest", True))
    commit(ctx)
    return batch_view(bid, ctx=ctx)


@router.post("/imports/batches/{bid}/cancel")
def batch_cancel(bid: int, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("import.run")
    import_engine.cancel_batch(ctx, bid)
    commit(ctx)
    return {"ok": True}


@router.post("/operations/rematch/{kind}")
def rematch(kind: str, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require(f"{'toll' if kind == 'toll' else 'fuel'}.edit")
    res = operations.rematch_unmatched(ctx, kind)
    commit(ctx)
    return res


# ───────────────────────── tyres ─────────────────────────
@router.get("/tyres/vehicle/{vid}")
def tyre_vehicle(vid: int, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("tyre.view")
    return jsonable(tyres.vehicle_tyres(ctx.db, vid))


@router.get("/tyres/{tid}/timeline")
def tyre_timeline(tid: int, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("tyre.view")
    t = ctx.db.get(Tyre, tid)
    if not t:
        raise NotFound("Tyre")
    return {"tyre": masters.serialize_many(ctx, get_spec("tyres"), [t])[0], "timeline": tyres.timeline(ctx.db, tid),
            "cost": jsonable(tyres.tyre_cost(ctx.db, t))}


# ───────────────────────── reports ─────────────────────────
@router.get("/reports")
def report_list(ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("report.view")
    return [{"key": r.key, "title": r.title, "group": r.group, "params": list(r.params)} for r in reports.REPORTS.values()]


@router.get("/reports/{key}")
def report_run(key: str, request: Request, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("report.view")
    res = reports.run(ctx.db, key, dict(request.query_params))
    res["rows"] = reports.display_rows(res["rows"])
    return jsonable(res)


@router.get("/reports/{key}/export")
def report_export(key: str, request: Request, fmt: str = "xlsx", ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("report.export")
    p = dict(request.query_params)
    res = reports.run(ctx.db, key, p)
    rows = reports.display_rows(res["rows"])
    fname = f"{key}_{today():%d-%m-%Y}"
    sub = " | ".join(f"{k}: {v}" for k, v in p.items() if k != "fmt" and v)
    if fmt == "csv":
        return Response(masters.to_csv(res["columns"], rows), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})
    if fmt == "pdf":
        return Response(masters.to_pdf(res["title"], res["columns"], rows, sub), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.pdf"'})
    return Response(masters.to_xlsx(res["title"], res["columns"], rows),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'})


# ───────────────────────── dashboard / notifications / jobs ─────────────────────────
@router.get("/dashboard")
def dash(ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("dashboard.view")
    return dashboard.summary(ctx.db, ctx.user)


@router.get("/notifications/unread-count")
def unread(ctx: Ctx = Depends(ctx_dep)):
    return {"count": ctx.db.execute(select(func.count()).select_from(Notification).where(
        Notification.is_read.is_(False))).scalar_one()}


def run_daily_jobs(db) -> dict:
    """Scheduled daily jobs (cron → `python -m app.jobs daily`, or the admin button)."""
    res = {"classifications_applied": vehicles.apply_scheduled_classifications(db),
           "renewal_status_changes": renewals.refresh_statuses(db), "renewal_alerts": renewals.scan_alerts(db),
           "maintenance_alerts": maintenance.due_alerts(db)}
    from app.services.notifications import notify
    unmatched = db.execute(select(func.count()).select_from(BankTransaction).where(
        BankTransaction.recon_status == "UNMATCHED", BankTransaction.status == "ACTIVE")).scalar_one()
    if unmatched:
        notify(db, "UNMATCHED_BANK", f"{unmatched} unmatched bank transaction(s) awaiting reconciliation",
               severity="WARNING", link_url="/finance/reconciliation", dedupe_key=f"unmatched:{today()}")
    thr = Decimal(rule(db, "TYRE_MIN_TREAD_MM"))
    for t in db.execute(select(Tyre).where(Tyre.current_tread_depth <= thr, Tyre.current_vehicle_id.is_not(None))).scalars():
        notify(db, "TYRE_TREAD_LOW", f"Tyre {t.serial_number} tread {t.current_tread_depth} mm (≤ {thr})",
               severity="WARNING", entity_type="tyres", entity_id=t.id, link_url="/tyres/dashboard",
               dedupe_key=f"tread:{t.id}:{t.current_tread_depth}")
    for t in db.execute(select(Tyre).where(Tyre.warranty_expiry_date.between(today(), today() + timedelta(days=30)))
                        ).scalars():
        notify(db, "TYRE_WARRANTY", f"Tyre {t.serial_number} warranty expires {t.warranty_expiry_date:%d/%m/%Y}",
               severity="INFO", entity_type="tyres", entity_id=t.id, dedupe_key=f"twarranty:{t.id}")
    return res


@router.post("/admin/jobs/daily")
def jobs_daily(ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("admin.edit")
    res = run_daily_jobs(ctx.db)
    commit(ctx)
    return res


# ───────────────────────── integration APIs (future provider feeds) ─────────────────────────
class TollApiTxn(BaseModel):
    transaction_id: str
    txn_datetime: str
    vehicle_number: str | None = None
    fastag_id: str | None = None
    plaza_id: str | None = None
    plaza_code: str | None = None
    plaza_name: str | None = None
    amount: Decimal
    direction: str | None = None
    lane: str | None = None
    txn_kind: str = "DEBIT"


@router.post("/integrations/toll/{provider_id}/transactions")
def api_toll(provider_id: int, items: list[TollApiTxn], ctx: Ctx = Depends(ctx_dep)):
    """Provider API feed → the same normalised `toll_transactions` table (source_type=API)."""
    ctx.user.require("import.run")
    from app.core.utils import parse_datetime
    from app.models.operations import TollTransaction
    created = dup = 0
    for it in items:
        if ctx.db.execute(select(TollTransaction.id).where(TollTransaction.provider_id == provider_id,
                                                           TollTransaction.transaction_id == it.transaction_id)).first():
            dup += 1
            continue
        dt = parse_datetime(it.txn_datetime)
        t = TollTransaction(provider_id=provider_id, transaction_id=it.transaction_id, txn_datetime=dt,
                            txn_date=dt.date(), registration_raw=it.vehicle_number, fastag_id=it.fastag_id,
                            plaza_external_id_raw=it.plaza_id, plaza_code_raw=it.plaza_code,
                            plaza_name_raw=it.plaza_name, amount=it.amount, direction=it.direction, lane=it.lane,
                            txn_kind=it.txn_kind, source_type="API", source_reference=f"API:{provider_id}",
                            created_by=ctx.user.id)
        operations.process_toll(ctx, t)
        ctx.db.add(t)
        ctx.db.flush()  # so a repeated id later in the same payload is detected as a duplicate
        created += 1
    commit(ctx)
    return {"created": created, "duplicates": dup}


# ───────────────────────── toll plaza master from internet sources ─────────────────────────
class TollPlazaSyncIn(BaseModel):
    integration_id: int | None = Field(None, description="API Integration of type TOLL_PLAZA_MASTER (default: first active)")
    states: list[str] = Field(default_factory=list, description="State codes or names; empty = all of India")
    dry_run: bool = Field(False, description="Read the source and count what would change, without saving")
    wait: bool = Field(False, description="Run inside the request instead of in the background")


@router.get("/toll-plazas/sync/sources")
def toll_sync_sources(ctx: Ctx = Depends(ctx_dep)):
    """Configured internet sources for the toll plaza master."""
    ctx.user.require("toll.view")
    from app.services import toll_sync
    return [{"id": i.id, "code": i.code, "name": i.name, "adapter": (i.settings or {}).get("adapter"),
             "is_active": i.is_active, "base_url": i.base_url, "needs_key": (i.auth_type or "NONE") != "NONE"
             or (i.settings or {}).get("adapter") == "DATA_GOV_IN",
             "key_env_var": i.credential_env_var, "last_sync_at": jsonable(i.last_sync_at),
             "last_sync_status": i.last_sync_status} for i in toll_sync.integrations(ctx.db)]


@router.get("/toll-plazas/sync/states")
def toll_sync_states(ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("toll.view")
    from app.services.toll_sync import INDIA_STATES
    return [{"code": c, "name": n} for c, n, *_ in INDIA_STATES]


@router.post("/toll-plazas/sync")
def toll_sync_start(data: TollPlazaSyncIn, background: BackgroundTasks, ctx: Ctx = Depends(ctx_dep)):
    """Fetch toll plazas (toll ID, name, place, state — all compulsory) from an internet source and
    create / update the toll plaza master. Runs in the background unless `wait` is true; poll the run."""
    ctx.user.require("toll.edit")
    from app.core.audit import audit
    from app.services import toll_sync
    integ = toll_sync.get_integration(ctx.db, data.integration_id)
    states = toll_sync.requested_states(data.states) if data.states else []
    if data.wait:
        run = toll_sync.run_now(ctx.db, integ, states, data.dry_run, ctx.user.id)
    else:
        run = toll_sync.create_run(ctx.db, integ, states, data.dry_run, ctx.user.id)
    audit(ctx.db, ctx.user, "SYNC", "toll_plazas", None, None,
          {"integration": integ.code, "states": states or "ALL", "dry_run": data.dry_run, "run_id": run.id})
    commit(ctx)
    if not data.wait:
        background.add_task(toll_sync.run_background, run.id)
    return toll_sync.run_to_dict(run)


@router.get("/toll-plazas/sync/runs")
def toll_sync_runs(limit: int = 20, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("toll.view")
    from app.models.operations import TollPlazaSyncRun
    from app.services.toll_sync import run_to_dict
    rows = ctx.db.execute(select(TollPlazaSyncRun).order_by(TollPlazaSyncRun.id.desc()).limit(min(limit, 200))).scalars()
    return [run_to_dict(r) for r in rows]


@router.get("/toll-plazas/sync/runs/{run_id}")
def toll_sync_run(run_id: int, ctx: Ctx = Depends(ctx_dep)):
    ctx.user.require("toll.view")
    from app.models.operations import TollPlazaSyncRun
    from app.services.toll_sync import run_to_dict
    run = ctx.db.get(TollPlazaSyncRun, run_id)
    if not run:
        raise NotFound("Sync run")
    return run_to_dict(run)


@router.get("/toll-plazas/summary")
def toll_plaza_summary(ctx: Ctx = Depends(ctx_dep)):
    """Directory view: totals and a state-wise count of active toll plazas."""
    ctx.user.require("toll.view")
    from sqlalchemy import case
    from app.models.operations import TollPlaza
    from app.models.org import State
    live = (TollPlaza.deleted_at.is_(None), TollPlaza.is_active.is_(True))
    n = lambda cond: func.coalesce(func.sum(case((cond, 1), else_=0)), 0)  # noqa: E731
    tot = ctx.db.execute(select(
        func.count(TollPlaza.id), n(TollPlaza.api_source.is_not(None)), n(TollPlaza.details_locked.is_(True)),
        n(TollPlaza.place.is_(None) | (TollPlaza.place == "")), n(TollPlaza.state_id.is_(None)),
        n(TollPlaza.latitude.is_(None) | TollPlaza.longitude.is_(None)), func.max(TollPlaza.api_last_synced_at),
    ).where(*live)).one()
    rows = ctx.db.execute(
        select(State.id, State.code, State.name, func.count(TollPlaza.id), n(TollPlaza.api_source.is_not(None)),
               n(TollPlaza.details_locked.is_(True)), func.max(TollPlaza.api_last_synced_at))
        .join(State, State.id == TollPlaza.state_id, isouter=True).where(*live)
        .group_by(State.id, State.code, State.name).order_by(func.count(TollPlaza.id).desc())).all()
    return {"total": tot[0], "from_internet": int(tot[1]), "entered_by_hand": tot[0] - int(tot[1]),
            "kept_changes": int(tot[2]), "missing_place": int(tot[3]), "missing_state": int(tot[4]),
            "without_coordinates": int(tot[5]), "last_fetched": jsonable(tot[6]),
            "by_state": [{"state_id": r[0], "code": r[1], "name": r[2] or "(no state)", "total": r[3],
                          "from_internet": int(r[4]), "kept_changes": int(r[5]), "last_fetched": jsonable(r[6])}
                         for r in rows]}


@router.get("/toll-plazas/map")
def toll_plaza_map(state_id: int | None = None, q: str | None = None, source: str | None = None,
                   ctx: Ctx = Depends(ctx_dep)):
    """Active toll plazas for the directory list and map (up to 5,000)."""
    ctx.user.require("toll.view")
    from sqlalchemy import or_ as _or
    from app.models.operations import TollPlaza
    from app.models.org import State
    stmt = (select(TollPlaza, State.code, State.name).join(State, State.id == TollPlaza.state_id, isouter=True)
            .where(TollPlaza.deleted_at.is_(None), TollPlaza.is_active.is_(True)))
    if state_id:
        stmt = stmt.where(TollPlaza.state_id == state_id)
    if source == "MANUAL":
        stmt = stmt.where(TollPlaza.api_source.is_(None))
    elif source:
        stmt = stmt.where(TollPlaza.api_source == source)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(_or(TollPlaza.name.ilike(like), TollPlaza.place.ilike(like), TollPlaza.plaza_code.ilike(like),
                              TollPlaza.external_plaza_id.ilike(like), TollPlaza.highway.ilike(like)))
    out = []
    for p, scode, sname in ctx.db.execute(stmt.order_by(TollPlaza.name).limit(5000)):
        out.append({"id": p.id, "plaza_code": p.plaza_code, "toll_id": p.external_plaza_id, "name": p.name,
                    "place": p.place, "state_code": scode, "state": sname or p.state_name, "highway": p.highway,
                    "lat": float(p.latitude) if p.latitude is not None else None,
                    "lon": float(p.longitude) if p.longitude is not None else None,
                    "source": p.api_source, "kept_changes": bool(p.details_locked),
                    "last_fetched": jsonable(p.api_last_synced_at)})
    return out


# ───────────────────────── global search ─────────────────────────
_SEARCH = [("vehicles", "Vehicle", ("registration_number", "vehicle_code", "fleet_number", "chassis_number"), "fleet.view"),
           ("drivers", "Driver", ("name", "driver_code", "license_number"), "driver.view"),
           ("tyres", "Tyre", ("serial_number", "tyre_code"), "tyre.view"),
           ("invoices", "Invoice", ("invoice_number",), "contract.view"),
           ("contracts", "Contract", ("contract_number",), "contract.view"),
           ("customers", "Customer", ("name", "code"), "contract.view"),
           ("vendors", "Vendor", ("name", "code"), "vendor.view"),
           ("bank_transactions", "Bank txn", ("utr", "reference_number"), "finance.view"),
           ("job_cards", "Job card", ("job_card_number",), "maintenance.view"),
           ("insurance_policies", "Policy", ("policy_number",), "compliance.view"),
           ("vehicle_renewals", "Certificate", ("certificate_number",), "compliance.view")]


@router.get("/search")
def global_search(q: str, ctx: Ctx = Depends(ctx_dep)):
    from sqlalchemy import or_ as _or
    from app.core.utils import normalize_vehicle_number
    q = q.strip()
    if len(q) < 2:
        return []
    hits = []
    for key, kind, cols, perm in _SEARCH:
        if not ctx.user.has(perm):
            continue
        spec = get_spec(key)
        M = spec.model
        conds = [getattr(M, c).ilike(f"%{q}%") for c in cols]
        if key == "vehicles":
            conds.append(M.registration_normalized.like(f"%{normalize_vehicle_number(q)}%"))
        for o in ctx.db.execute(select(M).where(_or(*conds)).limit(6)).scalars():
            hits.append({"kind": kind, "label": masters._label_of(o, spec), "url": f"/masters/{key}?id={o.id}"})
    return hits[:40]
