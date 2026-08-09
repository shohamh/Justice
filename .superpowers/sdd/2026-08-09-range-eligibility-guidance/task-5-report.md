# Task 5 report: calendar eligibility warnings

## Implementation

- Added `GET /calendar/weapon-ineligible/count`, accepting the same node/personal and date-range inputs as the shift calendar.
- The calendar service first derives the displayed primary assignments, then uses Task 1's `count_ineligible_soldiers_for_duties` projection. This yields unique visible soldiers, evaluates each duty at its scheduled date, excludes non-weapon duties through the projection, and preserves the projection's confirmed-main-range-only semantics (reserve/draft planned range assignments do not cover a duty).
- `UnitCalendar` loads the count independently from calendar/range data. The badge is hidden while the count is pending or fails, so either condition leaves the calendar usable.
- Added a red warning badge, always-rendered duty-type dropdown, and pointer/light-dark hover affordances for both shift and range events. The shared `UnitCalendar` serves unit, homepage, and commander calendar views.

## TDD evidence

1. Backend RED: `pytest tests/integration/test_calendar_api.py -q -k calendar_weapon_ineligible_count` failed with `404 Not Found` for `/api/calendar/weapon-ineligible/count`.
2. Backend GREEN: the same command passed (`1 passed`) after adding the route/service projection.
3. Frontend RED: `npm test -- src/components/UnitCalendar.test.tsx` failed three new checks because the warning badge, event interaction classes, and empty-calendar duty filter did not exist.
4. Frontend GREEN: the same command passed (`6 passed`) after the minimal calendar UI/API implementation.

## Required validation

- `backend> pytest tests/integration/test_calendar_api.py app/services/tests/test_calendar_shifts.py -q` — passed, 18 tests.
- `frontend> npm test -- src/components/UnitCalendar.test.tsx src/pages/UnitCalendarPage.test.tsx` — passed, 6 tests.
- `frontend> npm run lint` — passed (`tsc --noEmit && eslint src --max-warnings 0`).
- `frontend> npm run typecheck` — passed (`tsc --noEmit`).
- `git diff --check` — passed with no whitespace errors.

## Concerns

None. The first `npm run typecheck` was accidentally invoked from the repository root, where no script exists; it was immediately rerun from `frontend` and passed.

## Review fix round

- Final required validation after this fix round: backend 19 passed; frontend 7 passed; lint, typecheck, and `git diff --check` passed.
- The count endpoint now authorizes the requested hierarchy node; an out-of-scope non-admin receives `403` and cannot infer a hidden aggregate.
- The count endpoint now filters primary assignments through the same private-assignee scope policy used by calendar shift redaction: admins see all, while other users see only themselves and soldiers below their commander/duty-manager roots.
- The calendar now stamps each count request and ignores stale success or failure callbacks after a newer visible date range is selected.
- Backend RED: `pytest tests/integration/test_calendar_api.py -q -k hides_out_of_scope` returned `{'count': 1}` to an out-of-scope soldier instead of `{'count': 0}`. GREEN: the same command passed (`1 passed`).
- Frontend RED: `npm test -- src/components/UnitCalendar.test.tsx` showed the stale first response as `⚠1` after the second range had shown `⚠2`. GREEN: the same command passed (`7 passed`).
