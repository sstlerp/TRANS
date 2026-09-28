# Architecture

## Layers

| Layer | Location | Responsibility |
|---|---|---|
| Presentation | `app/templates/*.html`, `app/static/js/*.js`, `app/static/css/erp.css` | Server-rendered pages in the house design; all data via REST. `master.js` renders every master/transaction screen from metadata; dedicated pages for dashboard, import wizard, reconciliation workbench, tyre dashboard, renewal dashboard/calendar and reports. |
| API | `app/api/*` | Authentication, generic `/api/masters/{screen}` CRUD, domain endpoints (reconciliation, imports, tyres, reports, dashboard, jobs, integrations), documents. Each request = one DB transaction committed at the end (`api/deps.commit`). |
| Services | `app/services/*` | All business rules. No SQL in templates or routes beyond simple reads. Services `flush()` but never `commit()`, so callers control atomicity. |
| Data access | `app/models/*` (SQLAlchemy 2 ORM), `app/database.py` | Normalised schema, constraints, indexes. |
| Core | `app/core/*` | Security (bcrypt, JWT, RBAC, CSRF, rate limit), audit helper, error model, DD/MM/YYYY & decimal utilities, logging with secret masking. |
| Configuration | `app/config.py` (env), `business_rules` table (runtime), `lookup_values` (dropdowns) | No business assumption is hard-coded. |

## Generic screen engine

`app/services/registry.py` declares ~70 screens as `MasterSpec` objects (fields, sections, list/search/filter
columns, FK/lookup sources, child grids, row actions, hooks). `app/services/masters.py` turns a spec into:

* server-side list with global/exact search, per-field filters, date range, sorting and pagination;
* CSV / Excel / PDF export (dates DD/MM/YYYY);
* validation & coercion (types, required, length, regex, FK existence, configured lookup values, friendly duplicate checks);
* create/update with child grids saved atomically; soft delete; activate/deactivate;
* row actions implemented by domain services (renew, reclassify, install tyre, resolve toll row, approve …);
* audit (CREATE / UPDATE with field-level diff / ACTIVATE / DEACTIVATE / SOFT_DELETE / action-specific entries);
* branch restriction (direct `branch_id` or via the vehicle).

Adding a new master screen = add a model + a `MasterSpec` + a menu entry; the UI appears automatically.

## Module map

| Spec area | Services | Screens / pages |
|---|---|---|
| Organisation (§3) | masters | Companies, Branches, Departments, Locations/Godowns/Workshops/Warehouses, States, Districts, RTOs |
| Cost classification (§4) | vehicles | Cost categories, Sub-categories, Sub-category attributes, Cost centers, Vehicle cost-center history |
| Vehicles (§5, §6, §42) | vehicles | Vehicle master (+ technical attributes, fuel configuration, reclassify, odometer), Odometer readings |
| Drivers (§7) | masters, renewals | Driver master, driver renewals (renewal types applying to DRIVER), documents |
| Compliance (§8, §9) | renewals | Renewal dashboard/calendar, renewals (tax, permits, fitness, PUCC, PESO, hazmat …), slots, types, rules, history, insurance policies + history |
| Contracts & income (§10, §15) | contracts, bank | Customers, contracts (+ vehicle allocation), invoices/credit notes/advances (+ income allocation), receivables report |
| Bank & reconciliation (§11-§25) | bank, import_engine | Banks, accounts, statements, Reconciliation Workbench, financial links, allocations, reconciliation history, credit/expense types, matching rules |
| Import engine (§12, §56) | import_engine, transforms | Import wizard, templates/builder, providers, value mappings, batches/history, errors |
| Toll (§26) | operations | Toll providers, plazas, vehicle mappings, transactions, review, API integration endpoint |
| Fuel (§27, §28) | operations | Fuel types, stations, cards, transactions, efficiency report |
| Maintenance (§29) | maintenance | Maintenance types, job cards (+ parts, labour), due alerts |
| Tyres (§30-§36) | tyres | Tyre master & stock, lifecycle actions, dashboard, movements, inspections, retreading, warranty, maintenance, positions, layouts, locations, reports |
| Expenses (§37, §38) | contracts | Vendor invoices / operational expenses with multi-cost-center split |
| Reporting (§40, §41, §55) | reports | Report centre (20+ reports) with Excel/CSV/PDF/print |
| Dashboard (§48, §65) | dashboard | Executive dashboard |
| Documents (§43) | documents | Attach/version/download on every document-enabled screen; Documents register |
| Alerts (§44) | notifications, renewals, maintenance | Alerts list, notification rules, daily job |
| Security & audit (§45, §46, §53) | core/security, core/audit | Users, roles, permissions, audit log |
| Approvals (§66) | approvals | Approval rules, approvals inbox |
| Business rules (§67) | rules | System settings / business rules |

## Data model

90 tables (see `migrations/versions/0001_initial_schema.py`). Technical PKs are `BIGINT AUTO_INCREMENT`; business
identifiers are separate unique columns (vehicle code, registration, serial number, invoice number …). Money is
`DECIMAL(18,2)`, quantities `DECIMAL(18,3)`, rates `DECIMAL(18,4)`; dates are `DATE`/`DATETIME` (never text).
Masters carry `created_at/updated_at/created_by/updated_by/is_active/deleted_at`.

* **Organisation, parties & lookups** — `bank_accounts`, `banks`, `branches`, `companies`, `customers`, `departments`, `districts`, `locations`, `lookup_values`, `providers`, `rtos`, `states`, `units`, `vendors`
* **Fleet** — `cost_categories`, `cost_centers`, `fuel_types`, `odometer_readings`, `sub_category_attributes`, `vehicle_cost_center_history`, `vehicle_fuels`, `vehicle_sub_categories`, `vehicle_sub_category_attribute_values`, `vehicles`
* **Drivers & compliance** — `drivers`, `insurance_history`, `insurance_policies`, `renewal_history`, `renewal_rules`, `renewal_types`, `vehicle_renewal_assignments`, `vehicle_renewals`
* **Contracts, finance, reconciliation & approvals** — `approval_actions`, `approval_requests`, `approval_rules`, `bank_transaction_allocations`, `bank_transactions`, `contract_vehicle_allocations`, `contracts`, `credit_types`, `expense_allocations`, `expense_transactions`, `expense_types`, `financial_transaction_links`, `invoice_allocations`, `invoices`, `matching_rules`, `reconciliation_history`, `transaction_types`
* **Import engine** — `statement_import_batches`, `statement_import_errors`, `statement_import_rows` (staging: raw + normalised values per source row), `statement_import_templates`, `statement_template_columns`, `value_mappings`
* **Fuel, toll, maintenance** — `fuel_cards`, `fuel_stations`, `fuel_transactions`, `maintenance_job_cards`, `maintenance_labour`, `maintenance_parts`, `maintenance_types`, `toll_api_configurations` (generic API integration config, type TOLL/FUEL/BANK/GPS…), `toll_plazas`, `toll_transactions`, `toll_vehicle_mappings`
* **Tyres** — `tyre_fitments`, `tyre_inspections`, `tyre_layouts`, `tyre_locations`, `tyre_maintenance`, `tyre_movements`, `tyre_positions`, `tyre_retreading`, `tyre_warranty_claims`, `tyres`, `vehicle_tyre_position_configurations`
* **Security, audit, documents, notifications, configuration** — `audit_logs`, `background_jobs`, `business_rules`, `document_links`, `documents`, `notification_rules`, `notifications`, `permissions`, `roles`, `users`, `role_permissions`, `user_roles`, `user_branches`

Naming notes versus the spec's suggested list (§62): *vehicle cost centers* are `cost_centers` rows of type
`VEHICLE` linked 1:1 to the vehicle; *permits, fitness, PUCC, PESO/hazmat, tax* are configurable renewal types
stored in `vehicle_renewals` (with `renewal_history` and documents); *driver documents / renewal documents* use the
generic `documents` + `document_links` tables; *receivables* are derived from invoices and receipts (report
`receivables` with ageing) rather than a duplicated table; *maintenance transactions* are job cards.

### Relationships (spec §63)

```
Vehicle ─┬─ cost_category / sub_category / cost_center (current) + vehicle_cost_center_history (effective-dated)
         ├─ vehicle_fuels (n)            ├─ vehicle_renewal_assignments (n) → vehicle_renewals (n, chained by previous_renewal_id)
         ├─ insurance_policies (n)       ├─ maintenance_job_cards (n) → parts / labour
         ├─ tyre_fitments / tyres        ├─ fuel_transactions (n) · toll_transactions (n) · odometer_readings (n)
         └─ contract_vehicle_allocations · invoice_allocations · expense_allocations · bank_transaction_allocations

BankTransaction ─ bank_account ─┬─ financial_transaction_links → INVOICE | CONTRACT | FUEL | TOLL | MAINTENANCE | TYRE |
                                 │                                 TYRE_RETREAD | INSURANCE | RENEWAL | EXPENSE | BANK
                                 ├─ bank_transaction_allocations → cost_centers (+ expense/credit type, vendor)
                                 └─ reconciliation_history

Tyre ─ tyre_movements (authoritative history) · tyre_fitments (vehicle + position periods) · retreading · inspections ·
       tyre_maintenance · warranty claims · current vehicle/position/location

Imported row ─ provider ─ template ─ statement_import_batches ─ statement_import_rows (source row, raw values)
             → normalised table row (source_type/file/sheet/row/import_batch_id/txn_hash)
```

## Critical invariants and how they are enforced

| Invariant | Enforcement |
|---|---|
| Historical classification preserved | reclassification only via action; closes current history row, opens a new one; back-dating before the current period is refused; reports resolve category at transaction date (`vehicles.classification_at`) |
| No double counting | reports read cost from operational tables; bank → operational links only settle; a target cannot be settled beyond its value (`bank.target_linked`) |
| No over-allocation | `bank.recompute` raises if links + allocations exceed the bank amount; `allocate` requires totals = unmatched unless partial allocation is enabled |
| Unmatched stays unmatched | credits start `UNCLASSIFIED`; statuses only change through user/approved actions; auto-suggestions stored as `AUTO_SUGGESTED` |
| Provider-scoped IDs | unique `(provider_id, transaction_id)` on toll, `(provider_id, provider_transaction_id)` on fuel |
| Duplicate bank rows | unique `(bank_account_id, txn_hash)`; hash of account, dates, narration, amounts, reference, UTR, running balance and in-file occurrence |
| Single tyre per position / position per tyre | service checks + DB unique indexes `(vehicle_id, position_id, current_slot)` and `(tyre_id, current_slot)` (`current_slot` = 1 while fitted, NULL after) |
| Odometer chronology | `vehicles.record_odometer` checks the previous and next readings; configurable ERROR/WARN; overrides need permission + reason, are audited and can trigger approval review |
| Atomicity | one transaction per request; savepoints for per-row import isolation; background imports roll back fully on failure |

## Extension points

* **New statement provider/layout** — configuration only: provider + template (+ value mappings).
* **New statement family** — add a target schema in `import_engine.TARGET_FIELDS` and a committer branch.
* **Provider API feed** — follow `/api/integrations/toll/{provider_id}/transactions`: build the normalised row and call
  the same `process_*` service (`source_type=API`). Credentials come from environment variables named in *API Integrations*.
* **Notification channel** (SMS/WhatsApp) — implement `ChannelSender.send` and register it in `notifications.CHANNELS`.
* **Approval-controlled action** — `approvals.requires_approval(...)`, `create_request(...)`, `approvals.register(handler)`.
* **Accounting export** — reports expose the unified ledger (`reports.ledger`) with cost center, group and source.
