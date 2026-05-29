# Personal Constraints + Approval Flow — Design

**Date:** 2026-05-29
**Status:** Draft for review
**Builds on:** Slice 4 (assignments, scoring, transparency). Integrates with CP-SAT algorithm (slice 5 worktree).

## Goal

Implement the `personal_constraints` table, submission/approval/rejection lifecycle, cap enforcement, and frontend pages for both soldiers and approvers. Approved constraints feed into the CP-SAT algorithm's `SoldierInput.approved_constraint_dates`.

## Data layer

### Migration (`0015_create_personal_constraints`)

```sql
CREATE TYPE constraint_status AS ENUM ('pending','approved','rejected');

CREATE TABLE personal_constraints (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    soldier_id    uuid NOT NULL REFERENCES soldiers(id) ON DELETE CASCADE,
    start_date    date NOT NULL,
    end_date      date NOT NULL,
    reason        text NOT NULL,
    status        constraint_status NOT NULL DEFAULT 'pending',
    decided_by    uuid REFERENCES soldiers(id) ON DELETE SET NULL,
    decided_at    timestamptz,
    decision_note text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_pc_soldier ON personal_constraints(soldier_id);
CREATE INDEX idx_pc_status ON personal_constraints(status);
```

### ORM model (`models.py`)

```python
class PersonalConstraint(Base):
    __tablename__ = "personal_constraints"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    soldier_id = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE"))
    start_date = mapped_column(Date)
    end_date = mapped_column(Date)
    reason = mapped_column(Text)
    status = mapped_column(Text, server_default="pending", default="pending")
    decided_by = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True)
    decided_at = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
```

## Service layer (`services/constraints.py`)

### Domain errors

```python
class ConstraintError(Exception):
    """Raised on an invalid constraint operation."""
```

### Functions

**`submit_constraint(session, *, soldier_id, start_date, end_date, reason, actor_id) → PersonalConstraint`**
- Validates: soldier exists, `end_date >= start_date`, start_date is not in the past.
- Cap check: `sum(end-start+1)` for pending+approved future constraints per soldier ≤ `system_settings['constraints.personal_cap_days']` (default 15). Raises `ConstraintError("cap_exceeded")`.
- If `system_settings['constraints.require_manager_approval']` is `false`: auto-approves (status=`approved`, `decided_by=actor_id`, `decided_at=now()`).
- Writes audit `constraint.submit`.

**`approve_constraint(session, *, constraint_id, actor_id, decision_note=None) → PersonalConstraint`**
- Validates: constraint exists, status is `pending`.
- Sets `status='approved'`, `decided_by`, `decided_at`.
- Writes audit `constraint.approve`.

**`reject_constraint(session, *, constraint_id, actor_id, decision_note) → PersonalConstraint`**
- Validates: constraint exists, status is `pending`.
- Sets `status='rejected'`, `decided_by`, `decided_at`, `decision_note`.
- Writes audit `constraint.reject`.

**`cancel_constraint(session, *, constraint_id, actor_id) → None`**
- Soldier withdraws own pending request.
- Hard deletes (future constraint has no effect).
- Writes audit `constraint.cancel`.

**`list_constraints(session, *, soldier_id) → list[PersonalConstraint]`**
- Returns constraints ordered by `created_at desc`.

**`list_pending_approvals(session, *, soldier_id=None, node_ids=None) → list[PersonalConstraint]`**
- Returns all pending constraints for soldiers whose `hierarchy_node.path_ids` intersects the given `node_ids`.
- Ordered by `created_at asc` (oldest first).

**`pending_approval_count(session, *, node_ids) → int`**
- Count of pending constraints in scope (for sidebar badge).

**`get_approved_constraint_dates(session, *, soldier_id) → list[tuple[date, date]]`**
- Returns `(start_date, end_date)` for constraints where `status='approved'` and `end_date >= today`.
- Ready for the algorithm bridge service to consume when building `SoldierInput`.

## Auth layer (`authz.py`)

### New action constants

```python
Action.CONSTRAINT_SUBMIT = "constraint.submit"
Action.CONSTRAINT_READ = "constraint.read"
Action.CONSTRAINT_APPROVE = "constraint.approve"
```

### Permission matrix

| Action | Soldier | Commander (subtree) | Duty Manager (scope) | Admin |
|---|---|---|---|---|
| `CONSTRAINT_SUBMIT` | ✓ (self only, route-gated) | ✓ (self) | ✓ (self) | ✓ (self) |
| `CONSTRAINT_READ` | ✓ (self) | ✓ (subtree) | ✓ (scope) | ✓ |
| `CONSTRAINT_APPROVE` | — | ✓ (subtree) | ✓ (scope) | ✓ |

### Changes to action sets

- `_DM_ACTIONS`: add `CONSTRAINT_READ`, `CONSTRAINT_APPROVE`
- `_COMMANDER_ACTIONS`: add `CONSTRAINT_READ`, `CONSTRAINT_APPROVE`

Submit is gated at the route level (soldiers don't have it in their set; the route checks `soldier_id == user.id`).

## Routes (`routes/constraints.py`)

### Soldier self-service (`/api/me/constraints`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/me/constraints` | Any authenticated | List own constraints |
| `POST` | `/me/constraints` | Any authenticated | Submit new constraint |
| `DELETE` | `/me/constraints/{id}` | Any authenticated | Cancel own pending |

### Approval management (`/api/constraints`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/constraints/pending` | `CONSTRAINT_READ` + scope | Pending constraints for approval |
| `GET` | `/constraints/pending/count` | `CONSTRAINT_READ` + scope | Count for badge |
| `POST` | `/constraints/{id}/approve` | `CONSTRAINT_APPROVE` | Approve |
| `POST` | `/constraints/{id}/reject` | `CONSTRAINT_APPROVE` | Reject (req `decision_note`) |

### Cross-soldier view (commander/DM, consistent with exemptions pattern)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/soldiers/{soldier_id}/constraints` | `CONSTRAINT_READ` + scope | View a specific soldier's constraints |

### Pydantic schemas

```python
class ConstraintOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    start_date: date
    end_date: date
    reason: str
    status: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime

class SubmitRequest(BaseModel):
    start_date: date
    end_date: date
    reason: str = Field(max_length=1000)

class RejectRequest(BaseModel):
    decision_note: str = Field(max_length=1000)

class ApproveRequest(BaseModel):
    decision_note: str | None = Field(default=None, max_length=1000)
```

## Frontend

### API client (`api/constraints.ts`)

Types and functions matching the backend endpoints. Pattern follows `api/exemptions.ts`.

### Pages

**`MyRequestsPage.tsx`** (route: `/my-requests`)
- Header: `הבקשות והפטורים שלי`
- Submission form: date range + reason + submit button, with cap progress ("5/15 ימים בשימוש")
- Constraint history table: start/end/reason/status badge (green=אושר, amber=ממתין, red=נדחה) + cancel button on pending
- Read-only own exemptions section at bottom (reuses `listExemptions` API)

**`ApprovalsPage.tsx`** (route: `/approvals`, commander/DM only)
- Header: `אישור בקשות`
- Pending constraints list, each with: soldier name, dates, reason, action buttons
- "אשר" approves directly; "דחה" opens inline text input for `decision_note`
- Empty state: "אין בקשות ממתינות לאישור"

### Layout sidebar changes

- Add `הבקשות שלי` → `/my-requests` (all roles)
- Add `אישור בקשות {{count}}` → `/approvals` (commander/DM only, with pending count badge)

### i18n additions (`he.json`)

New keys under `my_requests`, `approvals`, and new nav entries.

## Algorithm integration

The `constraints` service exposes `get_approved_constraint_dates(session, *, soldier_id)` returning `list[tuple[date, date]]`. This matches the existing `SoldierInput.approved_constraint_dates` field in `app/algorithm/types.py` (line 18). When the algorithm bridge service (`app/services/algorithm.py`) is built (slice 5 merge), it will call this function to populate the field.

## Testing

### Unit tests (`tests/unit/test_constraints_service.py`)

- `test_submit_success` — valid dates, cap not exceeded → created with `pending`
- `test_submit_auto_approve` — `require_manager_approval=false` → `approved`
- `test_submit_cap_enforced` — exceeding cap → `ConstraintError("cap_exceeded")`
- `test_submit_bad_date_range` — `end_date < start_date` → error
- `test_submit_past_start` — `start_date < today` → error
- `test_approve_pending` — pending → approved
- `test_approve_already_approved` — already approved → error
- `test_reject` — pending → rejected, decision_note stored
- `test_cancel_pending` — own pending → deleted
- `test_list_constraints` — returns constraints for soldier
- `test_pending_approvals` — scope filtering
- `test_pending_count` — count matches
- `test_get_approved_dates` — returns only approved, future-dated

### Integration tests (`tests/integration/test_constraints_api.py`)

- `test_soldier_submit_and_list` — submit → see in own list
- `test_soldier_cancel_own` — submit → cancel → gone from list
- `test_commander_approves_in_subtree`
- `test_commander_out_of_subtree_forbidden`
- `test_dm_approves_in_scope`
- `test_soldier_cannot_approve` — 403
- `test_admin_approves_global`
- `test_cap_rejected_at_api`
- `test_pending_count_badge_header`
- `test_reject_requires_note`

## Out of scope

- Notifications (SMS/email/push) for constraint decisions — v2 per design
- The algorithm bridge service (`app/services/algorithm.py`) — lands with slice 5
- Online (greedy) algorithm mode — v2
