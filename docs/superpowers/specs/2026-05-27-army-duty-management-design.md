# Army Duty Management System — Design

**Date:** 2026-05-27
**Status:** Draft for review
**Pilot target:** ~100 soldiers, one branch

---

## 1. Purpose and scope

This system manages duty (תורנות) allocation for an army unit: who does what duty, when, and how cumulative effort is kept fair across soldiers. It replaces ad-hoc manual rosters with a system that:

- Tracks soldiers, hierarchy, duty types, exemptions, and personal constraints.
- Assigns duties either by hand (v1) or by a fairness-aware optimization algorithm (v1.5+).
- Enables peer-to-peer replacements (v2).
- Audits every state change for accountability.
- Exposes a transparent peer-comparable scoreboard (שקיפות).

The first release covers the **foundation** — data model, UI, manual workflows. The algorithm lands in v1.5. The social layer (replacement marketplace, punishment duties) lands in v2.

---

## 2. Decisions and constraints

| Decision | Choice |
|---|---|
| Deployment | Self-hostable architecture; POC on public internet. HTTPS + auth from day one. |
| Backend stack | Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, OR-Tools CP-SAT. |
| Frontend stack | React 18 + Vite + TypeScript; TanStack Query; shadcn/ui with RTL adapter. |
| Database | Postgres 16 (single instance, daily encrypted backup). |
| UI language | Hebrew-only, RTL. Backend code and identifiers in English. |
| Identity | Personal number (מספר אישי) + password. |
| Roles | Soldier, Commander, Duty Manager, Admin — composable with hierarchy scope. |
| Duty unit | Contiguous block `(soldier, duty_type, location, start_date, end_date)` + per-day override layer. |
| Algorithm mode | Hybrid — CP-SAT batch (primary) + greedy online (ad-hoc emergencies, v2). |
| Score window | All-time, normalized by active days since enrolment; per-duty-type denominator excludes exempted days. |
| Hierarchy | team → group → branch → department (small to big), arbitrary depth in code, this fixed enum in v1. |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser  ──  React SPA (Vite, TS, RTL via dir="rtl")        │
│                  i18n: react-i18next, single he-IL bundle     │
│                  state: TanStack Query + Zustand for UI       │
│                  components: shadcn/ui with RTL adapter       │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTPS, JWT bearer token in Authorization
┌────────────────────▼────────────────────────────────────────┐
│  Caddy reverse proxy (TLS, gzip, static SPA)                 │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  FastAPI app (uvicorn workers)                               │
│   ├─ routes/     REST endpoints, Pydantic schemas            │
│   ├─ services/   business logic, one module per context      │
│   ├─ algorithm/  CP-SAT batch + greedy online (pure)         │
│   ├─ db/         SQLAlchemy models, Alembic migrations       │
│   ├─ auth/       argon2id password, JWT, RBAC dep            │
│   └─ audit/      append-only audit writer + reader           │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  Postgres 16 (single instance; nightly encrypted backup)     │
└─────────────────────────────────────────────────────────────┘
```

**Key choices:**

- **Monolithic FastAPI app + workers.** No microservices, no message queue, no Celery for v1. CP-SAT solves the pilot-scale problem (a few hundred binary variables) in single-digit seconds synchronously.
- **Postgres for everything**: app data, sessions, audit, system settings.
- **`algorithm/` is a pure library** — no imports from `db/` or `routes/`. It takes plain Python data in and returns plain Python data out. Unit-testable on synthetic 1000-soldier populations without a database.
- **Repo layout:** one repo with `backend/` and `frontend/`. The FE consumes a TypeScript client generated from FastAPI's `openapi.json`. CI fails if the contract drifts.
- **Deployment artefact:** `docker-compose.yml`. Three containers (`app`, `db`, `caddy`). Same compose file for POC on a single VM and for self-hosted deployment.
- **Configuration:** all runtime knobs live in a `system_settings` table editable by the duty manager. Env vars are only for deployment-level concerns (DB URL, JWT secret, log level).

---

## 4. Data model

### 4.1 Core entities (v1)

```sql
-- Soldiers and identity
soldiers (
  id               uuid PK
  personal_number  text UNIQUE NOT NULL    -- canonical identity
  full_name        text NOT NULL
  password_hash    text NOT NULL           -- argon2id
  role             enum('soldier','commander','duty_manager','admin')
  hierarchy_node_id uuid FK -> hierarchy_nodes.id
  enrolled_at      date NOT NULL           -- start of active-days window
  left_at          date NULL               -- soft delete
  phone            text NULL
  created_at, updated_at  timestamptz
)

-- Hierarchy: team -> group -> branch -> department
hierarchy_nodes (
  id            uuid PK
  parent_id     uuid FK -> hierarchy_nodes.id NULL
  level         enum('team','group','branch','department')
  name          text NOT NULL
  commander_id  uuid FK -> soldiers.id NULL
  path_ids      uuid[]                     -- materialized ancestor chain incl self
)

-- Duty configuration
duty_types (
  id             uuid PK
  name           text NOT NULL UNIQUE     -- e.g. "שמירה", "ניקיון"
  score_per_day  numeric(6,2) NOT NULL    -- editable by duty_manager
  description    text
  active         boolean DEFAULT true
)

duty_locations (
  id      uuid PK
  name    text NOT NULL                   -- e.g. "עמדת שער דרום"
  base    text NULL
  active  boolean DEFAULT true
)

-- Exemptions (פטור)
exemption_types (
  id           uuid PK
  name         text NOT NULL UNIQUE       -- e.g. "פטור רפואי גב"
  description  text
)

-- Configurable mapping: which exemption types exempt from which duty types
exemption_duty_type_map (
  exemption_type_id  uuid FK,
  duty_type_id       uuid FK,
  PRIMARY KEY (exemption_type_id, duty_type_id)
)

-- A specific exemption granted to a specific soldier
soldier_exemptions (
  id                 uuid PK
  soldier_id         uuid FK
  exemption_type_id  uuid FK
  start_date         date NOT NULL
  end_date           date NULL              -- NULL = forever
  reason             text NULL              -- visible to commanders, DMs, the soldier
  granted_by         uuid FK -> soldiers.id
  granted_at         timestamptz
)

-- Personal constraints (dates a soldier wants off)
personal_constraints (
  id            uuid PK
  soldier_id    uuid FK
  start_date    date NOT NULL
  end_date      date NOT NULL
  reason        text NOT NULL
  status        enum('pending','approved','rejected')
  decided_by    uuid FK -> soldiers.id NULL
  decided_at    timestamptz NULL
  decision_note text NULL
  created_at    timestamptz
)
-- Application invariant: sum of (end-start+1) for approved+pending FUTURE
-- constraints per soldier <= system_settings['constraints.personal_cap_days'].

-- Duty assignments (contiguous blocks)
duty_assignments (
  id                uuid PK
  soldier_id        uuid FK              -- the originally assigned soldier
  duty_type_id      uuid FK
  duty_location_id  uuid FK
  start_date        date NOT NULL
  end_date          date NOT NULL
  status            enum('proposed','published','cancelled')
  created_by        uuid FK -> soldiers.id
  created_at        timestamptz
  notes             text
)
-- Indexes: (soldier_id, start_date), (start_date, end_date)

-- Per-day override layer: covers replacements, no-shows, partial cancellations.
-- A duty-day's effective assignee = override.effective_soldier_id if a row
-- exists for (assignment, date), else duty_assignments.soldier_id.
duty_day_overrides (
  id                    uuid PK
  duty_assignment_id    uuid FK
  date                  date NOT NULL
  effective_soldier_id  uuid FK -> soldiers.id NULL  -- NULL = day cancelled
  reason                enum('replacement','no_show_covered','cancelled','manual_edit')
  related_listing_id    uuid NULL                    -- v2 marketplace link
  created_by            uuid FK
  created_at            timestamptz
  UNIQUE (duty_assignment_id, date)
)

-- Manual score corrections / compensations
score_adjustments (
  id            uuid PK
  soldier_id    uuid FK
  delta         numeric(8,2) NOT NULL      -- can be negative
  reason        text NOT NULL              -- required, shown in audit
  duty_type_id  uuid FK NULL               -- optional category
  created_by    uuid FK -> soldiers.id
  created_at    timestamptz
)

-- Configuration (single source of truth for tunable behaviour)
system_settings (
  key         text PRIMARY KEY
  value       jsonb NOT NULL
  updated_by  uuid FK
  updated_at  timestamptz
)

-- Audit log (append-only, never updated, never deleted)
audit_log (
  id           uuid PK
  actor_id     uuid FK
  action       text NOT NULL              -- e.g. 'duty_assignment.create'
  entity_type  text NOT NULL
  entity_id    uuid
  before       jsonb NULL
  after        jsonb NULL
  context      jsonb NULL                 -- request id, IP, reason text, etc.
  created_at   timestamptz NOT NULL DEFAULT now()
)
-- Postgres role 'app' has INSERT and SELECT only on this table.
-- Separate db_admin role (used for backup/migrate) has UPDATE/DELETE.
```

### 4.2 v1.5 additions

```sql
reserve_assignments (
  id                  uuid PK
  duty_assignment_id  uuid FK
  reserve_soldier_id  uuid FK -> soldiers.id
  reason              text   -- "auto: nearest in hierarchy" or "manual override"
)

assignment_explanations (
  id                  uuid PK
  duty_assignment_id  uuid FK
  payload             jsonb NOT NULL    -- structured explanation from the solver
  algorithm_version   text NOT NULL
  solver_seed         text NOT NULL
  generated_at        timestamptz
)
```

### 4.3 v2 additions (sketched)

```sql
replacement_listings ( id, duty_assignment_id, date, posted_by, reason, status, ... )
replacement_offers   ( id, listing_id, offering_soldier_id, accepted_at, ... )
punishment_duties    ( id, soldier_id, source_assignment_id, severity, status, ... )
```

### 4.4 Derived quantities (not stored)

- **Cumulative score** for soldier S = sum of `duty_types[d.type].score_per_day` over duty-days `d` effectively assigned to S (respecting overrides), plus the sum of S's `score_adjustments.delta`. Computed on demand by SQL; cached if needed later.
- **Active days for soldier S** = `(today − enrolled_at)` minus days where an active full-coverage exemption applies. For per-duty-type normalisation, subtract only days where an exemption that covers *that* duty type was active.
- **Normalised score** = cumulative_score / active_days. The variance bound K applies here.

### 4.5 Notes on the model

- All Hebrew is plain UTF-8.
- Leaving the unit is a soft delete (`left_at`), preserving audit interpretability.
- The override layer is the key trick: a 7-day block stays a single row; a one-day swap is one extra row. The effective assignee per date is computed by query, not by mutating the block.

---

## 5. Roles and permissions

### 5.1 Role definitions

- **Soldier** — default; every user.
- **Commander** — a soldier referenced by `hierarchy_nodes.commander_id`. Scope = the subtree rooted at every node they command (recursive via `path_ids`).
- **Duty Manager** — the operational role; manages duties, exemptions, constraints, scoring, hierarchy editing within their scope. For the pilot, typically one DM scoped to the branch.
- **Admin** — system-level: account/role assignment, cross-scope authority. Does *not* manage duties (separation of concerns).

Roles compose with scope. A soldier can be a commander of a team and the duty manager of a branch; the auth layer resolves permission per (action, target).

### 5.2 Permission matrix (v1)

| Action | Soldier | Commander (subtree) | Duty Manager (scope) | Admin |
|---|---|---|---|---|
| View own profile, duties, score | ✓ | ✓ | ✓ | ✓ |
| Submit personal constraint request | ✓ | ✓ | ✓ | ✓ |
| View own active exemptions | ✓ | ✓ | ✓ | ✓ |
| View own "why did I get this?" | ✓ | ✓ | ✓ | ✓ |
| View transparency table (scores only) | ✓ | ✓ | ✓ | ✓ |
| View calendar of soldiers in subtree | — | ✓ | ✓ | ✓ |
| View each subtree soldier's score and history | — | ✓ | ✓ | ✓ |
| View any soldier's exemptions (incl. private reason) | own only | ✓ (subtree) | ✓ (scope) | — |
| View any soldier's personal constraints | own only | ✓ (subtree) | ✓ (scope) | — |
| Approve / reject personal constraints | — | ✓ (subtree) | ✓ (scope) | — |
| Grant / revoke exemptions | — | ✓ (subtree) | ✓ (scope) | — |
| Create / edit duty assignments | — | — | ✓ (scope) | — |
| Run the assignment algorithm (v1.5) | — | — | ✓ (scope) | — |
| Override an assignment | — | — | ✓ (scope) | — |
| Adjust soldier scores manually | — | — | ✓ (scope) | — |
| Edit duty type scoring | — | — | ✓ | — |
| Edit exemption ↔ duty-type mapping | — | — | ✓ | — |
| Edit `system_settings` | — | — | ✓ | ✓ |
| View audit log | — | scoped read | ✓ (scope) | ✓ (all) |
| Onboard soldier / reset password | — | — | ✓ (scope) | ✓ |
| Edit hierarchy (move soldiers, rename, add nodes) | — | — | ✓ (scope) | ✓ (all) |
| Assign / revoke roles | — | — | — | ✓ |

### 5.3 Auth implementation

- **Password hashing** via `argon2id` (argon2-cffi), tuned to ~100ms on deployment hardware.
- **JWT access token** (15 min) + **refresh token** (`HttpOnly; Secure; SameSite=Strict` cookie, 30 days). Server-side revocation list for emergency lockout.
- **Authorization** centralised in a FastAPI dependency `require(action, target=...)` that evaluates role + scope. Every endpoint goes through it; tests assert it.
- **Rate limit on login** via `slowapi`: 5 attempts per personal_number per 5 min, escalating lockout.
- **Password policy:** ≥10 chars (length over complexity); forced change on first login.

---

## 6. The fairness algorithm

### 6.1 Inputs

- Soldiers `S = {s_1, …, s_n}`, each with: enrolment date, cumulative score, active days per duty type, hierarchy position, approved personal constraints, active exemptions.
- Duties to fill `D = {d_1, …, d_m}`, each a contiguous block: duty type, location, start date, end date.
- Existing duty assignments touching the planning horizon (for spacing checks across the boundary).
- System settings: `K`, `T`, `W`, `α`, `β`, solver time limit.

### 6.2 Decision variable

`x[d, s] ∈ {0, 1}` — soldier `s` is assigned the entirety of block `d`.

### 6.3 Hard constraints

Define `block_score(d) = duty_types[d.type].score_per_day · (d.end_date − d.start_date + 1)` — the score a soldier gains for completing the entire block. Define `covers(d, t) = 1` if date `t` falls in `[d.start_date, d.end_date]`, else `0`.

1. **Coverage.** `∀ d : Σ_s x[d, s] = 1`.
2. **Exemption.** `x[d, s] = 0` if `s` has an active exemption type during `d.start..d.end` that maps to `d.duty_type`.
3. **Personal constraint.** `x[d, s] = 0` if `s` has an *approved* constraint overlapping `d.start..d.end`.
4. **No overlap.** A soldier cannot be assigned two blocks covering the same day: `∀ s, t : Σ_d covers(d, t) · x[d, s] ≤ 1`.
5. **Normalised-score variance.**
   `cum(s)` = cumulative score from history.
   `add(s) = Σ_d block_score(d) · x[d, s]` = score gained in this batch.
   `active(s)` = active days denominator.
   `norm(s) = (cum(s) + add(s)) / active(s)`.
   `max_s norm(s) − min_s norm(s) ≤ K`.

### 6.4 Soft objective

Two terms combined into a single scalar:

- **Density penalty.** For every soldier `s` and every rolling window of length `W` (default 14), let `density(s, w)` = the number of duty-days in window `w`. Penalty contribution `max(0, density(s, w) − T)²`, where `T` (default 7) is the soft cap on duty-days per window.
  *Implementation note: CP-SAT is integer-linear. The quadratic shape is approximated by stepwise slack variables (`excess_1, excess_2, …`), each with increasing linear cost — a standard convex piecewise-linear approximation.*
- **Spacing reward.** `min_gap` = the smallest number of empty days between any soldier's consecutive duty-days, considering existing duties on both sides of the planning window. Maximise this.

Combined:
```
maximise  α · min_gap  −  β · Σ_{s, w} penalty(s, w)
```
`α` and `β` are configurable; defaults `α=1.0`, `β=2.0`.

### 6.5 Tie-breakers

When several solutions reach the same objective value:

1. Minimise standard deviation of post-assignment normalised scores.
2. Prefer assignments where the soldier's hierarchy node aligns with the duty's location (when this metadata is configured).
3. Prefer the soldier with the lower current normalised score.

### 6.6 Why CP-SAT

`maximise min` and `max − min ≤ K` are natively expressible in CP-SAT via `AddMaxEquality` / `AddMinEquality`. The pilot-scale problem (≈30 duties × ≈100 soldiers = ~3000 binary variables) solves in single-digit seconds with the default presolve. A determinism seed (default: hash of the planning window dates) is passed so repeat runs of the same input return the same output — important for audit and reproducibility.

### 6.7 Online (greedy) mode for ad-hoc duties (v2)

When a single duty appears between batches: enumerate soldiers, filter by hard constraints 2/3/4, then rank candidates by the lex-smallest tuple
```
(post_assignment_norm_score, −resulting_min_gap_for_them, hierarchy_distance_to_existing_team)
```
and pick the best. Same scoring philosophy as batch — applied one-at-a-time.

### 6.8 Infeasibility relaxation chain

If the solver returns "infeasible", apply in order, surfacing each step to the DM:

1. Raise `K` by 1.
2. Raise the density soft cap `T` by 1.
3. Drop the lowest-priority *pending* personal constraints (with explicit manager confirmation).
4. Fail with "cannot cover these duties: …" — never silently compromise.

### 6.9 Reserve-soldier selection (v1.5)

After primary assignments are decided: for each block, walk the hierarchy outward from the primary assignee (same team → sibling teams in the group → sibling groups in the branch → branch) and pick the closest soldier who passes hard constraints 2/3/4 *for that block*. Store in `reserve_assignments`.

### 6.10 Explainability

When the solver finishes, for each `(duty d → soldier s)` we record into `assignment_explanations.payload`:

- Candidates considered (all soldiers passing hard constraints).
- For each rejected candidate: which hard constraint excluded them (with type-level specifics for the DM; redacted for cross-soldier viewers).
- For each candidate that passed hard constraints but wasn't chosen: their score-vector at decision time and the tiebreaker that pushed them down.
- Global metrics before and after: `min_gap`, normalised-score variance.
- Algorithm version + solver seed.

The personal "?למה קיבלתי" modal renders this filtered by the viewer's role: a soldier sees aggregate reasons ("other candidates were constrained") but never another soldier's exemption type.

---

## 7. Page surfaces

Hebrew RTL throughout. Sidebar visibility is role-dependent.

```
🏠  ראשי                         (all)
📅  היומן שלי                    (all)
🚫  הבקשות והפטורים שלי           (all)
🔄  חיפוש מחליפים                 (all, v2)
─────────────────────────────────
👥  היומן של היחידה              (commander+)
🛡️  שקיפות                        (all — read-only table)
─────────────────────────────────
⚙️  ניהול תורנויות                (duty_manager)
🗂  אנשי צוות והיררכיה            (duty_manager scope, admin all)
🔧  הגדרות מערכת                  (duty_manager, admin)
📋  יומן הביקורת                  (commander scoped, duty_manager scope, admin all)
─────────────────────────────────
👤  פרופיל / יציאה                (all)
```

**Per-page summary:**

1. **ראשי** — personal landing: upcoming duties, current cumulative + normalised score, transparency rank, constraint quota used, pending requests.
2. **היומן שלי** — month-grid personal calendar (RTL). Click day → side panel with duty details, reserve soldier, "?למה קיבלתי" button.
3. **הבקשות והפטורים שלי** — personal constraint history + submission form (cap-enforced); read-only list of own active exemptions.
4. **חיפוש מחליפים (v2)** — replacement marketplace; offers from others sorted by hierarchy distance + match quality; create/cancel own postings; see incoming offers.
5. **היומן של היחידה** — calendar grid with rows = soldiers in subtree, grouped by team. Filter chips, drill-down to any soldier's full record.
6. **שקיפות** — single table: שם, יחידה, יום הצטרפות, ימים פעילים, ניקוד מצטבר, ניקוד מנורמל. Other rows not expandable; own row expandable for one's own breakdown.
7. **ניהול תורנויות** — DM command centre: open duties, create duties, planning window with "הרץ אלגוריתם" (v1.5+), score adjustments, constraint approvals, exemptions, duty types.
8. **אנשי צוות והיררכיה** — hierarchy tree + soldier list; drag-to-reparent; create/rename/delete nodes within scope.
9. **הגדרות מערכת** — keyed form against `system_settings`; each row shows current, default, last-changed-by; changes audited.
10. **יומן הביקורת** — reverse-chronological feed with filters, JSON diff per row, CSV export.
11. **פרופיל** — own info, change password, logout, role-context switcher when applicable.

**Cross-cutting UX rules:**

- Every irreversible action goes through a confirmation modal with a required free-text reason saved to audit.
- Dates rendered `dd.MM.yyyy` with Hebrew weekday labels.
- Status colour palette consistent app-wide: green = approved, amber = pending, red = rejected, grey = cancelled.
- No dark mode in v1.

**System / hidden routes (not in navigation):**

- `/login` — personal number + password.
- `/health` — Docker healthcheck; returns 200 if DB reachable.
- `/api/docs`, `/api/openapi.json` — FastAPI auto-generated docs. Gated behind admin role outside of dev.

---

## 8. Audit and security

### 8.1 Audit principles

1. Every state-changing operation writes an audit row.
2. The `audit_log` table is append-only at the Postgres role level (app role has `INSERT, SELECT` only).
3. `before` and `after` JSONB snapshots make diffs viewable without joining to historical tables and survive schema changes.
4. Sensitive UI actions require a free-text reason saved in `audit_log.context` (cancelling a duty, revoking an exemption, score adjustment, manual override of an algorithm proposal, hierarchy edits).
5. Audit row writes happen in the same DB transaction as the change — either both or neither.

### 8.2 Threat model and mitigations (POC, internet-exposed)

| Concern | Mitigation |
|---|---|
| Password storage | `argon2id` with per-password salt. |
| Brute-force login | `slowapi`: 5 attempts per personal_number per 5 min; lockout escalates to 30 min after 20 failures. |
| Session theft | Short-lived JWT access token; `HttpOnly Secure SameSite=Strict` refresh cookie; server-side revocation list. |
| CSRF | Bearer token in `Authorization` header; cookie is `SameSite=Strict`. |
| XSS | React default escaping; no `dangerouslySetInnerHTML`; CSP header at Caddy. |
| SQL injection | All queries through SQLAlchemy parameterisation. |
| Insecure transport | Caddy terminates TLS; HTTP → HTTPS 301; HSTS 6 months. |
| Privilege escalation | Single central `require(action, target)` dep on every endpoint; tests assert wiring. |
| PII in logs | Log formatter scrubs `personal_number`, `password`, `phone` from logged payloads. |
| Backup leakage | Backups GPG-encrypted to an operator-held public key. |
| Default passwords | None. Admin generates per-user one-time tokens; soldier sets own password on first login. |
| CORS abuse | Allowlist of configured frontend origins only. |
| API docs in prod | `/api/docs` and `/api/openapi.json` gated behind admin role outside dev. |
| Explanation data leakage | Cross-soldier explanation rows redact other soldiers' exemption types — only the DM and the assigned soldier see full reasoning. |

### 8.3 Configuration (`system_settings`)

All knobs live in one keyed table.

| Key | Default | Type | Description (he) |
|---|---|---|---|
| `fairness.K` | 8 | number | מקסימום פער בין ניקוד מנורמל |
| `fairness.density_cap_T` | 7 | number | מקסימום ימי תורנות בחלון |
| `fairness.density_window_W` | 14 | number | אורך חלון לבדיקת צפיפות |
| `fairness.alpha` | 1.0 | number | משקל min_gap בפונקציית המטרה |
| `fairness.beta` | 2.0 | number | משקל קנס הצפיפות |
| `fairness.score_normalization` | `active_days` | enum | שיטת נירמול הניקוד |
| `constraints.personal_cap_days` | 15 | number | מקסימום ימי בקשה לחייל |
| `constraints.require_manager_approval` | true | bool | בקשה חייבת אישור |
| `planning.default_window_days` | 30 | number | אורך חלון תכנון |
| `planning.solver_time_limit_seconds` | 30 | number | תקרת זמן לפתרון |
| `planning.require_manager_review` | true | bool | אישור לפני פרסום |
| `auth.session_minutes` | 15 | number | תוקף Access Token |
| `auth.refresh_days` | 30 | number | תוקף Refresh Token |
| `auth.login_rate_limit_per_5m` | 5 | number | הגבלת התחברות |
| `audit.export_max_days` | 365 | number | מרווח מקסימלי לייצוא |

Changing any setting writes a `before`/`after` audit row.

### 8.4 What is deliberately not configurable

- The role list (Soldier / Commander / Duty Manager / Admin) — code-level enum.
- The `audit_log.action` vocabulary — code-level.
- The algorithm formulation — only the weights (`α`, `β`, `K`, `T`, `W`) are tunable.

---

## 9. Phased rollout

### 9.1 v1 — Foundation (target: pilot-ready in ~6-8 weeks)

**Goal:** the DM can run the pilot for ~100 soldiers using the system end-to-end *by hand*. No algorithm yet.

**Includes:** repo scaffolding, auth, full v1 schema, soldier directory + hierarchy CRUD, duty types + locations, exemption-types + mapping, exemption grants, personal constraints + approval flow + cap enforcement, manual duty creation + per-day overrides, cumulative + normalised score computation, manual score adjustments, all v1 pages, full audit log, docker-compose deployment, encrypted nightly backups, healthcheck, operator runbook.

**Explicitly out:** algorithm, structured reserve assignments, replacement marketplace, punishment duties, "why did I get this" with real explanation (v1 shows the manager's note).

**Definition of done:** a DM can onboard 100 soldiers, configure the hierarchy and duty types, grant a handful of exemptions, approve constraints, assign all next-month duties by hand, and the שקיפות page shows correct normalised scores. Audit log covers every state change. Backup + restore drill passes.

### 9.2 v1.5 — The algorithm (target: ~4-6 weeks after v1 in production)

**Goal:** automate assignment, with real v1 data to validate against.

**Includes:** `algorithm/` package with the CP-SAT formulation, solver-wiring endpoint, חלון תכנון sub-page, infeasibility relaxation chain with clear UI messaging, `assignment_explanations` storage, "?למה קיבלתי" modal rendering filtered explanations, hierarchy-distance reserve-soldier selection, solver seed exposed in explanations, **two weeks of shadow mode** (algorithm proposes alongside manual assignment so the DM can compare) before flipping to algorithm-published-but-DM-reviewed.

**Definition of done:** solver completes the pilot's monthly batch in < 30 s in practice; against 10 historical manually-assigned months, the algorithm matches or improves variance and min-gap; soldiers see coherent explanations; shadow mode then DM-approved mode both run cleanly.

### 9.3 v2 — Social layer and no-shows (after v1.5 settles)

**Goal:** soldiers help each other; the system handles no-shows fairly.

**Includes:** `replacement_listings` + `replacement_offers` + the חיפוש מחליפים page, match-quality computation (constraints, density, hierarchy distance), online/emergency assignment mode (greedy), `punishment_duties` mechanic (no-score punitive duty triggered by no-show + הקפצה, manager-confirmed), structured "compensation" workflow on top of `score_adjustments`.

### 9.4 Later (out of scope for this spec)

- Notifications (SMS / email / push) for constraint decisions, assigned duties, replacement offers, הקפצה risk.
- Mobile-app wrapper.
- Multi-branch deployment with multiple DMs each scoped.
- Longitudinal fairness dashboard.
- Localisation to other languages.

### 9.5 Cross-version invariants

- Data model is additive only; no destructive migrations against `audit_log`.
- v1 endpoints stay backwards-compatible; OpenAPI contract checked in CI.
- Hebrew strings live in one translation file per side; later versions only add keys.

---

## 10. Testing, ops, and repo conventions

### 10.1 Repository layout

```
justice/
├── README.md
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── .github/workflows/
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py
│   │   ├── routes/
│   │   ├── services/
│   │   ├── algorithm/        # pure module — no DB, no HTTP
│   │   │   ├── batch.py
│   │   │   ├── online.py
│   │   │   ├── explain.py
│   │   │   └── tests/
│   │   ├── db/models.py
│   │   ├── auth/
│   │   ├── audit/
│   │   ├── settings.py
│   │   └── i18n/he.json      # server-side error messages
│   └── tests/{unit,integration,fixtures}
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/{api,pages,components,hooks,i18n,lib}
│   └── tests/
│
├── docs/
│   ├── superpowers/specs/    # this file
│   ├── runbook.md
│   ├── architecture.md
│   └── algorithm.md
│
└── ops/{seeds,backup.sh,restore.sh}
```

### 10.2 Testing

**Backend:**

- Unit tests for `algorithm/` — property-based (`hypothesis`): random feasible populations, assert hard constraints satisfied, more solver time never reduces `min_gap`, determinism for same seed. Explanation builder tested separately against synthetic solver outputs.
- Unit tests for `services/` — pure functions over fakes.
- Integration tests — real Postgres via `testcontainers-python`, real FastAPI, real auth.
- Audit-completeness fixture wraps every endpoint test and asserts `audit_log` grew.

**Frontend:**

- Vitest + Testing Library on forms, the calendar grid (RTL math), table sorting.
- Playwright e2e for: login → submit constraint → DM approves → soldier sees status; DM creates duty → soldier sees it; DM runs algorithm (v1.5+) → reviews → publishes.

**Algorithm golden suite:** committed synthetic populations with expected metrics; CI fails on regression.

**Coverage target:** none — quality measured by golden-population results and absence of regressions.

### 10.3 CI

Per PR: `ruff` + `mypy` (backend), `eslint` + `tsc --noEmit` (frontend), backend unit + integration, algorithm golden suite, frontend unit + Playwright e2e, `alembic check`, `openapi.json` diff posted for human review.

Pre-commit: `ruff format`, `prettier`, `mypy` fast mode, commit-message lint.

### 10.4 Operations

**POC deployment:** single VM (4 vCPU, 8 GB RAM); Caddy + auto-TLS; three containers (`app`, `db`, `caddy`); Postgres volume on host; nightly `pg_dump | gpg --encrypt | rclone` to off-VM storage; monthly restore drill.

**Self-hosted:** same compose file; Caddy swappable for internal TLS process; notification settings (v2) routed via a single configurable abstraction.

**Bootstrap:** `docker-compose up -d` → `backend/scripts/bootstrap.py` creates the first admin from env vars then disables itself → admin logs in and configures hierarchy + first DM.

**Observability:** structured JSON logs to stdout; one Prometheus `/metrics` endpoint exposing request count, request latency, algorithm run duration, login failure count.

**Backups:** daily encrypted full dump; weekly *separate* audit-log-only dump for extra tamper-evidence.

### 10.5 Conventions for future editors (human or AI)

- Type-checked end-to-end (Pydantic + TypeScript + generated OpenAPI client).
- Bounded contexts with explicit boundaries; cross-context calls only via `services/__init__.py`.
- Hebrew strings in one file per side.
- The algorithm module is a swappable library — alternative formulations live as sibling modules gated behind a `system_settings` key.
- Every migration reversible; enforced by `alembic check`.
- No hard-coded magic numbers in domain code — either a `system_settings` key or a `# why this exact value:` comment.
- Audit log is sacred; changes touching it require two reviewers.
- Files crossing ~400 lines are a smell — split by responsibility.

---

## 11. Open questions parked for plan stage

These were intentionally deferred during brainstorming and should be resolved during the implementation plan:

- Exact unit-of-measure for `K` (raw score points vs normalised-score difference units) — pinned to "normalised units" here but the magnitude `8` needs calibration once real data exists.
- Concrete defaults for `α` (`min_gap` weight) and `β` (density penalty weight) — starting values `1.0` / `2.0` are placeholders to be tuned.
- Whether to ship a single seeded admin password or generate a one-time token via console on first boot (recommendation: console token, no shared default).
- Decision on per-action retention rules for `audit_log.context.request_id` once real request volume is measured.

---

*End of design.*
