# Algorithm GUI & Backend Bridge — Design

**Date:** 2026-05-30
**Status:** Approved (brainstorm 2026-05-30).
**Depends on:** Slice 5 CP-SAT pure algorithm (done, `slice-5-cp-sat-algorithm` branch), personal constraints + approval flow (must land first — this slice reads `approved_constraint_dates` from the constraints table).

## Goal

Wire the pure CP-SAT algorithm module into the FastAPI app with a background-job API, DB persistence (proposals, explanations, reserves), and two frontend surfaces: the DM's "חלון תכנון" planning window and the soldier's "?למה קיבלתי" (Why did I get this?) modal.

## Scope

- `algorithm_jobs`, `reserve_assignments`, `assignment_explanations` DB tables + Alembic migration `0015`
- `DutyAssignment.status` new values: `algorithm_draft`, `algorithm_rejected`
- `app/services/algorithm.py` — bridge: DB → pure module → persist results
- `app/routes/algorithm.py` — 4 endpoints, background task via FastAPI `BackgroundTasks`
- Frontend: planning window section on `DutyManagementPage`, proposals table, "?למה קיבלתי" modal on both `DutyManagementPage` (DM, full) and `MyDutiesPage` (soldier, redacted)
- Shadow mode via `system_settings` key `algorithm_mode` (`shadow` | `dm_reviewed`)
- i18n keys under `algorithm` namespace in `he.json`

**Out of scope:** Celery/task queue (FastAPI BackgroundTasks is sufficient at pilot scale), greedy online mode (v2), replacement marketplace, punishment duties, personal constraints table (prior slice).

---

## 1. Database (migration 0015)

### 1.1 New tables

```sql
algorithm_jobs (
  id               uuid PK DEFAULT gen_random_uuid()
  status           text NOT NULL DEFAULT 'pending'   -- 'pending' | 'running' | 'done' | 'failed'
  planning_start   date NOT NULL
  planning_end     date NOT NULL
  duty_type_ids    jsonb NOT NULL    -- array of uuid strings
  duty_location_id uuid FK duty_locations.id ON DELETE RESTRICT
  settings_json    jsonb NOT NULL    -- K, T, W, alpha, beta, time_limit at time of run
  mode             text NOT NULL     -- 'shadow' | 'dm_reviewed'
  created_by       uuid FK soldiers.id ON DELETE SET NULL
  started_at       timestamptz NULL
  finished_at      timestamptz NULL
  error_message    text NULL
  created_at       timestamptz NOT NULL DEFAULT now()
)

reserve_assignments (
  id                  uuid PK DEFAULT gen_random_uuid()
  duty_assignment_id  uuid FK duty_assignments.id ON DELETE CASCADE
  reserve_soldier_id  uuid FK soldiers.id ON DELETE CASCADE
  reason              text NOT NULL   -- 'auto: nearest in hierarchy' | 'manual override'
)

assignment_explanations (
  id                  uuid PK DEFAULT gen_random_uuid()
  duty_assignment_id  uuid FK duty_assignments.id ON DELETE CASCADE
  payload             jsonb NOT NULL
  algorithm_version   text NOT NULL
  solver_seed         text NOT NULL
  generated_at        timestamptz NOT NULL DEFAULT now()
)
```

### 1.2 DutyAssignment.status extension

Two new valid values added to the existing `status` column (text, no enum constraint):

- `algorithm_draft` — proposal created by the algorithm, not yet reviewed by DM
- `algorithm_rejected` — DM explicitly discarded this proposal

Published assignments visible to soldiers remain `status = 'published'` only. `algorithm_draft` and `algorithm_rejected` rows are invisible to non-DM roles.

---

## 2. Backend service & API

### 2.1 `app/services/algorithm.py`

Bridge between the DB and the pure `app.algorithm` module. No direct SQL in routes — all logic lives here.

**`run_algorithm_job(job_id, session)`** — called by the background task:

1. Load job row; set `status = 'running'`, `started_at = now()`
2. Load `SoldierInput` list:
   - Cumulative score + active days: call `scoring.cumulative_scores(session)`
   - Exempted duty type IDs: resolve via `ExemptionDutyTypeMap` for each soldier's active exemptions
   - Approved constraint dates: query the personal constraints table (populated by the prior slice)
3. Load `DutyBlock` list: synthesise one block per day in `[planning_start, planning_end]` per duty type in the job's `duty_type_ids` + location
4. Load `ExistingAssignment` list: published assignments whose date range overlaps the planning window (± `W` days for spacing boundary)
5. Call `solve(soldiers, duties, existing, settings)` → `SolverResult`
6. On `INFEASIBLE`: set `status = 'failed'`, `error_message` = JSON of relaxation steps + fewest-eligible duties; return
7. Call `build_explanations(...)` → `ExplanationData`
8. Call `select_reserves(...)` → reserve tuples
9. Persist:
   - Insert `DutyAssignment` rows with `status = 'algorithm_draft'` for each assignment
   - Insert `assignment_explanations` rows per assignment
   - Insert `reserve_assignments` rows per reserve tuple
10. Set job `status = 'done'`, `finished_at = now()`
11. On any exception: set `status = 'failed'`, `error_message = str(e)`

### 2.2 `app/routes/algorithm.py`

```
POST   /api/algorithm/jobs                                              duty_manager  — submit run, start background task
GET    /api/algorithm/jobs/{id}                                         duty_manager  — poll status + result summary
GET    /api/algorithm/jobs/{id}/explanations/{asgn_id}                  any           — fetch explanation (redacted by role)
DELETE /api/algorithm/jobs/{id}                                         duty_manager  — cancel pending job (sets status=failed)
POST   /api/algorithm/jobs/{id}/proposals/{asgn_id}/accept              duty_manager  — publish one proposal
POST   /api/algorithm/jobs/{id}/proposals/{asgn_id}/reject              duty_manager  — discard one proposal
```

**`POST /api/algorithm/jobs` request body:**
```json
{
  "planning_start":    "2026-06-01",
  "planning_end":      "2026-06-30",
  "duty_type_ids":     ["<uuid>", "..."],
  "duty_location_id":  "<uuid>",
  "mode":              "shadow",
  "settings": {
    "K": 8, "T": 7, "W": 14,
    "alpha": 1.0, "beta": 2.0,
    "time_limit_seconds": 30
  }
}
```

**`GET /api/algorithm/jobs/{id}` response:**
```json
{
  "id": "...",
  "status": "done",
  "mode": "shadow",
  "planning_start": "2026-06-01",
  "planning_end":   "2026-06-30",
  "started_at": "...", "finished_at": "...",
  "error_message": null,
  "proposals": [
    {
      "assignment_id": "...",
      "soldier_id": "...",
      "duty_type_id": "...",
      "duty_location_id": "...",
      "start_date": "...",
      "end_date": "...",
      "reserve_soldier_id": "...",
      "norm_score_before": 0.42,
      "norm_score_after":  0.45
    }
  ],
  "solver_metrics": { "wall_time": 3.2, "conflicts": 14, "branches": 80 },
  "relaxed": []
}
```

**`GET .../explanations/{assignment_id}` response (soldier view):**
```json
{
  "assigned": true,
  "norm_score_before": 0.42,
  "norm_score_after":  0.45,
  "blocked_count": 7,
  "tiebreaker_note": "lowest_post_norm_score",
  "global_before": { "min_gap": 3, "norm_variance": 0.12 },
  "global_after":  { "min_gap": 4, "norm_variance": 0.08 }
}
```

**DM view** additionally includes: per-candidate `blocking_constraints` (with exemption type name), full score vectors, candidate soldier names.

**Authorization:** explanation endpoint returns 403 if the requesting soldier is not the assignee and does not have `duty_manager` role.

### 2.3 Shadow mode

`system_settings` key `algorithm_mode`:
- `shadow` — `algorithm_draft` assignments are invisible to soldiers and do not affect scoring. DM can run the algorithm and compare proposals against their manual assignments without any soldier-visible effect.
- `dm_reviewed` — same behaviour; name signals intent that the DM is actively adopting algorithm output.

Flipping `algorithm_mode` in `system_settings` is a DM action audited in `audit_log`.

Accepting a proposal: `POST /api/algorithm/jobs/{job_id}/proposals/{assignment_id}/accept` — flips `algorithm_draft` → `published`, writes audit log.
Rejecting a proposal: `POST /api/algorithm/jobs/{job_id}/proposals/{assignment_id}/reject` — flips `algorithm_draft` → `algorithm_rejected`, writes audit log.

These are new endpoints on the algorithm router (not the assignments router) to keep accept/reject logic self-contained and audited with algorithm context.

---

## 3. Frontend

### 3.1 DutyManagementPage — planning window section

New collapsible "חלון תכנון" section below the existing assignment form:

**Controls:**
- Date range: planning_start, planning_end (date inputs)
- Duty type multi-select (checkboxes from existing duty types list)
- Location select
- Mode toggle: shadow / dm_reviewed
- Expandable settings panel: K, T, W, α, β sliders with defaults; time_limit number input

**Run flow:**
1. "הרץ אלגוריתם" button → `POST /api/algorithm/jobs` → store `jobId` in state
2. Poll `GET /api/algorithm/jobs/{jobId}` every 3s while status is `pending` or `running`
3. Show spinner with elapsed time during poll
4. On `done`: render proposals table (see below)
5. On `failed`: show error message + relaxation steps tried (from `relaxed` array + `error_message`)

**Proposals table columns:**
| תאריך | סוג תורנות | חייל | חייל מילואים | ניקוד לפני | ניקוד אחרי | פעולות |
|---|---|---|---|---|---|---|
| start–end | duty type name | soldier name | reserve name | norm_before | norm_after | ✓ אשר / ✗ דחה / ?למה |

"?למה" button opens the DM explanation modal (full view).

Accept → `POST /api/algorithm/jobs/{jobId}/proposals/{assignmentId}/accept`; row turns green.
Reject → `POST /api/algorithm/jobs/{jobId}/proposals/{assignmentId}/reject`; row turns grey and is hidden.

### 3.2 MyDutiesPage — "?למה קיבלתי" button

Each duty row/calendar tile that has an explanation gets a "?למה קיבלתי" button. Clicking opens a modal showing the **soldier-redacted view**:

- "נבחרת כי X חיילים אחרים היו מוגבלים"
- "הניקוד המנורמל שלך לפני: Y, אחרי: Z"
- "פער מינימלי בין תורנויות לפני: A ימים, אחרי: B ימים"
- No other soldier names, exemption type names, or score details visible

Only shown for duties with `status = 'published'` that have a linked `assignment_explanations` row.

### 3.3 New files

- `frontend/src/api/algorithm.ts` — `submitJob`, `pollJob`, `getExplanation`, `acceptProposal(jobId, assignmentId)`, `rejectProposal(jobId, assignmentId)`
- `frontend/src/components/AlgorithmPlanningWindow.tsx` — the collapsible section
- `frontend/src/components/ExplanationModal.tsx` — shared modal, role-aware rendering

### 3.4 i18n (`he.json` additions)

New `algorithm` block:
```json
"algorithm": {
  "title": "חלון תכנון",
  "run_button": "הרץ אלגוריתם",
  "running": "האלגוריתם רץ...",
  "done": "הצעות האלגוריתם",
  "failed": "האלגוריתם נכשל",
  "shadow_mode": "מצב צל",
  "dm_reviewed_mode": "מצב סקירה",
  "accept": "אשר",
  "reject": "דחה",
  "why_button": "?למה קיבלתי",
  "blocked_count": "{{count}} חיילים היו מוגבלים",
  "norm_before": "ניקוד מנורמל לפני",
  "norm_after": "ניקוד מנורמל אחרי",
  "min_gap_before": "פער מינימלי לפני",
  "min_gap_after": "פער מינימלי אחרי",
  "relaxed_k": "הורחב K ל-{{value}}",
  "relaxed_t": "הורחב T ל-{{value}}",
  "no_solution": "לא נמצא פתרון אפשרי"
}
```

---

## 4. Error handling

| Scenario | Behaviour |
|---|---|
| Solver INFEASIBLE after full relaxation chain | Job status `failed`; `error_message` lists duties with fewest eligible soldiers |
| No active soldiers | Job status `failed` immediately |
| Background worker crash | Job stuck in `running`; a startup cleanup task resets jobs with `started_at` > 2 min ago and no `finished_at` to `failed` |
| Explanation not found | 404 |
| Non-assignee soldier requests explanation | 403 |
| DM polls a job that belongs to a different scope | 403 |

---

## 5. Testing

- **Unit:** `test_algorithm_service.py` — mock DB session, verify bridge loads data correctly, verify proposals are persisted
- **Integration:** `test_algorithm_routes.py` — full DB, submit job, poll until done, verify `algorithm_draft` rows created, verify accept/reject transitions
- **Frontend unit:** `AlgorithmPlanningWindow.test.tsx` — mock API, verify polling loop, verify proposal table renders
- **E2E (Playwright):** DM runs algorithm → proposals appear → DM accepts one → soldier sees "?למה קיבלתי" on their duty

---

## 6. Sequencing

1. Personal constraints + approval flow (prior slice — provides `approved_constraint_dates`)
2. This slice — algorithm GUI + backend bridge
3. Future: flip `algorithm_mode` default from `shadow` to `dm_reviewed` once shadow-mode validation passes
