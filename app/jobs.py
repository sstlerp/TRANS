"""Scheduled jobs (run from cron / a systemd timer / Windows Task Scheduler).

    python -m app.jobs daily          # renewal statuses, reminders, maintenance-due, tread/warranty alerts,
                                      # future-dated reclassifications, unmatched-bank reminder
    python -m app.jobs rematch        # re-run toll/fuel vehicle & plaza matching after master/mapping updates

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


def main() -> None:
    setup_logging()
    import app.services.registry  # noqa: F401
    ap = argparse.ArgumentParser()
    ap.add_argument("job", choices=["daily", "rematch"])
    job = ap.parse_args().job
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
