"""The plain-SQL migration files must match the Alembic migrations, and every migration step must be guarded."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL = ROOT / "migrations" / "sql"


def test_sql_files_are_up_to_date():
    r = subprocess.run([sys.executable, "scripts/export_sql_migrations.py", "--check"], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_every_revision_has_guarded_upgrade_and_rollback():
    revs = sorted(p.name[:4] for p in (ROOT / "migrations" / "versions").glob("[0-9]*_*.py"))
    for rev in revs:
        up = next(SQL.glob(f"{rev}_*[!k].sql")).read_text(encoding="utf-8")
        down = next(SQL.glob(f"{rev}_*_rollback.sql")).read_text(encoding="utf-8")
        for text in (up, down):
            assert "SELECT MAX(version_num) INTO cur FROM alembic_version" in text
            assert text.count("DELIMITER $$") == 1 and text.rstrip().endswith("DROP PROCEDURE IF EXISTS erp_migration_step;")
            for m in re.findall(r"MESSAGE_TEXT = '([^']*)'", text):  # MySQL limit for SIGNAL messages
                assert len(m) <= 128
            # SIGNAL accepts only a literal or a variable (an expression is a syntax error on MySQL and MariaDB)
            for v in re.findall(r"MESSAGE_TEXT = ([^;]*);", text):
                assert re.fullmatch(r"'[^']*'|msg", v.strip()), v
        assert f"'{rev}'" in up and "USE `ERP_LOGISTICS`;" in up
