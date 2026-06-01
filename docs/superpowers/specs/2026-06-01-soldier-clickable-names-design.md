# Soldier Clickable Names & Role-Based Modal Design

**Date:** 2026-06-01
**Status:** Draft
**Depends on:** existing UnifiedSoldierModal, duty-history tab (being built in parallel)

---

## Goal

Every soldier name rendered in the frontend becomes a clickable link. Clicking opens `UnifiedSoldierModal` for that soldier. The modal shows different tabs and capabilities depending on the viewer's role and their relationship to the soldier.

---

## 1. Architecture

### 1.1 Global modal trigger

A `SoldierModalContext` (React context) is added to `App.tsx`. It provides:

```typescript
interface SoldierModalContextValue {
  openSoldierModal: (soldierId: string) => void;
}
```

A single `UnifiedSoldierModal` instance is rendered at the app root. When `openSoldierModal(id)` is called it fetches the soldier via `GET /soldiers/{id}`, fetches their score via `GET /soldiers/{id}/score`, then renders the modal.

### 1.2 SoldierLink component

A new `SoldierLink` component takes `id` and `name`. It calls `openSoldierModal` from context. Renders as an indigo underline button (visually consistent, no full underline on every cell in a dense table). Accepts an optional `className` override for compact contexts.

```tsx
<SoldierLink id={soldier.id} name={soldier.full_name} />
```

### 1.3 Modal reads viewer from context

`UnifiedSoldierModal` calls `useAuth()` internally (already does this in some pages via props). Remove `user` from the modal props — the modal always reads the logged-in viewer from context directly.

---

## 2. Backend changes

### 2.1 `GET /soldiers/{id}` — relax for plain soldiers

Current behaviour: 403 when a plain soldier requests another soldier's profile.
New behaviour: if the viewer is a plain soldier (role `"soldier"`) and not self, skip `authorize()` and return the same `SoldierOut` shape. Phone, rank, unit are already in the response.

No new field needed — the existing `SoldierOut` covers everything a plain soldier needs to see.

### 2.2 `GET /soldiers/{id}/score` — new endpoint

Returns a single soldier's scoring summary:

```python
class SoldierScoreOut(BaseModel):
    soldier_id: uuid.UUID
    cumulative_score: str       # Decimal as string
    normalised_score: str
    active_days: int
```

Calls the existing scoring service (already used by transparency endpoint). Auth: any authenticated user (same relaxation as 2.1).

### 2.3 `GET /soldiers/{id}/duty-history` — filter for plain-soldier viewers

If viewer role is `"soldier"` and `viewer.id != soldier_id`: return only events of type `"assignment"` and `"cancellation"`. Strip `"personal_constraint"`, `"exemption_request"`, `"dismissal"`, `"call_up"`.

The endpoint already allows self-read; no change needed for that path.

---

## 3. Frontend visibility rules

`UnifiedSoldierModal` determines its mode from `viewer.role` and `viewer.id === soldier.id`:

| Viewer | Tabs shown | Can edit | Can approve/reject |
|---|---|---|---|
| `admin` or `duty_manager` | details · profile · exemptions · constraints · duty_history | yes | yes |
| `commander` | details · profile · exemptions · constraints · duty_history | no | yes (constraints + exemptions) |
| `soldier` (self) | details · duty_history | no | no |
| `soldier` (other) | details (limited) · duty_history | no | no |

**Details tab — limited view** (soldier viewing another soldier):
- Shows: full name, rank, unit name, phone, score row (days active + normalised score)
- Hides: personal number, edit form, `left_at`

**Commander out-of-chain:** A commander clicking a soldier outside their subtree will see the details tab load (basic info now relaxed), but the duty-history, constraints, and exemptions calls will 403. The modal handles 403 on individual tab loads by showing "אין הרשאה להציג מידע זה" and hiding the tab quietly — it does not crash.

**Duty history tab — limited view** (soldier viewing another):
- Server already returns only `assignment` and `cancellation` events
- No approve/reject buttons (those require management roles)

---

## 4. Call sites — where SoldierLink replaces plain text

All of these have `soldier_id` available alongside the name:

| File | Current render | Data available |
|---|---|---|
| `HierarchyTree.tsx:170` | `{s.full_name}` | `s.id` (SoldierDTO) |
| `TransparencyPage.tsx:50,53` | `{r.full_name}` | `r.soldier_id` |
| `EntriesExitsPanel.tsx:86` | `{s.full_name}` | `s.id` (SoldierDTO) |
| `ShiftDetailPanel.tsx:50,98,124` | `{a.soldier_name}` | `a.soldier_id` (CalendarShiftAssignee) |
| `ShiftDetailPanel.tsx` (reserve covers) | `soldierName(id)` using assignment_id | build `assignmentId→{soldierId,name}` map from `shift.assignees` |
| `UpcomingSnapshot.tsx:25,59` | `{a.soldier_name}` | `a.soldier_id` |
| `ApprovalsFeed.tsx:51` | `{item.soldier_name}` | `item.soldier_id` |
| `AlgorithmPlanningWindow.tsx:358,365` | `soldierName(p.soldier_id)` | `p.soldier_id` directly |

`ApprovalsPage.tsx` uses soldier names only in summary labels inside cells that already have a soldier_id — wrap the same way.

---

## 5. New files

| File | Purpose |
|---|---|
| `frontend/src/contexts/SoldierModalContext.tsx` | Context + provider + singleton modal |
| `frontend/src/components/SoldierLink.tsx` | Clickable name component |
| `backend/app/services/soldier_score.py` | Single-soldier score query |

### Modified files

| File | Change |
|---|---|
| `backend/app/routes/soldiers.py` | Relax GET /{id} auth; add GET /{id}/score; filter duty-history by viewer role |
| `frontend/src/App.tsx` | Wrap with SoldierModalProvider |
| `frontend/src/api/soldiers.ts` | Add `getSoldierScore()` function |
| `frontend/src/components/UnifiedSoldierModal.tsx` | Role-based tab/field visibility; use `useAuth()` internally |
| All call sites in §4 | Swap `{name}` for `<SoldierLink id={...} name={...} />` |

---

## 6. No DB migrations needed

All data is already in the DB. This is pure query/UI work.

---

## 7. Testing

- **Backend:** Unit tests for the new score endpoint; integration test for the duty-history filter (plain soldier gets only assignment/cancellation events).
- **Frontend:** Component test for `SoldierLink` (calls `openSoldierModal` on click). Modal visibility test: mock viewer role, assert correct tabs rendered. E2E: click a soldier name in TransparencyPage, verify modal opens with correct tabs for the viewer's role.
