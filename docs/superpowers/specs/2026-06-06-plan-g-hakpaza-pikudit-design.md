# Plan G — הקפצה פיקודית (Forced Reserve Call-Up)
**Date:** 2026-06-06  
**Issue:** #9

---

## Overview

A new commander tool for pulling a soldier from an active or upcoming duty and finding the best replacement. Used when a soldier is sick, or when an operational need requires reassigning someone mid-shift. The replacement is found by running a solver pass and ranked by multiple fairness criteria. The replacement commander (or duty manager) approves the substitution.

---

## Who can use this

- **Commanders** and **duty managers** only.
- Can initiate a הקפצה for any soldier in their own sub-hierarchy (their node and all nodes below).
- Replacement candidates are sourced from the **parent node** of the pulled soldier's node and all nodes below that parent (siblings included).
- Admins can initiate for any soldier in the unit.

---

## New page

Route: `/commander/hakpaza`  
Location in nav: under **מפקד** section.  
Hebrew label: **"הקפצה פיקודית"**

---

## Flow (5 steps)

### Step 1 — Select soldier to pull

- Autocomplete search box (`SoldierSearchAutocomplete`, already exists) scoped to the initiating commander's sub-hierarchy.
- After selecting a soldier, shows their upcoming/active assignments in a table (date range, duty type, location, status).
- User selects the specific duty assignment to pull them from.

### Step 2 — Select pull date

- If the selected assignment's `start_date` is in the future: only option is "מהתחלת המשמרת" — the entire assignment is vacated.
- If the assignment is currently active (today falls within `start_date`–`end_date`): a date picker appears, defaulting to today, allowing mid-shift pull.
  - Pull date must be ≥ today and ≤ `end_date`.
  - Label: **"תאריך הקפצה"** — the replacement soldier takes over from this date.
- Shows a summary: "חייל X ישוחרר מהמשמרת החל מ-DD.MM.YYYY. נותרו Y ימים למילוי."

### Step 3 — Find replacement candidates

- User clicks **"חפש מחליפים"** → the backend runs a solver pass.
- Backend endpoint: `POST /hakpaza/candidates`
  - Input: `{ pulled_assignment_id, pull_date, n: 8 }`
  - Runs a lightweight CP-SAT pass for a single slot (the remaining days of the vacated assignment).
  - Candidate pool: all soldiers in scope (parent node and below) minus the pulled soldier.
  - Solver respects: eligibility, approved constraints, density cap, existing assignments.
  - Returns top N feasible candidates, each with:
    - `soldier_id`, `full_name`, `hierarchy_node_name`
    - `hierarchy_distance`: integer (0 = same node, 1 = sibling node under same parent, 2 = cousin, etc.)
    - `current_score`: cumulative score
    - `score_per_day`: score rate
    - `recent_forced_callups`: count of הקפצה events in last 90 days, with recency decay (most recent = weight 1.0, each 30 days older = ×0.5)
    - `conflicts`: list of constraint/exemption conflicts (for display; these candidates are still eligible after relaxation if included)
    - `rank_reason`: short Hebrew string explaining why they rank here (e.g., "ניקוד נמוך, אותו מדור")

- Results shown as a sortable table with all the above columns.
- Default sort: by solver objective score (best fit first).
- Table header columns: שם / מדור / ניקוד / ניקוד ליום / הקפצות אחרונות / מרחק היררכי / סיבת דירוג

### Step 4 — Pick replacement + confirm

- Commander clicks a row to select the replacement soldier.
- A confirmation dialog: **"האם להקפיץ את [שם המחליף] לתורנות [סוג] מתאריך DD.MM.YYYY?"**
  - Shows: replacement soldier name, duty type, remaining days, score that will be added (days × score_per_day × forced_callup_multiplier).
- On confirm: POST creates a `ForcedCallup` record with status `pending`.

### Step 5 — Pending approval

- The **replacement soldier's direct commander** (or duty manager) receives a notification: **"בקשת הקפצה ממתינה לאישורך: [שם המחליף] לתורנות [סוג] מ-DD.MM.YYYY."**
- The notification links to an approval page showing the הקפצה details.
- On **approve**: original assignment is truncated (end_date set to pull_date - 1), new assignment created for replacement from pull_date to original end_date, status set to `approved`, both soldiers notified.
- On **reject**: status set to `rejected`, initiating commander notified, original assignment untouched.
- Duty manager can also approve/reject any pending הקפצה in their scope.

---

## Data model

### New table: `forced_callups`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `initiator_id` | UUID FK soldiers | Commander who initiated |
| `pulled_soldier_id` | UUID FK soldiers | Soldier being pulled |
| `original_assignment_id` | UUID FK duty_assignments | Assignment being vacated (partially or fully) |
| `pull_date` | Date | Start of replacement period |
| `replacement_soldier_id` | UUID FK soldiers | Chosen replacement |
| `replacement_assignment_id` | UUID FK duty_assignments | Created on approval, null until then |
| `status` | Enum | `pending` / `approved` / `rejected` |
| `approver_id` | UUID FK soldiers | Nullable, set on approval/rejection |
| `approved_at` | Timestamp | Nullable |
| `callup_multiplier` | Numeric | Default 2.0, from system settings |
| `created_at` | Timestamp | |

### System settings

- New setting key: `hakpaza.callup_multiplier` — default `2.0`. Configurable via the system settings page. Displayed as "מכפיל הקפצה פיקודית".
- Existing reserve call-up multiplier (`reserve.callup_multiplier`, default `1.3`) is unchanged.

---

## Scoring on approval

When a הקפצה is approved:
```
replacement_score = score_per_day × days_served × callup_multiplier
```
Where:
- `days_served = (original_end_date - pull_date).days + 1`
- `callup_multiplier` = value from system settings (default 2.0)
- The score is applied as a `ScoreAdjustment` record on the replacement soldier with reason: `"הקפצה פיקודית — [original_soldier_name]"`

The pulled soldier retains score only for days they actually served (`pull_date - 1 - start_date + 1` days). No penalty applied to the pulled soldier.

---

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /hakpaza/candidates` | Run solver, return top N candidates |
| `POST /hakpaza` | Create pending הקפצה request |
| `GET /hakpaza` | List הקפצה requests (filtered by scope) |
| `POST /hakpaza/{id}/approve` | Approve — splits assignment, creates replacement |
| `POST /hakpaza/{id}/reject` | Reject — notifies initiator |
| `GET /hakpaza/pending-count` | Count for nav badge |

---

## Nav badge

The commander nav badge (`pendingCount`) includes pending הקפצה approvals for the logged-in commander's soldiers.

---

## Recency decay formula for recent forced call-ups

```
decayed_callups = Σ (1.0 × 0.5^(days_since / 30)) for each callup in last 90 days
```

This means a הקפצה 10 days ago contributes ~0.79, one 30 days ago contributes 0.5, one 60 days ago contributes 0.25.

---

## Testing

- Commander can search and select a soldier from their sub-hierarchy only.
- Can select assignment for future duty (full vacate) or active duty (mid-shift pull date).
- `/hakpaza/candidates` returns ≤ N eligible candidates respecting solver constraints.
- Table shows all required columns; sortable.
- Creating a הקפצה sends notification to replacement commander.
- Approval truncates original assignment and creates replacement assignment correctly.
- Rejection leaves original assignment intact; initiator is notified.
- Replacement soldier receives correct score × forced_callup_multiplier.
- Duty manager can approve הקפצה not in their direct node but within their unit.
- Pending count appears in nav badge.
