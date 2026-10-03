# Dev Changelog

Developer-facing log of everything merged into `dev`, written for people working
on this codebase (modules touched, migrations, API/schema changes, config,
gotchas). Entries are added by the `merge-worktree-to-dev` skill; the
user-facing `frontend/CHANGELOG.md` is derived from this file at release time
by `release-dev-to-master`.

## Unreleased

### Split dev and user-facing changelogs (`chore/split-changelogs`, 2026-10-04)
Docs: none
- `merge-worktree-to-dev` skill: new Step 5 adds an entry here (under `## Unreleased`) for every merge/PR into `dev`; later steps renumbered.
- `release-dev-to-master` skill: Step 4 now writes the user-facing `frontend/CHANGELOG.md` from this file plus the plan/spec docs on each `Docs:` line (Features/Fixes, "Why:" for non-obvious changes), then renames `## Unreleased` to the release date.
- `CLAUDE.md`: "Changelog" section replaced by "Changelogs" describing both files.
- Type: chore
