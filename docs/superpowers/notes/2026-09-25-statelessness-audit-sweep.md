# Statelessness audit sweep (Task 10)

Date: 2026-09-25

Broad grep-based sweep for in-process mutable state that would break correctness
if the backend runs as multiple replicas/workers, beyond the three specific
pieces already migrated in Tasks 2-4 (rate limiter, solver-cancel signal,
gimelim preview tokens).

## Sweep commands (run from `backend/`)

```bash
grep -rn "^[A-Za-z_][A-Za-z0-9_]*\s*:\s*dict\[" app --include=*.py | grep -v "/tests/\|test_"
grep -rn "^[A-Za-z_][A-Za-z0-9_]*\s*:\s*list\[" app --include=*.py | grep -v "/tests/\|test_"
grep -rn "^[A-Za-z_][A-Za-z0-9_]*\s*:\s*set\[" app --include=*.py | grep -v "/tests/\|test_"
grep -rn "^[A-Za-z_][A-Za-z0-9_]*\s*=\s*{}" app --include=*.py | grep -v "/tests/\|test_"
grep -rn "^[A-Za-z_][A-Za-z0-9_]*\s*=\s*\[\]" app --include=*.py | grep -v "/tests/\|test_"
grep -rn "^[A-Za-z_][A-Za-z0-9_]*\s*=\s*set()" app --include=*.py | grep -v "/tests/\|test_"
grep -rn "threading\.\(Lock\|Event\|RLock\)" app --include=*.py | grep -v "/tests/\|test_"
grep -rln "@lru_cache" app --include=*.py | grep -v "/tests/\|test_"
```

## Raw output

### `dict[` type-annotated module-level assignments

```
app/auth/password.py:9:_TEST_HASH_CACHE: dict[str, str] = {}
app/db/models.py:1186:RANGE_TYPE_RANK: dict[str, int] = {"laser": 1, "live": 2, "alal": 3}
app/error_logging.py:30:_rate_limit_state: dict[str, tuple[float, int, int]] = {}
app/routes/bug_reports.py:46:_COMMENT_ATTACHMENT_MAGIC: dict[str, list[bytes]] = {
app/routes/enrollment.py:27:_EDITABLE_FIELD_LABELS: dict[str, str] = {
app/services/algorithm_bridge.py:53:_cancel_events: dict[str, threading.Event] = {}
app/services/duty_history.py:134:_RANGE_TYPE_HE: dict[str, str] = {
app/services/eligibility.py:50:RANK_TRACK_COMPATIBILITY: dict[str, frozenset[str]] = {
app/services/excel_bilingual.py:19:HE_SHEETS: dict[str, str] = {
app/services/excel_bilingual.py:46:HE_HEADERS: dict[str, str] = {
app/services/excel_bilingual.py:178:_EN_HEADERS: dict[str, str] = {he: en for en, he in HE_HEADERS.items()}
app/services/excel_bilingual.py:181:_EN_SHEETS: dict[str, str] = {he: en for en, he in HE_SHEETS.items()}
app/services/file_validation.py:5:ALLOWED_EXEMPTION_FILE_TYPES: dict[str, list[bytes]] = {
app/services/hr/hierarchy_sync.py:20:HR_GROUP_KIND_TO_LEVEL_MAP: dict[str, str] = {
app/services/hr/mapping.py:10:GENDER_MAP: dict[str, str] = {
app/services/hr/mapping.py:20:RANK_MAP: dict[str, str] = {rank: rank for rank in (*ENLISTED_RANKS, *OFFICER_RANKS)}
app/services/hr/mapping.py:28:SERVICE_TYPE_TO_TRACK_MAP: dict[str, str] = {
app/services/import_parsers/registry.py:7:PARSER_REGISTRY: dict[str, ImportParser] = {}
app/services/notifications.py:40:_FRONTEND_PATHS: dict[str, str] = {
app/services/notifications.py:93:_FRONTEND_QUERY_PARAM: dict[str, str] = {
app/services/ranges.py:70:_RANGE_TYPE_HE: dict[RangeType, str] = {
app/services/ranges.py:742:_VALIDITY_SETTING_KEYS: dict[str, str] = {
app/services/ranges.py:751:_FALLBACK_VALIDITY_DAYS: dict[str, int] = {
app/services/rank_advancement.py:30:_LADDERS: dict[Track, list[str]] = {
```

### typed list/set module-level assignments

app/algorithm/solver.py:57:_profile_callbacks: list[_ProfileCallback] = []

No typed set globals were found. No bare empty-list or set() globals.

### Bare `= {}` module-level assignments (no type annotation)

No hits (all the empty-dict globals in the codebase use a type annotation, so they were already caught by the first pattern above).

### `threading.Lock` / `threading.Event` / `threading.RLock`

```
app/algorithm/solver.py:58:_profile_callbacks_lock = threading.Lock()
app/algorithm/solver.py:99:def _watch_cancel(solver: CpSolver, event: threading.Event) -> None:
app/algorithm/solver.py:110:        self.lock = threading.Lock()
app/algorithm/solver.py:121:    ... stop_event: threading.Event ...
app/algorithm/solver.py:136:    ... cancel_event: threading.Event | None ...
app/algorithm/solver.py:140:    stop_event = threading.Event()
app/algorithm/solver.py:161, 314, 467, 752, 897, 970, 1070, 1165, 1192, 1254, 1454: cancel_event: threading.Event | None (parameter/annotation reuse)
app/error_logging.py:29:_rate_limit_lock = threading.Lock()
app/services/algorithm_bridge.py:53:_cancel_events: dict[str, threading.Event] = {}
app/services/algorithm_bridge.py:81:def _watch_job_cancel_requested(job_id: uuid.UUID, cancel_event: threading.Event) -> None:
app/services/algorithm_bridge.py:94:def _watch_job_timeout(job_id: uuid.UUID, cancel_event: threading.Event, max_seconds: float) -> None:
app/services/algorithm_bridge.py:1459:    cancel_event = threading.Event()
```

### `@lru_cache` usage (files)

```
app/redis_client.py
app/services/holidays.py
app/settings.py
```

The list hit is _profile_callbacks in algorithm/solver.py. _capture_profile is used by
the profiling support context and removes the callback in finally. _profile_phase
snapshots active registrations and filters out inactive ones before invoking them.
This list is temporary profiling instrumentation and does not retain request state
across calls.

## Classification

| Hit | Classification | Reason |
|---|---|---|
| `auth/password.py` `_TEST_HASH_CACHE` | Already known-accepted | Test-only cache, process-local singleton by design (per plan). |
| `db/models.py` `RANGE_TYPE_RANK` | (b) constant, not state | Static lookup table (`{"laser": 1, "live": 2, "alal": 3}`) built once at import, never mutated afterward. Identical in every process/replica — no coordination needed. |
| `error_logging.py` `_rate_limit_state` + `_rate_limit_lock` | Already known-accepted | Reviewed in Task 1; best-effort/non-correctness-critical (log-spam suppression heuristic, not user-facing correctness). Per-process suppression window merely resets more often with more replicas — acceptable degradation, not a bug. |
| `routes/bug_reports.py` `_COMMENT_ATTACHMENT_MAGIC` | (b)/constant | Static magic-byte signature table for file-type sniffing, read-only after module load. |
| `routes/enrollment.py` `_EDITABLE_FIELD_LABELS` | (b)/constant | Static Hebrew label mapping, read-only after module load. |
| `services/algorithm_bridge.py` `_cancel_events` | Already fixed (Task 3) | Redis-bridged; dict intentionally kept as same-process fast path. Not a new bug. |
| `services/duty_history.py` `_RANGE_TYPE_HE` | (b)/constant | Static translation table, read-only. |
| `services/eligibility.py` `RANK_TRACK_COMPATIBILITY` | (b)/constant | Static compatibility table, read-only. |
| `services/excel_bilingual.py` `HE_SHEETS`, `HE_HEADERS`, `_EN_HEADERS`, `_EN_SHEETS` | (b)/constant | All four are built once at import time (the `_EN_*` ones are dict-comprehension inversions of the `HE_*` ones) and never mutated after; purely deterministic, identical across replicas. |
| `services/file_validation.py` `ALLOWED_EXEMPTION_FILE_TYPES` | (b)/constant | Static file-signature allow-list, read-only. |
| `services/hr/hierarchy_sync.py` `HR_GROUP_KIND_TO_LEVEL_MAP` | (b)/constant | Static mapping, read-only. |
| `services/hr/mapping.py` `GENDER_MAP`, `RANK_MAP`, `SERVICE_TYPE_TO_TRACK_MAP` | (b)/constant | Static HR-field mappings, read-only. |
| `services/import_parsers/registry.py` `PARSER_REGISTRY` | (b)/constant (plugin registry) | Populated only via `register()` calls made at *module import time* (e.g. `v1_standard.py:597` calls `register(V1StandardParser())` at module scope). No request-handling code path calls `register()`. Every process builds the identical registry deterministically from source at startup, then only reads (`.values()`, `.get()`) it — behaves like a constant, not per-request mutable state. |
| `services/notifications.py` `_FRONTEND_PATHS`, `_FRONTEND_QUERY_PARAM` | (b)/constant | Static route/param mappings, read-only. |
| `services/ranges.py` `_RANGE_TYPE_HE`, `_VALIDITY_SETTING_KEYS`, `_FALLBACK_VALIDITY_DAYS` | (b)/constant | Static mappings, read-only. |
| `services/rank_advancement.py` `_LADDERS` | (b)/constant | Static promotion-ladder table, read-only. |
| `algorithm/solver.py` `_profile_callbacks` / `_profile_callbacks_lock`, `_StallTracker.lock`, `threading.Event` cancel/stall/timeout plumbing | (b) best-effort/acceptable, not replica-breaking | All of this is scoped to a *single solve invocation* running inside one worker process/thread: `_capture_profile`'s docstring is explicit that it's a "process-local solver timer"; the stall/cancel `Event`s and their watcher daemon threads only coordinate between threads spawned by that same solve call (`_watch_cancel`, `_watch_stall`) and never need to be seen by another replica — the actual cross-replica cancel signal is already bridged through Redis in `algorithm_bridge.py` (Task 3). `algorithm/` is documented as "pure CP-SAT solver (no DB imports)" and is expected to use ordinary in-memory thread primitives for a single compute job; there's nothing here that a second replica needs to observe. |
| `db/session.py` engine/session-factory globals | Already known-accepted | Intentional process-local singleton (SQLAlchemy engine), not request-routing-sensitive state. |
| `@lru_cache` in `redis_client.py`, `holidays.py`, `settings.py` | (c) fine | Memoization of deterministic, side-effect-free functions (`get_redis()`, `get_settings()`, holiday-table lookups) — no shared *mutable* state, just caching each process's own computed value. |

**Result: no genuinely-new (a)-classified hits.** Every module-level dict found by
the sweep besides the three already-migrated/already-accepted items is a
read-only constant table populated once at import time (translation maps,
HR field mappings, allow-lists, a parser plugin registry) — none of it is
mutated during request handling, so none of it needs cross-replica
coordination. The `threading.*` primitives outside the already-covered
`algorithm_bridge.py` cancel signal live entirely inside `algorithm/solver.py`
and only coordinate threads within a single solve call in one process — not
state that needs to be shared or routed across replicas. All `@lru_cache`
usages are plain memoization of pure/deterministic functions.

## Infrastructure gap flagged for future work (not fixed here)

`backend/tests/conftest.py`'s `redis_container` fixture (line ~481) is
`scope="session"`. Under `pytest-xdist`, `scope="session"` is per-*xdist-worker
process*, not shared across the whole test run — unlike `postgres_container`,
which is also nominally `scope="session"` (line ~460) but is made to behave as
a single shared instance across all xdist workers via a controller/worker
handoff (see the `_SHARED_CONTAINER_ATTR` / lock-file mechanism earlier in the
file). `redis_container` has no equivalent handoff, so with `-n auto` each
xdist worker process spins up its own Redis testcontainer. This increases
container count and resource pressure (CPU/memory/Docker overhead) on
memory-constrained dev machines, compounding the known Docker/WSL2 disk and
memory pressure issues already documented for this machine.

This was flagged during Task 1's review as a follow-up for Task 10's audit.
**Not fixed as part of this task** — bringing Redis in line with Postgres's
shared-container-across-xdist-workers behavior is a larger, separate change
(needs its own coordination mechanism, e.g. a lock file + port-file handoff
mirroring the Postgres one) and is out of scope for this sweep-and-document
task. Recommended as a candidate for a future small task if Redis-container
proliferation becomes a practical problem in CI or local dev.

## Fixes made in this task

None. The sweep found no new (a)-classified (genuinely replica-breaking)
issues beyond what Tasks 1-4 already addressed or explicitly accepted.
