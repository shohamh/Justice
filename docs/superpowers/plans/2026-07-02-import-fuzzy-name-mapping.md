# Import Fuzzy Name Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users resolve unmatched Excel names during import review by selecting from a fuzzy-sorted combobox of existing DB records, with per-row or name-wide mappings that persist and are applied on reparse.

**Architecture:** Mappings are stored in `user_selections._name_mappings` (keyed by `by_name` and `by_row`). The backend applies them during reparse before the normal name-lookup, so resolved rows immediately flip to `new`. The frontend fetches all duty types and hierarchy nodes on mount, ranks candidates with `fuse.js`, and prompts the user to apply a pick globally (by name) or just to the current row.

**Tech Stack:** Python (SQLAlchemy, pytest), TypeScript (React, fuse.js, axios via existing `api` client)

---

## File Map

| File | Change |
|------|--------|
| `backend/app/services/import_sessions.py` | Add `name_mappings` args to resolvers; pass `user_selections` from `reparse_session` |
| `backend/app/services/tests/test_import_sessions_service.py` | Add tests for mapping resolution on reparse |
| `frontend/src/api/importSessions.ts` | Add `NameMappings`, `Selections`, `ShiftTemplateRow` types; update `saveSelections`; add two lookup fetch functions |
| `frontend/src/components/FuzzyPickerCombobox.tsx` | New inline searchable combobox sorted by fuzzy score |
| `frontend/src/pages/ImportSessionReviewPage.tsx` | Fetch lookup data; replace "שנה" button with combobox; add `pendingPick` prompt; wire up save+reparse flow |

---

## Task 1: Backend — apply name mappings during reparse

**Files:**
- Modify: `backend/app/services/import_sessions.py`

- [ ] **Step 1: Update `_resolve_soldiers` signature to accept mapping dicts**

  Replace the function signature and add mapping resolution before the existing name lookup. The full modified function body:

  ```python
  def _resolve_soldiers(
      session: Session,
      data: ParsedImportData,
      actor: Soldier,
      node_by_name: dict[str, str] | None = None,
      node_by_row: dict[str, str] | None = None,
  ) -> list[dict]:
      node_by_name = node_by_name or {}
      node_by_row = node_by_row or {}
      existing_by_pn = {
          s.personal_number: s for s in session.execute(select(Soldier)).scalars()
      }
      nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

      out = []
      for row in data.soldiers:
          errors: list[str] = []
          if not row.personal_number:
              errors.append("חסר מספר אישי")
          if not row.full_name:
              errors.append("חסר שם מלא")

          node = None
          if row.hierarchy_node_name:
              row_key = f"soldiers:{row.source_row}"
              mapped_id = node_by_row.get(row_key) or node_by_name.get(row.hierarchy_node_name)
              if mapped_id:
                  node = session.get(HierarchyNode, uuid.UUID(mapped_id))
              if node is None:
                  node = nodes_by_name.get(row.hierarchy_node_name)
              if node is None:
                  errors.append(f"יחידה לא מזוהה '{row.hierarchy_node_name}'")

          existing = existing_by_pn.get(row.personal_number) if row.personal_number else None

          if errors:
              action = "error"
          elif existing is not None:
              action = "update"
          else:
              action = "new"

          if action != "error" and node is not None:
              if actor.role != "admin" and not is_node_in_actor_scope(
                  session=session, actor=actor, node_id=node.id
              ):
                  action = "out_of_scope"

          out.append({
              "row": row.source_row,
              "action": action,
              "errors": errors,
              "personal_number": row.personal_number,
              "full_name": row.full_name,
              "rank": row.rank,
              "gender": row.gender,
              "is_officer": row.is_officer,
              "hierarchy_node_id": str(node.id) if node is not None else None,
              "hierarchy_node_name": row.hierarchy_node_name,
              "enrolled_at": row.enrolled_at,
              "enlistment_date": row.enlistment_date,
              "phone": row.phone,
              "email": row.email,
              "existing_id": str(existing.id) if existing is not None else None,
          })
      return out
  ```

- [ ] **Step 2: Update `_resolve_duty_shifts` signature and add mapping resolution**

  Replace the function:

  ```python
  def _resolve_duty_shifts(
      session: Session,
      data: ParsedImportData,
      actor: Soldier,
      dt_by_name: dict[str, str] | None = None,
      dt_by_row: dict[str, str] | None = None,
      node_by_name: dict[str, str] | None = None,
      node_by_row: dict[str, str] | None = None,
  ) -> list[dict]:
      dt_by_name = dt_by_name or {}
      dt_by_row = dt_by_row or {}
      node_by_name = node_by_name or {}
      node_by_row = node_by_row or {}
      duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
      locations_by_name = {loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()}
      nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

      out = []
      for row in data.duty_shifts:
          errors: list[str] = []

          duty_type = None
          if row.duty_type_name:
              row_key = f"duty_shifts:{row.source_row}"
              mapped_id = dt_by_row.get(row_key) or dt_by_name.get(row.duty_type_name)
              if mapped_id:
                  duty_type = session.get(DutyType, uuid.UUID(mapped_id))
              if duty_type is None:
                  duty_type = duty_types_by_name.get(row.duty_type_name)
          if duty_type is None:
              errors.append(f"סוג תורנות לא מזוהה '{row.duty_type_name}'")

          location = locations_by_name.get(row.duty_location_name) if row.duty_location_name else None
          if location is None:
              errors.append(f"מיקום תורנות לא מזוהה '{row.duty_location_name}'")

          if not row.start_date:
              errors.append("חסר תאריך התחלה")
          if not row.end_date:
              errors.append("חסר תאריך סיום")

          quota_dicts = []
          quota_total = 0
          for q in row.node_quotas:
              quota_key = f"duty_shifts:{row.source_row}:{q.node_name}"
              mapped_node_id = node_by_row.get(quota_key) or node_by_name.get(q.node_name)
              node = None
              if mapped_node_id:
                  node = session.get(HierarchyNode, uuid.UUID(mapped_node_id))
              if node is None:
                  node = nodes_by_name.get(q.node_name)
              quota_dicts.append({
                  "node_name": q.node_name,
                  "node_id": str(node.id) if node is not None else None,
                  "count": q.count,
                  "resolved": node is not None,
              })
              quota_total += q.count

          if quota_total > row.required_count:
              errors.append(
                  f"סה\"כ מכסות ({quota_total}) גדול מהכמות הנדרשת ({row.required_count})"
              )

          action = "error" if errors else "new"

          if action == "new" and actor.role != "admin":
              resolved_node_ids = [
                  uuid.UUID(qd["node_id"]) for qd in quota_dicts if qd["resolved"]
              ]
              for node_id in resolved_node_ids:
                  if not is_node_in_actor_scope(session=session, actor=actor, node_id=node_id):
                      action = "out_of_scope"
                      break

          out.append({
              "row": row.source_row,
              "action": action,
              "errors": errors,
              "duty_type_name": row.duty_type_name,
              "resolved_duty_type_id": str(duty_type.id) if duty_type is not None else None,
              "duty_location_name": row.duty_location_name,
              "resolved_duty_location_id": str(location.id) if location is not None else None,
              "start_date": row.start_date,
              "end_date": row.end_date,
              "start_time": row.start_time,
              "end_time": row.end_time,
              "required_count": row.required_count,
              "node_quotas": quota_dicts,
              "notes": row.notes,
          })
      return out
  ```

- [ ] **Step 3: Update `_resolve_shift_templates` signature and add mapping resolution**

  Replace the function:

  ```python
  def _resolve_shift_templates(
      session: Session,
      data: ParsedImportData,
      dt_by_name: dict[str, str] | None = None,
      dt_by_row: dict[str, str] | None = None,
  ) -> list[dict]:
      dt_by_name = dt_by_name or {}
      dt_by_row = dt_by_row or {}
      duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}

      out = []
      for row in data.shift_templates:
          errors: list[str] = []
          duty_type = None
          if row.duty_type_name:
              row_key = f"shift_templates:{row.source_row}"
              mapped_id = dt_by_row.get(row_key) or dt_by_name.get(row.duty_type_name)
              if mapped_id:
                  duty_type = session.get(DutyType, uuid.UUID(mapped_id))
              if duty_type is None:
                  duty_type = duty_types_by_name.get(row.duty_type_name)
          if duty_type is None:
              errors.append(f"סוג תורנות לא מזוהה '{row.duty_type_name}'")

          action = "error" if errors else "new"

          out.append({
              "row": row.source_row,
              "action": action,
              "errors": errors,
              "name": row.name,
              "duty_type_name": row.duty_type_name,
              "resolved_duty_type_id": str(duty_type.id) if duty_type is not None else None,
              "days_of_week": row.days_of_week,
              "required_primary": row.required_primary,
              "required_reserve": row.required_reserve,
          })
      return out
  ```

- [ ] **Step 4: Update `_resolve_and_score` to extract and pass mappings**

  Replace the function:

  ```python
  def _resolve_and_score(
      session: Session,
      data: ParsedImportData,
      actor: Soldier,
      selections: dict | None = None,
  ) -> dict:
      nm = (selections or {}).get("_name_mappings", {})
      dt_by_name  = nm.get("duty_type", {}).get("by_name", {})
      dt_by_row   = nm.get("duty_type", {}).get("by_row", {})
      node_by_name = nm.get("hierarchy_node", {}).get("by_name", {})
      node_by_row  = nm.get("hierarchy_node", {}).get("by_row", {})
      return {
          "soldiers": _resolve_soldiers(session, data, actor, node_by_name, node_by_row),
          "duty_shifts": _resolve_duty_shifts(session, data, actor, dt_by_name, dt_by_row, node_by_name, node_by_row),
          "shift_templates": _resolve_shift_templates(session, data, dt_by_name, dt_by_row),
          "parser_id": data.parser_id,
          "parser_warnings": data.parser_warnings,
      }
  ```

- [ ] **Step 5: Pass `user_selections` to `_resolve_and_score` in `reparse_session`**

  In `reparse_session`, change the call on the line `parsed_state = _resolve_and_score(...)`:

  ```python
  parsed_state = _resolve_and_score(session, data, actor, selections=import_session.user_selections)
  ```

  `create_session` does not need this change (selections are always empty at creation time).

- [ ] **Step 6: Commit**

  ```bash
  git add backend/app/services/import_sessions.py
  git commit -m "feat: apply name mappings from user_selections during import reparse"
  ```

---

## Task 2: Backend tests for name mapping resolution

**Files:**
- Modify: `backend/app/services/tests/test_import_sessions_service.py`

- [ ] **Step 1: Add test — duty type resolved via `by_name` mapping on reparse**

  Add after the existing tests:

  ```python
  def test_reparse_resolves_duty_type_via_by_name_mapping(admin_session):
      from decimal import Decimal
      dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
      loc = DutyLocation(name=f"loc_{_uid()}")
      admin_session.add(loc)
      admin_session.flush()
      admin_session.commit()

      # Excel uses a different name than the DB
      wb = _wb_with_duty_shifts([
          ["excel_alias", loc.name, "15.06.2024", "16.06.2024", "", "", 5, "", ""],
      ])
      admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

      sess = create_session(
          admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
      )
      # Initially unresolved
      assert sess.parsed_state["duty_shifts"][0]["action"] == "error"

      # Apply by_name mapping
      set_selections(admin_session, session_id=sess.id, selections={
          "_name_mappings": {
              "duty_type": {"by_name": {"excel_alias": str(dt.id)}}
          }
      })
      admin_session.commit()

      sess = reparse_session(admin_session, session_id=sess.id, actor=admin)
      row = sess.parsed_state["duty_shifts"][0]
      assert row["action"] == "new"
      assert row["resolved_duty_type_id"] == str(dt.id)
  ```

- [ ] **Step 2: Add test — duty type resolved via `by_row` mapping, `by_row` beats `by_name`**

  ```python
  def test_reparse_by_row_overrides_by_name_for_duty_type(admin_session):
      from decimal import Decimal
      dt_name = create_duty_type(admin_session, name=f"dt_name_{_uid()}", score_per_day=Decimal("1.00"))
      dt_row  = create_duty_type(admin_session, name=f"dt_row_{_uid()}",  score_per_day=Decimal("1.00"))
      loc = DutyLocation(name=f"loc_{_uid()}")
      admin_session.add(loc)
      admin_session.flush()
      admin_session.commit()

      wb = _wb_with_duty_shifts([
          ["excel_alias", loc.name, "15.06.2024", "16.06.2024", "", "", 5, "", ""],
      ])
      admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
      sess = create_session(
          admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
      )

      row_number = sess.parsed_state["duty_shifts"][0]["row"]

      set_selections(admin_session, session_id=sess.id, selections={
          "_name_mappings": {
              "duty_type": {
                  "by_name": {"excel_alias": str(dt_name.id)},
                  "by_row":  {f"duty_shifts:{row_number}": str(dt_row.id)},
              }
          }
      })
      admin_session.commit()

      sess = reparse_session(admin_session, session_id=sess.id, actor=admin)
      assert sess.parsed_state["duty_shifts"][0]["resolved_duty_type_id"] == str(dt_row.id)
  ```

- [ ] **Step 3: Add test — hierarchy node resolved via `by_name` mapping on reparse**

  ```python
  def test_reparse_resolves_hierarchy_node_via_by_name_mapping(admin_session):
      node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
      admin_session.commit()

      wb = _wb_with_soldiers([
          ["1234567", "Test Soldier", "", "", "", "excel_node_alias", "", "", "", ""],
      ])
      admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
      sess = create_session(
          admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
      )
      assert sess.parsed_state["soldiers"][0]["action"] == "error"

      set_selections(admin_session, session_id=sess.id, selections={
          "_name_mappings": {
              "hierarchy_node": {"by_name": {"excel_node_alias": str(node.id)}}
          }
      })
      admin_session.commit()

      sess = reparse_session(admin_session, session_id=sess.id, actor=admin)
      row = sess.parsed_state["soldiers"][0]
      assert row["action"] == "new"
      assert row["hierarchy_node_id"] == str(node.id)
  ```

- [ ] **Step 4: Add test — node quota resolved via `by_row` key `duty_shifts:<row>:<node_name>`**

  ```python
  def test_reparse_resolves_quota_node_via_by_row_mapping(admin_session):
      from decimal import Decimal
      dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
      loc = DutyLocation(name=f"loc_{_uid()}")
      node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
      admin_session.add(loc)
      admin_session.flush()
      admin_session.commit()

      wb = _wb_with_duty_shifts([
          [dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 5, "excel_quota_node:3", ""],
      ])
      admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
      sess = create_session(
          admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
      )
      row_number = sess.parsed_state["duty_shifts"][0]["row"]

      set_selections(admin_session, session_id=sess.id, selections={
          "_name_mappings": {
              "hierarchy_node": {
                  "by_row": {f"duty_shifts:{row_number}:excel_quota_node": str(node.id)}
              }
          }
      })
      admin_session.commit()

      sess = reparse_session(admin_session, session_id=sess.id, actor=admin)
      quotas = sess.parsed_state["duty_shifts"][0]["node_quotas"]
      assert quotas[0]["resolved"] is True
      assert quotas[0]["node_id"] == str(node.id)
  ```

- [ ] **Step 5: Add test — stale mapped UUID falls back to name lookup**

  ```python
  def test_reparse_stale_mapped_uuid_falls_back_to_name_lookup(admin_session):
      from decimal import Decimal
      dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
      loc = DutyLocation(name=f"loc_{_uid()}")
      admin_session.add(loc)
      admin_session.flush()
      admin_session.commit()

      wb = _wb_with_duty_shifts([
          [dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 5, "", ""],
      ])
      admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
      sess = create_session(
          admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
      )

      # Map to a non-existent UUID — should fall back to name lookup (which succeeds here)
      set_selections(admin_session, session_id=sess.id, selections={
          "_name_mappings": {
              "duty_type": {"by_name": {dt.name: str(uuid.uuid4())}}
          }
      })
      admin_session.commit()

      sess = reparse_session(admin_session, session_id=sess.id, actor=admin)
      # Falls back to name lookup → still resolves
      assert sess.parsed_state["duty_shifts"][0]["resolved_duty_type_id"] == str(dt.id)
  ```

- [ ] **Step 6: Run the new tests**

  ```bash
  cd backend
  pytest app/services/tests/test_import_sessions_service.py -v -q
  ```

  Expected: all new tests pass.

- [ ] **Step 7: Commit**

  ```bash
  git add backend/app/services/tests/test_import_sessions_service.py
  git commit -m "test: name mapping resolution on import reparse"
  ```

---

## Task 3: Frontend — types, API functions, and `FuzzyPickerCombobox`

**Files:**
- Modify: `frontend/src/api/importSessions.ts`
- Create: `frontend/src/components/FuzzyPickerCombobox.tsx`

- [ ] **Step 1: Install fuse.js**

  ```bash
  cd frontend
  npm install fuse.js
  ```

- [ ] **Step 2: Add types and API functions to `frontend/src/api/importSessions.ts`**

  Add the following at the top of the file, after the existing imports:

  ```typescript
  export interface NameMappings {
    duty_type?: {
      by_name?: Record<string, string>;
      by_row?: Record<string, string>;
    };
    hierarchy_node?: {
      by_name?: Record<string, string>;
      by_row?: Record<string, string>;
    };
  }

  export interface Selections {
    _name_mappings?: NameMappings;
    [group: string]: Record<string, string> | NameMappings | undefined;
  }
  ```

  Add `ShiftTemplateRow` interface after `DutyShiftRow`:

  ```typescript
  export interface ShiftTemplateRow extends RowBase {
    name: string;
    duty_type_name: string;
    resolved_duty_type_id: string | null;
    days_of_week: number[];
    required_primary: number;
    required_reserve: number;
  }
  ```

  Update `ParsedState` to include `shift_templates`:

  ```typescript
  export interface ParsedState {
    soldiers: SoldierRow[];
    duty_shifts: DutyShiftRow[];
    shift_templates: ShiftTemplateRow[];
    parser_id: string;
    parser_warnings: string[];
  }
  ```

  Update `SessionDetail.user_selections` type:

  ```typescript
  export interface SessionDetail {
    id: string;
    status: string;
    filename: string;
    parsed_state: ParsedState;
    user_selections: Selections;
    created_links: Record<string, string[]>;
  }
  ```

  Update `saveSelections` to accept `Selections`:

  ```typescript
  export async function saveSelections(
    id: string,
    selections: Selections,
  ): Promise<void> {
    await api.patch(`/import/sessions/${id}/selections`, { selections });
  }
  ```

  Add lookup fetch functions at the bottom of the file:

  ```typescript
  export async function listDutyTypesForImport(): Promise<{ id: string; name: string }[]> {
    return (
      await api.get<{ id: string; name: string }[]>("/import-lookup/duty-types")
    ).data;
  }

  export async function listNodesForImport(): Promise<{ id: string; name: string }[]> {
    const nodes = (
      await api.get<{ id: string; name: string }[]>("/import-lookup/hierarchy")
    ).data;
    return nodes.map((n) => ({ id: n.id, name: n.name }));
  }
  ```

- [ ] **Step 3: Create `frontend/src/components/FuzzyPickerCombobox.tsx`**

  ```tsx
  import Fuse from "fuse.js";
  import { useEffect, useMemo, useRef, useState } from "react";

  interface Candidate {
    id: string;
    name: string;
  }

  interface Props {
    unresolvedName: string;
    candidates: Candidate[];
    onPick: (id: string) => void;
    disabled?: boolean;
  }

  export default function FuzzyPickerCombobox({
    unresolvedName,
    candidates,
    onPick,
    disabled,
  }: Props) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState(unresolvedName);
    const containerRef = useRef<HTMLDivElement>(null);

    const fuse = useMemo(
      () =>
        new Fuse(candidates, {
          keys: ["name"],
          threshold: 0.5,
          includeScore: true,
        }),
      [candidates],
    );

    const results = useMemo(() => {
      if (!query.trim()) return candidates.slice(0, 8);
      return fuse
        .search(query)
        .slice(0, 8)
        .map((r) => r.item);
    }, [fuse, query, candidates]);

    useEffect(() => {
      function handler(e: MouseEvent) {
        if (
          containerRef.current &&
          !containerRef.current.contains(e.target as Node)
        ) {
          setOpen(false);
        }
      }
      document.addEventListener("mousedown", handler);
      return () => document.removeEventListener("mousedown", handler);
    }, []);

    return (
      <div ref={containerRef} className="relative inline-block">
        <input
          className="border rounded px-2 py-0.5 text-sm w-44 dark:bg-gray-700 dark:border-gray-600 text-red-600"
          value={query}
          disabled={disabled}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setOpen(true)}
          placeholder={unresolvedName}
          dir="rtl"
        />
        {open && results.length > 0 && (
          <ul
            className="absolute z-50 bg-white dark:bg-gray-800 border dark:border-gray-600 rounded shadow-lg mt-1 w-56 max-h-48 overflow-y-auto text-sm"
            dir="rtl"
          >
            {results.map((c) => (
              <li
                key={c.id}
                className="px-3 py-1.5 hover:bg-indigo-50 dark:hover:bg-gray-700 cursor-pointer"
                onMouseDown={(e) => {
                  e.preventDefault();
                  setOpen(false);
                  onPick(c.id);
                }}
              >
                {c.name}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }
  ```

- [ ] **Step 4: Commit**

  ```bash
  cd frontend
  npm run typecheck
  git add frontend/src/api/importSessions.ts frontend/src/components/FuzzyPickerCombobox.tsx
  git commit -m "feat: add fuzzy picker combobox and import name mapping types"
  ```

---

## Task 4: Frontend — integrate into `ImportSessionReviewPage`

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`

- [ ] **Step 1: Add new imports at the top of `ImportSessionReviewPage.tsx`**

  Add to the existing import from `"../api/importSessions"`:

  ```typescript
  import {
    type SessionDetail,
    type ConfirmSessionResult,
    type RowBase,
    type Selections,
    type ShiftTemplateRow,
    getSession,
    reparseSession,
    saveSelections,
    confirmSession,
    listDutyTypesForImport,
    listNodesForImport,
  } from "../api/importSessions";
  import FuzzyPickerCombobox from "../components/FuzzyPickerCombobox";
  ```

  Remove the `AddRootNodeDialog` and `renameNode` imports — the rename flow is replaced by the combobox.

  Remove:
  ```typescript
  import AddRootNodeDialog from "../components/AddRootNodeDialog";
  import { renameNode } from "../api/hierarchy";
  ```

- [ ] **Step 2: Add `PendingPick` interface and new state**

  After the existing `type ActionValue` declaration, add:

  ```typescript
  interface PendingPick {
    pickedId: string;
    kind: "duty_type" | "hierarchy_node";
    excelName: string;
    rowKey: string;       // by_row key for "just this row" option
    sameNameCount: number;
  }

  interface LookupItem {
    id: string;
    name: string;
  }
  ```

  Inside `ImportSessionReviewPage`, add new state after the existing state declarations:

  ```typescript
  const [allDutyTypes, setAllDutyTypes] = useState<LookupItem[]>([]);
  const [allNodes, setAllNodes] = useState<LookupItem[]>([]);
  const [pendingPick, setPendingPick] = useState<PendingPick | null>(null);
  ```

  Update the `selections` state type from `Record<string, Record<string, string>>` to `Selections`:

  ```typescript
  const [selections, setSelections] = useState<Selections>({});
  ```

- [ ] **Step 3: Fetch lookup data on mount**

  Add a `useEffect` after the existing `useEffect` that calls `load()`:

  ```typescript
  useEffect(() => {
    void (async () => {
      const [dts, nodes] = await Promise.all([
        listDutyTypesForImport(),
        listNodesForImport(),
      ]);
      setAllDutyTypes(dts);
      setAllNodes(nodes);
    })();
  }, []);
  ```

- [ ] **Step 4: Add `applyMapping` and `handlePick` functions**

  Add these before the existing `handleReparse` function:

  ```typescript
  async function applyMapping(
    scope: "all" | "row",
    pick: PendingPick,
  ) {
    setPendingPick(null);
    if (!id) return;
    const nm = (selections._name_mappings ?? {}) as NonNullable<Selections["_name_mappings"]>;
    const kindKey = pick.kind === "duty_type" ? "duty_type" : "hierarchy_node";
    const kindEntry = nm[kindKey] ?? {};

    let next: Selections;
    if (scope === "all") {
      next = {
        ...selections,
        _name_mappings: {
          ...nm,
          [kindKey]: {
            ...kindEntry,
            by_name: { ...(kindEntry.by_name ?? {}), [pick.excelName]: pick.pickedId },
          },
        },
      };
    } else {
      next = {
        ...selections,
        _name_mappings: {
          ...nm,
          [kindKey]: {
            ...kindEntry,
            by_row: { ...(kindEntry.by_row ?? {}), [pick.rowKey]: pick.pickedId },
          },
        },
      };
    }

    setSelections(next);
    await saveSelections(id, next);
    await handleReparse();
  }

  function handlePick(
    kind: "duty_type" | "hierarchy_node",
    excelName: string,
    rowKey: string,
    pickedId: string,
  ) {
    if (!detail) return;
    const { soldiers, duty_shifts, shift_templates } = detail.parsed_state;

    let sameNameCount = 0;
    if (kind === "hierarchy_node") {
      sameNameCount +=
        soldiers.filter((r) => !r.hierarchy_node_id && r.hierarchy_node_name === excelName).length;
      sameNameCount += duty_shifts.reduce(
        (acc, r) =>
          acc + r.node_quotas.filter((q) => !q.resolved && q.node_name === excelName).length,
        0,
      );
    } else {
      sameNameCount += duty_shifts.filter(
        (r) => !r.resolved_duty_type_id && r.duty_type_name === excelName,
      ).length;
      sameNameCount += shift_templates.filter(
        (r) => !r.resolved_duty_type_id && r.duty_type_name === excelName,
      ).length;
    }

    if (sameNameCount <= 1) {
      void applyMapping("row", { pickedId, kind, excelName, rowKey, sameNameCount });
    } else {
      setPendingPick({ pickedId, kind, excelName, rowKey, sameNameCount });
    }
  }
  ```

- [ ] **Step 5: Remove `handleNodePicked` and `nodeCreateContext`/`nodePickerContext` state**

  Remove:
  - `const [nodeCreateContext, setNodeCreateContext] = useState<...>(null);`
  - `const [nodePickerContext, setNodePickerContext] = useState<...>(null);`
  - The `handleNodePicked` function

  (These are replaced by the inline combobox.)

- [ ] **Step 6: Add the `PendingPickBanner` helper component**

  Add this inside the file, before `ImportSessionReviewPage`:

  ```tsx
  function PendingPickBanner({
    pick,
    onApplyAll,
    onApplyRow,
    onCancel,
  }: {
    pick: PendingPick;
    onApplyAll: () => void;
    onApplyRow: () => void;
    onCancel: () => void;
  }) {
    return (
      <div className="mt-1 p-2 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-700 rounded text-xs space-y-1">
        <p>
          יש עוד {pick.sameNameCount - 1} שורות עם השם &ldquo;{pick.excelName}&rdquo;. להחיל על כולן?
        </p>
        <div className="flex gap-3">
          <button className="text-indigo-600 hover:underline" onClick={onApplyAll}>
            החל על כולן
          </button>
          <button className="text-indigo-600 hover:underline" onClick={onApplyRow}>
            רק שורה זו
          </button>
          <button className="text-gray-500 hover:underline" onClick={onCancel}>
            ביטול
          </button>
        </div>
      </div>
    );
  }
  ```

- [ ] **Step 7: Update the soldiers tab to use `FuzzyPickerCombobox` for unresolved nodes**

  In the soldiers table, find the `unresolvedNode` block. Replace the entire inner `<div>` for `unresolvedNode` with:

  ```tsx
  {unresolvedNode ? (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <FuzzyPickerCombobox
          unresolvedName={row.hierarchy_node_name ?? ""}
          candidates={allNodes}
          disabled={readOnly}
          onPick={(id) =>
            handlePick(
              "hierarchy_node",
              row.hierarchy_node_name ?? "",
              `soldiers:${row.row}`,
              id,
            )
          }
        />
        {!readOnly && (
          <button
            className="text-indigo-600 hover:underline text-xs"
            onClick={() =>
              setNodeCreateContext({ unresolvedName: row.hierarchy_node_name ?? "" })
            }
          >
            צור יחידה
          </button>
        )}
      </div>
      {pendingPick?.rowKey === `soldiers:${row.row}` && pendingPick.kind === "hierarchy_node" && (
        <PendingPickBanner
          pick={pendingPick}
          onApplyAll={() => void applyMapping("all", pendingPick)}
          onApplyRow={() => void applyMapping("row", pendingPick)}
          onCancel={() => setPendingPick(null)}
        />
      )}
    </div>
  ) : (
    row.hierarchy_node_name
  )}
  ```

  Note: keep `nodeCreateContext` only (for "צור יחידה"); remove `nodePickerContext` entirely.

- [ ] **Step 8: Update the duty_shifts tab for unresolved duty type and quota nodes**

  For the duty type cell, replace the `unresolvedType` block:

  ```tsx
  {unresolvedType ? (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <FuzzyPickerCombobox
          unresolvedName={row.duty_type_name}
          candidates={allDutyTypes}
          disabled={readOnly}
          onPick={(id) =>
            handlePick(
              "duty_type",
              row.duty_type_name,
              `duty_shifts:${row.row}`,
              id,
            )
          }
        />
        {!readOnly && (
          <button
            className="text-indigo-600 hover:underline text-xs"
            onClick={() => setDutyTypeContext({ unresolvedName: row.duty_type_name })}
          >
            צור סוג תורנות
          </button>
        )}
      </div>
      {pendingPick?.rowKey === `duty_shifts:${row.row}` && pendingPick.kind === "duty_type" && (
        <PendingPickBanner
          pick={pendingPick}
          onApplyAll={() => void applyMapping("all", pendingPick)}
          onApplyRow={() => void applyMapping("row", pendingPick)}
          onCancel={() => setPendingPick(null)}
        />
      )}
    </div>
  ) : (
    row.duty_type_name
  )}
  ```

  For each quota in `node_quotas`, replace the unresolved quota block:

  ```tsx
  {row.node_quotas.map((q, i) => {
    const quotaRowKey = `duty_shifts:${row.row}:${q.node_name}`;
    return (
      <div key={i} className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className={q.resolved ? "" : "text-red-600"}>
            {q.node_name}:{q.count}
          </span>
          {!q.resolved && !readOnly && (
            <FuzzyPickerCombobox
              unresolvedName={q.node_name}
              candidates={allNodes}
              disabled={readOnly}
              onPick={(id) =>
                handlePick("hierarchy_node", q.node_name, quotaRowKey, id)
              }
            />
          )}
          {!q.resolved && !readOnly && (
            <button
              className="text-indigo-600 hover:underline text-xs"
              onClick={() => setNodeCreateContext({ unresolvedName: q.node_name })}
            >
              צור
            </button>
          )}
        </div>
        {pendingPick?.rowKey === quotaRowKey && pendingPick.kind === "hierarchy_node" && (
          <PendingPickBanner
            pick={pendingPick}
            onApplyAll={() => void applyMapping("all", pendingPick)}
            onApplyRow={() => void applyMapping("row", pendingPick)}
            onCancel={() => setPendingPick(null)}
          />
        )}
      </div>
    );
  })}
  ```

- [ ] **Step 9: Update the shift_templates tab for unresolved duty type**

  In the shift_templates table, replace the `unresolvedType` block:

  ```tsx
  {unresolvedType ? (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <FuzzyPickerCombobox
          unresolvedName={row.duty_type_name}
          candidates={allDutyTypes}
          disabled={readOnly}
          onPick={(id) =>
            handlePick(
              "duty_type",
              row.duty_type_name,
              `shift_templates:${row.row}`,
              id,
            )
          }
        />
        {!readOnly && (
          <button
            className="text-indigo-600 hover:underline text-xs"
            onClick={() => setDutyTypeContext({ unresolvedName: row.duty_type_name })}
          >
            צור סוג תורנות
          </button>
        )}
      </div>
      {pendingPick?.rowKey === `shift_templates:${row.row}` && pendingPick.kind === "duty_type" && (
        <PendingPickBanner
          pick={pendingPick}
          onApplyAll={() => void applyMapping("all", pendingPick)}
          onApplyRow={() => void applyMapping("row", pendingPick)}
          onCancel={() => setPendingPick(null)}
        />
      )}
    </div>
  ) : (
    row.duty_type_name
  )}
  ```

- [ ] **Step 10: Remove `AddRootNodeDialog` and `HierarchyNodePickerModal` rendering**

  At the bottom of the JSX, remove the `{nodePickerContext && ...}` and `{nodeCreateContext && <AddRootNodeDialog .../>}` blocks.

  Keep only:
  - `{dutyTypeContext && <DutyTypeFormModal ... />}`
  - `{nodeCreateContext && <AddRootNodeDialog initialName={nodeCreateContext.unresolvedName} onCreated={() => { void handleReparse(); }} onClose={() => setNodeCreateContext(null)} />}`

  Remove the `HierarchyNodePickerModal` import from the top of the file:
  ```typescript
  // remove this line:
  import HierarchyNodePickerModal from "../components/HierarchyNodePickerModal";
  ```

- [ ] **Step 11: Run typecheck and lint**

  ```bash
  cd frontend
  npm run typecheck
  npm run lint
  ```

  Expected: zero errors, zero warnings.

- [ ] **Step 12: Commit**

  ```bash
  git add frontend/src/pages/ImportSessionReviewPage.tsx
  git commit -m "feat: inline fuzzy combobox for resolving unmatched import names"
  ```

---

## Self-review notes

- **`nodeCreateContext` state is kept** in the page (for "צור יחידה" / "צור" buttons) — these are not removed.
- **`shift_templates` rows** in the page are typed via `ShiftTemplateRow` (added to `ParsedState` in Task 3).
- **Row key format** used in `handlePick` matches exactly what the backend resolvers expect: `soldiers:<row>`, `duty_shifts:<row>`, `shift_templates:<row>`, `duty_shifts:<row>:<node_name>`.
- **`by_row` wins when `sameNameCount === 1`** — this is correct; one row means the pick is unambiguous and we use the more specific override.
- **Stale UUID fallback** is tested in Task 2 Step 5.
