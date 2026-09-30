-- TRANS ERP — database ERP_LOGISTICS — rollback of migration 0003 (toll plaza keep manual changes (toll_plazas.details_locked, toll_plaza_sync_runs.locked))
-- Generated with: alembic downgrade 0003:0002 --sql      Take a backup first (scripts/backup_mysql.sh).
USE `ERP_LOGISTICS`;

-- Running downgrade 0003 -> 0002

ALTER TABLE toll_plazas DROP COLUMN details_locked;

ALTER TABLE toll_plaza_sync_runs DROP COLUMN locked;

UPDATE alembic_version SET version_num='0002' WHERE alembic_version.version_num = '0003';

