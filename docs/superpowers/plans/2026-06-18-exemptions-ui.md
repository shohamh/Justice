# Constraints & Exemptions Page UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Issue #23 — Add a titled card section "אילוצים שאושרו" above the approved exemptions list in `ExemptionsPanel`, giving it proper card styling with detail (type name, date range, days count).

**Architecture:**
- `ExemptionsPanel` currently shows a flat `<ul>` of all exemptions with expand-on-click. Split the list into two sections: "אילוצים שאושרו" (all active, i.e. non-expired and non-revoked) as a highlighted card section at the top, and the rest below.
- Each "approved" exemption card shows: exemption type name, date range formatted as DD.MM.YYYY, days remaining (if end_date set), and the exempted duty types if expanded.
- `canManage` still controls the revoke button.

**Tech Stack:** React, TypeScript

---

## File Map

| File | Change |
|------|--------|
| `frontend/src/components/ExemptionsPanel.tsx` | Add titled card section for active exemptions |

---

### Task 1: Add formatDate import and section header

**Files:**
- Modify: `frontend/src/components/ExemptionsPanel.tsx`

- [ ] **Step 1: Import formatDate**

At top of `frontend/src/components/ExemptionsPanel.tsx`, add:
```typescript
import { formatDate } from "../utils/formatDate";
```

- [ ] **Step 2: Split exemptions into active and all**

In the component body, after `const [items, setItems] = useState<Exemption[]>([]);`, no new state is needed. We compute derived lists inline in the JSX.

An "active" exemption is one without an end_date (indefinite) or with an end_date in the future. Add a helper above the `return` statement:

```typescript
  const today = new Date().toISOString().slice(0, 10);
  const activeItems = items.filter(
    (ex) => ex.end_date == null || ex.end_date >= today
  );
  const expiredItems = items.filter(
    (ex) => ex.end_date != null && ex.end_date < today
  );
```

- [ ] **Step 3: Render the "אילוצים שאושרו" card section**

Replace the entire `return (...)` in `ExemptionsPanel` with the following. The structure is: active items as prominent cards at the top (with section title), then a collapsible or plain list of expired ones below, then the grant form for managers.

```tsx
  return (
    <div data-testid="exemptions-panel" className="space-y-4">
      {/* Active exemptions — card section */}
      <div>
        <h3 className="font-semibold text-sm text-gray-700 dark:text-gray-200 mb-2">
          {t("exemptions.title")} ({activeItems.length})
        </h3>
        {activeItems.length === 0 ? (
          <p className="text-sm text-gray-500" data-testid="exemptions-empty">
            {t("exemptions.none")}
          </p>
        ) : (
          <ul className="space-y-2" data-testid="exemptions-list">
            {activeItems.map((ex) => {
              const names = dutyTypeMap[ex.exemption_type_id] ?? [];
              const isExpanded = expanded.has(ex.id);
              return (
                <li
                  key={ex.id}
                  className="border border-indigo-200 dark:border-indigo-700 bg-indigo-50 dark:bg-indigo-950 rounded-lg p-3 cursor-pointer hover:bg-indigo-100 dark:hover:bg-indigo-900 transition-colors"
                  onClick={() => toggleExpand(ex.id)}
                  data-testid={`exemption-row-${ex.id}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-0.5">
                      <p className="font-medium text-sm text-indigo-900 dark:text-indigo-100">
                        {typeName(ex.exemption_type_id)}
                      </p>
                      <p className="text-xs text-indigo-700 dark:text-indigo-300">
                        {formatDate(ex.start_date)} → {ex.end_date ? formatDate(ex.end_date) : t("exemptions.forever")}
                      </p>
                      <DaysBadge start={ex.start_date} end={ex.end_date} />
                    </div>
                    {canManage && (
                      <button
                        className="text-red-500 text-xs shrink-0"
                        onClick={(e) => { e.stopPropagation(); void onRevoke(ex.id); }}
                        data-testid={`revoke-${ex.id}`}
                      >
                        {t("exemptions.revoke")}
                      </button>
                    )}
                  </div>
                  {isExpanded && names.length > 0 && (
                    <div className="mt-2 text-xs text-indigo-700 dark:text-indigo-300 border-t border-indigo-200 dark:border-indigo-700 pt-1">
                      <span className="font-medium">{t("exemptions.exempts_from")}:</span>{" "}
                      {names.join("، ")}
                    </div>
                  )}
                  {isExpanded && ex.reason && (
                    <p className="mt-1 text-xs text-indigo-600 dark:text-indigo-400">{ex.reason}</p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Expired / past exemptions */}
      {expiredItems.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">
            {t("exemptions.past")}
          </h4>
          <ul className="space-y-1 text-sm" data-testid="exemptions-list-past">
            {expiredItems.map((ex) => {
              const names = dutyTypeMap[ex.exemption_type_id] ?? [];
              const isExpanded = expanded.has(ex.id);
              return (
                <li
                  key={ex.id}
                  className="border dark:border-gray-600 rounded p-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 opacity-60"
                  onClick={() => toggleExpand(ex.id)}
                  data-testid={`exemption-row-${ex.id}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{typeName(ex.exemption_type_id)}</span>
                    <span className="text-gray-500 dark:text-gray-400 text-xs">
                      {formatDate(ex.start_date)} → {ex.end_date ? formatDate(ex.end_date) : ""}
                    </span>
                    {canManage && (
                      <button
                        className="text-red-500 text-xs mr-auto"
                        onClick={(e) => { e.stopPropagation(); void onRevoke(ex.id); }}
                        data-testid={`revoke-${ex.id}`}
                      >
                        {t("exemptions.revoke")}
                      </button>
                    )}
                  </div>
                  {isExpanded && (
                    <div className="mt-1.5 space-y-0.5">
                      {ex.reason && <p className="text-xs text-gray-500">{ex.reason}</p>}
                      {names.length > 0 && (
                        <p className="text-xs text-gray-500">
                          <span className="font-medium">{t("exemptions.exempts_from")}:</span>{" "}
                          {names.join("، ")}
                        </p>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Grant form */}
      {canManage && (
        <form onSubmit={onGrant} className="flex flex-wrap items-end gap-2 pt-2 border-t dark:border-gray-600" data-testid="grant-form">
          <select className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={typeId} onChange={(e) => setTypeId(e.target.value)} required data-testid="grant-type">
            <option value="">{t("exemptions.type")}</option>
            {types.map((tp) => <option key={tp.id} value={tp.id}>{tp.name}</option>)}
          </select>
          <input type="date" className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={start} onChange={(e) => setStart(e.target.value)} required data-testid="grant-start" />
          <div className="flex items-center gap-2">
            <input
              type="date"
              className={`border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 ${indefinite ? "opacity-40 cursor-not-allowed" : ""}`}
              value={indefinite ? "" : end}
              onChange={(e) => setEnd(e.target.value)}
              disabled={indefinite}
              data-testid="grant-end"
            />
            <label className="flex items-center gap-1 text-sm whitespace-nowrap cursor-pointer">
              <input
                type="checkbox"
                checked={indefinite}
                onChange={(e) => {
                  setIndefinite(e.target.checked);
                  if (e.target.checked) setEnd("");
                }}
                data-testid="grant-indefinite"
              />
              ללא הגבלת זמן
            </label>
          </div>
          <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("exemptions.reason")} data-testid="grant-reason" />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="grant-submit">{t("exemptions.grant")}</button>
        </form>
      )}
    </div>
  );
```

- [ ] **Step 4: Add i18n key for "past" label**

In `frontend/src/i18n/he.json`, inside the `exemptions` object, add if missing:
```json
"past": "פטורים שפגו"
```

- [ ] **Step 5: Verify**

Open a soldier modal, go to the "exemptions" tab. Active exemptions should appear as indigo-tinted cards with a section title. Expired ones appear below in a greyed list.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ExemptionsPanel.tsx frontend/src/i18n/he.json
git commit -m "feat: add titled card section for active exemptions in ExemptionsPanel"
```
