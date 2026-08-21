### Task 2: Add projection tables and idempotent rebuild/backfill

**Files:**
- Create: `backend/alembic/versions/6a7b8c9d0e1f_add_score_projections.py` with `down_revision = "595a35bbf19e"`
- Modify: `backend/app/db/models.py` near scoring models
- Modify: `backend/app/services/score_projection.py`
- Create: `backend/app/services/tests/test_score_projection_persistence.py`
- Create: `backend/app/scripts/score_projection.py`

**Interfaces:**
- Consumes: Task 1 bucket functions.
- Produces: `SoldierScoreProjection`, `SoldierQuarterScoreProjection`, `ScoreProjectionQuarterTotal`, and `ScoreProjectionState` models; `rebuild_projection_bucket(session, soldier_id, quarter_start_value)`; `backfill_score_projection(session, batch_size=500, resume_after=None)`.

- [ ] **Step 1: Write failing persistence tests.** Assert unique keys, foreign keys, Decimal preservation, replacement of an existing bucket, resumable batch boundaries, and no duplicate rows after a second backfill.
- [ ] **Step 2: Run the focused persistence tests and verify failure.**
- [ ] **Step 3: Add the migration with indexes on `(soldier_id)`, `(quarter_start)`, and `(soldier_id, quarter_start)`, plus a state row recording the canonical version and completion status.** Use PostgreSQL UUID/date/numeric types consistent with existing models.
- [ ] **Step 4: Implement transactional bucket replacement and resumable backfill.** Rebuild from canonical data, delete/reinsert only requested buckets, update state in the same transaction, and never mark a bucket complete before replacement succeeds.
- [ ] **Step 5: Run migration upgrade/downgrade checks and focused persistence tests.**
- [ ] **Step 6:** Commit with message `feat: persist rebuildable score projections`.
