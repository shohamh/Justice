# Database Transaction and Concurrency Audit — Report

Date: 2026-10-02
Spec: `docs/superpowers/specs/2026-10-02-database-concurrency-audit-design.md`
Plan: `docs/superpowers/plans/2026-10-02-database-concurrency-audit.md`
Status: **Task 1 (baseline + inventory) complete.** Tasks 2–5 have not started.
No finding in this report has been reproduced yet. Every risk below is a
**candidate** from reading the code. Task 2 has to reproduce a candidate before
it counts as a confirmed finding.

> Reading rule for this document: "no defect identified" means only that
> reading the code did not show one. It is **not** a safety claim. The audit
> does not prove that any workflow is free of races.

---

## 1. Baseline

| Item | Value |
|---|---|
| Worktree branch | `feature/database-transaction-concurrency-audit` |
| Starting revision (HEAD) | `c9df8152` "docs: add database concurrency audit spec and plan" |
| Branch base (`dev` when the branch was cut) | `08196982` "merge: s3 object storage" |
| `dev` at audit time | `7aecc7c4`. It differs from `08196982` only in `.gitlab-ci.yml` and `docs/gitlab-ci.md`. No backend code changed. |
| Alembic head (fresh migrated DB) | `4858092e72e7` |
| Python env | new `backend/.venv` (Python 3.12), `pip install -e ".[dev]"` |
| DB for tests | Testcontainers `postgres:16-alpine` (see `backend/tests/support/database.py`) |
| Isolation level | No app-level override in `app/db/session.py`, so the PostgreSQL default READ COMMITTED applies. The production server config was not checked. |

### Baseline fast-suite result

Command: `pytest -q -p no:cacheprovider` from `backend/` (addopts adds `-q -n 4`).

- About **2130 passed**, **3 skipped**, **2 failed**. Counts come from the
  progress output, because the doubled `-q` hides the summary line.
- Failures (both also fail when run alone and serially with `-n 0`):
  1. `tests/unit/test_algorithm_bridge_shifts.py::test_block_ids_are_unique`.
     The test hard-codes a shift on `date(2026, 10, 1)`. That date is now in
     the past (today is 2026-10-02), so the loader drops it and returns 0
     blocks. The cause is the calendar, not concurrency (checked by reading the
     test).
  2. `tests/test_effort_score.py::test_breakdown_contributions_reconstruct_scores`.
     It expects `{'duty','adjustment'}` and gets `{'duty'}`. This is probably
     also date or quarter related (the Q4 boundary is 2026-10-01). **The root
     cause was not investigated.**
- Skips: 3 in `tests/integration/test_algorithm_routes.py` ("solver returned no proposals").

Tasks 2–5 must compare their runs against these two baseline failures.

### Schema evidence

Constraints were taken from a freshly migrated database
(`pg_constraint` contypes u/x/c plus `pg_indexes` UNIQUE), not from
`models.py`. Facts used in this report:

- `duty_day_overrides`: **has** `uq_duty_day_overrides_assignment_date UNIQUE (duty_assignment_id, date)`.
  The `swaps._lock_request` docstring says this constraint does not exist.
  That docstring is stale. `models.py` also does not declare the constraint
  (model/migration drift).
- `soldier_field_updates`: has a partial unique index
  `uq_soldier_field_updates_one_active (soldier_id, field_name) WHERE status IN (pending…)`.
  `models.py` does not declare it.
- `swap_requests`: has a partial unique index
  `uq_swap_requests_one_open_per_requester_duty (requesting_soldier_id, duty_assignment_id) WHERE status='open'`.
- `range_excusal_requests`: one pending per assignment (partial unique).
  `range_assignments`: `UNIQUE (range_event_id, soldier_id)`.
- `duty_no_shows`: `UNIQUE (duty_assignment_id)`. `duty_reserve_links`: `UNIQUE (primary_assignment_id)`.
- **The schema has no exclusion constraints** (no `contype='x'`). Nothing in
  the database prevents overlapping `duty_assignments` for one soldier.
- None of these tables has a uniqueness or status guard:
  - `personal_constraints` (cap)
  - `hierarchy_transfer_requests` (one pending per soldier)
  - `exemption_requests` / `soldier_exemptions` (1:1 link)
  - `soldier_enrollment_requests`
  - `import_sessions` (status)
  - `email_outbox` / `telegram_outbox` (claim)
  - `range_events.reminder_sent_at`
  - `duty_dismissals` (overlap)
  - `soldiers.email` among verified accounts
- No app code catches `DeadlockDetected`, `SerializationFailure`, or
  `OperationalError`. `IntegrityError` is translated in only two places:
  `swaps.create_request` and `hr_sync_worker`. Anywhere else, these errors
  surface as HTTP 500 through the global handler.

### Deployment facts that affect concurrency

- `deploy/docker-compose.prod.yml` runs `uvicorn --workers ${WEB_CONCURRENCY:-4}`.
  `app/main.py` lifespan starts **every background worker in every process**:
  email, swap/exemption expiry, range reminders, range attendance, duty
  eligibility, rank advancement, HR sync, qualification expiry, and score
  projection.
  - With the default setting, each periodic job runs in 4 processes at once.
  - Only `hr_sync_worker` (`pg_try_advisory_lock`) and
    `score_projection_revalidation_worker` (`pg_try_advisory_xact_lock`)
    coordinate between processes.
- The `_fail_orphaned_algorithm_jobs()` startup hook runs in every worker
  process. It fails every job with `status='running'`, including jobs being
  solved by sibling processes that are still alive.
- The Telegram bot is one separate process (`python -m bot.main`).

---

## 2. Inventory of transaction-sensitive operations

### Legend

- **Txn owner**: the code that calls `session.commit()`. "route" means the
  FastAPI handler commits after the service returns. "svc" means the service
  commits itself. "worker" means a `session_scope()` in a background job.
- **Outbox (in-txn)**: `create_notification` inserts `notifications` plus
  `telegram_outbox`/`email_outbox` rows in the caller's transaction. Delivery
  happens later in the email worker and the bot. These rows are atomic with
  the business change, but delivery is at-least-once (see N1/N2).
- Risk values: C = critical, H = high, M = medium, L = low.
  - These follow the spec's severity definitions.
  - The ratings are **initial and unreproduced**.

### Assignments (`services/assignments.py`, `routes/assignments.py`, `routes/shifts.py`)

| ID | Operation / caller | Txn owner | Checked invariant | DB constraint / lock | External effects | Existing test | Initial risk |
|---|---|---|---|---|---|---|---|
| A1 | `create_assignment`. Caller: `POST /assignments`, `POST /shifts/{id}/assign-batch`. | route | No overlap, enough rest, no blocking exemption, constraint override reason present | `SELECT soldiers … FOR UPDATE` on the target soldier, taken first in the service. No exclusion constraint. The route loads the soldier and authorizes **before** the lock, and the lock does not refresh the identity-mapped `Soldier` (no `populate_existing`). | outbox (in-txn), audit, projection refresh | Sequential tests only. No PostgreSQL race test for the soldier lock. | M. The lock only serializes writers that also take it (see A3, S6, J2). |
| A2 | `assign-batch` capacity check (route). Caller: `POST /shifts/{id}/assign-batch`. | route | Count of primaries/reserves ≤ `required_count` / reserve slots | **No lock on the `duty_shifts` row**. Counts are read without locks. | as A1 | none for concurrency | **H**. Two batches can both pass the count. |
| A3 | `assign-batch` soldier lock order | route | n/a | Takes `FOR UPDATE` on soldiers in **request-body order**. Two overlapping batches in different orders can deadlock. | — | none | M. A deadlock gives a 500 for one request (no retry). |
| A4 | `replace_assignment`. Only caller: `POST /shifts/{id}/assignments/{aid}/replace`. | route | Replacement soldier has no overlap/rest/exemption conflict | Locks the **replacement** soldier only. The assignment row itself is not locked, so two concurrent replaces of the same assignment are not serialized (last writer wins). | outbox, projection | none | M |
| A5 | `cancel_assignment`. Caller: `POST /assignments/{id}/cancel`. | route | none (no status check) | none | outbox (in-txn). A second call sends a duplicate "cancelled" notification, even when run sequentially. | sequential | L |
| A6 | `set_day_override` / `clear_day_override`. Callers: `PUT/DELETE /assignments/{id}/overrides/{day}`, swaps `_apply_cover`. | route / caller | Effective soldier not busy (`_day_busy` checks only nominal `duty_assignments.soldier_id`, not overrides), no exemption; select-then-insert on (assignment, date). | `uq_duty_day_overrides_assignment_date`. No lock on the assignment or the effective soldier. | outbox, projection | none | M. A concurrent insert for the same day fails as an unhandled IntegrityError (500). Concurrent updates of an existing row are last-writer-wins. |
| A7 | `clear_all_assignments` (bulk UPDATE). Caller: `DELETE /assignments`. | route | — | single UPDATE statement | none (no notifications) | sequential | L |

### Swaps (`services/swaps.py`)

| ID | Operation / caller | Txn owner | Checked invariant | DB constraint / lock | External effects | Existing test | Initial risk |
|---|---|---|---|---|---|---|---|
| S1 | `create_request` | route | One open request per (requester, duty), requester owns the duty | Partial unique `uq_swap_requests_one_open_per_requester_duty`. IntegrityError is translated to `already_pending`. | outbox | `test_swaps_service.py` (IntegrityError translation, sequential) | L |
| S2 | `add_targets`, `publish_to_marketplace`, `decline_candidate`, `approve_soldier_side`, `approve_manager_row`, `reject_manager_row`, `approve_manager_side_override`, `claim_request`, `reject_request`, `cancel_request`, `cover_offer` | route | Request is `open`; candidate state transitions; only one winner in `_try_finalize` | `SwapRequest FOR UPDATE` with `populate_existing`, taken first in each entry point | outbox, audit | `test_concurrent_finalize_of_two_candidates_applies_only_one` | Reviewed; no defect identified for **same-request** races (see S5 for cross-request races). |
| S3 | `take_free` | route | No open request for the assignment (any requester) | Not locked. The partial unique index applies only to (requester, duty), and the IntegrityError is **not** translated here. | outbox | sequential | L. Concurrent `take_free` / `create_request` gives a 500 for the loser. |
| S4 | `expire_started_swaps` (worker, 5 min, ×4 processes) | worker | Request still `open` | **No lock.** It reads open rows, then does an unconditional `UPDATE … SET status='cancelled' WHERE id=…`. | outbox | sequential | **H**. It can overwrite a concurrent `applied` finalize with `cancelled` after the cover overrides were written. Parallel workers also double-notify. |
| S5 | `_apply_cover` covering-soldier availability across **different** requests | route | Covering soldier not busy that day | Only the per-request lock is held. The covering soldier is not locked. `_day_busy` ignores overrides. | outbox | none | M/H. Possible double booking via two swaps on the same day. Part of this is a sequential business-rule gap, so a product decision may be needed. |

### Personal constraints (`services/constraints.py`, `routes/constraints.py`)

| ID | Operation / caller | Txn owner | Checked invariant | DB constraint / lock | External effects | Existing test | Initial risk |
|---|---|---|---|---|---|---|---|
| K1 | `submit_constraint`. Caller: `POST /me/constraints`. | route | `used + requested ≤ cap_days` for the reset period | **None** (no lock on the soldier, no constraint) | outbox | sequential | **H**. Concurrent submissions can exceed the cap. |
| K2 | `approve_constraint`, `reject_constraint`, `cancel_constraint`. Callers: routes plus the `/notifications/action` token dispatch. | route | Status is pending; DM step requires a DM/admin role | `PersonalConstraint FOR UPDATE` + `populate_existing` | outbox, projection | sequential | Reviewed; the lock covers same-row decisions. The route chooses the authorization branch from the **pre-lock** status. The in-service role check limits the impact (M/L permission-staleness note). |
| K3 | `create_assignment` vs a concurrent constraint approval | route | Override reason required if an approved constraint overlaps | The constraint is read without a lock. `create_assignment` locks the soldier, constraint approval locks the constraint, so the two never serialize. | — | none | M (stale decision) |

Incidental defect, not a concurrency issue: `cancel_constraint` (approved →
cancelled path) calls `datetime.now(timezone.utc)`, but `timezone` is not
imported. A static check (`'timezone' in vars(app.services.constraints)` →
`False`) confirms the name is undefined. No test exercises that path
successfully.

### Exemptions (`services/exemption_requests.py`, `services/exemptions.py`)

| ID | Operation / caller | Txn owner | Checked invariant | DB constraint / lock | External effects | Existing test | Initial risk |
|---|---|---|---|---|---|---|---|
| E1 | `approve_commander_step`, `approve_duty_manager_step`, `reject_request` | route | Status transition; one `SoldierExemption` per approved request | `ExemptionRequest FOR UPDATE` + `populate_existing`. No unique link to `soldier_exemptions`. | outbox, projection, `try_activate` (enrollment) | sequential | Reviewed; no defect identified for same-request decisions. |
| E2 | `expire_stale_exemption_requests` (worker, ×4) | worker | Still pending | **No lock.** Unconditional overwrite to `expired`. | outbox | sequential | **H/M**. It can overwrite a concurrent `approved` after the `SoldierExemption` row was created. |
| E3 | Token dispatch `exemption:approve` | route | Picks the commander or DM step from the **pre-lock** `req.status` | Lock taken inside the step function | outbox | none | L. A double redemption maps to a 500/400 error, not a duplicate exemption. |

### Hierarchy transfers (`services/hierarchy_transfers.py`)

| ID | Operation / caller | Txn owner | Checked invariant | DB constraint / lock | External effects | Existing test | Initial risk |
|---|---|---|---|---|---|---|---|
| H1 | `create_request` (or update of an existing pending request) | route | At most one pending request per soldier; daily limit | `Soldier FOR UPDATE`. No partial unique index. | outbox | sequential | L |
| H2 | `approve_request` / `reject_request` | route | Status is `pending`; authorized for the destination node read before the service | **No lock** on the request. The soldier is updated without a lock. The route authorizes against `req.to_node_id` read without a lock. | outbox, projection | sequential | **H**. Approve vs reject can both succeed. Approve racing with `create_request`'s in-place update can move the soldier to the old destination while the row records the new one. |

### Soldiers (`services/soldiers.py`)

| ID | Operation / caller | Txn owner | Checked invariant | DB constraint / lock | External effects | Existing test | Initial risk |
|---|---|---|---|---|---|---|---|
| P1 | `submit_field_update` | route | One active update per (soldier, field); supersedes older ones | `Soldier FOR UPDATE`, then UPDATE of older pending update rows. Partial unique `uq_soldier_field_updates_one_active`. | outbox | `test_concurrent_unit_join_date_submissions_leave_one_pending_request` | Reviewed (submit vs submit) |
| P2 | `approve_field_update` | route | Status equals what the caller observed | `SoldierFieldUpdate FOR UPDATE` + `populate_existing`, then UPDATE soldier at flush | outbox | `test_concurrent_unit_join_date_approvals_transition_once_and_notify_once` | Reviewed (approve vs approve) |
| P3 | `reject_field_update` | route | Status is pending | **No lock**. Unconditional overwrite. | none | none | **H**. Approve-then-reject can leave the soldier field changed while the row says `rejected`. |
| P4 | P1 vs P2 lock order | route | — | P1: soldier → update row. P2: update row → soldier. **Opposite order.** | — | none | M. Deadlock candidate. |
| P5 | `update_soldier`, `update_soldier_profile`, `reset_password`, `promote_to_admin`, `soft_delete` | route | none beyond field validation | No lock, no version column | audit | sequential | M. Lost update on concurrent profile PATCHes (and vs HR sync); `bump_token_version` read-modify-write. |
| P6 | `onboard_soldier`, `registration.register` | route | personal_number unique | `soldiers_personal_number_key` | — | sequential | L. The duplicate surfaces as IntegrityError (500), not the domain error. |

### Imports (`services/import_sessions.py`, `services/import_approvals.py`)

| ID | Operation / caller | Txn owner | Checked invariant | DB constraint / lock | External effects | Existing test | Initial risk |
|---|---|---|---|---|---|---|---|
| I1 | `confirm_session`. Caller: `POST /import/sessions/{id}/confirm`. | route | Session status is `draft` | **No lock, no conditional UPDATE.** It reads the workbook from object storage inside the transaction. Per-row savepoints exist for most groups but **not** for soldiers. | Creates soldiers/shifts/assignments/ranges/swaps etc. | sequential | **H**. A double submit, or confirm racing with cancel, can apply the import twice or leave status inconsistent. |
| I2 | `cancel_session`, `mark_done`, `set_selections`, `reparse_session` | route | Status checks (`set_selections` has none) | none | — | sequential | M |
| I3 | Import-applied overwrites of live rows (`swap.status = row["status"]`, constraint/exemption/field-update statuses) | route | — | none | — | sequential | M. Lost updates if an import runs while users act on the same rows. |

`import_approvals.py` was not read line by line in this task. It stays an
**untested and unreviewed boundary** for Task 5.

### Ranges (`services/ranges.py`, `range_reconciliation.py`, `range_assignment_requests.py`, `range_excusal.py`)

| ID | Operation / caller | Txn owner | Checked invariant | DB constraint / lock | External effects | Existing test | Initial risk |
|---|---|---|---|---|---|---|---|
| R1 | `add_range_assignment`, `assign_batch` | svc (commits itself) | Capacity, one assignment per soldier per date, event `planned` | `pg_advisory_xact_lock(ns, event_date)` + `uq_range_assignment_event_soldier` | outbox | sequential | Reviewed for same-date add vs add. |
| R2 | `reconcile_future_range_assignments` (called inside R1/R5) | caller | Refill capacity on later events | Per-date advisory locks. The comment claims ascending order. In `assign_batch` the per-soldier loop can take **non-ascending** dates. | outbox | none | M. Deadlock candidate. |
| R3 | `approve_assignment_request` | svc | Capacity, same-date conflict, request pending | **No advisory lock, no request lock** | outbox | sequential | **H**. Bypasses R1 serialization and can exceed capacity. Double approval gives an IntegrityError (500). |
| R4 | `create_assignment_request` | svc | One pending per (event, soldier) | none | outbox | sequential | L |
| R5 | `decide_primary_excusal` | svc | Request pending; promote one eligible reserve | **No lock** on the request or the reserve; partial unique only on pending | outbox | sequential | **H/M**. Two concurrent approvals can promote the same reserve, leaving one slot silently unfilled. Approve vs reject is a lost update. |
| R6 | `mark_past_range_events_completed` (worker, ×4) | worker | Transition each elapsed event once | conditional transition (per its test) | audit | `test_concurrent_elapsed_transitions_change_and_audit_each_event_once` | Reviewed |
| R7 | `send_due_range_reminders` (worker, ×4) | svc | `reminder_sent_at IS NULL` | **No lock**, flag set after notifications are created | outbox (Telegram + email) | sequential | **H**. Duplicate reminders across processes. |
| R8 | `auto_mark_present_for_elapsed_events` (worker, ×4) → `mark_attendance` | worker | Attendance still `pending` | no lock seen in the caller; `mark_attendance` not reviewed in depth | qualification rows, outbox | none | M |

### Reserves / no-show / misc duty

| ID | Operation | Checked invariant | DB constraint / lock | Initial risk |
|---|---|---|---|---|
| D1 | `reserves.dismiss_primary` / `dismiss_reserve` | No overlapping dismissal for the assignment | none (check-then-insert) | M |
| D2 | `reserves.relink_reserve` / `reallocate_orphaned_primaries`, shift batch reserve links | One link per primary | `uq_reserve_links_primary` | L. The duplicate gives a 500. |
| D3 | `no_show.mark_no_show` | One no-show per assignment | `uq_duty_no_shows_assignment` | L. The duplicate gives a 500; the adjustment rolls back in the same transaction. |
| D4 | `reserves.call_up_reserve` | — | none | L (last-writer-wins on the call-up range) |

### One-time tokens and codes

| ID | Operation / caller | Checked invariant | DB constraint / lock | Existing test | Initial risk |
|---|---|---|---|---|---|
| T1 | `action_tokens.redeem_token` (bot) / `redeem_token_from_link` (`POST /notifications/action`) | Token unused and unexpired | **SELECT, then ORM UPDATE by PK.** The second redeemer still succeeds after the first commits. | none | M. Double dispatch. Downstream row locks mostly turn the second run into an error, but this was not verified for every action. |
| T2 | `password_reset.redeem_reset_token` | Token unused | same pattern as T1 | none | M. Two concurrent resets both report `ok`; `token_version` read-modify-write. |
| T3 | `password_reset.create_and_send`, `email_verification.request_verification` | Invalidate old tokens, issue a new one | none; **SMTP `send_email` is called inline inside the request transaction** while updated token rows are locked | none | M (transaction held across the network); two concurrent requests can leave two live tokens. |
| T4 | `email_verification.verify_token` | No other soldier has this verified email | **No unique constraint** | none | M. Two accounts verified with the same email. |
| T5 | `invite_codes.consume_invite_code` | `uses_left > 0` | Conditional `UPDATE … WHERE uses_left > 0 RETURNING` | `test_concurrent_consume_never_over_redeems` | Reviewed |
| T6 | `hr_activation.consume_activation_code` | Unused and unexpired | Conditional `UPDATE … RETURNING` | sequential | Reviewed; no defect identified |
| T7 | `hr_activation.generate_activation_code` | Only one live code per soldier | none | none | L |

### Notifications, outbox, and jobs

| ID | Operation | Checked invariant | DB constraint / lock | External effect | Existing test | Initial risk |
|---|---|---|---|---|---|---|
| N1 | `email_worker._drain_email_outbox` (every 5 s, **×4 processes**) | Row `sent_at IS NULL` | **No claim (no FOR UPDATE SKIP LOCKED / conditional UPDATE)**. SMTP is sent inside the open transaction, then committed per row. Failed rows are retried forever with no backoff. | **SMTP email (irreversible)** | none | **C/H**. Concurrent processes can send the same email more than once. |
| N2 | `bot/outbox.poll_outbox` (single bot process) | `sent_at IS NULL` | no claim; at-least-once (a crash between send and commit means a resend) | Telegram message | none | M/L (only if the bot is scaled up) |
| N3 | `create_notification` + cascade | — | Inserted in the caller's transaction (transactional outbox) | outbox rows | many sequential | Reviewed: atomic with the business change |
| N4 | Expiry dedupe `_already_notified_for_expiry` (qualification worker, ×4) | Not already notified for this expiry date | none (check-then-insert) | outbox | sequential | M (duplicate notifications) |
| N5 | Rank advancement worker (×4) `_promote_due_soldiers` | due soldier not yet promoted | not reviewed in depth | outbox | sequential | M (possible double promotion or notification; unverified) |
| J1 | `run_algorithm_job` status transitions | `failed` (cancelled) must not be overwritten | Unconditional writes (`running` at start, `done` at end). Refreshes only before persistence; the cancel landing between that refresh and the final commit is overwritten. | outbox | `test_algorithm_cancel.py`, watcher thread tests | M |
| J2 | `persist_results` drafts vs manual assignments made during the solve; `accept_proposal` / `bulk_accept` do not re-check overlap | No soldier double booked | Snapshot read before the solve (minutes); no lock | outbox at accept time | none | M/H (stale decision) |
| J3 | `accept_proposal` vs `reject_proposal` on the same draft | Status `algorithm_draft` | Single-item routes: unlocked read then write. Bulk routes: conditional `UPDATE … WHERE status='algorithm_draft'`. | projection | sequential | M (single-item lost update) |
| J4 | `_fail_orphaned_algorithm_jobs` on each worker start | "running" rows are orphans | Assumes a single process | — | none | M. Marks live jobs in sibling processes as failed. |
| J5 | `score_projection_revalidation_worker`, `hr_sync_worker` | single runner | advisory try-locks | — | `test_hr_sync_worker.py` | Reviewed |
| J6 | `accept_proposal` / `bulk_accept_proposals` call `recheck_assignments(session, ids)` with the default `commit=True` (`duty_eligibility_watch.py:188`). This commits **in the middle of the route**, before `refresh_projection_for_assignment_change` / `refresh_projections_for_assignments_bulk` and `_maybe_publish_job`. | Publish + projection + job status are atomic | none; route transaction split into two commits whenever a recheck target exists | outbox | sequential | M. If a later step fails, partial state stays committed (assignment published, projection/job not updated). |

### Enrollment / storage / other

| ID | Operation | Checked invariant | DB constraint / lock | Initial risk |
|---|---|---|---|---|
| X1 | `enrollment.approve_enrollment` / `reject_enrollment` / `try_activate` | Status `pending` → decided | **No lock** | **H/M**. Approve vs reject lost update; the soldier is moved while the status says rejected. |
| X2 | `storage_uploads.persist_uploaded_object` | Object stored before metadata binds | Object-store PUT happens **after flushing the row insert** (row locks + FK KEY SHARE on parents held during the network call); cleanup goes through `storage_delete_outbox` | M (lock held across network; e.g. blocks `FOR UPDATE` on a parent `exemption_requests` row) |
| X3 | `deputies.create_deputy`, `dm_scope`, notification prefs | uniqueness | `uq_role_deputy`, `uq_dm_scope`, `uq_notification_preferences_soldier_type` | L (500 on duplicate) |

Not reviewed in this task, and named here so nothing is silently dropped:
- `import_approvals.py` in detail
- `calendar_shifts.py`
- `duty_config.py`
- `shift_templates.py` auto-roll
- `gimelim.py` / `hakpaza.py` (they do not call `replace_assignment` / `set_day_override`, per grep; their own writes were not reviewed)
- `bug_reports.py`
- `score_projection.py` internals (dirty-bucket upsert)
- `hr/person_sync.py` (beyond its advisory lock)
- `rank_advancement` worker internals

---

## 3. Lock-order review

Lock acquisition was inferred from the code. PostgreSQL locks taken implicitly
by inserting a child row (`FOR KEY SHARE` on referenced parents via RI
triggers) are noted where relevant, because `FOR UPDATE` conflicts with
`FOR KEY SHARE`. None of these orders has been exercised under concurrency
yet. Each entry says whether a cycle was identified.

| Workflow | Order of row/advisory locks (as written) | Cycle identified? |
|---|---|---|
| Assignment create (A1) | `soldiers[S] FOR UPDATE`, then INSERT `duty_assignments` (KEY SHARE on soldier/type/location/shift), then INSERT notifications/audit (KEY SHARE on recipients/actor) | None found on its own. Any concurrent child insert that references `soldiers[S]` (exemption grant, notification for S, field update) waits on S's `FOR UPDATE`, and the reverse is also true. This serializes more than the code comment implies (unverified). |
| Shift assign-batch (A2/A3) | `soldiers[s1] … soldiers[sn]` in **request order** | **Yes, potential.** Two batches with overlapping soldiers in different orders. Candidate C10. |
| Replace assignment (A4) | `soldiers[replacement] FOR UPDATE`, then UPDATE `duty_assignments[A]` at flush | None found; the assignment row is not locked first. |
| Swaps (S2) | `swap_requests[R] FOR UPDATE`, then child inserts, then `_apply_cover` → INSERT/UPDATE `duty_day_overrides[A,d]` | None found within a request. Across workflows, the override row (A,d) is shared with the `PUT overrides` route, which takes no other locks, so no cycle — conflicts surface as unique violation / last-writer-wins. |
| Constraints (K2) | `personal_constraints[C] FOR UPDATE` only | None found |
| Exemption decisions (E1) | `exemption_requests[E] FOR UPDATE`, then INSERT `soldier_exemptions` (KEY SHARE soldiers[S]), then `try_activate` UPDATE `soldier_enrollment_requests`, UPDATE `soldiers[S]` | Not identified; `try_activate` takes a soldier row lock while E is held. A workflow that locks `soldiers[S]` and then `exemption_requests[E]` was not found. |
| Hierarchy transfer | create: `soldiers[S] FOR UPDATE` → UPDATE/INSERT request. approve: no explicit locks; UPDATE soldiers[S] and UPDATE request in one flush. SQLAlchemy unit-of-work dependency ordering is expected to flush the parent (`soldiers`) first. | None identified **if** the flush order is soldier → request. **Not verified.** |
| Soldier field updates (P4) | submit: `soldiers[S] FOR UPDATE` → UPDATE `soldier_field_updates[U]`. approve: `soldier_field_updates[U] FOR UPDATE` → UPDATE `soldiers[S]` | **Yes, opposite order.** Candidate C9. |
| Ranges (R1/R2) | `advisory(event_date)`, then reconciliation `advisory(later dates)` ascending **per soldier**; `assign_batch` loops soldiers | **Yes, potential**, in `assign_batch` with ≥2 soldiers whose reconciliation targets are not globally ascending. Candidate C11. |
| Range request approval / excusal (R3/R5) | no advisory lock / no row lock | No cycle (they take no locks), but they bypass R1 serialization. |
| Imports (I1) | no explicit locks; row locks are taken implicitly by UPDATEs in file order across soldiers, shifts, assignments, swaps … | No cycle identified, but imports and live workflows are not serialized at all. |
| Notification/job transitions (N1, S4, E2, R7, J1) | no row locks; unconditional UPDATE by PK | No deadlock risk identified; lost-update and duplicate risks instead (C1, C2, C7, C13). |

---

## 4. Candidate races for Task 2 (ranked)

Ranking uses initial severity × likelihood under the default production setup
(4 uvicorn processes, normal request concurrency). Every item is a hypothesis.
Task 2 must reproduce it with independent PostgreSQL sessions and explicit
barriers, or drop it from the confirmed list.

| Rank | ID | Candidate | Inventory refs | Initial severity | Reproduction sketch (two sessions + barrier) |
|---|---|---|---|---|---|
| 1 | C1 | Email outbox delivered more than once by concurrent drainers | N1 | Critical (duplicate irreversible effect) | Seed 1 `email_outbox` row. Run two `_drain_email_outbox` calls with a stubbed `send_email` that hits a barrier. Assert the send count == 1. |
| 2 | C2 | Range reminders sent once per process | R7 | High | Seed an event at the threshold date with assignments. Two sessions call `send_due_range_reminders` with a barrier after the event SELECT. Count notifications/outbox rows. |
| 3 | C3 | Shift assign-batch capacity overrun | A2 | High | Shift with `required_count=1`. Two batches with different soldiers, barrier after the count query. Assert ≤ 1 primary. |
| 4 | C4 | Range assignment request approval bypasses the per-date lock (capacity overrun) | R3 | High | Event with capacity 1. `approve_assignment_request` vs `add_range_assignment` for different soldiers, barrier after `_check_capacity`. |
| 5 | C5 | Personal-constraint cap bypass | K1 | High | `cap_days` small. Two `submit_constraint` calls whose total exceeds the cap, barrier after `remaining_days`. |
| 6 | C6 | Import confirmed twice / confirm vs cancel | I1 | High | Draft session with shift rows only. Two `confirm_session` calls, barrier after the status check. Count created shifts. |
| 7 | C7 | Expiry workers overwrite a concurrent decision (`applied` → `cancelled`; `approved` → `expired`) | S4, E2 | High | Worker session reads open rows, barrier; a decision session finalizes and commits; the worker writes. Assert the final status and the overrides/exemption state agree. |
| 8 | C8 | Unlocked approve/reject decisions lose updates | H2, P3, X1, R5, J3 | High (state contradicts applied effect) | Per workflow: approve vs reject with a barrier after each status read. Assert exactly one outcome and a consistent side effect (soldier node, field value, promoted reserve). |
| 9 | C9 | Deadlock: `submit_field_update` vs `approve_field_update` | P4 | Medium | Pending update U. Session A approves (locks U), barrier; session B submits for the same field (locks S, waits on U); A flushes the soldier. Expect deadlock → 500. |
| 10 | C10 | Deadlock: shift assign-batch soldier ordering | A3 | Medium | Two batches [S1,S2] and [S2,S1], barrier after the first lock. |
| 11 | C11 | Deadlock: range `assign_batch` reconciliation lock order | R2 | Medium | Construct future events so reconciliation for soldier A targets D5 and for soldier B targets D3, plus a concurrent add on D3 that reconciles into D5. |
| 12 | C12 | Action token / reset token redeemed twice | T1, T2 | Medium | Two `redeem_token_from_link` calls with a barrier after the SELECT. Assert only one returns a row. |
| 13 | C13 | Algorithm job: final `done` overwrites a user cancel; startup hook fails live sibling jobs | J1, J4 | Medium | Stub the solver; cancel commits between `session.refresh(job)` and the final commit. Separately, call `_fail_orphaned_algorithm_jobs` while a job is `running`. |
| 14 | C14 | Swap cross-request double booking of the covering soldier | S5, A6 | Medium/High (needs a product decision on overrides vs `_day_busy`) | Two requests on different duties the same day, the same candidate, concurrent finalization. |
| 15 | C15 | Duplicate verified email | T4 | Medium | Two soldiers with the same email, concurrent `verify_token`. |
| 16 | C16 | Overlapping dismissals; stale constraint check in `create_assignment`; duplicate expiry notifications; attendance auto-mark duplicates | D1, K3, N4, R8 | Medium/Low | Standard two-session check-then-insert schedules. |
| 17 | C18 | Proposal accept commits mid-route (partial commit) | J6 | Medium | Failure injection: make the projection refresh raise after `recheck_assignments`. Assert the assignment status rolled back (expected to fail today). |
| 18 | C17 | Error mapping only (IntegrityError → 500): concurrent `set_day_override` insert, `take_free`, `mark_no_show`, reserve links, range request double approval | A6, S3, D3, D2, R3 | Low | Assert a stable 409 instead of a 500 if fixing is accepted. |

### Items that are not concurrency defects but were found during the inventory

- `constraints.cancel_constraint`: undefined `timezone` on the approved →
  cancelled path. Statically confirmed; no successful-path test exists.
- `swaps._lock_request` docstring says `duty_day_overrides` has no
  `(duty_assignment_id, date)` unique constraint. The migrated schema has
  `uq_duty_day_overrides_assignment_date`.
- `models.py` is missing `uq_duty_day_overrides_assignment_date` and
  `uq_soldier_field_updates_one_active` (model/migration drift).
- `confirm_session` soldier rows have no savepoint. A single row-level DB
  error inside the try/except leaves the session needing rollback, which
  poisons the rest of the import.
- `_day_busy` (used by `set_day_override`) ignores existing overrides when it
  decides whether the effective soldier is free (sequential rule gap).

---

## 5. Remaining untested concurrency boundaries (so far)

- All candidates in §4 are unreproduced.
- Modules listed under "Not reviewed in this task" in §2.
- No PostgreSQL race test exists for the `create_assignment` soldier lock (A1),
  even though the code comment relies on it.
- The production `default_transaction_isolation` was not checked.
- Behavior with `WEB_CONCURRENCY` other than 4, and the bot when scaled
  beyond one process.
