# Acceptance criteria traceability (spec §75)

`tests/…` refer to automated tests (run on MySQL and SQLite). UI items were additionally exercised in a headless
browser against a seeded MySQL instance.

| # | Criterion | Implementation | Verified by |
|---|---|---|---|
| 1 | Create Truck and Trailer categories | `cost_categories` master (seeded, editable) | test_fleet::test_admin_creates_categories_subcategories_and_attributes |
| 2 | Create LPG / Open Body / Container sub-categories | `vehicle_sub_categories` master | same |
| 3 | Configure technical sub-category attributes | `sub_category_attributes` (type, unit, mandatory, order, dropdown, min/max) + dynamic vehicle form | same · test_mandatory_attribute_enforced |
| 4 | Vehicle becomes a cost center | `vehicles.after_save` creates `cost_centers` (type VEHICLE) | test_vehicle_becomes_cost_center_and_attributes_are_stored |
| 5 | Non-vehicle cost centers | `cost_centers.cc_type` NON_VEHICLE/COMMON/CONTRACT/OTHER | test_non_vehicle_cost_centers |
| 6 | Category changes preserve history | `vehicle_cost_center_history`, reclassify action, history-aware reports | test_reclassification_preserves_history · test_reports::test_historical_classification_in_reports |
| 7 | Multiple fuel types per vehicle | `vehicle_fuels` child grid | test_multiple_fuel_types_per_vehicle |
| 8 | Multiple insurance policies per vehicle | `insurance_policies` + history + renew | test_multiple_insurance_policies_and_renewal |
| 9 | Multiple PESO/hazardous renewals | renewal rules → multiple slots; `vehicle_renewals` per slot | test_peso_rule_creates_multiple_slots_for_lpg · test_multiple_peso_certificates_and_statuses |
| 10 | Renewal reminders | configurable reminder days (global/type/rule/slot), idempotent notifications, daily job | test_expiry_alerts_use_configurable_reminders |
| 11 | Documents for insurance/permit/fitness/PUCC | `documents` (+ versions, links), document panel on all such screens | test_renew_keeps_history_and_supports_documents · test_document_upload_validation · test_api::test_document_upload_download_access |
| 12 | Bank Excel templates configurable | templates + columns + transformations; 2 bank layouts seeded | test_bank::test_second_bank_layout_amount_with_drcr · test_imports::test_template_builder_validates_configuration |
| 13 | Bank statements can be imported | import engine BANK family | test_bank_import_credits_and_debits_all_unclassified · test_api::test_import_wizard_api_flow |
| 14 | Duplicate bank transactions detected | business hash (incl. balance/occurrence) + unique index | test_duplicate_bank_import_is_flagged_not_inserted · test_manual_bank_entry_uses_same_table_and_detects_duplicates |
| 15 | Credits matched to contract income | INVOICE_RECEIPT / CONTRACT_RECEIPT links | test_one_to_one_contract_receipt_no_double_income · test_contract_allocation_percentages_generate_invoice_split |
| 16 | Partial contract receipts | invoice status PARTIALLY_PAID / outstanding | test_partial_receipt_and_many_receipts_to_one_invoice |
| 17 | Multiple invoices matched to one receipt | one-to-many link call | test_one_receipt_to_many_invoices |
| 18 | One invoice with multiple receipts | many-to-one | test_partial_receipt_and_many_receipts_to_one_invoice |
| 19 | Cashback / rebate / refund classified separately | credit types + REFUND/CASHBACK/REBATE links, configurable treatment | test_refund_reduces_expense_not_revenue · test_cashback_classified_separately |
| 20 | Internal transfers matched | INTERNAL_TRANSFER link between own accounts, suggestion by UTR/amount/date | test_internal_transfer_matching_is_neither_income_nor_expense |
| 21 | Unmatched debits remain pending | UNMATCHED status, no auto-allocation | test_unmatched_credit_is_not_income_and_unmatched_debit_stays_pending |
| 22 | Bank debits split among cost centers | `bank_transaction_allocations` | test_multi_cost_center_allocation |
| 23 | Allocation totals validated | over-allocation always refused; balance required unless partial allowed | test_over_allocation_and_unbalanced_allocation_prevented |
| 24 | Fuel Excel layouts configurable | 2 fuel templates (IOCL, BPCL) | test_fuel::test_fuel_import_two_provider_layouts_same_table |
| 25 | Diesel/Petrol/CNG/etc. | `fuel_types` master with units | test_diesel_petrol_cng_supported |
| 26 | Multiple fuel types per vehicle work | compatibility against `vehicle_fuels` | test_multiple_fuel_types_on_one_vehicle · test_invalid_fuel_compatibility_requires_override |
| 27 | Fuel efficiency | km since last fill / quantity per fuel type; configurable thresholds | test_fuel_efficiency_and_unusual_flag |
| 28 | Toll Excel layouts configurable | 2 toll templates (FastWay, HighRoad) | test_toll::test_provider_specific_layouts_and_provider_scoped_ids |
| 29 | Toll transaction IDs provider-scoped | unique (provider_id, transaction_id) | same · test_manual_toll_entry_same_table_and_duplicate_rejected |
| 30 | Toll plazas matched | external id → code → mapping → unique name | same |
| 31 | Unmatched toll vehicles/plazas reviewable | statuses + review list + Resolve action + learnt mappings | test_unmatched_rows_reviewed_and_resolved_with_mapping |
| 32 | Manual toll entry uses the same table | `toll_transactions.source_type` | test_manual_toll_entry_same_table_and_duplicate_rejected · test_api_feed_uses_same_table |
| 33 | Manual fuel entry uses the same table | `fuel_transactions.source_type` | test_fuel_import_two_provider_layouts_same_table |
| 34 | Maintenance history available | job cards (+ parts/labour), per-vehicle list & report | test_maintenance::* |
| 35 | Tyres individually traceable | `tyres` + `tyre_movements` + `tyre_fitments` | test_tyres::test_full_lifecycle |
| 36 | Installation tracks vehicle/position/odometer | install action | test_full_lifecycle |
| 37 | Tyre transfers preserve history | TRANSFER movement with from/to vehicle, position, odometers | test_full_lifecycle |
| 38 | Position changes preserve history | SHIFT movements (+ swap) | test_full_lifecycle · test_shift_swap |
| 39 | Removal calculates running km | removal − installation odometer; total km accumulates | test_full_lifecycle |
| 40 | Retreading tracked | `tyre_retreading`; count incremented only by lifecycle | test_full_lifecycle · test_lifecycle_fields_not_directly_editable_and_correction_audited |
| 41 | Warranty tracked | `tyre_warranty_claims` + resolution | test_full_lifecycle |
| 42 | Inspection tracked | `tyre_inspections`, tread threshold alert | test_inspection_and_dashboard |
| 43 | Tyre dashboard displays positions | layout-driven diagram | test_inspection_and_dashboard · UI |
| 44 | Duplicate position occupancy prevented | service check + DB unique indexes | test_duplicate_position_occupancy_prevented · test_database_enforces_single_occupancy |
| 45 | Odometer inconsistencies controlled | `record_odometer` (ERROR/WARN, override + reason + audit) | test_fleet::test_odometer_* · test_fuel::test_odometer_validation_on_fuel · test_tyres::test_removal_odometer_below_installation_requires_override · test_maintenance::test_job_card_odometer_is_validated |
| 46 | Operational and bank linked without double counting | settlement links; ledger excludes linked bank rows; capacity checks | test_no_double_counting_fuel_and_toll · test_refund_reduces_expense_not_revenue · test_one_to_one_contract_receipt_no_double_income |
| 47 | Profitability and cost reports | `reports.profitability`, category costs, 20+ reports | test_reports::* · test_api::test_dashboard_and_reports_api |
| 48 | Important changes auditable | `audit_logs` with diffs + reasons; domain histories | test_api::test_master_crud_audit_and_soft_delete · test_bank::test_reverse_and_unlink_are_audited |
| 49 | RBAC works | permissions/roles/branch restriction/approvals | test_api::test_rbac_* · test_branch_restriction · test_bank::test_large_allocation_requires_approval |
| 50 | Responsive | CSS grid breakpoints (1100/1000/700 px), collapsible sidebar | browser check |
| 51 | Dates display DD/MM/YYYY | UI formatters, exports, input masks; day-first parsing | test_transforms::test_date_parsing_is_day_first · test_api::test_dates_accept_ddmmyyyy_and_return_iso · test_exports |
| 52 | Large imports handled safely | staging rows, bulk flushes, SAVEPOINT per row, background commit with progress, full rollback on failure | test_imports::test_progress_callback_and_row_isolation |
| 53 | Errors recoverable | friendly error model, error register + resolution, unmatch/reverse, re-import safe | test_api::test_validation_errors_are_friendly · test_imports::test_error_register_shows_row_column_and_can_be_resolved |
| 54 | No business rule silently hard-coded | `business_rules`, lookups, masters; tests change rules at runtime | test_odometer_warn_mode_is_configurable · test_quantity_rate_amount_tolerance · test_common_cost_allocation_is_configurable · test_same_file_policy_is_configurable |
