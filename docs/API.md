# REST API

Interactive OpenAPI documentation: **`/docs`** (Swagger UI) and **`/redoc`**. All payloads are JSON; dates may be sent
as `DD/MM/YYYY` (or ISO) and are returned as ISO `YYYY-MM-DD` (the UI displays DD/MM/YYYY). Money is returned as a
decimal string.

## Authentication

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H 'Content-Type: application/json' \
        -d '{"username":"admin","password":"***"}' | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/auth/me
```

Bearer-token clients are not subject to CSRF. Browser sessions use an HttpOnly cookie and must send the `erp_csrf`
cookie value in `X-CSRF-Token` on POST/PUT/DELETE. `POST /api/auth/change-password` revokes older tokens.

## Generic screens — `/api/masters/{screen}`

`{screen}` is any registry key (e.g. `vehicles`, `drivers`, `vehicle_renewals`, `insurance_policies`, `contracts`,
`invoices`, `bank_transactions`, `fuel_transactions`, `toll_transactions`, `job_cards`, `tyres`, `import_templates`,
`cost_centers`, `lookup_values`, `business_rules`, `users`, `roles`, `audit_logs` … — see `app/services/registry.py`).

| Method & path | Purpose |
|---|---|
| `GET /{screen}/meta` | fields, sections, children, actions and the caller's permissions |
| `GET /{screen}?q=&exact=1&f_<field>=v1,v2&date_from=&date_to=&active=1\|0\|all&sort=&dir=&page=&size=` | server-side list |
| `GET /{screen}/options?q=&<field>=` | id/label pairs for dropdowns |
| `GET /{screen}/export?fmt=xlsx\|csv\|pdf&…filters` | export (DD/MM/YYYY) |
| `GET /{screen}/{id}` | record incl. child rows (`allocations`, `columns`, `parts`, `fuels` …) |
| `POST /{screen}` / `PUT /{screen}/{id}` | create / update (child arrays replace existing lines atomically) |
| `POST /{screen}/{id}/active` `{"active":false,"reason":"…"}` | activate / deactivate |
| `DELETE /{screen}/{id}?reason=` | soft delete (masters) |
| `POST /{screen}/{id}/actions/{action}` | domain action, e.g. `vehicles/5/actions/reclassify`, `vehicle_renewals/9/actions/renew`, `tyres/3/actions/install`, `toll_transactions/7/actions/resolve`, `approval_requests/2/actions/approve` |
| `GET /{screen}/{id}/audit` | audit history of the record |

Example — create a vehicle with fuels and technical attributes:

```json
POST /api/masters/vehicles
{"vehicle_code":"V010","registration_number":"TN01XY1234","cost_category_id":1,"sub_category_id":1,"vehicle_status":"ACTIVE",
 "branch_id":1,"current_odometer":"50000","purchase_date":"15/04/2024",
 "fuels":[{"fuel_type_id":1,"is_primary":true,"is_active":true},{"fuel_type_id":3,"is_active":true}],
 "attributes":{"1":"18","2":"3"}}
```

## Documents — `/api/documents`

`GET ?entity_type=vehicles&entity_id=5` · `POST` multipart (`entity_type`, `entity_id`, `document_type`, `file`,
`remarks`, `replaces_id` for a new version) · `GET /{id}/download[?inline=true]` · `DELETE /{id}?reason=` (soft).

## Reconciliation — `/api/recon`

| Method & path | Purpose |
|---|---|
| `GET /{bank_txn_id}` | transaction, links, allocations, history |
| `GET /{bank_txn_id}/suggestions` | ranked candidates + classification hints (never applied automatically) |
| `GET /targets/{INVOICE\|CONTRACT\|FUEL\|TOLL\|MAINTENANCE\|TYRE\|TYRE_RETREAD\|INSURANCE\|RENEWAL\|EXPENSE\|BANK}?date_from=&date_to=&q=` | open items with remaining amounts |
| `POST /{id}/link` `{"link_type":"INVOICE_RECEIPT","targets":[{"type":"INVOICE","id":1,"amount":"60000"}],"allow_overpayment":false}` | match (one-to-one / one-to-many; many-to-one = several calls) |
| `POST /links/{link_id}/unlink` `{"reason":"…"}` · `/accept` · `/reject` | unmatch / accept or reject a suggestion |
| `POST /{id}/allocate` `{"lines":[{"cost_center_id":5,"amount":"40000","expense_type_id":11}],"allow_partial":false}` | split to cost centers |
| `POST /allocations/{id}/reverse` · `/{id}/classify` · `/{id}/ignore` · `/{id}/keep-unmatched` · `/auto-suggest` | other workbench operations |

Link types: `CONTRACT_RECEIPT, INVOICE_RECEIPT, REFUND, CASHBACK, REBATE, REVERSAL, INTERNAL_TRANSFER, FUEL_PAYMENT,
TOLL_PAYMENT, MAINTENANCE_PAYMENT, TYRE_PAYMENT, INSURANCE_PAYMENT, TAX_PAYMENT, PERMIT_PAYMENT, PESO_PAYMENT,
VENDOR_PAYMENT, OTHER`.

## Imports — `/api/imports`

`GET /templates?provider_id=&statement_type=` · `GET /target-fields/{type}` · `POST /sheets` (file) ·
`POST /preview` (multipart: `template_id`, `file`, `sheet`, `bank_account_id`) → batch + status counts ·
`GET /batches/{id}` · `GET /batches/{id}/rows?status=&page=` · `GET /batches/{id}/errors` ·
`POST /batches/{id}/commit` (returns `{"queued":true}` for large files) · `POST /batches/{id}/cancel`.

## Other endpoints

* `GET /api/dashboard` — executive dashboard aggregates · `GET /api/notifications/unread-count` · `GET /api/search?q=`
* `GET /api/compliance/dashboard?category=` · `GET /api/compliance/calendar?date_from=&date_to=&category=`
* `GET /api/tyres/vehicle/{vehicle_id}` (positions + fitted tyres) · `GET /api/tyres/{tyre_id}/timeline` (history + cost/km)
* `GET /api/vehicles/attribute-definitions/{sub_category_id}` · `GET /api/vehicles/{id}/classification?on=DD/MM/YYYY`
* `GET /api/reports` · `GET /api/reports/{key}?…` · `GET /api/reports/{key}/export?fmt=xlsx|csv|pdf`
* `POST /api/operations/rematch/{toll|fuel}` · `POST /api/admin/jobs/daily`
* Toll plaza master from the internet (toll ID, name, place, state): `GET /api/toll-plazas/sync/sources`,
  `GET /api/toll-plazas/sync/states`, `POST /api/toll-plazas/sync`, `GET /api/toll-plazas/sync/runs[/{id}]` — see
  `docs/INTEGRATIONS.md`.
* `POST /api/integrations/toll/{provider_id}/transactions` — provider API feed into the same `toll_transactions`
  table (`source_type=API`, provider-scoped duplicate detection):

```json
[{"transaction_id":"T-991","txn_datetime":"01/08/2026 10:05","vehicle_number":"TN01AB1234","plaza_code":"PLZ-SRIP","amount":"335"}]
```
