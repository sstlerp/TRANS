# Error handling

## Error model (API)

Every error response is JSON:

```json
{"detail": "Human-readable message", "code": "MACHINE_CODE", "errors": [{"field": "gstin", "message": "invalid GSTIN"}]}
```

| HTTP | code | When |
|---|---|---|
| 400 | `BUSINESS_RULE`, `OVER_ALLOCATION`, `ALLOCATION_MISMATCH`, `OVERPAYMENT`, `INVALID_TRANSITION`, `POSITION_OCCUPIED`, `TARGET_OVER_ALLOCATION`, `TEMPLATE` … | a business rule rejected the operation |
| 401 | `HTTP_401` | not signed in (browser pages redirect to `/login`) |
| 403 | `FORBIDDEN`, `HTTP_403` | missing permission, branch restriction, or missing/invalid CSRF token |
| 404 | `NOT_FOUND` | record/screen not found |
| 409 | `DUPLICATE`, `INTEGRITY`, `DUPLICATE_FILE` | unique business key already exists / referential integrity |
| 409 | `ODOMETER_INCONSISTENT`, `FUEL_TYPE_INCOMPATIBLE`, `AMOUNT_MISMATCH`, `TYRE_ODOMETER` + `override_permission` | rule can be **overridden** by an authorised user with a reason — the UI shows an override dialog and resends with `override=true` + reason (audited, may create an approval review) |
| 422 | `VALIDATION` | field validation; `errors[]` lists each field (the form highlights them) |
| 423 / 429 | `LOCKED`, `RATE_LIMIT` | too many failed logins |
| 500 | `SERVER_ERROR` | unexpected fault — the message contains only a **reference id**; the full stack trace is in `logs/erp.log` under that id |

Stack traces, SQL and internal paths are never returned to users.

## Transactions and recovery

* Each API request is a single unit of work: services only `flush()`; the route commits at the end; any exception
  rolls back everything (e.g. a multi-line allocation, a multi-invoice receipt, a tyre transfer or a swap is all-or-nothing).
* Imports: preview never writes normalised data. Commit processes rows inside SAVEPOINTs so one bad row cannot poison
  the batch (it is marked `ERROR` with the reason). An unexpected failure rolls back the whole batch; background
  imports mark the batch `FAILED` with the error message and nothing is saved — fix and re-upload.
* Duplicates are always flagged, never inserted, so re-running an import after a failure is safe.
* Financial corrections are made by **reversing/unmatching** (with a mandatory reason and history), never by editing
  history in place. Master data is soft-deleted.

## Import error register

Every issue is stored in `statement_import_errors` with batch, source row, source column, target field, original
value, error type (`HEADER`, `REQUIRED`, `FORMAT`, `VALIDATION`, `LOOKUP`/`UNMATCHED`, `DUPLICATE`), severity
(ERROR/WARNING), message and a suggested correction. The wizard shows them next to the preview; *Imports → Import
Errors* lets users mark items resolved with notes (resolver and time recorded).

## Logging

* `logs/erp.log` (rotating 10 MB × 10) + console. Categories: `erp.errors`, `erp.auth` (login success/failure/rate
  limit), `erp.import`, `erp.audit` (`financial-op …` lines for allocations, matches, approvals, overrides, imports),
  `erp.notify` (e-mail failures), `erp.jobs`.
* A log filter masks `password`, `secret`, `token`, `api_key`, `authorization` values.
* The audit log (database) is the business record of who changed what, when, from which IP, with old/new values and reasons.
