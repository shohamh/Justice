# Commander Dashboard (דף מפקד) — Design

**Date:** 2026-06-01
**Status:** Draft for review

---

## 1. Purpose

A dedicated dashboard for the `commander` role that consolidates all commander-relevant views into a single page. Duty managers and admins already have their own pages; this is specifically for commanders managing their sub-hierarchy.

**Target user:** A soldier with the `commander` role, who commands any node in the hierarchy tree. The dashboard is auto-scoped to that commander's node and all descendants.

**Relationship to existing pages:** The commander dashboard is a separate new page (`/command-dashboard`), accessible from the sidebar. Existing pages (team, transparency, unit-calendar, etc.) remain accessible to commanders.

---

## 2. Page Layout

Dashboard grid layout (not tabbed). Responsive 2-column grid.

### Top row — summary cards (3 compact cards, ~200px each)

| Card | Data | Click action |
|------|------|-------------|
| Approvals pending | Count of pending swap/exemption/field-update requests in subtree | Scrolls to / opens Approvals Hub panel |
| Upcoming duties (7 days) | Count of duties next week + unfilled gaps | Scrolls to / opens Upcoming Snapshot panel |
| Alerts | Count of active exceptions (score threshold, consecutive days, exemption expiry) | Scrolls to / opens Alerts panel |

Below the top row, the detailed panels are arranged vertically (collapsible sections or scroll).

---

## 3. Panels

### Panel 1 — Sub-hierarchy Calendar

Reuses the existing `UnitCalendar` component, auto-scoped to the commander's hierarchy node (no node selector). Shows all duties for the commander's subtree. Same interactions (shift detail panel, dismissal modal, etc.) as the existing unit calendar — just filtered by scope.

**Backend:** Existing calendar API with `node_id` parameter set to the commander's node.

### Panel 2 — Soldier List (tree + table, merged with status)

A single panel with two toggleable views:

**Tree view:** Existing `HierarchyTree` component, scoped to the commander's subtree. Each soldier node shows a **status badge** (colored dot or icon):
- Active (green) — no exemptions, not left
- Exempt (yellow) — has active exemptions (course, medical, personal)
- In reserve (blue) — actively serving in reserve
- Left (gray) — `left_at` is set, soft-deleted

**Table view:** Existing `DataTable` with soldiers filtered to the subtree. Columns:
- Personal number, full name, role, hierarchy node, status, transparency score, normalized score, enrolled date
- Actions: Edit profile (opens existing `UnifiedSoldierModal`), reset password, remove

**Status derivation:** Computed from existing data — `left_at`, active `exemptions`, reserve assignments. No new database fields needed.

### Panel 3 — Internal Fairness Dashboard

Shows fairness distribution within the commander's subtree:

- **Distribution chart:** Histogram of soldiers' normalized scores — x-axis: score buckets, y-axis: soldier count.
- **Stats summary:** Mean, median, min, max, standard deviation of normalized scores.
- **Outliers:** Soldiers significantly above/below the mean (configurable threshold, default ±2σ), flagged with a link to their profile.

**Data source:** Existing scoring/transparency API, filtered to the commander's subtree nodes.

### Panel 4 — External Fairness Dashboard

Comparison against adjacent subtrees:

- **Peer comparison:** Same distribution stats (mean, stddev, median) shown for the commander's subtree alongside sibling nodes at the same hierarchy level.
- **Wider context:** Optionally compare against the entire branch/department or unit average.
- **Ranking:** Where the commander's subtree ranks among peers on fairness metrics (best/worst mean normalized score, lowest/highest variance).

**Data source:** Scoring API aggregated at each hierarchy node level.

### Panel 5 — Entries & Exits (Pool Management)

A table of soldiers in the subtree with management actions:

- **Grant global exemption:** Exempt a soldier from all duties for a reason (e.g., קורס חיצוני, רפואי, personal). Uses existing exemption system (`is_global: true`). Start/end dates required.
- **Move to different unit:** Change `hierarchy_node_id` to reassign the soldier to a different subtree within the unit. Opens a node selector.
- **Release from unit:** Soft-delete (set `left_at`).

The table shows each soldier's current exemptions with expiry dates. Exemptions nearing expiry (within 7 days) are highlighted.

### Panel 6 — Duty Potential / Statistics

Statistical overview of soldier types and qualifications in the subtree:

- **Counts by soldier type:** חובה (mandatory) vs קבע (career), by rank, by role.
- **Counts by qualification:** בוגרי בהד"1 (Bahad1 graduates), by duty type eligibility requirements.
- **Comparison mode:** Same counts for peer subtrees or unit-wide, so the commander can contextualize their subtree's composition.
- **Duty burden metrics:** Total duty days assigned vs available headcount, utilization rate per duty type.

### Panel 7 — Approvals Hub

Unified feed of all pending requests requiring the commander's approval within their subtree:

- Each request shows: soldier name, request type (swap, exemption, field update), summary, timestamp.
- Accept / reject buttons inline.
- Requests are grouped by category with count badges.
- After approval/rejection, the request is removed from the feed and the count updates.

**Backend:** Aggregates from existing approval endpoints (`getPendingCount`, `getPendingExemptionCount`, `getPendingFieldUpdateCount`), filtered to the commander's subtree instead of the entire unit.

### Panel 8 — Upcoming Duty Snapshot

Compact 7-day timeline showing upcoming duties in the subtree:

- Each day: which soldiers have duties and what type.
- Gaps (shifts with no assignee) highlighted in red with a "!" indicator.
- Total headcount assigned per day shown as a small number.
- Clicking a day or duty opens the calendar at that date.

### Panel 9 — Alerts & Exceptions

Automatically surfaced edge cases:

- Soldiers falling below a minimum normalized score threshold (configurable, default -3.0).
- Soldiers with too many consecutive duty days (configurable, default 5).
- Exemptions expiring within 7 days.
- Duties with missing coverage (no assignee) within the next 48 hours.
- Newly enrolled soldiers with no duties assigned yet (optional).

Each alert shows: description, affected soldier(s), severity (info/warning/critical), and a link to take action.

---

## 4. Backend changes

### New API endpoints (or parameter additions to existing ones):

| Endpoint | Purpose |
|----------|---------|
| `GET /api/command-dashboard/summary` | Aggregated counts for the top-row cards (approvals, upcoming, alerts) for a given node |
| `GET /api/command-dashboard/soldiers?node_id=X` | List soldiers in subtree with computed status |
| `GET /api/command-dashboard/fairness/internal?node_id=X` | Fairness distribution stats for the subtree |
| `GET /api/command-dashboard/fairness/external?node_id=X` | Peer comparison fairness stats |
| `GET /api/command-dashboard/potential?node_id=X` | Eligibility/qualification counts |
| `GET /api/command-dashboard/alerts?node_id=X` | Active exceptions for the subtree |
| `GET /api/command-dashboard/upcoming?node_id=X&days=7` | Upcoming duty snapshot |

Alternatively, parameters can be added to existing endpoints to support subtree scoping.

### Authorization:
- Each endpoint verifies the requesting soldier is the commander of the specified node (or an admin).
- A helper function `get_subtree_node_ids(node_id)` returns all descendant node IDs (already exists in hierarchy service).

---

## 5. Frontend changes

### New route:
- `/command-dashboard` — accessible to `commander` role (and `admin`).
- New nav link in `Layout.tsx` sidebar for commanders.

### New components:
- `CommandDashboardPage.tsx` — main page layout, orchestrates all panels.
- `SummaryCards.tsx` — top row of 3 compact cards.
- `FairnessChart.tsx` — histogram/distribution chart (can use a charting library or simple CSS bars).
- `ApprovalsFeed.tsx` — unified approvals list with inline actions.
- `UpcomingSnapshot.tsx` — 7-day timeline component.
- `AlertsPanel.tsx` — list of active exceptions.
- `DutyPotentialPanel.tsx` — eligibility/qualification counts.

### Modified components:
- `UnitCalendar.tsx` — accept `nodeId` prop for subtree scoping (remove node selector when provided).
- `HierarchyTree.tsx` — accept `nodeId` prop for subtree scoping.
- `DataTable.tsx` — no changes needed.

---

## 6. Algorithm page — duty restriction by sub-hierarchy

Part of the existing algorithm page (`/duty-management` or algorithm tab):

### UI:
- For each duty type or shift, a new "Eligible sub-hierarchy" section.
- A tree selector (multi-select) allowing the user to pick one or more hierarchy nodes whose soldiers are eligible.
- Default: all nodes eligible (current behavior).
- If nodes are selected, only soldiers in those nodes (and their descendants) can be assigned to that duty type/shift.

### Backend:
- New field in `DutyType.requirements` JSONB: `eligible_node_ids: string[] | null`.
- New field on `duty_shifts` (optional override): `eligible_node_ids: string[] | null`.
- In the CP-SAT algorithm model, filter eligible soldiers per duty block based on these constraints.
- In manual assignment UI, the assignee dropdown is filtered to eligible soldiers.

### Authorization:
- Only `duty_manager` and `admin` can set eligible sub-hierarchies.
- Commanders can view but not modify.

---

## 7. Out of scope

- Commander notes / journal (per-soldier notes).
- Handoff / succession tooling.
- Notifications (SMS/push) for alerts.
