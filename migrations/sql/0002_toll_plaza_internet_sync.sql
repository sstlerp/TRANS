-- =====================================================================================================
-- TRANS ERP — database ERP_LOGISTICS — migration 0002 (upgrade)
--   toll plaza internet sync (toll_plazas.place, state_name, source key; toll_plaza_sync_runs)
--
-- Generated from migrations/versions/0002_toll_plaza_internet_sync.py by scripts/export_sql_migrations.py (alembic upgrade 0001:0002 --sql).
-- Run the files in order, e.g.   mysql -u root -p < migrations/sql/0002_toll_plaza_internet_sync.sql
-- Safe to run again: the alembic_version marker is checked first, so an applied step is skipped and a missing
-- earlier step stops the script before anything is changed. Then `alembic upgrade head` / run_app.bat continue.
-- =====================================================================================================

-- Requires migration 0001.

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
  DECLARE n INT DEFAULT 0;
  SELECT MAX(version_num) INTO cur FROM alembic_version;
  SET n = 0;
  IF cur IS NOT NULL AND cur >= '0002' THEN
    SELECT CONCAT('Migration 0002 is already applied (database is at ', cur, ') - nothing to do.') AS result;
  ELSEIF cur IS NULL OR cur <> '0001' THEN
    SET msg = CONCAT('Migration 0002 needs migration 0001 first; database is at ', IFNULL(cur, 'no version'), '.');
    SET msg = LEFT(msg, 128);  -- MySQL limit for SIGNAL messages
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = msg;
  ELSEIF (SELECT COUNT(*) FROM (SELECT api_source, external_plaza_id FROM toll_plazas WHERE api_source IS NOT NULL AND external_plaza_id IS NOT NULL GROUP BY api_source, external_plaza_id HAVING COUNT(*) > 1) AS dup) > 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Duplicate API Source + External Plaza ID in toll_plazas: make them unique, then run migration 0002 again.';
  ELSE
    CREATE TABLE toll_plaza_sync_runs (
        integration_id BIGINT, 
        source VARCHAR(30) NOT NULL, 
        states VARCHAR(255), 
        dry_run BOOL NOT NULL, 
        status VARCHAR(20) NOT NULL, 
        started_at DATETIME, 
        finished_at DATETIME, 
        states_done INTEGER NOT NULL, 
        states_total INTEGER NOT NULL, 
        fetched INTEGER NOT NULL, 
        created INTEGER NOT NULL, 
        updated INTEGER NOT NULL, 
        unchanged INTEGER NOT NULL, 
        skipped INTEGER NOT NULL, 
        skipped_samples JSON, 
        error_message TEXT, 
        triggered_by BIGINT, 
        id BIGINT NOT NULL AUTO_INCREMENT, 
        CONSTRAINT pk_toll_plaza_sync_runs PRIMARY KEY (id), 
        CONSTRAINT fk_toll_plaza_sync_runs_integration_id_toll_api_configurations FOREIGN KEY(integration_id) REFERENCES toll_api_configurations (id), 
        CONSTRAINT fk_toll_plaza_sync_runs_triggered_by_users FOREIGN KEY(triggered_by) REFERENCES users (id)
    );

    CREATE INDEX ix_toll_plaza_sync_runs_integration_id ON toll_plaza_sync_runs (integration_id);

    CREATE INDEX ix_toll_plaza_sync_runs_started_at ON toll_plaza_sync_runs (started_at);

    CREATE INDEX ix_toll_plaza_sync_runs_status ON toll_plaza_sync_runs (status);

    CREATE INDEX ix_toll_plaza_sync_runs_triggered_by ON toll_plaza_sync_runs (triggered_by);

    ALTER TABLE toll_plazas ADD COLUMN place VARCHAR(150);

    ALTER TABLE toll_plazas ADD COLUMN state_name VARCHAR(100);

    ALTER TABLE toll_plazas ADD CONSTRAINT uq_toll_plaza_source_ext UNIQUE (api_source, external_plaza_id);

    UPDATE alembic_version SET version_num = '0002' WHERE version_num = '0001';
    SELECT 'Migration 0002 applied.' AS result;
  END IF;
END$$
DELIMITER ;
CALL erp_migration_step();
DROP PROCEDURE IF EXISTS erp_migration_step;
