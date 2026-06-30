# Sub-Unit Quotas Within a Shift & Pluggable Excel Parsers
**Date:** 2026-06-30

---

## Overview

Allow a single `DutyShift` to require an exact number of soldiers from specific hierarchy nodes (e.g. ענף פוקוס gives 2, ענף אלומות gives 3, remaining slots unconstrained). The algorithm enforces these as hard constraints with an optional one-level-up relaxation. Quotas are settable via the shift edit UI and via Excel import.

This plan also introduces a **pluggable Excel parser architecture**: multiple parsers can target the same canonical JSON schema, so new human-readable Excel layouts can be supported by writing an isolated parser, without touching validation/import logic. This depends on and extends the import-sessions system from [Plan 1](2026-06-30-import-sessions-design.md).

---

## Data Model

### New table: `duty_shift_node_quotas`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `duty_shift_id` | UUID FK → duty_shifts, ON DELETE CASCADE | |
| `hierarchy_node_id` | UUID FK → hierarchy_nodes, ON DELETE RESTRICT | |
| `count` | integer | exact number of soldiers required from this node's subtree |

Constraints:
- Unique on `(duty_shift_id, hierarchy_node_id)`.
- `count >= 1`.
- Service-layer validation: sum of all `count` for a shift must be `≤ duty_shifts.required_count`. Not a DB constraint — enforced in `app/services/shifts.py` with a clear error.
- Slots not covered by any quota are unconstrained, same eligibility rules as today.

No changes to `DutyShift` itself.

---

## Algorithm

For each `DutyShift` with quota entries, the solver adds per-entry constraints:

- For `(node, count)`: `sum(assignments where soldier.hierarchy_node in subtree(node)) == count` (exact equality), using the existing subtree/scope resolution logic shared with `dm_scope`.
- Remaining `required_count - sum(quotas)` slots are filled by any eligible soldier per existing rules.

### Relaxation (one level up)

When a quota constraint is unsatisfiable for a given shift, the solver can relax it to the **parent node's subtree**: `assignments from subtree(node.parent) == count`. This permits siblings of the original node to fill the quota.

Two activation modes:
1. **Manual retry** — a toggle "אפשר הרחבת יחידה" in the shift retry / generate dialog. Solver first tries exact quotas; on failure for a given shift, retries with one-level-up relaxation for just that shift's unsatisfiable quotas.
2. **Auto-relax setting** — `auto_relax_node_quotas: bool`, configurable per algorithm run (and as a system default). When set, relaxation is applied automatically without a manual retry step.

Both modes record which shifts were relaxed and which node was substituted, surfaced in algorithm run results.

---

## Backend API & Service

- `GET /shifts/{id}` → adds `node_quotas: [{ hierarchy_node_id, node_name, count }]`.
- `PUT /shifts/{id}/quotas` → replaces the full quota list. Validates: sum ≤ `required_count`, nodes exist, no duplicates. Used by both manual edit and import apply.
- `ShiftFormModal` gets a new section "הקצאת מכסות ליחידות": add node + count rows, live running total vs. `required_count`, blocks save when over-allocated.
- Algorithm run config UI gets `auto_relax_node_quotas` checkbox; shift retry dialog gets the manual "אפשר הרחבת יחידה" toggle.
- Algorithm result detail view shows a badge on relaxed shifts with a tooltip naming original vs. substituted node.

---

## Pluggable Excel Parser Architecture

### Canonical schema (the only contract import logic depends on)

```python
class ImportNodeQuota(BaseModel):
    node_name: str
    count: int

class ImportSoldierRow(BaseModel):
    source_row: int
    personal_number: str
    full_name: str
    rank: str | None
    gender: str | None
    is_officer: bool | None
    hierarchy_node_name: str | None
    enrolled_at: str | None
    enlistment_date: str | None
    phone: str | None
    email: str | None

class ImportDutyShiftRow(BaseModel):
    source_row: int
    duty_type_name: str
    duty_location_name: str
    start_date: str
    end_date: str
    start_time: str | None
    end_time: str | None
    required_count: int
    node_quotas: list[ImportNodeQuota]
    notes: str | None

class ImportShiftTemplateRow(BaseModel):
    source_row: int
    name: str
    duty_type_name: str
    days_of_week: list[int]
    required_primary: int
    required_reserve: int

class ParsedImportData(BaseModel):
    soldiers: list[ImportSoldierRow]
    duty_shifts: list[ImportDutyShiftRow]
    shift_templates: list[ImportShiftTemplateRow]
    parser_id: str
    parser_warnings: list[str]
```

All resolution, scope-checking, quota-sum validation, and the session/preview machinery from Plan 1 operate exclusively on `ParsedImportData`. They have no knowledge of sheet names or cell layout.

### Parser interface

```python
class ImportParser(Protocol):
    id: str      # stable identifier, e.g. "v1_standard"
    label: str   # human-readable label for UI picker

    def detect(self, wb: Workbook) -> float:
        """Confidence score 0.0-1.0 that this parser matches the given workbook."""
        ...

    def parse(self, wb: Workbook) -> ParsedImportData:
        ...
```

- Parsers live under `backend/app/services/import_parsers/`, one file per parser (e.g. `v1_standard.py`).
- `PARSER_REGISTRY: dict[str, ImportParser]` collects all registered parsers.
- **Auto parser (default):** runs `detect()` across the registry, picks the highest score above a 0.5 threshold. If none qualifies, the upload is rejected with "unrecognized format" rather than guessing.
- `POST /import/sessions` accepts optional `parser_id`. If omitted, auto-detect runs. The chosen `parser_id` (explicit or detected) is stored on the session and reused by `/reparse`.
- Upload step UI gets a parser dropdown: "זיהוי אוטומטי" (default) + each registered parser's label — lets the user override when auto-detect picks wrong, or when two legacy formats are ambiguous.
- New Excel layouts are supported by writing a single new parser file implementing `detect`/`parse` and registering it — no other code changes required. This isolation is intentional: it's a self-contained task suitable for handing to Claude per new layout.

### `duty_shifts` sheet (primary import format for `v1_standard` parser)

| Column | Required | Notes |
|---|---|---|
| `duty_type_name` | Yes | matched by name |
| `duty_location_name` | Yes | matched by name |
| `start_date` | Yes | `dd.mm.yyyy` |
| `end_date` | Yes | `dd.mm.yyyy` |
| `start_time` | No | `HH:MM`, default `00:00` |
| `end_time` | No | `HH:MM`, default `23:59` |
| `required_count` | Yes | total slots |
| `node_quotas` | No | semicolon-separated `node_name:count`, e.g. `ענף פוקוס:2;ענף אלומות:3` |
| `notes` | No | |

`shift_templates` sheet remains supported (backward compat) but is secondary; it does not carry quotas. Quotas are added to generated shifts afterward via the edit UI or a follow-up `duty_shifts` import.

### Validation & resolution (within Plan 1's session/reparse machinery)

- Unresolved `duty_type_name` / `duty_location_name` → error row (existing pattern).
- Unresolved node in `node_quotas` → row flagged with inline "צור יחידה" / "שנה" buttons per quota-node (same UX as Plan 1's soldier node resolution); row stays in review until resolved or quota removed.
- Sum of quota counts > `required_count` → hard error row (data correctness issue in the source file — no inline fix).
- DM scope check: each quota node must be within the DM's managed subtree, AND the shift's duty_location/duty_type must be in scope. If any quota node in a row is out of scope while others are in scope, the **entire row** is `out_of_scope` — partial quota import within a single shift is not allowed, to preserve shift integrity. Admins are unrestricted.

---

## Alembic Migrations

1. Create table `duty_shift_node_quotas` as specified.
2. (No new enum needed — reuses existing hierarchy_nodes / duty_shifts tables.)

---

## Testing

- Create a shift with node quotas via API → sum validation rejects over-allocation.
- Algorithm run with quotas → solver produces exact counts per node for constrained slots, free assignment for unconstrained slots.
- Quota unsatisfiable + manual relax toggle off → shift reported unfillable, no relaxation applied.
- Quota unsatisfiable + manual relax toggle on → retry uses parent subtree, logs substitution.
- Auto-relax setting enabled → relaxation applied without manual retry; logged.
- Import `duty_shifts` sheet with valid quotas → preview shows shift with quota breakdown.
- Import row with unresolved quota node → inline create/resolve flips row to valid via reparse.
- Import row with quota sum > required_count → hard error, not inline-fixable.
- DM imports row with one in-scope and one out-of-scope quota node → entire row marked `out_of_scope`.
- Auto-detect parser picks correct parser among 2+ registered parsers for distinct sample files.
- Explicit `parser_id` override bypasses auto-detect and is persisted for reparse.
- Unrecognized file format → clear rejection, no silent misparse.
