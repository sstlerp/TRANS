# TRANS ERP — Transport & Logistics ERP (India)

A modular, auditable ERP for an India-based transport and logistics company: fleet and cost centers, compliance and
renewals, insurance, contracts and income, bank statement import and reconciliation, fuel, toll/FASTag, maintenance,
the full tyre lifecycle, profitability reporting, RBAC, audit trail, documents, alerts and approvals.

* **Backend:** Python 3.11+, FastAPI (REST + OpenAPI), SQLAlchemy 2 ORM, Alembic migrations, service layer.
* **Database:** MySQL 8 / MariaDB 10.6+ (InnoDB, utf8mb4). SQLite is used only as a fallback for quick tests.
* **Frontend:** server-rendered HTML pages (Jinja2) + vanilla JavaScript calling the REST API, in the same design
  system as the supplied `employee_master.html` template (dark toolbar with centred title pill, sky-blue section
  heads, VSB summary bar, compact 3-column forms, navy-gradient tables, modals, toasts). Responsive for desktop,
  laptop and tablet. **All dates are shown as DD/MM/YYYY.**

---

## Contents

1. [Architecture](#architecture) · 2. [Prerequisites](#prerequisites) · 3. [Installation](#installation) ·
4. [Environment variables](#environment-variables) · 5. [MySQL setup](#mysql-setup) · 6. [Migrations](#migrations) ·
7. [Seed data](#seed-data) · 8. [Running](#running-the-application) · 9. [Tests](#running-tests) ·
10. [Importing Excel](#importing-excel-statements) · 11. [Templates & providers](#configuring-templates-and-providers) ·
12. [Users & roles](#users-and-roles) · 13. [Deployment](#deployment) · 14. [Backup](#backup-and-restore) ·
15. [Troubleshooting](#troubleshooting) · 16. [Further documentation](#further-documentation)

---

## Architecture

```
Browser (HTML pages + erp.js / master.js)          API clients / provider feeds
        │  cookie session + CSRF token                    │  Bearer JWT
        ▼                                                 ▼
┌─────────────────────────── FastAPI app (app/main.py) ───────────────────────────┐
│ Security headers · error handlers (no stack traces) · RBAC dependencies          │
│ app/api/*      REST endpoints (auth, generic masters, domain, reports, imports)  │
│ app/services/* business logic — one place per rule                               │
│   masters.py  generic metadata CRUD engine (search/filter/sort/paginate/export,  │
│               validation, child grids, actions, audit) driven by registry.py     │
│   vehicles · renewals · bank · contracts · operations (fuel/toll) · maintenance  │
│   tyres · import_engine + transforms · reports · dashboard · approvals ·         │
│   documents · notifications · rules (configurable business rules)               │
│ app/models/*   SQLAlchemy ORM (90 tables)          app/core/* security, audit,   │
│                                                    utils (DD/MM/YYYY, decimals)  │
└──────────────────────────────────────────┬──────────────────────────────────────┘
                                           ▼
                                  MySQL (InnoDB, utf8mb4)
```

Key principles (spec §2) and where they live:

| Principle | Implementation |
|---|---|
| Configurable, not hard-coded | `lookup_values` for every business dropdown, `business_rules` for tolerances/thresholds/policies, masters for categories, renewal types/rules, positions, layouts, credit/expense types, matching/approval/notification rules, import templates |
| History never silently changed | `vehicle_cost_center_history` (effective-dated), renewal/insurance history, tyre movements, reconciliation history, soft deletes, audit log with old/new values |
| One normalised table per domain | manual entry, Excel import and API feeds all write `bank_transactions`, `fuel_transactions`, `toll_transactions`, … with `source_type/file/sheet/row/import_batch_id` |
| Bank = settlement, not a second expense | `financial_transaction_links`; reports take cost from operational tables + *directly allocated* bank debits only |
| Nothing unmatched is hidden or guessed | UNCLASSIFIED/UNMATCHED statuses, review workbenches, dashboard counters; suggestions stay `AUTO_SUGGESTED` until accepted |
| Atomic financial operations | each API call is one DB transaction (commit at the end, rollback on any error); imports commit per batch |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module map, data model and extension points.

## Prerequisites

* Python **3.11+** (3.12 works)
* MySQL **8.0+** or MariaDB **10.6+** (InnoDB, `utf8mb4`)
* For PDF export: nothing extra (ReportLab is pure Python)
* Optional: Docker 24+ with Compose

## Installation

```bash
git clone <repo-url> trans-erp && cd trans-erp
python3 -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt                           # production deps
pip install -r requirements-dev.txt                       # + pytest/httpx for tests
cp .env.example .env                                      # then edit values
```

## Environment variables

All settings are read from environment variables (prefix `ERP_`) or `.env`. Nothing secret is committed.

| Variable | Default | Purpose |
|---|---|---|
| `ERP_ENV` | development | `production` refuses to start with the development secret key |
| `ERP_DATABASE_URL` | mysql+pymysql://erp:erp_pass@127.0.0.1:3306/ERP_LOGISTICS?charset=utf8mb4 | SQLAlchemy URL |
| `ERP_SECRET_KEY` | dev-only | signs session tokens — **set a long random value** |
| `ERP_ACCESS_TOKEN_MINUTES` | 480 | session lifetime |
| `ERP_COOKIE_SECURE` | false | set `true` behind HTTPS |
| `ERP_TIMEZONE` | Asia/Kolkata | company timezone used for "today", timestamps and expiry maths |
| `ERP_STORAGE_DIR` | ./storage | uploaded documents & import files (opaque keys, never user paths) |
| `ERP_LOG_DIR`, `ERP_LOG_LEVEL` | ./logs, INFO | rotating application log (secrets masked) |
| `ERP_MAX_UPLOAD_MB`, `ERP_ALLOWED_UPLOAD_EXT` | 25, pdf/jpg/png/xlsx/… | upload validation (extension + magic bytes) |
| `ERP_ASYNC_IMPORT_THRESHOLD` | 2000 | batches larger than this commit as a background job with progress |
| `ERP_LOGIN_RATE_LIMIT`, `ERP_LOGIN_RATE_WINDOW_SEC` | 10, 300 | login attempts per IP per window |
| `ERP_ADMIN_PASSWORD` | – | initial `admin` password used by the seed (else `Admin@12345` + forced change) |
| `ERP_SMTP_*` | – | optional e-mail channel for notifications |

Integration credentials (FASTag, fuel-card, bank APIs) are **never stored in the database**: Administration → API
Integrations stores only the *name* of the environment variable that holds the secret.

## MySQL setup

The application database is **`ERP_LOGISTICS`** (utf8mb4). Create a user with rights on it — the migration creates
the database itself if it does not exist yet:

```sql
CREATE USER 'erp_user'@'%' IDENTIFIED BY '<strong password>';
GRANT ALL PRIVILEGES ON `ERP_LOGISTICS`.* TO 'erp_user'@'%';
-- optional test database for the test-suite
GRANT ALL PRIVILEGES ON `ERP_LOGISTICS_TEST`.* TO 'erp_user'@'%';
```

Point the app at it (`.env`): `ERP_DATABASE_URL=mysql+pymysql://erp_user:<password>@<host>:3306/ERP_LOGISTICS?charset=utf8mb4`.
On Linux MySQL database names are case-sensitive — always write `ERP_LOGISTICS` in upper case.

Recommended server settings: `innodb_file_per_table=ON`, `max_allowed_packet=64M`, `default-time-zone='+05:30'`
(or keep UTC — the application stores naive local times in the company timezone consistently).

## Migrations

The migration files that create every table in `ERP_LOGISTICS` are in [`migrations/`](migrations/README.md):

| File | Purpose |
|---|---|
| `migrations/versions/0001_initial_schema.py` | Alembic migration: all 90 tables with primary keys, unique keys, indexes and foreign keys |
| `migrations/sql/0001_initial_schema.sql` | the same schema as plain MySQL SQL, incl. `CREATE DATABASE ERP_LOGISTICS` |
| `migrations/sql/0001_initial_schema_rollback.sql` | plain-SQL rollback (drops the tables — back up first) |

**Option A — Alembic (recommended):**

```bash
alembic upgrade head          # creates database ERP_LOGISTICS if missing + all tables; later: applies new migrations
alembic current               # shows the applied revision (0001)
alembic check                 # verifies models and migrations agree
alembic downgrade base        # drop all tables (development only)
alembic revision --autogenerate -m "describe change"   # after changing app/models/*, then:
scripts/export_sql_migrations.sh                       # refresh the plain-SQL files
```

**Option B — plain SQL (MySQL Workbench / command line, no Python needed for the schema):**

```bash
mysql -u root -p < migrations/sql/0001_initial_schema.sql
```

Either way, then load the reference data with `python -m app.seed`. Both options produce an identical schema and
record revision `0001` in `alembic_version`, so you can switch to Alembic for later upgrades.

## Seed data

```bash
python -m app.seed            # permissions, roles, admin user, lookups, business rules, states/RTOs, units,
                              # fuel types, Truck/Trailer + LPG/Open Body/Container, attributes, cost centers,
                              # tyre positions & layouts, renewal types & rules (incl. 2× PESO for LPG),
                              # credit/expense/transaction types, matching/approval/notification rules,
                              # sample providers and 6 provider import templates
python -m app.seed --demo     # + demo company, branches, bank accounts, 5 vehicles, drivers, renewals,
                              #   insurance, a contract, plazas, fuel stations, 12 tyres
python -m app.sample_files    # regenerate samples/*.xlsx (two layouts each for bank, toll and fuel)
```

The seed is idempotent and everything it creates is ordinary editable master data (nothing is locked).
Default login: **admin / Admin@12345** (or `ERP_ADMIN_PASSWORD`); you are asked to change it at first login.

## Running the application

```bash
uvicorn app.main:app --reload --port 8000               # development
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers   # production (behind nginx)
python -m app.jobs daily                                  # schedule daily (renewal statuses & alerts …)
```

* UI: http://localhost:8000 · API docs (Swagger): http://localhost:8000/docs · ReDoc: /redoc
* There is no separate frontend build: pages are served by the same process (`app/templates`, `app/static`).
  Icons are vendored locally (Tabler webfont) so the UI works on intranet servers; Google Fonts fall back to
  system fonts when offline.

## Running tests

```bash
pytest                                                   # SQLite fallback (fast)
ERP_TEST_DATABASE_URL="mysql+pymysql://erp_user:pw@127.0.0.1/ERP_LOGISTICS_TEST?charset=utf8mb4" pytest   # real MySQL
```

105 tests cover unit (transformations, parsing), service, API, database constraints, imports, allocation,
reconciliation, permissions and regressions — including every mandatory case listed in spec §59 (bank, fuel, toll,
tyres, compliance). Each test runs in a rolled-back transaction. See [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) for
the criterion → test map.

## Importing Excel statements

1. **Imports → Import Wizard** (or `/imports`).
2. Choose the statement type (BANK, TOLL, FASTAG, FUEL, FUEL_CARD, MAINTENANCE, INSURANCE, GPS) and provider.
3. Pick the template/version — its column mapping and transformation rules are shown for review.
4. Upload `.xlsx`/`.csv`, pick the sheet (and the bank account for bank statements).
5. **Parse & Preview**: header validation, per-row transformation, typing, validation, lookups
   (vehicle / plaza / station / fuel type), duplicate detection. Nothing is saved yet.
6. Review tabs (valid / warnings / duplicates / errors / skipped) with original and normalised values and the error
   register (row · column · field · original value · error · suggested correction).
7. **Confirm import** → a batch is created; valid and warning rows are inserted into the normalised tables;
   duplicates and errors are not. Unmatched vehicles/plazas are imported as `*_UNMATCHED` for review — never guessed.
8. Follow the review links: bank rows → Reconciliation Workbench; toll/fuel → unmatched review lists.

Large files (> `ERP_ASYNC_IMPORT_THRESHOLD` rows) commit in the background with progress; a failed import rolls
back completely and the batch shows `FAILED`. Try it with the files in [`samples/`](samples/) after `--demo` seed.

## Configuring templates and providers

* **Imports → Providers**: add the provider with its type (BANK/TOLL/FUEL/INSURANCE/MAINTENANCE/GPS/OTHER).
* **Imports → Import Templates / Builder**: sheet name, header row, data start row, date formats, amount mode
  (`SEPARATE` debit/credit columns, `SIGNED` amount, or amount `WITH_TYPE` DR/CR), footer rows to skip, duplicate key
  fields, version and effective dates; then one line per column: source column letter and/or header text → target
  field, type, required, transformation pipeline, default, lookup, validation.
* **Imports → Value Mappings**: provider-specific translations (e.g. `HSD` → `DIESEL`, a plaza name → plaza id,
  an external vehicle number → internal vehicle). Mappings are also learnt from the review screens.
* Full reference (target fields per type, transformation DSL, lookups, validation rules): [docs/IMPORT_TEMPLATES.md](docs/IMPORT_TEMPLATES.md).

## Users and roles

* **Administration → Users**: create users, set/reset password, assign roles, optionally restrict to branches.
* **Administration → Roles**: tick permissions. Permissions are `module.action`
  (`view/create/edit/delete` plus sensitive ones: `finance.match`, `finance.allocate`, `approval.approve`,
  `fleet.reclassify`, `fleet.odometer_override`, `fuel.override`, `tyre.move`, `tyre.correct`, `tyre.override`,
  `compliance.renew`, `import.run`, `report.export`, `audit.view`, …).
* Seeded roles: ADMIN, FINANCE, OPERATIONS, APPROVER, VIEWER (editable).
* **Administration → Approval Rules**: approval levels for bank allocations/matches above an amount, large job cards,
  odometer overrides, tyre corrections, etc. Approvals are handled in **Dashboard → Approvals** with full history.

## Deployment

Summary (details, nginx/systemd files and a hardening checklist in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)):

1. Provision MySQL, create DB/user; create `/etc/trans-erp.env` from `.env.example` (`ERP_ENV=production`,
   long `ERP_SECRET_KEY`, `ERP_COOKIE_SECURE=true`).
2. `pip install -r requirements.txt`, `alembic upgrade head`, `python -m app.seed`.
3. Run `uvicorn app.main:app --workers 4 --proxy-headers` under systemd behind nginx with TLS.
4. Schedule `python -m app.jobs daily` and the backup script.

Docker: `docker compose up --build` (MySQL 8 + app; migrations and reference seed run on start).

## Backup and restore

* `scripts/backup_mysql.sh /backup/dir` — consistent `mysqldump --single-transaction` of the database plus a tarball
  of uploaded documents, with SHA-256 checksums and retention. Schedule nightly; copy off-server.
* `scripts/restore_mysql.sh dump.sql.gz documents.tar.gz [db]` — restores into an empty database, then run
  `alembic upgrade head`.
* Every screen and report can also be exported to Excel/CSV/PDF.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ERP_SECRET_KEY must be set in production` | set a long random `ERP_SECRET_KEY` |
| `Can't connect to MySQL` / `Access denied` | check `ERP_DATABASE_URL`, grants, firewall; the URL must include `?charset=utf8mb4` |
| `ModuleNotFoundError: _cffi_backend` / cryptography panic | `pip install --upgrade --force-reinstall cryptography cffi` (PyMySQL uses it for caching_sha2 auth) |
| Import: “Header validation failed” | the file does not match the selected template/version — check header row and column letters, or create a new template version |
| Import: rows flagged DUPLICATE | the business key (e.g. provider + transaction id, bank hash incl. balance) already exists — duplicates are never re-inserted |
| “Override required” dialogs | an odometer/fuel/tyre rule was violated; a user with the override permission can proceed with a mandatory reason (audited) |
| Bank allocation rejected | totals must equal the unmatched amount unless `BANK_ALLOW_PARTIAL_ALLOCATION` is enabled; over-allocation is always rejected |
| 403 on save from the browser | the CSRF cookie expired — reload the page / sign in again |
| Unexpected error with “Reference: xxxx” | look for the reference in `logs/erp.log` (full stack trace is logged, never shown to users) |

## Further documentation

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — modules, data model, invariants, extension points
* [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — day-to-day workflows per module
* [docs/IMPORT_TEMPLATES.md](docs/IMPORT_TEMPLATES.md) — template builder & transformation reference
* [docs/API.md](docs/API.md) — authentication and REST endpoints (plus live OpenAPI at `/docs`)
* [docs/ERROR_HANDLING.md](docs/ERROR_HANDLING.md) — error model, logging, recovery
* [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — production deployment, security hardening, operations
* [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) — spec acceptance criteria → implementation → tests
