# Reserve Duty Assignments (רזרבה) — Design

**Date:** 2026-05-31
**Status:** Approved for implementation

---

## 1. Purpose and scope

Reserve duty assignments (רזרבות) put soldiers on call for a shift. A reserve knows
exactly which primary soldiers they back; a primary knows who their reserve is. The
CP-SAT algorithm assigns reserves with the same hard-constraint rigour as primaries,
while softly preferring hierarchy-close pairings. The Duty Manager can **הקפצה**
(scramble/call up) a reserve when a primary is dismissed, partially or fully, for
their shift. Scoring is adjusted for each case via configurable multipliers.

**In scope:**

- Per-duty-type reserve ratio + minimum; per-shift override
- Algorithm assigns reserves in one combined pass; hierarchy proximity as a soft
  objective term
- Post-solve linking: every primary has exactly one designated reserve; every reserve
  knows the primaries it covers
- Dismissal records on primary assignments (partial or full, date-ranged)
- הקפצה records on reserve assignments (partial or full, date-ranged)
- Extended scoring with per-day multipliers (standby, called-up, dismissed)
- Shift detail panel with primary/reserve split and הקפצה / dismissal actions
- Unit calendar shows `"N + Mר"` headcount badge
- Reserve assignments participate in the swap system (same SwapRequest flow)

**Out of scope:**

- Automatic הקפצה (always DM-initiated)
- Push notifications on הקפצה
- Multi-reserve-per-primary (one designated reserve per primary)

---

## 2. Data model

### 2.1 `duty_types` — two new columns

| Column | Type | Default | Description |
|---|---|---|---|
| `reserve_ratio` | `Numeric(4,3)` | `0.000` | Fraction of `required_count` to allocate as reserves. `0.000` = no reserves for this type. |
| `reserve_minimum` | `integer` | `0` | Floor on reserve count regardless of ratio. |

**Effective reserve count formula** (for a given shift):

```
reserve_count_override  -- if set on the shift, use it directly
  ?? max(reserve_minimum, ceil(required_count × reserve_ratio))
```

### 2.2 `duty_shifts` — one new column

| Column | Type | Default | Description |
|---|---|---|---|
| `reserve_count_override` | `integer NULL` | `NULL` | When set, replaces the formula for this specific shift. |

### 2.3 `duty_assignments` — three new columns

| Column | Type | Default | Description |
|---|---|---|---|
| `is_reserve` | `boolean` | `false` | Distinguishes a reserve slot from a primary slot. |
| `called_up_from` | `date NULL` | `NULL` | First day of הקפצה. `NULL` = still on standby. |
| `called_up_to` | `date NULL` | `NULL` | Last day of הקפצה (inclusive). |

A reserve assignment that has been הקפצה'd for days `called_up_from..called_up_to`
earns `called_up_multiplier` for those days and `standby_multiplier` for the rest.

### 2.4 New table: `duty_dismissals`

```sql
duty_dismissals (
  id                  uuid PK
  duty_assignment_id  uuid FK → duty_assignments(id) ON DELETE CASCADE
  dismissed_from      date NOT NULL
  dismissed_to        date NOT NULL    -- inclusive
  reason              text NULL
  created_by          uuid FK → soldiers(id) ON DELETE SET NULL
  created_at          timestamptz NOT NULL DEFAULT now()
  CHECK dismissed_to >= dismissed_from
)
```

Multiple non-overlapping rows per assignment are allowed (e.g. dismissed day 3 for
illness, dismissed day 7 for training). Overlap validation is enforced in the service
layer. Each dismissal row is independently auditable.

### 2.5 New table: `duty_reserve_links`

```sql
duty_reserve_links (
  id                    uuid PK
  reserve_assignment_id uuid FK → duty_assignments(id) ON DELETE CASCADE
  primary_assignment_id uuid FK → duty_assignments(id) ON DELETE CASCADE
  hierarchy_distance    integer NOT NULL   -- 0 = same node, 1 = one step, …
  UNIQUE (primary_assignment_id)           -- each primary has at most one designated reserve
)
```

One row per (reserve → primary) pair. A reserve may appear multiple times (backing
several primaries). `UNIQUE(primary_assignment_id)` ensures each primary has exactly
one designated reserve.

### 2.6 Drop `reserve_assignments`

The existing v1.5 table (`reserve_assignments`) — one hierarchy-walk reserve per
primary duty block — is replaced entirely by `is_reserve=True` `DutyAssignment` rows
plus `duty_reserve_links`. Migration 0025 drops `reserve_assignments` and all code
paths that read or write it.

### 2.7 New `system_settings` keys

| Key | Type | Default | Description |
|---|---|---|---|
| `scoring.reserve_standby_multiplier` | `Decimal` | `0.2` | Multiplier on `score_per_day` for a standby reserve day. |
| `scoring.reserve_called_up_multiplier` | `Decimal` | `1.3` | Multiplier for a called-up reserve day. |
| `scoring.dismissed_multiplier` | `Decimal` | `0.0` | Multiplier for a dismissed primary day. |
| `fairness.reserve_hierarchy_weight` | `Decimal` | `0.5` | Weight `γ` for the hierarchy-proximity term in the solver objective. |

---

## 3. Algorithm

### 3.1 Input: DutyBlock extended

Add `is_reserve: bool` to `DutyBlock` in `algorithm/types.py`. This flag lets the
model builder separate reserve and primary blocks for the new objective term.

### 3.2 Block generation

`load_duty_blocks_from_shifts` (in `services/algorithm_bridge.py`) currently creates
`required_count` primary `DutyBlock`s per shift. It is extended to also create
`effective_reserve_count` reserve `DutyBlock`s per shift, with:

```python
reserve_block.score_per_day = duty_type.score_per_day × standby_multiplier
reserve_block.is_reserve = True
```

The `block_to_shift` map covers both primary and reserve blocks. If
`effective_reserve_count = 0` for a shift, no reserve blocks are generated for it
and the post-solve linking step skips it.

### 3.3 Solver: combined pass

All blocks (primary + reserve) enter the same CP-SAT solve. This means:

- **Coverage:** each block must be assigned to exactly one soldier.
- **No-overlap:** a soldier cannot hold two blocks on the same day — naturally
  prevents a soldier being both primary and reserve on the same day, or reserve on
  two shifts.
- **Min-gap / adjacency:** the spacing reward applies across all blocks, so a reserve
  duty is treated as a "busy day" and adjacent primary/reserve combinations are
  penalised exactly the same as adjacent primary duties.
- **Normalised-score variance:** the constraint `max_norm − min_norm ≤ K` now
  includes reserve score contribution, keeping overall fairness across both types.

### 3.4 Hierarchy-proximity soft term

Before building the model, precompute for each `(reserve_block d, candidate soldier s)`:

```
dist[d][s] = min over all soldiers p eligible for any primary block of shift(d)
             of hierarchy_distance(s.node, p.node)
```

`hierarchy_distance` is the number of edges in the hierarchy tree between the two
nodes (using `path_ids`, O(1) per pair). If `s.node == p.node` → 0.

Add to the objective (for reserve blocks only):

```
maximise  α·min_gap  −  β·density_penalty  −  γ·Σ_{d∈reserve, s} dist[d][s]·x[d,s]
```

`γ = fairness.reserve_hierarchy_weight` (default `0.5`). It is deliberately small
enough that hard-constraint feasibility is never affected and fairness remains
dominant, but large enough to meaningfully break ties in favour of close soldiers.
Raising `γ` trades spacing/density quality for tighter hierarchy pairing.

### 3.5 Post-solve: reserve linking

After the solver returns assignments, run `link_reserves(primary_assignments,
reserve_assignments, hierarchy_maps)` — a pure function that, for each primary
assignment, walks the hierarchy outward (BFS, same algorithm as the old
`select_reserves`) and picks the closest reserve soldier from this shift's reserve
pool. Returns a list of `ReserveLink(reserve_assignment_id, primary_assignment_id,
hierarchy_distance)`. These are bulk-inserted into `duty_reserve_links`.

### 3.6 Persist results

`persist_results` in `algorithm_bridge.py`:

- Primary blocks → `DutyAssignment(is_reserve=False, …)` (unchanged)
- Reserve blocks → `DutyAssignment(is_reserve=True, called_up_from=NULL, …)`
- After creating all assignments, call `link_reserves` and insert links
- **Remove** `select_reserves` call and `ReserveAssignment` row creation

---

## 4. Scoring

### 4.1 Per-day multiplier logic

Extend `effective_duty_days()` (in `services/scoring.py`) to return a fourth element:
`multiplier: Decimal`. The updated signature:

```python
def effective_duty_days(session, …) -> list[tuple[date, uuid.UUID, uuid.UUID, Decimal]]:
```

For each day of a published assignment, the multiplier is resolved as:

```
if assignment.is_reserve:
    if called_up_from <= day <= called_up_to:
        multiplier = reserve_called_up_multiplier
    else:
        multiplier = reserve_standby_multiplier
else:  # primary
    if any DutyDismissal covers this day:
        multiplier = dismissed_multiplier
    else:
        multiplier = Decimal("1.0")
```

`duty_score_by_soldier()` then sums `score_per_day × multiplier` per soldier.

### 4.2 Algorithm input

`load_soldier_inputs` feeds the solver `cumulative_score` per soldier. That score
now includes reserve standby contributions (from `duty_score_by_soldier`). This
ensures the solver's fairness constraint accounts for a soldier already earning
standby score from a previous reserve assignment.

### 4.3 Transparency page

No structural change. The normalised score, cumulative score, and active-days
columns all automatically reflect the new multipliers. The personal score breakdown
endpoint can annotate reserve assignment rows with "(רזרבה)" and dismissed rows with
"(משוחרר)" for the soldier's own view.

---

## 5. Service layer

### 5.1 New / modified functions

**`services/shifts.py`** (or a new `services/reserves.py`):

```python
def reserve_count_for_shift(session, *, shift: DutyShift) -> int:
    """Apply formula or override to get the effective reserve count."""

def call_up_reserve(
    session, *, assignment: DutyAssignment,
    from_date: date, to_date: date, actor_id: uuid.UUID | None
) -> DutyAssignment:
    """Record הקפצה on a reserve assignment. Validates:
    - assignment.is_reserve is True
    - from_date..to_date is within assignment.start_date..end_date
    - the range is within the assignment's shift dates
    - if a prior הקפצה exists on this assignment, the new call replaces it entirely
      (last-write-wins; the audit log preserves the history); overlapping or
      extending a prior call-up is achieved by submitting a new range that covers
      all intended days
    Writes audit row: action="reserve.call_up".
    """

def dismiss_primary(
    session, *, assignment: DutyAssignment,
    from_date: date, to_date: date, reason: str | None,
    actor_id: uuid.UUID | None
) -> DutyDismissal:
    """Record a dismissal on a primary assignment. Validates:
    - assignment.is_reserve is False
    - date range is within the assignment's dates
    - new range does not overlap an existing DutyDismissal on this assignment
    Writes audit row: action="reserve.dismiss".
    """

def delete_dismissal(
    session, *, dismissal: DutyDismissal, actor_id: uuid.UUID | None
) -> None:
    """Remove a dismissal record. Audited. No cascade on the reserve assignment."""

def get_shift_reserve_detail(
    session, *, shift_id: uuid.UUID
) -> ShiftReserveDetail:
    """Return primary assignments with their linked reserve, plus each reserve's
    dismissals and הקפצה state. Used by the shift detail panel."""
```

**`services/algorithm_bridge.py`** — `load_duty_blocks_from_shifts` extended as
described in §3.2; `persist_results` updated as in §3.6.

**`algorithm/reserve.py`** — `select_reserves` replaced by `link_reserves` (pure
function, same BFS logic but operating on the solver-assigned reserve pool instead
of the full soldier pool).

### 5.2 Authorisation

| Action | Role required |
|---|---|
| View reserve assignments and links | Any authenticated user (own shift), Commander (subtree), DM (scope) |
| הקפצה (`call_up_reserve`) | `ASSIGNMENT_MANAGE` (DM-only global) |
| Dismiss primary (`dismiss_primary`) | `ASSIGNMENT_MANAGE` (DM-only global) |
| Delete dismissal | `ASSIGNMENT_MANAGE` |
| Edit `reserve_ratio` / `reserve_minimum` on DutyType | `ASSIGNMENT_MANAGE` (already gated) |
| Edit `reserve_count_override` on DutyShift | `ASSIGNMENT_MANAGE` |

No new `Action` constant is needed; both הקפצה and dismissal are DM actions and
`ASSIGNMENT_MANAGE` already exists and is already in `_DM_GLOBAL_ACTIONS`.

---

## 6. API routes

### New routes

```
GET  /shifts/{shift_id}/reserve-detail
     → ShiftReserveDetail (primaries with reserve links + call-up / dismissal state)

POST /duty-assignments/{id}/call-up
     body: { from_date, to_date }
     DM-only. Records הקפצה on a reserve assignment.
     Returns updated DutyAssignment.

POST /duty-assignments/{id}/dismissals
     body: { from_date, to_date, reason? }
     DM-only. Creates a DutyDismissal on a primary assignment.
     Returns the new DutyDismissal.

DELETE /duty-assignments/{assignment_id}/dismissals/{dismissal_id}
     DM-only. Removes a dismissal record.
     204 No Content.
```

### Modified routes

- `GET /duty-config/duty-types` and `PATCH /duty-config/duty-types/{id}` — add
  `reserve_ratio`, `reserve_minimum` fields.
- `GET /shifts`, `POST /shifts`, `PATCH /shifts/{id}` — add `reserve_count_override`
  field; responses include `calculated_reserve_count: int` (from the formula) for
  display.

---

## 7. Frontend

### 7.1 Duty Config page

DutyType form adds:
- **יחס רזרבה** (`reserve_ratio`): numeric 0–1, 3 decimal places
- **מינימום רזרבה** (`reserve_minimum`): integer ≥ 0
- A live hint: "עם 20 חיילים בתורנות ← 4 רזרבה" computed from the current
  `required_count` context.

### 7.2 Shift form / edit

- **עדכון ספירת רזרבה** (`reserve_count_override`): optional integer. When blank,
  the formula applies. Label shows the formula result next to the input.

### 7.3 Unit Calendar shift block

Each shift block shows a headcount chip: `"5 + 2ר"` (5 primaries, 2 reserves). If
there are no reserves, the reserve count is hidden. Clicking the block opens the
shift detail panel.

Reserve soldiers appear in the block with a distinct "ר" badge or muted colour so
they're visually distinct from primaries at a glance.

### 7.4 Shift detail panel

Opened by clicking a shift block in the unit calendar. Two sections:

**Primary soldiers:**

| Soldier | Status | Reserve |
|---|---|---|
| א. כהן | פעיל | ב. לוי (מרחק 0) |
| ג. דוד | משוחרר 13.06–16.06 | ב. לוי (מרחק 0) |

Each primary row:
- Shows full name, assignment status (active / dismissed with date range)
- Shows their designated reserve's name + hierarchy distance
- **[שחרור]** button (DM-only): opens date-range picker (from/to within the shift)
  and optional reason field. Submits `POST /duty-assignments/{id}/dismissals`.

**Reserve soldiers:**

| Reserve | מכסה | סטטוס |
|---|---|---|
| ב. לוי | א. כהן, ג. דוד | רזרבה |
| ד. מזרחי | ה. פרץ | הוקפץ 14.06–16.06 |

Each reserve row:
- Shows full name, the primaries they cover (linked)
- Status badge: "רזרבה" (standby) or "הוקפץ [date range]" (called up)
- **[הקפצה]** button (DM-only): opens date-range picker (from/to within the shift).
  Submits `POST /duty-assignments/{id}/call-up`.

### 7.5 System Settings page

Four new rows in the fairness/scoring section:
- `scoring.reserve_standby_multiplier`
- `scoring.reserve_called_up_multiplier`
- `scoring.dismissed_multiplier`
- `fairness.reserve_hierarchy_weight`

---

## 8. Migration

**Migration 0025** (single migration):

1. `ALTER TABLE duty_types ADD COLUMN reserve_ratio Numeric(4,3) DEFAULT 0.000 NOT NULL`
2. `ALTER TABLE duty_types ADD COLUMN reserve_minimum integer DEFAULT 0 NOT NULL`
3. `ALTER TABLE duty_shifts ADD COLUMN reserve_count_override integer NULL`
4. `ALTER TABLE duty_assignments ADD COLUMN is_reserve boolean DEFAULT false NOT NULL`
5. `ALTER TABLE duty_assignments ADD COLUMN called_up_from date NULL`
6. `ALTER TABLE duty_assignments ADD COLUMN called_up_to date NULL`
7. `CREATE TABLE duty_dismissals (…)`
8. `CREATE TABLE duty_reserve_links (…)`
9. `DROP TABLE reserve_assignments` (cascade — only referenced by code, no FK from
   other tables)

Reversible: `downgrade()` drops the new tables and columns and recreates
`reserve_assignments` (empty — no data loss because it was auto-generated by the
algorithm, not manually entered).

---

## 9. Open questions resolved during brainstorm

- **Algorithm assigns reserves, not a post-hoc walk.** The existing `select_reserves`
  (hierarchy walk from each primary) is replaced entirely.
- **Hierarchy proximity is a soft term (γ), not a hard constraint.** It cannot cause
  infeasibility.
- **Dismissal does not require a paired הקפצה.** A primary may be dismissed and
  the shift simply runs with fewer effective soldiers.
- **Swaps for reserve assignments** use the existing `SwapRequest` mechanism
  unchanged — a swap targets any `DutyAssignment` regardless of `is_reserve`.
- **One designated reserve per primary** (`UNIQUE(primary_assignment_id)` on
  `duty_reserve_links`). A reserve may cover multiple primaries; a primary has
  exactly one designated reserve.
- **הקפצה and dismissal are DM-only** (`ASSIGNMENT_MANAGE`, already a DM-global
  action, no new `Action` constant required).
