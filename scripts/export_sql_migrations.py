"""Write the plain-SQL migration scripts in migrations/sql/ from the Alembic migrations.

For every revision N (in order) two files are written:

* ``NNNN_<name>.sql``           — upgrade from the previous revision to N
* ``NNNN_<name>_rollback.sql``  — downgrade from N to the previous revision

The statements come from ``alembic upgrade/downgrade --sql`` (exactly what Alembic itself runs). They are wrapped in a
temporary stored procedure that first reads the ``alembic_version`` marker, so each file is safe to run by hand:

* it runs only when the database is at the right version (upgrade: the previous revision; rollback: N itself);
* running a file again, or on a newer database, does nothing and says so;
* running a file out of order stops with a clear message (``Run 0002 first``) before anything is changed;
* the marker is updated in the same procedure, so ``alembic upgrade head`` / run_app.bat continue from there.

Works with the mysql command-line client, MySQL Workbench and HeidiSQL (they understand DELIMITER), on MySQL 8.x
and MariaDB 10.6+. Needs no database connection.   Usage:  python scripts/export_sql_migrations.py
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# one shared name: a run stopped by a version check leaves the procedure behind, and the next run of any file drops it
PROC = "erp_migration_step"
PRE: dict[str, list[tuple[str, str]]] = {}  # per revision: data checks run before anything is changed
OUT = ROOT / "migrations" / "sql"
VERSIONS = ROOT / "migrations" / "versions"


DB = "ERP_LOGISTICS"  # the files always target the standard database name (edit the USE lines for another name)


def revisions() -> list[tuple[str, str | None, str, Path]]:
    """(revision, down_revision, title, file) in upgrade order."""
    revs = {}
    for f in VERSIONS.glob("[0-9]*_*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        doc = (ast.get_docstring(tree) or "").split("\n\n")[0]
        vals = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                if isinstance(target, ast.Name) and target.id in ("revision", "down_revision", "PRECHECKS") \
                        and node.value is not None:
                    vals[target.id] = ast.literal_eval(node.value)
        title = " ".join(doc.split()).rstrip(",;:")
        PRE[vals["revision"]] = vals.get("PRECHECKS", [])
        revs[vals["revision"]] = (vals["revision"], vals.get("down_revision"), title, f)
    ordered, cur = [], None
    while True:
        nxt = [r for r in revs.values() if r[1] == cur]
        if not nxt:
            break
        if len(nxt) > 1:
            raise SystemExit(f"Branched migrations after {cur}: {[r[0] for r in nxt]}")
        ordered.append(nxt[0])
        cur = nxt[0][0]
    if len(ordered) != len(revs):
        raise SystemExit("Some migration files are not linked by down_revision")
    return ordered


def alembic_sql(args: list[str]) -> list[str]:
    """Statements emitted by alembic --sql, without the alembic_version bookkeeping (handled by the wrapper)."""
    out = subprocess.run([sys.executable, "-m", "alembic", *args, "--sql"], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout
    stmts, buf = [], []
    for line in out.splitlines():
        if line.startswith("-- Running") or (not buf and not line.strip()):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip()
            buf = []
            if "alembic_version" not in stmt:
                stmts.append(stmt)
    if "".join(buf).strip():
        raise SystemExit(f"Unterminated SQL from alembic {' '.join(args)}")
    for s in stmts:
        if "$$" in s:
            raise SystemExit("A statement contains $$ — choose another DELIMITER in export_sql_migrations.py")
    return stmts


def indent(stmts: list[str]) -> str:
    return "\n\n".join("    " + s.replace("\n", "\n    ") for s in stmts)


HEAD = """-- =====================================================================================================
-- TRANS ERP — database {db} — {what}
--   {title}
--
-- Generated from {src} by scripts/export_sql_migrations.py ({how}).
-- Run the files in order, e.g.   mysql -u root -p < {path}
-- Safe to run again: the alembic_version marker is checked first, so an applied step is skipped and a missing
-- earlier step stops the script before anything is changed. Then `alembic upgrade head` / run_app.bat continue.
-- =====================================================================================================
"""


def upgrade_file(db: str, rev: str, prev: str | None, title: str, src: Path, stmts: list[str]) -> str:
    name = PROC
    first = prev is None
    path = f"migrations/sql/{src.stem}.sql"
    parts = [HEAD.format(db=db, what=f"migration {rev} (upgrade)", title=title, src=src.relative_to(ROOT).as_posix(),
                         how=f"alembic upgrade {prev + ':' if prev else ''}{rev} --sql", path=path)]
    if first:
        parts.append("-- Creates the database (utf8mb4) and every ERP table. Afterwards load reference data with:"
                     "  python -m app.seed\n")
        parts.append(f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        parts.append(f"ALTER DATABASE `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    else:
        parts.append(f"-- Requires migration {prev}.\n")
    parts.append(f"USE `{db}`;\nSET NAMES utf8mb4;\n")
    parts.append("CREATE TABLE IF NOT EXISTS alembic_version (\n    version_num VARCHAR(32) NOT NULL,\n"
                 "    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)\n);\n")
    marker = (f"ALTER TABLE alembic_version CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n\n"
              f"    INSERT INTO alembic_version (version_num) VALUES ('{rev}');" if first
              else f"UPDATE alembic_version SET version_num = '{rev}' WHERE version_num = '{prev}';")
    count_tables = ("SELECT COUNT(*) INTO n FROM information_schema.tables WHERE table_schema = DATABASE() "
                    "AND table_name <> 'alembic_version';") if first else "SET n = 0;"
    missing_check = "" if first else f"""
  ELSEIF cur IS NULL OR cur <> '{prev}' THEN
    SET msg = CONCAT('Migration {rev} needs migration {prev} first; database is at ', IFNULL(cur, 'no version'), '.');
    SET msg = LEFT(msg, 128);  -- MySQL limit for SIGNAL messages
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = msg;"""
    tables_check = ("""
  ELSEIF n > 0 THEN
    SET msg = CONCAT('Database `', DATABASE(), '` already has ', n,
                     ' tables but no migration marker. Restore a backup or use an empty database.');
    SET msg = LEFT(msg, 128);  -- MySQL limit for SIGNAL messages
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = msg;""" if first else "")
    for query, message in PRE.get(rev, []):
        if len(message) > 128:  # MySQL's SIGNAL MESSAGE_TEXT limit
            raise SystemExit(f"PRECHECK message of {rev} is longer than 128 characters")
        tables_check += f"""
  ELSEIF ({query}) > 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '{message.replace("'", "''")}';"""
    parts.append(f"""DROP PROCEDURE IF EXISTS {name};
DELIMITER $$
CREATE PROCEDURE {name}()
BEGIN
  DECLARE cur VARCHAR(32) DEFAULT NULL;
  DECLARE msg VARCHAR(255);
  DECLARE n INT DEFAULT 0;
  SELECT MAX(version_num) INTO cur FROM alembic_version;
  {count_tables}
  IF cur IS NOT NULL AND cur >= '{rev}' THEN
    SELECT CONCAT('Migration {rev} is already applied (database is at ', cur, ') - nothing to do.') AS result;{missing_check}{tables_check}
  ELSE
{indent(stmts)}

    {marker}
    SELECT 'Migration {rev} applied.' AS result;
  END IF;
END$$
DELIMITER ;
CALL {name}();
DROP PROCEDURE IF EXISTS {name};
""")
    return "\n".join(parts)


def rollback_file(db: str, rev: str, prev: str | None, title: str, src: Path, stmts: list[str]) -> str:
    name = PROC
    path = f"migrations/sql/{src.stem}_rollback.sql"
    head = HEAD.format(db=db, what=f"ROLLBACK of migration {rev}", title=title, src=src.relative_to(ROOT).as_posix(),
                       how=f"alembic downgrade {rev}:{prev or 'base'} --sql", path=path)
    head = head.replace("-- Run the files in order", "-- Roll back newest first; TAKE A BACKUP FIRST (scripts/backup_mysql.sh)"
                        if prev else "-- THIS DROPS EVERY ERP TABLE AND ALL DATA; TAKE A BACKUP FIRST. Run")
    marker = (f"DELETE FROM alembic_version WHERE version_num = '{rev}';" if prev is None
              else f"UPDATE alembic_version SET version_num = '{prev}' WHERE version_num = '{rev}';")
    return head + f"""
USE `{db}`;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

DROP PROCEDURE IF EXISTS {name};
DELIMITER $$
CREATE PROCEDURE {name}()
BEGIN
  DECLARE cur VARCHAR(32) DEFAULT NULL;
  DECLARE msg VARCHAR(255);
  SELECT MAX(version_num) INTO cur FROM alembic_version;
  IF cur IS NULL OR cur < '{rev}' THEN
    SELECT CONCAT('Migration {rev} is not applied (database is at ', IFNULL(cur, 'no version'), ') - nothing to roll back.') AS result;
  ELSEIF cur > '{rev}' THEN
    SET msg = CONCAT('Roll back migration ', cur, ' first (newest first); database is at ', cur, '.');
    SET msg = LEFT(msg, 128);  -- MySQL limit for SIGNAL messages
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = msg;
  ELSE
{indent(stmts)}

    {marker}
    SELECT 'Migration {rev} rolled back.' AS result;
  END IF;
END$$
DELIMITER ;
CALL {name}();
DROP PROCEDURE IF EXISTS {name};
"""


def render() -> dict[str, str]:
    """{file name: content} for every migration file."""
    files = {}
    for rev, prev, title, src in revisions():
        up = alembic_sql(["upgrade", f"{prev}:{rev}" if prev else rev])
        down = [re.sub(r"^DROP TABLE ", "DROP TABLE IF EXISTS ", d)
                for d in alembic_sql(["downgrade", f"{rev}:{prev or 'base'}"])]
        files[f"{src.stem}.sql"] = upgrade_file(DB, rev, prev, title, src, up)
        files[f"{src.stem}_rollback.sql"] = rollback_file(DB, rev, prev, title, src, down)
    return files


def main() -> None:
    files = render()
    if "--check" in sys.argv:  # used by the tests: are the committed files up to date?
        current = {f.name: f.read_text(encoding="utf-8") for f in OUT.glob("*.sql")}
        stale = sorted(set(files) ^ set(current) | {k for k in files if current.get(k) != files[k]})
        if stale:
            raise SystemExit("migrations/sql is out of date (run python scripts/export_sql_migrations.py): " + ", ".join(stale))
        print("migrations/sql is up to date")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.sql"):
        old.unlink()
    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf-8", newline="\n")
        print("Wrote", name)


if __name__ == "__main__":
    main()
