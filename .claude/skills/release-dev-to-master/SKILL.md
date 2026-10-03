---
name: release-dev-to-master
description: Use when promoting accumulated work on `dev` to `master` in this repo (justice) — a "release". Merges `dev` into `master` and writes the user-facing frontend/CHANGELOG.md from docs/CHANGELOG-dev.md in the same step. Use whenever the human asks to release, ship, or merge dev to master.
---

# Release: dev → master

## Overview

`dev` is this repo's integration branch (see CLAUDE.md's Branch workflow).
Feature branches/worktrees merge into `dev` via the `merge-worktree-to-dev`
skill. This skill is the *other* half: promoting `dev` to `master`, which is
the one point where the user-facing changelog gets written (from the
developer changelog that `merge-worktree-to-dev` maintains).

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

### Step 4: Update the Changelogs

Two files change in the release commit: the user-facing
`frontend/CHANGELOG.md` (written here) and the developer log
`docs/CHANGELOG-dev.md` (just marked as released).

**4a. Gather sources.** Read the `## Unreleased` section of
`docs/CHANGELOG-dev.md` — the source of truth for what shipped. Cross-check
it against `git log --oneline <last-changelog-sha-or-tag>..master` (the
previous `## YYYY-MM-DD` heading in `frontend/CHANGELOG.md` marks the start)
and note any commits with no dev-changelog entry. Then read the plan/spec/
design docs listed on each entry's `Docs:` line (under `docs/superpowers/`)
to learn *why* each change was made.

**4b. Write the user-facing entry.** Add a new `## YYYY-MM-DD` section (today's
date) at the top of `frontend/CHANGELOG.md`, for the people who *use* the
app (soldiers, commanders, duty managers), not developers:

- Group under **Features** (new or changed behavior) and **Fixes**. Omit
  Chores — mention internal work only when users notice it (e.g. faster
  pages, under "Features" or "Fixes" as fits).
- One bullet per user-visible change, merging several commits/dev entries
  that form one change. Describe what users can now do or what now works,
  in plain language — no module names, endpoints, migrations, or test notes.
- For features and behavior changes whose reason isn't obvious, add the
  rationale as a short indented sub-line starting with "Why:", drawn from
  the plan/design docs. A simple bug fix gets no rationale.
- Entries with no user-visible effect are left out.

```markdown
- Duty managers can now replace a soldier directly from algorithm results.
  Why: rejecting a result forced a full re-run; replacing keeps the rest of
  the schedule stable.
```

**4c. Mark the dev changelog.** In `docs/CHANGELOG-dev.md`, rename
`## Unreleased` to `## YYYY-MM-DD (released)` and add a fresh empty
`## Unreleased` heading above it.

Commit both files on `master` directly:

```bash
git add frontend/CHANGELOG.md docs/CHANGELOG-dev.md
git commit -m "docs: update changelog YYYY-MM-DD"
```

This is the one sanctioned direct-to-`master` commit in this workflow (see
CLAUDE.md) — it's part of the release step itself, not a bypass of it.

Immediately cherry-pick this same commit onto `dev`, so `dev`'s changelogs
never drift from `master`'s (this merge is usually non-fast-forward —
`dev` keeps moving while a release is in flight — so the changelog commit
needs its own cherry-pick, not just a merge):

```bash
git checkout dev
git cherry-pick <changelog-commit-sha>
git checkout master   # or wherever you were before, for Step 5
```

If the cherry-pick conflicts (most likely in `docs/CHANGELOG-dev.md`, since
feature merges keep adding entries under `## Unreleased` on `dev`), resolve by
keeping both sides' content: entries added on `dev` after the release cut
stay under the new `## Unreleased`. Never drop content to force a clean apply.

### Step 5: Confirm Before Pushing

Pushing to `origin/master` and `origin/dev` is a shared, visible action —
confirm with the human before pushing, unless they already explicitly asked
for merge-and-push in the same request that triggered this skill. If
confirmed (or already requested):

```bash
git push origin master
git push origin dev
```

`dev` always needs a push here: either its tip moved (fast-forward target)
or it just gained the cherry-picked changelog commit above.

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
- Write developer-speak (modules, endpoints, migrations) in the user-facing changelog, or add "Why:" to a plain bug fix
- Bundle unrelated manual edits into the changelog commit
- Leave the changelog commit only on `master` — always cherry-pick it onto
  `dev` too (Step 4) so the two branches' changelogs never diverge

## Integration

- Upstream of this: `merge-worktree-to-dev` (how work gets onto `dev` in the first place).
- See CLAUDE.md's "Branch workflow" and "Changelog" sections for the policy this skill implements.
