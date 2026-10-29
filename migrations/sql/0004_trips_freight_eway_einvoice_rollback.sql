-- =====================================================================================================
-- TRANS ERP — database ERP_LOGISTICS — ROLLBACK of migration 0004
--   trips & freight, e-way bills, driver advances & settlements, GST e-invoice fields
--
-- Generated from migrations/versions/0004_trips_freight_eway_einvoice.py by scripts/export_sql_migrations.py (alembic downgrade 0004:0003 --sql).
-- Roll back newest first; TAKE A BACKUP FIRST (scripts/backup_mysql.sh), e.g.   mysql -u root -p < migrations/sql/0004_trips_freight_eway_einvoice_rollback.sql
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
  IF cur IS NULL OR cur < '0004' THEN
    SELECT CONCAT('Migration 0004 is not applied (database is at ', IFNULL(cur, 'no version'), ') - nothing to roll back.') AS result;
  ELSEIF cur > '0004' THEN
    SET msg = CONCAT('Roll back migration ', cur, ' first (newest first); database is at ', cur, '.');
    SET msg = LEFT(msg, 128);  -- MySQL limit for SIGNAL messages
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = msg;
  ELSE
    ALTER TABLE invoices DROP INDEX uq_invoices_irn;

    ALTER TABLE invoices DROP COLUMN irn_cancel_reason;

    ALTER TABLE invoices DROP COLUMN irn_cancelled_at;

    ALTER TABLE invoices DROP COLUMN signed_qr;

    ALTER TABLE invoices DROP COLUMN irn_ack_date;

    ALTER TABLE invoices DROP COLUMN irn_ack_number;

    ALTER TABLE invoices DROP COLUMN irn;

    ALTER TABLE invoices DROP COLUMN einvoice_status;

    DROP TABLE IF EXISTS trip_expenses;

    DROP TABLE IF EXISTS driver_advances;

    DROP TABLE IF EXISTS eway_bills;

    DROP TABLE IF EXISTS driver_settlements;

    DROP TABLE IF EXISTS trips;

    UPDATE alembic_version SET version_num = '0003' WHERE version_num = '0004';
    SELECT 'Migration 0004 rolled back.' AS result;
  END IF;
END$$
DELIMITER ;
CALL erp_migration_step();
DROP PROCEDURE IF EXISTS erp_migration_step;
