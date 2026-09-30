-- =====================================================================================================
-- TRANS ERP — database ERP_LOGISTICS — migration 0003: toll plaza keep manual changes (toll_plazas.details_locked, toll_plaza_sync_runs.locked)
--
-- Generated from migrations/versions/0003_toll_plaza_keep_manual_changes.py with:  alembic upgrade 0002:0003 --sql   (scripts/export_sql_migrations.sh)
-- Use it instead of Alembic by running the files in order:
--     mysql -u root -p < migrations/sql/0003_toll_plaza_keep_manual_changes.sql
-- Each file also updates the alembic_version marker, so later `alembic upgrade head` runs continue from here.
-- =====================================================================================================

USE `ERP_LOGISTICS`;
SET NAMES utf8mb4;

-- Running upgrade 0002 -> 0003

ALTER TABLE toll_plaza_sync_runs ADD COLUMN locked INTEGER NOT NULL DEFAULT '0';

ALTER TABLE toll_plazas ADD COLUMN details_locked BOOL NOT NULL DEFAULT '0';

UPDATE alembic_version SET version_num='0003' WHERE alembic_version.version_num = '0002';

