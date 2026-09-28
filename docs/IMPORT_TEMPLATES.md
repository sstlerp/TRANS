# Import templates, transformations and lookups

Provider differences live only in **template + column mapping + transformation rules + lookup rules**. The normalised
tables never change when a provider changes its Excel layout — create a new template *version* instead (old batches
keep pointing to the version they were imported with).

## Template header

| Field | Meaning |
|---|---|
| Provider / Statement type | BANK, TOLL, FASTAG, FUEL, FUEL_CARD, MAINTENANCE, INSURANCE, GPS, TELEMATICS |
| Version, Effective from/to | expired versions cannot be used for new imports |
| File format, Sheet name | XLSX (sheet optional → first sheet) or CSV |
| Header row, Data start row | 1-based row numbers |
| Stop after N blank rows | end of data detection |
| Skip rows starting with | comma list, e.g. `STATEMENT SUMMARY,OPENING BALANCE,TOTAL` |
| Date format / Date-time format | `strftime` patterns, e.g. `%d/%m/%y`, `%d-%b-%Y`, `%d/%m/%Y %H:%M:%S`. Blank = auto (day-first) |
| Amount columns (bank) | `SEPARATE` (debit & credit columns), `SIGNED` (one signed amount), `WITH_TYPE` (amount + DR/CR column) |
| Duplicate key fields | optional override of the business key, e.g. `txn_date,amount,reference_number` |

## Column mapping

| Field | Meaning |
|---|---|
| Column | letter (`A`) or 1-based index; leave blank to locate the column by header text |
| Header text | expected header; when a letter is also given the header is **validated** (wrong layout → import blocked) |
| Target field | see tables below |
| Type | TEXT, DATE, DATETIME, TIME, DECIMAL, INTEGER |
| Required | row error when empty |
| Transformation | pipeline (below) applied before typing |
| Default | used when the (transformed) value is empty |
| Lookup | `vehicle`, `fuel_type`, `fuel_station`, `toll_plaza`, `maintenance_type`, `vendor`, `provider` |
| Validation | `min:0`, `max:100000`, `len:10`, `maxlen:20`, `regex:[A-Z]{2}\d+`, `in:DEBIT;REFUND` (combine with `&&`) |

## Target fields

**BANK** — `txn_date`* · `value_date` · `narration` · `credit` · `debit` · `amount` · `dr_cr` · `reference_number` ·
`utr` · `cheque_number` · `balance` · `counterparty`

**FUEL / FUEL_CARD** — `provider_transaction_id` · `txn_datetime` or `txn_date` + `txn_time` · `vehicle_number` ·
`card_number` · `station_code` · `station_name` · `fuel_type`* · `quantity`* · `unit` · `rate` · `amount` ·
`tax_amount` · `discount_amount` · `total_amount` · `invoice_number` · `odometer` · `remarks`

**TOLL / FASTAG** — `transaction_id`* · `txn_datetime` or `txn_date` + `txn_time` · `vehicle_number` · `fastag_id` ·
`plaza_id` · `plaza_code` · `plaza_name` · `amount`* · `direction` · `lane` · `txn_kind` (DEBIT / REFUND / RECHARGE) · `remarks`

**MAINTENANCE** — `job_card_number`* · `job_date`* · `vehicle_number`* · `maintenance_type`* · `odometer` · `complaint` ·
`work_performed` · `vendor_name` · `parts_amount` · `labour_amount` · `other_amount` · `tax_amount` · `invoice_number`

**INSURANCE** — `policy_number`* · `vehicle_number` · `policy_type`* · `start_date`* · `expiry_date`* ·
`insured_amount` · `premium` · `tax_amount`

**GPS / TELEMATICS** — `vehicle_number`* · `reading_datetime`* · `odometer`* (→ odometer readings with chronology checks)

(* required by the target schema)

## Transformation pipeline

Steps are separated by `|` and applied left to right. Arguments are comma separated (`\,` for a literal comma).

| Step | Example | Effect |
|---|---|---|
| `trim`, `upper`, `lower`, `collapse_spaces` | `trim\|upper` | text clean-up |
| `remove_commas`, `remove_currency` | `remove_currency\|remove_commas` | `Rs 1,500.00` → `1500.00` |
| `replace(a,b)` | `replace(Rs ,)` | substring replace |
| `regex(pattern,group)` | `regex(\d+,0)` | extract with a regular expression |
| `split(sep,index)` | `split(/,1)` | `A/B/C` → `B` |
| `concat(sep,COL,COL…)` | `concat( ,C,D)` | join this value with other source columns (letter or header) |
| `left(n)`, `right(n)`, `prefix(x)`, `suffix(x)` | `left(4)` | substrings / decoration |
| `default(x)` | `default(0)` | value when empty |
| `decimal`, `int`, `abs`, `negate` | `remove_commas\|abs` | numeric conversion |
| `date(fmt)`, `datetime(fmt)` | `date(%d-%b-%Y)` | explicit date parsing |
| `normalize_vehicle` | | `TN-01 ab 1234` → `TN01AB1234` |
| `map(TYPE)` | `upper\|map(FUEL_TYPE)` | translate through **Value Mappings** (provider-specific first, then global) |
| `if(cond,then,else)` | `if(eq:CR,REFUND,DEBIT)` · `if(col:F=CR,$value,0)` | conditional; conditions `eq:`, `ne:`, `contains:`, `empty`, `notempty`, `gt:`, `lt:`, `col:X=v`; `$value` and `$col:X` refer to values |

Unknown steps are rejected when the template is saved.

## Matching & duplicates

* Vehicles: toll vehicle mappings (provider + external number/FASTag, effective dates) → fuel cards → normalised
  registration → VEHICLE value mappings. **No fuzzy guessing**; unresolved rows are imported as `VEHICLE_UNMATCHED`.
* Plazas: external plaza id → plaza code → TOLL_PLAZA mappings → exact unique name.
* Fuel types: code/name → FUEL_TYPE mappings (e.g. `HSD` → `DIESEL`, `SPEED` → `PETROL` for BPCL only).
* Business keys: bank = account + hash(date, narration, debit, credit, reference, UTR, balance, in-file occurrence);
  toll = provider + transaction id; fuel = provider + provider transaction id (or hash of vehicle, time, qty, amount);
  maintenance = job card number; insurance = provider + policy number. Duplicates are flagged in preview and never inserted.
* Re-uploading the same file (same SHA-256) warns or blocks according to the `DUPLICATE_FILE_CHECK` rule.

## Sample files (`samples/`)

| File | Template | Demonstrates |
|---|---|---|
| `bank_hdfc_statement.xlsx` | HDFC Current Account Statement | title rows, header row 4, separate withdrawal/deposit, `dd/mm/yy`, summary footer skipped |
| `bank_sbi_statement.xlsx` | SBI Account Statement (Amount + Dr/Cr) | single amount + DR/CR column, `dd Mon yyyy`, UTR column, internal-transfer counterpart |
| `toll_fastway.xlsx` | FastWay FASTag Statement | separate date/time, plaza id + name, unknown vehicle, unknown plaza, duplicate id, invalid date, refund |
| `toll_highroad.xlsx` | HighRoad Toll Transactions | sheet name, header row 3, combined date-time, plaza code, `CR/DR` → REFUND/DEBIT via `if()`, same txn id as FastWay (provider-scoped) |
| `fuel_iocl_xtrapower.xlsx` | IOCL XTRAPOWER Transactions | `HSD`/`XTRAMILE` mapping, incompatible fuel, unknown vehicle, amount ≠ qty×rate, duplicate row |
| `fuel_bpcl_smartfleet.xlsx` | BPCL SmartFleet Statement | header row 2, `dd-Mon-yyyy`, CNG in KG, total incl. tax, petrol for a diesel-only trailer |

Regenerate with `python -m app.sample_files` (dates are placed in the previous calendar month).
