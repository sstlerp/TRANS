-- TRANS ERP — database ERP_LOGISTICS — rollback of migration 0001 (initial schema — all ERP tables (organisation, fleet, compliance, finance, imports,)
-- Generated with: alembic downgrade 0001:base --sql      Take a backup first (scripts/backup_mysql.sh).
USE `ERP_LOGISTICS`;

-- Running downgrade 0001 -> 

SET FOREIGN_KEY_CHECKS=0;

DROP TABLE IF EXISTS renewal_history;

DROP TABLE IF EXISTS vehicle_renewals;

DROP TABLE IF EXISTS tyre_warranty_claims;

DROP TABLE IF EXISTS tyre_retreading;

DROP TABLE IF EXISTS tyre_movements;

DROP TABLE IF EXISTS tyre_maintenance;

DROP TABLE IF EXISTS tyre_inspections;

DROP TABLE IF EXISTS tyre_fitments;

DROP TABLE IF EXISTS reconciliation_history;

DROP TABLE IF EXISTS maintenance_parts;

DROP TABLE IF EXISTS maintenance_labour;

DROP TABLE IF EXISTS invoice_allocations;

DROP TABLE IF EXISTS insurance_history;

DROP TABLE IF EXISTS expense_allocations;

DROP TABLE IF EXISTS bank_transaction_allocations;

DROP TABLE IF EXISTS vehicle_sub_category_attribute_values;

DROP TABLE IF EXISTS vehicle_renewal_assignments;

DROP TABLE IF EXISTS vehicle_fuels;

DROP TABLE IF EXISTS vehicle_cost_center_history;

DROP TABLE IF EXISTS tyres;

DROP TABLE IF EXISTS toll_vehicle_mappings;

DROP TABLE IF EXISTS toll_transactions;

DROP TABLE IF EXISTS statement_import_rows;

DROP TABLE IF EXISTS statement_import_errors;

DROP TABLE IF EXISTS odometer_readings;

DROP TABLE IF EXISTS maintenance_job_cards;

DROP TABLE IF EXISTS invoices;

DROP TABLE IF EXISTS insurance_policies;

DROP TABLE IF EXISTS fuel_transactions;

DROP TABLE IF EXISTS fuel_cards;

DROP TABLE IF EXISTS expense_transactions;

DROP TABLE IF EXISTS contract_vehicle_allocations;

DROP TABLE IF EXISTS bank_transactions;

DROP TABLE IF EXISTS vehicles;

DROP TABLE IF EXISTS statement_import_batches;

DROP TABLE IF EXISTS drivers;

DROP TABLE IF EXISTS contracts;

DROP TABLE IF EXISTS tyre_locations;

DROP TABLE IF EXISTS statement_template_columns;

DROP TABLE IF EXISTS cost_centers;

DROP TABLE IF EXISTS bank_accounts;

DROP TABLE IF EXISTS value_mappings;

DROP TABLE IF EXISTS user_branches;

DROP TABLE IF EXISTS toll_plazas;

DROP TABLE IF EXISTS toll_api_configurations;

DROP TABLE IF EXISTS statement_import_templates;

DROP TABLE IF EXISTS locations;

DROP TABLE IF EXISTS fuel_stations;

DROP TABLE IF EXISTS departments;

DROP TABLE IF EXISTS banks;

DROP TABLE IF EXISTS sub_category_attributes;

DROP TABLE IF EXISTS rtos;

DROP TABLE IF EXISTS renewal_rules;

DROP TABLE IF EXISTS providers;

DROP TABLE IF EXISTS branches;

DROP TABLE IF EXISTS approval_actions;

DROP TABLE IF EXISTS vendors;

DROP TABLE IF EXISTS vehicle_tyre_position_configurations;

DROP TABLE IF EXISTS vehicle_sub_categories;

DROP TABLE IF EXISTS user_roles;

DROP TABLE IF EXISTS role_permissions;

DROP TABLE IF EXISTS renewal_types;

DROP TABLE IF EXISTS notification_rules;

DROP TABLE IF EXISTS fuel_types;

DROP TABLE IF EXISTS document_links;

DROP TABLE IF EXISTS districts;

DROP TABLE IF EXISTS customers;

DROP TABLE IF EXISTS companies;

DROP TABLE IF EXISTS approval_requests;

DROP TABLE IF EXISTS users;

DROP TABLE IF EXISTS units;

DROP TABLE IF EXISTS tyre_positions;

DROP TABLE IF EXISTS tyre_layouts;

DROP TABLE IF EXISTS transaction_types;

DROP TABLE IF EXISTS states;

DROP TABLE IF EXISTS roles;

DROP TABLE IF EXISTS permissions;

DROP TABLE IF EXISTS notifications;

DROP TABLE IF EXISTS matching_rules;

DROP TABLE IF EXISTS maintenance_types;

DROP TABLE IF EXISTS lookup_values;

DROP TABLE IF EXISTS financial_transaction_links;

DROP TABLE IF EXISTS expense_types;

DROP TABLE IF EXISTS documents;

DROP TABLE IF EXISTS credit_types;

DROP TABLE IF EXISTS cost_categories;

DROP TABLE IF EXISTS business_rules;

DROP TABLE IF EXISTS background_jobs;

DROP TABLE IF EXISTS audit_logs;

DROP TABLE IF EXISTS approval_rules;

SET FOREIGN_KEY_CHECKS=1;

DELETE FROM alembic_version WHERE alembic_version.version_num = '0001';

