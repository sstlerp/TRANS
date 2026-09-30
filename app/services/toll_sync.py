"""Toll plaza master — fetch and update from internet sources.

Every source is configured as an *API Integration* row with integration type ``TOLL_PLAZA_MASTER``
(Administration → API Integrations). ``settings.adapter`` picks how it is read:

* ``OSM_OVERPASS`` — OpenStreetMap via the public Overpass API (free, no key). Toll booths
  (``barrier=toll_booth``) are fetched state by state, so the state is always known; the place is taken
  from the address tags or, failing that, the nearest city / town / village within ``place_radius_m``.
  Data © OpenStreetMap contributors, ODbL.
* ``DATA_GOV_IN`` — Open Government Data Platform India (api.data.gov.in). Needs a free API key (kept in the
  environment variable named in *Credential Env Variable*) and the toll plaza dataset's ``resource_id``.
* ``CUSTOM_JSON`` — any REST API returning JSON (FASTag aggregators, ULIP, NHAI partner feeds …): URL,
  authentication, ``records_path`` and ``field_map`` are configured, nothing is hard-coded.

Every record must have **toll ID, toll plaza name, place and state**; records missing any of them are
skipped (never guessed) and the reason is kept in the sync run. Existing plazas are matched by source + toll
ID, then by toll ID, then by name + state for plazas keyed in by hand, so re-running a sync updates rather
than duplicates. Plazas are never deleted by a sync.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.audit import audit
from app.core.errors import BusinessError, NotFound
from app.core.utils import now
from app.models.operations import ApiIntegration, TollPlaza, TollPlazaSyncRun
from app.models.org import District, State

log = logging.getLogger("erp.toll_sync")

INTEGRATION_TYPE = "TOLL_PLAZA_MASTER"
ADAPTERS = ("OSM_OVERPASS", "DATA_GOV_IN", "CUSTOM_JSON")
USER_AGENT = "TRANS-ERP/1.0 (toll plaza master sync)"
MAX_SKIP_SAMPLES = 200

# States / UTs of India: (ERP code, name, ISO 3166-2 codes old and new, other spellings used by sources, GST code)
INDIA_STATES: list[tuple[str, str, tuple[str, ...], tuple[str, ...], str]] = [
    ("AN", "Andaman and Nicobar Islands", ("AN",), ("andaman & nicobar islands", "andaman and nicobar"), "35"),
    ("AP", "Andhra Pradesh", ("AP",), (), "37"),
    ("AR", "Arunachal Pradesh", ("AR",), (), "12"),
    ("AS", "Assam", ("AS",), (), "18"),
    ("BR", "Bihar", ("BR",), (), "10"),
    ("CH", "Chandigarh", ("CH",), (), "04"),
    ("CG", "Chhattisgarh", ("CT", "CG"), ("chattisgarh", "chhatisgarh"), "22"),
    ("DH", "Dadra and Nagar Haveli and Daman and Diu", ("DH", "DN", "DD"),
     ("dadra & nagar haveli and daman & diu", "dadra and nagar haveli", "daman and diu", "daman & diu"), "26"),
    ("DL", "Delhi", ("DL",), ("nct of delhi", "new delhi"), "07"),
    ("GA", "Goa", ("GA",), (), "30"),
    ("GJ", "Gujarat", ("GJ",), (), "24"),
    ("HR", "Haryana", ("HR",), (), "06"),
    ("HP", "Himachal Pradesh", ("HP",), (), "02"),
    ("JK", "Jammu and Kashmir", ("JK",), ("jammu & kashmir",), "01"),
    ("JH", "Jharkhand", ("JH",), (), "20"),
    ("KA", "Karnataka", ("KA",), (), "29"),
    ("KL", "Kerala", ("KL",), (), "32"),
    ("LA", "Ladakh", ("LA",), (), "38"),
    ("LD", "Lakshadweep", ("LD",), (), "31"),
    ("MP", "Madhya Pradesh", ("MP",), (), "23"),
    ("MH", "Maharashtra", ("MH",), (), "27"),
    ("MN", "Manipur", ("MN",), (), "14"),
    ("ML", "Meghalaya", ("ML",), (), "17"),
    ("MZ", "Mizoram", ("MZ",), (), "15"),
    ("NL", "Nagaland", ("NL",), (), "13"),
    ("OD", "Odisha", ("OR", "OD"), ("orissa",), "21"),
    ("PY", "Puducherry", ("PY",), ("pondicherry",), "34"),
    ("PB", "Punjab", ("PB",), (), "03"),
    ("RJ", "Rajasthan", ("RJ",), (), "08"),
    ("SK", "Sikkim", ("SK",), (), "11"),
    ("TN", "Tamil Nadu", ("TN",), ("tamilnadu",), "33"),
    ("TG", "Telangana", ("TG", "TS"), ("telengana",), "36"),
    ("TR", "Tripura", ("TR",), (), "16"),
    ("UP", "Uttar Pradesh", ("UP",), (), "09"),
    ("UK", "Uttarakhand", ("UT", "UK"), ("uttaranchal",), "05"),
    ("WB", "West Bengal", ("WB",), (), "19"),
]
_BY_CODE = {s[0]: s for s in INDIA_STATES}


def _norm(v: Any) -> str:
    return " ".join(str(v or "").replace("&", " and ").lower().split())


def state_key(value: str | None) -> str | None:
    """ERP state code for a state name / code / ISO code as written by a source, or None."""
    v = _norm(value)
    if not v:
        return None
    for code, name, isos, aliases, _gst in INDIA_STATES:
        if v in (code.lower(), _norm(name)) or v in (_norm(a) for a in aliases):
            return code
        if v.startswith("in-") and v[3:].upper() in isos:
            return code
    return None


# ───────────────────────── records ─────────────────────────
@dataclass
class PlazaRecord:
    toll_id: str | None
    name: str | None
    place: str | None
    state: str | None
    district: str | None = None
    highway: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    operator: str | None = None

    def clean(self) -> PlazaRecord:
        for k in ("toll_id", "name", "place", "state", "district", "highway", "operator"):
            v = getattr(self, k)
            setattr(self, k, " ".join(str(v).split()) if v not in (None, "") else None)
        return self

    def missing(self) -> list[str]:
        labels = {"toll_id": "toll ID", "name": "toll plaza name", "place": "place", "state": "state"}
        return [lbl for k, lbl in labels.items() if not getattr(self, k)]


@dataclass
class Fetched:
    record: PlazaRecord
    raw_ref: str  # short reference to the source row, for skipped-row messages


@dataclass
class StateBatch:
    state_code: str | None  # None when the source is not read state by state
    items: list[Fetched] = field(default_factory=list)


# ───────────────────────── HTTP ─────────────────────────
def http_json(url: str, *, params: dict | None = None, data: dict | None = None, headers: dict | None = None,
              timeout: int = 60, retries: int = 3, backoff: float = 2.0) -> Any:
    """GET (or form POST when `data` is given) returning parsed JSON. Retries rate limits / gateway errors.
    Proxies from HTTPS_PROXY / HTTP_PROXY are honoured automatically."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=hdrs, method="POST" if body else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL comes from admin config
                raw = resp.read()
            try:
                return json.loads(raw.decode("utf-8"))
            except ValueError as exc:
                raise BusinessError(f"The source did not return JSON: {raw[:200]!r}") from exc
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503, 504) or attempt == retries:
                detail = exc.read()[:300].decode("utf-8", "replace") if exc.fp else ""
                raise BusinessError(f"Source returned HTTP {exc.code} {exc.reason}. {detail}".strip()) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt == retries:
                raise BusinessError(f"Cannot reach the source ({getattr(exc, 'reason', exc)}). "
                                    "Check the internet connection / proxy and the Base URL.") from exc
        time.sleep(backoff * (2 ** attempt))
    raise BusinessError(f"Source request failed: {last}")


def _credential(integ: ApiIntegration, required: bool) -> str | None:
    name = integ.credential_env_var
    val = os.environ.get(name) if name else None
    if required and not val:
        raise BusinessError(f"Set the API key in the environment variable {name or '(Credential Env Variable not set)'} "
                            f"for integration {integ.code} and restart the app.")
    return val


def _auth(integ: ApiIntegration, settings: dict) -> tuple[dict, dict]:
    """(headers, query params) for the configured authentication."""
    kind = (integ.auth_type or "NONE").upper()
    if kind == "NONE":
        return {}, {}
    secret = _credential(integ, required=True)
    if kind == "API_KEY":
        if settings.get("key_param"):
            return {}, {settings["key_param"]: secret}
        return {settings.get("key_header") or "X-API-Key": secret}, {}
    if kind == "BASIC":
        user = os.environ.get(integ.client_id_env_var or "", "")
        return {"Authorization": "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()}, {}
    return {"Authorization": f"Bearer {secret}"}, {}  # OAUTH2: a ready bearer token


# ───────────────────────── field helpers ─────────────────────────
DEFAULT_FIELD_MAP = {
    "toll_id": ["toll_id", "toll_plaza_id", "tollplaza_id", "plaza_id", "plaza_code", "toll_plaza_code", "id"],
    "name": ["toll_plaza_name", "tollplaza_name", "name_of_toll_plaza", "plaza_name", "toll_name", "name"],
    "place": ["place", "location", "toll_plaza_location", "city", "town", "village", "locality", "district"],
    "state": ["state", "state_name", "state_ut", "state_ut_name", "statename"],
    "district": ["district", "district_name"],
    "highway": ["nh_no", "nh_no_", "highway", "nh", "national_highway", "road", "section"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lon", "lng", "long"],
    "operator": ["operator", "concessionaire", "agency", "fee_plaza_operator"],
}


def pick(row: dict, candidates: Iterable[str] | str | None) -> Any:
    """First non-empty value among candidate keys (case / space / underscore insensitive; a.b paths allowed)."""
    if not candidates:
        return None
    if isinstance(candidates, str):
        candidates = [candidates]
    keys = {"".join(ch for ch in k.lower() if ch.isalnum()): k for k in row} if isinstance(row, dict) else {}
    for c in candidates:
        if "." in c:
            v = dig(row, c)
        else:
            k = keys.get("".join(ch for ch in c.lower() if ch.isalnum()))
            v = row.get(k) if k is not None else None
        if v not in (None, "", "NA", "N/A", "-"):
            return v
    return None


def dig(obj: Any, path: str | None) -> Any:
    for part in (path or "").split("."):
        if not part:
            continue
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


def _float(v: Any) -> float | None:
    try:
        f = float(str(v).strip())
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def map_record(row: dict, field_map: dict) -> PlazaRecord:
    fm = {**DEFAULT_FIELD_MAP, **(field_map or {})}
    g = lambda k: pick(row, fm.get(k))  # noqa: E731
    return PlazaRecord(toll_id=g("toll_id"), name=g("name"), place=g("place"), state=g("state"), district=g("district"),
                       highway=g("highway"), latitude=_float(g("latitude")), longitude=_float(g("longitude")),
                       operator=g("operator")).clean()


# ───────────────────────── adapters ─────────────────────────
def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def overpass_query(state_code: str, radius_m: int, timeout: int) -> str:
    isos = "|".join(_BY_CODE[state_code][2])
    return (f'[out:json][timeout:{timeout}];\n'
            f'area["boundary"="administrative"]["admin_level"="4"]["ISO3166-2"~"^IN-({isos})$"]->.st;\n'
            '(node["barrier"="toll_booth"](area.st);way["barrier"="toll_booth"](area.st););\n'
            'foreach->.t(\n'
            '  .t out center;\n'
            f'  node(around.t:{int(radius_m)})["place"~"^(city|town|village|suburb|hamlet)$"];\n'
            '  out body;\n'
            ');')


_OSM_PLACE_TAGS = ("addr:city", "addr:town", "addr:village", "addr:place", "addr:hamlet", "addr:suburb",
                   "is_in:city", "is_in:town", "is_in:village")


def _osm_name(tags: dict) -> str | None:
    return tags.get("name:en") or tags.get("name") or tags.get("official_name")


def parse_overpass(payload: dict, state_code: str, name_fallback: bool = False) -> list[Fetched]:
    """Overpass output: each toll booth followed by the place nodes around it."""
    booths: list[tuple[dict, list[dict]]] = []
    for el in payload.get("elements", []):
        tags = el.get("tags") or {}
        if tags.get("barrier") == "toll_booth":
            booths.append((el, []))
        elif tags.get("place") and booths:
            booths[-1][1].append(el)
    state_name = _BY_CODE[state_code][1]
    out, seen = [], set()
    for el, places in booths:
        tags = el.get("tags") or {}
        oid = f"OSM-{el.get('type', 'node')[0].upper()}{el.get('id')}"
        if oid in seen:
            continue
        seen.add(oid)
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        place = next((tags[k] for k in _OSM_PLACE_TAGS if tags.get(k)), None)
        if not place and lat is not None and places:
            near = min((p for p in places if p.get("lat") is not None and _osm_name(p.get("tags") or {})),
                       key=lambda p: _haversine_km((lat, lon), (p["lat"], p["lon"])), default=None)
            place = _osm_name(near["tags"]) if near else None
        name = _osm_name(tags)
        if not name and name_fallback and place:
            name = f"{place} Toll Plaza"
        rec = PlazaRecord(toll_id=oid, name=name, place=place, state=state_name,
                          district=tags.get("addr:district") or tags.get("is_in:district"),
                          highway=tags.get("highway:ref") or tags.get("road_ref"), latitude=lat, longitude=lon,
                          operator=tags.get("operator")).clean()
        out.append(Fetched(rec, f"OSM {el.get('type')}/{el.get('id')}"))
    return out


def fetch_osm(integ: ApiIntegration, settings: dict, states: list[str]) -> Iterator[StateBatch]:
    url = integ.base_url or "https://overpass-api.de/api/interpreter"
    radius = int(settings.get("place_radius_m") or 10000)
    timeout = int(integ.timeout_seconds or 180)
    for code in states:
        payload = http_json(url, data={"data": overpass_query(code, radius, timeout)}, timeout=timeout + 30,
                            retries=int(settings.get("retries", 3)))
        yield StateBatch(code, parse_overpass(payload, code, bool(settings.get("name_fallback"))))


def _paged_rows(url: str, headers: dict, params: dict, settings: dict, timeout: int,
                records_path: str, total_path: str | None) -> Iterator[list[dict]]:
    page_size = int(settings.get("page_size") or 500)
    style = (settings.get("pagination") or "offset").lower()  # offset | page | none
    offset, page, got = 0, int(settings.get("first_page", 1)), 0
    for _ in range(int(settings.get("max_pages") or 1000)):
        p = dict(params)
        if style == "offset":
            p[settings.get("offset_param", "offset")] = offset
            p[settings.get("limit_param", "limit")] = page_size
        elif style == "page":
            p[settings.get("page_param", "page")] = page
            p[settings.get("limit_param", "limit")] = page_size
        payload = http_json(url, params=p, headers=headers, timeout=timeout)
        rows = dig(payload, records_path) if records_path else payload
        if not isinstance(rows, list):
            raise BusinessError(f"No record list at '{records_path or '(top level)'}' in the source response. "
                                "Set settings.records_path for this integration.")
        rows = [r for r in rows if isinstance(r, dict)]
        yield rows
        got += len(rows)
        total = dig(payload, total_path) if total_path else None
        if style == "none" or not rows or len(rows) < page_size or (total is not None and got >= int(total)):
            return
        offset += len(rows)
        page += 1


def _rows_to_batch(rows: list[dict], field_map: dict, start: int) -> list[Fetched]:
    return [Fetched(map_record(r, field_map), f"row {start + i + 1}") for i, r in enumerate(rows)]


def fetch_data_gov_in(integ: ApiIntegration, settings: dict, states: list[str]) -> Iterator[StateBatch]:
    rid = (settings.get("resource_id") or "").strip()
    if not rid:
        raise BusinessError(f"Set settings.resource_id (the toll plaza dataset's resource ID from data.gov.in) "
                            f"for integration {integ.code}.")
    key = _credential(integ, required=True)
    url = (integ.base_url or "https://api.data.gov.in/resource/{resource_id}").replace("{resource_id}", rid)
    base = {"api-key": key, "format": "json"}
    fm, sf = settings.get("field_map") or {}, settings.get("state_filter_field")
    timeout = int(integ.timeout_seconds or 60)
    targets: list[str | None] = list(states) if (sf and states) else [None]
    for code in targets:
        params = dict(base)
        if code:
            params[f"filters[{sf}]"] = _BY_CODE[code][1]
        items: list[Fetched] = []
        for rows in _paged_rows(url, {}, params, settings, timeout, settings.get("records_path", "records"),
                                settings.get("total_path", "total")):
            items += _rows_to_batch(rows, fm, len(items))
        yield StateBatch(code, items)


def fetch_custom_json(integ: ApiIntegration, settings: dict, states: list[str]) -> Iterator[StateBatch]:
    if not integ.base_url:
        raise BusinessError(f"Set the Base URL for integration {integ.code}.")
    headers, params = _auth(integ, settings)
    params = {**(settings.get("params") or {}), **params}
    sp = settings.get("state_param")
    timeout = int(integ.timeout_seconds or 60)
    targets: list[str | None] = list(states) if (sp and states) else [None]
    for code in targets:
        p = dict(params)
        if code:
            p[sp] = _BY_CODE[code][1] if settings.get("state_param_value", "name") == "name" else code
        items: list[Fetched] = []
        for rows in _paged_rows(integ.base_url, headers, p, settings, timeout, settings.get("records_path", ""),
                                settings.get("total_path")):
            items += _rows_to_batch(rows, settings.get("field_map") or {}, len(items))
        yield StateBatch(code, items)


FETCHERS: dict[str, Callable[[ApiIntegration, dict, list[str]], Iterator[StateBatch]]] = {
    "OSM_OVERPASS": fetch_osm, "DATA_GOV_IN": fetch_data_gov_in, "CUSTOM_JSON": fetch_custom_json}


# ───────────────────────── upsert ─────────────────────────
class _Resolver:
    """State / district lookups (states missing from the master are added from the India list)."""

    def __init__(self, db, dry_run: bool):
        self.db, self.dry_run = db, dry_run
        self.states = {s.code: s for s in db.execute(select(State)).scalars()}
        self.by_name = {_norm(s.name): s for s in self.states.values()}
        self._districts: dict[tuple[int, str], int | None] = {}

    def state(self, text: str) -> State | None:
        code = state_key(text)
        s = self.states.get(code) if code else self.by_name.get(_norm(text))
        if s or not code:
            return s
        _c, name, _i, _a, gst = _BY_CODE[code]
        s = self.by_name.get(_norm(name))
        if s is None and not self.dry_run:
            s = State(code=code, name=name, gst_code=gst)
            self.db.add(s)
            self.db.flush()
        if s is not None:
            self.states[code] = s
            self.by_name[_norm(name)] = s
        return s

    def district(self, state_id: int | None, name: str | None) -> int | None:
        if not state_id or not name:
            return None
        k = (state_id, _norm(name))
        if k not in self._districts:
            r = self.db.execute(select(District.id).where(District.state_id == state_id,
                                                          func.lower(District.name) == name.strip().lower())).first()
            self._districts[k] = r[0] if r else None
        return self._districts[k]


def _unique_code(db, wanted: str, taken: set[str]) -> str:
    base = "".join(ch for ch in wanted.upper() if ch.isalnum() or ch in "-_/")[:36] or "PLAZA"
    code, n = base, 1
    while code in taken or db.execute(select(TollPlaza.id).where(TollPlaza.plaza_code == code)).first():
        n += 1
        code = f"{base[:36 - len(str(n))]}-{n}"
    taken.add(code)
    return code


def _dec(v: float | None, places: int = 7) -> Decimal | None:
    return None if v is None else Decimal(str(round(v, places)))


def apply_records(db, integ: ApiIntegration, source: str, batch: StateBatch, run: TollPlazaSyncRun,
                  resolver: _Resolver, seen: set[str], taken: set[str], user_id: int | None) -> None:
    """Validate and upsert one batch of fetched records; counts go to `run`."""
    samples = run.skipped_samples if run.skipped_samples is not None else []

    def skip(ref: str, why: str) -> None:
        run.skipped += 1
        if len(samples) < MAX_SKIP_SAMPLES:
            samples.append(f"{ref}: {why}")

    for f in batch.items:
        r = f.record
        run.fetched += 1
        miss = r.missing()
        if miss:
            skip(f.raw_ref + (f" ({r.name})" if r.name else ""), "missing " + ", ".join(miss))
            continue
        if r.toll_id in seen:
            skip(f.raw_ref, f"duplicate toll ID {r.toll_id} in the source")
            continue
        seen.add(r.toll_id)
        st = resolver.state(r.state)
        if st is None and not resolver.dry_run:
            skip(f"{f.raw_ref} ({r.name})", f"unknown state '{r.state}'")
            continue
        if batch.state_code and st is not None and st.code != batch.state_code and state_key(r.state) != batch.state_code:
            skip(f"{f.raw_ref} ({r.name})", f"state '{r.state}' does not match the requested state {batch.state_code}")
            continue
        sid = st.id if st is not None else None
        values = {"name": r.name[:200], "place": r.place[:150], "state_id": sid, "state_name": r.state[:100],
                  "latitude": _dec(r.latitude), "longitude": _dec(r.longitude)}
        if r.district and (d := resolver.district(sid, r.district)):
            values["district_id"] = d
        if r.highway:
            values["highway"] = r.highway[:50]
        if r.operator:
            values["operator"] = r.operator[:150]
        tid = r.toll_id[:40]
        p = db.execute(select(TollPlaza).where(TollPlaza.api_source == source, TollPlaza.external_plaza_id == tid)).scalars().first()
        if p is None:
            p = db.execute(select(TollPlaza).where(TollPlaza.external_plaza_id == tid,
                                                   TollPlaza.deleted_at.is_(None))).scalars().first()
        if p is None and sid:
            cands = db.execute(select(TollPlaza).where(func.lower(TollPlaza.name) == r.name.lower(),
                                                       TollPlaza.state_id == sid, TollPlaza.api_source.is_(None),
                                                       TollPlaza.deleted_at.is_(None))).scalars().all()
            p = cands[0] if len(cands) == 1 else None  # ambiguous names are never guessed
        if p is None:
            run.created += 1
            if not resolver.dry_run:
                p = TollPlaza(plaza_code=_unique_code(db, tid, taken), external_plaza_id=tid, api_source=source,
                              provider_id=integ.provider_id, api_last_synced_at=now(), created_by=user_id, **values)
                db.add(p)
                db.flush()
                audit(db, None, "CREATE", "toll_plazas", p.id, None, {"source": source, "toll_id": tid, **values},
                      reason=f"Fetched from {integ.code}")
            continue
        changes = {k: v for k, v in values.items() if getattr(p, k) != v}
        if p.external_plaza_id != tid:
            changes["external_plaza_id"] = tid
        if p.api_source != source:
            changes["api_source"] = source
        if not changes:
            run.unchanged += 1
            if not resolver.dry_run:
                p.api_last_synced_at = now()
            continue
        run.updated += 1
        if not resolver.dry_run:
            old = {k: getattr(p, k) for k in changes}
            for k, v in changes.items():
                setattr(p, k, v)
            p.api_last_synced_at, p.updated_by = now(), user_id
            audit(db, None, "UPDATE", "toll_plazas", p.id, old, changes, reason=f"Fetched from {integ.code}")
    run.skipped_samples = list(samples)


# ───────────────────────── runs ─────────────────────────
def integrations(db, active_only: bool = False) -> list[ApiIntegration]:
    q = select(ApiIntegration).where(ApiIntegration.integration_type == INTEGRATION_TYPE,
                                     ApiIntegration.deleted_at.is_(None)).order_by(ApiIntegration.id)
    if active_only:
        q = q.where(ApiIntegration.is_active.is_(True))
    return list(db.execute(q).scalars())


def get_integration(db, integration_id: int | None) -> ApiIntegration:
    if integration_id:
        integ = db.get(ApiIntegration, integration_id)
        if not integ or integ.integration_type != INTEGRATION_TYPE or integ.deleted_at is not None:
            raise NotFound("Toll plaza source")
    else:
        act = integrations(db, active_only=True)
        if not act:
            raise BusinessError("No active toll plaza source. Activate one in Administration → API Integrations "
                                f"(type {INTEGRATION_TYPE}).")
        integ = act[0]
    if not integ.is_active:
        raise BusinessError(f"Integration {integ.code} is inactive.")
    settings = integ.settings or {}
    adapter = settings.get("adapter")
    if adapter not in FETCHERS:
        raise BusinessError(f"Integration {integ.code}: settings.adapter must be one of {', '.join(ADAPTERS)}.")
    # configuration problems are reported before anything is fetched
    if adapter == "DATA_GOV_IN":
        if not (settings.get("resource_id") or "").strip():
            raise BusinessError(f"Set settings.resource_id (the toll plaza dataset's resource ID from data.gov.in) "
                                f"for integration {integ.code}.")
        _credential(integ, required=True)
    elif adapter == "CUSTOM_JSON":
        if not integ.base_url:
            raise BusinessError(f"Set the Base URL for integration {integ.code}.")
        _credential(integ, required=(integ.auth_type or "NONE").upper() != "NONE")
    return integ


def requested_states(codes: Iterable[str] | None) -> list[str]:
    out = []
    for c in codes or []:
        k = state_key(c) or (c.strip().upper() if c.strip().upper() in _BY_CODE else None)
        if not k:
            raise BusinessError(f"Unknown state '{c}'")
        if k not in out:
            out.append(k)
    return out or [s[0] for s in INDIA_STATES]


def create_run(db, integ: ApiIntegration, states: list[str] | None, dry_run: bool, user_id: int | None,
               status: str = "QUEUED") -> TollPlazaSyncRun:
    run = TollPlazaSyncRun(integration_id=integ.id, source=integ.settings["adapter"],
                           states=",".join(states or [])[:255] or None, dry_run=dry_run, status=status,
                           started_at=now(), triggered_by=user_id, skipped_samples=[])
    db.add(run)
    db.flush()
    return run


def execute_run(db, run: TollPlazaSyncRun, progress: Callable[[TollPlazaSyncRun], None] | None = None) -> TollPlazaSyncRun:
    """Fetch every requested state and upsert; with `progress` the caller commits after each state.
    (Dry runs are rolled back by the caller — see run_now / run_background.)"""
    integ = get_integration(db, run.integration_id)
    settings = integ.settings or {}
    source = settings["adapter"]
    states = requested_states(run.states.split(",") if run.states else None)
    run.status, run.started_at, run.states_total, run.states_done = "RUNNING", now(), len(states), 0
    resolver, seen, taken = _Resolver(db, run.dry_run), set(), set()
    failures: list[str] = []

    def done(batch: StateBatch) -> None:
        apply_records(db, integ, source, batch, run, resolver, seen, taken, run.triggered_by)
        run.states_done = min(run.states_total, run.states_done + 1) if batch.state_code else run.states_total
        if progress:
            progress(run)

    if source == "OSM_OVERPASS":
        # one request per state: a state that fails (timeout, rate limit) does not lose the others
        pause = float(settings.get("pause_seconds", 2))
        for i, code in enumerate(states):
            if i and pause:
                time.sleep(pause)  # be polite to the public Overpass service
            try:
                batch = next(fetch_osm(integ, settings, [code]))
            except BusinessError as exc:
                failures.append(f"{code}: {exc.message}")
                run.states_done += 1
                continue
            done(batch)
    else:
        try:
            for batch in FETCHERS[source](integ, settings, states):
                done(batch)
        except BusinessError as exc:
            failures.append(exc.message)
    run.finished_at = now()
    run.status = "FAILED" if failures and not run.fetched else "PARTIAL" if failures else "SUCCESS"
    run.error_message = "\n".join(failures)[:4000] or None
    if not run.dry_run:
        integ.last_sync_at, integ.last_sync_status = run.finished_at, run.status
    log.info("toll plaza sync run=%s source=%s status=%s fetched=%s created=%s updated=%s skipped=%s",
             run.id, source, run.status, run.fetched, run.created, run.updated, run.skipped)
    return run


def run_now(db, integ: ApiIntegration, states: list[str] | None, dry_run: bool, user_id: int | None) -> TollPlazaSyncRun:
    """Run in the current transaction (small syncs, tests, CLI). A dry run is rolled back but its run is kept."""
    run = create_run(db, integ, states, dry_run, user_id, status="RUNNING")
    execute_run(db, run)
    if dry_run:
        snap = run_to_dict(run)
        db.rollback()
        run = TollPlazaSyncRun(**_restore(snap))
        db.add(run)
        db.flush()
    return run


def _restore(snap: dict) -> dict:
    from app.core.utils import parse_datetime
    vals = {k: v for k, v in snap.items() if k != "id"}
    for k in ("started_at", "finished_at"):
        if isinstance(vals.get(k), str):
            vals[k] = parse_datetime(vals[k])
    return vals


def run_to_dict(run: TollPlazaSyncRun) -> dict:
    from app.core.utils import jsonable
    return {c.key: jsonable(getattr(run, c.key)) for c in run.__table__.columns}


def run_background(run_id: int) -> None:
    """Background execution (FastAPI BackgroundTasks / CLI): commits after every state for progress."""
    from app.database import SessionLocal, get_engine
    get_engine()
    _save_snapshot(run_id, {"status": "RUNNING", "started_at": now()})  # visible at once to the screen polling it
    db = SessionLocal()
    try:
        run = db.get(TollPlazaSyncRun, run_id)
        if run.dry_run:
            execute_run(db, run)
            snapshot = run_to_dict(run)
            db.rollback()
            _save_snapshot(run_id, snapshot)
            return
        execute_run(db, run, progress=lambda _r: db.commit())
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("toll plaza sync run %s failed", run_id)
        _save_snapshot(run_id, {"status": "FAILED", "finished_at": now(),
                                "error_message": str(getattr(exc, "message", exc))[:4000]})
    finally:
        db.close()


def _save_snapshot(run_id: int, values: dict) -> None:
    from app.database import SessionLocal
    s2 = SessionLocal()
    try:
        run = s2.get(TollPlazaSyncRun, run_id)
        for k, v in _restore(values).items():
            if k not in ("integration_id", "triggered_by"):
                setattr(run, k, v)
        s2.commit()
    finally:
        s2.close()
