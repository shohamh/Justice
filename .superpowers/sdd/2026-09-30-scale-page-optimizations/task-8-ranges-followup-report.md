# Task 8 Ranges display follow-up

Date: 2026-10-02

## Change

- The bounded soldier-name lookup now matches legacy `GET /soldiers` personal-number visibility. Admins and non-admins with scope roots receive personal numbers on requested global rows. Non-admins without roots receive only their own row. The 200-ID request cap, deduplication, request order, and exclusion of unrelated rows remain in place.
- `RangesPage` resolves responsible-manager names from loaded range rows plus the selected detail/edit event. It deduplicates IDs and splits lookups into requests of at most 200 IDs. Missing rows still display their IDs. The full soldier roster is not requested.
- Candidate behavior, assignment mutations, range paging, and hierarchy preload were not changed.

## RED/GREEN evidence

- RED: `& '.venv/Scripts/python.exe' -m pytest -q -n 0 tests/integration/test_soldiers_api.py -k bounded_display_lookup` failed 2 tests: scoped out-of-scope and admin/no-roots personal numbers were absent.
- RED: `npx vitest run src/pages/RangesPage.test.tsx -t "resolves loaded table managers|keeps loaded-row manager lookup|loads only referenced display rows"` failed 3 tests: loaded manager names and IDs were missing from the lookup.
- GREEN: backend same focused command passed 2 tests. Full `tests/integration/test_soldiers_api.py` passed 33 tests.
- GREEN: `npx vitest run src/pages/RangesPage.test.tsx src/components/ranges/RangeEditAssignmentsModal.test.tsx --reporter=dot` passed 74 tests in 2 files. Existing React `act(...)` and i18next warnings appeared.
- `npx eslint src/pages/RangesPage.tsx src/pages/RangesPage.test.tsx` passed.
- `git diff --check` passed.

## Additional check

`npm run typecheck` reported existing errors in hierarchy, scoring, soldiers API, hierarchy components, and Transparency files. It reported none in the changed Ranges page or test. This repository-wide check is not green for this slice.
