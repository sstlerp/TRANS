# Deployment & operations

## Reference topology

```
Users (browser, LAN/VPN/Internet) ──HTTPS──► nginx (TLS, gzip, request limits) ──► uvicorn workers (app)
                                                                                   │
                                                          MySQL 8 (InnoDB) ◄───────┤
                                                          /var/lib/trans-erp/storage (documents, import files)
cron / systemd timers: python -m app.jobs daily · scripts/backup_mysql.sh
```

## Linux (systemd + nginx)

```bash
sudo useradd -r -m -d /opt/trans-erp erp
sudo -u erp git clone <repo> /opt/trans-erp && cd /opt/trans-erp
sudo -u erp python3.11 -m venv .venv && sudo -u erp .venv/bin/pip install -r requirements.txt
sudo install -o erp -m 600 .env.example /etc/trans-erp.env      # edit: DB URL, SECRET_KEY, COOKIE_SECURE=true …
sudo mkdir -p /var/lib/trans-erp/storage /var/log/trans-erp && sudo chown -R erp /var/lib/trans-erp /var/log/trans-erp
# database ERP_LOGISTICS: the migration creates it (utf8mb4) if missing — or run migrations/sql/0001_initial_schema.sql
sudo -u erp env $(cat /etc/trans-erp.env | xargs) .venv/bin/alembic upgrade head
sudo -u erp env $(cat /etc/trans-erp.env | xargs) .venv/bin/python -m app.seed
```

`/etc/systemd/system/trans-erp.service`

```ini
[Unit]
Description=TRANS ERP
After=network.target mysql.service

[Service]
User=erp
WorkingDirectory=/opt/trans-erp
EnvironmentFile=/etc/trans-erp.env
ExecStart=/opt/trans-erp/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4 --proxy-headers
Restart=always
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/trans-erp-daily.service` + `.timer` (06:15 IST):

```ini
[Service]
Type=oneshot
User=erp
WorkingDirectory=/opt/trans-erp
EnvironmentFile=/etc/trans-erp.env
ExecStart=/opt/trans-erp/.venv/bin/python -m app.jobs daily

[Timer]
OnCalendar=*-*-* 06:15:00 Asia/Kolkata
Persistent=true
[Install]
WantedBy=timers.target
```

nginx server block:

```nginx
server {
  listen 443 ssl http2;
  server_name erp.example.com;
  ssl_certificate /etc/letsencrypt/live/erp.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/erp.example.com/privkey.pem;
  client_max_body_size 30m;                       # ≥ ERP_MAX_UPLOAD_MB
  add_header Strict-Transport-Security "max-age=31536000" always;
  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;                      # large import previews
  }
  location /static/ { alias /opt/trans-erp/app/static/; expires 7d; }
}
```

## Docker

```bash
cp .env.example .env         # set ERP_SECRET_KEY etc.
docker compose up --build -d # MySQL 8 + app; runs `alembic upgrade head` and the reference seed on start
docker compose exec app python -m app.seed --demo      # optional demo data
```

## Windows server

Install Python 3.11 and MySQL 8, create the venv as above, run `alembic upgrade head` and `python -m app.seed`, then
register `uvicorn app.main:app --host 0.0.0.0 --port 8000` as a service (NSSM) and schedule `python -m app.jobs daily`
and a `mysqldump` backup with Task Scheduler. Put IIS/nginx with TLS in front.

## Upgrades

1. Back up (database + storage). 2. `git pull` a tagged release. 3. `pip install -r requirements.txt`.
4. `alembic upgrade head`. 5. `python -m app.seed` (adds new reference rows/permissions; never overwrites edits).
6. Restart the service. Roll back = restore backup + previous release.

## Backups

`scripts/backup_mysql.sh` runs a consistent `mysqldump --single-transaction` (no table locks for InnoDB) and archives
`ERP_STORAGE_DIR`, writes SHA-256 checksums and prunes by `RETENTION_DAYS`. Schedule nightly, copy off-site, test a
restore monthly with `scripts/restore_mysql.sh` into a scratch database. For point-in-time recovery enable MySQL binary
logs (`log_bin`, `binlog_expire_logs_seconds`) and archive them.

## Security hardening checklist

* `ERP_ENV=production`, long random `ERP_SECRET_KEY`, `ERP_COOKIE_SECURE=true`, HTTPS only (HSTS).
* Database user limited to the ERP schema; MySQL not exposed publicly; TLS to MySQL if on another host.
* Change the seeded admin password (forced at first login) and create named users per person (no shared logins).
* Review role permissions; keep `approval.approve`, overrides and `admin.*` to a few people; use branch restrictions.
* Integration secrets only in environment variables / a secret manager (API Integrations stores names only).
* Keep `logs/` and backups readable only by the service account; logs mask passwords/tokens/keys.
* Rate limiting of logins is in-process: behind several app servers also rate-limit `/login` in nginx.
* Built-in protections: bcrypt passwords, JWT with revocation on password change, CSRF double-submit token for cookie
  sessions, CSP/X-Frame-Options/nosniff headers, parameterised SQL (ORM), HTML escaping in templates and JS, upload
  extension + magic-byte validation, opaque storage keys (no user-controlled paths), permission checks on document download.

## Monitoring

* `logs/erp.log` (rotating): API errors with reference ids, authentication events, import processing, financial
  operations (`financial-op action=…`), background jobs, integration errors.
* Dashboard counters for unmatched transactions, import errors, pending approvals and unresolved matches.
* Health check: `GET /login` (200) — add `/docs` for a deeper check that the app imports correctly.

## Performance notes

* All lists are server-side paginated (max 500 rows per page); exports stream the filtered set.
* Indexes on business keys and hot filters (vehicle+date, status, txn hash, expiry, entity for audit/documents).
* Report aggregation happens in SQL (grouped by cost center / report group / day) before any Python processing.
* Imports stage rows in bulk (1,000 per flush); batches above `ERP_ASYNC_IMPORT_THRESHOLD` commit in the background
  with progress; run multiple uvicorn workers for concurrency. For very large fleets consider monthly summary tables
  refreshed by the daily job (the ledger query is the single source to summarise).
