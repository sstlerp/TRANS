-- =====================================================================================================
-- TRANS ERP — database ERP_LOGISTICS — migration 0004 (upgrade)
--   trips & freight, e-way bills, driver advances & settlements, GST e-invoice fields
--
-- Generated from migrations/versions/0004_trips_freight_eway_einvoice.py by scripts/export_sql_migrations.py (alembic upgrade 0003:0004 --sql).
-- Run the files in order, e.g.   mysql -u root -p < migrations/sql/0004_trips_freight_eway_einvoice.sql
-- Safe to run again: the alembic_version marker is checked first, so an applied step is skipped and a missing
-- earlier step stops the script before anything is changed. Then `alembic upgrade head` / run_app.bat continue.
-- =====================================================================================================

-- Requires migration 0003.

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
  IF cur IS NOT NULL AND cur >= '0004' THEN
    SELECT CONCAT('Migration 0004 is already applied (database is at ', cur, ') - nothing to do.') AS result;
  ELSEIF cur IS NULL OR cur <> '0003' THEN
    SET msg = CONCAT('Migration 0004 needs migration 0003 first; database is at ', IFNULL(cur, 'no version'), '.');
    SET msg = LEFT(msg, 128);  -- MySQL limit for SIGNAL messages
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = msg;
  ELSE
    CREATE TABLE trips (
        trip_number VARCHAR(30) NOT NULL, 
        trip_date DATE NOT NULL, 
        lr_number VARCHAR(40), 
        lr_date DATE, 
        customer_id BIGINT, 
        contract_id BIGINT, 
        vehicle_id BIGINT NOT NULL, 
        driver_id BIGINT, 
        cost_center_id BIGINT, 
        origin VARCHAR(150) NOT NULL, 
        destination VARCHAR(150) NOT NULL, 
        from_pincode VARCHAR(6), 
        to_pincode VARCHAR(6), 
        from_state_id BIGINT, 
        to_state_id BIGINT, 
        route_via VARCHAR(255), 
        planned_km NUMERIC(18, 3), 
        consignor_name VARCHAR(200), 
        consignor_gstin VARCHAR(15), 
        consignor_address VARCHAR(500), 
        consignee_name VARCHAR(200), 
        consignee_gstin VARCHAR(15), 
        consignee_address VARCHAR(500), 
        goods_description VARCHAR(255), 
        hsn_code VARCHAR(10), 
        packing_type VARCHAR(30), 
        packages INTEGER, 
        weight_tonnes NUMERIC(18, 3), 
        goods_value NUMERIC(18, 2), 
        goods_invoice_number VARCHAR(60), 
        goods_invoice_date DATE, 
        freight_payment VARCHAR(10) NOT NULL, 
        freight_basis VARCHAR(15) NOT NULL, 
        freight_rate NUMERIC(18, 4), 
        freight_amount NUMERIC(18, 2) NOT NULL, 
        loading_charges NUMERIC(18, 2) NOT NULL, 
        unloading_charges NUMERIC(18, 2) NOT NULL, 
        detention_charges NUMERIC(18, 2) NOT NULL, 
        other_charges NUMERIC(18, 2) NOT NULL, 
        total_freight NUMERIC(18, 2) NOT NULL, 
        advance_received NUMERIC(18, 2) NOT NULL, 
        balance_freight NUMERIC(18, 2) NOT NULL, 
        scheduled_start DATETIME, 
        actual_start DATETIME, 
        actual_end DATETIME, 
        start_odometer NUMERIC(18, 3), 
        end_odometer NUMERIC(18, 3), 
        actual_km NUMERIC(18, 3), 
        status VARCHAR(20) NOT NULL, 
        delivered_packages INTEGER, 
        shortage_damage VARCHAR(255), 
        pod_received_date DATE, 
        pod_remarks VARCHAR(255), 
        invoice_id BIGINT, 
        cancel_reason VARCHAR(255), 
        remarks TEXT, 
        id BIGINT NOT NULL AUTO_INCREMENT, 
        created_at DATETIME NOT NULL, 
        updated_at DATETIME NOT NULL, 
        created_by BIGINT, 
        updated_by BIGINT, 
        CONSTRAINT pk_trips PRIMARY KEY (id), 
        CONSTRAINT fk_trips_contract_id_contracts FOREIGN KEY(contract_id) REFERENCES contracts (id), 
        CONSTRAINT fk_trips_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
        CONSTRAINT fk_trips_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id), 
        CONSTRAINT fk_trips_driver_id_drivers FOREIGN KEY(driver_id) REFERENCES drivers (id), 
        CONSTRAINT fk_trips_from_state_id_states FOREIGN KEY(from_state_id) REFERENCES states (id), 
        CONSTRAINT fk_trips_invoice_id_invoices FOREIGN KEY(invoice_id) REFERENCES invoices (id), 
        CONSTRAINT fk_trips_to_state_id_states FOREIGN KEY(to_state_id) REFERENCES states (id), 
        CONSTRAINT fk_trips_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
        CONSTRAINT uq_trips_lr_number UNIQUE (lr_number), 
        CONSTRAINT uq_trips_trip_number UNIQUE (trip_number)
    );

    CREATE INDEX ix_trips_contract_id ON trips (contract_id);

    CREATE INDEX ix_trips_cost_center_id ON trips (cost_center_id);

    CREATE INDEX ix_trips_customer_id ON trips (customer_id);

    CREATE INDEX ix_trips_driver_status ON trips (driver_id, status);

    CREATE INDEX ix_trips_invoice_id ON trips (invoice_id);

    CREATE INDEX ix_trips_status ON trips (status);

    CREATE INDEX ix_trips_trip_date ON trips (trip_date);

    CREATE INDEX ix_trips_vehicle_start ON trips (vehicle_id, actual_start);

    CREATE TABLE driver_settlements (
        settlement_number VARCHAR(30) NOT NULL, 
        driver_id BIGINT NOT NULL, 
        trip_id BIGINT, 
        settlement_date DATE NOT NULL, 
        period_from DATE, 
        period_to DATE, 
        trip_days NUMERIC(18, 3), 
        allowance_per_day NUMERIC(18, 2), 
        allowance_amount NUMERIC(18, 2) NOT NULL, 
        other_earnings NUMERIC(18, 2) NOT NULL, 
        deductions NUMERIC(18, 2) NOT NULL, 
        deduction_remarks VARCHAR(255), 
        total_expenses NUMERIC(18, 2) NOT NULL, 
        total_advances NUMERIC(18, 2) NOT NULL, 
        net_payable NUMERIC(18, 2) NOT NULL, 
        settle_amount NUMERIC(18, 2) NOT NULL, 
        cost_center_id BIGINT, 
        status VARCHAR(15) NOT NULL, 
        approved_by BIGINT, 
        approved_at DATETIME, 
        paid_date DATE, 
        payment_mode VARCHAR(20), 
        payment_reference VARCHAR(60), 
        remarks TEXT, 
        id BIGINT NOT NULL AUTO_INCREMENT, 
        created_at DATETIME NOT NULL, 
        updated_at DATETIME NOT NULL, 
        created_by BIGINT, 
        updated_by BIGINT, 
        CONSTRAINT pk_driver_settlements PRIMARY KEY (id), 
        CONSTRAINT fk_driver_settlements_approved_by_users FOREIGN KEY(approved_by) REFERENCES users (id), 
        CONSTRAINT fk_driver_settlements_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
        CONSTRAINT fk_driver_settlements_driver_id_drivers FOREIGN KEY(driver_id) REFERENCES drivers (id), 
        CONSTRAINT fk_driver_settlements_trip_id_trips FOREIGN KEY(trip_id) REFERENCES trips (id), 
        CONSTRAINT uq_driver_settlements_settlement_number UNIQUE (settlement_number)
    );

    CREATE INDEX ix_driver_settlements_cost_center_id ON driver_settlements (cost_center_id);

    CREATE INDEX ix_driver_settlements_driver_id ON driver_settlements (driver_id);

    CREATE INDEX ix_driver_settlements_settlement_date ON driver_settlements (settlement_date);

    CREATE INDEX ix_driver_settlements_trip_id ON driver_settlements (trip_id);

    CREATE TABLE eway_bills (
        ewb_number VARCHAR(12) NOT NULL, 
        trip_id BIGINT, 
        vehicle_id BIGINT, 
        generated_at DATETIME NOT NULL, 
        valid_until DATETIME, 
        distance_km INTEGER, 
        is_odc BOOL NOT NULL, 
        doc_type VARCHAR(10) NOT NULL, 
        doc_number VARCHAR(60), 
        doc_date DATE, 
        goods_value NUMERIC(18, 2), 
        from_place VARCHAR(150), 
        to_place VARCHAR(150), 
        transporter_gstin VARCHAR(15), 
        status VARCHAR(15) NOT NULL, 
        extension_count INTEGER NOT NULL, 
        last_extension_reason VARCHAR(255), 
        cancel_reason VARCHAR(255), 
        closed_at DATETIME, 
        remarks TEXT, 
        id BIGINT NOT NULL AUTO_INCREMENT, 
        created_at DATETIME NOT NULL, 
        updated_at DATETIME NOT NULL, 
        created_by BIGINT, 
        updated_by BIGINT, 
        CONSTRAINT pk_eway_bills PRIMARY KEY (id), 
        CONSTRAINT fk_eway_bills_trip_id_trips FOREIGN KEY(trip_id) REFERENCES trips (id), 
        CONSTRAINT fk_eway_bills_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
        CONSTRAINT uq_eway_bills_ewb_number UNIQUE (ewb_number)
    );

    CREATE INDEX ix_eway_bills_trip_id ON eway_bills (trip_id);

    CREATE INDEX ix_eway_bills_vehicle_id ON eway_bills (vehicle_id);

    CREATE INDEX ix_eway_status_valid ON eway_bills (status, valid_until);

    CREATE TABLE driver_advances (
        advance_number VARCHAR(30) NOT NULL, 
        driver_id BIGINT NOT NULL, 
        trip_id BIGINT, 
        advance_date DATE NOT NULL, 
        amount NUMERIC(18, 2) NOT NULL, 
        payment_mode VARCHAR(20), 
        reference VARCHAR(60), 
        purpose VARCHAR(255), 
        status VARCHAR(15) NOT NULL, 
        settlement_id BIGINT, 
        remarks TEXT, 
        id BIGINT NOT NULL AUTO_INCREMENT, 
        created_at DATETIME NOT NULL, 
        updated_at DATETIME NOT NULL, 
        created_by BIGINT, 
        updated_by BIGINT, 
        CONSTRAINT pk_driver_advances PRIMARY KEY (id), 
        CONSTRAINT fk_driver_advances_driver_id_drivers FOREIGN KEY(driver_id) REFERENCES drivers (id), 
        CONSTRAINT fk_driver_advances_settlement_id_driver_settlements FOREIGN KEY(settlement_id) REFERENCES driver_settlements (id), 
        CONSTRAINT fk_driver_advances_trip_id_trips FOREIGN KEY(trip_id) REFERENCES trips (id), 
        CONSTRAINT uq_driver_advances_advance_number UNIQUE (advance_number)
    );

    CREATE INDEX ix_driver_adv_driver_status ON driver_advances (driver_id, status);

    CREATE INDEX ix_driver_advances_advance_date ON driver_advances (advance_date);

    CREATE INDEX ix_driver_advances_settlement_id ON driver_advances (settlement_id);

    CREATE INDEX ix_driver_advances_trip_id ON driver_advances (trip_id);

    CREATE TABLE trip_expenses (
        trip_id BIGINT NOT NULL, 
        expense_date DATE, 
        expense_head VARCHAR(30) NOT NULL, 
        amount NUMERIC(18, 2) NOT NULL, 
        paid_by VARCHAR(10) NOT NULL, 
        bill_number VARCHAR(50), 
        remarks VARCHAR(255), 
        settlement_id BIGINT, 
        id BIGINT NOT NULL AUTO_INCREMENT, 
        CONSTRAINT pk_trip_expenses PRIMARY KEY (id), 
        CONSTRAINT fk_trip_expenses_settlement_id_driver_settlements FOREIGN KEY(settlement_id) REFERENCES driver_settlements (id), 
        CONSTRAINT fk_trip_expenses_trip_id_trips FOREIGN KEY(trip_id) REFERENCES trips (id) ON DELETE CASCADE
    );

    CREATE INDEX ix_trip_expenses_settlement_id ON trip_expenses (settlement_id);

    CREATE INDEX ix_trip_expenses_trip_id ON trip_expenses (trip_id);

    ALTER TABLE invoices ADD COLUMN einvoice_status VARCHAR(15) NOT NULL DEFAULT 'NOT_APPLICABLE';

    ALTER TABLE invoices ADD COLUMN irn VARCHAR(64);

    ALTER TABLE invoices ADD COLUMN irn_ack_number VARCHAR(30);

    ALTER TABLE invoices ADD COLUMN irn_ack_date DATETIME;

    ALTER TABLE invoices ADD COLUMN signed_qr TEXT;

    ALTER TABLE invoices ADD COLUMN irn_cancelled_at DATETIME;

    ALTER TABLE invoices ADD COLUMN irn_cancel_reason VARCHAR(255);

    ALTER TABLE invoices ADD CONSTRAINT uq_invoices_irn UNIQUE (irn);

    UPDATE alembic_version SET version_num = '0004' WHERE version_num = '0003';
    SELECT 'Migration 0004 applied.' AS result;
  END IF;
END$$
DELIMITER ;
CALL erp_migration_step();
DROP PROCEDURE IF EXISTS erp_migration_step;
