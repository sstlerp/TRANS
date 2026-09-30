-- =====================================================================================================
-- TRANS ERP — database ERP_LOGISTICS — migration 0002: toll plaza internet sync (toll_plazas.place, state_name, source key; toll_plaza_sync_runs)
--
-- Generated from migrations/versions/0002_toll_plaza_internet_sync.py with:  alembic upgrade 0001:0002 --sql   (scripts/export_sql_migrations.sh)
-- Use it instead of Alembic by running the files in order:
--     mysql -u root -p < migrations/sql/0002_toll_plaza_internet_sync.sql
-- Each file also updates the alembic_version marker, so later `alembic upgrade head` runs continue from here.
-- =====================================================================================================

USE `ERP_LOGISTICS`;
SET NAMES utf8mb4;

-- Running upgrade 0001 -> 0002

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

UPDATE alembic_version SET version_num='0002' WHERE alembic_version.version_num = '0001';

