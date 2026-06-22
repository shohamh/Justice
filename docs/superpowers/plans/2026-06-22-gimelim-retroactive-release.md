# Gimelim Retroactive Release + Unified Dismissal Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a duty manager backdate a gimelim ("שחרור גימלים") release to a day before today, and merge the regular dismissal modal and the gimelim modal into one modal with a mode toggle.

**Architecture:** Backend: `preview_gimelim`/`commit_gimelim` gain a `from_date` parameter (defaulting to today) that replaces the hardcoded shift-start as the dismissal/call-up start date; `to_date` stays locked to end-of-shift. Frontend: `DismissalModal.tsx` absorbs `GimelimModal.tsx`'s preview/commit/file-upload flow behind a "רגיל"/"גימלים" toggle; `GimelimModal.tsx` is deleted; `ShiftDetailPanel.tsx` drops its separate gimelim button and state.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend), React + TanStack Query + i18next (frontend), pytest (backend tests).

**Spec:** `docs/superpowers/specs/2026-06-22-gimelim-retroactive-release-design.md`

---

## Backend

### Task 1: `preview_gimelim` accepts and validates `from_date`

**Files:**
- Modify: `backend/app/services/gimelim.py:286-422` (`preview_gimelim`)
- Test: `backend/tests/unit/test_gimelim_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_gimelim_service.py` (after `test_preview_finds_future_slot`, before the "Commit tests" section):

```python
def test_preview_defaults_from_date_to_today(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd1", "ActorFD1")
    soldier_a = _make_soldier(admin_session, "gimfd1", "A")
    soldier_b = _make_soldier(admin_session, "gimfd2", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date.today() - timedelta(days=2), end=date.today() + timedelta(days=2),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="medical leave",
        actor_id=actor.id,
    )

    token_entry = preview.preview_token
    assert token_entry is not None
    # from_date defaults to today when not passed
    from app.services.gimelim import _PREVIEW_STORE
    _, payload = _PREVIEW_STORE[token_entry]
    assert payload["from_date"] == date.today().isoformat()


def test_preview_accepts_backdated_from_date(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd2", "ActorFD2")
    soldier_a = _make_soldier(admin_session, "gimfd3", "A")
    soldier_b = _make_soldier(admin_session, "gimfd4", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 10), end=date(2026, 6, 15),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    backdated = date(2026, 6, 11)
    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="medical leave",
        actor_id=actor.id,
        from_date=backdated,
    )

    from app.services.gimelim import _PREVIEW_STORE
    _, payload = _PREVIEW_STORE[preview.preview_token]
    assert payload["from_date"] == backdated.isoformat()


def test_preview_rejects_from_date_before_shift_start(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd3", "ActorFD3")
    soldier_a = _make_soldier(admin_session, "gimfd5", "A")
    soldier_b = _make_soldier(admin_session, "gimfd6", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 10), end=date(2026, 6, 15),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    with pytest.raises(GimelimError, match="date_out_of_range"):
        preview_gimelim(
            admin_session,
            shift_id=shift.id,
            primary_assignment_id=primary.id,
            rest_days=7,
            reason="medical leave",
            actor_id=actor.id,
            from_date=date(2026, 6, 9),
        )


def test_preview_rejects_from_date_on_or_after_shift_end(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd4", "ActorFD4")
    soldier_a = _make_soldier(admin_session, "gimfd7", "A")
    soldier_b = _make_soldier(admin_session, "gimfd8", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 10), end=date(2026, 6, 15),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    with pytest.raises(GimelimError, match="date_out_of_range"):
        preview_gimelim(
            admin_session,
            shift_id=shift.id,
            primary_assignment_id=primary.id,
            rest_days=7,
            reason="medical leave",
            actor_id=actor.id,
            from_date=date(2026, 6, 15),  # == end_date, invalid (must be < end_date)
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/unit/test_gimelim_service.py -k "from_date" -v`
Expected: FAIL — `preview_gimelim() got an unexpected keyword argument 'from_date'`

- [ ] **Step 3: Implement `from_date` in `preview_gimelim`**

In `backend/app/services/gimelim.py`, change the `preview_gimelim` signature (around line 286-294):

```python
def preview_gimelim(
    session: Session,
    *,
    shift_id: uuid.UUID,
    primary_assignment_id: uuid.UUID,
    rest_days: int,
    reason: str | None,
    actor_id: uuid.UUID,
    from_date: date | None = None,
) -> GimelimPreview:
    """Compute a gimelim proposal without writing anything."""
```

Right after the existing `shift is None` check (currently ends around line 311, right before the reserve-link lookup), insert the `from_date` resolution and validation:

```python
    if from_date is None:
        from_date = date.today()
    if from_date < primary_a.start_date or from_date >= primary_a.end_date:
        raise GimelimError("date_out_of_range")
```

In the `payload` dict construction (around line 382-399), add a new entry alongside `"rest_days": rest_days,`:

```python
        "from_date": from_date.isoformat(),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/unit/test_gimelim_service.py -k "from_date" -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full gimelim unit test file to check for regressions**

Run: `pytest backend/tests/unit/test_gimelim_service.py -v`
Expected: PASS (all tests, including the pre-existing ones — they don't pass `from_date`, so it must default cleanly)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gimelim.py backend/tests/unit/test_gimelim_service.py
git commit -m "feat: preview_gimelim accepts a backdated from_date"
```

---

### Task 2: `commit_gimelim` uses the stored `from_date` instead of shift start

**Files:**
- Modify: `backend/app/services/gimelim.py:447-521` (`commit_gimelim`)
- Test: `backend/tests/unit/test_gimelim_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_gimelim_service.py`, in the "Commit tests" section, after `test_commit_full_flow`:

```python
def test_commit_uses_backdated_from_date(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd9", "ActorFD9")
    soldier_a = _make_soldier(admin_session, "gimfd9", "A")
    soldier_b = _make_soldier(admin_session, "gimfd10", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 10), end=date(2026, 6, 15),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    backdated = date(2026, 6, 11)
    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="medical leave",
        actor_id=actor.id,
        from_date=backdated,
    )

    result = commit_gimelim(
        admin_session,
        shift_id=shift.id,
        preview_token=preview.preview_token,
        actor_id=actor.id,
    )

    admin_session.refresh(reserve)
    assert reserve.called_up_from == backdated
    assert reserve.called_up_to == date(2026, 6, 14)  # shift.end_date - 1 day, unchanged

    dismissal = admin_session.get(DutyDismissal, result.dismissal_id)
    assert dismissal.dismissed_from == backdated
    assert dismissal.dismissed_to == date(2026, 6, 14)
```

Add `DutyDismissal` to the existing import block at the top of the file (it currently imports `DutyAssignment, DutyLocation, DutyReserveLink, DutyShift, DutyType, HierarchyNode, Soldier, SystemSetting` from `app.db.models` — add `DutyDismissal` to that list).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_gimelim_service.py -k test_commit_uses_backdated_from_date -v`
Expected: FAIL — `assert reserve.called_up_from == backdated` fails because `called_up_from` is still `primary.start_date` (2026-06-10)

- [ ] **Step 3: Implement — read `from_date` from the payload in `commit_gimelim`**

In `backend/app/services/gimelim.py`, inside `commit_gimelim` (around line 488-489), add:

```python
    rest_days: int = payload["rest_days"]
    reason: str | None = payload["reason"]
    from_date_stored = date.fromisoformat(payload["from_date"])
    notifications_queued = 0
```

Then update the `dismiss_primary` call (around line 492-500) to use it:

```python
    # ── Step 1: Dismiss primary A ──────────────────────────────────────────
    dismissal = dismiss_primary(
        session,
        assignment=primary_a,
        from_date=from_date_stored,
        to_date=primary_a.end_date - timedelta(days=1),
        reason=reason,
        actor_id=actor_id,
    )
```

And the `call_up_reserve` call (around line 513-521):

```python
    # ── Step 2: Call up reserve B ──────────────────────────────────────────
    call_up_last = primary_a.end_date - timedelta(days=1)
    call_up_reserve(
        session,
        assignment=reserve_b,
        from_date=from_date_stored,
        to_date=call_up_last,
        actor_id=actor_id,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/unit/test_gimelim_service.py -k test_commit_uses_backdated_from_date -v`
Expected: PASS

- [ ] **Step 5: Run the full gimelim unit test file to check for regressions**

Run: `pytest backend/tests/unit/test_gimelim_service.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gimelim.py backend/tests/unit/test_gimelim_service.py
git commit -m "feat: commit_gimelim dismisses and calls up from the chosen from_date"
```

---

### Task 3: Wire `from_date` through the route schema and add an integration test

**Files:**
- Modify: `backend/app/routes/gimelim.py:52-56` (`GimelimPreviewRequest`), `backend/app/routes/gimelim.py:173-181` (`preview_gimelim_route`)
- Test: `backend/tests/integration/test_gimelim_api.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_gimelim_api.py`, after `test_preview_then_commit`:

```python
# ── Test: from_date defaults to today, and rejects out-of-range values ───────

def test_preview_from_date_out_of_range_returns_400(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="branch", name="n_gim006")
    admin = create_soldier(admin_session, personal_number="gim006_adm", role="admin", hierarchy_node_id=node.id)
    soldier_a = create_soldier(admin_session, personal_number="gim006_a", hierarchy_node_id=node.id)
    soldier_b = create_soldier(admin_session, personal_number="gim006_b", hierarchy_node_id=node.id)
    dt, loc = _make_dt_loc(admin_session, "gim006")
    shift = _make_shift(admin_session, dt, loc, "2030-09-01", "2030-09-05")
    primary_a = _make_assignment(admin_session, soldier_a.id, dt, loc, shift, is_reserve=False)
    reserve_b = _make_assignment(admin_session, soldier_b.id, dt, loc, shift, is_reserve=True)
    _link_reserve(admin_session, primary_a, reserve_b)
    admin_session.commit()

    resp = client.post(
        f"/api/shifts/{shift.id}/gimelim/preview",
        json={
            "primary_assignment_id": str(primary_a.id),
            "reason": "medical leave",
            "from_date": "2030-08-31",  # before shift start
        },
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400
    assert "date_out_of_range" in resp.json()["detail"]


def test_preview_then_commit_with_backdated_from_date(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="branch", name="n_gim007")
    admin = create_soldier(admin_session, personal_number="gim007_adm", role="admin", hierarchy_node_id=node.id)
    soldier_a = create_soldier(admin_session, personal_number="gim007_a", hierarchy_node_id=node.id)
    soldier_b = create_soldier(admin_session, personal_number="gim007_b", hierarchy_node_id=node.id)
    dt, loc = _make_dt_loc(admin_session, "gim007")
    shift = _make_shift(admin_session, dt, loc, "2030-10-01", "2030-10-05")
    primary_a = _make_assignment(admin_session, soldier_a.id, dt, loc, shift, is_reserve=False)
    reserve_b = _make_assignment(admin_session, soldier_b.id, dt, loc, shift, is_reserve=True)
    _link_reserve(admin_session, primary_a, reserve_b)
    admin_session.commit()

    preview_resp = client.post(
        f"/api/shifts/{shift.id}/gimelim/preview",
        json={
            "primary_assignment_id": str(primary_a.id),
            "reason": "medical leave",
            "from_date": "2030-10-02",
        },
        headers=auth_headers(admin),
    )
    assert preview_resp.status_code == 200, preview_resp.text
    token = preview_resp.json()["preview_token"]

    commit_resp = client.post(
        f"/api/shifts/{shift.id}/gimelim/commit",
        json={"preview_token": token},
        headers=auth_headers(admin),
    )
    assert commit_resp.status_code == 200, commit_resp.text

    admin_session.refresh(reserve_b)
    assert str(reserve_b.called_up_from) == "2030-10-02"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/integration/test_gimelim_api.py -k from_date -v`
Expected: FAIL — `test_preview_from_date_out_of_range_returns_400` gets 200 instead of 400 (no validation yet); `test_preview_then_commit_with_backdated_from_date` fails the `called_up_from` assertion (still defaults to shift start)

- [ ] **Step 3: Add `from_date` to the route schema**

In `backend/app/routes/gimelim.py`, update `GimelimPreviewRequest` (around line 52-56):

```python
class GimelimPreviewRequest(BaseModel):
    primary_assignment_id: uuid.UUID
    rest_days: int = Field(default=7, ge=0, le=365)
    reason: str | None = Field(default=None, max_length=1000)
    from_date: date | None = None
```

Update `preview_gimelim_route` (around line 173-181) to pass it through:

```python
    try:
        preview = svc.preview_gimelim(
            session,
            shift_id=shift_id,
            primary_assignment_id=body.primary_assignment_id,
            rest_days=body.rest_days,
            reason=body.reason,
            actor_id=user.id,
            from_date=body.from_date,
        )
    except GimelimError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/integration/test_gimelim_api.py -k from_date -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full gimelim integration test file to check for regressions**

Run: `pytest backend/tests/integration/test_gimelim_api.py -v`
Expected: PASS (all tests — the pre-existing tests omit `from_date` and must still default to today cleanly)

- [ ] **Step 6: Run the full backend test suite for the `duty` area**

Run: `pytest -m duty -q`
Expected: PASS (gimelim tests are tagged under the `duty` marker per `backend/pyproject.toml`)

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/gimelim.py backend/tests/integration/test_gimelim_api.py
git commit -m "feat: expose gimelim from_date through the preview API"
```

---

## Frontend

### Task 4: Add `from_date` to the `previewGimelim` API wrapper

**Files:**
- Modify: `frontend/src/api/gimelim.ts:45-50`

- [ ] **Step 1: Update the function signature**

In `frontend/src/api/gimelim.ts`, change:

```ts
export async function previewGimelim(
  shiftId: string,
  body: { primary_assignment_id: string; rest_days: number; reason?: string }
): Promise<GimelimPreview> {
  return (await api.post<GimelimPreview>(`/shifts/${shiftId}/gimelim/preview`, body)).data;
}
```

to:

```ts
export async function previewGimelim(
  shiftId: string,
  body: { primary_assignment_id: string; rest_days: number; reason?: string; from_date: string }
): Promise<GimelimPreview> {
  return (await api.post<GimelimPreview>(`/shifts/${shiftId}/gimelim/preview`, body)).data;
}
```

- [ ] **Step 2: Verify the project still typechecks**

Run (from `frontend/`): `npx tsc --noEmit -p .`
Expected: One error in `frontend/src/components/GimelimModal.tsx` — `Property 'from_date' is missing in type`. This is expected; `GimelimModal.tsx` is deleted in Task 5/7, so the error will disappear once that happens. Confirm no *other* file errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/gimelim.ts
git commit -m "feat: previewGimelim sends a from_date"
```

---

### Task 5: Merge gimelim flow into `DismissalModal.tsx` behind a mode toggle

**Files:**
- Modify: `frontend/src/components/DismissalModal.tsx` (full rewrite)

- [ ] **Step 1: Replace the file contents**

Replace the entire contents of `frontend/src/components/DismissalModal.tsx` with:

```tsx
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarShift, CalendarShiftAssignee } from "../api/calendar";
import { dismissAndReallocate } from "../api/reserves";
import {
  previewGimelim,
  commitGimelim,
  uploadGimelimAttachment,
  GimelimPreview,
} from "../api/gimelim";
import Combobox from "./Combobox";
import SoldierLink from "./SoldierLink";

interface Props {
  shift: CalendarShift;
  primary: CalendarShiftAssignee;
  canGimelim: boolean;
  defaultRestDays: number;
  onClose: () => void;
  onDone: () => void;
}

const DAY_NAMES = ["א", "ב", "ג", "ד", "ה", "ו", "ש"];
const ALLOWED_TYPES = new Set(["application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"]);
const MAX_BYTES = 20 * 1024 * 1024;

type Mode = "regular" | "gimelim";
type GimelimStep = "form" | "preview";

export default function DismissalModal({
  shift,
  primary,
  canGimelim,
  defaultRestDays,
  onClose,
  onDone,
}: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const allDates = useMemo(() => {
    const dates: string[] = [];
    const d = new Date(shift.start_date);
    const stop = new Date(shift.end_date);
    while (d <= stop) {
      dates.push(d.toISOString().slice(0, 10));
      d.setDate(d.getDate() + 1);
    }
    return dates;
  }, [shift.start_date, shift.end_date]);

  // Index of the last day a gimelim "from" can be (shift.end_date - 1 day).
  const lastGimelimFromIdx = Math.max(allDates.length - 2, 0);

  const [mode, setMode] = useState<Mode>("regular");

  // ── Regular mode state ──────────────────────────────────────────────────
  const [fromIdx, setFromIdx] = useState<number | null>(0);
  const [toIdx, setToIdx] = useState<number | null>(allDates.length - 1);
  const [selectedReserveId, setSelectedReserveId] = useState(primary.reserve_assignment_id ?? "");

  // ── Shared ───────────────────────────────────────────────────────────────
  const [reason, setReason] = useState("");
  const [reasonTouched, setReasonTouched] = useState(false);

  // ── Gimelim mode state ──────────────────────────────────────────────────
  const initialGimelimFromIdx = useMemo(() => {
    const todayStr = new Date().toISOString().slice(0, 10);
    const idx = allDates.indexOf(todayStr);
    if (idx === -1) return 0;
    return Math.min(idx, lastGimelimFromIdx);
  }, [allDates, lastGimelimFromIdx]);
  const [gimelimFromIdx, setGimelimFromIdx] = useState(initialGimelimFromIdx);
  const [restDays, setRestDays] = useState(defaultRestDays);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [gimelimStep, setGimelimStep] = useState<GimelimStep>("form");
  const [preview, setPreview] = useState<GimelimPreview | null>(null);

  const reserveOptions = useMemo(
    () => shift.assignees.filter(a => a.is_reserve && a.assignment_id && !a.called_up_from),
    [shift.assignees]
  );

  useMemo(() => {
    if (!selectedReserveId && primary.reserve_assignment_id) {
      setSelectedReserveId(primary.reserve_assignment_id);
    } else if (!selectedReserveId && reserveOptions.length > 0) {
      setSelectedReserveId(reserveOptions[0].assignment_id ?? "");
    }
  }, [primary.reserve_assignment_id, reserveOptions, selectedReserveId]);

  const fromDate = fromIdx !== null ? allDates[fromIdx] : null;
  const toDate = toIdx !== null ? allDates[toIdx] : null;

  function handleDateClick(i: number) {
    if (fromIdx === null || toIdx === null) {
      setFromIdx(i);
      setToIdx(i);
    } else if (i < fromIdx) {
      setFromIdx(i);
    } else if (i > toIdx) {
      setToIdx(i);
    } else if (i === fromIdx && i === toIdx) {
      return;
    } else {
      const dFrom = Math.abs(i - fromIdx);
      const dTo = Math.abs(i - toIdx);
      if (dFrom <= dTo) setFromIdx(i);
      else setToIdx(i);
    }
  }

  const reasonEmpty = reason.trim() === "";
  const showReasonError = mode === "gimelim" && reasonTouched && reasonEmpty;

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setFileError(null);
    if (!f) { setSelectedFile(null); return; }
    if (!ALLOWED_TYPES.has(f.type)) {
      setFileError("סוג קובץ לא נתמך — יש להעלות PDF, JPG, PNG, GIF או WEBP");
      setSelectedFile(null);
      e.target.value = "";
      return;
    }
    if (f.size > MAX_BYTES) {
      setFileError("הקובץ גדול מדי — מקסימום 20 MB");
      setSelectedFile(null);
      e.target.value = "";
      return;
    }
    setSelectedFile(f);
  }

  const mutation = useMutation({
    mutationFn: () =>
      dismissAndReallocate(shift.id, {
        primary_assignment_id: primary.assignment_id,
        covering_reserve_assignment_id: selectedReserveId,
        from_date: fromDate ?? shift.start_date,
        to_date: toDate ?? shift.end_date,
        reason: reason || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendarShifts"] });
      onDone();
    },
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      previewGimelim(shift.id, {
        primary_assignment_id: primary.assignment_id,
        rest_days: restDays,
        reason: reason.trim(),
        from_date: allDates[gimelimFromIdx],
      }),
    onSuccess: (data) => {
      setPreview(data);
      setGimelimStep("preview");
    },
  });

  const commitMutation = useMutation({
    mutationFn: () => commitGimelim(shift.id, preview!.preview_token),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["calendarShifts"] });
      onDone();
      if (selectedFile && result.dismissal_id) {
        uploadGimelimAttachment(result.dismissal_id, selectedFile).catch(() => {
          // Silent — attachment upload failure doesn't block the gimelim action
        });
      }
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      const detail = err?.response?.data?.detail ?? "";
      if (detail.includes("stale") || detail.includes("expired")) {
        setGimelimStep("form");
        setPreview(null);
      }
    },
  });

  const tokenExpiresAt = preview ? new Date(preview.preview_token_expires_at) : null;

  function handlePreviewClick() {
    setReasonTouched(true);
    if (reasonEmpty) return;
    previewMutation.mutate();
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-lg w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-5">
          <div>
            <h3 className="font-bold text-lg">
              {mode === "gimelim" ? "🏥 שחרור גימלים" : t("dismiss_modal.title")}
            </h3>
            <p className="text-sm text-gray-500 mt-0.5">{primary.soldier_name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none p-1">✕</button>
        </div>

        {canGimelim && (
          <div className="flex gap-1 mb-5 bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
            <button
              type="button"
              onClick={() => setMode("regular")}
              className={`flex-1 text-sm py-1.5 rounded-md transition-colors ${mode === "regular" ? "bg-white dark:bg-gray-800 shadow font-medium" : "text-gray-500"}`}
            >
              {t("dismiss_modal.mode_regular")}
            </button>
            <button
              type="button"
              onClick={() => setMode("gimelim")}
              className={`flex-1 text-sm py-1.5 rounded-md transition-colors ${mode === "gimelim" ? "bg-white dark:bg-gray-800 shadow font-medium text-red-700" : "text-gray-500"}`}
            >
              {t("dismiss_modal.mode_gimelim")}
            </button>
          </div>
        )}

        {mode === "regular" && (
          <>
            <div className="mb-5">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-2 block">{t("dismiss_modal.date_range")}</label>
              <div className="flex flex-wrap gap-1.5 justify-center">
                {allDates.map((d, i) => {
                  const dt = new Date(d);
                  const dayName = DAY_NAMES[dt.getDay()];
                  const dayNum = dt.getDate();
                  const isStart = fromIdx === i;
                  const isEnd = toIdx === i;
                  const isSelected = fromIdx !== null && toIdx !== null && i >= fromIdx && i <= toIdx;
                  const isRange = isSelected && !isStart && !isEnd;
                  return (
                    <button
                      key={d}
                      type="button"
                      onClick={() => handleDateClick(i)}
                      className={`flex flex-col items-center rounded-lg px-2.5 py-1.5 text-xs min-w-[48px] transition-colors
                        ${isStart || isEnd
                          ? "bg-amber-500 text-white shadow-md font-bold"
                          : isRange
                            ? "bg-amber-100 text-amber-900"
                            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                        }`}
                    >
                      <span className="text-[10px] opacity-70">{dayName}</span>
                      <span className="text-sm font-medium">{dayNum}</span>
                    </button>
                  );
                })}
              </div>
              <div className="flex justify-center gap-6 mt-3 text-sm text-gray-600 dark:text-gray-300">
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm bg-amber-500 inline-block" />
                  {t("dismiss_modal.from")}: <span className="font-medium text-gray-800" dir="ltr">{fromDate}</span>
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm bg-amber-500 inline-block" />
                  {t("dismiss_modal.to")}: <span className="font-medium text-gray-800" dir="ltr">{toDate}</span>
                </span>
              </div>
            </div>

            <div className="mb-4">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-1.5 block">{t("dismiss_modal.covering_reserve")}</label>
              {reserveOptions.length === 0 ? (
                <p className="text-sm text-gray-400 italic">{t("dismiss_modal.no_reserves")}</p>
              ) : (
                <Combobox
                  items={reserveOptions.map(a => ({
                    id: a.assignment_id,
                    name: a.soldier_name + (a.assignment_id === primary.reserve_assignment_id ? ` (${t("reserve_standby")})` : ""),
                  }))}
                  value={selectedReserveId}
                  onChange={setSelectedReserveId}
                />
              )}
            </div>

            <div className="mb-4">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-1.5 block">{t("dismiss_modal.reason")}</label>
              <input
                className="border border-gray-300 dark:border-gray-600 rounded-lg p-2 w-full text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-amber-300 focus:border-amber-400 outline-none"
                value={reason}
                onChange={e => setReason(e.target.value)}
                placeholder={t("dismiss_modal.reason_placeholder")}
              />
            </div>

            {mutation.isError && (
              <div className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg p-3 mb-4">
                <p className="text-red-600 text-sm">
                  {(mutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? t("dismiss_modal.error")}
                </p>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                {t("dismiss_modal.cancel")}
              </button>
              <button
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending || selectedReserveId === ""}
                className="px-4 py-2 text-sm bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {mutation.isPending ? (
                  <span className="flex items-center gap-1.5">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    {t("dismiss_modal.submitting")}
                  </span>
                ) : t("dismiss_modal.confirm")}
              </button>
            </div>
          </>
        )}

        {mode === "gimelim" && gimelimStep === "form" && (
          <>
            <div className="mb-5">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-2 block">{t("dismiss_modal.date_range")}</label>
              <div className="flex flex-wrap gap-1.5 justify-center">
                {allDates.slice(0, -1).map((d, i) => {
                  const dt = new Date(d);
                  const dayName = DAY_NAMES[dt.getDay()];
                  const dayNum = dt.getDate();
                  const isSelected = gimelimFromIdx === i;
                  return (
                    <button
                      key={d}
                      type="button"
                      onClick={() => setGimelimFromIdx(i)}
                      className={`flex flex-col items-center rounded-lg px-2.5 py-1.5 text-xs min-w-[48px] transition-colors
                        ${isSelected ? "bg-red-500 text-white shadow-md font-bold" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
                    >
                      <span className="text-[10px] opacity-70">{dayName}</span>
                      <span className="text-sm font-medium">{dayNum}</span>
                    </button>
                  );
                })}
              </div>
              <div className="flex justify-center gap-6 mt-3 text-sm text-gray-600 dark:text-gray-300">
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm bg-red-500 inline-block" />
                  {t("dismiss_modal.from")}: <span className="font-medium text-gray-800" dir="ltr">{allDates[gimelimFromIdx]}</span>
                </span>
                <span className="flex items-center gap-1.5 text-gray-400">
                  {t("dismiss_modal.to")}: <span className="font-medium" dir="ltr">{allDates[allDates.length - 1]}</span>
                </span>
              </div>
            </div>

            <div className="mb-4">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-1.5 block">
                ימי מנוחה לפני שיבוץ מחדש
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={365}
                  value={restDays}
                  onChange={(e) => setRestDays(Number(e.target.value))}
                  className="w-24 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-1.5 text-sm bg-white dark:bg-gray-700 dark:text-gray-100 text-center focus:ring-2 focus:ring-red-300 outline-none"
                  dir="ltr"
                />
                <span className="text-sm text-gray-500">ימים</span>
              </div>
              <p className="text-xs text-gray-400 mt-1">
                המינימום ממועד סיום התורנות הנוכחית עד לתורנות שיושב בה החייל
              </p>
            </div>

            <div className="mb-4">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-1.5 block">
                סיבה <span className="text-red-500">*</span>
                <span className="font-normal text-gray-400 mr-1">(גלויה למנהלים בלבד)</span>
              </label>
              <textarea
                className={`border rounded-lg p-2 w-full text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 outline-none resize-none transition-colors ${
                  showReasonError
                    ? "border-red-400 focus:ring-red-300"
                    : "border-gray-300 dark:border-gray-600 focus:ring-red-300"
                }`}
                rows={2}
                value={reason}
                onChange={(e) => { setReason(e.target.value); setReasonTouched(true); }}
                onBlur={() => setReasonTouched(true)}
                placeholder="פרטים רפואיים (לא מועברים לחיילים אחרים)"
              />
              {showReasonError && (
                <p className="text-xs text-red-500 mt-1">חובה למלא סיבה לפני הגשת הבקשה</p>
              )}
            </div>

            <div className="mb-5">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-1.5 block">
                צירוף מסמך <span className="text-gray-400 font-normal">(אופציונלי — לזיכרון ארגוני)</span>
              </label>
              <div
                className="flex items-center gap-2 border border-dashed border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 cursor-pointer hover:border-red-300 transition-colors"
                onClick={() => fileInputRef.current?.click()}
              >
                <span className="text-gray-400 text-sm">{selectedFile ? `📎 ${selectedFile.name}` : "לחץ לבחירת קובץ..."}</span>
                {selectedFile && (
                  <button
                    type="button"
                    className="mr-auto text-gray-400 hover:text-red-500 text-xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedFile(null);
                      if (fileInputRef.current) fileInputRef.current.value = "";
                    }}
                  >
                    ✕
                  </button>
                )}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.gif,.webp"
                className="hidden"
                onChange={handleFileChange}
              />
              {fileError && <p className="text-xs text-red-500 mt-1">{fileError}</p>}
              <p className="text-xs text-gray-400 mt-1">PDF, JPG, PNG, GIF, WEBP — עד 20 MB</p>
            </div>

            {previewMutation.isError && (
              <div className="bg-red-50 dark:bg-red-950 border border-red-200 rounded-lg p-3 mb-4 text-sm text-red-700">
                {(previewMutation.error as { response?: { data?: { detail?: string } } })
                  ?.response?.data?.detail ?? "שגיאה בחישוב ההצעה"}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-300 hover:bg-gray-50 transition-colors"
              >
                ביטול
              </button>
              <button
                onClick={handlePreviewClick}
                disabled={previewMutation.isPending}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-40 transition-colors shadow-sm"
              >
                {previewMutation.isPending ? "מחשב..." : "חשב הצעה ⟶"}
              </button>
            </div>
          </>
        )}

        {mode === "gimelim" && gimelimStep === "preview" && preview && (
          <>
            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 mb-3 text-sm space-y-1">
              <div className="font-semibold text-gray-700 dark:text-gray-200 mb-1">
                ⬛ תורנות נוכחית — {preview.current_shift.duty_type_name}
              </div>
              <div>
                <span className="text-gray-500">משוחרר:</span>{" "}
                <SoldierLink id={preview.soldier_a.id} name={preview.soldier_a.name} />
                {" "}({preview.current_shift.start_date} — {preview.current_shift.end_date})
              </div>
              <div>
                <span className="text-gray-500">מוקפץ לכיסוי:</span>{" "}
                <SoldierLink id={preview.reserve_soldier.id} name={preview.reserve_soldier.name} />
              </div>
            </div>

            {preview.future_assignment ? (
              <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 mb-3 text-sm space-y-1">
                <div className="font-semibold text-gray-700 dark:text-gray-200 mb-1">
                  ⬛ תורנות עתידית —{" "}
                  {preview.future_assignment.shift.duty_type_name}{" "}
                  ({preview.future_assignment.shift.start_date})
                </div>
                <div>
                  <span className="text-gray-500">ממומר לרזרבה:</span>{" "}
                  <SoldierLink
                    id={preview.future_assignment.soldier_demoted.id}
                    name={preview.future_assignment.soldier_demoted.name}
                  />
                </div>
                <div>
                  <span className="text-gray-500">נכנס כראשוני:</span>{" "}
                  <SoldierLink id={preview.soldier_a.id} name={preview.soldier_a.name} />
                </div>
                {preview.future_assignment.c_existing_reserve_soldier && (
                  <div>
                    <span className="text-gray-500">רזרבה כללית נשארת:</span>{" "}
                    <SoldierLink
                      id={preview.future_assignment.c_existing_reserve_soldier.id}
                      name={preview.future_assignment.c_existing_reserve_soldier.name}
                    />
                  </div>
                )}
              </div>
            ) : (
              <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg p-3 mb-3 text-sm text-amber-800 dark:text-amber-200">
                ⚠️ לא נמצאה תורנות עתידית מתאימה. הגימלים יבוצע ללא שיבוץ מחדש אוטומטי — ניתן לשבץ ידנית לאחר מכן.
              </div>
            )}

            {preview.warnings.filter(w => w !== "no_future_slot_found").map((w) => (
              <div key={w} className="text-xs text-amber-600 mb-2">⚠️ {w}</div>
            ))}

            {selectedFile && (
              <p className="text-xs text-gray-500 mb-2">📎 {selectedFile.name} יצורף לאחר האישור</p>
            )}

            {tokenExpiresAt && (
              <p className="text-xs text-gray-400 mb-3 text-left" dir="ltr">
                ההצעה תקפה עד {tokenExpiresAt.toLocaleTimeString("he-IL")}
              </p>
            )}

            {commitMutation.isError && (
              <div className="bg-red-50 dark:bg-red-950 border border-red-200 rounded-lg p-3 mb-3 text-sm text-red-700">
                {(commitMutation.error as { response?: { data?: { detail?: string } } })
                  ?.response?.data?.detail ?? "שגיאה בביצוע"}
                {String(
                  (commitMutation.error as { response?: { data?: { detail?: string } } })
                    ?.response?.data?.detail ?? ""
                ).includes("stale") && " — הנתונים השתנו, יש לחשב מחדש"}
              </div>
            )}

            <div className="flex flex-wrap justify-between gap-2 pt-1">
              <button
                onClick={() => { setGimelimStep("form"); setPreview(null); }}
                className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-300 hover:bg-gray-50 transition-colors"
              >
                ⟵ חזור לעריכה
              </button>
              <button
                onClick={() => commitMutation.mutate()}
                disabled={commitMutation.isPending}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-40 transition-colors shadow-sm"
              >
                {commitMutation.isPending ? (
                  <span className="flex items-center gap-1.5">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    מבצע...
                  </span>
                ) : "אשר ובצע ✓"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/DismissalModal.tsx
git commit -m "feat: merge gimelim flow into DismissalModal behind a mode toggle"
```

(`tsc`/lint are checked in Task 6, once `ShiftDetailPanel.tsx` passes the new props — `DismissalModal.tsx` alone will fail to compile in isolation because nothing supplies `canGimelim`/`defaultRestDays` yet, which is expected mid-refactor.)

---

### Task 6: Update `ShiftDetailPanel.tsx` to use the merged modal and drop the gimelim button

**Files:**
- Modify: `frontend/src/components/ShiftDetailPanel.tsx`

- [ ] **Step 1: Remove the `GimelimModal` import and `gimelimTarget` state**

Delete line 14 (`import GimelimModal from "./GimelimModal";`).

Delete this line from the state block (line 57):

```tsx
  const [gimelimTarget, setGimelimTarget] = useState<CalendarShiftAssignee | null>(null);
```

Keep `gimelimEnabled` and `gimelimDefaultRestDays` (still needed — they now feed `canGimelim`/`defaultRestDays` on the merged modal).

- [ ] **Step 2: Remove the separate "גימלים 🏥" button**

In the primaries-rendering block, delete this block (currently lines 231-238):

```tsx
                        {gimelimEnabled && !a.is_reserve && (user?.role === "duty_manager" || user?.role === "admin") && (
                          <button
                            className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded hover:bg-red-200"
                            onClick={() => setGimelimTarget(a)}
                          >
                            גימלים 🏥
                          </button>
                        )}
```

- [ ] **Step 3: Update the `dismiss_action` button to also gate gimelim availability**

The existing button (currently lines 225-230):

```tsx
                        <button
                          className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded hover:bg-amber-200"
                          onClick={() => setDismissTarget(a)}
                        >
                          {t("dismiss_action")}
                        </button>
```

stays exactly as-is — `setDismissTarget(a)` already opens the modal we're about to update in Step 4. No change needed here; the toggle for גימלים now lives inside the modal itself.

- [ ] **Step 4: Pass the new props to `DismissalModal`**

Replace the `DismissalModal` render block (currently lines 380-387):

```tsx
        {dismissTarget && (
          <DismissalModal
            shift={shift}
            primary={dismissTarget}
            onClose={() => setDismissTarget(null)}
            onDone={() => { setDismissTarget(null); onRefreshNeeded(); }}
          />
        )}
```

with:

```tsx
        {dismissTarget && (
          <DismissalModal
            shift={shift}
            primary={dismissTarget}
            canGimelim={
              gimelimEnabled &&
              !dismissTarget.is_reserve &&
              (user?.role === "duty_manager" || user?.role === "admin")
            }
            defaultRestDays={gimelimDefaultRestDays}
            onClose={() => setDismissTarget(null)}
            onDone={() => { setDismissTarget(null); onRefreshNeeded(); }}
          />
        )}
```

- [ ] **Step 5: Remove the now-dead `GimelimModal` render block**

Delete this block (currently lines 398-409):

```tsx
        {gimelimTarget && (
          <GimelimModal
            shiftId={shift.id}
            primary={gimelimTarget}
            defaultRestDays={gimelimDefaultRestDays}
            onClose={() => setGimelimTarget(null)}
            onDone={() => {
              setGimelimTarget(null);
              onRefreshNeeded();
            }}
          />
        )}
```

- [ ] **Step 6: Verify the project typechecks**

Run (from `frontend/`): `npx tsc --noEmit -p .`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ShiftDetailPanel.tsx
git commit -m "feat: open the merged dismissal/gimelim modal from a single button"
```

---

### Task 7: Delete `GimelimModal.tsx` and add the toggle i18n keys

**Files:**
- Delete: `frontend/src/components/GimelimModal.tsx`
- Modify: `frontend/src/i18n/he.json:698-711`

- [ ] **Step 1: Confirm nothing else references `GimelimModal`**

Run: `grep -rn "GimelimModal" frontend/src`
Expected: No output (Task 6 removed the only import/usage).

- [ ] **Step 2: Delete the file**

```bash
git rm frontend/src/components/GimelimModal.tsx
```

- [ ] **Step 3: Add the mode-toggle i18n keys**

In `frontend/src/i18n/he.json`, update the `dismiss_modal` block (currently lines 698-711) to add `mode_regular` and `mode_gimelim`:

```json
  "dismiss_modal": {
    "title": "שחרור מתורנות",
    "date_range": "טווח תאריכים",
    "from": "מ",
    "to": "עד",
    "covering_reserve": "רזרבה מכסה",
    "no_reserves": "אין רזרבות זמינות",
    "reason": "סיבה",
    "reason_placeholder": "הכנס סיבה לשחרור...",
    "error": "שגיאה בשחרור התורנות",
    "cancel": "ביטול",
    "submitting": "שולח...",
    "confirm": "אשר שחרור",
    "mode_regular": "רגיל",
    "mode_gimelim": "גימלים"
  },
```

- [ ] **Step 4: Run lint and typecheck**

Run (from `frontend/`): `npm run lint`
Expected: 0 warnings, 0 errors.

Run (from `frontend/`): `npx tsc --noEmit -p .`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "chore: remove standalone GimelimModal, add mode-toggle labels"
```

---

## Final verification

### Task 8: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend `duty`-area suite**

Run: `pytest -m duty -q`
Expected: PASS

- [ ] **Step 2: Run the fast backend suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 3: Run frontend lint**

Run (from `frontend/`): `npm run lint`
Expected: 0 warnings, 0 errors

- [ ] **Step 4: Run frontend unit tests**

Run (from `frontend/`): `npm test`
Expected: PASS

- [ ] **Step 5: Manually smoke-test in the dev stack**

Start `.\dev.ps1`, open a shift detail panel for a primary soldier with a linked reserve, click "שחרור": confirm the mode toggle appears (for a duty_manager/admin account with gimelim enabled), switch to "גימלים", confirm "from" defaults to today and can be moved to an earlier day within the shift, "to" is locked to the shift's last day, and the preview/commit/file-upload flow completes successfully. Then confirm the regular ("רגיל") flow still works unchanged, and that a non-duty_manager/admin account sees no toggle at all.
