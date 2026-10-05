# Frontend Dependency Remediation — Design

Date: 2026-10-05
Status: Draft for review
Audit baseline: `2e1515f7` (`dev`)

## Context

The frontend lockfile audit reported 17 vulnerable package entries across the full dependency tree and 7 in the production dependency tree. The report distinguished package advisories from confirmed browser exploitability. The installed React Router 6.30.4 is used in the app and is affected by open-redirect advisories. The installed Axios is a direct production dependency; `form-data` is pulled in through Axios and jsdom. Mermaid and DOMPurify are in the production tree, but `MermaidDiagram` has no source call sites. Ten additional findings are development/build dependencies; one remediation path requires a Tailwind major upgrade.

The server-side XLSX design owns removal of SheetJS. This design owns the remaining package risks and coordinates with that work so the final lockfile can reach a clean audit result.

## Goals

1. Remove the reachable React Router advisory risk with a supported patched version.
2. Upgrade Axios and vulnerable transitive dependencies without relying on forced, unreviewed lockfile overrides.
3. Remove unused Mermaid code and packages unless a current product requirement is found during implementation.
4. Resolve development/build dependency advisories, including the Tailwind major-version path, while preserving the app's Hebrew/RTL presentation.
5. Finish with current `npm audit` and `npm audit --omit=dev` results reviewed and no unexplained findings.

## Design

- Upgrade React Router to a supported release that fixes all currently reported advisories. The reviewed [GHSA-wrjc-x8rr-h8h6 advisory](https://github.com/advisories/GHSA-wrjc-x8rr-h8h6) lists versions before 7.18.0 as affected and 7.18.0 as patched; verify the latest fixed release when implementing. Treat this as a coordinated v7 migration, not a patch-only update. The stored-history link is separately removed by the untrusted-data design.
- Upgrade Axios to a release that clears current audit findings. Update jsdom or its dependency path as needed so `form-data` no longer appears in the vulnerable range. Confirm dependency paths with `npm explain` before choosing overrides.
- Remove `frontend/src/components/MermaidDiagram.tsx` and Mermaid from the app if implementation finds no hidden caller or approved feature requirement. Removing Mermaid should also remove its vulnerable transitive DOMPurify dependency. Do not retain an unused generated-SVG `innerHTML` sink.
- Update the remaining direct/transitive development dependencies to fixed compatible versions where possible. Handle Tailwind's required major upgrade as its own task within this workstream: migrate configuration and utilities to Tailwind 4, then validate representative desktop/mobile, dark-mode, Hebrew, and RTL screens. Do not use `npm audit fix --force` as a substitute for reviewing the migration.
- Rerun the full and production-only audit after the XLSX removal and every dependency change. If a no-fix advisory remains, first replace or remove the package. Any unavoidable exception must identify its exact package path, runtime reachability, impact, and compensating control rather than being silently waived.

## Scope

Expected changes include `frontend/package.json`, `frontend/package-lock.json`, React Router imports/navigation tests, `frontend/src/components/MermaidDiagram.tsx`, and Tailwind/PostCSS configuration and class usage only where required by the v4 migration. The XLSX package and export tests are handled by the server-side XLSX design.

## Acceptance criteria

1. The app runs on the selected patched React Router version with route, redirect, query, nested path, and navigation-history behavior covered.
2. Axios and its transitive tree contain no unresolved applicable advisories; `form-data` is no longer in an affected version range.
3. Mermaid and DOMPurify are absent unless a documented, reachable feature requirement is found; any retained diagram renderer has a separate reviewed data-safety boundary.
4. Tailwind 4 migration preserves representative Hebrew/RTL, responsive, dark-mode, and focus states.
5. `npm audit --omit=dev` and `npm audit` complete without unexplained findings after all remediation tracks are integrated.

## Non-goals

- Automatically accepting every `npm audit fix` result.
- Suppressing advisories solely because a package is transitive or development-only.
- Updating unrelated application dependencies that are not implicated in the audit.
