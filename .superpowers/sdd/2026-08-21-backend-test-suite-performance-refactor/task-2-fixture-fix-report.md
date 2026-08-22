# Task 2 compatibility fix: database runtime fixture re-export

## Delivered

- Added `_database_runtime` to the fixture imports re-exported by
  `backend/app/services/tests/conftest.py`.
- Left application code and database isolation semantics unchanged.
- Preserved the pre-existing unrelated worktree changes; they were neither
  staged nor modified by this task.

## Regression evidence

The existing algorithm bridge test
`test_resolve_solver_settings_uses_system_defaults` already requests
`admin_session`, which transitively needs `_database_runtime`. It is therefore
the focused regression for fixture visibility; no duplicate test was added.

Before the re-export, run from `backend`:

```text
python -m pytest app/services/tests/test_algorithm_bridge.py::test_resolve_solver_settings_uses_system_defaults -q -n 0
```

Result: failed at setup with `fixture '_database_runtime' not found` while
resolving the re-exported `_apply_schema` fixture.

After the re-export, the same command completed successfully in 10.4 seconds
(well within the 180-second maximum):

```text
.                                                                        [100%]
```

Pytest emitted the pre-existing third-party
`starlette.formparsers` `PendingDeprecationWarning` for `multipart`.

## Scope

- No broad suite was run.
- The local `backend/.venv` was absent, so the focused command used the
  already-available `C:\Python313\python.exe` environment with pytest 9.0.3;
  no dependencies were installed or changed.
