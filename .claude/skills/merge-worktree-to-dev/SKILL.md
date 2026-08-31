---
name: merge-worktree-to-dev
description: Use when implementation work in a feature branch/worktree in this repo (justice) is complete and ready to integrate. Project-specific replacement for superpowers:finishing-a-development-branch — merges to `dev`, never directly to `master`.
---

# Merge Worktree to Dev

## Overview

This repo (`justice`) uses `dev` as the integration branch. Feature branches
and worktrees never merge directly into `master` — only into `dev`. `master`
only moves forward via the separate `release-dev-to-master` skill, which also
updates the changelog.

Same shape as superpowers:finishing-a-development-branch, with the base
branch fixed to `dev` instead of detected/guessed.

**Announce at start:** "I'm using the merge-worktree-to-dev skill to complete this work."

## The Process

### Step 1: Verify the Relevant Subset

Merging into `dev` runs a **scoped** subset of tests, not the full suite —
the full suite is expensive (~10 min per side) and only needs to run once,
at the `dev` → `master` release gate (see `release-dev-to-master`). Running
it again per feature merge is the redundant cost this step removes.

1. Get changed files relative to `dev`:
   `git diff --name-only $(git merge-base dev HEAD)..HEAD`
2. **Backend** (files under `backend/`):
   - If any changed file is core/shared-infra — `app/main.py`,
     `app/settings.py`, `app/db/`, `app/logging_config.py`,
     `app/error_logging.py`, `app/rate_limit.py`, `app/auth/`,
     `alembic/versions/`, `tests/conftest.py`, `tests/support/`,
     `pyproject.toml` — skip the mapping below and run the full fast suite:
     `pytest -q`.
   - Otherwise, for each changed non-test file, take its stem (e.g.
     `app/services/swaps.py` → `swaps`) and find matching test files under
     `backend/tests/` by name (`rg -l --glob 'test_*swap*.py' backend/tests`
     or equivalent — try the stem as-is and an obvious singular/plural
     variant). Union the matches across all changed files.
   - If a changed non-test file has no matching test file, or the matches
     span more than ~5 of the area markers listed in CLAUDE.md (algorithm,
     auth, hierarchy, duty, scoring, notifications, soldiers, misc), treat
     it as ambiguous and fall back to `pytest -q` instead of guessing.
   - Otherwise run `pytest -q <matched test files>`.
   - No backend files changed → skip backend tests entirely.
3. **Frontend** (files under `frontend/`):
   - Always run `npm run typecheck` and `npm run lint` in full — both are
     fast whole-project static checks, not the slow part.
   - Run `npx vitest run --changed dev` instead of the full `npm test`
     (Vitest's own git-diff-aware selection, using its module graph rather
     than path guessing). If it errors (e.g. `dev` not fetched locally),
     fall back to `npm test -- --run`.
   - No frontend files changed → skip frontend tests entirely.
4. When in doubt about whether a change is "core" or a mapping is
   reliable, prefer the full-suite fallback for that side — this step
   trades exhaustiveness for speed, not correctness.

If the scoped run fails, stop and report the failures — don't proceed to
Step 2 until they're fixed or the failure is confirmed pre-existing and
unrelated (verify with a quick reproduction on `dev` before trusting that
claim).

### Step 2: Detect Environment

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
```

| State | Menu | Cleanup |
|-------|------|---------|
| `GIT_DIR == GIT_COMMON` (normal repo) | Standard 4 options | No worktree to clean up |
| `GIT_DIR != GIT_COMMON`, named branch | Standard 4 options | Provenance-based (see Step 6) |
| `GIT_DIR != GIT_COMMON`, detached HEAD | Reduced 3 options (no merge) | No cleanup (externally managed) |

### Step 3: Base Branch

Always `dev` — not `master`, and not guessed via `git merge-base`. If the
feature branch was cut from somewhere other than `dev` (e.g. an old branch
predating this workflow), say so explicitly and confirm with the human
before merging, since the history may not be a clean fast-forward-friendly
merge onto `dev`.

### Step 4: Present Options

**Normal repo and named-branch worktree — present exactly these 4 options:**

```
Implementation complete. What would you like to do?

1. Merge back to dev locally
2. Push and create a Pull Request (targeting dev)
3. Keep the branch as-is (I'll handle it later)
4. Discard this work

Which option?
```

**Detached HEAD — present exactly these 3 options:**

```
Implementation complete. You're on a detached HEAD (externally managed workspace).

1. Push as new branch and create a Pull Request (targeting dev)
2. Keep as-is (I'll handle it later)
3. Discard this work

Which option?
```

Don't add explanation — keep options concise. Never offer "merge to master"
here; that's out of scope for this skill.

### Step 5: Execute Choice

#### Option 1: Merge Locally (to dev)

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
```

If `dev` is already checked out somewhere else (another worktree/session),
do not force a second checkout — either merge from within the feature
worktree itself (checking out `dev` there only if `dev` isn't checked out
elsewhere) or ask the human how they want to proceed. Never disturb another
active worktree's checked-out branch or uncommitted changes to do this merge.

```bash
git checkout dev   # wherever it's safe to do so
git pull
git merge <feature-branch>

# Re-run the same scoped subset from Step 1 on the merged result before
# treating the merge as done — a clean feature-branch merge rarely needs
# more than that; reach for the full suite only if the merge itself
# touched core/shared infra in a way Step 1 didn't already cover.
<scoped test command from Step 1>
```

Then: Cleanup worktree (Step 6), then delete the feature branch:

```bash
git branch -d <feature-branch>
```

Push `dev` only if the human asked for it explicitly (pushing is a shared,
visible action — confirm first per this project's normal push conventions).

#### Option 2: Push and Create PR (base: dev)

```bash
git push -u origin <feature-branch>
gh pr create --base dev ...
```

**Do NOT clean up worktree** — the human needs it alive to iterate on PR feedback.

#### Option 3: Keep As-Is

Report: "Keeping branch <name>. Worktree preserved at <path>."
**Don't cleanup worktree.**

#### Option 4: Discard

**Confirm first, requiring the typed word `discard`:**
```
This will permanently delete:
- Branch <name>
- All commits: <commit-list>
- Worktree at <path>

Type 'discard' to confirm.
```

If confirmed, cleanup worktree (Step 6), then:
```bash
git branch -D <feature-branch>
```

### Step 6: Cleanup Workspace

Only for Options 1 and 4. Same provenance rules as
superpowers:finishing-a-development-branch: only remove worktrees under
`.worktrees/` or `worktrees/` (ones this workflow created); leave
harness-owned workspaces alone.

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
git worktree remove "$WORKTREE_PATH"
git worktree prune
```

## Red Flags

**Never:**
- Merge a feature branch directly into `master` — always `dev`
- Proceed with failing tests (unless a pre-existing, verified-unrelated failure)
- Guess a test subset for a change you flagged as core/shared infra, or for
  a changed file with no matching test file — fall back to the full suite
  for that side instead
- Delete work without typed `discard` confirmation
- Force-push without explicit request
- Remove a worktree before confirming the merge to `dev` succeeded
- Clean up worktrees you didn't create
- Check out `dev` (or any branch) in a way that disturbs another active
  worktree's in-progress, uncommitted work

## Integration

- Updates the changelog: never — that only happens in `release-dev-to-master`.
- See also: `release-dev-to-master` (the `dev` → `master` promotion step),
  superpowers:using-git-worktrees, superpowers:finishing-a-development-branch
  (the generic version this project-specific skill replaces).
