# Shift Potential-Split Quotas
**Date:** 2026-07-03

---

## Overview

Duty managers can already set per-hierarchy-node exact quotas on a shift (`duty_shift_node_quotas`, added in [Plan 1](2026-06-30-subunit-shift-quotas-design.md)) via manually-entered rows in `ShiftFormModal`. This adds a way to **auto-populate those rows proportionally** across a chosen parent node's direct children, weighted by each child's total soldier count ("potential", same figure shown in the commander dashboard's potential tab). It also adds a lowest-common-ancestor (LCA) label for quota sanity-checking, and a one-click way to re-run the algorithm for the edited shift.

This is additive to the existing quota system — it only changes how `quotaRows` get populated in the UI and adds one new read-only backend endpoint. No changes to `duty_shift_node_quotas` schema or the algorithm's constraint handling.

---

## 1. System setting

New key: `shifts.auto_split_node_quotas` (boolean, default `false`).

- Stored in the existing `system_settings` key-value table (no migration needed — it's schemaless JSONB).
- Admin-editable via the existing `/admin/system-settings` GET/PUT endpoints and admin settings UI (add one checkbox row).
- Added to `_PUBLIC_KEYS` in `backend/app/routes/public_settings.py` so any authenticated user (including DMs) can read it via `GET /settings/public`.

When `true`, `ShiftFormModal` auto-runs the split (see §3) whenever its trigger condition holds, instead of requiring a manual button click.

---

## 2. Backend: split-preview endpoint

```
GET /shifts/quota-split-preview?parent_node_id=<uuid>&required_count=<int>
```

- Router: `backend/app/routes/shifts.py`.
- Auth: `require_duty_manager_or_admin`, then `authorize(session, user, Action.SHIFT_MANAGE, target_node=None)` — identical to the existing `PUT /shifts/{id}/quotas` route. `SHIFT_MANAGE` is a DM-global action (see `_DM_GLOBAL_ACTIONS` in `authz.py`), so no extra per-node scope check is needed beyond "is a DM or admin".
- Validation:
  - `parent_node_id` must exist → 404 `not_found` otherwise.
  - `required_count` must be `>= 1` → 400 `invalid_required_count` otherwise (mirrors `CreateShiftRequest.required_count`'s `ge=1`).
  - Parent must have at least one direct child (`HierarchyNode.parent_id == parent_node_id`) → 400 `no_child_nodes` otherwise.
- Computation (new helper, e.g. `app/services/shift_quotas.py::compute_potential_split`):
  1. For each direct child, compute `weight` = count of active soldiers (`left_at IS NULL`) whose `hierarchy_node.path_ids` contains the child's id (subtree total). Reuse/extract the subtree-membership logic already used by `commander_dashboard.py::_soldiers_in_nodes` into a small shared helper (e.g. move to `app/services/hierarchy_helpers.py` or similar) rather than duplicating the query — both call sites need "soldiers whose node is under this node's subtree".
  2. If all weights are 0 (no soldiers anywhere in the subtree), split evenly instead of by proportion (equal integer shares, remainder distributed by node order) so the endpoint never returns an all-zero, unusable split.
  3. Otherwise allocate `required_count` proportionally to weight using the **largest-remainder method**: `share_i = floor(required_count * weight_i / total_weight)`, then distribute the `required_count - sum(share_i)` leftover units one-by-one to the children with the largest fractional remainder (ties broken by child order). This guarantees `sum(share_i) == required_count` exactly.
  4. Children with `share_i == 0` are still returned (so the DM can see them and see why), but rows with `count == 0` are dropped before being handed to `quotaRows` on the frontend (the existing quota UI/validation assumes `count >= 1` per row, matching the `ck_shift_node_quota_count_positive` DB constraint).
- Response model:
  ```python
  class QuotaSplitEntry(BaseModel):
      hierarchy_node_id: uuid.UUID
      node_name: str
      count: int
      weight: int  # total soldiers, for the DM's own sanity check

  class QuotaSplitPreviewOut(BaseModel):
      entries: list[QuotaSplitEntry]
  ```
- Pure read — does not touch `duty_shift_node_quotas`. Saving still goes through the existing `PUT /shifts/{id}/quotas`.

---

## 3. Frontend: `ShiftFormModal`

**Split / recompute button**

- New button, label `t("shifts.quotas_split_by_potential")` ("חלק לפי פוטנציאל לתתי מסגרות"), rendered next to the existing quota-rows header.
- Visible/enabled only when `scopeNodeIds.length === 1` and `count >= 1`.
- On click: `GET /shifts/quota-split-preview` with `parent_node_id = scopeNodeIds[0]`, `required_count = count`. On success, **replaces** `quotaRows` wholesale with the non-zero entries (mapped to `{hierarchy_node_id, count}`). This same click, run again later (e.g. after headcounts changed or `count` changed), is the "recompute" action — no separate button.
- On error (400/404 from above), show the existing inline `error` banner with a translated message per error code.

**Auto mode**

- On mount, fetch `GET /settings/public` (or reuse an existing settings hook/context if one already loads public settings app-wide — check `frontend/src/api` for an existing public-settings fetch before adding a new one) to read `shifts.auto_split_node_quotas`.
- When that flag is `true`, a `useEffect` watching `[scopeNodeIds, count]` calls the same split logic automatically (debounced ~400ms) whenever `scopeNodeIds.length === 1` and `count >= 1`, overwriting `quotaRows`. Manual edits to `quotaRows` after that point are preserved until the effect fires again (i.e. until the DM changes the node selection or `count`).
- When auto-populated, show a small hint text under the quota rows: `t("shifts.quotas_auto_split_hint")` ("מכסות חושבו אוטומטית לפי פוטנציאל").

**LCA label**

- When `quotaRows.length >= 2`, compute the longest common prefix of `path_ids` (from the already-fetched `fetchTree()` node list — extend `flattenNodes`/`nodeOptions` to retain `path_ids`, or look them up from the raw tree) for the nodes referenced in `quotaRows`.
- Render `t("shifts.quotas_common_ancestor", { name })` ("מסגרת אם משותפת: {{name}}") above the quota rows list. If the only common ancestor is the tree root, still show the root's name (no special-casing — it's accurate).
- Purely client-side, no backend call.

**Rerun-algorithm button**

- New button, label `t("shifts.rerun_algorithm")` ("הרץ אלגוריתם"), rendered near the quota section, visible only when `existing` is set (editing a saved shift — a new unsaved shift has no `shift_id` to scope a job to).
- On click: build `SolverSettings` the same way `AlgorithmRunForm` does today (its `DEFAULT_SETTINGS` constant merged with `getAlgorithmDefaults()`), then `submitJob({ shift_ids: [existing.id], mode: "shadow", settings })`.
- On success, show a lightweight confirmation (reuse the modal's existing `error`/status banner pattern for a success message, or a toast if the app has a toast pattern already — check before adding a new UI primitive) with the returned job id. Does not navigate away or close the modal.

---

## Error Handling

- Split-preview 400/404s surface as translated inline errors in the modal, matching the existing `quotaOverAllocated` error pattern.
- Rerun-algorithm failures (e.g. `submitJob` rejecting) surface the same way `AlgorithmRunForm` already surfaces submit failures.
- No new failure modes for the existing quota save path (`PUT /shifts/{id}/quotas`) — its sum-vs-required_count validation already guards against a bad split leaving `quotaRows` over-allocated (can't happen here since split always sums to exactly `required_count`, but manual edits after an auto/manual split can still over-allocate, and the existing `quotaOverAllocated` check already blocks save in that case).

---

## Testing

Backend (`backend/app/routes/tests/` or `backend/app/services/tests/`, pytest marker `duty` or `hierarchy`):
- Even split across N children with equal weights.
- Uneven split (largest-remainder correctness — sums to exactly `required_count`).
- Child with zero soldiers gets `count == 0` (dropped by frontend, but present in the raw response with `weight == 0`).
- All children zero-weight → even fallback split.
- Parent with no children → 400 `no_child_nodes`.
- Unknown `parent_node_id` → 404.
- Non-DM/non-admin caller → 403.

Frontend (`ShiftFormModal.test.tsx`):
- Split button hidden when 0 or 2+ nodes selected in `scopeNodeIds`; visible with exactly 1.
- Clicking split button populates `quotaRows` from a mocked API response.
- Clicking again (recompute) overwrites previous rows.
- Auto mode (mocked `shifts.auto_split_node_quotas = true`) populates rows without a click when a single scope node + valid count are present.
- LCA label appears and shows correct common-ancestor name for a 2+-row quota set; absent for 0-1 rows.
- Rerun-algorithm button hidden for new (unsaved) shifts; visible for existing shifts and calls `submitJob` with `shift_ids: [existing.id]`.
