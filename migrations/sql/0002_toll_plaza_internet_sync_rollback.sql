-- TRANS ERP — database ERP_LOGISTICS — rollback of migration 0002 (toll plaza internet sync (toll_plazas.place, state_name, source key; toll_plaza_sync_runs))
-- Generated with: alembic downgrade 0002:0001 --sql      Take a backup first (scripts/backup_mysql.sh).
USE `ERP_LOGISTICS`;

-- Running downgrade 0002 -> 0001

ALTER TABLE toll_plazas DROP INDEX uq_toll_plaza_source_ext;

ALTER TABLE toll_plazas DROP COLUMN state_name;

ALTER TABLE toll_plazas DROP COLUMN place;

DROP TABLE IF EXISTS toll_plaza_sync_runs;

UPDATE alembic_version SET version_num='0001' WHERE alembic_version.version_num = '0002';

