# Task 2 report: database test adapter

## Delivered

- Added `backend/tests/support/database.py`, a test-only `TestDatabaseRuntime`
  that owns the worker database URL, migration decision, session-scoped admin
  and app engines, reset SQL, and migration-seeded defaults.
- Moved reset table ordering and precomputed reset/seed SQL into the adapter.
  `reset_database(engine)` retains the prior truncate, identity restart,
  cascading, system-settings reseed, and hierarchy-level-type reseed behavior.
- Kept `pg_container`, `db_admin_url`, `admin_engine`, `app_engine`,
  `admin_session`, and `app_session` fixture names compatible. Focused and
  single-process runs migrate their own container; xdist worker clones skip a
  redundant migration.
- Left application production code untouched. Unrelated soldier-modal work
  remains unstaged and unmodified by this task.

## Test-first evidence

The new adapter contract test was run before implementation and failed during
collection because `tests.support.database` did not exist. After implementation
it passed.

## Verification

| Command | Result |
| --- | --- |
| `pytest tests/unit/test_database_test_adapter.py -q -n 0` | 4 passed |
| `pytest tests/unit/test_database_test_adapter.py tests/unit/test_test_fixtures.py -q -n 0` | 54 passed |
| `pytest tests/integration/test_soldiers_api.py tests/integration/test_private_fields.py -q -n 0` | 38 passed in 46.1 seconds |
| `pytest tests/integration/test_soldiers_api.py tests/integration/test_private_fields.py -q -n 0 --durations=30` | 38 passed in 37.5 seconds |
| `pytest tests/integration/test_audit_append_only.py -q -n 0` | 3 passed; app-role insert/update/delete RBAC exercised |

All completed pytest commands emitted the pre-existing third-party
`starlette.formparsers` `PendingDeprecationWarning` for `multipart`.

## Measurement

The representative duration run is recorded in
`docs/superpowers/benchmarks/2026-08-21-backend-test-suite-performance-baseline.md`.
It has no matching pre-Task-2 phase breakdown, so a numeric delta is not
available. The report did not show reset cost as a material contributor; no
further reset strategy was attempted.

## Scope and concerns

- No broad suite was run.
- The requested stop instruction was received after the narrow integration
  checks above had completed; no integration suite was started afterward.
- No production behavior changed.

## Review follow-up: required Step 6 measurement

Command, run from `backend` with a 180-second cap:

```text
pytest tests/integration/test_soldiers_api.py tests/integration/test_private_fields.py -q -n 0 --durations=30
......................................                                   [100%]
============================== warnings summary ===============================
starlette.formparsers.py:12: PendingDeprecationWarning: Please use python_multipart instead.

============================ slowest 30 durations =============================
7.93s setup    tests/integration/test_soldiers_api.py::test_admin_onboards_without_password_gets_temp
1.45s call     tests/integration/test_soldiers_api.py::test_list_soldiers_query_count_does_not_scale_with_soldier_count
0.66s teardown tests/integration/test_private_fields.py::test_self_can_see_own_exemption_type_and_reason
0.66s setup    tests/integration/test_private_fields.py::test_out_of_scope_profile_uses_public_mode_and_exposes_approved_public_fields
0.60s setup    tests/integration/test_private_fields.py::test_admin_cannot_see_exemption_type_or_reason
0.59s setup    tests/integration/test_soldiers_api.py::test_commander_below_min_level_cannot_delete
0.55s setup    tests/integration/test_soldiers_api.py::test_phone_and_email_hidden_when_public_settings_disabled
0.54s setup    tests/integration/test_private_fields.py::test_admin_cannot_see_phone_email_when_public_settings_disabled
0.51s setup    tests/integration/test_soldiers_api.py::test_patch_enrolled_at
0.49s call     tests/integration/test_private_fields.py::test_admin_list_soldiers_private_fields_null
0.49s setup    tests/integration/test_private_fields.py::test_dm_in_scope_can_see_gender
0.48s setup    tests/integration/test_private_fields.py::test_admin_list_soldiers_private_fields_null
0.43s call     tests/integration/test_private_fields.py::test_admin_cannot_see_gender_but_sees_phone_email_by_default
0.40s call     tests/integration/test_private_fields.py::test_plain_soldier_cannot_see_peer_gender
0.37s setup    tests/integration/test_soldiers_api.py::test_plain_soldier_can_view_another_soldiers_basic_profile
0.37s setup    tests/integration/test_private_fields.py::test_plain_soldier_cannot_see_peer_gender
0.36s setup    tests/integration/test_soldiers_api.py::test_onboard_with_password_no_temp_returned
0.35s call     tests/integration/test_private_fields.py::test_admin_cannot_see_exemption_type_or_reason
0.35s setup    tests/integration/test_soldiers_api.py::test_release_soldier_sets_left_at_to_given_date
0.34s call     tests/integration/test_private_fields.py::test_admin_cannot_see_phone_email_when_public_settings_disabled
0.34s setup    tests/integration/test_private_fields.py::test_self_can_see_own_constraint_reason
0.33s call     tests/integration/test_private_fields.py::test_dm_in_scope_can_see_gender
0.33s setup    tests/integration/test_soldiers_api.py::test_reset_password_returns_temp_and_sets_flag
0.33s setup    tests/integration/test_soldiers_api.py::test_duty_manager_can_only_onboard_in_scope
0.33s setup    tests/integration/test_soldiers_api.py::test_duty_history_survives_permanent_pending_exemption_request
0.33s setup    tests/integration/test_soldiers_api.py::test_commander_at_mador_or_above_can_delete_in_scope
0.33s setup    tests/integration/test_soldiers_api.py::test_me_exposes_can_delete_soldier_flag
0.33s setup    tests/integration/test_soldiers_api.py::test_list_soldiers_telegram_linked_false_by_default
0.33s setup    tests/integration/test_soldiers_api.py::test_soft_delete_sets_left_at
0.32s setup    tests/integration/test_private_fields.py::test_target_read_permission_gets_full_mode_independently_of_navigation_path
```

The reset fixture is included in each test setup, but pytest cannot split out
fixture-internal reset time. Therefore the recurring 0.32–0.66-second setup
times are reset-inclusive upper bounds; the 7.93-second first setup includes
container and migration startup. A like-for-like base/head comparison is not
available because the recorded baseline has no run of this exact slice or
per-phase timing. The benchmark document records the comparison rationale.
