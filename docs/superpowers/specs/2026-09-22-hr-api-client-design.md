# HR API Client (Subsystem 1 of HR Integration) — Design

## Context

Justice is gaining an integration with an external HR system (משא"ן) so
soldier profiles can be sourced from HR rather than created manually. The
full integration is large enough to need decomposition into independent
subsystems, each with its own spec → plan → implementation cycle:

1. **HR API client + fixtures** (this document)
2. Data model & field mapping (JSONB raw DTO storage, rank/gender/servicType
   vocab mapping, local-override tracking)
3. Org hierarchy sync (HR groups → Justice tree, auto-create nodes, holding
   node fallback)
4. Person sync engine (idempotent per-record transactional sync, vanished
   flagging, abort-on-anomaly safety, dependent-logic reruns)
5. Activation-code security system (one-time, profile-bound codes; RBAC
   scoped generation; first-login flow)
6. Admin review UI + cron wiring (divergence/holding/vanished queues,
   last-run stats, audit log, daily scheduler, create-profile UI change,
   and the משא"ן integration status/health section in system settings)

This document specs **subsystem 1 only**: a pure HTTP client for the HR API,
with typed request/response models and fixture-based tests. It has **no**
database writes, no field mapping to Justice's vocabulary, and exposes no
routes or UI — those are later subsystems. The client is deliberately kept
standalone (similar in spirit to `app/algorithm/` being pure logic with no
DB imports) so it can be fully tested without a reachable HR server, using
JSON fixtures that mirror the OpenAPI spec below.

There is no live HR server reachable from the development/CI environment.
The HR API spec supplied by the user (reproduced in full under "HR API
contract" below) is the sole source of truth for request/response shapes;
all tests run against fixture data captured from that spec, never a live
call.

## Goals

- A typed, async `HrApiClient` wrapping the HR REST API described below.
- Auto-pagination helper so callers don't hand-roll page-walking loops.
- Off-by-default configuration matching the existing `TELEGRAM_BOT_TOKEN` /
  `SMTP_HOST` idiom: integration is disabled unless both base URL and API
  key are set.
- Support for a custom CA bundle so the client works against an internal
  HR server signed by an offline/internal CA.
- Full unit test coverage using `respx`-mocked fixtures — no network I/O in
  tests.

## Non-goals (deferred to later subsystems)

- Mapping HR field names/values onto Justice's schema and vocab (subsystem 2).
- Any DB reads/writes.
- Any FastAPI route, cron job, or frontend UI (the settings-page health
  section is subsystem 6, though this client provides the `check_connection`
  method it will call).
- Retry/backoff policy — the client raises on failure; retry policy (if any)
  is a sync-engine concern (subsystem 4).

## HR API contract (source of truth for this subsystem)

Auth: header `X-API-KEY: <key>` on every request.

Pagination: `take` (page size) + `page` (1-based or 0-based — TBD by
observing fixture examples the user provides; default assumption: `page`
starts at 1, confirmed via fixture, not guessed). No documented page-size
limit; caller must keep requesting increasing pages until a page returns
fewer than `take` records (including zero).

Date filters: for any date-typed field `f`, the API accepts `f`, `f_gte`,
`f_lte` query params for exact/greater-or-equal/less-or-equal filtering.

Path-based lookup: endpoints taking `{prop}` accept one of `t_personID`,
`personalNumber`, `nationalIdentifier`, `username`, `mail` as the lookup
property name.

### Endpoints

- `GET /api/v1/user` → `User[]`. Every `User` field is usable as an exact-match
  query filter (note: the `imageUrl` field is filtered under the query param
  name `photo`, not `imageUrl` — an API quirk, not a Justice-side mapping).
  Additional params: `query` (free text), `sortBy`, `sortOrder`, `allFields`,
  `take`, `page`.
- `GET /api/v1/user/{prop}/{id}` → `User`.
- `GET /api/v1/user/{prop}/{id}/subhierarchy?maximumDepth` → `User` object
  extended with a `manages: User[]` field (direct + indirect reports).
- `GET /api/v1/user/{prop}/{id}/image` → raw image bytes.
- `GET /api/v1/group?unit,parentKind,parentId,parentName,kind,id,name,take,page`
  → `Group[]`.
- `GET /api/v1/group/{groupId}` → `Group`.
- `GET /api/v1/group/{groupId}/subhierarchy?maximumDepth` → `Group` extended
  with nested subhierarchy (shape mirrors the user subhierarchy pattern:
  isolate any undocumented nesting detail behind a constant/TODO rather than
  guessing).

### `User` fields (raw HR names, used verbatim in `schemas.py`)

```
username firstName lastName fullName imageUrl mail status nationalIdentifier
personalNumber rank gender servicType job profession professionId
serviceStartDate serviceEndDate baseEntryDate t_personID address jobStartDate
endHovaDate dateOfBirth phone voip manager managerName managerUserName
managerPersonalNumber organization hulia huliaId huliaManager team teamId
teamManager mador madorId madorManager branch branchId branchManager shetach
shetachId shetachManager department departmentId departmentManager palga
palgaManager unit unitId unitManager maritalStatus minuy minuyRank isRashatz
isRamad isRaan isMafmar isMefakedYechida
```

(`professionId` — spec text had a typo `prefessionId`; using the corrected
spelling. `isRashatz`/`isRamad`/`isRaan`/`isMafmar`/`isMefakedYechida` are
per-level commander flags as documented by the user: team/mador/branch/
department/unit manager respectively.)

### `Group` fields

```
id name kind unit parentKind parentId parentName
```

### Unknowns

Any field whose type, nullability, or exact semantics isn't nailed down by
the fixtures the user supplies must be isolated behind a named constant or a
clearly labeled TODO in `schemas.py` — never guessed at. Concretely: mark
such fields `Optional` with no assumed default, and leave a one-line comment
naming what's unconfirmed.

## Location & module layout

New subpackage `backend/app/services/hr/` (will grow to house subsystems
2–4 as they land):

```
app/services/hr/
  __init__.py
  schemas.py       # HrUser, HrGroup, HrUserWithReports, HrGroupWithReports
                    # Pydantic models, field aliases matching raw JSON keys
  errors.py         # HrApiError, HrClientNotConfigured
  client.py         # HrApiClient
  tests/
    conftest.py      # respx fixture wiring
    fixtures/
      users_page1.json
      users_page2_short.json
      user_single.json
      user_subhierarchy.json
      groups_page1.json
      group_single.json
      group_subhierarchy.json
      image_bytes.bin
    test_client.py
    test_schemas.py
```

`schemas.py` models are named `Hr*` (not `User`/`Group`) to avoid collision
with Justice's own `Soldier`/`HierarchyNode` models once subsystem 2 starts
importing both in the same module.

## Settings

`app/settings.py` additions:

```python
hr_api_base_url: str = Field(default="", alias="HR_API_BASE_URL")
hr_api_key: str = Field(default="", alias="HR_API_KEY")
hr_api_ca_bundle_path: str = Field(default="", alias="HR_API_CA_BUNDLE_PATH")
hr_api_page_size: int = Field(default=200, alias="HR_API_PAGE_SIZE")

@property
def hr_sync_enabled(self) -> bool:
    return bool(self.hr_api_base_url and self.hr_api_key)
```

`.env.example` additions (documented, blank/commented by default, matching
the `TELEGRAM_BOT_TOKEN` idiom):

```
# HR (משא"ן) integration — leave blank to disable
HR_API_BASE_URL=
HR_API_KEY=
# Path to a CA bundle (.pem) for verifying an internally-signed HR server.
# Leave blank to use the system trust store.
# HR_API_CA_BUNDLE_PATH=/app/certs/internal-ca.pem
```

## Docker / CA bundle support

- New `backend/certs/` directory, gitignored except `.gitkeep`, intended to
  hold operator-supplied `.pem` CA bundle(s) at deploy time.
- `docker-compose.yml`: mount `./backend/certs:/app/certs:ro` on the backend
  service so ops can drop a cert in without rebuilding the image.
- `HrApiClient` passes `verify=settings.hr_api_ca_bundle_path or True` to the
  underlying `httpx.AsyncClient` — empty string falls back to `True` (system
  trust store), a non-empty path is used as the CA bundle.

## Client design

```python
class HrApiClient:
    def __init__(self, base_url: str, api_key: str, *, ca_bundle_path: str = "",
                 page_size: int = 200, timeout: float = 10.0) -> None:
        if not base_url or not api_key:
            raise HrClientNotConfigured(...)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-KEY": api_key},
            verify=ca_bundle_path or True,
            timeout=timeout,
        )
        self._page_size = page_size

    async def get_user(self, prop: str, id: str) -> HrUser: ...
    async def iter_users(self, **filters) -> AsyncIterator[HrUser]: ...
    async def get_user_subhierarchy(self, prop: str, id: str,
                                     maximum_depth: int | None = None) -> HrUserWithReports: ...
    async def get_user_image(self, prop: str, id: str) -> bytes: ...
    async def iter_groups(self, **filters) -> AsyncIterator[HrGroup]: ...
    async def get_group(self, group_id: str) -> HrGroup: ...
    async def get_group_subhierarchy(self, group_id: str,
                                      maximum_depth: int | None = None) -> HrGroupWithReports: ...
    async def check_connection(self) -> HrHealthCheckResult: ...

    async def aclose(self) -> None: ...
    async def __aenter__(self) -> "HrApiClient": ...
    async def __aexit__(self, *exc) -> None: ...
```

**Pagination** (`iter_users`, `iter_groups`): starts at `page=1`, requests
`take=self._page_size` each call, yields records from the page, stops when
a page returns fewer than `take` records (covers the last full page, a
short page, and an empty page uniformly). Filter kwargs are passed through
as query params as-is, except `image` is mapped to `photo` (per the
documented API quirk) and any `*_gte`/`*_lte` suffix is passed through
unchanged (already matches the HR API's own naming).

**Error handling**: any non-2xx response, network error, or JSON decode
failure raises `HrApiError(status_code, message, url)`. No retries inside
the client.

**`check_connection()`**: issues `GET /api/v1/user?take=1`, returns
`HrHealthCheckResult(ok: bool, latency_ms: float, error: str | None)`. Built
now (needed by subsystem 6's settings-page health check) but not wired to
any route yet — subsystem 6 wires it up.

## Testing plan (TDD)

Write tests first, in this order, each red→green:

1. `HrClientNotConfigured` raised when `base_url` or `api_key` is empty.
2. `get_user` happy path — correct URL, `X-API-KEY` header sent, response
   parsed into `HrUser`.
3. `iter_users` pagination: full page → short page (stops correctly);
   empty first page (zero results, no infinite loop); exact-multiple-of-
   `take` page followed by empty page.
4. Filter passthrough: arbitrary field filters, `f_gte`/`f_lte`, `query`,
   `sortBy`, `sortOrder`, `allFields`, and the `image`→`photo` param rename,
   all asserted via respx's request-matching.
5. `get_user_subhierarchy` — parses `manages` list correctly, including an
   empty `manages` list.
6. `get_user_image` — returns raw bytes, content-type not assumed.
7. `iter_groups` / `get_group` / `get_group_subhierarchy` — mirror the user
   tests at a lighter touch (shared pagination logic already covered).
8. Error cases: 401, 500, timeout, malformed JSON → `HrApiError` with the
   right `status_code`/message; verify no partial/garbage model returned.
9. `check_connection()` — success and failure paths, latency populated.
10. CA bundle: `HrApiClient` constructed with `ca_bundle_path` set passes
    that path as `verify=`; empty path passes `verify=True`. No real TLS
    handshake — assert the constructed httpx client's `verify` config.

Target: 100% coverage of `client.py`, `schemas.py`, `errors.py`. Tests live
under `app/services/hr/tests/` following the existing per-package `tests/`
convention, auto-tagged by the existing filename-based pytest marker hook
(likely falls under an existing or new marker — confirm during
implementation which marker bucket `services/hr` should join).

## Dependencies

Add to `backend/pyproject.toml`:
- `httpx` (runtime) — likely already a transitive dep via `fastapi`/
  `starlette`'s `TestClient`; confirm during implementation whether it needs
  promoting to a direct dependency.
- `respx` (dev) — new dev dependency for mocking the httpx transport in
  tests.

## Open questions to resolve during implementation (not blocking the plan)

- Exact `page` indexing (0- vs 1-based) — confirm against whatever sample
  fixture data is available; default to 1-based per the design above but
  flag clearly if evidence suggests otherwise.
- Exact shape of `subhierarchy` nesting for groups (spec doesn't detail it
  beyond "+ manages" for users) — isolate behind a narrowly-typed
  `HrGroupWithReports` and keep it loose (`list[HrGroup]`) rather than
  guessing a deep tree shape.
