---
name: release-dev-to-master
description: Use when promoting accumulated work on `dev` to `master` in this repo (justice) — a "release". Merges `dev` into `master` and updates frontend/CHANGELOG.md in the same step. Use whenever the human asks to release, ship, or merge dev to master.
---

# Release: dev → master

## Overview

`dev` is this repo's integration branch (see CLAUDE.md's Branch workflow).
Feature branches/worktrees merge into `dev` via the `merge-worktree-to-dev`
skill. This skill is the *other* half: promoting `dev` to `master`, which is
the one point where the changelog gets updated.

**Announce at start:** "I'm using the release-dev-to-master skill to promote dev to master."

**Core principle:** Verify tests on `dev` → merge into `master` → update
changelog as part of the same release → confirm before pushing.

## The Process

### Step 1: Verify Tests on `dev`

Run the project's test suite against `dev` before merging anywhere:

```bash
# Backend (from backend/, venv active)
pytest -q
# Frontend (from frontend/)
npm run typecheck
npm run lint
npm test
```

If something fails, stop and report it. Don't merge broken code into
`master`. If a failure is pre-existing and unrelated (e.g. a known flaky
test), verify that claim by reproducing it on `master`'s current tip before
trusting it, same as any other verification-before-completion check.

### Step 2: Locate `master` and `dev` Safely

Check whether `master` or `dev` is already checked out in another worktree
before touching either:

```bash
git worktree list
```

- If `master` isn't checked out anywhere, you can check it out in whichever
  worktree is convenient (including the `dev`-merge worktree itself).
- If it's checked out elsewhere with uncommitted changes, do not touch that
  worktree. Either operate from a worktree where neither branch is checked
  out, or ask the human how to proceed — never discard or stash another
  worktree's in-progress work to make room.

### Step 3: Merge `dev` into `master`

```bash
git checkout master
git pull   # if a remote exists and this is meant to track it
git merge dev

# Verify tests on the merged result
pytest -q   # backend
npm run typecheck && npm test   # frontend
```

If the merge isn't a clean fast-forward and produces conflicts, stop and
resolve them thoughtfully (never blindly take one side) or escalate to the
human if the conflict implies a real design decision.

### Step 4: Update the Changelog

Find the previous changelog entry's date/commit in `frontend/CHANGELOG.md`
(the most recent `## YYYY-MM-DD` heading). Reconstruct what shipped since
then:

```bash
git log --oneline <last-changelog-sha-or-tag>..master
```

Add a new `## YYYY-MM-DD` section (today's date) to the top of the log,
grouped into **Features**, **Fixes**, and **Chores** as appropriate — same
format as existing entries. Don't just dump commit subjects verbatim if
several commits form one user-visible change; summarize at the level a
reader of the changelog would want.

Commit this on `master` directly:

```bash
git add frontend/CHANGELOG.md
git commit -m "docs: update changelog YYYY-MM-DD"
```

This is the one sanctioned direct-to-`master` commit in this workflow (see
CLAUDE.md) — it's part of the release step itself, not a bypass of it.

### Step 5: Confirm Before Pushing

Pushing to `origin/master` (and `origin/dev` if it moved) is a shared,
visible action — confirm with the human before pushing, unless they already
explicitly asked for merge-and-push in the same request that triggered this
skill. If confirmed (or already requested):

```bash
git push origin master
git push origin dev   # only if dev's tip changed (e.g. a fast-forward merge target)
```

### Step 6: Report

Summarize: what was merged (commit range), the changelog entry added, test
results, and whether/what was pushed.

## Red Flags

**Never:**
- Skip test verification before merging `dev` into `master`
- Silently resolve merge conflicts by discarding one side without judgment
- Push without confirmation (unless explicitly pre-authorized in the same request)
- Disturb another worktree's checked-out branch or uncommitted work to free up `master`/`dev`
- Backdate or fabricate the changelog date — use the actual day of the release
- Bundle unrelated manual edits into the changelog commit

## Integration

- Upstream of this: `merge-worktree-to-dev` (how work gets onto `dev` in the first place).
- See CLAUDE.md's "Branch workflow" and "Changelog" sections for the policy this skill implements.
