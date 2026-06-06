# Cancel All Assignments From Today Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two bulk-cancel buttons to the שיבוץ ידני page — one for all published assignments from today onward, one for all algorithm_draft assignments from today onward — with a live draft count shown on page load.

**Architecture:** Relax the existing `reset-published` / `reset-drafts` backend endpoints to accept `days_ahead=0` (today inclusive), add a `GET /algorithm/drafts-preview` endpoint for the live count/list, wire a new `getDraftsPreview()` API call in the frontend, and render a "ביטול שיבוצים" section at the bottom of `DutyManagementPage`.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript (frontend), react-i18next (translations), pytest (backend tests)

---

## File Map

| File | Change |
|---|---|
| `backend/app/routes/algorithm.py` | Relax `ge=1→0`, fix `>→>=` on both reset endpoints; add `DraftsPreviewOut` schema + `GET /drafts-preview` |
| `backend/tests/integration/test_algorithm_routes.py` | Update two existing `422` tests → `200`; add three new tests |
| `frontend/src/api/algorithm.ts` | Add `DraftPreviewItem`, `DraftsPreviewOut` interfaces + `getDraftsPreview()` |
| `frontend/src/i18n/he.json` | Add 14 keys under `duty_management` |
| `frontend/src/pages/DutyManagementPage.tsx` | Add bulk-cancel state + section UI |

---

### Task 1: Backend — relax reset endpoints to allow `days_ahead=0`

**Files:**
- Modify: `backend/app/routes/algorithm.py` (lines ~389–454)
- Modify: `backend/tests/integration/test_algorithm_routes.py` (lines ~266–350)

- [ ] **Step 1: Update `reset-published` — change `ge=1` to `ge=0` and `>` to `>=`**

In `backend/app/routes/algorithm.py`, find `reset_published_assignments`:

```python
@router.post("/reset-published", status_code=status.HTTP_200_OK)
def reset_published_assignments(
    days_ahead: int = Query(ge=0),          # was ge=1
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    cutoff = date.today() + timedelta(days=days_ahead)
    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "published",
            DutyAssignment.start_date >= cutoff,    # was >
        )
    ).scalars().all()

    for a in assignments:
        a.status = "cancelled"
        write_audit(
            session,
            actor_id=user.id,
            action="assignment.bulk_cancel",
            entity_type="duty_assignment",
            entity_id=a.id,
            before={"status": "published"},
            after={"status": "cancelled"},
            context={"days_ahead": days_ahead},
        )

    session.commit()
    return {"cancelled": len(assignments)}
```

- [ ] **Step 2: Update `reset-drafts` — same two changes**

Find `reset_draft_assignments`:

```python
@router.post("/reset-drafts", status_code=status.HTTP_200_OK)
def reset_draft_assignments(
    days_ahead: int = Query(ge=0),          # was ge=1
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    cutoff = date.today() + timedelta(days=days_ahead)
    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "algorithm_draft",
            DutyAssignment.start_date >= cutoff,    # was >
        )
    ).scalars().all()

    for a in assignments:
        a.status = "algorithm_rejected"
        write_audit(
            session,
            actor_id=user.id,
            action="algorithm.proposal.bulk_reject",
            entity_type="duty_assignment",
            entity_id=a.id,
            before={"status": "algorithm_draft"},
            after={"status": "algorithm_rejected"},
            context={"days_ahead": days_ahead},
        )

    session.commit()
    return {"rejected": len(assignments)}
```

- [ ] **Step 3: Update existing 422 tests to expect 200**

In `backend/tests/integration/test_algorithm_routes.py`, find `test_reset_published_rejects_days_ahead_zero` and `test_reset_drafts_rejects_days_ahead_zero`. Rename them and flip the assertion:

```python
def test_reset_published_allows_days_ahead_zero(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rp_dm_003")
    dm = create_soldier(admin_session, personal_number="rp_dm_003", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-published",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert "cancelled" in resp.json()


def test_reset_drafts_allows_days_ahead_zero(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rd_dm_003")
    dm = create_soldier(admin_session, personal_number="rd_dm_003", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-drafts",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert "rejected" in resp.json()
```

- [ ] **Step 4: Add test — `days_ahead=0` cancels today's published assignments**

Append to `backend/tests/integration/test_algorithm_routes.py`:

```python
def test_reset_published_days_ahead_zero_includes_today(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rp_today_001")
    dm = create_soldier(admin_session, personal_number="rp_today_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    today_assignment = _make_published_assignment(admin_session, "rp_today_s_001", date.today())

    resp = client.post(
        "/api/algorithm/reset-published",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["cancelled"] >= 1

    admin_session.expire(today_assignment)
    admin_session.refresh(today_assignment)
    assert today_assignment.status == "cancelled"


def test_reset_drafts_days_ahead_zero_includes_today(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rd_today_001")
    dm = create_soldier(admin_session, personal_number="rd_today_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    today_draft = _make_draft_assignment(admin_session, "rd_today_s_001", date.today())

    resp = client.post(
        "/api/algorithm/reset-drafts",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["rejected"] >= 1

    admin_session.expire(today_draft)
    admin_session.refresh(today_draft)
    assert today_draft.status == "algorithm_rejected"
```

- [ ] **Step 5: Run the modified and new tests**

```bash
cd backend
pytest tests/integration/test_algorithm_routes.py -k "reset_published or reset_drafts" -v
```

Expected: all pass (previously the two `422` tests now expect `200`, and the new today-inclusive tests pass).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/algorithm.py backend/tests/integration/test_algorithm_routes.py
git commit -m "feat: relax reset endpoints to accept days_ahead=0 (includes today)"
```

---

### Task 2: Backend — add `GET /algorithm/drafts-preview` endpoint

**Files:**
- Modify: `backend/app/routes/algorithm.py`
- Modify: `backend/tests/integration/test_algorithm_routes.py`

- [ ] **Step 1: Write the failing test first**

Append to `backend/tests/integration/test_algorithm_routes.py`:

```python
def test_drafts_preview_returns_today_and_future_drafts(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_dp_001")
    dm = create_soldier(admin_session, personal_number="dp_dm_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    today_draft = _make_draft_assignment(admin_session, "dp_s_001", date.today())
    future_draft = _make_draft_assignment(admin_session, "dp_s_002", date.today() + timedelta(days=10))
    # past draft — must NOT appear
    _make_draft_assignment(admin_session, "dp_s_003", date.today() - timedelta(days=5))

    resp = client.get("/api/algorithm/drafts-preview", headers=auth_headers(dm))
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert "items" in data
    returned_ids = {item["assignment_id"] for item in data["items"]}
    assert str(today_draft.id) in returned_ids
    assert str(future_draft.id) in returned_ids


def test_drafts_preview_excludes_published_and_cancelled(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_dp_002")
    dm = create_soldier(admin_session, personal_number="dp_dm_002", role="duty_manager", hierarchy_node_id=dm_node.id)

    _make_published_assignment(admin_session, "dp_pub_s_001", date.today() + timedelta(days=5))

    resp = client.get("/api/algorithm/drafts-preview", headers=auth_headers(dm))
    assert resp.status_code == 200
    data = resp.json()
    # published assignment must not appear (wrong status)
    for item in data["items"]:
        assert item.get("duty_type_name") is not None  # shape check


def test_drafts_preview_soldier_forbidden(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="dp_soldier_001")

    resp = client.get("/api/algorithm/drafts-preview", headers=auth_headers(soldier))
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend
pytest tests/integration/test_algorithm_routes.py -k "drafts_preview" -v
```

Expected: FAIL with 404 (route doesn't exist yet).

- [ ] **Step 3: Add Pydantic schema and endpoint to `algorithm.py`**

At the top of the route file (with other Pydantic models, after `JobSummaryOut`):

```python
class DraftPreviewItem(BaseModel):
    assignment_id: uuid.UUID
    soldier_name: str
    duty_type_name: str
    start_date: date
    end_date: date


class DraftsPreviewOut(BaseModel):
    count: int
    items: list[DraftPreviewItem]
```

Then add the endpoint (place it before or after `reset-drafts`):

```python
@router.get("/drafts-preview", response_model=DraftsPreviewOut)
def get_drafts_preview(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> DraftsPreviewOut:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    today = date.today()
    rows = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "algorithm_draft",
            DutyAssignment.start_date >= today,
        )
    ).scalars().all()

    items = []
    for a in rows:
        soldier = session.get(Soldier, a.soldier_id)
        duty_type = session.get(DutyType, a.duty_type_id)
        items.append(DraftPreviewItem(
            assignment_id=a.id,
            soldier_name=soldier.full_name if soldier else str(a.soldier_id),
            duty_type_name=duty_type.name if duty_type else str(a.duty_type_id),
            start_date=a.start_date,
            end_date=a.end_date,
        ))

    return DraftsPreviewOut(count=len(items), items=items)
```

Note: `DutyType` is already imported at the top of the file. `Soldier` is already imported.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend
pytest tests/integration/test_algorithm_routes.py -k "drafts_preview" -v
```

Expected: all 3 new tests pass.

- [ ] **Step 5: Run full algorithm test suite to check for regressions**

```bash
cd backend
pytest tests/integration/test_algorithm_routes.py tests/integration/test_algorithm_cancel.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/algorithm.py backend/tests/integration/test_algorithm_routes.py
git commit -m "feat: add GET /algorithm/drafts-preview endpoint"
```

---

### Task 3: Frontend — add API types and `getDraftsPreview()`

**Files:**
- Modify: `frontend/src/api/algorithm.ts`

- [ ] **Step 1: Add interfaces and function**

At the end of `frontend/src/api/algorithm.ts`, append:

```typescript
export interface DraftPreviewItem {
  assignment_id: string;
  soldier_name: string;
  duty_type_name: string;
  start_date: string;
  end_date: string;
}

export interface DraftsPreviewOut {
  count: number;
  items: DraftPreviewItem[];
}

export async function getDraftsPreview(): Promise<DraftsPreviewOut> {
  return (await api.get<DraftsPreviewOut>("/algorithm/drafts-preview")).data;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/algorithm.ts
git commit -m "feat: add getDraftsPreview API function"
```

---

### Task 4: Frontend — add i18n keys

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add keys under `duty_management`**

In `frontend/src/i18n/he.json`, find the `duty_management` block (around line 183). Replace the closing `}` of that block with these additions:

```json
  "duty_management": {
    "title": "ניהול תורנויות",
    "soldier": "חייל",
    "duty_type": "סוג תורנות",
    "location": "מיקום",
    "start_date": "מתאריך",
    "end_date": "עד תאריך",
    "notes": "הערות",
    "create": "צור תורנות",
    "cancel": "בטל תורנות",
    "cancel_reason": "סיבת ביטול",
    "override": "החלפה ליום",
    "override_day": "תאריך",
    "replacement": "מחליף",
    "score_adjustment": "תיקון ניקוד",
    "delta": "שינוי ניקוד",
    "reason": "סיבה",
    "apply": "החל",
    "none": "אין תורנויות",
    "bulk_cancel_section_title": "ביטול שיבוצים",
    "drafts_from_today_label": "טיוטות שיבוץ מהיום ואילך",
    "drafts_badge": "{{count}} שיבוצים",
    "drafts_badge_none": "אין טיוטות",
    "drafts_toggle_show": "הצג פירוט",
    "drafts_toggle_hide": "הסתר פירוט",
    "cancel_drafts_btn": "מחק טיוטות",
    "cancel_drafts_confirm": "למחוק {{count}} טיוטות שיבוץ מהיום ואילך?",
    "cancel_drafts_result": "בוטלו {{count}} טיוטות",
    "cancel_drafts_none": "לא נמצאו טיוטות לביטול",
    "published_from_today_label": "שיבוצים פורסמים מהיום ואילך",
    "cancel_published_btn": "מחק שיבוצים פורסמים",
    "cancel_published_confirm": "לבטל את כל השיבוצים הפורסמים מהיום ואילך?",
    "cancel_published_result": "בוטלו {{count}} שיבוצים פורסמים",
    "cancel_published_none": "לא נמצאו שיבוצים פורסמים לביטול"
  },
```

- [ ] **Step 2: Verify JSON is valid**

```bash
cd frontend
node -e "require('./src/i18n/he.json'); console.log('valid')"
```

Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "feat: add i18n keys for bulk cancel section"
```

---

### Task 5: Frontend — add bulk cancel section to `DutyManagementPage`

**Files:**
- Modify: `frontend/src/pages/DutyManagementPage.tsx`

- [ ] **Step 1: Add imports and new state**

Replace the top of `DutyManagementContent` in `frontend/src/pages/DutyManagementPage.tsx`:

```typescript
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { Assignment, cancelAssignment, createAssignment, listAssignments, setOverride } from "../api/assignments";
import { createAdjustment } from "../api/scoreAdjustments";
import { DutyLocation, DutyType, listDutyTypes, listLocations } from "../api/dutyConfig";
import { SoldierDTO, listSoldiers } from "../api/soldiers";
import { DraftPreviewItem, getDraftsPreview, resetDrafts, resetPublished } from "../api/algorithm";

export function DutyManagementContent() {
  const { t } = useTranslation();
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [types, setTypes] = useState<DutyType[]>([]);
  const [locs, setLocs] = useState<DutyLocation[]>([]);
  const [soldierId, setSoldierId] = useState("");
  const [typeId, setTypeId] = useState("");
  const [locId, setLocId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [rows, setRows] = useState<Assignment[]>([]);
  const [error, setError] = useState("");
  const [adjDelta, setAdjDelta] = useState("");
  const [adjReason, setAdjReason] = useState("");

  // Bulk cancel state
  const [draftCount, setDraftCount] = useState<number>(0);
  const [draftItems, setDraftItems] = useState<DraftPreviewItem[]>([]);
  const [draftsExpanded, setDraftsExpanded] = useState(false);
  const [cancelDraftsLoading, setCancelDraftsLoading] = useState(false);
  const [cancelDraftsMsg, setCancelDraftsMsg] = useState<string | null>(null);
  const [cancelPublishedLoading, setCancelPublishedLoading] = useState(false);
  const [cancelPublishedMsg, setCancelPublishedMsg] = useState<string | null>(null);
  const draftsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const publishedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
```

- [ ] **Step 2: Add draft preview fetch function and hook**

After the `refresh` callback and before `submit`, insert:

```typescript
  const refreshDraftPreview = useCallback(async () => {
    try {
      const preview = await getDraftsPreview();
      setDraftCount(preview.count);
      setDraftItems(preview.items);
    } catch { /* ignore — DM-only endpoint, silently skip for non-DM users */ }
  }, []);

  useEffect(() => { void refreshDraftPreview(); }, [refreshDraftPreview]);
```

- [ ] **Step 3: Add bulk cancel handler functions**

After `submitAdj` and before the `return`, insert:

```typescript
  async function handleCancelDrafts() {
    if (!window.confirm(t("duty_management.cancel_drafts_confirm", { count: draftCount }))) return;
    setCancelDraftsLoading(true);
    setCancelDraftsMsg(null);
    if (draftsTimerRef.current) clearTimeout(draftsTimerRef.current);
    try {
      const result = await resetDrafts(0);
      const msg = result.rejected === 0
        ? t("duty_management.cancel_drafts_none")
        : t("duty_management.cancel_drafts_result", { count: result.rejected });
      setCancelDraftsMsg(msg);
      draftsTimerRef.current = setTimeout(() => setCancelDraftsMsg(null), 5000);
      await refreshDraftPreview();
    } catch {
      setCancelDraftsMsg(t("errors.generic"));
    } finally {
      setCancelDraftsLoading(false);
    }
  }

  async function handleCancelPublished() {
    if (!window.confirm(t("duty_management.cancel_published_confirm"))) return;
    setCancelPublishedLoading(true);
    setCancelPublishedMsg(null);
    if (publishedTimerRef.current) clearTimeout(publishedTimerRef.current);
    try {
      const result = await resetPublished(0);
      const msg = result.cancelled === 0
        ? t("duty_management.cancel_published_none")
        : t("duty_management.cancel_published_result", { count: result.cancelled });
      setCancelPublishedMsg(msg);
      publishedTimerRef.current = setTimeout(() => setCancelPublishedMsg(null), 5000);
      await refreshDraftPreview();
    } catch {
      setCancelPublishedMsg(t("errors.generic"));
    } finally {
      setCancelPublishedLoading(false);
    }
  }
```

- [ ] **Step 4: Add cleanup effect for timers**

After the `useEffect` for `refreshDraftPreview`, add:

```typescript
  useEffect(() => {
    return () => {
      if (draftsTimerRef.current) clearTimeout(draftsTimerRef.current);
      if (publishedTimerRef.current) clearTimeout(publishedTimerRef.current);
    };
  }, []);
```

- [ ] **Step 5: Add the bulk cancel UI section**

In the `return` of `DutyManagementContent`, after the closing `</form>` of the score adjustment form (just before the closing `</section>`), append:

```tsx
      <div className="border-t dark:border-gray-600 pt-4 space-y-4" dir="rtl">
        <h3 className="font-medium text-sm text-gray-700 dark:text-gray-300">
          {t("duty_management.bulk_cancel_section_title")}
        </h3>

        {/* Drafts row */}
        <div className="space-y-2">
          <div className="flex items-center gap-3 flex-wrap text-sm">
            <span className="text-gray-700 dark:text-gray-300">
              {t("duty_management.drafts_from_today_label")}
            </span>
            <button
              type="button"
              onClick={() => setDraftsExpanded(v => !v)}
              className={`px-2 py-0.5 rounded text-xs font-medium ${
                draftCount > 0
                  ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200 hover:bg-amber-200 dark:hover:bg-amber-800"
                  : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
              }`}
            >
              {draftCount > 0
                ? t("duty_management.drafts_badge", { count: draftCount })
                : t("duty_management.drafts_badge_none")}
              {" "}
              {draftCount > 0 ? (draftsExpanded ? t("duty_management.drafts_toggle_hide") : t("duty_management.drafts_toggle_show")) : ""}
            </button>
            <button
              type="button"
              onClick={handleCancelDrafts}
              disabled={cancelDraftsLoading || draftCount === 0}
              className="bg-amber-600 text-white px-3 py-1 rounded text-xs hover:bg-amber-700 disabled:opacity-40"
            >
              {t("duty_management.cancel_drafts_btn")}
            </button>
            {cancelDraftsMsg && (
              <span className="text-xs text-gray-600 dark:text-gray-400">{cancelDraftsMsg}</span>
            )}
          </div>
          {draftsExpanded && draftItems.length > 0 && (
            <ul className="text-xs space-y-0.5 pr-2 max-h-40 overflow-y-auto border rounded dark:border-gray-600 p-2">
              {draftItems.map(item => (
                <li key={item.assignment_id} className="text-gray-700 dark:text-gray-300">
                  {item.soldier_name} · {item.duty_type_name} · {item.start_date}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Published row */}
        <div className="flex items-center gap-3 flex-wrap text-sm">
          <span className="text-gray-700 dark:text-gray-300">
            {t("duty_management.published_from_today_label")}
          </span>
          <button
            type="button"
            onClick={handleCancelPublished}
            disabled={cancelPublishedLoading}
            className="bg-red-600 text-white px-3 py-1 rounded text-xs hover:bg-red-700 disabled:opacity-40"
          >
            {t("duty_management.cancel_published_btn")}
          </button>
          {cancelPublishedMsg && (
            <span className="text-xs text-gray-600 dark:text-gray-400">{cancelPublishedMsg}</span>
          )}
        </div>
      </div>
```

- [ ] **Step 6: Verify TypeScript compiles**

```bash
cd frontend
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 7: Run frontend dev server and manually verify**

```bash
cd frontend
npm run dev
```

Open the app, navigate to שיבוץ ידני page:
- The "ביטול שיבוצים" section appears at the bottom
- Draft count badge shows correct number (or "אין טיוטות")
- Clicking badge toggles the draft list
- "מחק טיוטות" is disabled when count=0
- Clicking "מחק שיבוצים פורסמים" → confirm dialog appears → after confirm, shows result message

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/DutyManagementPage.tsx
git commit -m "feat: add bulk cancel section to DutyManagementPage"
```

---

## Self-Review

**Spec coverage:**
- ✅ `reset-published` relaxed to `ge=0` with `>=` filter — Task 1
- ✅ `reset-drafts` relaxed to `ge=0` with `>=` filter — Task 1
- ✅ `GET /algorithm/drafts-preview` endpoint — Task 2
- ✅ `getDraftsPreview()` frontend API function — Task 3
- ✅ i18n keys — Task 4
- ✅ Page-load draft count fetch — Task 5 Step 2
- ✅ Draft count badge + expandable list — Task 5 Step 5
- ✅ "מחק טיוטות" button, disabled when count=0 — Task 5 Step 5
- ✅ "מחק שיבוצים פורסמים" button — Task 5 Step 5
- ✅ Result messages with 5-second auto-clear — Task 5 Steps 3 & 4
- ✅ Re-fetch draft preview after either action — Task 5 Step 3
- ✅ Error handling → `t("errors.generic")` — Task 5 Step 3

**Placeholder scan:** none found.

**Type consistency:**
- `DraftPreviewItem` defined in Task 3, used in Task 5 ✅
- `getDraftsPreview()` returns `DraftsPreviewOut` with `.count` / `.items` — matched in Task 5 state (`draftCount`, `draftItems`) ✅
- `resetDrafts(0)` returns `{ rejected: number }` — used as `result.rejected` in Task 5 ✅
- `resetPublished(0)` returns `{ cancelled: number }` — used as `result.cancelled` in Task 5 ✅
