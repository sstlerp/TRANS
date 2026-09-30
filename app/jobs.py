"""Scheduled jobs (run from cron / a systemd timer / Windows Task Scheduler).

    python -m app.jobs daily          # renewal statuses, reminders, maintenance-due, tread/warranty alerts,
                                      # future-dated reclassifications, unmatched-bank reminder
    python -m app.jobs rematch        # re-run toll/fuel vehicle & plaza matching after master/mapping updates
    python -m app.jobs toll-plazas [--source TOLL-OSM] [--states TN,KA] [--dry-run]
                                      # fetch / update the toll plaza master from the internet (e.g. weekly)

Example crontab (company timezone Asia/Kolkata):
    15 6 * * *  cd /opt/trans-erp && .venv/bin/python -m app.jobs daily >> logs/jobs.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import logging

from sqlalchemy import select

from app.core.logging_setup import setup_logging
from app.database import session_scope

log = logging.getLogger("erp.jobs")


def _system_ctx(db):
    from app.core.security import load_user
    from app.models.system import User
    from app.services.masters import Ctx
    u = db.execute(select(User).where(User.is_superuser.is_(True), User.is_active.is_(True))).scalars().first()
    return Ctx(db, load_user(db, u.id))


def _toll_plazas(args) -> dict:
    """Runs like the background job: commits after every state, so a long all-India fetch keeps its progress."""
    from app.models.operations import ApiIntegration
    from app.services import toll_sync
    with session_scope() as db:
        integ_id = None
        if args.source:
            integ = db.execute(select(ApiIntegration).where(ApiIntegration.code == args.source)).scalars().first()
            if not integ:
                raise SystemExit(f"Unknown source {args.source}")
            integ_id = integ.id
        integ = toll_sync.get_integration(db, integ_id)
        states = toll_sync.requested_states(args.states.split(",")) if args.states else []
        run_id = toll_sync.create_run(db, integ, states, args.dry_run, _system_ctx(db).user.id).id
    toll_sync.run_background(run_id)
    with session_scope() as db:
        from app.models.operations import TollPlazaSyncRun
        return toll_sync.run_to_dict(db.get(TollPlazaSyncRun, run_id))


def main() -> None:
    setup_logging()
    import app.services.registry  # noqa: F401
    ap = argparse.ArgumentParser()
    ap.add_argument("job", choices=["daily", "rematch", "toll-plazas"])
    ap.add_argument("--source", help="toll-plazas: API integration code (default: first active source)")
    ap.add_argument("--states", help="toll-plazas: comma-separated state codes or names (default: all of India)")
    ap.add_argument("--dry-run", action="store_true", help="toll-plazas: count changes without saving")
    args = ap.parse_args()
    job = args.job
    if job == "toll-plazas":
        res = _toll_plazas(args)
        log.info("job %s finished: %s", job, res)
        print(json.dumps(res, default=str))
        return
    with session_scope() as db:
        if job == "daily":
            from app.api.domain import run_daily_jobs
            res = run_daily_jobs(db)
        else:
            from app.services.operations import rematch_unmatched
            ctx = _system_ctx(db)
            res = {"toll": rematch_unmatched(ctx, "toll"), "fuel": rematch_unmatched(ctx, "fuel")}
    log.info("job %s finished: %s", job, res)
    print(json.dumps(res, default=str))


if __name__ == "__main__":
    main()
