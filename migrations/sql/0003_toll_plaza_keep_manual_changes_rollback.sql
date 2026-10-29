-- =====================================================================================================
-- TRANS ERP — database ERP_LOGISTICS — ROLLBACK of migration 0003
--   toll plaza keep manual changes (toll_plazas.details_locked, toll_plaza_sync_runs.locked)
--
-- Generated from migrations/versions/0003_toll_plaza_keep_manual_changes.py by scripts/export_sql_migrations.py (alembic downgrade 0003:0002 --sql).
-- Roll back newest first; TAKE A BACKUP FIRST (scripts/backup_mysql.sh), e.g.   mysql -u root -p < migrations/sql/0003_toll_plaza_keep_manual_changes_rollback.sql
-- Safe to run again: the alembic_version marker is checked first, so an applied step is skipped and a missing
-- earlier step stops the script before anything is changed. Then `alembic upgrade head` / run_app.bat continue.
-- =====================================================================================================

USE `ERP_LOGISTICS`;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

DROP PROCEDURE IF EXISTS erp_migration_step;
DELIMITER $$
CREATE PROCEDURE erp_migration_step()
BEGIN
  DECLARE cur VARCHAR(32) DEFAULT NULL;
  DECLARE msg VARCHAR(255);
  SELECT MAX(version_num) INTO cur FROM alembic_version;
  IF cur IS NULL OR cur < '0003' THEN
    SELECT CONCAT('Migration 0003 is not applied (database is at ', IFNULL(cur, 'no version'), ') - nothing to roll back.') AS result;
  ELSEIF cur > '0003' THEN
    SET msg = CONCAT('Roll back migration ', cur, ' first (newest first); database is at ', cur, '.');
    SET msg = LEFT(msg, 128);  -- MySQL limit for SIGNAL messages
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = msg;
  ELSE
    ALTER TABLE toll_plazas DROP COLUMN details_locked;

    ALTER TABLE toll_plaza_sync_runs DROP COLUMN locked;

    UPDATE alembic_version SET version_num = '0002' WHERE version_num = '0003';
    SELECT 'Migration 0003 rolled back.' AS result;
  END IF;
END$$
DELIMITER ;
CALL erp_migration_step();
DROP PROCEDURE IF EXISTS erp_migration_step;
