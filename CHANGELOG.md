# Changelog

## 2026-06-27

### Features
- **Shifts table "תת יחידה אחראית" column** — new column after "מיקום" shows which sub-unit(s) are eligible for each shift ("כולם" when unrestricted). Supports a collapsible hierarchy tree filter in the column header.
- **`HierarchyNodeFilter` component** — reusable collapsible tree picker for filtering by hierarchy nodes, used in the shifts table column filter.
- **`customColumnFilter` on `DataTable`** — new `ColDef` field for fully-controlled column filter dropdowns: provide a React node for the popup content and a predicate function for row filtering, replacing the built-in exact-match checkbox list.
- **Collapsible `SubHierarchySelector`** — each node now has a ▾/▸ expand/collapse toggle; the tree starts fully expanded. Used in the shift, shift template, and duty type forms.

### Fixes
- **`ShiftFormModal` scroll on mobile** — modal container now has `max-h-[90vh] overflow-y-auto` so tall forms are scrollable on small screens.
- **`DismissalModal` date range picker** — replaced broken "snap to nearest endpoint" heuristic with a two-phase model (click FROM then click TO). The old logic made it geometrically impossible to select a range ending near the start of a long shift. Phase starts at "to" so the first click on a pre-filled full-range naturally narrows the end date.

### Features
- **Post-solve swap pass** — after CP-SAT solving, a greedy swap pass transfers individual duties between over- and under-loaded soldiers to reduce effort imbalance without re-solving. Runs on every decomposition mode (interleaved, effort-rounds, calendar, monolithic).
- **Duty-count progress reporting** — progress bar now advances proportionally to duties solved rather than batches completed, giving smoother and more accurate progress indication. A distinct "מאזן עומסים…" label appears during the swap pass (at 94 %).

### Chores
- **Effort formula: cumulative weighted ratio** — changed effort formula to use cumulative weighted ratio for better convergence.
- **`useDutyManagerPortfolio` hook** — shared hook extracted from `HierarchyTree` and `TeamHierarchyPage` (worktree merged; master uses `usePortfolioDialog` naming).
- **SIGABRT debug handler removed** — removed temporary SIGABRT signal handler from algorithm job runner.
- **`dev.ps1` process cleanup** — more reliable stale process killing on dev server startup.

---

## 2026-06-26

### Features
- **Transparency export respects all active filters** — "ייצוא לאקסל" button moved directly above each table (soldiers and sub-units) and now exports only the currently visible/filtered/sorted rows instead of the full unfiltered dataset. Button is disabled when zero rows are visible.
- **Client-side Excel export** — new `ExcelExportButton` component generates `.xlsx` files in the browser using SheetJS, replacing the old backend-driven download endpoints.
- **Planning > Export page migrated to client-side** — `ExportPage` now computes the full unfiltered export locally (DFS-ordered by unit for soldiers, shallowest-first for sub-units) without calling the backend.
- **Hierarchy scope picker on duty forms** — duty types, shift templates, and shifts now have an eligible-units picker (hierarchy scope) so a duty can be restricted to a specific sub-tree of the hierarchy.
- **Algorithm partial results on cancel** — salvages partial solver results when a batch job is cancelled and retries interrupted jobs automatically.

### Fixes
- **DataTable infinite re-render loop** — `onVisibleRowsChange` callback previously created a new array on every render, causing `useEffect` to fire every render and loop indefinitely. Fixed by memoizing visible rows on actual filter/sort state and reading column defs via a ref.
- **Fairness: thin-quarter denominator** — inflate the denominator by pending workload before computing each soldier's effort share, preventing score inflation for soldiers with very few active days in the quarter.
- **Fairness: run workload in effort-share denominator** — the algorithm's own duty workload is now fed into the effort-share denominator so the solver accounts for the current run's load when computing fairness.
- **Sub-tree eligibility in candidate listing** — candidate filtering is now sub-tree-aware and correctly excludes unassigned soldiers.
- **ExportPage `dfsOrder`** — fixed parent-child hierarchy construction to build from `parent_id` map instead of relying on the unpopulated `children` field returned by the flat API.

### Removed
- Backend transparency export endpoints (`GET /transparency/export`, `GET /transparency/sub-units/export`) and their `openpyxl`-based helpers — superseded by client-side export.
- Frontend `downloadTransparencyExport` / `downloadSubUnitsExport` API functions.

---

## 2026-06-25

### Features
- **RBAC capability model** — replaced role-string checks throughout the frontend with real `is_commander` / `is_duty_manager` capability flags exposed on the `/auth/me` response. Gates nav tabs, approval widgets, duty-config management, algorithm page, explanation redaction, hakpaza flow, and private-field visibility on actual DB-backed capabilities instead of the display-only role label.
- **Role label derived from real capabilities** — `Soldier.role` is now computed from the soldier's actual node assignments and DM scope rather than a stored string; displaced commanders are handled correctly.
- **Lexicographic range tie-break** — algorithm solver uses a lexicographic range tie-break for cross-batch fairness.
- **Backend & bot crash logging** — backend and Telegram bot now persist startup/shutdown/crash markers to rotating log files outside the container; `dev.ps1` supervisor auto-restarts on crash.
- **Crash-detecting supervisor in dev.ps1** — detects backend/bot crashes and automatically restarts the affected process.

### Fixes
- **DM scope derived from real data** — duty-manager scope is computed from actual DB assignments regardless of the role display label.
- **bot restart loop** — `run_dev_bot.py` no longer restarts on a clean (deliberate) bot exit.
- **`run_dev_bot.py` kills stale supervisors** — cleans up `run_dev_bot.py` parent processes in addition to bot children.
- **Explanation redaction gated on real DM capability** — previously gated on role string.
- **Hakpaza initiate/approve gated on real capability flags**.

### Removed
- Unused role-override endpoint (`PATCH /soldiers/{id}/role`) — role is now derived, never set directly.

---

## 2026-06-24

### Features
- **Gimelim merged into DismissalModal** — gimelim (reserve call-up) flow is now a mode toggle inside the unified DismissalModal rather than a standalone dialog.
- **Hierarchy level types** — hierarchy node levels are now managed from the database (`hierarchy_level_types` table) instead of being hardcoded. Admin/duty-managers can create, rename, reorder, and delete level types. The hierarchy tree, level dropdowns, and node-edit dialog all drive from the DB-backed types.
- **EditNodeDialog** — replaces the old RenameNodeDialog; includes a level dropdown driven by DB level types and an inline level-type manager.
- **Algorithm batch results UI improvements** — run status, assigned/total coverage display, and assignment page cleanup.

### Fixes
- **Level type management widened to duty_managers**.
- **AddRootNodeDialog** — guarded against rendering before level types load.
- **`change_node_level` children-rank boundary** — test coverage added and edge case fixed.

---

## 2026-06-23

### Features
- **Algorithm run badges** — colored status badges (pending / running / done / failed) on the algorithm runs section header and on the Planning nav tab/sheet item. Cancelled jobs are excluded from badge counts.
- **Private fields access control** — soldier private fields, constraint reasons, and exemption types are redacted from admins and unauthorized viewers; DMs see only soldiers in their scope. Frontend shows "מידע פרטי" placeholder for redacted values.
- **Algorithm job FK and score columns** — `duty_assignments` table gains `algorithm_job_id` and `score` columns; a fast-path query uses the FK to load proposals for a given job.
- **Approvals page embed** — pending swap, field-update, and exemption responses embed soldier/node names and files server-side, eliminating N+1 fetches.
- **Unit calendar "כלל המסגרת" option** — added full-corps view option to the unit calendar filter.
- **Cover ineligibility tooltip** — shift cover button shows the ineligibility reason as a disabled-button tooltip.
- **Assigned/total coverage in algorithm job list**.
- **Success message after clear all assignments**.
- **`can_see_private` capability** added to authz, gating all private-field access.

### Fixes
- **Clear all assignments** — bulk UPDATE instead of per-row ORM loop; shifts table refreshes after operation.
- **Exclusive end-date display** — end dates now display and fire overlap detection correctly.
- **15 miscellaneous bug fixes** — shift tests, nav badge computation, algorithm run section improvements.

### Performance
- **Batch-load** soldiers/nodes in pending field-updates, swap, and exemption handlers.
- **Parallel ApprovalsPage** initial load.
- **Embed exemption files** in pending exemption response.

---

## 2026-06-22

### Features
- **Project renamed to Justice** — package names, database name, API title, ICS UID domain, docs, and CLAUDE.md all updated from "callofduty2 / Call of Duty 2" to "justice / Justice".
- **Saturation-aware relaxation restart** — solver detects saturation clusters (groups of duties that compete for the same small candidate pool) and explains them in the Issues tab; suppresses misleading "add soldiers" recommendation when the real constraint is a scheduling conflict.
- **Retroactive gimelim release** — `preview_gimelim` and `commit_gimelim` now accept a backdated `from_date` so a soldier can be released from a duty that already started.
- **Batch time limit raised** — default `batch_time_limit_seconds` increased from 60 to 120.

### Fixes
- **Relaxation restart** — restarts the whole component from scratch on relaxation instead of patching residual state.
- **Gimelim audit log** — records the actual gimelim call-up `from_date`, not the shift start date.
- **Exclusive end-date misfiring** — single-day duties using exclusive end dates no longer misfire as overlapping.
- **Migration revision collision** — resolved a migration revision collision between the shift-templates branch and the main branch.

---

## 2026-06-21

### Features
- **Duty day calculation fix** — effort score now uses `score_days` (actual duty-day windows) instead of calendar days touched, preventing inflation for multi-day duties that span non-duty days.
- **Shift start/end times** — `duty_shifts` and `duty_assignments` gain `start_time` / `end_time` columns; times are copied from the shift template onto generated shifts and from the source shift onto gimelim-promoted assignments.
- **Solver block score uses score_days** — the CP-SAT solver's per-block effort score uses `score_days` for consistency with the transparency score.
- **`--fair` seed flag** — `generate_seeds` CLI accepts `--fair` to skip exemptions and constraints for a clean fairness baseline.

### Fixes
- **Count-spread tiebreaker weight raised** — fixes a duty-concentration bug where multiple duties were assigned to the same soldier when spreading was possible.
- **Day-weight division by zero** — guarded against zero-day assignments in the per-day effort weight calculation.
- **Exclusive end-date in tests** — corrected single-day duty fixtures to use exclusive end dates consistently.
- **HH:MM format validation** — manually-created shift times are validated for correct format.

---

## 2026-06-20

### Features
- **Shared searchable Combobox** — new `Combobox` component with keyboard navigation and ARIA roles, wired into: hierarchy node, rank, exemption type, duty type, location, candidate, reserve assignment, and batch-filter dropdowns across all major forms.
- **Shift template auto-roll until-date** — shift templates gain an `auto_roll_until` date field; the roll-horizon generator clamps generation to this date. A live instance count picker is shown when configuring it.
- **Solver input snapshot** — `algorithm_jobs` stores a snapshot of solver inputs at run time so `export-inputs` can replay a completed job's exact inputs.

### Fixes
- **Export-inputs replay** — fixed so it uses the snapshotted inputs from the completed job rather than recomputing.
- **Required-field guard** — restored a required-field guard lost when the select's `required` attribute was dropped.
- **Soldier profile edit form** — removed erroneous `sm:grid-cols-2` making the form two-column on small screens.

---

## 2026-06-19

### Docs
- Design spec and implementation plan for shared searchable Combobox component.
- Design spec and implementation plan for shift template auto-roll until-date.
