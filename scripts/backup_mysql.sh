#!/usr/bin/env bash
# Consistent, compressed MySQL backup of the ERP database + uploaded documents.
#   Usage: scripts/backup_mysql.sh [/backup/dir]
# Reads DB credentials from ~/.my.cnf or MYSQL_* env vars (never hard-code passwords here).
# Schedule daily (e.g. 01:30) and copy the output off-server; keep ≥ 30 daily + 12 monthly copies.
set -euo pipefail
DEST="${1:-/var/backups/trans-erp}"
DB="${ERP_DB_NAME:-trans_erp}"
STORAGE="${ERP_STORAGE_DIR:-$(dirname "$0")/../storage}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DEST"
# --single-transaction gives a consistent InnoDB snapshot without locking; routines/triggers included.
mysqldump --single-transaction --routines --triggers --events --hex-blob --default-character-set=utf8mb4 \
  "$DB" | gzip -9 > "$DEST/${DB}_${STAMP}.sql.gz"
tar -czf "$DEST/documents_${STAMP}.tar.gz" -C "$STORAGE" .
sha256sum "$DEST/${DB}_${STAMP}.sql.gz" "$DEST/documents_${STAMP}.tar.gz" > "$DEST/${STAMP}.sha256"
find "$DEST" -type f -mtime +"${RETENTION_DAYS:-35}" -delete
echo "Backup written to $DEST (${STAMP})"
