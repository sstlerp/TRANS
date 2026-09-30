# Database migrations — `ERP_LOGISTICS`

| Path | Contents |
|---|---|
| `versions/0001_initial_schema.py` | Alembic revision `0001`: creates all 90 ERP tables (organisation, fleet, compliance, contracts & finance, import engine, fuel/toll/maintenance, tyres, security/audit/documents/notifications/config) with PKs, unique keys, indexes and FKs. `downgrade()` drops them. |
| `env.py` | Reads `ERP_DATABASE_URL` (default database `ERP_LOGISTICS`). In online mode it runs `CREATE DATABASE IF NOT EXISTS ERP_LOGISTICS CHARACTER SET utf8mb4` before migrating. |
| `versions/0002_toll_plaza_internet_sync.py` | Revision `0002`: `toll_plazas.place` and `state_name`, unique key (`api_source`, `external_plaza_id`), new table `toll_plaza_sync_runs` (toll plaza fetches from the internet — see `docs/INTEGRATIONS.md`). |
| `sql/0001_initial_schema.sql` | Plain MySQL script: `CREATE DATABASE ERP_LOGISTICS`, all tables, and the `alembic_version` row `0001`. |
| `versions/0003_toll_plaza_keep_manual_changes.py` | Revision `0003`: `toll_plazas.details_locked` (user corrections are kept by later internet fetches) and `toll_plaza_sync_runs.locked` (count of such plazas per run). |
| `sql/0002_toll_plaza_internet_sync.sql`, `sql/0003_toll_plaza_keep_manual_changes.sql` | Plain MySQL scripts for revisions `0002` and `0003` (run in order after 0001). |
| `sql/000N_…_rollback.sql` | Plain MySQL rollback of each revision (newest first — 0001 drops all ERP tables). |

## Create the schema

```bash
# A) Alembic
alembic upgrade head
# B) plain SQL — every file in order
mysql -u root -p < migrations/sql/0001_initial_schema.sql
mysql -u root -p < migrations/sql/0002_toll_plaza_internet_sync.sql
mysql -u root -p < migrations/sql/0003_toll_plaza_keep_manual_changes.sql
# then reference data (permissions, roles, admin, lookups, rules, templates …)
python -m app.seed            # add --demo for sample fleet data
```

## Changing the schema

1. Edit the models in `app/models/`.
2. `alembic revision --autogenerate -m "short description"` → review the new file in `versions/`.
3. `alembic upgrade head` on a test copy, run `pytest`, then `alembic check`.
4. `scripts/export_sql_migrations.sh` to refresh the plain-SQL scripts (one upgrade + one rollback file per revision).

Always back up (`scripts/backup_mysql.sh`) before upgrading production.
