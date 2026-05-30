# Hierarchy & Soldier Editor Fixups

## Goal

Post-user-testing fixes to the hierarchy tree editor on the /team page.

## Hierarchy Levels

Current 4-level chain `department → branch → group → team` is replaced with 6 levels:

| English ID | Hebrew display |
|---|---|
| `division` | מערך |
| `unit` | יחידה |
| `department` | מרכז |
| `branch` | ענף |
| `group` | מדור |
| `team` | צוות |

Existing DB enum values (`department`, `branch`, `group`, `team`) remain unchanged; `division` and `unit` are added. Existing nodes keep their current level — only their display translations change.

## Flexible Level Selection

When adding a child node, the user can choose ANY level below the parent's level (not just the immediate next). The default selection is the next logical level.

- Backend: Relax child-level validation from "must be exactly one level below" to "must be any level below"
- Frontend: `AddChildNodeDialog` shows all sub-levels as options, defaults to the immediate next

## Add Soldier in Tree

Each tree node gets a "+" button that expands an inline quick-add form:

1. A combined search/autocomplete field — type personal number or name
2. On partial match, the dropdown suggests existing soldiers (debounced)
3. Selecting an existing soldier assigns them to this node
4. If no match found, fill in remaining fields and create a new soldier under this node

## Soldier Edit Modal

Soldiers displayed under each tree node show an edit button. Clicking opens a modal with editable fields:
- Full name
- Phone
- Reassign to a different hierarchy node (dropdown)

Permission check: Modal buttons/fields only appear for authorized users — commanders whose scope includes the soldier's node, duty managers, and admins.

## Fix "פטורים" Button

The button on each tree node that opens the Assign Commander dialog:
- Currently labeled with `t("exemptions.title")` ("פטורים") — change to `t("team.assign_commander")` ("קביעת מפקד")
- The search input placeholder uses `t("my_requests.reason")` ("סיבה") — change to "חפש חייל..."
- The search filter itself is fine; fix is cosmetic (label/placeholder only)

## Affected Files

### Backend
- `backend/app/db/models.py` — add `division`, `unit` to enum
- `backend/app/services/hierarchy.py` — update `LEVEL_ORDER`, relax child-level validation
- `backend/app/routes/hierarchy.py` — update `CreateNodeRequest` validation pattern
- New Alembic migration — add enum values

### Frontend
- `frontend/src/api/hierarchy.ts` — update `NodeDTO.level` type union
- `frontend/src/components/HierarchyTree.tsx` — add soldier quick-add form per node, add soldier edit modal, fix button label, show soldiers under nodes
- `frontend/src/components/AddChildNodeDialog.tsx` — show all sub-levels, not just next
- `frontend/src/components/AssignCommanderDialog.tsx` — fix placeholder text
- `frontend/src/i18n/he.json` — update level display names, add new translation keys
- `frontend/src/pages/TeamHierarchyPage.tsx` — may need updates if soldier display moves to tree

### New Components
- `frontend/src/components/SoldierEditModal.tsx` — edit modal for soldier details
- `frontend/src/components/SoldierSearchAutocomplete.tsx` — reusable search/autocomplete for soldiers
