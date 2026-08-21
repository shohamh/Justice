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
