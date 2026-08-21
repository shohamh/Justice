# Task 2 Report — Persist rebuildable score projections

## Status

Completed Task 2 only in the isolated worktree.

## Changed files

- `backend/alembic/versions/6a7b8c9d0e1f_add_score_projections.py`
- `backend/app/db/models.py`
- `backend/app/scripts/score_projection.py`
- `backend/app/services/score_projection.py`
- `backend/app/services/tests/test_score_projection_persistence.py`
- `backend/tests/conftest.py`

## Design decisions

1. Added four persisted projection models:
   - `SoldierQuarterScoreProjection` for per-soldier quarter buckets
   - `SoldierScoreProjection` for persisted per-soldier totals derived from currently stored buckets
   - `ScoreProjectionQuarterTotal` for persisted per-quarter totals derived from stored quarter buckets
   - `ScoreProjectionState` for canonical version and resumable backfill state

2. Kept Task 1’s bucket contract authoritative for rebuilds.
   - `rebuild_projection_bucket(...)` always recomputes the requested soldier+quarter from canonical rows.
   - The persisted quarter row stores a JSON-safe `source_fingerprint` with deterministic UUID/date/Decimal string conversion.

3. Made explicit soldier×quarter rebuilds replace the requested key even when the canonical result is zero.
   - The quarter row is deleted/reinserted for that exact `(soldier_id, quarter_start)` key.
   - Zero buckets persist as explicit all-zero rows with empty fingerprint lists.

4. Made backfill resumable and idempotent by batching on sorted `soldiers.id`.
   - `resume_after` is the last processed soldier UUID.
   - Re-running a batch deletes/reinserts that batch’s persisted quarter rows before recomputing derived totals, so no duplicate rows accumulate.

5. Updated the test harness truncation list so the new projection tables are cleared between database tests.

## Commands and outputs

### Red phase — focused persistence tests before implementation

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection_persistence.py
```

Output:

```text
ERROR collecting app/services/tests/test_score_projection_persistence.py
ImportError: cannot import name 'ScoreProjectionQuarterTotal' from 'app.db.models'
```

### Intermediate blocker 1 — model dataclass field order

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection_persistence.py
```

Output:

```text
TypeError: non-default argument 'source_fingerprint' follows default argument 'shift_count'
sqlalchemy.exc.InvalidRequestError: Python dataclasses error encountered when creating dataclass for 'SoldierQuarterScoreProjection'
```

Resolution:

- Reordered the mapped fields in `SoldierQuarterScoreProjection`
- Reordered `ScoreProjectionState` fields so non-default dataclass fields come first

### Intermediate blocker 2 — deterministic Decimal string scale

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection_persistence.py
```

Output:

```text
FAILED ... test_rebuild_projection_bucket_persists_json_safe_fingerprint_and_totals
Differing items:
{'score': '0.000'} != {'score': '0.0'}
```

Resolution:

- Kept persisted Decimal strings in their exact deterministic `str(Decimal(...))` form
- Updated the focused test expectation to match the persisted representation

### Focused scoring-projection verification

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection.py app/services/tests/test_score_projection_persistence.py
```

Output:

```text
........                                                                 [100%]
============================== warnings summary ===============================
... PendingDeprecationWarning: Please use `import python_multipart` instead.
```

### Migration upgrade/downgrade/upgrade verification

Command:

```powershell
@'
import os
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.postgres import PostgresContainer

root = Path.cwd()
container = PostgresContainer(
    'postgres:16-alpine',
    username='db_admin',
    password='db_admin_pw',
    dbname='justice',
).with_command('postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off')
container.start()
try:
    url = container.get_connection_url().replace('postgresql://', 'postgresql+psycopg://', 1)
    os.environ['DATABASE_URL'] = url
    os.environ['DB_ADMIN_URL'] = url
    cfg = Config(str(root / 'alembic.ini'))
    cfg.set_main_option('script_location', str(root / 'alembic'))
    command.upgrade(cfg, 'head')
    engine = create_engine(url, future=True)
    with engine.connect() as conn:
        conn.execute(text("select canonical_version, backfill_complete from score_projection_state"))
        conn.commit()
    command.downgrade(cfg, '595a35bbf19e')
    command.upgrade(cfg, 'head')
    print('alembic upgrade head -> downgrade 595a35bbf19e -> upgrade head: PASS')
finally:
    container.stop()
'@ | python -
```

Output:

```text
alembic upgrade head -> downgrade 595a35bbf19e -> upgrade head: PASS
```

## Concerns

1. The focused verification still emits the pre-existing Starlette `python_multipart` PendingDeprecationWarning.
2. `SoldierScoreProjection` and `ScoreProjectionQuarterTotal` are intentionally derived from the currently persisted quarter rows; Task 4’s completeness gate remains necessary before projected reads rely on them globally.

## Fix round 1 — review findings addressed

### Findings addressed

1. Expanded `SoldierQuarterScoreProjection` from one coarse soldier-quarter row into partition rows keyed by `(soldier_id, quarter_start, duty_type_id)` via unique indexes, plus a documented nullable `duty_type_id` aggregate row for quarter adjustments and explicit zero-bucket persistence.
   - Added persisted `raw_day_count`, `effective_weighted_days`, `duty_score`, `adjustment_score`, and row-scoped fingerprints.
   - Preserved the API-neutral Task 1 bucket contract; the decomposition happens only inside Task 2 persistence helpers.

2. Expanded `ScoreProjectionQuarterTotal` so it can serve future effort normalization without re-expanding history.
   - It now stores `raw_day_count`, `effective_weighted_days`, `duty_score`, `adjustment_score`, and `total_score` per quarter.

3. Made backfill partitioned and resumable by soldier and quarter.
   - `ScoreProjectionState` now carries `resume_after_soldier_id` and `resume_after_quarter_start`.
   - `backfill_score_projection(...)` accepts a lexicographic `(soldier_id, quarter_start)` cursor, processes a fixed number of soldier-quarter partitions per call, and remains idempotent on rerun.

4. Fixed the worktree brief path issue.
   - Added `.superpowers/sdd/2026-08-21-scoring-projection-implementation/task-2-brief.md` inside the worktree so the brief is reachable locally alongside the report.

### Red phase for the fix round

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection_persistence.py
```

Output:

```text
FAILED ... object has no attribute 'duty_type_id'
TypeError: __init__() got an unexpected keyword argument 'duty_type_id'
FAILED ... current cursor shape is still soldier-only
```

### Intermediate blocker — SQLAlchemy dataclass field ordering

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection_persistence.py
```

Output:

```text
TypeError: non-default argument 'source_fingerprint' follows default argument 'raw_day_count'
sqlalchemy.exc.InvalidRequestError: Python dataclasses error encountered when creating dataclass for 'SoldierQuarterScoreProjection'
```

Resolution:

- Reordered the new mapped fields so every non-default field precedes defaulted fields in the SQLAlchemy dataclass models.

### Focused verification after the fix round

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection.py app/services/tests/test_score_projection_persistence.py
```

Output:

```text
........                                                                 [100%]
============================== warnings summary ===============================
... PendingDeprecationWarning: Please use `import python_multipart` instead.
```

### Migration round-trip after the fix round

Command:

```powershell
@'
import os
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.postgres import PostgresContainer

root = Path.cwd()
container = PostgresContainer(
    'postgres:16-alpine',
    username='db_admin',
    password='db_admin_pw',
    dbname='justice',
).with_command('postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off')
container.start()
try:
    url = container.get_connection_url().replace('postgresql://', 'postgresql+psycopg://', 1)
    os.environ['DATABASE_URL'] = url
    os.environ['DB_ADMIN_URL'] = url
    cfg = Config(str(root / 'alembic.ini'))
    cfg.set_main_option('script_location', str(root / 'alembic'))
    command.upgrade(cfg, 'head')
    engine = create_engine(url, future=True)
    with engine.connect() as conn:
        conn.execute(text("select canonical_version, backfill_complete, resume_after_quarter_start from score_projection_state"))
        conn.commit()
    command.downgrade(cfg, '595a35bbf19e')
    command.upgrade(cfg, 'head')
    print('alembic upgrade head -> downgrade 595a35bbf19e -> upgrade head: PASS')
finally:
    container.stop()
'@ | python -
```

Output:

```text
alembic upgrade head -> downgrade 595a35bbf19e -> upgrade head: PASS
```

### Fix-round concerns

1. The projection-key enumeration used by backfill is now correctly partitioned by soldier+quarter, but it still derives the global partition list in memory before slicing a batch. That is functionally correct for Task 2 and covered by the focused tests, but Task 6 scale work should revisit the enumeration path if it becomes a backfill bottleneck.
2. The pre-existing Starlette `python_multipart` PendingDeprecationWarning remains unchanged.

## Fix round 2 — persisted cursor is authoritative on restart

### Findings addressed

1. `backfill_score_projection(...)` now treats the persisted `ScoreProjectionState` cursor as authoritative whenever no explicit `resume_after` override is supplied.
   - Interrupted restarts continue lexicographically after the stored `(resume_after_soldier_id, resume_after_quarter_start)` cursor.
   - Completed plain reruns preserve `backfill_complete=True` and do not restart or duplicate rows unless an explicit cursor override is supplied.

2. The CLI now defaults to persisted state.
   - `backend/app/scripts/score_projection.py` only overrides the stored cursor when both `--resume-after-soldier` and `--resume-after-quarter` are supplied together.
   - Supplying only one half of the explicit cursor now fails fast with an argparse error.
   - In `--until-complete` mode, the explicit override is used only for the first call; subsequent iterations fall back to the persisted state cursor.

3. The focused persistence tests now prove:
   - an interrupted restart resumes without manually restating the cursor,
   - a completed plain rerun remains complete,
   - persisted soldier-quarter rows remain duplicate-free across reruns,
   - the CLI accepts no explicit cursor by default and requires both explicit cursor parts together.

### Focused verification after fix round 2

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection.py app/services/tests/test_score_projection_persistence.py
```

Output:

```text
.........                                                                [100%]
============================== warnings summary ===============================
... PendingDeprecationWarning: Please use `import python_multipart` instead.
```

### Migration round-trip after fix round 2

Command:

```powershell
@'
import os
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.postgres import PostgresContainer

root = Path.cwd()
container = PostgresContainer(
    'postgres:16-alpine',
    username='db_admin',
    password='db_admin_pw',
    dbname='justice',
).with_command('postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off')
container.start()
try:
    url = container.get_connection_url().replace('postgresql://', 'postgresql+psycopg://', 1)
    os.environ['DATABASE_URL'] = url
    os.environ['DB_ADMIN_URL'] = url
    cfg = Config(str(root / 'alembic.ini'))
    cfg.set_main_option('script_location', str(root / 'alembic'))
    command.upgrade(cfg, 'head')
    engine = create_engine(url, future=True)
    with engine.connect() as conn:
        conn.execute(text("select canonical_version, backfill_complete, resume_after_soldier_id, resume_after_quarter_start from score_projection_state"))
        conn.commit()
    command.downgrade(cfg, '595a35bbf19e')
    command.upgrade(cfg, 'head')
    print('alembic upgrade head -> downgrade 595a35bbf19e -> upgrade head: PASS')
finally:
    container.stop()
'@ | python -
```

Output:

```text
alembic upgrade head -> downgrade 595a35bbf19e -> upgrade head: PASS
```

### Fix-round concerns

1. The pre-existing Starlette `python_multipart` PendingDeprecationWarning remains unchanged in the focused pytest run.
