#!/usr/bin/env bash
# Regenerate the plain-SQL migration scripts in migrations/sql/ (see scripts/export_sql_migrations.py).
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-python}" scripts/export_sql_migrations.py "$@"
