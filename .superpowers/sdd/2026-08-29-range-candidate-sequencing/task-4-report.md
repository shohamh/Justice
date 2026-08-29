# Task 4 report

## Result

Weapon-duty eligibility now obtains projected range windows from the shared
range-coverage module. Non-draft planned primaries, completed reserves, draft
assignments, range-type hierarchy, and range-date ordering use one set of
predicates.

Candidate ranking always treats a pending primary excusal as reserve-like.
Eligibility projections retain the existing
`weapon_qualification.pending_excusal_disqualifies` setting: when enabled,
pending primary excusals do not project eligibility; when disabled, the
projection keeps its established configurable behavior.

## RED

`pytest -q tests/unit/test_eligibility.py -k 'projects_only_guaranteed_future_range_coverage_at_duty_date'`

```text
.F...
FAILED tests/unit/test_eligibility.py::test_range_eligibility_projects_only_guaranteed_future_range_coverage_at_duty_date[completed-reserve]
assert False is True
```

## Verification

Command:

```powershell
pytest -q tests/unit/test_eligibility.py tests/integration/test_calendar_api.py
```

Exact result:

```text
...........................................................              [100%]
59 passed, 5 warnings in 32.8s
```

## Concerns

- The five warnings are pre-existing `starlette.formparsers` pending-deprecation
  warnings for `multipart`; they do not come from this change.
- The focused Task 4 command is green. No broader suite was run.
