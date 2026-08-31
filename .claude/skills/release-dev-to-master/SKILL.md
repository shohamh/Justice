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

**Core principle:** Merge `dev` into `master` first → run the full suite
*once*, on the merged result → only then update the changelog and push.

**Why the full suite runs here, not before the merge:** each feature merge
into `dev` (via `merge-worktree-to-dev`) already verified a fast, scoped
subset of tests relevant to that change. Running the expensive full
backend + frontend suite (~10 min per side) a second time on `dev` before
this merge would just repeat work already covered by the accumulation of
those scoped checks. This skill is the one place the full suite runs,
catching anything the scoped per-feature checks couldn't (cross-feature
interactions, drift between what was scoped and what actually changed) —
which is also exactly why a failure here means recover-and-retry (Step 3a)
rather than "stop and fix on `dev` directly": the full suite is the release
gate, not a pre-check to satisfy before merging.

### Step 1: Locate `master` and `dev` Safely

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

### Step 2: Merge `dev` into `master`

```bash
git checkout master
git pull   # if a remote exists and this is meant to track it
git merge dev
```

If the merge isn't a clean fast-forward and produces conflicts, stop and
resolve them thoughtfully (never blindly take one side) or escalate to the
human if the conflict implies a real design decision.

### Step 3: Run the Full Suite on Merged `master`

This is the release's one full-suite gate:

```bash
# Backend (from backend/, venv active)
pytest -q
# Frontend (from frontend/)
npm run typecheck
npm run lint
npm test
```

All green → continue to Step 4 (changelog).

#### Step 3a: If the Full Suite Fails — Sync, Fix, Retry

Do not push `master` in this state, and do not fix the problem directly on
`master` or `dev`. Recover by looping back through the normal branch
workflow:

1. **Sync `dev` to the merged `master`.** `master` now holds everything
   `dev` had plus this merge commit; bring `dev` up to the same tip
   (typically a fast-forward, since `dev` hasn't moved):
   ```bash
   git checkout dev
   git merge master   # fast-forward if dev hasn't diverged
   ```
   This makes `dev` an exact reflection of the (currently failing) release
   candidate, so the fix is developed against the real failure, not a stale
   `dev`.
2. **Fix the failure** on a normal feature branch/worktree cut from this
   updated `dev` — same as any other change. Re-run the specific test(s)
   that failed in Step 3, not just the scoped subset, to confirm the fix
   actually addresses them.
3. **Merge the fix into `dev`** via `merge-worktree-to-dev` as usual (its
   scoped-subset check applies normally here).
4. **Restart this skill from Step 2** — merge the now-fixed `dev` into
   `master` again and re-run the full suite. Repeat until Step 3 is green.

A failure here is a real defect the scoped per-feature checks missed, not
routine noise — do not loosen Step 3 into a "quick partial check" as a
shortcut past a repeat failure; find and fix the actual cause.

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
- Skip the full-suite run on merged `master` (Step 3) — it's the release's
  only full-suite gate; nothing upstream substitutes for it
- Push `master` (or update the changelog) while Step 3 is red
- Fix a Step 3 failure directly on `master` or `dev` — always sync `dev` to
  the merged `master` first, then fix via a normal feature branch/worktree
  merged back through `merge-worktree-to-dev` (Step 3a)
- Silently resolve merge conflicts by discarding one side without judgment
- Push without confirmation (unless explicitly pre-authorized in the same request)
- Disturb another worktree's checked-out branch or uncommitted work to free up `master`/`dev`
- Backdate or fabricate the changelog date — use the actual day of the release
- Bundle unrelated manual edits into the changelog commit

## Integration

- Upstream of this: `merge-worktree-to-dev` (how work gets onto `dev` in the first place).
- See CLAUDE.md's "Branch workflow" and "Changelog" sections for the policy this skill implements.
