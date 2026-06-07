# Bulk Accept Performance — Design

**Date:** 2026-06-08

## Problem

`POST /algorithm/jobs/{job_id}/proposals/bulk-accept` loops over assignments in Python and issues N individual `UPDATE` statements plus N `INSERT INTO audit_log` statements at commit time. For 200 proposals that's ~400 DB round-trips inside one transaction — slow and unnecessary.

## Solution (Option A — Backend bulk SQL)

### Backend (`backend/app/routes/algorithm.py`)

Replace the ORM loop in `bulk_accept_proposals` with two SQL statements:

1. **Bulk UPDATE** using SQLAlchemy Core:
   ```python
   from sqlalchemy import update
   session.execute(
       update(DutyAssignment)
       .where(DutyAssignment.id.in_(body.assignment_ids), DutyAssignment.status == "algorithm_draft")
       .values(status="published")
       .returning(DutyAssignment.id)
   )
   ```
   The `RETURNING id` lets us know which rows were actually updated (some may have already been published/rejected).

2. **Bulk audit INSERT** using `insert(...).values([...])`:
   ```python
   from sqlalchemy.dialects.postgresql import insert as pg_insert
   session.execute(
       pg_insert(AuditLog).values([
           {"actor_id": user.id, "action": "algorithm.proposal.accept", ...}
           for aid in accepted_ids
       ])
   )
   ```

### Frontend (`frontend/src/components/AlgorithmProposalTable.tsx`)

Add `approving: boolean` state. While `handleApproveSelected` is in-flight:
- Disable the button
- Show "מפרסם... (N)" instead of "אשר ופרסם (הפוך לרשמי) (N)"

## Constraints

- Keep the `max_length=500` guard on `BulkAcceptRequest` (already there)
- Preserve audit log integrity — every accepted assignment still gets an audit row
- No schema/migration changes needed

## Testing

- Existing backend unit tests cover the endpoint; add one test verifying bulk SQL path actually updates multiple assignments atomically
- Manual: select 100+ proposals → click button → confirm it completes quickly with spinner shown
