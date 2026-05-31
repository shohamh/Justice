# Agent Onboarding

Orientation for AI agents (Claude Code and similar) working in this repo. Read
[developers.md](developers.md) for setup and the codebase tour; this file covers
how to *work* here effectively.

## Read these first

1. **The design doc** —
   [`docs/superpowers/specs/2026-05-27-army-duty-management-design.md`](../superpowers/specs/2026-05-27-army-duty-management-design.md).
   It is the source of truth for intent, the data model, the permission matrix,
   the algorithm, and the phasing. When code and the doc disagree, the code is
   reality but the doc tells you the *target* — note the gap, don't silently
   diverge.
2. **The plans** — [`docs/superpowers/plans/`](../superpowers/plans/). Each slice
   has a spec and a matching plan. New work follows the same spec → plan →
   implement loop.
3. **This onboarding set** — [user-guide.md](user-guide.md),
   [developers.md](developers.md).

## How this project is built

Slice by slice, using the **superpowers** workflow:

- **Brainstorm** before creative work (new features, behaviour changes).
- **Write a spec**, then **write a plan**, before touching code.
- **TDD**: write the failing test first, then the implementation.
- **Verify before claiming done** — run the actual commands, paste the evidence.
  Never assert "tests pass" without having run them.
- **Request code review** at the end of a meaningful chunk.

Invoke the relevant skill rather than improvising these.

## Working rules specific to this repo

- **Scope.** Commits are small and scoped — roughly one per plan task. Recent
  history mixes direct-to-`master` commits with feature branches; **confirm the
  branch strategy with the user before starting** rather than assuming. Commit
  and push **only when the user asks**.
- **Run commands from the right place.** Backend: `cd backend` then `uv run …`
  (uv won't find the project from the repo root). Frontend: `cd frontend` then
  `pnpm …`.
- **The match-the-gate rule.** Before saying a change is done, run, from
  `backend/`: `uv run ruff check app tests`, `uv run ruff format --check app
  tests`, `uv run mypy app`, `uv run pytest -q`; and from `frontend/`: `pnpm
  lint`, `pnpm exec tsc --noEmit`, `pnpm test`, `pnpm build`. These mirror
  [CI](../../.github/workflows/ci.yml).
- **Docker must be running** for `pytest` integration tests (testcontainers) and
  the local `db` service.
- **Windows + PowerShell** is the dev environment. Use `$env:VAR` / `$null`, not
  bash idioms, in one-off shell commands.

## Invariants you must not break

- **Authorization goes through `authz.authorize(...)`.** Every management
  endpoint calls it; the RBAC matrix integration test
  (`tests/integration/test_rbac_matrix.py`) asserts the wiring. New guarded
  actions get a new `Action` constant and an entry in `_DM_ACTIONS` /
  `_COMMANDER_ACTIONS` as appropriate.
- **Every state change writes an audit row**, in the **same transaction** as the
  change (`audit/writer.py`). The `audit_log` table is INSERT/SELECT-only for the
  `app` DB role — never add an UPDATE/DELETE path against it.
- **`algorithm/` stays pure** — no imports from `db/` or `routes/`. Plain data in,
  plain data out. It must remain unit-testable without a database.
- **Tunables live in `system_settings`, not in code.** No bare magic numbers in
  domain logic.
- **All UI strings live in `frontend/src/i18n/he.json`** (Hebrew, RTL). Backend
  errors return stable string keys that the frontend maps to Hebrew.
- **Migrations are reversible** and numbered sequentially; grant `app` table
  permissions in the migration that creates the table.
- **Files over ~400 lines** should be split by responsibility.

## Where things live (quick map)

| Need to… | Go to |
|---|---|
| Add/guard an endpoint | `backend/app/routes/<context>.py` + `auth/authz.py` |
| Add domain logic | `backend/app/services/<context>.py` |
| Change the schema | new `backend/alembic/versions/NNNN_*.py` + `db/models.py` |
| Touch the solver | `backend/app/algorithm/` (+ its `tests/`) |
| Add a screen | `frontend/src/pages/` + `api/` + `i18n/he.json` + `Layout.tsx` nav |
| Change permissions UI | `frontend/src/components/Layout.tsx` (nav gating) + the backend `authorize` call |

## Known deviations & open items

- **No production deployment artefacts** — `docker-compose.yml` runs only
  Postgres; there is no Caddy/TLS or prod compose file yet. The design doc
  describes the target.
- **OpenAPI docs are disabled** (`docs_url=None` in `main.py`), not gated behind
  admin as the doc envisions.
- **Deferred bug — `revoke_exemption` on already-expired exemptions** rewrites
  `end_date` forward to today, re-opening a closed exemption
  (`services/exemptions.py`). The fix is **blocked on a product decision**
  (reject vs. no-op) — don't fix it unilaterally. Details:
  [`docs/superpowers/specs/2026-05-29-slice-3-duty-config-and-exemptions-design.md`](../superpowers/specs/2026-05-29-slice-3-duty-config-and-exemptions-design.md).
- **Swap board ranking** — open swap postings are ordered by duty date only;
  full hierarchy-distance + match-quality ranking (described in the v2 spec) is
  not yet implemented.
- **Swap create UI** — the "create swap" modal asks for a raw assignment UUID;
  a duty-day picker showing the soldier's upcoming published assignments is
  a planned improvement.
- **`updated_at` is not auto-updating** — `SwapRequest` and `ShiftTemplate`
  (and other models) have `updated_at` with `server_default=now()` but no
  `ON UPDATE` trigger. Status-change operations do not bump the column.
- **One pre-existing failing test** —
  `tests/unit/test_authz.py::test_duty_manager_can_manage_assignments_and_scores_in_scope`
  fails on master (pre-dates v2; not introduced by it). Investigate before
  adding further RBAC tests against that area.

## Persistent memory

This repo has agent memory under
`.claude/projects/.../memory/` (indexed by `MEMORY.md`). It records non-obvious
facts: the Windows env setup, the branch/commit workflow, and the deferred
exemption edge case above. Consult it at the start of a session and update it
when you learn something durable and non-obvious that the code itself doesn't
record.
