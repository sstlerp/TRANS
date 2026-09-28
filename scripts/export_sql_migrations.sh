#!/usr/bin/env bash
# Regenerate the plain-SQL migration scripts in migrations/sql/ from the Alembic migrations.
# Run after adding a migration (alembic revision --autogenerate ...). Needs no database connection.
#   Usage: scripts/export_sql_migrations.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DB="$(python -c 'from sqlalchemy.engine import make_url; from app.config import get_settings; print(make_url(get_settings().database_url).database)')"
OUT=migrations/sql
mkdir -p "$OUT"
{
cat <<SQL
-- =====================================================================================================
-- TRANS ERP — database ${DB} — full schema up to the latest migration (all tables, keys, indexes, FKs)
--
-- Generated from migrations/versions/*.py with:  alembic upgrade head --sql   (scripts/export_sql_migrations.sh)
-- Use it to create the schema directly in MySQL instead of running Alembic:
--     mysql -u root -p < ${OUT}/0001_initial_schema.sql
-- It creates the database, every ERP table and the alembic_version marker, so later
-- \`alembic upgrade head\` runs continue from here. Then load reference data with:  python -m app.seed
-- =====================================================================================================

CREATE DATABASE IF NOT EXISTS \`${DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE \`${DB}\`;
SET NAMES utf8mb4;

SQL
alembic upgrade head --sql 2>/dev/null | sed 's/^CREATE TABLE alembic_version (/CREATE TABLE IF NOT EXISTS alembic_version (/'
} > "$OUT/0001_initial_schema.sql"
{
cat <<SQL
-- TRANS ERP — database ${DB} — rollback of migration 0001 (DROPS ALL ERP TABLES AND DATA).
-- Generated with: alembic downgrade 0001:base --sql      Take a backup first (scripts/backup_mysql.sh).
USE \`${DB}\`;

SQL
alembic downgrade 0001:base --sql 2>/dev/null | sed "s/^DROP TABLE /DROP TABLE IF EXISTS /"
} > "$OUT/0001_initial_schema_rollback.sql"
echo "Wrote $OUT/0001_initial_schema.sql and $OUT/0001_initial_schema_rollback.sql for database ${DB}"
