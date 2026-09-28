#!/usr/bin/env bash
# Restore a backup produced by backup_mysql.sh into an EMPTY database, then documents.
#   Usage: scripts/restore_mysql.sh <db_dump.sql.gz> <documents.tar.gz> [target_db]
set -euo pipefail
DUMP="$1"; DOCS="$2"; DB="${3:-${ERP_DB_NAME:-ERP_LOGISTICS}}"
STORAGE="${ERP_STORAGE_DIR:-$(dirname "$0")/../storage}"
read -r -p "Restore into database '$DB' (must be empty) and storage '$STORAGE'? [yes/NO] " ok
[ "$ok" = "yes" ] || { echo "Aborted"; exit 1; }
mysql -e "CREATE DATABASE IF NOT EXISTS \`$DB\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
gunzip -c "$DUMP" | mysql "$DB"
mkdir -p "$STORAGE" && tar -xzf "$DOCS" -C "$STORAGE"
echo "Restored. Run 'alembic upgrade head' if the backup is older than the application version."
