# Commander Notifications Profile UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Issue #10 — Replace the `prompt()` dialogs in the commander notification scopes section with a proper UI: a node dropdown and a depth selector. The subscribed-soldiers list is already displayed — keep it, just make it more prominent.

**Architecture:**
- Fetch the hierarchy tree (already fetched elsewhere, not yet in ProfilePage) to populate a `<select>` for node selection.
- Depth: a `<select>` with "כל הרמות" (−1) and options 1–5.
- The `addCommanderScope` API call and the display of existing scopes with their soldier lists remain unchanged.

**Tech Stack:** React, TypeScript, hierarchy API

---

## File Map

| File | Change |
|------|--------|
| `frontend/src/pages/ProfilePage.tsx` | Replace prompt() with inline form; fetch hierarchy tree |

---

### Task 1: Add hierarchy tree fetch and inline add-scope form

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx`

- [ ] **Step 1: Import hierarchy fetch and NodeDTO**

At the top of `frontend/src/pages/ProfilePage.tsx`, add:
```typescript
import { fetchTree, NodeDTO } from "../api/hierarchy";
import { sortNodesByTree, indentedNodeLabel } from "../utils/sortNodesByTree";
```

- [ ] **Step 2: Add state for the tree and the form inputs**

In the component body, after `const [scopes, setScopes] = useState<CommanderScope[]>([]);`, add:
```typescript
  const [hierarchyNodes, setHierarchyNodes] = useState<NodeDTO[]>([]);
  const [addNodeId, setAddNodeId] = useState("");
  const [addDepth, setAddDepth] = useState<number>(-1);
  const [addingScopeLoading, setAddingScopeLoading] = useState(false);
```

- [ ] **Step 3: Fetch the tree when the user is a commander/DM/admin**

In the existing `useEffect` that calls `listCommanderScopes()` (around line 52):
```typescript
    if (user?.role === "commander" || user?.role === "duty_manager" || user?.role === "admin") {
      listCommanderScopes().then(setScopes).catch(() => {});
    }
```
Add a tree fetch alongside it:
```typescript
    if (user?.role === "commander" || user?.role === "duty_manager" || user?.role === "admin") {
      listCommanderScopes().then(setScopes).catch(() => {});
      fetchTree().then((nodes) => {
        const flat: NodeDTO[] = [];
        function flatten(ns: NodeDTO[]) { for (const n of ns) { flat.push(n); if (n.children) flatten(n.children); } }
        flatten(nodes);
        setHierarchyNodes(flat);
      }).catch(() => {});
    }
```

- [ ] **Step 4: Replace handleAddScope with a non-prompt version**

Find and remove the current `handleAddScope` function:
```typescript
  async function handleAddScope() {
    const nodeId = prompt(t("notifications.enter_node_id"));
    if (!nodeId) return;
    const depthStr = prompt(t("notifications.enter_depth"), "-1");
    const depth = parseInt(depthStr ?? "-1", 10);
    try {
      const scope = await addCommanderScope(nodeId, isNaN(depth) ? -1 : depth);
      setScopes((prev) => [...prev, scope]);
    } catch { alert(t("notifications.scope_add_error")); }
  }
```
Replace with:
```typescript
  async function handleAddScope(e: React.FormEvent) {
    e.preventDefault();
    if (!addNodeId) return;
    setAddingScopeLoading(true);
    try {
      const scope = await addCommanderScope(addNodeId, addDepth);
      setScopes((prev) => [...prev, scope]);
      setAddNodeId("");
      setAddDepth(-1);
    } catch {
      alert(t("notifications.scope_add_error"));
    } finally {
      setAddingScopeLoading(false);
    }
  }
```

- [ ] **Step 5: Replace the "+ הוסף" button with an inline form**

Find (around line 385):
```tsx
          <button onClick={handleAddScope} className="text-sm text-indigo-600 hover:text-indigo-800">
            + {t("notifications.add_scope")}
          </button>
```
Replace with:
```tsx
          <form onSubmit={handleAddScope} className="flex flex-wrap gap-2 items-end pt-2 border-t dark:border-gray-600">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">{t("notifications.scope_node")}</label>
              <select
                value={addNodeId}
                onChange={(e) => setAddNodeId(e.target.value)}
                required
                className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 min-w-[180px]"
              >
                <option value="">— בחר ענף —</option>
                {sortNodesByTree(hierarchyNodes).map(({ node, depth }) => (
                  <option key={node.id} value={node.id}>
                    {indentedNodeLabel(node, depth)}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">{t("notifications.scope_depth")}</label>
              <select
                value={addDepth}
                onChange={(e) => setAddDepth(Number(e.target.value))}
                className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              >
                <option value={-1}>כל הרמות</option>
                <option value={1}>רמה 1 (ישיר)</option>
                <option value={2}>עד 2 רמות</option>
                <option value={3}>עד 3 רמות</option>
                <option value={4}>עד 4 רמות</option>
                <option value={5}>עד 5 רמות</option>
              </select>
            </div>
            <button
              type="submit"
              disabled={!addNodeId || addingScopeLoading}
              className="bg-indigo-600 text-white px-3 py-1.5 rounded text-sm hover:bg-indigo-700 disabled:opacity-50"
            >
              {addingScopeLoading ? "מוסיף..." : "+ הוסף"}
            </button>
          </form>
```

- [ ] **Step 6: Add i18n keys (if missing)**

In `frontend/src/i18n/he.json`, inside the `notifications` object, ensure these keys exist (add if missing):
```json
"scope_node": "ענף",
"scope_depth": "עומק",
```

- [ ] **Step 7: Verify and commit**

Open the profile page as a commander. The "commander scopes" section should show a node dropdown and a depth selector instead of prompt dialogs. Adding a scope should work and the new scope should appear with its soldier list.

```bash
git add frontend/src/pages/ProfilePage.tsx frontend/src/i18n/he.json
git commit -m "feat: replace prompt dialogs with proper form in commander notification scopes"
```
