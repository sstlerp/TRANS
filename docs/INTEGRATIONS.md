# Integrations — toll plaza master from the internet

The toll plaza master (**Toll → Toll Plazas**) can be filled and kept up to date from internet sources. Every
plaza fetched must have the four compulsory values **toll ID, toll plaza name, place and state**. A record
missing any of them is **skipped, never guessed**, and the reason is listed in the run (for example
`OSM node/123: missing place`).

## How to fetch

| Where | How |
|---|---|
| Screen | **Toll → Toll Plazas → Fetch from Internet**. Pick the source and the states (none ticked = all of India). Tick *Dry run* to see what would change without saving. Progress and results are shown live. |
| Schedule | `toll_plazas_sync.bat` (Windows Task Scheduler, e.g. weekly) or `python -m app.jobs toll-plazas [--source TOLL-OSM] [--states TN,KA] [--dry-run]` (cron). |
| REST API | `POST /api/toll-plazas/sync` — see below. |
| History | **Toll → Toll Plaza Internet Sync**: every run with fetched / new / updated / unchanged / skipped counts, errors and skipped-record reasons. |

What a sync does:

* **New plaza** → created with plaza code = the toll ID (e.g. `OSM-N123456`), the source's name, place, state
  (and district, highway, operator, latitude / longitude when the source has them).
* **Known plaza** → matched by source + toll ID, then by toll ID alone (e.g. the NHAI plaza ID), then — for plazas keyed in
  by hand — by name + state (only when exactly one matches). Changed values are updated; your plaza code is kept.
* **Nothing is deleted.** Plazas that disappear from a source stay; deactivate them yourself if needed.
* Every create / update is written to the audit log with the source as the reason. The state is matched to the
  States master: spellings such as *Orissa*, *Pondicherry*, *IN-TS* and *Jammu & Kashmir* are understood; all 36
  states / UTs are seeded.
* OpenStreetMap is read state by state: one state failing (e.g. a timeout) does not lose the others — the run ends
  **PARTIAL** and names the state; run it again for that state.
* **Your corrections are kept.** When you change the name, place, state, district, highway, operator or position of
  a fetched plaza, the plaza is marked **Keep My Changes**; later fetches leave its details alone and the run counts
  it under *Your changes kept*. Untick **Keep My Changes** to let the source update it again.

## Viewing and updating toll plazas

| Screen | What you can do |
|---|---|
| **Toll → Toll Plaza Directory & Map** | Totals (from internet, entered by hand, changes kept, missing place / state, not on the map, last fetch), a state-wise count (click a state to filter), a map of every plaza with a position (blue = from internet, amber = entered by hand, violet = your changes kept), and a searchable list. Each plaza opens in Google Maps or in the register to view / update. |
| **Toll → Toll Plazas** (register) | The entry form on top, the table below. Click a row to view and update any detail; the plaza's links show **Google Maps**, **Re-fetch *state* from internet** (only this plaza's state, from the same source) and the directory. Row menu ⋯ → **Audit history** shows every change, including what each fetch changed. Export to Excel / CSV / PDF. |
| **Toll → Toll Plaza Internet Sync** | Every fetch run and its counts, errors and skipped records. |

The map background is OpenStreetMap (`ERP_MAP_TILE_URL`, `ERP_MAP_ATTRIBUTION` change it to another XYZ tile
server); the PC showing the map needs internet access to it. The list and counts work without it.

## Sources

Sources are rows in **Administration → API Integrations** with type **TOLL_PLAZA_MASTER**. Two are seeded; add
more for any other provider. Secrets are never stored in the database — *Credential Env Variable* holds the
**name** of an environment variable (put it in `.env`, e.g. `ERP_DATA_GOV_IN_API_KEY=...`, and restart).

### 1. OpenStreetMap — `TOLL-OSM` (active, free, no key)

Reads all toll booths (`barrier=toll_booth`) in each state through the public Overpass API.

* **Toll ID** = the OpenStreetMap element (`OSM-N…` node / `OSM-W…` way).
* **Name** = `name:en`, else `name`.
* **Place** = the address tags (`addr:city`, `addr:town`, `addr:village` …), else the nearest city / town / village
  within `place_radius_m`.
* **State** = the state being read.

Coverage depends on OpenStreetMap volunteers: a booth without a name is skipped. Set `"name_fallback": true` to name
such booths "*Place* Toll Plaza" instead. A whole-India run makes 36 requests and takes several minutes; the
public service asks for moderate use, so schedule it weekly, not hourly. Data © OpenStreetMap contributors,
licensed ODbL — keep the attribution if you publish the data.

| Setting | Default | Meaning |
|---|---|---|
| `adapter` | `OSM_OVERPASS` | |
| `place_radius_m` | `10000` | search radius for the nearest place |
| `pause_seconds` | `2` | pause between states |
| `retries` | `3` | retries on 429 / 5xx / network errors (2, 4, 8 s back-off) |
| `name_fallback` | `false` | see above |

Base URL `https://overpass-api.de/api/interpreter`; the mirror `https://overpass.kumi.systems/api/interpreter` also
works. Timeout (s) is the per-state query timeout (180).

### 2. data.gov.in — `TOLL-DATAGOV` (inactive until configured)

The Open Government Data Platform India publishes NHAI / MoRTH toll plaza datasets.

1. Register at <https://data.gov.in>, copy your **API key** and put it in `.env`: `ERP_DATA_GOV_IN_API_KEY=your-key`.
2. Search the catalogue for the toll plaza dataset, open its **API** tab and copy the **resource ID**.
3. Edit `TOLL-DATAGOV`: set `"resource_id"` in Settings, tick Active, save, restart the app.
4. Run a **dry run** first and look at the skipped reasons. If a compulsory value is missing, map the dataset's
   column names in `field_map`, e.g.

```json
{"adapter": "DATA_GOV_IN", "resource_id": "<resource id>", "page_size": 500,
 "records_path": "records", "total_path": "total", "state_filter_field": "state",
 "field_map": {"toll_id": "toll_plaza_id", "name": "toll_plaza_name", "place": "location", "state": "state"}}
```

`state_filter_field` (optional) makes the fetch state by state using `filters[<field>]=<state name>`.

### 3. Any other JSON API — adapter `CUSTOM_JSON`

For a FASTag aggregator, ULIP or an NHAI partner feed: add an API Integration with type TOLL_PLAZA_MASTER,
the endpoint as Base URL, the authentication, and Settings such as:

```json
{"adapter": "CUSTOM_JSON", "records_path": "data.items",
 "pagination": "offset", "limit_param": "limit", "offset_param": "offset", "page_size": 500, "total_path": "data.total",
 "state_param": "state", "state_param_value": "name",
 "params": {"country": "IN"},
 "field_map": {"toll_id": "plazaCode", "name": "plazaName", "place": "address.city", "state": "address.state",
               "highway": "nh", "latitude": "lat", "longitude": "lng"}}
```

| Auth | Sent as |
|---|---|
| NONE | — |
| API_KEY | header `X-API-Key` (change with `"key_header"`), or a query parameter with `"key_param": "api_key"` |
| BASIC | user from *Client-ID Env Variable*, password from *Credential Env Variable* |
| OAUTH2 | `Authorization: Bearer <value of Credential Env Variable>` |

`pagination`: `offset` (default), `page` (`page_param`, `first_page`) or `none`. Field-map values may be dotted paths
(`address.city`) or a list of candidate names; the first non-empty value wins. Without a field map, common names are
tried (`toll_plaza_id`, `plaza_id`, `toll_plaza_name`, `location`, `place`, `city`, `state`, `state_name` …).

## REST API

| Method & path | Permission | |
|---|---|---|
| `GET /api/toll-plazas/sync/sources` | toll.view | configured sources, active flag, key variable, last sync |
| `GET /api/toll-plazas/sync/states` | toll.view | the 36 state / UT codes and names |
| `POST /api/toll-plazas/sync` | toll.edit | body `{"integration_id": 1, "states": ["TN", "Karnataka"], "dry_run": false, "wait": false}` → the run (`QUEUED`); with `"wait": true` it runs inside the request and returns the finished run |
| `GET /api/toll-plazas/sync/runs` / `…/runs/{id}` | toll.view | run status and counts: `status` QUEUED · RUNNING · SUCCESS · PARTIAL · FAILED, `states_done/states_total`, `fetched`, `created`, `updated`, `unchanged`, `skipped`, `skipped_samples`, `error_message` |

## Database

Migration `0002` (`migrations/versions/0002_toll_plaza_internet_sync.py`, plain SQL
`migrations/sql/0002_toll_plaza_internet_sync.sql`):

* `toll_plazas`: new `place`, `state_name` (the state as written by the source); unique key
  `(api_source, external_plaza_id)`; existing `external_plaza_id` (toll ID), `api_source`, `api_last_synced_at`,
  `state_id`, `district_id`, `latitude`, `longitude`, `highway`, `operator` are filled by the sync.
* `toll_plaza_sync_runs`: one row per run (source, states, dry run, status, counts, skipped reasons, errors, user).

## Network

The app calls the sources from the server running TRANS ERP, so that machine needs internet access to
`overpass-api.de` (or the mirror) and `api.data.gov.in`. Behind a company proxy set `HTTPS_PROXY` in the environment.
