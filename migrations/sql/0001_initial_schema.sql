-- =====================================================================================================
-- TRANS ERP — database ERP_LOGISTICS — migration 0001: initial schema — all ERP tables (organisation, fleet, compliance, finance, imports,
--
-- Generated from migrations/versions/0001_initial_schema.py with:  alembic upgrade 0001 --sql   (scripts/export_sql_migrations.sh)
-- Use it instead of Alembic by running the files in order:
--     mysql -u root -p < migrations/sql/0001_initial_schema.sql
-- Each file also updates the alembic_version marker, so later `alembic upgrade head` runs continue from here.
-- This first file creates the database and every ERP table. Then load reference data with:  python -m app.seed
-- =====================================================================================================

CREATE DATABASE IF NOT EXISTS `ERP_LOGISTICS` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `ERP_LOGISTICS`;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001

CREATE TABLE approval_rules (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    action_type VARCHAR(40) NOT NULL, 
    min_amount NUMERIC(18, 2), 
    levels INTEGER NOT NULL, 
    approver_permission VARCHAR(80) NOT NULL, 
    allow_self_approval BOOL NOT NULL, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_approval_rules PRIMARY KEY (id), 
    CONSTRAINT uq_approval_rules_code UNIQUE (code)
);

CREATE INDEX ix_approval_rules_action_type ON approval_rules (action_type);

CREATE INDEX ix_approval_rules_is_active ON approval_rules (is_active);

CREATE TABLE audit_logs (
    user_id BIGINT, 
    username VARCHAR(50), 
    action VARCHAR(30) NOT NULL, 
    entity_type VARCHAR(60) NOT NULL, 
    entity_id VARCHAR(40), 
    old_values JSON, 
    new_values JSON, 
    reason VARCHAR(500), 
    ip_address VARCHAR(45), 
    user_agent VARCHAR(255), 
    created_at DATETIME NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_audit_logs PRIMARY KEY (id)
);

CREATE INDEX ix_audit_at ON audit_logs (created_at);

CREATE INDEX ix_audit_entity ON audit_logs (entity_type, entity_id);

CREATE INDEX ix_audit_logs_action ON audit_logs (action);

CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id);

CREATE TABLE background_jobs (
    job_type VARCHAR(40) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    progress INTEGER NOT NULL, 
    params JSON, 
    result JSON, 
    error TEXT, 
    started_at DATETIME, 
    finished_at DATETIME, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_background_jobs PRIMARY KEY (id)
);

CREATE INDEX ix_background_jobs_job_type ON background_jobs (job_type);

CREATE INDEX ix_background_jobs_status ON background_jobs (status);

CREATE TABLE business_rules (
    rule_key VARCHAR(80) NOT NULL, 
    module VARCHAR(30) NOT NULL, 
    value VARCHAR(500) NOT NULL, 
    value_type VARCHAR(10) NOT NULL, 
    choices VARCHAR(255), 
    description VARCHAR(500), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_business_rules PRIMARY KEY (id), 
    CONSTRAINT uq_business_rules_rule_key UNIQUE (rule_key)
);

CREATE INDEX ix_business_rules_is_active ON business_rules (is_active);

CREATE INDEX ix_business_rules_module ON business_rules (module);

CREATE TABLE cost_categories (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    applies_to VARCHAR(20) NOT NULL, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_cost_categories PRIMARY KEY (id), 
    CONSTRAINT uq_cost_categories_code UNIQUE (code), 
    CONSTRAINT uq_cost_categories_name UNIQUE (name)
);

CREATE INDEX ix_cost_categories_is_active ON cost_categories (is_active);

CREATE TABLE credit_types (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    accounting_treatment VARCHAR(30) NOT NULL, 
    default_link_type VARCHAR(30), 
    requires_link BOOL NOT NULL, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_credit_types PRIMARY KEY (id), 
    CONSTRAINT uq_credit_types_code UNIQUE (code)
);

CREATE INDEX ix_credit_types_is_active ON credit_types (is_active);

CREATE TABLE documents (
    document_type VARCHAR(40) NOT NULL, 
    entity_type VARCHAR(60) NOT NULL, 
    entity_id BIGINT NOT NULL, 
    file_name VARCHAR(255) NOT NULL, 
    storage_key VARCHAR(255) NOT NULL, 
    content_type VARCHAR(100), 
    size_bytes INTEGER NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    version INTEGER NOT NULL, 
    previous_document_id BIGINT, 
    uploaded_by BIGINT, 
    uploaded_at DATETIME NOT NULL, 
    remarks VARCHAR(500), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_documents PRIMARY KEY (id), 
    CONSTRAINT fk_documents_previous_document_id_documents FOREIGN KEY(previous_document_id) REFERENCES documents (id), 
    CONSTRAINT uq_documents_storage_key UNIQUE (storage_key)
);

CREATE INDEX ix_doc_entity ON documents (entity_type, entity_id);

CREATE INDEX ix_documents_is_active ON documents (is_active);

CREATE INDEX ix_documents_previous_document_id ON documents (previous_document_id);

CREATE TABLE expense_types (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    report_group VARCHAR(30) NOT NULL, 
    is_operating BOOL NOT NULL, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_expense_types PRIMARY KEY (id), 
    CONSTRAINT uq_expense_types_code UNIQUE (code)
);

CREATE INDEX ix_expense_types_is_active ON expense_types (is_active);

CREATE INDEX ix_expense_types_report_group ON expense_types (report_group);

CREATE TABLE financial_transaction_links (
    source_transaction_type VARCHAR(30) NOT NULL, 
    source_transaction_id BIGINT NOT NULL, 
    target_transaction_type VARCHAR(30) NOT NULL, 
    target_transaction_id BIGINT NOT NULL, 
    linked_amount NUMERIC(18, 2) NOT NULL, 
    link_type VARCHAR(30) NOT NULL, 
    match_status VARCHAR(20) NOT NULL, 
    matching_method VARCHAR(20) NOT NULL, 
    match_score INTEGER, 
    matched_by BIGINT, 
    matched_at DATETIME, 
    approved_by BIGINT, 
    approved_at DATETIME, 
    remarks VARCHAR(500), 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_financial_transaction_links PRIMARY KEY (id)
);

CREATE INDEX ix_financial_transaction_links_link_type ON financial_transaction_links (link_type);

CREATE INDEX ix_financial_transaction_links_match_status ON financial_transaction_links (match_status);

CREATE INDEX ix_ftl_source ON financial_transaction_links (source_transaction_type, source_transaction_id);

CREATE INDEX ix_ftl_target ON financial_transaction_links (target_transaction_type, target_transaction_id);

CREATE TABLE lookup_values (
    category VARCHAR(50) NOT NULL, 
    code VARCHAR(50) NOT NULL, 
    label VARCHAR(150) NOT NULL, 
    sort_order INTEGER NOT NULL, 
    description VARCHAR(255), 
    is_system BOOL NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_lookup_values PRIMARY KEY (id), 
    CONSTRAINT uq_lookup_values_category_code UNIQUE (category, code)
);

CREATE INDEX ix_lookup_values_category ON lookup_values (category);

CREATE INDEX ix_lookup_values_is_active ON lookup_values (is_active);

CREATE TABLE maintenance_types (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    category VARCHAR(30) NOT NULL, 
    interval_km INTEGER, 
    interval_days INTEGER, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_maintenance_types PRIMARY KEY (id), 
    CONSTRAINT uq_maintenance_types_code UNIQUE (code)
);

CREATE INDEX ix_maintenance_types_is_active ON maintenance_types (is_active);

CREATE TABLE matching_rules (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    link_type VARCHAR(30) NOT NULL, 
    priority INTEGER NOT NULL, 
    date_tolerance_days INTEGER NOT NULL, 
    amount_tolerance NUMERIC(18, 2) NOT NULL, 
    match_on_amount BOOL NOT NULL, 
    match_on_utr BOOL NOT NULL, 
    match_on_reference BOOL NOT NULL, 
    match_on_party_name BOOL NOT NULL, 
    narration_keywords VARCHAR(500), 
    min_score INTEGER NOT NULL, 
    auto_approve BOOL NOT NULL, 
    auto_approve_min_score INTEGER NOT NULL, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_matching_rules PRIMARY KEY (id), 
    CONSTRAINT uq_matching_rules_code UNIQUE (code)
);

CREATE INDEX ix_matching_rules_is_active ON matching_rules (is_active);

CREATE INDEX ix_matching_rules_link_type ON matching_rules (link_type);

CREATE TABLE notifications (
    event_type VARCHAR(40) NOT NULL, 
    severity VARCHAR(10) NOT NULL, 
    title VARCHAR(200) NOT NULL, 
    message TEXT, 
    entity_type VARCHAR(60), 
    entity_id BIGINT, 
    link_url VARCHAR(255), 
    user_id BIGINT, 
    role_id BIGINT, 
    dedupe_key VARCHAR(150), 
    channels_sent VARCHAR(100), 
    is_read BOOL NOT NULL, 
    read_by BIGINT, 
    read_at DATETIME, 
    created_at DATETIME NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_notifications PRIMARY KEY (id), 
    CONSTRAINT uq_notifications_dedupe_key UNIQUE (dedupe_key)
);

CREATE INDEX ix_notif_read ON notifications (is_read, created_at);

CREATE INDEX ix_notifications_event_type ON notifications (event_type);

CREATE INDEX ix_notifications_user_id ON notifications (user_id);

CREATE TABLE permissions (
    code VARCHAR(80) NOT NULL, 
    module VARCHAR(40) NOT NULL, 
    action VARCHAR(30) NOT NULL, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_permissions PRIMARY KEY (id), 
    CONSTRAINT uq_permissions_code UNIQUE (code)
);

CREATE INDEX ix_permissions_module ON permissions (module);

CREATE TABLE roles (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_roles PRIMARY KEY (id), 
    CONSTRAINT uq_roles_code UNIQUE (code)
);

CREATE INDEX ix_roles_is_active ON roles (is_active);

CREATE TABLE states (
    code VARCHAR(5) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    gst_code VARCHAR(2), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_states PRIMARY KEY (id), 
    CONSTRAINT uq_states_code UNIQUE (code), 
    CONSTRAINT uq_states_name UNIQUE (name)
);

CREATE INDEX ix_states_is_active ON states (is_active);

CREATE TABLE transaction_types (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    module VARCHAR(30) NOT NULL, 
    direction VARCHAR(10), 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_transaction_types PRIMARY KEY (id), 
    CONSTRAINT uq_transaction_types_code UNIQUE (code)
);

CREATE INDEX ix_transaction_types_is_active ON transaction_types (is_active);

CREATE TABLE tyre_layouts (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    axle_count INTEGER, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_tyre_layouts PRIMARY KEY (id), 
    CONSTRAINT uq_tyre_layouts_code UNIQUE (code)
);

CREATE INDEX ix_tyre_layouts_is_active ON tyre_layouts (is_active);

CREATE TABLE tyre_positions (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    axle_number INTEGER, 
    side VARCHAR(10), 
    placement VARCHAR(10), 
    position_type VARCHAR(20), 
    display_order INTEGER NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_tyre_positions PRIMARY KEY (id), 
    CONSTRAINT uq_tyre_positions_code UNIQUE (code)
);

CREATE INDEX ix_tyre_positions_is_active ON tyre_positions (is_active);

CREATE TABLE units (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(60) NOT NULL, 
    unit_type VARCHAR(30) NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_units PRIMARY KEY (id), 
    CONSTRAINT uq_units_code UNIQUE (code)
);

CREATE INDEX ix_units_is_active ON units (is_active);

CREATE TABLE users (
    username VARCHAR(50) NOT NULL, 
    full_name VARCHAR(150) NOT NULL, 
    email VARCHAR(150), 
    mobile VARCHAR(15), 
    password_hash VARCHAR(255) NOT NULL, 
    is_superuser BOOL NOT NULL, 
    all_branches BOOL NOT NULL, 
    must_change_password BOOL NOT NULL, 
    failed_attempts INTEGER NOT NULL, 
    locked_until DATETIME, 
    last_login_at DATETIME, 
    token_version INTEGER NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_users PRIMARY KEY (id), 
    CONSTRAINT uq_users_email UNIQUE (email), 
    CONSTRAINT uq_users_username UNIQUE (username)
);

CREATE INDEX ix_users_is_active ON users (is_active);

CREATE TABLE approval_requests (
    action_type VARCHAR(40) NOT NULL, 
    entity_type VARCHAR(40) NOT NULL, 
    entity_id BIGINT, 
    amount NUMERIC(18, 2), 
    payload JSON, 
    summary VARCHAR(500), 
    status VARCHAR(20) NOT NULL, 
    current_level INTEGER NOT NULL, 
    required_levels INTEGER NOT NULL, 
    rule_id BIGINT, 
    requested_by BIGINT, 
    remarks VARCHAR(500), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_approval_requests PRIMARY KEY (id), 
    CONSTRAINT fk_approval_requests_rule_id_approval_rules FOREIGN KEY(rule_id) REFERENCES approval_rules (id)
);

CREATE INDEX ix_approval_requests_action_type ON approval_requests (action_type);

CREATE INDEX ix_approval_requests_rule_id ON approval_requests (rule_id);

CREATE INDEX ix_approval_requests_status ON approval_requests (status);

CREATE TABLE companies (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    legal_name VARCHAR(255), 
    gstin VARCHAR(15), 
    pan VARCHAR(10), 
    address TEXT, 
    state_id BIGINT, 
    phone VARCHAR(20), 
    email VARCHAR(150), 
    timezone VARCHAR(50) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_companies PRIMARY KEY (id), 
    CONSTRAINT fk_companies_state_id_states FOREIGN KEY(state_id) REFERENCES states (id), 
    CONSTRAINT uq_companies_code UNIQUE (code)
);

CREATE INDEX ix_companies_is_active ON companies (is_active);

CREATE INDEX ix_companies_state_id ON companies (state_id);

CREATE TABLE customers (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    gstin VARCHAR(15), 
    pan VARCHAR(10), 
    contact_person VARCHAR(100), 
    phone VARCHAR(20), 
    email VARCHAR(150), 
    billing_address TEXT, 
    state_id BIGINT, 
    credit_days INTEGER, 
    credit_limit NUMERIC(18, 2), 
    match_keywords VARCHAR(255), 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_customers PRIMARY KEY (id), 
    CONSTRAINT fk_customers_state_id_states FOREIGN KEY(state_id) REFERENCES states (id), 
    CONSTRAINT uq_customers_code UNIQUE (code)
);

CREATE INDEX ix_customers_is_active ON customers (is_active);

CREATE INDEX ix_customers_name ON customers (name);

CREATE INDEX ix_customers_state_id ON customers (state_id);

CREATE TABLE districts (
    state_id BIGINT NOT NULL, 
    code VARCHAR(20), 
    name VARCHAR(100) NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_districts PRIMARY KEY (id), 
    CONSTRAINT fk_districts_state_id_states FOREIGN KEY(state_id) REFERENCES states (id), 
    CONSTRAINT uq_districts_state_id_name UNIQUE (state_id, name)
);

CREATE INDEX ix_districts_is_active ON districts (is_active);

CREATE INDEX ix_districts_state_id ON districts (state_id);

CREATE TABLE document_links (
    document_id BIGINT NOT NULL, 
    entity_type VARCHAR(60) NOT NULL, 
    entity_id BIGINT NOT NULL, 
    created_at DATETIME NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_document_links PRIMARY KEY (id), 
    CONSTRAINT fk_document_links_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE INDEX ix_doclink_entity ON document_links (entity_type, entity_id);

CREATE INDEX ix_document_links_document_id ON document_links (document_id);

CREATE TABLE fuel_types (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(60) NOT NULL, 
    default_unit_id BIGINT, 
    efficiency_label VARCHAR(20), 
    min_efficiency NUMERIC(10, 3), 
    max_efficiency NUMERIC(10, 3), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_fuel_types PRIMARY KEY (id), 
    CONSTRAINT fk_fuel_types_default_unit_id_units FOREIGN KEY(default_unit_id) REFERENCES units (id), 
    CONSTRAINT uq_fuel_types_code UNIQUE (code), 
    CONSTRAINT uq_fuel_types_name UNIQUE (name)
);

CREATE INDEX ix_fuel_types_default_unit_id ON fuel_types (default_unit_id);

CREATE INDEX ix_fuel_types_is_active ON fuel_types (is_active);

CREATE TABLE notification_rules (
    code VARCHAR(40) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    event_type VARCHAR(40) NOT NULL, 
    channels VARCHAR(100) NOT NULL, 
    days_before VARCHAR(100), 
    severity VARCHAR(10) NOT NULL, 
    recipient_role_id BIGINT, 
    recipient_emails VARCHAR(500), 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_notification_rules PRIMARY KEY (id), 
    CONSTRAINT fk_notification_rules_recipient_role_id_roles FOREIGN KEY(recipient_role_id) REFERENCES roles (id), 
    CONSTRAINT uq_notification_rules_code UNIQUE (code)
);

CREATE INDEX ix_notification_rules_event_type ON notification_rules (event_type);

CREATE INDEX ix_notification_rules_is_active ON notification_rules (is_active);

CREATE INDEX ix_notification_rules_recipient_role_id ON notification_rules (recipient_role_id);

CREATE TABLE renewal_types (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    applies_to VARCHAR(20) NOT NULL, 
    category VARCHAR(30) NOT NULL, 
    expense_type_id BIGINT, 
    requires_document BOOL NOT NULL, 
    allows_multiple BOOL NOT NULL, 
    default_validity_months INTEGER, 
    default_reminder_days VARCHAR(100), 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_renewal_types PRIMARY KEY (id), 
    CONSTRAINT fk_renewal_types_expense_type_id_expense_types FOREIGN KEY(expense_type_id) REFERENCES expense_types (id), 
    CONSTRAINT uq_renewal_types_code UNIQUE (code)
);

CREATE INDEX ix_renewal_types_category ON renewal_types (category);

CREATE INDEX ix_renewal_types_expense_type_id ON renewal_types (expense_type_id);

CREATE INDEX ix_renewal_types_is_active ON renewal_types (is_active);

CREATE TABLE role_permissions (
    role_id BIGINT NOT NULL, 
    permission_id BIGINT NOT NULL, 
    CONSTRAINT pk_role_permissions PRIMARY KEY (role_id, permission_id), 
    CONSTRAINT fk_role_permissions_permission_id_permissions FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE, 
    CONSTRAINT fk_role_permissions_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE
);

CREATE TABLE user_roles (
    user_id BIGINT NOT NULL, 
    role_id BIGINT NOT NULL, 
    CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_id), 
    CONSTRAINT fk_user_roles_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
    CONSTRAINT fk_user_roles_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE vehicle_sub_categories (
    cost_category_id BIGINT NOT NULL, 
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    default_tyre_layout_id BIGINT, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_vehicle_sub_categories PRIMARY KEY (id), 
    CONSTRAINT fk_vehicle_sub_categories_cost_category_id_cost_categories FOREIGN KEY(cost_category_id) REFERENCES cost_categories (id), 
    CONSTRAINT fk_vehicle_sub_categories_default_tyre_layout_id_tyre_layouts FOREIGN KEY(default_tyre_layout_id) REFERENCES tyre_layouts (id), 
    CONSTRAINT uq_vehicle_sub_categories_code UNIQUE (code), 
    CONSTRAINT uq_vehicle_sub_categories_cost_category_id_name UNIQUE (cost_category_id, name)
);

CREATE INDEX ix_vehicle_sub_categories_cost_category_id ON vehicle_sub_categories (cost_category_id);

CREATE INDEX ix_vehicle_sub_categories_default_tyre_layout_id ON vehicle_sub_categories (default_tyre_layout_id);

CREATE INDEX ix_vehicle_sub_categories_is_active ON vehicle_sub_categories (is_active);

CREATE TABLE vehicle_tyre_position_configurations (
    layout_id BIGINT NOT NULL, 
    position_id BIGINT NOT NULL, 
    display_row INTEGER NOT NULL, 
    display_col INTEGER NOT NULL, 
    is_spare BOOL NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_vehicle_tyre_position_configurations PRIMARY KEY (id), 
    CONSTRAINT fk_vehicle_tyre_position_configurations_layout_id_tyre_layouts FOREIGN KEY(layout_id) REFERENCES tyre_layouts (id) ON DELETE CASCADE, 
    CONSTRAINT fk_vehicle_tyre_position_configurations_position_id_tyre_ed92 FOREIGN KEY(position_id) REFERENCES tyre_positions (id), 
    CONSTRAINT uq_vehicle_tyre_position_configurations_layout_id_position_id UNIQUE (layout_id, position_id)
);

CREATE INDEX ix_vehicle_tyre_position_configurations_layout_id ON vehicle_tyre_position_configurations (layout_id);

CREATE INDEX ix_vehicle_tyre_position_configurations_position_id ON vehicle_tyre_position_configurations (position_id);

CREATE TABLE vendors (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    vendor_type VARCHAR(50) NOT NULL, 
    gstin VARCHAR(15), 
    pan VARCHAR(10), 
    contact_person VARCHAR(100), 
    phone VARCHAR(20), 
    email VARCHAR(150), 
    address TEXT, 
    state_id BIGINT, 
    bank_name VARCHAR(150), 
    bank_account_no VARCHAR(30), 
    bank_ifsc VARCHAR(11), 
    payment_terms_days INTEGER, 
    match_keywords VARCHAR(255), 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_vendors PRIMARY KEY (id), 
    CONSTRAINT fk_vendors_state_id_states FOREIGN KEY(state_id) REFERENCES states (id), 
    CONSTRAINT uq_vendors_code UNIQUE (code)
);

CREATE INDEX ix_vendors_is_active ON vendors (is_active);

CREATE INDEX ix_vendors_name ON vendors (name);

CREATE INDEX ix_vendors_state_id ON vendors (state_id);

CREATE INDEX ix_vendors_vendor_type ON vendors (vendor_type);

CREATE TABLE approval_actions (
    request_id BIGINT NOT NULL, 
    level INTEGER NOT NULL, 
    action VARCHAR(20) NOT NULL, 
    acted_by BIGINT, 
    acted_at DATETIME NOT NULL, 
    remarks VARCHAR(500), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_approval_actions PRIMARY KEY (id), 
    CONSTRAINT fk_approval_actions_request_id_approval_requests FOREIGN KEY(request_id) REFERENCES approval_requests (id)
);

CREATE INDEX ix_approval_actions_request_id ON approval_actions (request_id);

CREATE TABLE branches (
    company_id BIGINT NOT NULL, 
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    address TEXT, 
    state_id BIGINT, 
    district_id BIGINT, 
    phone VARCHAR(20), 
    email VARCHAR(150), 
    gstin VARCHAR(15), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_branches PRIMARY KEY (id), 
    CONSTRAINT fk_branches_company_id_companies FOREIGN KEY(company_id) REFERENCES companies (id), 
    CONSTRAINT fk_branches_district_id_districts FOREIGN KEY(district_id) REFERENCES districts (id), 
    CONSTRAINT fk_branches_state_id_states FOREIGN KEY(state_id) REFERENCES states (id), 
    CONSTRAINT uq_branches_code UNIQUE (code)
);

CREATE INDEX ix_branches_company_id ON branches (company_id);

CREATE INDEX ix_branches_district_id ON branches (district_id);

CREATE INDEX ix_branches_is_active ON branches (is_active);

CREATE INDEX ix_branches_state_id ON branches (state_id);

CREATE TABLE providers (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    provider_type VARCHAR(30) NOT NULL, 
    vendor_id BIGINT, 
    contact_person VARCHAR(100), 
    phone VARCHAR(20), 
    email VARCHAR(150), 
    website VARCHAR(200), 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_providers PRIMARY KEY (id), 
    CONSTRAINT fk_providers_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    CONSTRAINT uq_providers_code UNIQUE (code)
);

CREATE INDEX ix_providers_is_active ON providers (is_active);

CREATE INDEX ix_providers_provider_type ON providers (provider_type);

CREATE INDEX ix_providers_vendor_id ON providers (vendor_id);

CREATE TABLE renewal_rules (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    renewal_type_id BIGINT NOT NULL, 
    cost_category_id BIGINT, 
    sub_category_id BIGINT, 
    fuel_type_id BIGINT, 
    is_mandatory BOOL NOT NULL, 
    instances_required INTEGER NOT NULL, 
    validity_months INTEGER, 
    reminder_days VARCHAR(100), 
    grace_days INTEGER NOT NULL, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_renewal_rules PRIMARY KEY (id), 
    CONSTRAINT fk_renewal_rules_cost_category_id_cost_categories FOREIGN KEY(cost_category_id) REFERENCES cost_categories (id), 
    CONSTRAINT fk_renewal_rules_fuel_type_id_fuel_types FOREIGN KEY(fuel_type_id) REFERENCES fuel_types (id), 
    CONSTRAINT fk_renewal_rules_renewal_type_id_renewal_types FOREIGN KEY(renewal_type_id) REFERENCES renewal_types (id), 
    CONSTRAINT fk_renewal_rules_sub_category_id_vehicle_sub_categories FOREIGN KEY(sub_category_id) REFERENCES vehicle_sub_categories (id), 
    CONSTRAINT uq_renewal_rules_code UNIQUE (code)
);

CREATE INDEX ix_renewal_rules_cost_category_id ON renewal_rules (cost_category_id);

CREATE INDEX ix_renewal_rules_fuel_type_id ON renewal_rules (fuel_type_id);

CREATE INDEX ix_renewal_rules_is_active ON renewal_rules (is_active);

CREATE INDEX ix_renewal_rules_renewal_type_id ON renewal_rules (renewal_type_id);

CREATE INDEX ix_renewal_rules_sub_category_id ON renewal_rules (sub_category_id);

CREATE TABLE rtos (
    code VARCHAR(10) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    state_id BIGINT, 
    district_id BIGINT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_rtos PRIMARY KEY (id), 
    CONSTRAINT fk_rtos_district_id_districts FOREIGN KEY(district_id) REFERENCES districts (id), 
    CONSTRAINT fk_rtos_state_id_states FOREIGN KEY(state_id) REFERENCES states (id), 
    CONSTRAINT uq_rtos_code UNIQUE (code)
);

CREATE INDEX ix_rtos_district_id ON rtos (district_id);

CREATE INDEX ix_rtos_is_active ON rtos (is_active);

CREATE INDEX ix_rtos_state_id ON rtos (state_id);

CREATE TABLE sub_category_attributes (
    sub_category_id BIGINT NOT NULL, 
    code VARCHAR(40) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    data_type VARCHAR(20) NOT NULL, 
    unit_id BIGINT, 
    dropdown_options TEXT, 
    is_mandatory BOOL NOT NULL, 
    display_order INTEGER NOT NULL, 
    min_value NUMERIC(18, 4), 
    max_value NUMERIC(18, 4), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_sub_category_attributes PRIMARY KEY (id), 
    CONSTRAINT fk_sub_category_attributes_sub_category_id_vehicle_sub_c_6706 FOREIGN KEY(sub_category_id) REFERENCES vehicle_sub_categories (id), 
    CONSTRAINT fk_sub_category_attributes_unit_id_units FOREIGN KEY(unit_id) REFERENCES units (id), 
    CONSTRAINT uq_sub_category_attributes_sub_category_id_code UNIQUE (sub_category_id, code)
);

CREATE INDEX ix_sub_category_attributes_is_active ON sub_category_attributes (is_active);

CREATE INDEX ix_sub_category_attributes_sub_category_id ON sub_category_attributes (sub_category_id);

CREATE INDEX ix_sub_category_attributes_unit_id ON sub_category_attributes (unit_id);

CREATE TABLE banks (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    short_name VARCHAR(30), 
    provider_id BIGINT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_banks PRIMARY KEY (id), 
    CONSTRAINT fk_banks_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT uq_banks_code UNIQUE (code)
);

CREATE INDEX ix_banks_is_active ON banks (is_active);

CREATE INDEX ix_banks_provider_id ON banks (provider_id);

CREATE TABLE departments (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    branch_id BIGINT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_departments PRIMARY KEY (id), 
    CONSTRAINT fk_departments_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id), 
    CONSTRAINT uq_departments_code UNIQUE (code)
);

CREATE INDEX ix_departments_branch_id ON departments (branch_id);

CREATE INDEX ix_departments_is_active ON departments (is_active);

CREATE TABLE fuel_stations (
    provider_id BIGINT, 
    station_code VARCHAR(40) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    address TEXT, 
    city VARCHAR(100), 
    district_id BIGINT, 
    state_id BIGINT, 
    pincode VARCHAR(6), 
    latitude NUMERIC(10, 7), 
    longitude NUMERIC(10, 7), 
    contact VARCHAR(100), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_fuel_stations PRIMARY KEY (id), 
    CONSTRAINT fk_fuel_stations_district_id_districts FOREIGN KEY(district_id) REFERENCES districts (id), 
    CONSTRAINT fk_fuel_stations_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT fk_fuel_stations_state_id_states FOREIGN KEY(state_id) REFERENCES states (id), 
    CONSTRAINT uq_fuel_stations_provider_id_station_code UNIQUE (provider_id, station_code)
);

CREATE INDEX ix_fuel_stations_district_id ON fuel_stations (district_id);

CREATE INDEX ix_fuel_stations_is_active ON fuel_stations (is_active);

CREATE INDEX ix_fuel_stations_name ON fuel_stations (name);

CREATE INDEX ix_fuel_stations_provider_id ON fuel_stations (provider_id);

CREATE INDEX ix_fuel_stations_state_id ON fuel_stations (state_id);

CREATE TABLE locations (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    location_type VARCHAR(50) NOT NULL, 
    branch_id BIGINT, 
    address TEXT, 
    state_id BIGINT, 
    district_id BIGINT, 
    pincode VARCHAR(6), 
    contact_person VARCHAR(100), 
    phone VARCHAR(20), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_locations PRIMARY KEY (id), 
    CONSTRAINT fk_locations_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id), 
    CONSTRAINT fk_locations_district_id_districts FOREIGN KEY(district_id) REFERENCES districts (id), 
    CONSTRAINT fk_locations_state_id_states FOREIGN KEY(state_id) REFERENCES states (id), 
    CONSTRAINT uq_locations_code UNIQUE (code)
);

CREATE INDEX ix_locations_branch_id ON locations (branch_id);

CREATE INDEX ix_locations_district_id ON locations (district_id);

CREATE INDEX ix_locations_is_active ON locations (is_active);

CREATE INDEX ix_locations_location_type ON locations (location_type);

CREATE INDEX ix_locations_state_id ON locations (state_id);

CREATE TABLE statement_import_templates (
    provider_id BIGINT NOT NULL, 
    template_name VARCHAR(100) NOT NULL, 
    statement_type VARCHAR(30) NOT NULL, 
    file_format VARCHAR(10) NOT NULL, 
    sheet_name VARCHAR(100), 
    header_row INTEGER NOT NULL, 
    data_start_row INTEGER NOT NULL, 
    stop_at_blank_rows INTEGER NOT NULL, 
    skip_footer_keywords VARCHAR(255), 
    date_format VARCHAR(30), 
    datetime_format VARCHAR(40), 
    amount_mode VARCHAR(20) NOT NULL, 
    duplicate_key_fields VARCHAR(255), 
    version INTEGER NOT NULL, 
    effective_from DATE, 
    effective_to DATE, 
    description TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_statement_import_templates PRIMARY KEY (id), 
    CONSTRAINT fk_statement_import_templates_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT uq_statement_import_templates_provider_id_template_name_version UNIQUE (provider_id, template_name, version)
);

CREATE INDEX ix_statement_import_templates_is_active ON statement_import_templates (is_active);

CREATE INDEX ix_statement_import_templates_provider_id ON statement_import_templates (provider_id);

CREATE INDEX ix_statement_import_templates_statement_type ON statement_import_templates (statement_type);

CREATE TABLE toll_api_configurations (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    integration_type VARCHAR(30) NOT NULL, 
    provider_id BIGINT, 
    base_url VARCHAR(255), 
    auth_type VARCHAR(20), 
    credential_env_var VARCHAR(100), 
    client_id_env_var VARCHAR(100), 
    timeout_seconds INTEGER NOT NULL, 
    sync_frequency_minutes INTEGER, 
    last_sync_at DATETIME, 
    last_sync_status VARCHAR(30), 
    settings JSON, 
    remarks VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_toll_api_configurations PRIMARY KEY (id), 
    CONSTRAINT fk_toll_api_configurations_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT uq_toll_api_configurations_code UNIQUE (code)
);

CREATE INDEX ix_toll_api_configurations_integration_type ON toll_api_configurations (integration_type);

CREATE INDEX ix_toll_api_configurations_is_active ON toll_api_configurations (is_active);

CREATE INDEX ix_toll_api_configurations_provider_id ON toll_api_configurations (provider_id);

CREATE TABLE toll_plazas (
    external_plaza_id VARCHAR(40), 
    plaza_code VARCHAR(40) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    highway VARCHAR(50), 
    road VARCHAR(150), 
    state_id BIGINT, 
    district_id BIGINT, 
    latitude NUMERIC(10, 7), 
    longitude NUMERIC(10, 7), 
    operator VARCHAR(150), 
    provider_id BIGINT, 
    api_source VARCHAR(60), 
    api_last_synced_at DATETIME, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_toll_plazas PRIMARY KEY (id), 
    CONSTRAINT fk_toll_plazas_district_id_districts FOREIGN KEY(district_id) REFERENCES districts (id), 
    CONSTRAINT fk_toll_plazas_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT fk_toll_plazas_state_id_states FOREIGN KEY(state_id) REFERENCES states (id), 
    CONSTRAINT uq_toll_plazas_plaza_code UNIQUE (plaza_code)
);

CREATE INDEX ix_toll_plazas_district_id ON toll_plazas (district_id);

CREATE INDEX ix_toll_plazas_external_plaza_id ON toll_plazas (external_plaza_id);

CREATE INDEX ix_toll_plazas_is_active ON toll_plazas (is_active);

CREATE INDEX ix_toll_plazas_name ON toll_plazas (name);

CREATE INDEX ix_toll_plazas_provider_id ON toll_plazas (provider_id);

CREATE INDEX ix_toll_plazas_state_id ON toll_plazas (state_id);

CREATE TABLE user_branches (
    user_id BIGINT NOT NULL, 
    branch_id BIGINT NOT NULL, 
    CONSTRAINT pk_user_branches PRIMARY KEY (user_id, branch_id), 
    CONSTRAINT fk_user_branches_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id) ON DELETE CASCADE, 
    CONSTRAINT fk_user_branches_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE value_mappings (
    mapping_type VARCHAR(30) NOT NULL, 
    provider_id BIGINT, 
    source_value VARCHAR(150) NOT NULL, 
    target_value VARCHAR(150), 
    target_id BIGINT, 
    remarks VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_value_mappings PRIMARY KEY (id), 
    CONSTRAINT fk_value_mappings_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT uq_value_mappings_mapping_type_provider_id_source_value UNIQUE (mapping_type, provider_id, source_value)
);

CREATE INDEX ix_value_mappings_is_active ON value_mappings (is_active);

CREATE INDEX ix_value_mappings_mapping_type ON value_mappings (mapping_type);

CREATE INDEX ix_value_mappings_provider_id ON value_mappings (provider_id);

CREATE TABLE bank_accounts (
    bank_id BIGINT NOT NULL, 
    company_id BIGINT, 
    branch_id BIGINT, 
    code VARCHAR(20) NOT NULL, 
    account_name VARCHAR(200) NOT NULL, 
    account_number VARCHAR(34) NOT NULL, 
    account_type VARCHAR(30) NOT NULL, 
    bank_branch VARCHAR(150), 
    ifsc VARCHAR(11), 
    opening_balance NUMERIC(18, 2) NOT NULL, 
    opening_date DATE, 
    closing_balance NUMERIC(18, 2), 
    closing_balance_date DATE, 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_bank_accounts PRIMARY KEY (id), 
    CONSTRAINT fk_bank_accounts_bank_id_banks FOREIGN KEY(bank_id) REFERENCES banks (id), 
    CONSTRAINT fk_bank_accounts_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id), 
    CONSTRAINT fk_bank_accounts_company_id_companies FOREIGN KEY(company_id) REFERENCES companies (id), 
    CONSTRAINT uq_bank_accounts_bank_id_account_number UNIQUE (bank_id, account_number), 
    CONSTRAINT uq_bank_accounts_code UNIQUE (code)
);

CREATE INDEX ix_bank_accounts_bank_id ON bank_accounts (bank_id);

CREATE INDEX ix_bank_accounts_branch_id ON bank_accounts (branch_id);

CREATE INDEX ix_bank_accounts_company_id ON bank_accounts (company_id);

CREATE INDEX ix_bank_accounts_is_active ON bank_accounts (is_active);

CREATE TABLE cost_centers (
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    cc_type VARCHAR(20) NOT NULL, 
    cost_category_id BIGINT, 
    branch_id BIGINT, 
    department_id BIGINT, 
    vehicle_id BIGINT, 
    parent_id BIGINT, 
    description VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_cost_centers PRIMARY KEY (id), 
    CONSTRAINT fk_cost_centers_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id), 
    CONSTRAINT fk_cost_centers_cost_category_id_cost_categories FOREIGN KEY(cost_category_id) REFERENCES cost_categories (id), 
    CONSTRAINT fk_cost_centers_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id), 
    CONSTRAINT fk_cost_centers_parent_id_cost_centers FOREIGN KEY(parent_id) REFERENCES cost_centers (id), 
    CONSTRAINT uq_cost_centers_code UNIQUE (code), 
    CONSTRAINT uq_cost_centers_vehicle_id UNIQUE (vehicle_id)
);

CREATE INDEX ix_cost_centers_branch_id ON cost_centers (branch_id);

CREATE INDEX ix_cost_centers_cc_type ON cost_centers (cc_type);

CREATE INDEX ix_cost_centers_cost_category_id ON cost_centers (cost_category_id);

CREATE INDEX ix_cost_centers_department_id ON cost_centers (department_id);

CREATE INDEX ix_cost_centers_is_active ON cost_centers (is_active);

CREATE INDEX ix_cost_centers_parent_id ON cost_centers (parent_id);

CREATE TABLE statement_template_columns (
    template_id BIGINT NOT NULL, 
    source_column VARCHAR(10), 
    source_header VARCHAR(150), 
    target_field VARCHAR(60) NOT NULL, 
    data_type VARCHAR(20) NOT NULL, 
    is_required BOOL NOT NULL, 
    transformation VARCHAR(500), 
    default_value VARCHAR(150), 
    lookup_rule VARCHAR(60), 
    validation_rule VARCHAR(255), 
    display_order INTEGER NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_statement_template_columns PRIMARY KEY (id), 
    CONSTRAINT fk_statement_template_columns_template_id_statement_impo_0885 FOREIGN KEY(template_id) REFERENCES statement_import_templates (id) ON DELETE CASCADE
);

CREATE INDEX ix_statement_template_columns_template_id ON statement_template_columns (template_id);

CREATE TABLE tyre_locations (
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    location_type VARCHAR(30) NOT NULL, 
    location_id BIGINT, 
    vendor_id BIGINT, 
    branch_id BIGINT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_tyre_locations PRIMARY KEY (id), 
    CONSTRAINT fk_tyre_locations_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id), 
    CONSTRAINT fk_tyre_locations_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id), 
    CONSTRAINT fk_tyre_locations_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    CONSTRAINT uq_tyre_locations_code UNIQUE (code)
);

CREATE INDEX ix_tyre_locations_branch_id ON tyre_locations (branch_id);

CREATE INDEX ix_tyre_locations_is_active ON tyre_locations (is_active);

CREATE INDEX ix_tyre_locations_location_id ON tyre_locations (location_id);

CREATE INDEX ix_tyre_locations_vendor_id ON tyre_locations (vendor_id);

CREATE TABLE contracts (
    customer_id BIGINT NOT NULL, 
    contract_number VARCHAR(50) NOT NULL, 
    contract_date DATE, 
    start_date DATE NOT NULL, 
    end_date DATE, 
    contract_type VARCHAR(30), 
    billing_method VARCHAR(30), 
    rate NUMERIC(18, 2), 
    rate_unit_id BIGINT, 
    contract_value NUMERIC(18, 2), 
    cost_center_id BIGINT, 
    branch_id BIGINT, 
    payment_terms_days INTEGER, 
    invoice_details TEXT, 
    status VARCHAR(20) NOT NULL, 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_contracts PRIMARY KEY (id), 
    CONSTRAINT fk_contracts_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id), 
    CONSTRAINT fk_contracts_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_contracts_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id), 
    CONSTRAINT fk_contracts_rate_unit_id_units FOREIGN KEY(rate_unit_id) REFERENCES units (id), 
    CONSTRAINT uq_contracts_contract_number UNIQUE (contract_number)
);

CREATE INDEX ix_contracts_branch_id ON contracts (branch_id);

CREATE INDEX ix_contracts_cost_center_id ON contracts (cost_center_id);

CREATE INDEX ix_contracts_customer_id ON contracts (customer_id);

CREATE INDEX ix_contracts_is_active ON contracts (is_active);

CREATE INDEX ix_contracts_rate_unit_id ON contracts (rate_unit_id);

CREATE INDEX ix_contracts_status ON contracts (status);

CREATE TABLE drivers (
    driver_code VARCHAR(30) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    employee_number VARCHAR(30), 
    mobile VARCHAR(15), 
    alt_mobile VARCHAR(15), 
    address TEXT, 
    date_of_birth DATE, 
    license_number VARCHAR(30), 
    license_class VARCHAR(50), 
    license_issue_date DATE, 
    license_expiry_date DATE, 
    hazardous_endorsement BOOL NOT NULL, 
    medical_expiry_date DATE, 
    branch_id BIGINT, 
    cost_center_id BIGINT, 
    engagement_type VARCHAR(30), 
    status VARCHAR(30) NOT NULL, 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_drivers PRIMARY KEY (id), 
    CONSTRAINT fk_drivers_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id), 
    CONSTRAINT fk_drivers_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT uq_drivers_driver_code UNIQUE (driver_code), 
    CONSTRAINT uq_drivers_license_number UNIQUE (license_number)
);

CREATE INDEX ix_drivers_branch_id ON drivers (branch_id);

CREATE INDEX ix_drivers_cost_center_id ON drivers (cost_center_id);

CREATE INDEX ix_drivers_employee_number ON drivers (employee_number);

CREATE INDEX ix_drivers_is_active ON drivers (is_active);

CREATE INDEX ix_drivers_license_expiry_date ON drivers (license_expiry_date);

CREATE INDEX ix_drivers_name ON drivers (name);

CREATE TABLE statement_import_batches (
    provider_id BIGINT NOT NULL, 
    template_id BIGINT NOT NULL, 
    statement_type VARCHAR(30) NOT NULL, 
    bank_account_id BIGINT, 
    file_name VARCHAR(255) NOT NULL, 
    file_hash VARCHAR(64) NOT NULL, 
    storage_key VARCHAR(255), 
    sheet_name VARCHAR(100), 
    imported_at DATETIME, 
    imported_by BIGINT, 
    total_rows INTEGER NOT NULL, 
    successful_rows INTEGER NOT NULL, 
    duplicate_rows INTEGER NOT NULL, 
    error_rows INTEGER NOT NULL, 
    warning_rows INTEGER NOT NULL, 
    unmatched_rows INTEGER NOT NULL, 
    processed_rows INTEGER NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    error_message TEXT, 
    summary JSON, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_statement_import_batches PRIMARY KEY (id), 
    CONSTRAINT fk_statement_import_batches_bank_account_id_bank_accounts FOREIGN KEY(bank_account_id) REFERENCES bank_accounts (id), 
    CONSTRAINT fk_statement_import_batches_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT fk_statement_import_batches_template_id_statement_import_8767 FOREIGN KEY(template_id) REFERENCES statement_import_templates (id)
);

CREATE INDEX ix_sib_hash ON statement_import_batches (file_hash);

CREATE INDEX ix_statement_import_batches_bank_account_id ON statement_import_batches (bank_account_id);

CREATE INDEX ix_statement_import_batches_provider_id ON statement_import_batches (provider_id);

CREATE INDEX ix_statement_import_batches_statement_type ON statement_import_batches (statement_type);

CREATE INDEX ix_statement_import_batches_status ON statement_import_batches (status);

CREATE INDEX ix_statement_import_batches_template_id ON statement_import_batches (template_id);

CREATE TABLE vehicles (
    vehicle_code VARCHAR(30) NOT NULL, 
    registration_number VARCHAR(20) NOT NULL, 
    registration_normalized VARCHAR(20) NOT NULL, 
    fleet_number VARCHAR(30), 
    vehicle_type VARCHAR(50), 
    cost_category_id BIGINT NOT NULL, 
    sub_category_id BIGINT NOT NULL, 
    cost_center_id BIGINT, 
    chassis_number VARCHAR(30), 
    engine_number VARCHAR(30), 
    manufacturer VARCHAR(100), 
    model VARCHAR(100), 
    manufacturing_year INTEGER, 
    purchase_date DATE, 
    purchase_cost NUMERIC(18, 2), 
    vehicle_status VARCHAR(30) NOT NULL, 
    branch_id BIGINT, 
    location_id BIGINT, 
    rto_id BIGINT, 
    ownership_type VARCHAR(30), 
    owner_name VARCHAR(150), 
    capacity NUMERIC(18, 3), 
    capacity_unit_id BIGINT, 
    gvw NUMERIC(18, 3), 
    axle_count INTEGER, 
    tyre_layout_id BIGINT, 
    current_odometer NUMERIC(12, 1), 
    odometer_updated_at DATETIME, 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_vehicles PRIMARY KEY (id), 
    CONSTRAINT fk_vehicles_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id), 
    CONSTRAINT fk_vehicles_capacity_unit_id_units FOREIGN KEY(capacity_unit_id) REFERENCES units (id), 
    CONSTRAINT fk_vehicles_cost_category_id_cost_categories FOREIGN KEY(cost_category_id) REFERENCES cost_categories (id), 
    CONSTRAINT fk_vehicles_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_vehicles_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id), 
    CONSTRAINT fk_vehicles_rto_id_rtos FOREIGN KEY(rto_id) REFERENCES rtos (id), 
    CONSTRAINT fk_vehicles_sub_category_id_vehicle_sub_categories FOREIGN KEY(sub_category_id) REFERENCES vehicle_sub_categories (id), 
    CONSTRAINT fk_vehicles_tyre_layout_id_tyre_layouts FOREIGN KEY(tyre_layout_id) REFERENCES tyre_layouts (id), 
    CONSTRAINT uq_vehicles_chassis_number UNIQUE (chassis_number), 
    CONSTRAINT uq_vehicles_registration_normalized UNIQUE (registration_normalized), 
    CONSTRAINT uq_vehicles_vehicle_code UNIQUE (vehicle_code)
);

CREATE INDEX ix_vehicles_branch_id ON vehicles (branch_id);

CREATE INDEX ix_vehicles_capacity_unit_id ON vehicles (capacity_unit_id);

CREATE INDEX ix_vehicles_cost_category_id ON vehicles (cost_category_id);

CREATE INDEX ix_vehicles_cost_center_id ON vehicles (cost_center_id);

CREATE INDEX ix_vehicles_fleet_number ON vehicles (fleet_number);

CREATE INDEX ix_vehicles_is_active ON vehicles (is_active);

CREATE INDEX ix_vehicles_location_id ON vehicles (location_id);

CREATE INDEX ix_vehicles_rto_id ON vehicles (rto_id);

CREATE INDEX ix_vehicles_sub_category_id ON vehicles (sub_category_id);

CREATE INDEX ix_vehicles_tyre_layout_id ON vehicles (tyre_layout_id);

CREATE INDEX ix_vehicles_vehicle_status ON vehicles (vehicle_status);

CREATE TABLE bank_transactions (
    bank_account_id BIGINT NOT NULL, 
    txn_date DATE NOT NULL, 
    value_date DATE, 
    narration VARCHAR(500), 
    credit NUMERIC(18, 2) NOT NULL, 
    debit NUMERIC(18, 2) NOT NULL, 
    amount NUMERIC(18, 2) NOT NULL, 
    direction VARCHAR(2) NOT NULL, 
    reference_number VARCHAR(80), 
    utr VARCHAR(40), 
    cheque_number VARCHAR(20), 
    balance NUMERIC(18, 2), 
    counterparty VARCHAR(200), 
    credit_type_id BIGINT, 
    expense_type_id BIGINT, 
    classification VARCHAR(30) NOT NULL, 
    recon_status VARCHAR(20) NOT NULL, 
    matched_amount NUMERIC(18, 2) NOT NULL, 
    unmatched_amount NUMERIC(18, 2) NOT NULL, 
    allow_partial BOOL NOT NULL, 
    remarks TEXT, 
    status VARCHAR(20) NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    source_type VARCHAR(10) NOT NULL, 
    source_reference VARCHAR(255), 
    source_file VARCHAR(255), 
    source_sheet VARCHAR(100), 
    source_row INTEGER, 
    import_batch_id BIGINT, 
    txn_hash VARCHAR(64), 
    CONSTRAINT pk_bank_transactions PRIMARY KEY (id), 
    CONSTRAINT ck_bank_transactions_amount_non_negative CHECK (amount >= 0), 
    CONSTRAINT fk_bank_transactions_bank_account_id_bank_accounts FOREIGN KEY(bank_account_id) REFERENCES bank_accounts (id), 
    CONSTRAINT fk_bank_transactions_credit_type_id_credit_types FOREIGN KEY(credit_type_id) REFERENCES credit_types (id), 
    CONSTRAINT fk_bank_transactions_expense_type_id_expense_types FOREIGN KEY(expense_type_id) REFERENCES expense_types (id), 
    CONSTRAINT fk_bank_transactions_import_batch_id_statement_import_batches FOREIGN KEY(import_batch_id) REFERENCES statement_import_batches (id), 
    CONSTRAINT uq_bank_txn_business_key UNIQUE (bank_account_id, txn_hash)
);

CREATE INDEX ix_bank_transactions_credit_type_id ON bank_transactions (credit_type_id);

CREATE INDEX ix_bank_transactions_expense_type_id ON bank_transactions (expense_type_id);

CREATE INDEX ix_bank_transactions_import_batch_id ON bank_transactions (import_batch_id);

CREATE INDEX ix_bank_transactions_reference_number ON bank_transactions (reference_number);

CREATE INDEX ix_bank_transactions_txn_hash ON bank_transactions (txn_hash);

CREATE INDEX ix_bank_transactions_utr ON bank_transactions (utr);

CREATE INDEX ix_bt_account_date ON bank_transactions (bank_account_id, txn_date);

CREATE INDEX ix_bt_status_dir ON bank_transactions (recon_status, direction);

CREATE TABLE contract_vehicle_allocations (
    contract_id BIGINT NOT NULL, 
    vehicle_id BIGINT, 
    cost_center_id BIGINT, 
    allocation_percent NUMERIC(18, 2), 
    fixed_amount NUMERIC(18, 2), 
    effective_from DATE, 
    effective_to DATE, 
    remarks VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_contract_vehicle_allocations PRIMARY KEY (id), 
    CONSTRAINT fk_contract_vehicle_allocations_contract_id_contracts FOREIGN KEY(contract_id) REFERENCES contracts (id) ON DELETE CASCADE, 
    CONSTRAINT fk_contract_vehicle_allocations_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_contract_vehicle_allocations_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
);

CREATE INDEX ix_contract_vehicle_allocations_contract_id ON contract_vehicle_allocations (contract_id);

CREATE INDEX ix_contract_vehicle_allocations_cost_center_id ON contract_vehicle_allocations (cost_center_id);

CREATE INDEX ix_contract_vehicle_allocations_vehicle_id ON contract_vehicle_allocations (vehicle_id);

CREATE TABLE expense_transactions (
    document_number VARCHAR(50) NOT NULL, 
    expense_date DATE NOT NULL, 
    expense_type_id BIGINT NOT NULL, 
    vendor_id BIGINT, 
    driver_id BIGINT, 
    vehicle_id BIGINT, 
    cost_center_id BIGINT, 
    invoice_number VARCHAR(50), 
    invoice_date DATE, 
    amount NUMERIC(18, 2) NOT NULL, 
    tax_amount NUMERIC(18, 2) NOT NULL, 
    total_amount NUMERIC(18, 2) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    description TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    source_type VARCHAR(10) NOT NULL, 
    source_reference VARCHAR(255), 
    source_file VARCHAR(255), 
    source_sheet VARCHAR(100), 
    source_row INTEGER, 
    import_batch_id BIGINT, 
    txn_hash VARCHAR(64), 
    CONSTRAINT pk_expense_transactions PRIMARY KEY (id), 
    CONSTRAINT fk_expense_transactions_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_expense_transactions_driver_id_drivers FOREIGN KEY(driver_id) REFERENCES drivers (id), 
    CONSTRAINT fk_expense_transactions_expense_type_id_expense_types FOREIGN KEY(expense_type_id) REFERENCES expense_types (id), 
    CONSTRAINT fk_expense_transactions_import_batch_id_statement_import_batches FOREIGN KEY(import_batch_id) REFERENCES statement_import_batches (id), 
    CONSTRAINT fk_expense_transactions_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT fk_expense_transactions_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    CONSTRAINT uq_expense_transactions_document_number UNIQUE (document_number)
);

CREATE INDEX ix_exp_date ON expense_transactions (expense_date);

CREATE INDEX ix_expense_transactions_cost_center_id ON expense_transactions (cost_center_id);

CREATE INDEX ix_expense_transactions_driver_id ON expense_transactions (driver_id);

CREATE INDEX ix_expense_transactions_expense_type_id ON expense_transactions (expense_type_id);

CREATE INDEX ix_expense_transactions_import_batch_id ON expense_transactions (import_batch_id);

CREATE INDEX ix_expense_transactions_invoice_number ON expense_transactions (invoice_number);

CREATE INDEX ix_expense_transactions_txn_hash ON expense_transactions (txn_hash);

CREATE INDEX ix_expense_transactions_vehicle_id ON expense_transactions (vehicle_id);

CREATE INDEX ix_expense_transactions_vendor_id ON expense_transactions (vendor_id);

CREATE TABLE fuel_cards (
    provider_id BIGINT NOT NULL, 
    card_number VARCHAR(40) NOT NULL, 
    vehicle_id BIGINT, 
    effective_from DATE, 
    effective_to DATE, 
    remarks VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_fuel_cards PRIMARY KEY (id), 
    CONSTRAINT fk_fuel_cards_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT fk_fuel_cards_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT uq_fuel_cards_provider_id_card_number UNIQUE (provider_id, card_number)
);

CREATE INDEX ix_fuel_cards_is_active ON fuel_cards (is_active);

CREATE INDEX ix_fuel_cards_provider_id ON fuel_cards (provider_id);

CREATE INDEX ix_fuel_cards_vehicle_id ON fuel_cards (vehicle_id);

CREATE TABLE fuel_transactions (
    provider_id BIGINT, 
    provider_transaction_id VARCHAR(80), 
    txn_datetime DATETIME NOT NULL, 
    txn_date DATE NOT NULL, 
    vehicle_id BIGINT, 
    vehicle_number_raw VARCHAR(30), 
    cost_center_id BIGINT, 
    fuel_station_id BIGINT, 
    station_raw VARCHAR(200), 
    fuel_type_id BIGINT, 
    fuel_type_raw VARCHAR(50), 
    quantity NUMERIC(18, 3) NOT NULL, 
    unit_id BIGINT, 
    rate NUMERIC(18, 4), 
    amount NUMERIC(18, 2) NOT NULL, 
    tax_amount NUMERIC(18, 2) NOT NULL, 
    discount_amount NUMERIC(18, 2) NOT NULL, 
    total_amount NUMERIC(18, 2) NOT NULL, 
    invoice_number VARCHAR(50), 
    card_number VARCHAR(40), 
    odometer NUMERIC(12, 1), 
    km_since_last NUMERIC(12, 1), 
    efficiency NUMERIC(10, 3), 
    efficiency_flag VARCHAR(20), 
    status VARCHAR(20) NOT NULL, 
    validation_flags JSON, 
    override_reason VARCHAR(500), 
    override_by BIGINT, 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    source_type VARCHAR(10) NOT NULL, 
    source_reference VARCHAR(255), 
    source_file VARCHAR(255), 
    source_sheet VARCHAR(100), 
    source_row INTEGER, 
    import_batch_id BIGINT, 
    txn_hash VARCHAR(64), 
    CONSTRAINT pk_fuel_transactions PRIMARY KEY (id), 
    CONSTRAINT ck_fuel_transactions_qty_non_negative CHECK (quantity >= 0), 
    CONSTRAINT fk_fuel_transactions_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_fuel_transactions_fuel_station_id_fuel_stations FOREIGN KEY(fuel_station_id) REFERENCES fuel_stations (id), 
    CONSTRAINT fk_fuel_transactions_fuel_type_id_fuel_types FOREIGN KEY(fuel_type_id) REFERENCES fuel_types (id), 
    CONSTRAINT fk_fuel_transactions_import_batch_id_statement_import_batches FOREIGN KEY(import_batch_id) REFERENCES statement_import_batches (id), 
    CONSTRAINT fk_fuel_transactions_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT fk_fuel_transactions_unit_id_units FOREIGN KEY(unit_id) REFERENCES units (id), 
    CONSTRAINT fk_fuel_transactions_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT uq_fuel_provider_txn UNIQUE (provider_id, provider_transaction_id)
);

CREATE INDEX ix_fuel_status ON fuel_transactions (status);

CREATE INDEX ix_fuel_transactions_cost_center_id ON fuel_transactions (cost_center_id);

CREATE INDEX ix_fuel_transactions_fuel_station_id ON fuel_transactions (fuel_station_id);

CREATE INDEX ix_fuel_transactions_fuel_type_id ON fuel_transactions (fuel_type_id);

CREATE INDEX ix_fuel_transactions_import_batch_id ON fuel_transactions (import_batch_id);

CREATE INDEX ix_fuel_transactions_txn_date ON fuel_transactions (txn_date);

CREATE INDEX ix_fuel_transactions_txn_hash ON fuel_transactions (txn_hash);

CREATE INDEX ix_fuel_transactions_unit_id ON fuel_transactions (unit_id);

CREATE INDEX ix_fuel_vehicle_dt ON fuel_transactions (vehicle_id, txn_datetime);

CREATE TABLE insurance_policies (
    vehicle_id BIGINT, 
    driver_id BIGINT, 
    provider_id BIGINT NOT NULL, 
    policy_type VARCHAR(30) NOT NULL, 
    policy_number VARCHAR(80) NOT NULL, 
    insured_amount NUMERIC(18, 2), 
    start_date DATE NOT NULL, 
    expiry_date DATE NOT NULL, 
    premium NUMERIC(18, 2), 
    tax_amount NUMERIC(18, 2), 
    total_premium NUMERIC(18, 2), 
    payment_mode VARCHAR(30), 
    payment_reference VARCHAR(80), 
    payment_date DATE, 
    payment_status VARCHAR(20) NOT NULL, 
    renewal_status VARCHAR(20) NOT NULL, 
    cost_center_id BIGINT, 
    is_current BOOL NOT NULL, 
    previous_policy_id BIGINT, 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_insurance_policies PRIMARY KEY (id), 
    CONSTRAINT fk_insurance_policies_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_insurance_policies_driver_id_drivers FOREIGN KEY(driver_id) REFERENCES drivers (id), 
    CONSTRAINT fk_insurance_policies_previous_policy_id_insurance_policies FOREIGN KEY(previous_policy_id) REFERENCES insurance_policies (id), 
    CONSTRAINT fk_insurance_policies_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT fk_insurance_policies_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT uq_insurance_policies_provider_id_policy_number UNIQUE (provider_id, policy_number)
);

CREATE INDEX ix_ins_expiry ON insurance_policies (expiry_date);

CREATE INDEX ix_insurance_policies_cost_center_id ON insurance_policies (cost_center_id);

CREATE INDEX ix_insurance_policies_driver_id ON insurance_policies (driver_id);

CREATE INDEX ix_insurance_policies_policy_type ON insurance_policies (policy_type);

CREATE INDEX ix_insurance_policies_previous_policy_id ON insurance_policies (previous_policy_id);

CREATE INDEX ix_insurance_policies_provider_id ON insurance_policies (provider_id);

CREATE INDEX ix_insurance_policies_renewal_status ON insurance_policies (renewal_status);

CREATE INDEX ix_insurance_policies_vehicle_id ON insurance_policies (vehicle_id);

CREATE TABLE invoices (
    invoice_number VARCHAR(50) NOT NULL, 
    invoice_type VARCHAR(20) NOT NULL, 
    customer_id BIGINT NOT NULL, 
    contract_id BIGINT, 
    invoice_date DATE NOT NULL, 
    due_date DATE, 
    period_from DATE, 
    period_to DATE, 
    taxable_amount NUMERIC(18, 2) NOT NULL, 
    tax_amount NUMERIC(18, 2) NOT NULL, 
    total_amount NUMERIC(18, 2) NOT NULL, 
    received_amount NUMERIC(18, 2) NOT NULL, 
    outstanding_amount NUMERIC(18, 2) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    original_invoice_id BIGINT, 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_invoices PRIMARY KEY (id), 
    CONSTRAINT fk_invoices_contract_id_contracts FOREIGN KEY(contract_id) REFERENCES contracts (id), 
    CONSTRAINT fk_invoices_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id), 
    CONSTRAINT fk_invoices_original_invoice_id_invoices FOREIGN KEY(original_invoice_id) REFERENCES invoices (id), 
    CONSTRAINT uq_invoices_invoice_number UNIQUE (invoice_number)
);

CREATE INDEX ix_inv_customer_status ON invoices (customer_id, status);

CREATE INDEX ix_invoices_contract_id ON invoices (contract_id);

CREATE INDEX ix_invoices_invoice_date ON invoices (invoice_date);

CREATE INDEX ix_invoices_original_invoice_id ON invoices (original_invoice_id);

CREATE TABLE maintenance_job_cards (
    job_card_number VARCHAR(40) NOT NULL, 
    vehicle_id BIGINT NOT NULL, 
    cost_center_id BIGINT, 
    job_date DATE NOT NULL, 
    completion_date DATE, 
    odometer NUMERIC(12, 1), 
    maintenance_type_id BIGINT NOT NULL, 
    complaint TEXT, 
    diagnosis TEXT, 
    work_performed TEXT, 
    vendor_id BIGINT, 
    workshop_location_id BIGINT, 
    downtime_start DATETIME, 
    downtime_end DATETIME, 
    downtime_hours NUMERIC(10, 2), 
    parts_amount NUMERIC(18, 2) NOT NULL, 
    labour_amount NUMERIC(18, 2) NOT NULL, 
    other_amount NUMERIC(18, 2) NOT NULL, 
    amount NUMERIC(18, 2) NOT NULL, 
    tax_amount NUMERIC(18, 2) NOT NULL, 
    total_amount NUMERIC(18, 2) NOT NULL, 
    invoice_number VARCHAR(50), 
    invoice_date DATE, 
    status VARCHAR(20) NOT NULL, 
    approval_status VARCHAR(20) NOT NULL, 
    approved_by BIGINT, 
    approved_at DATETIME, 
    next_due_km NUMERIC(12, 1), 
    next_due_date DATE, 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    source_type VARCHAR(10) NOT NULL, 
    source_reference VARCHAR(255), 
    source_file VARCHAR(255), 
    source_sheet VARCHAR(100), 
    source_row INTEGER, 
    import_batch_id BIGINT, 
    txn_hash VARCHAR(64), 
    CONSTRAINT pk_maintenance_job_cards PRIMARY KEY (id), 
    CONSTRAINT fk_maintenance_job_cards_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_maintenance_job_cards_import_batch_id_statement_impor_990e FOREIGN KEY(import_batch_id) REFERENCES statement_import_batches (id), 
    CONSTRAINT fk_maintenance_job_cards_maintenance_type_id_maintenance_types FOREIGN KEY(maintenance_type_id) REFERENCES maintenance_types (id), 
    CONSTRAINT fk_maintenance_job_cards_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT fk_maintenance_job_cards_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    CONSTRAINT fk_maintenance_job_cards_workshop_location_id_locations FOREIGN KEY(workshop_location_id) REFERENCES locations (id), 
    CONSTRAINT uq_maintenance_job_cards_job_card_number UNIQUE (job_card_number)
);

CREATE INDEX ix_maintenance_job_cards_cost_center_id ON maintenance_job_cards (cost_center_id);

CREATE INDEX ix_maintenance_job_cards_import_batch_id ON maintenance_job_cards (import_batch_id);

CREATE INDEX ix_maintenance_job_cards_maintenance_type_id ON maintenance_job_cards (maintenance_type_id);

CREATE INDEX ix_maintenance_job_cards_txn_hash ON maintenance_job_cards (txn_hash);

CREATE INDEX ix_maintenance_job_cards_vendor_id ON maintenance_job_cards (vendor_id);

CREATE INDEX ix_maintenance_job_cards_workshop_location_id ON maintenance_job_cards (workshop_location_id);

CREATE INDEX ix_mjc_vehicle_date ON maintenance_job_cards (vehicle_id, job_date);

CREATE TABLE odometer_readings (
    vehicle_id BIGINT NOT NULL, 
    reading_at DATETIME NOT NULL, 
    reading NUMERIC(12, 1) NOT NULL, 
    source_module VARCHAR(30) NOT NULL, 
    source_entity_id BIGINT, 
    is_override BOOL NOT NULL, 
    override_reason VARCHAR(500), 
    remarks VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_odometer_readings PRIMARY KEY (id), 
    CONSTRAINT fk_odometer_readings_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
);

CREATE INDEX ix_odo_vehicle_date ON odometer_readings (vehicle_id, reading_at);

CREATE TABLE statement_import_errors (
    batch_id BIGINT NOT NULL, 
    source_row INTEGER, 
    source_column VARCHAR(20), 
    target_field VARCHAR(60), 
    original_value VARCHAR(500), 
    error_type VARCHAR(30) NOT NULL, 
    error_message VARCHAR(500) NOT NULL, 
    suggested_correction VARCHAR(255), 
    severity VARCHAR(10) NOT NULL, 
    resolved BOOL NOT NULL, 
    resolved_by BIGINT, 
    resolved_at DATETIME, 
    resolution_notes VARCHAR(500), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_statement_import_errors PRIMARY KEY (id), 
    CONSTRAINT fk_statement_import_errors_batch_id_statement_import_batches FOREIGN KEY(batch_id) REFERENCES statement_import_batches (id) ON DELETE CASCADE
);

CREATE INDEX ix_statement_import_errors_batch_id ON statement_import_errors (batch_id);

CREATE INDEX ix_statement_import_errors_resolved ON statement_import_errors (resolved);

CREATE TABLE statement_import_rows (
    batch_id BIGINT NOT NULL, 
    source_row INTEGER NOT NULL, 
    raw_values JSON, 
    normalized_values JSON, 
    row_hash VARCHAR(64), 
    status VARCHAR(20) NOT NULL, 
    target_table VARCHAR(60), 
    target_id BIGINT, 
    messages TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_statement_import_rows PRIMARY KEY (id), 
    CONSTRAINT fk_statement_import_rows_batch_id_statement_import_batches FOREIGN KEY(batch_id) REFERENCES statement_import_batches (id) ON DELETE CASCADE
);

CREATE INDEX ix_sir_batch_row ON statement_import_rows (batch_id, source_row);

CREATE TABLE toll_transactions (
    provider_id BIGINT NOT NULL, 
    transaction_id VARCHAR(80) NOT NULL, 
    txn_date DATE NOT NULL, 
    txn_time TIME, 
    txn_datetime DATETIME, 
    vehicle_id BIGINT, 
    registration_raw VARCHAR(30), 
    registration_normalized VARCHAR(20), 
    toll_plaza_id BIGINT, 
    plaza_external_id_raw VARCHAR(40), 
    plaza_code_raw VARCHAR(40), 
    plaza_name_raw VARCHAR(200), 
    amount NUMERIC(18, 2) NOT NULL, 
    direction VARCHAR(20), 
    fastag_id VARCHAR(40), 
    lane VARCHAR(20), 
    txn_kind VARCHAR(10) NOT NULL, 
    cost_center_id BIGINT, 
    status VARCHAR(20) NOT NULL, 
    vehicle_match_status VARCHAR(20) NOT NULL, 
    plaza_match_status VARCHAR(20) NOT NULL, 
    review_notes VARCHAR(500), 
    remarks VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    source_type VARCHAR(10) NOT NULL, 
    source_reference VARCHAR(255), 
    source_file VARCHAR(255), 
    source_sheet VARCHAR(100), 
    source_row INTEGER, 
    import_batch_id BIGINT, 
    txn_hash VARCHAR(64), 
    CONSTRAINT pk_toll_transactions PRIMARY KEY (id), 
    CONSTRAINT fk_toll_transactions_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_toll_transactions_import_batch_id_statement_import_batches FOREIGN KEY(import_batch_id) REFERENCES statement_import_batches (id), 
    CONSTRAINT fk_toll_transactions_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT fk_toll_transactions_toll_plaza_id_toll_plazas FOREIGN KEY(toll_plaza_id) REFERENCES toll_plazas (id), 
    CONSTRAINT fk_toll_transactions_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT uq_toll_provider_txn UNIQUE (provider_id, transaction_id)
);

CREATE INDEX ix_toll_status ON toll_transactions (status);

CREATE INDEX ix_toll_transactions_cost_center_id ON toll_transactions (cost_center_id);

CREATE INDEX ix_toll_transactions_import_batch_id ON toll_transactions (import_batch_id);

CREATE INDEX ix_toll_transactions_registration_normalized ON toll_transactions (registration_normalized);

CREATE INDEX ix_toll_transactions_toll_plaza_id ON toll_transactions (toll_plaza_id);

CREATE INDEX ix_toll_transactions_txn_hash ON toll_transactions (txn_hash);

CREATE INDEX ix_toll_vehicle_date ON toll_transactions (vehicle_id, txn_date);

CREATE TABLE toll_vehicle_mappings (
    provider_id BIGINT NOT NULL, 
    external_vehicle_number VARCHAR(30), 
    external_vehicle_id VARCHAR(60), 
    fastag_id VARCHAR(40), 
    vehicle_id BIGINT NOT NULL, 
    effective_from DATE, 
    effective_to DATE, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_toll_vehicle_mappings PRIMARY KEY (id), 
    CONSTRAINT fk_toll_vehicle_mappings_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT fk_toll_vehicle_mappings_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
);

CREATE INDEX ix_toll_vehicle_mappings_fastag_id ON toll_vehicle_mappings (fastag_id);

CREATE INDEX ix_toll_vehicle_mappings_is_active ON toll_vehicle_mappings (is_active);

CREATE INDEX ix_toll_vehicle_mappings_vehicle_id ON toll_vehicle_mappings (vehicle_id);

CREATE INDEX ix_tvm_lookup ON toll_vehicle_mappings (provider_id, external_vehicle_number);

CREATE TABLE tyres (
    serial_number VARCHAR(50) NOT NULL, 
    tyre_code VARCHAR(30), 
    brand VARCHAR(60) NOT NULL, 
    model VARCHAR(60), 
    size VARCHAR(40) NOT NULL, 
    tyre_type VARCHAR(30), 
    pattern VARCHAR(60), 
    ply_rating VARCHAR(10), 
    load_index VARCHAR(10), 
    speed_rating VARCHAR(5), 
    original_tread_depth NUMERIC(6, 2), 
    current_tread_depth NUMERIC(6, 2), 
    purchase_date DATE, 
    supplier_id BIGINT, 
    invoice_number VARCHAR(50), 
    cost NUMERIC(18, 2), 
    gst_amount NUMERIC(18, 2), 
    discount_amount NUMERIC(18, 2), 
    total_cost NUMERIC(18, 2), 
    warranty_km INTEGER, 
    warranty_months INTEGER, 
    warranty_expiry_date DATE, 
    manufacture_date DATE, 
    current_status VARCHAR(30) NOT NULL, 
    current_vehicle_id BIGINT, 
    current_position_id BIGINT, 
    current_location_id BIGINT, 
    current_install_odometer NUMERIC(12, 1), 
    current_odometer NUMERIC(12, 1), 
    total_km NUMERIC(12, 1) NOT NULL, 
    retread_count INTEGER NOT NULL, 
    scrap_date DATE, 
    scrap_reason VARCHAR(255), 
    scrap_value NUMERIC(18, 2), 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_tyres PRIMARY KEY (id), 
    CONSTRAINT fk_tyres_current_location_id_tyre_locations FOREIGN KEY(current_location_id) REFERENCES tyre_locations (id), 
    CONSTRAINT fk_tyres_current_position_id_tyre_positions FOREIGN KEY(current_position_id) REFERENCES tyre_positions (id), 
    CONSTRAINT fk_tyres_current_vehicle_id_vehicles FOREIGN KEY(current_vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT fk_tyres_supplier_id_vendors FOREIGN KEY(supplier_id) REFERENCES vendors (id), 
    CONSTRAINT uq_tyres_serial_number UNIQUE (serial_number), 
    CONSTRAINT uq_tyres_tyre_code UNIQUE (tyre_code)
);

CREATE INDEX ix_tyre_status ON tyres (current_status);

CREATE INDEX ix_tyres_brand ON tyres (brand);

CREATE INDEX ix_tyres_current_location_id ON tyres (current_location_id);

CREATE INDEX ix_tyres_current_position_id ON tyres (current_position_id);

CREATE INDEX ix_tyres_current_vehicle_id ON tyres (current_vehicle_id);

CREATE INDEX ix_tyres_is_active ON tyres (is_active);

CREATE INDEX ix_tyres_size ON tyres (size);

CREATE INDEX ix_tyres_supplier_id ON tyres (supplier_id);

CREATE TABLE vehicle_cost_center_history (
    vehicle_id BIGINT NOT NULL, 
    old_cost_category_id BIGINT, 
    new_cost_category_id BIGINT NOT NULL, 
    old_sub_category_id BIGINT, 
    new_sub_category_id BIGINT NOT NULL, 
    old_cost_center_id BIGINT, 
    new_cost_center_id BIGINT NOT NULL, 
    effective_from DATE NOT NULL, 
    effective_to DATE, 
    reason VARCHAR(500), 
    changed_by BIGINT, 
    changed_at DATETIME NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_vehicle_cost_center_history PRIMARY KEY (id), 
    CONSTRAINT fk_vehicle_cost_center_history_new_cost_category_id_cost_715e FOREIGN KEY(new_cost_category_id) REFERENCES cost_categories (id), 
    CONSTRAINT fk_vehicle_cost_center_history_new_cost_center_id_cost_centers FOREIGN KEY(new_cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_vehicle_cost_center_history_new_sub_category_id_vehic_e230 FOREIGN KEY(new_sub_category_id) REFERENCES vehicle_sub_categories (id), 
    CONSTRAINT fk_vehicle_cost_center_history_old_cost_category_id_cost_422d FOREIGN KEY(old_cost_category_id) REFERENCES cost_categories (id), 
    CONSTRAINT fk_vehicle_cost_center_history_old_cost_center_id_cost_centers FOREIGN KEY(old_cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_vehicle_cost_center_history_old_sub_category_id_vehic_0eb8 FOREIGN KEY(old_sub_category_id) REFERENCES vehicle_sub_categories (id), 
    CONSTRAINT fk_vehicle_cost_center_history_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
);

CREATE INDEX ix_vcch_vehicle_eff ON vehicle_cost_center_history (vehicle_id, effective_from);

CREATE INDEX ix_vehicle_cost_center_history_vehicle_id ON vehicle_cost_center_history (vehicle_id);

CREATE TABLE vehicle_fuels (
    vehicle_id BIGINT NOT NULL, 
    fuel_type_id BIGINT NOT NULL, 
    is_primary BOOL NOT NULL, 
    tank_capacity NUMERIC(18, 3), 
    effective_from DATE, 
    effective_to DATE, 
    is_active BOOL NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_vehicle_fuels PRIMARY KEY (id), 
    CONSTRAINT fk_vehicle_fuels_fuel_type_id_fuel_types FOREIGN KEY(fuel_type_id) REFERENCES fuel_types (id), 
    CONSTRAINT fk_vehicle_fuels_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id) ON DELETE CASCADE
);

CREATE INDEX ix_vehicle_fuels_fuel_type_id ON vehicle_fuels (fuel_type_id);

CREATE INDEX ix_vehicle_fuels_vehicle_id ON vehicle_fuels (vehicle_id);

CREATE TABLE vehicle_renewal_assignments (
    vehicle_id BIGINT, 
    driver_id BIGINT, 
    renewal_type_id BIGINT NOT NULL, 
    renewal_rule_id BIGINT, 
    reference_label VARCHAR(100) NOT NULL, 
    is_applicable BOOL NOT NULL, 
    reminder_days VARCHAR(100), 
    remarks VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    is_active BOOL NOT NULL, 
    deleted_at DATETIME, 
    CONSTRAINT pk_vehicle_renewal_assignments PRIMARY KEY (id), 
    CONSTRAINT fk_vehicle_renewal_assignments_driver_id_drivers FOREIGN KEY(driver_id) REFERENCES drivers (id), 
    CONSTRAINT fk_vehicle_renewal_assignments_renewal_rule_id_renewal_rules FOREIGN KEY(renewal_rule_id) REFERENCES renewal_rules (id), 
    CONSTRAINT fk_vehicle_renewal_assignments_renewal_type_id_renewal_types FOREIGN KEY(renewal_type_id) REFERENCES renewal_types (id), 
    CONSTRAINT fk_vehicle_renewal_assignments_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT uq_vehicle_renewal_assignments_vehicle_id_renewal_type_i_2dfa UNIQUE (vehicle_id, renewal_type_id, reference_label)
);

CREATE INDEX ix_vehicle_renewal_assignments_driver_id ON vehicle_renewal_assignments (driver_id);

CREATE INDEX ix_vehicle_renewal_assignments_is_active ON vehicle_renewal_assignments (is_active);

CREATE INDEX ix_vehicle_renewal_assignments_renewal_rule_id ON vehicle_renewal_assignments (renewal_rule_id);

CREATE INDEX ix_vehicle_renewal_assignments_renewal_type_id ON vehicle_renewal_assignments (renewal_type_id);

CREATE INDEX ix_vehicle_renewal_assignments_vehicle_id ON vehicle_renewal_assignments (vehicle_id);

CREATE TABLE vehicle_sub_category_attribute_values (
    vehicle_id BIGINT NOT NULL, 
    attribute_id BIGINT NOT NULL, 
    value_text VARCHAR(500), 
    value_number NUMERIC(18, 4), 
    value_bool BOOL, 
    value_date DATE, 
    updated_at DATETIME, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_vehicle_sub_category_attribute_values PRIMARY KEY (id), 
    CONSTRAINT fk_vehicle_sub_category_attribute_values_attribute_id_su_7e38 FOREIGN KEY(attribute_id) REFERENCES sub_category_attributes (id), 
    CONSTRAINT fk_vehicle_sub_category_attribute_values_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id) ON DELETE CASCADE, 
    CONSTRAINT uq_vehicle_sub_category_attribute_values_vehicle_id_attribute_id UNIQUE (vehicle_id, attribute_id)
);

CREATE INDEX ix_vehicle_sub_category_attribute_values_attribute_id ON vehicle_sub_category_attribute_values (attribute_id);

CREATE INDEX ix_vehicle_sub_category_attribute_values_vehicle_id ON vehicle_sub_category_attribute_values (vehicle_id);

CREATE TABLE bank_transaction_allocations (
    bank_transaction_id BIGINT NOT NULL, 
    cost_center_id BIGINT NOT NULL, 
    expense_type_id BIGINT, 
    credit_type_id BIGINT, 
    vendor_id BIGINT, 
    vehicle_id BIGINT, 
    amount NUMERIC(18, 2) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    remarks VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_bank_transaction_allocations PRIMARY KEY (id), 
    CONSTRAINT fk_bank_transaction_allocations_bank_transaction_id_bank_3104 FOREIGN KEY(bank_transaction_id) REFERENCES bank_transactions (id), 
    CONSTRAINT fk_bank_transaction_allocations_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_bank_transaction_allocations_credit_type_id_credit_types FOREIGN KEY(credit_type_id) REFERENCES credit_types (id), 
    CONSTRAINT fk_bank_transaction_allocations_expense_type_id_expense_types FOREIGN KEY(expense_type_id) REFERENCES expense_types (id), 
    CONSTRAINT fk_bank_transaction_allocations_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT fk_bank_transaction_allocations_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES vendors (id)
);

CREATE INDEX ix_bank_transaction_allocations_bank_transaction_id ON bank_transaction_allocations (bank_transaction_id);

CREATE INDEX ix_bank_transaction_allocations_cost_center_id ON bank_transaction_allocations (cost_center_id);

CREATE INDEX ix_bank_transaction_allocations_credit_type_id ON bank_transaction_allocations (credit_type_id);

CREATE INDEX ix_bank_transaction_allocations_expense_type_id ON bank_transaction_allocations (expense_type_id);

CREATE INDEX ix_bank_transaction_allocations_vehicle_id ON bank_transaction_allocations (vehicle_id);

CREATE INDEX ix_bank_transaction_allocations_vendor_id ON bank_transaction_allocations (vendor_id);

CREATE TABLE expense_allocations (
    expense_id BIGINT NOT NULL, 
    cost_center_id BIGINT NOT NULL, 
    vehicle_id BIGINT, 
    amount NUMERIC(18, 2) NOT NULL, 
    remarks VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_expense_allocations PRIMARY KEY (id), 
    CONSTRAINT fk_expense_allocations_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_expense_allocations_expense_id_expense_transactions FOREIGN KEY(expense_id) REFERENCES expense_transactions (id) ON DELETE CASCADE, 
    CONSTRAINT fk_expense_allocations_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
);

CREATE INDEX ix_expense_allocations_cost_center_id ON expense_allocations (cost_center_id);

CREATE INDEX ix_expense_allocations_expense_id ON expense_allocations (expense_id);

CREATE INDEX ix_expense_allocations_vehicle_id ON expense_allocations (vehicle_id);

CREATE TABLE insurance_history (
    policy_id BIGINT NOT NULL, 
    action VARCHAR(30) NOT NULL, 
    old_status VARCHAR(20), 
    new_status VARCHAR(20), 
    snapshot JSON, 
    remarks VARCHAR(500), 
    changed_by BIGINT, 
    changed_at DATETIME NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_insurance_history PRIMARY KEY (id), 
    CONSTRAINT fk_insurance_history_policy_id_insurance_policies FOREIGN KEY(policy_id) REFERENCES insurance_policies (id)
);

CREATE INDEX ix_insurance_history_policy_id ON insurance_history (policy_id);

CREATE TABLE invoice_allocations (
    invoice_id BIGINT NOT NULL, 
    vehicle_id BIGINT, 
    cost_center_id BIGINT NOT NULL, 
    amount NUMERIC(18, 2) NOT NULL, 
    remarks VARCHAR(255), 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_invoice_allocations PRIMARY KEY (id), 
    CONSTRAINT fk_invoice_allocations_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_invoice_allocations_invoice_id_invoices FOREIGN KEY(invoice_id) REFERENCES invoices (id) ON DELETE CASCADE, 
    CONSTRAINT fk_invoice_allocations_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
);

CREATE INDEX ix_invoice_allocations_cost_center_id ON invoice_allocations (cost_center_id);

CREATE INDEX ix_invoice_allocations_invoice_id ON invoice_allocations (invoice_id);

CREATE INDEX ix_invoice_allocations_vehicle_id ON invoice_allocations (vehicle_id);

CREATE TABLE maintenance_labour (
    job_card_id BIGINT NOT NULL, 
    description VARCHAR(255) NOT NULL, 
    technician VARCHAR(100), 
    hours NUMERIC(8, 2), 
    rate NUMERIC(18, 2) NOT NULL, 
    amount NUMERIC(18, 2) NOT NULL, 
    tax_amount NUMERIC(18, 2) NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_maintenance_labour PRIMARY KEY (id), 
    CONSTRAINT fk_maintenance_labour_job_card_id_maintenance_job_cards FOREIGN KEY(job_card_id) REFERENCES maintenance_job_cards (id) ON DELETE CASCADE
);

CREATE INDEX ix_maintenance_labour_job_card_id ON maintenance_labour (job_card_id);

CREATE TABLE maintenance_parts (
    job_card_id BIGINT NOT NULL, 
    part_name VARCHAR(150) NOT NULL, 
    part_number VARCHAR(60), 
    quantity NUMERIC(18, 3) NOT NULL, 
    unit_id BIGINT, 
    rate NUMERIC(18, 2) NOT NULL, 
    amount NUMERIC(18, 2) NOT NULL, 
    tax_amount NUMERIC(18, 2) NOT NULL, 
    is_consumable BOOL NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_maintenance_parts PRIMARY KEY (id), 
    CONSTRAINT fk_maintenance_parts_job_card_id_maintenance_job_cards FOREIGN KEY(job_card_id) REFERENCES maintenance_job_cards (id) ON DELETE CASCADE, 
    CONSTRAINT fk_maintenance_parts_unit_id_units FOREIGN KEY(unit_id) REFERENCES units (id)
);

CREATE INDEX ix_maintenance_parts_job_card_id ON maintenance_parts (job_card_id);

CREATE INDEX ix_maintenance_parts_unit_id ON maintenance_parts (unit_id);

CREATE TABLE reconciliation_history (
    bank_transaction_id BIGINT NOT NULL, 
    action VARCHAR(30) NOT NULL, 
    old_status VARCHAR(20), 
    new_status VARCHAR(20), 
    amount NUMERIC(18, 2), 
    link_id BIGINT, 
    allocation_id BIGINT, 
    snapshot JSON, 
    remarks VARCHAR(500), 
    performed_by BIGINT, 
    performed_at DATETIME NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_reconciliation_history PRIMARY KEY (id), 
    CONSTRAINT fk_reconciliation_history_bank_transaction_id_bank_transactions FOREIGN KEY(bank_transaction_id) REFERENCES bank_transactions (id)
);

CREATE INDEX ix_reconciliation_history_bank_transaction_id ON reconciliation_history (bank_transaction_id);

CREATE TABLE tyre_fitments (
    tyre_id BIGINT NOT NULL, 
    vehicle_id BIGINT NOT NULL, 
    position_id BIGINT NOT NULL, 
    installed_at DATETIME NOT NULL, 
    install_odometer NUMERIC(12, 1) NOT NULL, 
    install_tread_depth NUMERIC(6, 2), 
    removed_at DATETIME, 
    removal_odometer NUMERIC(12, 1), 
    removal_tread_depth NUMERIC(6, 2), 
    running_km NUMERIC(12, 1), 
    current_slot INTEGER, 
    install_movement_id BIGINT, 
    removal_movement_id BIGINT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_tyre_fitments PRIMARY KEY (id), 
    CONSTRAINT fk_tyre_fitments_position_id_tyre_positions FOREIGN KEY(position_id) REFERENCES tyre_positions (id), 
    CONSTRAINT fk_tyre_fitments_tyre_id_tyres FOREIGN KEY(tyre_id) REFERENCES tyres (id), 
    CONSTRAINT fk_tyre_fitments_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT uq_tyre_single_fitment UNIQUE (tyre_id, current_slot), 
    CONSTRAINT uq_tyre_position_occupancy UNIQUE (vehicle_id, position_id, current_slot)
);

CREATE INDEX ix_tyre_fitments_position_id ON tyre_fitments (position_id);

CREATE INDEX ix_tyre_fitments_tyre_id ON tyre_fitments (tyre_id);

CREATE INDEX ix_tyre_fitments_vehicle_id ON tyre_fitments (vehicle_id);

CREATE TABLE tyre_inspections (
    tyre_id BIGINT NOT NULL, 
    inspection_date DATE NOT NULL, 
    vehicle_id BIGINT, 
    position_id BIGINT, 
    odometer NUMERIC(12, 1), 
    tread_depth NUMERIC(6, 2), 
    pressure_psi NUMERIC(6, 1), 
    `condition` VARCHAR(30), 
    damage VARCHAR(255), 
    recommended_action VARCHAR(100), 
    inspector VARCHAR(100), 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_tyre_inspections PRIMARY KEY (id), 
    CONSTRAINT fk_tyre_inspections_position_id_tyre_positions FOREIGN KEY(position_id) REFERENCES tyre_positions (id), 
    CONSTRAINT fk_tyre_inspections_tyre_id_tyres FOREIGN KEY(tyre_id) REFERENCES tyres (id), 
    CONSTRAINT fk_tyre_inspections_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
);

CREATE INDEX ix_tyre_inspections_position_id ON tyre_inspections (position_id);

CREATE INDEX ix_tyre_inspections_tyre_id ON tyre_inspections (tyre_id);

CREATE INDEX ix_tyre_inspections_vehicle_id ON tyre_inspections (vehicle_id);

CREATE TABLE tyre_maintenance (
    tyre_id BIGINT NOT NULL, 
    maintenance_type VARCHAR(30) NOT NULL, 
    maintenance_date DATE NOT NULL, 
    vehicle_id BIGINT, 
    position_id BIGINT, 
    odometer NUMERIC(12, 1), 
    vendor_id BIGINT, 
    cost NUMERIC(18, 2) NOT NULL, 
    gst_amount NUMERIC(18, 2) NOT NULL, 
    invoice_number VARCHAR(50), 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_tyre_maintenance PRIMARY KEY (id), 
    CONSTRAINT fk_tyre_maintenance_position_id_tyre_positions FOREIGN KEY(position_id) REFERENCES tyre_positions (id), 
    CONSTRAINT fk_tyre_maintenance_tyre_id_tyres FOREIGN KEY(tyre_id) REFERENCES tyres (id), 
    CONSTRAINT fk_tyre_maintenance_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT fk_tyre_maintenance_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES vendors (id)
);

CREATE INDEX ix_tyre_maintenance_position_id ON tyre_maintenance (position_id);

CREATE INDEX ix_tyre_maintenance_tyre_id ON tyre_maintenance (tyre_id);

CREATE INDEX ix_tyre_maintenance_vehicle_id ON tyre_maintenance (vehicle_id);

CREATE INDEX ix_tyre_maintenance_vendor_id ON tyre_maintenance (vendor_id);

CREATE TABLE tyre_movements (
    tyre_id BIGINT NOT NULL, 
    movement_type VARCHAR(30) NOT NULL, 
    movement_date DATETIME NOT NULL, 
    from_vehicle_id BIGINT, 
    to_vehicle_id BIGINT, 
    from_location_id BIGINT, 
    to_location_id BIGINT, 
    from_position_id BIGINT, 
    to_position_id BIGINT, 
    odometer NUMERIC(12, 1), 
    to_odometer NUMERIC(12, 1), 
    tread_depth NUMERIC(6, 2), 
    running_km NUMERIC(12, 1), 
    status_before VARCHAR(30), 
    status_after VARCHAR(30), 
    reason VARCHAR(255), 
    reference VARCHAR(80), 
    performed_by VARCHAR(100), 
    is_override BOOL NOT NULL, 
    override_reason VARCHAR(500), 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_tyre_movements PRIMARY KEY (id), 
    CONSTRAINT fk_tyre_movements_from_location_id_tyre_locations FOREIGN KEY(from_location_id) REFERENCES tyre_locations (id), 
    CONSTRAINT fk_tyre_movements_from_position_id_tyre_positions FOREIGN KEY(from_position_id) REFERENCES tyre_positions (id), 
    CONSTRAINT fk_tyre_movements_from_vehicle_id_vehicles FOREIGN KEY(from_vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT fk_tyre_movements_to_location_id_tyre_locations FOREIGN KEY(to_location_id) REFERENCES tyre_locations (id), 
    CONSTRAINT fk_tyre_movements_to_position_id_tyre_positions FOREIGN KEY(to_position_id) REFERENCES tyre_positions (id), 
    CONSTRAINT fk_tyre_movements_to_vehicle_id_vehicles FOREIGN KEY(to_vehicle_id) REFERENCES vehicles (id), 
    CONSTRAINT fk_tyre_movements_tyre_id_tyres FOREIGN KEY(tyre_id) REFERENCES tyres (id)
);

CREATE INDEX ix_tm_tyre_date ON tyre_movements (tyre_id, movement_date);

CREATE INDEX ix_tyre_movements_from_location_id ON tyre_movements (from_location_id);

CREATE INDEX ix_tyre_movements_from_position_id ON tyre_movements (from_position_id);

CREATE INDEX ix_tyre_movements_from_vehicle_id ON tyre_movements (from_vehicle_id);

CREATE INDEX ix_tyre_movements_movement_type ON tyre_movements (movement_type);

CREATE INDEX ix_tyre_movements_to_location_id ON tyre_movements (to_location_id);

CREATE INDEX ix_tyre_movements_to_position_id ON tyre_movements (to_position_id);

CREATE INDEX ix_tyre_movements_to_vehicle_id ON tyre_movements (to_vehicle_id);

CREATE TABLE tyre_retreading (
    tyre_id BIGINT NOT NULL, 
    vendor_id BIGINT, 
    sent_date DATE NOT NULL, 
    return_date DATE, 
    odometer NUMERIC(12, 1), 
    tread_condition VARCHAR(100), 
    tread_depth NUMERIC(6, 2), 
    retread_type VARCHAR(30), 
    cost NUMERIC(18, 2), 
    gst_amount NUMERIC(18, 2), 
    invoice_number VARCHAR(50), 
    new_tread_depth NUMERIC(6, 2), 
    new_pattern VARCHAR(60), 
    retread_serial VARCHAR(50), 
    warranty_km INTEGER, 
    warranty_months INTEGER, 
    status VARCHAR(20) NOT NULL, 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_tyre_retreading PRIMARY KEY (id), 
    CONSTRAINT fk_tyre_retreading_tyre_id_tyres FOREIGN KEY(tyre_id) REFERENCES tyres (id), 
    CONSTRAINT fk_tyre_retreading_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES vendors (id)
);

CREATE INDEX ix_tyre_retreading_tyre_id ON tyre_retreading (tyre_id);

CREATE INDEX ix_tyre_retreading_vendor_id ON tyre_retreading (vendor_id);

CREATE TABLE tyre_warranty_claims (
    tyre_id BIGINT NOT NULL, 
    warranty_provider_id BIGINT, 
    vendor_id BIGINT, 
    claim_number VARCHAR(50) NOT NULL, 
    claim_date DATE NOT NULL, 
    failure_date DATE, 
    failure_reason VARCHAR(255), 
    evidence TEXT, 
    km_at_failure NUMERIC(12, 1), 
    tread_depth_at_failure NUMERIC(6, 2), 
    claim_amount NUMERIC(18, 2), 
    approved_amount NUMERIC(18, 2), 
    resolution_type VARCHAR(20), 
    replacement_tyre_id BIGINT, 
    status VARCHAR(20) NOT NULL, 
    resolution_date DATE, 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_tyre_warranty_claims PRIMARY KEY (id), 
    CONSTRAINT fk_tyre_warranty_claims_replacement_tyre_id_tyres FOREIGN KEY(replacement_tyre_id) REFERENCES tyres (id), 
    CONSTRAINT fk_tyre_warranty_claims_tyre_id_tyres FOREIGN KEY(tyre_id) REFERENCES tyres (id), 
    CONSTRAINT fk_tyre_warranty_claims_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    CONSTRAINT fk_tyre_warranty_claims_warranty_provider_id_vendors FOREIGN KEY(warranty_provider_id) REFERENCES vendors (id), 
    CONSTRAINT uq_tyre_warranty_claims_claim_number UNIQUE (claim_number)
);

CREATE INDEX ix_tyre_warranty_claims_replacement_tyre_id ON tyre_warranty_claims (replacement_tyre_id);

CREATE INDEX ix_tyre_warranty_claims_tyre_id ON tyre_warranty_claims (tyre_id);

CREATE INDEX ix_tyre_warranty_claims_vendor_id ON tyre_warranty_claims (vendor_id);

CREATE INDEX ix_tyre_warranty_claims_warranty_provider_id ON tyre_warranty_claims (warranty_provider_id);

CREATE TABLE vehicle_renewals (
    assignment_id BIGINT, 
    vehicle_id BIGINT, 
    driver_id BIGINT, 
    renewal_type_id BIGINT NOT NULL, 
    certificate_number VARCHAR(80), 
    issue_date DATE, 
    start_date DATE, 
    expiry_date DATE, 
    renewal_date DATE, 
    amount NUMERIC(18, 2), 
    tax_amount NUMERIC(18, 2), 
    total_amount NUMERIC(18, 2), 
    provider_id BIGINT, 
    authority VARCHAR(150), 
    document_number VARCHAR(80), 
    status VARCHAR(20) NOT NULL, 
    payment_status VARCHAR(20) NOT NULL, 
    cost_center_id BIGINT, 
    is_current BOOL NOT NULL, 
    previous_renewal_id BIGINT, 
    remarks TEXT, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    created_by BIGINT, 
    updated_by BIGINT, 
    CONSTRAINT pk_vehicle_renewals PRIMARY KEY (id), 
    CONSTRAINT fk_vehicle_renewals_assignment_id_vehicle_renewal_assignments FOREIGN KEY(assignment_id) REFERENCES vehicle_renewal_assignments (id), 
    CONSTRAINT fk_vehicle_renewals_cost_center_id_cost_centers FOREIGN KEY(cost_center_id) REFERENCES cost_centers (id), 
    CONSTRAINT fk_vehicle_renewals_driver_id_drivers FOREIGN KEY(driver_id) REFERENCES drivers (id), 
    CONSTRAINT fk_vehicle_renewals_previous_renewal_id_vehicle_renewals FOREIGN KEY(previous_renewal_id) REFERENCES vehicle_renewals (id), 
    CONSTRAINT fk_vehicle_renewals_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id), 
    CONSTRAINT fk_vehicle_renewals_renewal_type_id_renewal_types FOREIGN KEY(renewal_type_id) REFERENCES renewal_types (id), 
    CONSTRAINT fk_vehicle_renewals_vehicle_id_vehicles FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
);

CREATE INDEX ix_vehicle_renewals_assignment_id ON vehicle_renewals (assignment_id);

CREATE INDEX ix_vehicle_renewals_certificate_number ON vehicle_renewals (certificate_number);

CREATE INDEX ix_vehicle_renewals_cost_center_id ON vehicle_renewals (cost_center_id);

CREATE INDEX ix_vehicle_renewals_driver_id ON vehicle_renewals (driver_id);

CREATE INDEX ix_vehicle_renewals_is_current ON vehicle_renewals (is_current);

CREATE INDEX ix_vehicle_renewals_previous_renewal_id ON vehicle_renewals (previous_renewal_id);

CREATE INDEX ix_vehicle_renewals_provider_id ON vehicle_renewals (provider_id);

CREATE INDEX ix_vehicle_renewals_renewal_type_id ON vehicle_renewals (renewal_type_id);

CREATE INDEX ix_vehicle_renewals_status ON vehicle_renewals (status);

CREATE INDEX ix_vehicle_renewals_vehicle_id ON vehicle_renewals (vehicle_id);

CREATE INDEX ix_vr_expiry_status ON vehicle_renewals (expiry_date, status);

CREATE TABLE renewal_history (
    renewal_id BIGINT NOT NULL, 
    action VARCHAR(30) NOT NULL, 
    old_status VARCHAR(20), 
    new_status VARCHAR(20), 
    snapshot JSON, 
    remarks VARCHAR(500), 
    changed_by BIGINT, 
    changed_at DATETIME NOT NULL, 
    id BIGINT NOT NULL AUTO_INCREMENT, 
    CONSTRAINT pk_renewal_history PRIMARY KEY (id), 
    CONSTRAINT fk_renewal_history_renewal_id_vehicle_renewals FOREIGN KEY(renewal_id) REFERENCES vehicle_renewals (id)
);

CREATE INDEX ix_renewal_history_renewal_id ON renewal_history (renewal_id);

INSERT INTO alembic_version (version_num) VALUES ('0001');

