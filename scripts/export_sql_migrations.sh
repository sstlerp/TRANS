#!/usr/bin/env bash
# Regenerate the plain-SQL migration scripts in migrations/sql/ from the Alembic migrations — one upgrade file and
# one rollback file per migration. Run after adding a migration (alembic revision --autogenerate ...).
# Needs no database connection.
#   Usage: scripts/export_sql_migrations.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DB="$(python -c 'from sqlalchemy.engine import make_url; from app.config import get_settings; print(make_url(get_settings().database_url).database)')"
OUT=migrations/sql
mkdir -p "$OUT"
prev=""
for f in migrations/versions/[0-9][0-9][0-9][0-9]_*.py; do
  name="$(basename "$f" .py)"
  rev="${name%%_*}"
  title="$(sed -n '1s/^"""//p' "$f")"
  from="${prev:-base}"
  {
  cat <<SQL
-- =====================================================================================================
-- TRANS ERP — database ${DB} — migration ${rev}: ${title}
--
-- Generated from ${f} with:  alembic upgrade ${prev:+${prev}:}${rev} --sql   (scripts/export_sql_migrations.sh)
-- Use it instead of Alembic by running the files in order:
--     mysql -u root -p < ${OUT}/${name}.sql
-- Each file also updates the alembic_version marker, so later \`alembic upgrade head\` runs continue from here.
SQL
  if [ -z "$prev" ]; then
    cat <<SQL
-- This first file creates the database and every ERP table. Then load reference data with:  python -m app.seed
-- =====================================================================================================

CREATE DATABASE IF NOT EXISTS \`${DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
SQL
  else
    echo "-- ====================================================================================================="
    echo
  fi
  cat <<SQL
USE \`${DB}\`;
SET NAMES utf8mb4;

SQL
  if [ -z "$prev" ]; then
    alembic upgrade "$rev" --sql 2>/dev/null | sed 's/^CREATE TABLE alembic_version (/CREATE TABLE IF NOT EXISTS alembic_version (/'
  else
    alembic upgrade "$prev:$rev" --sql 2>/dev/null
  fi
  } > "$OUT/${name}.sql"
  {
  cat <<SQL
-- TRANS ERP — database ${DB} — rollback of migration ${rev} (${title})
-- Generated with: alembic downgrade ${rev}:${prev:-base} --sql      Take a backup first (scripts/backup_mysql.sh).
USE \`${DB}\`;

SQL
  alembic downgrade "$rev:${prev:-base}" --sql 2>/dev/null | sed "s/^DROP TABLE /DROP TABLE IF EXISTS /"
  } > "$OUT/${name}_rollback.sql"
  echo "Wrote $OUT/${name}.sql and $OUT/${name}_rollback.sql"
  prev="$rev"
done
