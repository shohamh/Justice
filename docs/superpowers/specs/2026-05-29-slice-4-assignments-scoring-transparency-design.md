# Slice 4: Duty Assignments, Scoring & Transparency — Design

**Status:** Approved (brainstorm 2026-05-29). Builds on Slices 1–3, all merged to `master`. Slice 4 branches from `master`.

## Goal

Add the core duty mechanics and the fairness-visibility surfaces on top of Slice 3: manual `duty_assignments` (contiguous blocks), the `duty_day_overrides` per-day layer (replacements / cancellations), manual `score_adjustments`, on-demand cumulative + normalised score computation, and the four UI surfaces that consume them — the DM duty-management page, the שקיפות transparency table, a personal duty list, and the unit calendar grid. Every mutation audited, all behind the role + scope authorization layer. No personal constraints and no fairness algorithm yet (constraints land in a later slice; the algorithm is v1.5).

## Spec coverage

Implements design-doc §4.1 tables `duty_assignments`, `duty_day_overrides`, `score_adjustments`; §4.4 derived quantities (cumulative score, active days, normalised score); §5.2 permission rows "Create / edit duty assignments", "Override an assignment", "Adjust soldier scores manually", "View calendar of soldiers in subtree", "View each subtree soldier's score and history", "View transparency table (scores only)"; and page surfaces §7 #5 (היומן של היחידה), #6 (שקיפות), #7 (ניהול תורנויות — the assignment/override/adjustment portions), and a personal duty list feeding #1/#2.

Explicitly **out** of this slice: `personal_constraints` and their approval flow, the CP-SAT fairness algorithm and `assignment_explanations`, structured `reserve_assignments`, the full month-grid personal calendar with the "?למה קיבלתי" modal, the replacement marketplace, and `system_settings` editing UI.

## Decisions locked during brainstorming (2026-05-29)

- **Scope:** "Assignments + overrides + scoring + transparency" — the larger of the offered slices, taking the duty backbone through to visible scores in one coherent stack.
- **Full stack, one branch, one PR** — backend (migrations, services, routes, RBAC, audit, tests) **and** the Hebrew RTL frontend (DM duty-management page, transparency table, personal duty list, unit calendar grid, i18n, Playwright e2e), mirroring Slices 2–3.
- **Manual assignment validation = block overlap + block exemption.** Creating an assignment hard-rejects (a) any day overlapping an existing non-cancelled assignment for the same soldier, and (b) assigning a soldier to a duty type they hold an active mapped exemption for during the block. No DM soft-override in this slice. Personal constraints aren't built yet, so they are not checked.
- **Score adjustments:** include the `score_adjustments` table + DM adjustment action now; `delta` may be **negative or positive** (non-zero), `reason` required, folded into the cumulative-score formula.
- **Active-days denominator: subtract full-coverage-exemption days.** A date counts as exempt for the overall denominator when the soldier holds an active exemption whose type maps to **every currently-active duty type** (requires ≥1 active duty type). This implements §4.4 literally rather than the simpler raw-tenure denominator.
- **Status handling:** `duty_assignments.status` is `proposed|published|cancelled`. Manual creation defaults to `published`; `proposed` is reserved for the v1.5 algorithm's review flow. Scoring counts only `published` assignments; `cancelled` are excluded.
- **Scoring is pure Python.** A `scoring.py` service loads the relevant rows and expands to effective duty-days in Python (clear, unit-testable, trivial at pilot scale), rather than expanding date ranges in SQL.
- **Admin global override** continues as in Slice 3: admin passes every action via the `authz.can()` `role == "admin"` short-circuit and can manage assignments / adjust scores globally.

## Architecture

Same layering as Slices 2–3: pure service functions (no HTTP) that mutate + `write_audit` in one transaction and raise domain errors; thin routes that parse the request, load targets, `authorize(...)`, call the service, and return Pydantic models.

`duty_assignments`, `duty_day_overrides`, and `score_adjustments` are all **scoped** to the target soldier's hierarchy node, resolved through the existing `app/auth/authz.py` engine. The transparency table is the one read that is open to every authenticated user (scores only, no private reasons).

```
                ┌──────────────────────────────────────────┐
 assignments  → │ authorize(ASSIGNMENT_MANAGE, target=node) │ → assignments service → audit
 routes         └──────────────────────────────────────────┘
                ┌──────────────────────────────────────────┐
 adjustments  → │ authorize(SCORE_ADJUST, target=node)      │ → adjustments service → audit
 routes         └──────────────────────────────────────────┘
                ┌──────────────────────────────────────────┐
 scoring/cal  → │ transparency: any authed user            │ → scoring service (read-only)
 routes         │ unit calendar / soldier history: scope    │
                └──────────────────────────────────────────┘
```

`scoring.py` is read-only and DB-light: it pulls raw rows via SQLAlchemy and computes in Python, keeping the aggregation logic isolated and directly unit-testable on fixtures.

## Data model (migrations 0012–0014)

Next migrations after Slice 3's `0011`. ORM models appended to `app/db/models.py` (MappedAsDataclass: non-default fields before defaulted ones; `init=False` PK/timestamps).

- **0012 `duty_assignments`** — `id uuid PK` (`gen_random_uuid()`), `soldier_id uuid FK→soldiers(id) ON DELETE CASCADE NOT NULL`, `duty_type_id uuid FK→duty_types(id) ON DELETE RESTRICT NOT NULL`, `duty_location_id uuid FK→duty_locations(id) ON DELETE RESTRICT NOT NULL`, `start_date date NOT NULL`, `end_date date NOT NULL`, `status text NOT NULL DEFAULT 'published'` (CHECK in `proposed|published|cancelled`), `created_by uuid FK→soldiers(id) ON DELETE SET NULL`, `notes text NULL`, `created_at timestamptz NOT NULL DEFAULT now()`. Indexes `(soldier_id, start_date)` and `(start_date, end_date)`.
- **0013 `duty_day_overrides`** — `id uuid PK`, `duty_assignment_id uuid FK→duty_assignments(id) ON DELETE CASCADE NOT NULL`, `date date NOT NULL`, `effective_soldier_id uuid FK→soldiers(id) ON DELETE SET NULL NULL` (NULL = day cancelled), `reason text NOT NULL` (CHECK in `replacement|no_show_covered|cancelled|manual_edit`), `created_by uuid FK→soldiers(id) ON DELETE SET NULL`, `created_at timestamptz NOT NULL DEFAULT now()`, `UNIQUE (duty_assignment_id, date)`. (`related_listing_id` deferred to v2.)
- **0014 `score_adjustments`** — `id uuid PK`, `soldier_id uuid FK→soldiers(id) ON DELETE CASCADE NOT NULL`, `delta numeric(8,2) NOT NULL`, `reason text NOT NULL`, `duty_type_id uuid FK→duty_types(id) ON DELETE SET NULL NULL`, `created_by uuid FK→soldiers(id) ON DELETE SET NULL`, `created_at timestamptz NOT NULL DEFAULT now()`. Index `(soldier_id)`.

The enum-like columns use `text` + a CHECK constraint (matching the spec's portability preference) rather than a Postgres `ENUM` type, so adding values later needs no type migration.

## Authorization

- **New actions** in `app/auth/authz.py` `Action`: `ASSIGNMENT_MANAGE = "assignment.manage"`, `SCORE_ADJUST = "score.adjust"`.
- Add both to `_DM_ACTIONS` only (not `_COMMANDER_ACTIONS`): per §5.2 commanders may *view* duties/scores in their subtree but may not create/edit assignments or adjust scores. Admin passes via the `role == "admin"` short-circuit.
- For viewing within a subtree, reuse the existing read actions: unit calendar and per-soldier duty/score history require `HIERARCHY_READ`/`SOLDIER_READ` over the target node (commander + DM + admin). A plain soldier reading **own** duties/score is a route-level `user.id == soldier_id` check (mirrors `/api/me`).
- **Transparency table** is readable by any authenticated, password-changed user — a dedicated route with no scope check, returning scores only (no exemption reasons, no notes).
- **Target node** for an assignment/adjustment action = the target soldier's `hierarchy_node_id`. A soldier with no node is actionable only by admin (consistent with Slice 3).

## Services

Three modules, mirroring the Slice 2–3 grain:

### `app/services/assignments.py`
- `create_assignment(session, *, soldier_id, duty_type_id, duty_location_id, start_date, end_date, notes, actor_id)` → validates `start_date <= end_date`, referenced rows exist, **no day-overlap** with the soldier's existing non-cancelled assignments, and **no active mapped exemption** over the block; creates `status='published'`; audits `assignment.create`.
- `cancel_assignment(session, *, assignment, reason, actor_id)` → sets `status='cancelled'`; audits `assignment.cancel` with the required reason in context.
- `set_day_override(session, *, assignment, date, effective_soldier_id, reason, actor_id)` → upserts a `duty_day_overrides` row (date must fall in the block; `effective_soldier_id` NULL = cancel that day; a replacement target must itself pass overlap/exemption checks for that day); audits `assignment.override`.
- `clear_day_override(session, *, assignment, date, actor_id)` → deletes the override row if present (idempotent); audits `assignment.override_clear`.
- `list_assignments(session, *, soldier_id=None, node_path_ids=None, date_from=None, date_to=None)` → query helpers for the personal list and the unit calendar.
- `AssignmentError` domain exception → mapped to HTTP 400/409 in the route.

### `app/services/adjustments.py`
- `create_adjustment(session, *, soldier_id, delta, reason, duty_type_id=None, actor_id)` → rejects `delta == 0` and empty `reason`; audits `score_adjustment.create`. `AdjustmentError` domain exception.
- `list_adjustments(session, *, soldier_id)`.

### `app/services/scoring.py` (read-only, pure aggregation)
- `effective_duty_days(session, *, date_from=None, date_to=None)` → expands every `published` assignment to per-day `(date, effective_soldier_id, duty_type_id)` tuples, applying overrides (replacement reassigns the day; NULL effective drops the day).
- `cumulative_score(session, *, soldier_id)` = Σ `duty_types.score_per_day` over that soldier's effective duty-days + Σ `score_adjustments.delta`.
- `active_days(session, *, soldier)` = `max(1, (today − enrolled_at).days)` minus the count of dates in `[enrolled_at, today]` that are **full-coverage exempt** (an active exemption whose type maps to every currently-`active` duty type; only when ≥1 duty type is active).
- `normalised_score(session, *, soldier)` = `cumulative_score / active_days`.
- `transparency_rows(session)` → one row per non-left soldier: `{soldier_id, full_name, node_name, enrolled_at, active_days, cumulative_score, normalised_score}`, sorted by normalised score descending.
- `soldier_score_breakdown(session, *, soldier_id)` → per-duty-type day counts + score and the adjustment list, for the own-row expansion and the per-soldier history view.

## API routes

New routers wired in `app/main.py`, all under `require_password_changed`.

- `POST /api/assignments` (ASSIGNMENT_MANAGE) — create; 400 `bad_date_range`, 409 `overlap`, 409 `exempted`.
- `GET /api/assignments?soldier_id=&date_from=&date_to=` — own (self-check) or scoped read.
- `POST /api/assignments/{id}/cancel` (ASSIGNMENT_MANAGE) — body `{reason}`.
- `PUT /api/assignments/{id}/overrides/{date}` (ASSIGNMENT_MANAGE) — body `{effective_soldier_id|null, reason}`.
- `DELETE /api/assignments/{id}/overrides/{date}` (ASSIGNMENT_MANAGE).
- `POST /api/score-adjustments` (SCORE_ADJUST) — body `{soldier_id, delta, reason, duty_type_id?}`.
- `GET /api/score-adjustments?soldier_id=` — scoped/self read.
- `GET /api/scoring/transparency` — any authed user; scores-only rows.
- `GET /api/scoring/soldiers/{id}` — own (self) or scoped read; full breakdown.
- `GET /api/calendar/unit?date_from=&date_to=&node_id=` (HIERARCHY_READ over node) — rows = soldiers in subtree, each with their effective duty-days in range.

## Frontend

Mirrors the Slice 2–3 axios/page/i18n patterns; Hebrew RTL throughout; `dd.MM.yyyy` dates; every irreversible action (cancel assignment, override, adjustment) goes through a confirmation modal with a required free-text reason.

- `src/api/{assignments,scoreAdjustments,scoring,calendar}.ts` — typed axios clients.
- `src/pages/DutyManagementPage.tsx` — DM command centre subset: assignment list + create form (soldier/type/location/date-range pickers), per-assignment cancel + day-override actions, and a score-adjustment form. Behind the DM/admin sidebar gate.
- `src/pages/TransparencyPage.tsx` — the שקיפות table for all users; own row expandable into the per-duty-type breakdown + adjustments.
- `src/pages/MyDutiesPage.tsx` — personal list of the signed-in soldier's effective upcoming/past duties.
- `src/pages/UnitCalendarPage.tsx` — commander+ grid: rows = soldiers in subtree, columns = days in the selected range, cells = duty type/location; range picker.
- `src/components/Layout.tsx` — add role-gated sidebar entries (שקיפות + היומן שלי for all; היומן של היחידה for commander+; ניהול תורנויות for DM/admin).
- `src/App.tsx`, `src/i18n/he.json` — routes + Hebrew strings.

## Testing

Backend (pytest + testcontainers, real Postgres + FastAPI + auth):
- Unit: `assignments` (overlap rejection, exemption rejection, override reassignment + cancellation, date validation), `adjustments` (zero-delta + empty-reason rejection, negative allowed), `scoring` (effective-day expansion with overrides, cumulative incl. adjustments, active-days with full-coverage exemption subtraction, normalised, transparency ordering).
- Integration: assignment/override/adjustment API happy paths + error codes; RBAC matrix (soldier/commander/DM/admin) for ASSIGNMENT_MANAGE + SCORE_ADJUST and for the scoped read routes; transparency open to any authed user; audit-row-grew assertion on every mutation.

Frontend:
- Playwright e2e: DM creates an assignment → soldier sees it in "היומן שלי"; DM applies a replacement override → score moves to the replacement soldier on the transparency table; DM makes a negative adjustment → transparency total reflects it.

## Conventions & invariants

- Migrations continue at `0012`; every migration reversible (`alembic check`).
- Files crossing ~400 lines get split by responsibility (scoring vs assignments vs adjustments already separated).
- No hard-coded magic numbers; the only constant introduced (active-days floor of 1) carries a `# why` comment (avoid divide-by-zero for same-day enrolment).
- `audit_log` writes share the mutation's transaction; the append-only role property is unchanged.
- OpenAPI contract regenerated; the TypeScript client stays in sync.

## Open questions deferred to the plan stage

- Whether the unit-calendar range defaults to the current month or `planning.default_window_days` from `system_settings` (lean: current month; revisit when the planning window UI lands in v1.5).
- Pagination of the transparency table for >100 soldiers (lean: none for the pilot; the table is one query and sorts client-side).
