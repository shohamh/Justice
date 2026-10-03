# Database Transaction and Concurrency Audit — Report

Date: 2026-10-02
Spec: `docs/superpowers/specs/2026-10-02-database-concurrency-audit-design.md`
Plan: `docs/superpowers/plans/2026-10-02-database-concurrency-audit.md`
Status: **Tasks 1–4 complete.** Task 1 (baseline + inventory), Task 2 (race
reproduction for C1–C8), Task 3 (fixes for C1–C8) and Task 4 (C9–C18 and O1)
are done. Task 5 has not started.
All eight Critical/High candidates C1–C8 (including every C8 sub-workflow)
were reproduced against PostgreSQL and are **confirmed findings** (§4.1). All
of them are now **fixed** with database-level locking/claims and their race
tests pass for real (§4.2). No fix needed a product decision or a migration.
Task 4 (§4.3) reproduced C9–C13, C15, C16 (D1, N4, R8), C17, C18 and O1 and
fixed each one; C14 is deferred for a product decision, and C16/K3 and the
original J1 schedule were not reproduced. Still no migration (head
`4858092e72e7`).

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

### 4.1 Task 2 — confirmed findings (C1–C8)

Scope ruling for Task 2: reproduce C1–C8 only. C9–C18 (including C14) belong
to Task 4.

**Method.** Each test is in `backend/tests/integration/test_concurrency_<workflow>.py`
and runs on the Testcontainers PostgreSQL 16 fixture at the default READ
COMMITTED isolation.
- Every simulated request or worker process gets its own SQLAlchemy session
  on its own connection, in its own thread.
- The schedule is forced with explicit rendezvous points. No sleeps, no SQLite.
  The helpers are `race` / `RaceKit` in `backend/tests/conftest.py`:
  - `rendezvous` is a tolerant `threading.Barrier`;
  - `signal` is a bounded `threading.Event`;
  - `pause_after_select` parks a session right after its first ORM SELECT on
    an entity returns rows;
  - `stale_write` runs the lost-update schedule: read, then the other side
    decides and commits, then write.
- Waits are bounded (10 s). A fixed implementation that serializes the racers
  will time one wait out and carry on; it will not hang. On today's code every
  rendezvous is met at once.
- Each confirmed-bug test is
  `@pytest.mark.xfail(strict=True, raises=AssertionError, reason="C#: ...")`.
  The suite stays green, a racer crash (any non-assertion error) still fails
  the test, and Task 3's fix turns each one into XPASS → failure until the
  marker is removed.
- Multi-process candidates (C1, C2, C7) are reproduced at function/DB level:
  two sessions in two threads of one process. The race is only on database
  state, so this matches the 4-process deployment for the invariant under
  test. No deployment or infrastructure change was made.
- C3 and C8/J3 call the FastAPI route functions directly (not over HTTP).
  The other tests call the service functions plus `commit()`, which is what
  the route does.
- In the lost-update schedules (C8/H2, P3, X1, J3), the late request's first
  `session.get` stands in for the route/service read. The service then reuses
  that identity-mapped row, which is how the code behaves within one request.

**Commands.**
- Green, normal mode: `pytest tests/integration/test_concurrency_*.py -p no:cacheprovider -rxXfE`
  → `4 passed, 14 xfailed`.
- The defects themselves: `pytest tests/integration/test_concurrency_*.py -p no:cacheprovider --runxfail`
  → the 14 confirmed-bug tests fail with the messages quoted below. The
  4 controls pass. This was repeated 3 times with `-n 4`, and the outcome was
  identical every time.
- Full fast suite after the change: only the two baseline failures
  (`test_block_ids_are_unique`, `test_breakdown_contributions_reconstruct_scores`).

| ID | Test (file :: test) | Reproduced schedule | Observed DB state on unmodified code | Severity |
|---|---|---|---|---|
| C1 (N1) | `test_concurrency_email_outbox.py::test_concurrent_drainers_send_each_outbox_row_once` | Two `_drain_email_outbox` calls (each in its own `session_scope`) both SELECT the one unsent row. Both enter the stubbed `send_email` and meet there. Both set `sent_at` and commit. | `send_email` called **2 times** for 1 outbox row. The row ends up `sent_at IS NOT NULL` (no error, so nothing reveals the duplicate). | Critical: duplicate irreversible SMTP send |
| C2 (R7) | `test_concurrency_range_reminders.py::test_concurrent_reminder_workers_notify_each_recipient_once` | Two `send_due_range_reminders` sessions both SELECT the due event (`reminder_sent_at IS NULL`) and meet right after that SELECT. Both create notifications. B's UPDATE of `range_events.reminder_sent_at` waits for A's commit, then overwrites it. | Both workers return `1`. The soldier has **2** `range_reminder` notifications and the duty manager has **2** (each with its outbox rows). | High: duplicate user-visible messages |
| C3 (A2) | `test_concurrency_shift_assign_batch.py::test_concurrent_batches_cannot_exceed_required_count` | Two `assign_batch` route calls (different soldiers, `required_count=1`) both count 0 active primaries and meet before `create_assignment`. Each locks only its own soldier, inserts, and commits. | **2** published primaries on a `required_count=1` shift. Both requests returned 201. Control `..._within_capacity_both_succeed` (required_count=2) passes. | High: capacity invariant broken |
| C4 (R3) | `test_concurrency_range_assignment_requests.py::test_request_approval_and_manual_add_cannot_exceed_capacity` | `add_range_assignment` (holds the per-date advisory lock) and `approve_assignment_request` (takes no lock) both run `_check_capacity` → 0 primaries and meet right after it. Both insert for different soldiers and commit. | **2** primary `range_assignments` on a `required_count=1` event. Both calls succeeded. The request is `approved`. Control with two free slots passes. | High: capacity invariant broken |
| C5 (K1) | `test_concurrency_personal_constraints.py::test_concurrent_submissions_cannot_exceed_cap` | Two `submit_constraint` calls (2 days each, cap 3, same quarter) both read used=0 in `remaining_days` and meet right after it. Both insert and commit. | **4** pending constraint days against a 3-day cap. Both submissions succeeded. Control (1+1 days) passes. | High: quota invariant broken |
| C6 (I1) | `test_concurrency_import_sessions.py::test_concurrent_confirms_apply_the_import_once` | Two `confirm_session` calls both read the import session (`draft`) and meet right after that SELECT. Both apply the one `duty_shifts` row and set `confirmed`. | **2** `duty_shifts` from a one-row import. Both calls returned `created: 1`. | High: import applied twice |
| C6 (I1) | `test_concurrency_import_sessions.py::test_cancel_committed_during_confirm_stops_the_import` | The confirm reads `draft` and parks. `cancel_session` reads `draft`, sets `cancelled`, and commits. The confirm resumes, applies the rows, and sets `confirmed`. | Both calls succeed. Final status is **`confirmed`** with 1 shift created **after a successful cancel**. The cancel is silently lost. | High |
| C7 (S4) | `test_concurrency_expiry_workers.py::test_swap_expiry_does_not_cancel_a_swap_applied_after_its_read` | The worker's `expire_started_swaps` SELECTs the open request and parks. `approve_soldier_side` locks the request, finalizes it (`applied`, writes cover overrides), and commits. The worker resumes and writes `cancelled`. | Worker cancelled 1. The decision returned `applied`. Final `swap_requests.status='cancelled'` while **1 `duty_day_overrides` cover row is committed**. The covering soldier is on duty for a swap the system reports as cancelled. | High: state contradicts applied effect |
| C7 (E2) | `test_concurrency_expiry_workers.py::test_exemption_expiry_does_not_expire_a_request_approved_after_its_read` | The worker's `expire_stale_exemption_requests` SELECTs the pending request and parks. `approve_duty_manager_step` locks it, sets `approved`, inserts a `soldier_exemptions` row, and commits. The worker resumes and writes `expired`. | Final `exemption_requests.status='expired'` while **1 `soldier_exemptions` row is committed** (an active exemption from a request shown as expired). | High |
| C8 (H2) | `test_concurrency_hierarchy_transfers.py::test_approve_and_reject_of_one_transfer_cannot_both_succeed` | The reject request reads the transfer request (`pending`). `approve_request` moves the soldier, sets `approved`, and commits. The reject resumes, sets `rejected`, and commits. | Both decisions returned success. Final status **`rejected`** but the soldier **was moved** to the destination node. | High |
| C8 (P3) | `test_concurrency_soldier_field_updates.py::test_reject_cannot_overwrite_a_committed_approval` | The reject loads the field update (`pending`). `approve_field_update` (FOR UPDATE) applies the phone change and commits. `reject_field_update` writes `rejected` unconditionally. | Both succeed. Final status **`rejected`** but `soldiers.phone` holds the **new value**. | High |
| C8 (X1) | `test_concurrency_enrollment.py::test_approve_and_reject_of_one_enrollment_cannot_both_succeed` | The reject reads the enrollment request (`pending`). `approve_enrollment` → `try_activate` places the soldier and commits. The reject resumes and writes `rejected`. | Both succeed. Final status **`rejected`** but the soldier **is placed** in the requested node. | High |
| C8 (J3) | `test_concurrency_algorithm_proposals.py::test_accept_and_reject_of_one_draft_cannot_both_succeed` | The reject route loads the draft (`algorithm_draft`). The accept route publishes it (score projection refreshed) and commits. The reject resumes and writes `algorithm_rejected`. | Accept returned `published`, reject returned `algorithm_rejected`. Final status **`algorithm_rejected`**. The soldier was told it was published, and the projection reflects the publish. | High |
| C8 (R5) | `test_concurrency_range_excusal.py::test_concurrent_excusal_approvals_promote_a_reserve_at_most_once` | Two `decide_primary_excusal(approve=True)` calls (different primaries, same event, one reserve) each delete their primary, read `_eligible_assigned_reserves` → [R], and meet right after that read. Both promote R; B's UPDATE waits for A's commit, then re-applies. | **Both** requests record `promoted_assignment_id = R`. The event has **1** primary for `required_count=2`. Neither approval took the no-backfill path, so the missing slot is never reported. | High |

**Dropped candidates.** None. Every C1–C8 candidate and every C8
sub-workflow listed in §4 (H2, P3, X1, R5, J3) was demonstrated, so none
was removed from the confirmed list. C9–C18 are not dropped either: they
are out of Task 2's scope and stay unreproduced candidates for Task 4.

**Controls (passing).** These guard Task 3 against over-serializing:
- `test_single_drainer_sends_each_row_once` (C1)
- `test_concurrent_batches_within_capacity_both_succeed` (C3)
- `test_request_approval_and_manual_add_within_capacity_both_succeed` (C4)
- `test_concurrent_submissions_within_cap_both_succeed` (C5)

Every non-conflicting concurrent request must keep succeeding after a fix.

**New observations from Task 2 (not in the §4 list; not reproduced as
dedicated tests)**
- **O1: score projection quarter total, first insert and lost update.**
  - What happened: in the C3 control, two concurrent first-ever assignments in
    a quarter both called `_upsert_quarter_total`
    (`services/score_projection.py`). Both found no
    `score_projection_quarter_total` row, both INSERTed it, and one request
    failed with `UniqueViolation` on `score_projection_quarter_total_pkey`
    (an HTTP 500 for that request).
  - Why it matters beyond the cold start: the function recomputes the total
    from `_quarter_sums` and writes it back without a lock, so two concurrent
    projection refreshes for the same quarter can also store a total that
    leaves out the other transaction's rows. This was inferred from reading
    the code and was not asserted.
  - Test workaround: the C3 tests pre-create the quarter-total row so the
    capacity race is measured on its own.
  - Status: candidate for Task 4/5.
- **Test-harness note, not a production defect.** The per-test TRUNCATE
  removes the singleton `score_projection_state` row that migration
  `6a7b8c9d0e1f` seeds. On an empty table, two concurrent writers both
  lazily INSERT it and one fails. The `race` fixture restores the seeded row
  so race tests match a migrated production database.

### 4.2 Task 3 — dispositions of the confirmed findings

Every fix is database-level (row lock, `SKIP LOCKED` claim, conditional
`UPDATE ... WHERE`, or the existing per-date advisory lock). Deployment and
worker topology are unchanged, and no Alembic revision was added (head is
still `4858092e72e7`). Each strict-xfail marker was removed and the test
now asserts the single-winner outcome, including the loser's error code.
Under the fix, the winning racer's rendezvous times out (bounded 10 s)
because the loser is blocked on the lock. That timeout is the expected
serialized schedule, not a sleep.

| ID | Disposition | Fix (commit) | Lock order / error mapping |
|---|---|---|---|
| C1 (N1) | **Fixed** | `email_worker._drain_email_outbox` claims one row at a time with `SELECT ... FOR UPDATE SKIP LOCKED` and commits `sent_at`/`error` per row. Rows that fail are excluded for the rest of that drain (`f78cf9b4`). | One row lock at a time. Delivery is still at-least-once if a process crashes between the SMTP send and the commit. |
| C2 (R7) | **Fixed** | `range_reminders._claim_reminder`: `UPDATE range_events SET reminder_sent_at WHERE id AND status='planned' AND reminder_sent_at IS NULL RETURNING` runs before any notification is created. Events are claimed in id order (`bbc66422`). | The losing worker skips the event (returns 0). |
| C3 (A2) | **Fixed** | `routes/shifts.assign_batch` locks `duty_shifts[id]` with `FOR NO KEY UPDATE` before counting (`a53964b2`). | Shift row, then soldiers (in `create_assignment`). `NO KEY UPDATE` does not conflict with the `KEY SHARE` taken by assignment inserts. The loser gets 409 `primary_capacity_exceeded` / `reserve_capacity_exceeded`. |
| C4 (R3) | **Fixed** | `approve_assignment_request` takes the per-date advisory lock, then `FOR UPDATE` on the request (re-checks `pending`), then refreshes the event before `_check_capacity` (`22974693`). | Advisory(date), then the request row, the same order as `add_range_assignment`. The approve route now maps `RangeValidationError` to 400, like the manual-add route. It used to be an unhandled 500. |
| C5 (K1) | **Fixed** | `submit_constraint` locks the soldier row with `FOR NO KEY UPDATE` before `remaining_days` (`8851ecd2`). | Soldier row only. The loser gets `cap_exceeded` (existing 400 mapping). Other inserters that do not check the cap (registration, HR onboarding, import) are unchanged. |
| C6 (I1) | **Fixed** | `_lock_import_session` (`FOR UPDATE`, `populate_existing`) is used by `confirm_session` and `cancel_session` (`09c5d603`). | The import row is held for the whole confirm transaction. The loser gets `only_draft_sessions_can_be_confirmed/_cancelled` (existing 400). `reparse_session` / `mark_done` / `set_selections` were not changed (not reproduced). |
| C7 (S4, E2) | **Fixed** | `expire_started_swaps` and `expire_stale_exemption_requests` re-lock each candidate with the decision paths' `_lock_request` in id order and skip it unless it is still open/pending (`b35f0d1f`). | Request row first, the same as the decision paths. A decided request is left as it is. |
| C8/H2 | **Fixed** | `hierarchy_transfers.lock_request_for_decision` (soldier `FOR UPDATE`, then request `FOR UPDATE`, fresh read) is used by approve/reject and by both routes **before** `authorize` (`058629d9`). | Soldier, then request, the same order as `create_request`. The loser gets `not_pending` (400). Authorization now checks the destination node that is applied. |
| C8/P3 | **Fixed** | `reject_field_update` takes the same `FOR UPDATE` re-read as `approve_field_update` and requires the status the route authorized against (`be765728`). | The update row only; reject takes no soldier lock, so C9's order is unchanged. The loser gets `not_pending` (400). |
| C8/X1 | **Fixed** | `enrollment.lock_request` (`FOR UPDATE`, fresh read) is used by approve/reject and by both routes before `authorize` (`533d3436`). | Enrollment request, then soldier (`try_activate`), consistent with exemption → enrollment → soldier. The loser gets `already_decided` (400). |
| C8/J3 | **Fixed** | `routes/algorithm._transition_draft` applies the bulk routes' guard `UPDATE ... WHERE status='algorithm_draft' RETURNING` to all four single-item accept/reject routes (`f1eab90f`). | The loser gets 409 `not_draft` (existing code). |
| C8/R5 | **Fixed** | `decide_primary_excusal` takes the per-date advisory lock, then `FOR UPDATE` on the excusal request (re-checks `pending`), before reading eligible reserves (`57da94d3`). | Advisory(date), then request, then assignments, then reconciliation's later-date advisory locks (ascending), the same order as `add_range_assignment`. The second approval takes the no-backfill path and notifies duty managers. |

**Verification.**
- `pytest tests/integration/test_concurrency_*.py`: **18 passed**, 0 xfailed.
- Each fix also ran its focused workflow suites: range, shifts routes,
  constraints, imports, swaps/exemptions, transfers, soldiers/field updates,
  enrollment/registration, and algorithm proposals.
- Fast suite (`pytest -p no:cacheprovider`): **2148 passed, 3 skipped,
  2 failed**. The failures are only the two baseline failures
  (`test_block_ids_are_unique`, `test_breakdown_contributions_reconstruct_scores`).

**Residual risk (not addressed by Task 3).**
- C9–C18 and O1 are still unreproduced.
- The fixes serialize only the writers named above. Range roster writers that
  do not take the per-date lock (e.g. reserve excusal, removal) were not
  reviewed under concurrency.
- Shift writers other than `assign_batch` (single create, algorithm publish)
  do not check capacity at all, so the shift lock does not constrain them.

### 4.3 Task 4 — C9–C18 and O1: reproduction and dispositions

**Method.** Same as §4.1: independent sessions in threads on the
Testcontainers PostgreSQL 16 fixture (READ COMMITTED), explicit rendezvous /
signals from the `race` fixture, no sleeps. Each reproduction was committed
first as `@pytest.mark.xfail(strict=True, raises=AssertionError)` and seen to
fail on unmodified code (`--runxfail` messages quoted below); the fix commit
removes the marker. Lock-order candidates assert "no request fails with a
database error", so `DeadlockDetected` is the observed defect. Failure-
injection tests (C18) make the step after the suspect commit raise, roll back
as the request handler would, and inspect committed state. New test files are
registered in `_AREA_MARKERS`.

| ID | Test (file :: test) | Observed on unmodified code | Severity | Fix (commit) | Lock order / error mapping |
|---|---|---|---|---|---|
| C9 (P4) | `test_concurrency_field_update_lock_order.py::test_concurrent_submit_and_approve_of_one_field_do_not_deadlock` | Approve holds the update row, submit holds the soldier; `DeadlockDetected` aborts the submit ("while updating tuple … soldier_field_updates"). | Medium | `approve_field_update` locks the soldier (`FOR NO KEY UPDATE`, fresh read) before the update row (`daf8ec74`). | soldier → field update, the same order as submit. Reject takes no soldier lock and writes no soldier, so it cannot cycle. |
| C10 (A3) | `test_concurrency_shift_batch_lock_order.py::test_batches_with_opposite_soldier_order_do_not_deadlock` | Batches on two shifts with [S1,S2] / [S2,S1]: `DeadlockDetected` "while locking tuple … soldiers". (Same-shift batches were already serialized by the C3 shift lock.) | Medium | `assign_batch` locks all batch soldiers `ORDER BY id FOR UPDATE` right after the shift row (`3285b51c`). | shift row → soldiers ascending. `create_assignment`'s own soldier lock is then re-entrant. |
| C11 (R2) | `test_concurrency_range_batch_lock_order.py::test_batch_reconciliation_and_single_add_do_not_deadlock` | Batch on D1 reconciles A into D5, then B into D3; a single add on D3 reconciles into D5: advisory-lock `DeadlockDetected`. | Medium | `range_reconciliation.lock_reconciliation_target_dates` takes every later date the batch may touch, ascending, before reconciling; `assign_batch` calls it (`db740781`). | advisory(event date) → later dates ascending across the whole batch. The set is a superset of the dates actually touched (only extra serialization). |
| C12 (T1, T2) | `test_concurrency_one_time_tokens.py` (3 tests: email-link action token, Telegram action token, password-reset token) | Both redeemers return success for one token (`redeemed 2 times`); both reset calls return `ok`. | Medium | The three redeem SELECTs use `FOR UPDATE` + `populate_existing` (`f6b6abff`). | Token row only. The loser re-evaluates `used_at IS NULL` after the winner commits and gets `None` / `token_invalid`. |
| C13 (J1) start | `test_concurrency_algorithm_jobs.py::test_cancel_committed_before_the_runner_starts_is_not_overwritten` | A cancel committed between the runner's read and its `running` write is overwritten: the runner moved the cancelled job to `running` and began solving. | Medium | Runner claims with `UPDATE … WHERE status='pending' RETURNING` and returns if nothing matched (`39a9a1c5`). | Job row only. |
| C13 (J1) finish | `…::test_cancel_cannot_overwrite_a_job_that_finished_after_its_read` | A cancel that read `running` overwrote a committed `done` with `failed/cancelled_by_user` (drafts and the "done" notification stay). | Medium | `cancel_job` and the timeout watchdog re-read the job `FOR UPDATE` before the status check (`30a37435`). | Loser gets 409 `not_cancellable`. |
| C13 (J4) | `…::test_startup_hook_does_not_fail_a_job_another_process_is_solving` (+ control `…_still_fails_a_job_whose_runner_is_gone`) | `_fail_orphaned_algorithm_jobs` marked a job a live runner was solving as `failed/server_restarted`. | Medium | The runner holds a session-level `pg_try_advisory_lock(ns, hashtext(job_id))` on a dedicated connection for the whole run; the startup hook fails a `running` job only if `pg_try_advisory_xact_lock` on that key succeeds (`7301d6fc`). | PostgreSQL drops the lock when the owner connection dies, which is the orphan definition. A second runner for the same job now returns immediately. |
| C15 (T4) | `test_concurrency_email_verification.py::test_two_accounts_cannot_both_verify_one_email` | Two soldiers with one email both verified (`2 accounts verified`). | Medium | `verify_token` locks the token row, then `pg_advisory_xact_lock(ns, hashtext(email))` before the conflict check (`b0f10b0f`). | token → email lock → soldier. Loser gets `email_taken`. No partial unique index was added: it could fail to build on existing duplicate data, and `verify_token` is the only writer of `email_verified = true`. |
| C16/D1 | `test_concurrency_dismissals.py::test_concurrent_overlapping_dismissals_record_only_one` | Two overlapping dismissals committed on one assignment. | Medium | `dismiss_primary` / `dismiss_reserve` lock the assignment (`FOR NO KEY UPDATE`) before the overlap read (`8d377d4d`). | assignment row only. Loser gets `overlapping_dismissal`. |
| C16/N4 | `test_concurrency_qualification_expiry.py::test_concurrent_mitvahim_expiry_checks_notify_once` | Two worker processes each created a `mitvahim_expired` notification for one expiry. | Medium/Low | Each check takes `pg_try_advisory_xact_lock(hashtextextended('qualification_expiry:<kind>'))` and returns if another process holds it (`a1a4dbd8`). | Same single-runner pattern as `score_projection_revalidation_worker`. |
| C16/R8 | `test_concurrency_range_attendance.py` (2 tests) | Two auto-mark workers both recorded a qualification for one attendance (`2 qualifications`); a manual `no_show` committed after the worker's read was overwritten with `present` while its no-show penalty adjustment stayed. | Medium | `ranges.lock_assignment_for_attendance` (soldier `FOR NO KEY UPDATE`, then assignment `FOR UPDATE`, fresh read) at the start of `mark_attendance`; the auto-mark worker re-checks `pending` on the locked row and skips otherwise (`77eb9225`). | soldier → range assignment, the order the flush already used. |
| C16/K3 | — | **Not reproduced as a concurrency defect.** `approve_constraint` never checks existing assignments, so "assignment created, then constraint approved, no override recorded" is the sequential outcome too. The concurrent schedule produces no state the sequential one cannot. | — | none | Product question only (should approval warn about existing assignments?). |
| C17/A6 | `test_concurrency_duplicate_inserts.py::test_concurrent_day_overrides_for_one_day_both_succeed` | Second insert: `UniqueViolation uq_duty_day_overrides_assignment_date` (500). | Low | `assignments.lock_assignment_row` before the existence check in `set_day_override` (`0e1b8c3d`). | (swap request →) assignment. The second request updates the existing override, as it would sequentially. |
| C17/S3 | `…::test_concurrent_take_free_of_one_duty_yields_already_pending` | Second `take_free`: `UniqueViolation uq_swap_requests_one_open_per_requester_duty` (500). | Low | Translate the `IntegrityError` to `SwapError("already_pending")`, like `create_request` (`b13130d1`). | A lock would not cover the competing `create_request`, which takes no assignment lock. |
| C17/D3 | `…::test_concurrent_no_show_marks_yield_already_marked` | Second mark: `UniqueViolation uq_duty_no_shows_assignment` (500). | Low | Assignment lock before the existence check (`388bef0d`). | Loser gets `already_marked`. |
| C17/D2 | `…::test_concurrent_relinks_of_one_primary_both_succeed` | Second relink: `UniqueViolation uq_reserve_links_primary` (500). | Low | Lock the primary before reading its link (`0726b5eb`). | Second relink replaces the link. Two `dismiss_reserve` calls relink disjoint primary sets, so they cannot cycle with each other. **This fix did introduce a cycle candidate with other workflows** (review finding; reproduced and fixed, see the row below): `dismiss_reserve(R, covering_reserve_id)` takes R → quarter total (projection refresh) → P (relink), while `dismiss_primary` / `mark_no_show` / `set_day_override` / `relink_reserve` on P take P → quarter total. |
| D2 follow-up (review) | `test_concurrency_dismissals.py::test_covered_reserve_dismissal_and_primary_dismissal_do_not_deadlock` | `dismiss_reserve(R, covering_reserve_id)` held the quarter total and waited for linked primary P; `dismiss_primary(P)` held P and waited for the quarter total: `DeadlockDetected` "while locking tuple … duty_assignments". | Medium | With a cover, `dismiss_reserve` locks R's linked primaries (`ORDER BY id`, `FOR NO KEY UPDATE`) right after R, before the projection refresh (`e34a42c9`; test `710ae78e`). | reserve → linked primaries ascending → projection rows. Primary-side writers keep P → projection. |
| C17/R3 | `test_concurrency_range_assignment_requests.py::test_concurrent_double_approval_of_one_request_approves_once` | Already fixed by C4 (Task 3); this is a regression test, not a reproduction on pre-Task-3 code. | Low | — (`95320a59`) | Loser gets `request_not_pending`. |
| C18 (J6) | `test_concurrency_partial_commits.py` (accept, bulk accept, primary-excusal approval) | After an injected failure right after `recheck_assignments`, the proposal stayed `published`; the excusal stayed `approved` with the primary assignment deleted. In `decide_primary_excusal` the mid-way commit also released the C8/R5 advisory and request locks. | Medium | In-transaction callers pass `commit=False` (accept, bulk accept, `range_excusal._recheck_soldier_assignments`, `mark_attendance`) (`cb62184c`). | Callers whose recheck runs after their own commit (duty-config route, settings route, eligibility worker) keep the default. |
| O1 | `test_concurrency_score_projection.py` (3 tests) | (a) two first writes in a quarter: `UniqueViolation score_projection_quarter_total_pkey`; (b) quarter total `raw_day_count=2` while its rows sum to 4 (lost update); (c) two refreshes for one soldier: `UniqueViolation uq_score_projection_dirty_bucket`. | Medium | `_lock_or_create_row` (`INSERT … ON CONFLICT DO NOTHING`, then `SELECT … FOR UPDATE`) *before* computing values, for the quarter total and soldier total; same for the dirty bucket (`8b10aca3`). | Same rows the old code already locked by UPDATE in the same function, now locked before the read. |

**Also done in Task 4 (scope ruling 2).**
- `cancel_constraint` approved → cancelled path: `timezone` NameError fixed
  (`70daa649`); new test
  `test_constraints_service.py::test_cancel_approved_constraint_with_reason_marks_it_cancelled`.
- Route-level test: approving a range assignment request on a full event
  returns 400 `primary_capacity_exceeded` (`e3ffe404`).
- SMTP connection timeout (30 s) in `services/email.py`, with a unit test
  (`6c6c2b40`). The C1 outbox claim holds the row lock across the send.
- `enrollment.lock_request` docstring corrected (`8bd30d3c`): the exemption
  path takes no enrollment lock, and `try_activate` takes no explicit soldier
  lock.
- P3: the approve/reject field-update routes map the service's `not_found`
  (row deleted between the route's read and the locked re-read) to 404
  (`2c608222`), with a route test.

**Not reproduced.**
- **Original J1 hypothesis** (cancel commits between the runner's
  `session.refresh(job)` and its final commit). `persist_results` has already
  flushed an UPDATE of the job row by then, so the cancel blocks on that row
  lock. What the cancel then does is the "finish" schedule above (fixed).
- **C16/K3**, see the table.

**Deferred: C14 (S5/A6) — product decision needed.** Two swaps (or a swap and
a manual override) on different duties the same day can both make the same
soldier the effective soldier for that day. `_day_busy` checks only nominal
`duty_assignments.soldier_id` and ignores `duty_day_overrides`, so this is
reachable **sequentially** too. Before a lock can be added, the product needs
to decide: does an override make the covering soldier "busy" for that day
(i.e. must `_day_busy` include effective soldiers from overrides), and should
a covering soldier be allowed to hold two duties on one day by override?
Once that is decided, the fix is a check that includes overrides plus a
per-(soldier, date) serialization point (for example an advisory lock on the
covering soldier's id and the date, taken in `set_day_override` and
`_apply_cover`). No safeguard was weakened.

**Medium/low items that remain open.**

| Item | Impact | Evidence | Recovery path | Owner | Why deferral is reasonable |
|---|---|---|---|---|---|
| C14 cross-request double booking | A soldier can be the effective soldier for two duties on one day | Sequential rule gap (code reading); see above | Manager removes one override | Product owner (rule), then backend | Needs the rule decision above; the sequential path has the same gap |
| N4 try-lock skip | If the process that wins the daily expiry check crashes mid-run, the others skipped that day | Design of the fix | The next daily run notifies (dedupe is per expiry date) | Backend | One-day delay of an informational notification; no duplicate or lost state |
| Projection lock order inside `refresh_projection_for_change` | Two refreshes covering overlapping soldier sets lock dirty buckets and the quarter total interleaved per soldier, so a cycle (bucket S1 → quarter total → bucket S2 vs bucket S2 → quarter total) is possible | Code reading only; **not reproduced**. The old code already took these locks in the same order (UPDATE of the same rows) | A deadlock surfaces as one 500; the user retries | Backend | Not demonstrated; reordering the projection refresh is a larger change with many callers |
| `take_free` rollback on conflict | The loser's whole session is rolled back inside the service | Same pattern as `create_request` | n/a (the route returns an error) | Backend | Matches existing project convention |
| Runner lock holds a pool connection per running job | One extra DB connection for each solve in progress | Fix design (C13/J4) | — | Backend | Solves are few and bounded by the solver executor; pool is 20 + 10 overflow |

**Verification.**
- `pytest tests/integration/test_concurrency_*.py -o addopts="-n 4"`:
  **44 passed**, twice in a row; **45 passed** after the D2 follow-up.
- Focused suites after each fix: soldiers area, shifts routes, range suites
  (API, service, batch, excusal, attendance), token/forgot-password/bot,
  algorithm cancel/notification/routes, auth area, constraints, reserves,
  no-show, swaps, scoring area, and the relevant `app/services/tests`
  projection/attendance/excusal tests (those need a resolvable `REDIS_URL`
  on this machine; that was a pre-existing environment issue).
- Fast suite (`pytest -p no:cacheprovider -o addopts="-n 4"`): **2178 passed,
  3 skipped, 2 failed**. The failures are only the two baseline failures.

### Items that are not concurrency defects but were found during the inventory

- `constraints.cancel_constraint`: undefined `timezone` on the approved →
  cancelled path. **Fixed in Task 4** (`70daa649`).
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

- C1–C8 are reproduced, confirmed (§4.1) and fixed (§4.2). C9–C18 and O1 are
  dispositioned in §4.3. C14 is deferred for a product decision; C16/K3 and
  the original J1 schedule were not reproduced.
- Inventory items outside C1–C18 that were never reproduced: A4 (concurrent
  replaces of one assignment), A5 (duplicate cancel notification), A6
  `clear_day_override`, P5 (profile lost updates, `bump_token_version`), T3
  (token invalidation race; SMTP inside the request transaction, now bounded
  by the timeout), T7, I2/I3, D4, N2 (bot scaled out), N5, X2 (object-store
  PUT after the row flush), X3/P6 (duplicate → 500).
- Modules listed under "Not reviewed in this task" in §2.
- No PostgreSQL race test exists for the `create_assignment` soldier lock (A1),
  even though the code comment relies on it.
- The production `default_transaction_isolation` was not checked.
- Behavior with `WEB_CONCURRENCY` other than 4, and the bot when scaled
  beyond one process.
