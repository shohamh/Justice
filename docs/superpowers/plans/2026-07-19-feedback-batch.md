# Feedback Batch (2026-07-16..19) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 15 reported feedback items — 7 bugs, 4 small settings/features, and 3 larger workflow changes — on one feature branch off `dev`, merged in a single pass.

**Architecture:** Backend is FastAPI + SQLAlchemy (`backend/app/routes` → `backend/app/services` → `backend/app/db/models.py`), no ORM logic in `routes`. Frontend is React + TypeScript + react-query (`frontend/src/pages`, `frontend/src/components`, `frontend/src/api`). i18n via `frontend/src/i18n/he.json` + `react-i18next`.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / Alembic / pytest. React / Vite / TypeScript / vitest / Tailwind.

## Global Constraints

- Branch: `feedback-batch-2026-07-19` (already created off `dev`). Do not merge to `dev` directly — use the `merge-worktree-to-dev` skill when all tasks are done.
- Backend tests: `pytest -q` (fast suite) from `backend/`, venv activated first. Only run tests scoped to the area you're touching per task; full suite is a final check, not a per-task gate.
- Frontend tests: `npm test` (vitest) from `frontend/`. `npm run typecheck` after any `.ts`/`.tsx` change.
- Rank strings, notification types, and system-setting keys must match exact existing string values in `backend/app/db/models.py` / `backend/app/services/eligibility.py` — copied verbatim below.
- Every new/changed system setting must appear in `frontend/src/pages/SystemSettingsPage.tsx`'s `SETTING_GROUPS`.
- Hebrew-only UI strings; no English leaking into user-facing text.

---

## Task A1: Chovah/קבע consistency — derive `is_career`, block invalid rank/status combos

**Files:**
- Modify: `backend/app/services/eligibility.py` (add `CHOVAH_ONLY_RANKS`, add `derive_is_career`)
- Modify: `backend/app/services/soldiers.py:33-45` (`_check_soldier_dates`), `:205-225` (`update_soldier_profile`), `:284-` (`approve_field_update`)
- Modify: `backend/app/routes/enrollment.py` (remove `is_career` from `PatchEnrollmentBody`)
- Modify: `frontend/src/pages/RegisterPage.tsx` (remove the is_career checkbox; always register חובה)
- Modify: `backend/app/services/registration.py` (drop `is_career` param, always `False` at registration)
- Test: `backend/app/services/tests/test_soldiers.py`, `backend/app/services/tests/test_eligibility.py` (create if missing — check `backend/app/services/tests/` for an existing `test_eligibility.py` first; if absent, create it)

**Interfaces:**
- Produces: `eligibility.CHOVAH_ONLY_RANKS: list[str]`, `eligibility.derive_is_career(rank: str | None, mandatory_end_date: date | None, discharge_date: date | None, today: date | None = None) -> bool`
- Consumes: existing `soldiers.SoldierValidationError`, `soldiers._check_soldier_dates`

- [ ] **Step 1: Write the failing test for `derive_is_career`**

```python
# backend/app/services/tests/test_eligibility.py  (create if it doesn't exist)
from __future__ import annotations
from datetime import date


def test_derive_is_career_false_before_mandatory_end():
    from app.services.eligibility import derive_is_career
    assert derive_is_career(
        rank="טוראי", mandatory_end_date=date(2027, 1, 1), discharge_date=None,
        today=date(2026, 7, 19),
    ) is False


def test_derive_is_career_true_after_mandatory_end_no_discharge():
    from app.services.eligibility import derive_is_career
    assert derive_is_career(
        rank="רסן", mandatory_end_date=date(2025, 1, 1), discharge_date=None,
        today=date(2026, 7, 19),
    ) is True


def test_derive_is_career_false_when_discharged_before_mandatory_end():
    from app.services.eligibility import derive_is_career
    assert derive_is_career(
        rank="רסן", mandatory_end_date=date(2027, 1, 1), discharge_date=date(2026, 6, 1),
        today=date(2026, 7, 19),
    ) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_eligibility.py -v`
Expected: FAIL — `ImportError: cannot import name 'derive_is_career'`

- [ ] **Step 3: Implement `derive_is_career` and `CHOVAH_ONLY_RANKS`**

```python
# backend/app/services/eligibility.py — add near inferred_service_type (after line 24's ALL_RANKS)
CHOVAH_ONLY_RANKS = ["טוראי", "רבט", "סמל", "סגמ", "קמא"]


def derive_is_career(
    rank: str | None,
    mandatory_end_date: "date | None",
    discharge_date: "date | None",
    today: "date | None" = None,
) -> bool:
    """A soldier is קבע once their mandatory (חובה) service has ended and no
    discharge closed it out first — mirrors inferred_service_type's rule.
    Never true while holding a חובה-only rank, regardless of dates."""
    if rank in CHOVAH_ONLY_RANKS:
        return False
    if mandatory_end_date is None:
        return False
    ref = today or date.today()
    if ref <= mandatory_end_date:
        return False
    return discharge_date is None or discharge_date > mandatory_end_date
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_eligibility.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/eligibility.py backend/app/services/tests/test_eligibility.py
git commit -m "feat: add derive_is_career and CHOVAH_ONLY_RANKS"
```

- [ ] **Step 6: Write the failing test for rank/career validation in `_check_soldier_dates`**

```python
# backend/app/services/tests/test_soldiers.py — append
def test_update_soldier_profile_rejects_chovah_only_rank_while_career(admin_session):
    from datetime import date
    from app.services.soldiers import update_soldier_profile, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920004")
    soldier.mandatory_end_date = date(2020, 1, 1)  # long past -> derives to קבע
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="rank"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"rank": "טוראי"}, actor_id=None,
        )


def test_update_soldier_profile_derives_is_career_from_dates(admin_session):
    from datetime import date
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920005")
    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={"rank": "רסן", "mandatory_end_date": date(2020, 1, 1)}, actor_id=None,
    )
    assert soldier.is_career is True
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_soldiers.py -k chovah_only_rank or derives_is_career -v`
Expected: FAIL — no rank check raised / `is_career` stays `False`

- [ ] **Step 8: Implement rank/career consistency check + derivation in `soldiers.py`**

```python
# backend/app/services/soldiers.py:33-45 — replace _check_soldier_dates
def _check_soldier_dates(
    *,
    rank: str | None,
    enlistment_date: date | None,
    discharge_date: date | None,
    mandatory_end_date: date | None,
    is_career: bool,
) -> None:
    if discharge_date is not None and enlistment_date is not None and discharge_date <= enlistment_date:
        raise SoldierValidationError("discharge_date must be after enlistment_date")
    if mandatory_end_date is not None and discharge_date is not None and mandatory_end_date > discharge_date:
        raise SoldierValidationError("mandatory_end_date must not be after discharge_date")
    if is_career and discharge_date is not None and discharge_date < date.today():
        raise SoldierValidationError("career soldier's discharge_date cannot be in the past")
    from app.services.eligibility import CHOVAH_ONLY_RANKS
    if is_career and rank in CHOVAH_ONLY_RANKS:
        raise SoldierValidationError("rank is חובה-only and cannot be combined with קבע status")


def validate_soldier_dates(soldier: Soldier) -> None:
    _check_soldier_dates(
        rank=soldier.rank,
        enlistment_date=soldier.enlistment_date,
        discharge_date=soldier.discharge_date,
        mandatory_end_date=soldier.mandatory_end_date,
        is_career=soldier.is_career,
    )
```

```python
# backend/app/services/soldiers.py:205-225 — update_soldier_profile: derive is_career before validating
def update_soldier_profile(
    session: Session,
    *,
    soldier: Soldier,
    fields: dict,
    actor_id: uuid.UUID | None,
) -> Soldier:
    """DM/admin direct update of profile fields."""
    from app.services.eligibility import derive_is_career
    for k, v in fields.items():
        if k in PROFILE_FIELDS:
            setattr(soldier, k, v)
    soldier.is_career = derive_is_career(soldier.rank, soldier.mandatory_end_date, soldier.discharge_date)
    validate_soldier_dates(soldier)
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.profile.update",
        entity_type="soldier",
        entity_id=soldier.id,
        after={k: str(v) for k, v in fields.items() if v is not None},
    )
    return soldier
```

Also update `approve_field_update` (soldiers.py, the `elif field == "rank":`/`"mandatory_end_date"`/`"discharge_date"` branches around line 296-309) to re-derive and validate after applying the change — add at the end of that function, right before its `return`:

```python
    soldier.is_career = derive_is_career(soldier.rank, soldier.mandatory_end_date, soldier.discharge_date)
    validate_soldier_dates(soldier)
```

(add `from app.services.eligibility import derive_is_career` at the top of `approve_field_update`, matching the existing local-import style already used for `SOLDIER_EDITABLE_FIELDS` in this file).

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_soldiers.py -v`
Expected: PASS, including the two new tests

- [ ] **Step 10: Remove `is_career` from registration/enrollment write paths**

In `backend/app/routes/enrollment.py`: delete `is_career: bool | None = None` from `PatchEnrollmentBody` (line 65) and its handling (`if body.is_career is not None: s.is_career = body.is_career`).

In `backend/app/services/registration.py:38,71,87`: remove the `is_career: bool = False` parameter from `register_soldier(...)` and stop passing it into the `Soldier(...)` constructor — the model's `is_career` keeps its `default=False` server-side default.

In `frontend/src/pages/RegisterPage.tsx`: remove the "אני בקבע" checkbox bound to `form.is_career` and drop `is_career` from the submitted payload and initial form state (line 53).

Update `backend/app/services/tests/test_registration.py:128-144` (`test_register_stores_is_career`) — replace with a test asserting a freshly registered soldier always has `is_career is False` regardless of any legacy caller still passing the field:

```python
def test_register_always_starts_as_chovah(admin_session):
    from app.services.registration import register_soldier
    soldier = register_soldier(
        admin_session, personal_number="7920006", full_name="Test Soldier",
        password="Passw0rd123", requested_node_id=None,
        exemption_requests=[], personal_constraints=[],
    )
    assert soldier.is_career is False
```

- [ ] **Step 11: Run full soldiers/registration/enrollment test files**

Run: `cd backend && pytest app/services/tests/test_soldiers.py app/services/tests/test_registration.py app/services/tests/test_eligibility.py -v`
Expected: PASS

- [ ] **Step 12: Run frontend typecheck and RegisterPage-related tests**

Run: `cd frontend && npm run typecheck && npm test -- RegisterPage`
Expected: PASS (fix any compile errors from the removed `is_career` field)

- [ ] **Step 13: Commit**

```bash
git add backend/app/services/soldiers.py backend/app/services/registration.py backend/app/routes/enrollment.py frontend/src/pages/RegisterPage.tsx backend/app/services/tests/test_soldiers.py backend/app/services/tests/test_registration.py
git commit -m "fix: derive is_career from dates, block chovah-only rank + career combo"
```

---

## Task A2: Missing translations — exemption status keys + swap-page duty names via API

**Files:**
- Modify: `frontend/src/i18n/he.json:390-400` (`exemption_requests` block)
- Modify: `backend/app/routes/assignments.py:54-67,123-137` (`EffectiveDutyOut`, `list_effective_duties`)
- Modify: `frontend/src/api/assignments.ts:14-27` (`EffectiveDuty` interface)
- Modify: `frontend/src/pages/SwapsPage.tsx:460,606,611` (use `duty_type_name` directly)
- Test: `backend/app/routes/tests/test_assignments.py` (create if missing — check first), `frontend/src/i18n/*.test.ts` if an i18n-completeness test exists (search first; otherwise add the translation and move on — no dedicated test needed for pure copy)

**Interfaces:**
- Produces: `EffectiveDutyOut.duty_type_name: str`, `EffectiveDuty.duty_type_name: string` (frontend)

- [ ] **Step 1: Add missing i18n keys**

```json
// frontend/src/i18n/he.json — inside "exemption_requests" (after line 399 "rejected": "נדחה",)
    "pending_commander": "ממתין לאישור מפקד",
    "pending_duty_manager": "ממתין לאישור אחראי תורנויות",
```

- [ ] **Step 2: Write the failing backend test for `duty_type_name` on `/assignments/effective`**

```python
# backend/app/routes/tests/test_assignments.py (create if missing)
from __future__ import annotations
import uuid
from datetime import date, time
from app.db.models import DutyAssignment, DutyLocation, DutyType
from tests.helpers import auth_headers, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def test_effective_duties_include_duty_type_name(client, admin_session):
    soldier = create_soldier(admin_session, personal_number=f"eff_{_uid()}")
    dtype = DutyType(name=f"שמירה_{_uid()}", score_per_day=1, active=True)
    loc = DutyLocation(name=f"loc_{_uid()}", base="בסיס")
    admin_session.add_all([dtype, loc])
    admin_session.flush()
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dtype.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 1),
        start_time=time(8, 0), end_time=time(20, 0), status="published",
    ))
    admin_session.commit()

    resp = client.get(
        "/api/assignments/effective",
        params={"soldier_id": str(soldier.id)},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 200
    assert resp.json()[0]["duty_type_name"] == dtype.name
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest app/routes/tests/test_assignments.py -v`
Expected: FAIL — `KeyError: 'duty_type_name'`

(If `DutyAssignment`/`DutyType` constructor kwargs differ from the above, check `backend/app/services/tests/test_assignments.py` for the exact fixture pattern already in use and match it.)

- [ ] **Step 4: Add `duty_type_name` to `EffectiveDutyOut`**

```python
# backend/app/routes/assignments.py:54-66 — add field
class EffectiveDutyOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    start_time: str
    end_time: str
    start_at: datetime
    end_at: datetime
    shift_id: uuid.UUID | None = None
    is_reserve: bool = False
```

```python
# backend/app/routes/assignments.py:123-137 — populate the name map
@router.get("/effective", response_model=list[EffectiveDutyOut])
def list_effective_duties(
    soldier_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[EffectiveDutyOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    spans = scoring_svc.effective_duty_spans(
        session, soldier_ids={soldier_id}, date_from=date_from, date_to=date_to
    )
    type_ids = {sp["duty_type_id"] for sp in spans}
    names = {
        dt.id: dt.name
        for dt in session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars()
    } if type_ids else {}
    return [
        EffectiveDutyOut(**sp, duty_type_name=names.get(sp["duty_type_id"], ""))
        for sp in spans
    ]
```

Add `DutyType` to the existing `from app.db.models import (...)` import at the top of `assignments.py` if it isn't already imported.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest app/routes/tests/test_assignments.py -v`
Expected: PASS

- [ ] **Step 6: Update frontend types and SwapsPage rendering**

```typescript
// frontend/src/api/assignments.ts:14-27 — add field
export interface EffectiveDuty {
  assignment_id: string;
  soldier_id: string;
  duty_type_id: string;
  duty_type_name: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  start_time: string;
  end_time: string;
  start_at: string;
  end_at: string;
  shift_id?: string | null;
  is_reserve: boolean;
}
```

In `frontend/src/pages/SwapsPage.tsx`, replace the two lookup-fallback sites:
- Line 460 (list row): `<span className="font-medium dark:text-gray-100">{dutyTypes[d.duty_type_id] ?? d.duty_type_id}</span>` → `<span className="font-medium dark:text-gray-100">{d.duty_type_name}</span>`
- Line 611 (modal prop): `dutyTypeName={dutyTypes[askSwapDuty.duty_type_id] ?? askSwapDuty.duty_type_id}` → `dutyTypeName={askSwapDuty.duty_type_name}`

- [ ] **Step 7: Run frontend typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/i18n/he.json backend/app/routes/assignments.py backend/app/routes/tests/test_assignments.py frontend/src/api/assignments.ts frontend/src/pages/SwapsPage.tsx
git commit -m "fix: add missing exemption status translations, embed duty type name in effective-duty API"
```

---

## Task A3: Missing translation `cover_blocked.overlap`

**Files:**
- Modify: `frontend/src/components/CoverOfferModal.tsx:39-46`
- Modify: `frontend/src/i18n/he.json` (add `cover_blocked` block near `swaps`/error blocks)
- Test: `frontend/src/components/CoverOfferModal.test.tsx` (check if it exists first; if not, add a focused test)

**Interfaces:**
- Consumes: backend error string `cover_blocked:<reason>` from `backend/app/services/swaps.py:151` (reasons come from `AssignmentError` in `backend/app/services/assignments.py:146,266` — confirm the exact reason strings there before finalizing keys; `overlap` is confirmed)

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/components/CoverOfferModal.test.tsx (create if missing — check existing file first)
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import CoverOfferModal from "./CoverOfferModal";

vi.mock("../api/swaps", () => ({
  submitCoverOffer: vi.fn().mockRejectedValue({
    response: { data: { detail: "cover_blocked:overlap" } },
  }),
}));

it("shows a translated message for cover_blocked:overlap", async () => {
  render(
    <CoverOfferModal
      swap={{ id: "1", duties: [] } as any}
      onDone={() => {}}
      onClose={() => {}}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: /שלח|אשר/ }));
  await waitFor(() =>
    expect(screen.getByText("קיימת חפיפה עם תורנות אחרת")).toBeInTheDocument()
  );
});
```

(Adjust the required props on `CoverOfferModal` to match its actual prop interface — read the top of `frontend/src/components/CoverOfferModal.tsx` for the exact `Props` type before writing this test, since the plan author only confirmed lines 30-50.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- CoverOfferModal`
Expected: FAIL — raw `cover_blocked:overlap` text present, translated text missing

- [ ] **Step 3: Add the `cover_blocked` i18n block**

```json
// frontend/src/i18n/he.json — new top-level block, alphabetically near "constraints"/"cover..." entries
  "cover_blocked": {
    "overlap": "קיימת חפיפה עם תורנות אחרת"
  },
```

- [ ] **Step 4: Parse the `cover_blocked:` prefix in `CoverOfferModal.tsx`**

```typescript
// frontend/src/components/CoverOfferModal.tsx:39-46 — replace handleSubmit's catch block
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (detail?.startsWith("cover_not_eligible:")) {
        setError(detail.slice("cover_not_eligible:".length));
      } else if (detail?.startsWith("cover_blocked:")) {
        const reason = detail.slice("cover_blocked:".length);
        setError(t(`cover_blocked.${reason}`, { defaultValue: reason }));
      } else {
        setError(detail ?? "שגיאה");
      }
    }
```

Ensure `const { t } = useTranslation();` is already destructured at the top of the component (it is, per existing pattern in sibling components) — add it if this particular component doesn't already call `useTranslation`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test -- CoverOfferModal`
Expected: PASS

- [ ] **Step 6: Also apply the same fix in `ApprovalsPage.tsx`'s `describeError`, if it's reachable from a `cover_blocked:` error**

Read `ApprovalsPage.tsx`'s swap-approval call sites; if any approval action can surface a `cover_blocked:*` detail through `describeError` (line 39-44), extend it the same way:

```typescript
function describeError(err: unknown): string {
  if (err && typeof err === "object" && "response" in err) {
    const resp = (err as { response?: { data?: { detail?: string } } }).response;
    const detail = resp?.data?.detail;
    if (detail?.startsWith("cover_blocked:")) {
      return i18n.t(`cover_blocked.${detail.slice("cover_blocked:".length)}`, { defaultValue: detail });
    }
    if (detail) return detail;
  }
  return "שגיאה בביצוע הפעולה";
}
```

Import `i18n` from `"../i18n"` (or whatever the existing i18n instance import path is in this codebase — check `frontend/src/i18n/index.ts` or similar) since `describeError` is a plain function, not a component, so it can't call the `useTranslation` hook.

- [ ] **Step 7: Run frontend tests + typecheck**

Run: `cd frontend && npm run typecheck && npm test -- CoverOfferModal ApprovalsPage`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/i18n/he.json frontend/src/components/CoverOfferModal.tsx frontend/src/pages/ApprovalsPage.tsx frontend/src/components/CoverOfferModal.test.tsx
git commit -m "fix: translate cover_blocked:* errors instead of showing raw error code"
```

---

## Task A4: "Missing token" viewing exemption request images

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx:345-362` (file link rendering)
- Test: `frontend/src/pages/ApprovalsPage.test.tsx` (check existing file first)

**Interfaces:**
- Consumes: `api` client from `frontend/src/api/client.ts` (attaches Bearer token automatically), `exemptionFileDownloadUrl(erId, fileId)` from `frontend/src/api/exemptions.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/pages/ApprovalsPage.test.tsx — add a focused test (adjust imports/mocks to match the file's existing test setup)
it("opens exemption files via an authenticated blob fetch, not a raw href", async () => {
  // Render the approvals list with one exemption request that has a file,
  // click the file link, and assert `api.get` was called with responseType: "blob"
  // and exemptionFileDownloadUrl(...) rather than a plain <a href> navigation.
  // Exact assertions depend on how the page's existing tests mock listPendingExemptions —
  // follow that file's established render/mock pattern.
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ApprovalsPage`
Expected: FAIL (no such fetch call is made yet; the element is a plain `<a>`)

- [ ] **Step 3: Replace the plain anchor with an authenticated blob fetch**

```tsx
// frontend/src/pages/ApprovalsPage.tsx:345-362 — replace the <a> file link
async function openExemptionFile(erId: string, fileId: string, fileName: string) {
  const resp = await api.get(exemptionFileDownloadUrl(erId, fileId), { responseType: "blob" });
  const url = URL.createObjectURL(resp.data as Blob);
  const win = window.open(url, "_blank");
  if (win) {
    win.addEventListener("beforeunload", () => URL.revokeObjectURL(url));
  } else {
    // popup blocked — revoke immediately, nothing to show
    URL.revokeObjectURL(url);
  }
}
```

```tsx
                  {er.files.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-2">
                      {er.files.map(f => (
                        <button
                          key={f.id}
                          type="button"
                          onClick={() => openExemptionFile(er.id, f.id, f.file_name)}
                          className="text-blue-600 dark:text-blue-400 text-xs hover:underline flex items-center gap-1"
                        >
                          📎 {f.file_name}
                        </button>
                      ))}
                    </div>
                  )}
```

Import `api` from `"../api/client"` at the top of `ApprovalsPage.tsx` if not already imported.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- ApprovalsPage`
Expected: PASS

- [ ] **Step 5: Manual verification**

Since this touches file download/auth behavior, per project convention start the dev stack (`.\dev.ps1`) and manually open an exemption request with an attached file from the Approvals page to confirm the file opens in a new tab without a "missing token" error.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx frontend/src/pages/ApprovalsPage.test.tsx
git commit -m "fix: fetch exemption request files with auth token instead of raw link navigation"
```

---

## Task A5: Phantom pending-approval entries

**Files:**
- Modify: `backend/app/services/commander_dashboard.py:108-115` (`summary_cards`)
- Modify: `backend/app/services/soldiers.py:182-194` (`soft_delete`)
- Test: `backend/app/services/tests/test_commander_dashboard.py`, `backend/app/services/tests/test_soldiers.py`

**Interfaces:**
- Consumes: `swaps.reject_request`/`cancel_request`, `exemption_requests` service reject path, `constraints.reject_constraint` (all already exist — reused, not modified)

- [ ] **Step 1: Write the failing test for the swap-status literal**

```python
# backend/app/services/tests/test_commander_dashboard.py — add
def test_summary_cards_counts_pending_approval_swaps(admin_session):
    from app.db.models import SwapRequest, DutyAssignment
    from app.services.commander_dashboard import summary_cards
    from tests.helpers import create_soldier, create_node

    node = create_node(admin_session, level="unit", name="pending_swap_test")
    soldier = create_soldier(admin_session, personal_number="7930001", hierarchy_node_id=node.id)
    # minimal swap request in pending_approval status
    req = SwapRequest(requesting_soldier_id=soldier.id, duty_assignment_id=None, status="pending_approval")
    admin_session.add(req)
    admin_session.commit()

    cards = summary_cards(admin_session, node_ids={node.id})
    assert cards["pending_swaps"] >= 1
```

(Match `SwapRequest`'s actual required columns — check `backend/app/services/tests/test_assignments.py` or `test_swaps` for a working `SwapRequest(...)` construction, since `duty_assignment_id` may be non-nullable; adjust the fixture accordingly rather than guessing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_commander_dashboard.py -v`
Expected: FAIL — count is 0

- [ ] **Step 3: Fix the status literal**

```python
# backend/app/services/commander_dashboard.py:108-115
    pending_swaps = session.execute(
        select(func.count(SwapRequest.id)).where(
            SwapRequest.status == "pending_approval",
            SwapRequest.requesting_soldier_id.in_(soldier_ids),
        )
    ).scalar_one()
```

(Match whatever the surrounding query's existing structure is exactly — read the full function before editing; this shows the corrected literal, not necessarily the full untouched query shape.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_commander_dashboard.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for soft_delete cancelling pending requests**

```python
# backend/app/services/tests/test_soldiers.py — add
def test_soft_delete_cancels_pending_exemption_and_swap_requests(admin_session):
    from app.db.models import ExemptionRequest, SwapRequest
    from app.services.soldiers import soft_delete
    from tests.helpers import create_soldier
    from datetime import date

    soldier = create_soldier(admin_session, personal_number="7930002")
    er = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=None, start_date=date(2026, 8, 1),
        end_date=None, status="pending_commander",
    )
    admin_session.add(er)
    admin_session.commit()

    soft_delete(admin_session, soldier=soldier, actor_id=None)
    admin_session.commit()
    admin_session.refresh(er)
    assert er.status == "cancelled"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_soldiers.py -k soft_delete_cancels -v`
Expected: FAIL — `er.status` still `pending_commander`

- [ ] **Step 7: Implement cancellation in `soft_delete`**

```python
# backend/app/services/soldiers.py:182-194 — replace soft_delete
def soft_delete(
    session: Session, *, soldier: Soldier, actor_id: uuid.UUID | None = None
) -> Soldier:
    soldier.left_at = date.today()
    from app.db.models import ExemptionRequest, PersonalConstraint, SwapRequest
    session.execute(
        sa_update(ExemptionRequest)
        .where(
            ExemptionRequest.soldier_id == soldier.id,
            ExemptionRequest.status.in_(("pending_commander", "pending_duty_manager")),
        )
        .values(status="cancelled")
    )
    session.execute(
        sa_update(PersonalConstraint)
        .where(PersonalConstraint.soldier_id == soldier.id, PersonalConstraint.status == "pending")
        .values(status="cancelled")
    )
    session.execute(
        sa_update(SwapRequest)
        .where(
            SwapRequest.requesting_soldier_id == soldier.id,
            SwapRequest.status.in_(("open", "pending_approval")),
        )
        .values(status="cancelled")
    )
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.soft_delete",
        entity_type="soldier",
        entity_id=soldier.id,
        after={"left_at": soldier.left_at.isoformat()},
    )
    return soldier
```

Add `from sqlalchemy import update as sa_update` to the imports at the top of `soldiers.py` if not already present (check first — `soldiers.py` already uses `sa_case`/`sa_update` patterns elsewhere per `auth.py`; if `soldiers.py` itself doesn't import it yet, add it).

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_soldiers.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/commander_dashboard.py backend/app/services/soldiers.py backend/app/services/tests/test_commander_dashboard.py backend/app/services/tests/test_soldiers.py
git commit -m "fix: correct pending-swap status literal, cancel pending requests on soldier soft-delete"
```

---

## Task A6: Soldier's own duty shows only "תורנות" with no details

**Files:**
- Modify: `frontend/src/components/dashboard/DutyCalendarWidget.tsx:37-52`
- Modify: `frontend/src/components/dashboard/SwapStatusWidget.tsx:38-40`
- Test: none exist for these widgets today — add `frontend/src/components/dashboard/DutyCalendarWidget.test.tsx`

**Interfaces:**
- Consumes: `EffectiveDuty.duty_type_name` (added in Task A2 — this task must run after A2)

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/components/dashboard/DutyCalendarWidget.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import DutyCalendarWidget from "./DutyCalendarWidget";

it("shows the duty's own name even when typeNames lookup is empty", () => {
  const duty = {
    assignment_id: "a1", soldier_id: "s1", duty_type_id: "missing-id",
    duty_type_name: "שמירה ראשית", duty_location_id: "l1",
    start_date: "2026-08-01", end_date: "2026-08-01",
    start_time: "08:00", end_time: "20:00",
    start_at: "2026-08-01T08:00:00Z", end_at: "2026-08-01T20:00:00Z",
    is_reserve: false,
  };
  const { container } = render(
    <DutyCalendarWidget duties={[duty]} typeNames={{}} onOpenDuty={() => {}} />
  );
  expect(container.textContent).toContain("שמירה ראשית");
  expect(container.textContent).not.toContain("תורנות");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- DutyCalendarWidget`
Expected: FAIL — title falls back to `"תורנות"` since `typeNames` is empty

- [ ] **Step 3: Prefer the embedded name**

```typescript
// frontend/src/components/dashboard/DutyCalendarWidget.tsx:44
        title: d.duty_type_name || typeNames[d.duty_type_id] || "תורנות",
```

```typescript
// frontend/src/components/dashboard/SwapStatusWidget.tsx:38-40 — SwapRequest already has duty_type_name,
// this widget is unaffected by A2's EffectiveDuty change; leave as-is unless SwapRequest itself
// has the same silent-failure issue (it doesn't — duty_type_name is already server-populated there).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- DutyCalendarWidget`
Expected: PASS

- [ ] **Step 5: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/dashboard/DutyCalendarWidget.tsx frontend/src/components/dashboard/DutyCalendarWidget.test.tsx
git commit -m "fix: show real duty name on dashboard calendar even when duty-type lookup fails"
```

---

## Task A7: Frontend crash requesting a swap by invalid personal number

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx:152-221` (`AskSwapModal`)
- Create: `frontend/src/components/ErrorBoundary.tsx`
- Modify: `frontend/src/App.tsx` (wrap the app shell)
- Test: `frontend/src/pages/SwapsPage.test.tsx`, `frontend/src/components/ErrorBoundary.test.tsx`

**Interfaces:**
- Consumes: `SoldierSearchAutocomplete` (`frontend/src/components/SoldierSearchAutocomplete.tsx`, props `{ onSelect: (soldier: SoldierDTO | null) => void; onCreateNew: (personalNumber: string, fullName: string) => void }`)

- [ ] **Step 1: Write the failing test for the autocomplete replacing the raw input**

```typescript
// frontend/src/pages/SwapsPage.test.tsx — add (adjust to the file's existing render/mock setup)
it("lets the requester pick a soldier via search instead of typing a raw id", async () => {
  // Render AskSwapModal in "send to soldier" mode and assert a search input
  // (SoldierSearchAutocomplete's placeholder/role) is present instead of the
  // old free-text "מספר אישי של חייל" input.
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- SwapsPage`
Expected: FAIL

- [ ] **Step 3: Replace the raw input with `SoldierSearchAutocomplete`**

```tsx
// frontend/src/pages/SwapsPage.tsx:152-221 — AskSwapModal, replace state + the soldier-mode input
function AskSwapModal({
  duty, dutyTypeName, onClose, onCreated,
}: {
  duty: EffectiveDuty; dutyTypeName: string; onClose: () => void; onCreated: () => void;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"open" | "soldier">("open");
  const [targetSoldier, setTargetSoldier] = useState<SoldierDTO | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const input: CreateSwapInput = {
        duty_assignment_id: duty.assignment_id,
        reason: reason || null,
        target_soldier_id: mode === "soldier" ? targetSoldier?.id ?? null : null,
      };
      await createSwap(input);
      onCreated();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      if (typeof detail === "string") {
        setError(detail);
      } else if (Array.isArray(detail) && detail.length > 0 && typeof detail[0]?.msg === "string") {
        setError(detail[0].msg);
      } else {
        setError("שגיאה");
      }
    }
  }
  // ... rest of component body unchanged except the soldier-mode input block below
```

```tsx
          {mode === "soldier" && (
            <SoldierSearchAutocomplete
              onSelect={setTargetSoldier}
              onCreateNew={() => {}}
            />
          )}
```

Import `SoldierSearchAutocomplete` from `"../components/SoldierSearchAutocomplete"` and `SoldierDTO` from `"../api/soldiers"` at the top of `SwapsPage.tsx`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- SwapsPage`
Expected: PASS

- [ ] **Step 5: Write the failing test for the ErrorBoundary**

```typescript
// frontend/src/components/ErrorBoundary.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ErrorBoundary from "./ErrorBoundary";

function Boom(): JSX.Element {
  throw new Error("boom");
}

it("renders a fallback instead of a blank crash", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  render(
    <ErrorBoundary>
      <Boom />
    </ErrorBoundary>
  );
  expect(screen.getByText(/משהו השתבש/)).toBeInTheDocument();
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npm test -- ErrorBoundary`
Expected: FAIL — `ErrorBoundary` module doesn't exist

- [ ] **Step 7: Implement `ErrorBoundary`**

```tsx
// frontend/src/components/ErrorBoundary.tsx
import { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    console.error("Unhandled render error:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6 dark:bg-gray-900" dir="rtl">
          <p className="text-gray-600 dark:text-gray-300">משהו השתבש. נסה לרענן את הדף.</p>
        </div>
      );
    }
    return this.props.children;
  }
}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npm test -- ErrorBoundary`
Expected: PASS

- [ ] **Step 9: Wrap the app shell**

In `frontend/src/App.tsx`, import `ErrorBoundary` from `"./components/ErrorBoundary"` and wrap the top-level router/layout output with `<ErrorBoundary>...</ErrorBoundary>`.

- [ ] **Step 10: Run typecheck and full frontend test file for SwapsPage**

Run: `cd frontend && npm run typecheck && npm test -- SwapsPage ErrorBoundary`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add frontend/src/pages/SwapsPage.tsx frontend/src/components/ErrorBoundary.tsx frontend/src/App.tsx frontend/src/pages/SwapsPage.test.tsx frontend/src/components/ErrorBoundary.test.tsx
git commit -m "fix: use soldier search instead of raw id for swap requests, add app-level ErrorBoundary"
```

---

## Task B1: Export/import for system settings

**Files:**
- Modify: `backend/app/routes/system_settings.py`
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Modify: `frontend/src/api/systemSettings.ts` (check exact current exports first)
- Test: `backend/app/routes/tests/test_system_settings.py` (create)

**Interfaces:**
- Produces: `GET /admin/system-settings/export` → `{"settings": {...}}`, `POST /admin/system-settings/import` body `{"settings": {...}}` → same shape as `PUT /admin/system-settings`

- [ ] **Step 1: Write the failing test**

```python
# backend/app/routes/tests/test_system_settings.py
from __future__ import annotations
from tests.helpers import auth_headers, create_soldier


def test_export_returns_current_settings(client, admin_session):
    admin = create_soldier(admin_session, personal_number="7940001", role="admin")
    resp = client.get("/api/admin/system-settings/export", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert "settings" in resp.json()


def test_import_applies_settings(client, admin_session):
    admin = create_soldier(admin_session, personal_number="7940002", role="admin")
    resp = client.post(
        "/api/admin/system-settings/import",
        json={"settings": {"eligibility.mitvahim_months": 9}},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["eligibility.mitvahim_months"] == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/routes/tests/test_system_settings.py -v`
Expected: FAIL — 404 (routes don't exist yet)

- [ ] **Step 3: Add export/import endpoints**

```python
# backend/app/routes/system_settings.py — add below the existing update_settings endpoint
@router.get("/export", response_model=SettingsOut)
def export_settings(
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> SettingsOut:
    rows = session.execute(select(SystemSetting)).scalars().all()
    return SettingsOut(settings={r.key: r.value for r in rows if r.key not in _HIDDEN_KEYS})


@router.post("/import", response_model=SettingsOut)
def import_settings(
    body: UpdateSettingsBody,
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> SettingsOut:
    return update_settings(body, session, user)
```

(Reuses `update_settings`'s existing validation for the density settings — calling it directly keeps the two endpoints' behavior identical rather than duplicating the checks.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/routes/tests/test_system_settings.py -v`
Expected: PASS

- [ ] **Step 5: Add export/import buttons to the settings page**

Check `frontend/src/api/systemSettings.ts` for the exact existing `getSystemSettings`/`updateSystemSettings` function shapes, then add:

```typescript
// frontend/src/api/systemSettings.ts — add
export async function exportSystemSettings(): Promise<SettingsMap> {
  return (await api.get<{ settings: SettingsMap }>("/admin/system-settings/export")).data.settings;
}

export async function importSystemSettings(settings: SettingsMap): Promise<SettingsMap> {
  return (await api.post<{ settings: SettingsMap }>("/admin/system-settings/import", { settings })).data.settings;
}
```

In `frontend/src/pages/SystemSettingsPage.tsx`, add an "ייצוא הגדרות" button that calls `exportSystemSettings()` and triggers a client-side JSON file download (`new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })` + a temporary object-URL anchor click, same pattern as `ExcelExportButton.tsx` uses for its own download — follow that component's existing download-trigger code rather than inventing a new one), and an "ייבוא הגדרות" file input that reads the selected `.json` file via `FileReader`, `JSON.parse`s it, and calls `importSystemSettings(parsed)`, then invalidates the settings query (`queryClient.invalidateQueries({ queryKey: queryKeys.systemSettings() })` — confirm the exact query key used by this page's existing `useQuery` call first).

- [ ] **Step 6: Run frontend typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/system_settings.py backend/app/routes/tests/test_system_settings.py frontend/src/api/systemSettings.ts frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat: add export/import for system settings"
```

---

## Task B2: Default email-domain-hint system setting

**Files:**
- Modify: `backend/app/routes/public_settings.py` (add unauthenticated registration-settings endpoint)
- Modify: `frontend/src/pages/SystemSettingsPage.tsx` (add setting), `frontend/src/pages/RegisterPage.tsx`, `frontend/src/pages/ProfilePage.tsx`
- Create: `frontend/src/api/registrationSettings.ts`
- Test: `backend/app/routes/tests/test_public_settings.py` (check first if it exists)

**Interfaces:**
- Produces: `GET /settings/public/registration` (no auth) → `{"email_domain_hint": string | null}`

- [ ] **Step 1: Write the failing test**

```python
# backend/app/routes/tests/test_public_settings.py (create if missing)
def test_registration_public_settings_no_auth_required(client, admin_session):
    from app.db.models import SystemSetting
    admin_session.add(SystemSetting(key="registration.email_domain_hint", value="gmail.com", updated_by=None))
    admin_session.commit()

    resp = client.get("/api/settings/public/registration")
    assert resp.status_code == 200
    assert resp.json()["email_domain_hint"] == "gmail.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/routes/tests/test_public_settings.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Add the unauthenticated endpoint**

```python
# backend/app/routes/public_settings.py — add
class RegistrationPublicSettingsOut(BaseModel):
    email_domain_hint: str | None = None


@router.get("/registration", response_model=RegistrationPublicSettingsOut)
def get_registration_public_settings(session: Session = Depends(get_session)) -> RegistrationPublicSettingsOut:
    row = session.get(SystemSetting, "registration.email_domain_hint")
    return RegistrationPublicSettingsOut(email_domain_hint=row.value if row else None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/routes/tests/test_public_settings.py -v`
Expected: PASS

- [ ] **Step 5: Add the setting to the admin settings page**

```typescript
// frontend/src/pages/SystemSettingsPage.tsx — add a new group after "הרשמה"
  {
    label: "הרשמה",
    settings: [
      { key: "registration.telegram_required", label: "טלגרם חובה", description: "האם חיילים חדשים חייבים לקשר חשבון טלגרם לאחר ההרשמה", type: "boolean", defaultValue: false },
      { key: "registration.email_domain_hint", label: "רמז לדומיין אימייל", description: "דומיין ברירת מחדל המוצג כרמז בשדה האימייל, למשל gmail.com (ריק = ללא רמז)", type: "select", defaultValue: "", options: [] },
    ],
  },
```

(Use `type: "select"` only if `SystemSettingsPage.tsx`'s renderer supports free-text via a `"select"` type with empty `options` — if it doesn't, use whatever the page's existing renderer supports for a plain string input; check the render-switch on `SettingDef.type` before finalizing this line.)

- [ ] **Step 6: Wire the hint into registration and email-change UI**

```typescript
// frontend/src/api/registrationSettings.ts
import { api } from "./client";

export async function getRegistrationPublicSettings(): Promise<{ email_domain_hint: string | null }> {
  return (await api.get("/settings/public/registration")).data;
}
```

In `RegisterPage.tsx`, fetch this on mount (`useQuery({ queryKey: ["registrationPublicSettings"], queryFn: getRegistrationPublicSettings })`) and, when `email_domain_hint` is set, show it as the email input's `placeholder` (e.g. `שם@${hint}`) — purely cosmetic, does not restrict submission. Apply the same placeholder to the email field in `ProfilePage.tsx`.

- [ ] **Step 7: Run frontend typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/routes/public_settings.py backend/app/routes/tests/test_public_settings.py frontend/src/api/registrationSettings.ts frontend/src/pages/SystemSettingsPage.tsx frontend/src/pages/RegisterPage.tsx frontend/src/pages/ProfilePage.tsx
git commit -m "feat: add configurable email-domain hint for registration and email change"
```

---

## Task B3: Missing notification on enrollment rejection

**Files:**
- Modify: `backend/app/services/enrollment.py:65-85` (`reject_enrollment`)
- Test: `backend/app/services/tests/test_enrollment.py`

**Interfaces:**
- Consumes: `notifications.create_notification`, `NotificationType.enrollment_rejected` (both already exist)

- [ ] **Step 1: Write the failing test**

```python
# backend/app/services/tests/test_enrollment.py — add
def test_reject_enrollment_notifies_soldier(admin_session):
    from app.db.models import Notification, NotificationType
    from app.services.enrollment import reject_enrollment
    from tests.helpers import create_soldier, create_node
    from sqlalchemy import select

    node = create_node(admin_session, level="unit", name="reject_notify_test")
    soldier = create_soldier(admin_session, personal_number="7950001", hierarchy_node_id=node.id)
    decider = create_soldier(admin_session, personal_number="7950002", role="admin")
    from app.db.models import SoldierEnrollmentRequest
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    admin_session.add(req)
    admin_session.commit()

    reject_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note="not eligible")
    admin_session.commit()

    notif = admin_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.type == NotificationType.enrollment_rejected,
        )
    ).scalar_one_or_none()
    assert notif is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_enrollment.py -k reject_enrollment_notifies -v`
Expected: FAIL — `notif is None`

- [ ] **Step 3: Add the notification call**

```python
# backend/app/services/enrollment.py:65-85 — replace reject_enrollment
def reject_enrollment(
    session: Session,
    *,
    request_id: uuid.UUID,
    decider_id: uuid.UUID,
    decision_note: str,
) -> SoldierEnrollmentRequest:
    from app.services.notifications import create_notification
    from app.db.models import NotificationType

    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise EnrollmentError("enrollment request not found")
    if req.status != "pending":
        raise EnrollmentError("already decided")
    req.status = "rejected"
    req.decided_by = decider_id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_note = decision_note
    session.flush()
    create_notification(
        session, soldier_id=req.soldier_id, type=NotificationType.enrollment_rejected,
        title="בקשת ההרשמה נדחתה", reference_type="soldier_enrollment_request",
        reference_id=req.id, actor_id=decider_id,
    )
    write_audit(session, actor_id=decider_id, action="enrollment.reject",
                entity_type="soldier_enrollment_request", entity_id=req.id,
                after={"decision_note": decision_note})
    return req
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_enrollment.py -v`
Expected: PASS (including the pre-existing `test_reject_leaves_soldier_in_holding`)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/enrollment.py backend/app/services/tests/test_enrollment.py
git commit -m "fix: notify soldier when their enrollment request is rejected"
```

---

## Task B4: Login page — show attempt count against the lockout limit

**Files:**
- Modify: `backend/app/routes/auth.py:167-188` (`login`, wrong-password branch)
- Modify: `frontend/src/pages/LoginPage.tsx`
- Modify: `frontend/src/i18n/he.json:7-20` (`login.errors`)
- Test: `backend/tests/integration/test_auth_routes.py` (check exact existing filename first), `frontend/src/pages/LoginPage.test.tsx` (check first)

**Interfaces:**
- Produces: 401 body `{"detail": "invalid_credentials", "attempts": int, "max_attempts": int}` from `/auth/login`

- [ ] **Step 1: Write the failing backend test**

```python
# in the existing auth routes integration test file — add
def test_login_401_reports_attempt_count(client, admin_session):
    from tests.helpers import create_soldier
    from app.auth.password import hash_password

    soldier = create_soldier(admin_session, personal_number="7960001")
    soldier.password_hash = hash_password("Correct123Pass")
    admin_session.commit()

    resp = client.post("/api/auth/login", json={"personal_number": "7960001", "password": "wrong"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["attempts"] == 1
    assert body["max_attempts"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest -k test_login_401_reports_attempt_count -v`
Expected: FAIL — `KeyError: 'attempts'`

- [ ] **Step 3: Include attempt count in the 401 response**

```python
# backend/app/routes/auth.py:167-188 — replace the wrong-password branch
    if not verify_password(body.password, soldier.password_hash):
        new_count = soldier.failed_login_count + 1
        locked_now = new_count >= _LOCKOUT_THRESHOLD
        session.execute(
            sa_update(Soldier)
            .where(Soldier.id == soldier.id)
            .values(
                failed_login_count=sa_case(
                    (new_count >= _LOCKOUT_THRESHOLD, 0),
                    else_=new_count,
                ),
                locked_until=sa_case(
                    (new_count >= _LOCKOUT_THRESHOLD, _now_utc + _td(minutes=_LOCKOUT_MINUTES)),
                    else_=Soldier.locked_until,
                ),
            )
        )
        write_audit(
            session, actor_id=soldier.id, action="auth.login.failure", entity_type="soldier",
            entity_id=soldier.id, context={**_client_context(request), "personal_number": body.personal_number},
        )
        session.commit()
        if locked_now:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="account_locked",
                headers={"Retry-After": str(_LOCKOUT_MINUTES * 60)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": "invalid_credentials", "attempts": new_count, "max_attempts": _LOCKOUT_THRESHOLD},
        )
```

(FastAPI's `HTTPException.detail` can be a dict; it's serialized as the full JSON body's `"detail"` key, so the test above should assert `body["detail"]["attempts"]` — adjust Step 1's test to match once you confirm FastAPI's actual serialization shape by running it once and reading the failure output, rather than guessing blind.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest -k test_login_401_reports_attempt_count -v`
Expected: PASS

- [ ] **Step 5: Update `LoginPage.tsx` to show the attempt count**

```typescript
// frontend/src/pages/LoginPage.tsx — extend state and catch block
  const [attempts, setAttempts] = useState<{ n: number; max: number } | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErrorKey(null);
    setSubmitting(true);
    try {
      await login(personalNumber, password, rememberMe);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof AxiosError) {
        if (err.response?.status === 401) {
          setErrorKey("invalid_credentials");
          const d = err.response.data?.detail;
          if (d && typeof d === "object" && "attempts" in d) {
            setAttempts({ n: d.attempts, max: d.max_attempts });
          }
        } else if (err.response?.status === 429) {
          setErrorKey("rate_limited");
          setRetryAfterSeconds(err.response.headers["retry-after"] ?? null);
        } else {
          setErrorKey("network");
        }
      } else {
        setErrorKey("network");
      }
    } finally {
      setSubmitting(false);
    }
  }
```

```tsx
        {errorKey && (
          <div className="text-rejected text-sm" data-testid="login-error">
            {errorKey === "rate_limited" && retryAfterSeconds
              ? t("login.errors.rate_limited", { seconds: retryAfterSeconds })
              : t(`login.errors.${errorKey}`)}
            {errorKey === "invalid_credentials" && attempts && (
              <div>{t("login.errors.attempts_remaining", { n: attempts.n, max: attempts.max })}</div>
            )}
          </div>
        )}
```

```json
// frontend/src/i18n/he.json:16-18 — add a key
      "invalid_credentials": "מספר אישי או סיסמה שגויים",
      "attempts_remaining": "ניסיון {{n}} מתוך {{max}}, לאחר מכן החשבון ייחסם זמנית",
      "network": "שגיאת רשת. נסה שוב.",
      "rate_limited": "יותר מדי ניסיונות. נסה שוב בעוד {{seconds}} שניות."
```

- [ ] **Step 6: Run frontend tests + typecheck**

Run: `cd frontend && npm run typecheck && npm test -- LoginPage`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/auth.py frontend/src/pages/LoginPage.tsx frontend/src/i18n/he.json
git commit -m "feat: show failed-login attempt count on the login page"
```

---

## Task C1: System setting to restrict swaps to within a hierarchy level

**Files:**
- Modify: `backend/app/services/hierarchy.py` (add `ancestor_id_at_level`)
- Modify: `backend/app/services/swaps.py:22-` (`create_request`)
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Test: `backend/app/services/tests/test_hierarchy.py`, `backend/app/services/tests/test_swaps.py`

**Interfaces:**
- Produces: `hierarchy.ancestor_id_at_level(session: Session, node_id: uuid.UUID, level: str) -> uuid.UUID | None`

- [ ] **Step 1: Write the failing test for the ancestor helper**

```python
# backend/app/services/tests/test_hierarchy.py — add (check file exists first; create if not)
def test_ancestor_id_at_level_finds_matching_ancestor(admin_session):
    from app.services.hierarchy import ancestor_id_at_level
    from tests.helpers import create_node

    root = create_node(admin_session, level="division", name="div_test")
    branch = create_node(admin_session, level="branch", name="branch_test", parent=root)
    unit = create_node(admin_session, level="unit", name="unit_test", parent=branch)

    assert ancestor_id_at_level(admin_session, unit.id, "branch") == branch.id
    assert ancestor_id_at_level(admin_session, unit.id, "division") == root.id
    assert ancestor_id_at_level(admin_session, unit.id, "nonexistent_level") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_hierarchy.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `ancestor_id_at_level`**

```python
# backend/app/services/hierarchy.py — add
def ancestor_id_at_level(session: Session, node_id: uuid.UUID, level: str) -> uuid.UUID | None:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        return None
    candidate_ids = [*node.path_ids, node.id]
    rows = session.execute(
        select(HierarchyNode.id, HierarchyNode.level).where(HierarchyNode.id.in_(candidate_ids))
    ).all()
    by_level = {lvl: nid for nid, lvl in rows}
    return by_level.get(level)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_hierarchy.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for the swap restriction**

```python
# backend/app/services/tests/test_swaps.py — add
def test_create_request_blocked_across_hierarchy_level_when_restricted(admin_session):
    from app.services.swaps import create_request, SwapError
    from app.services.settings_loader import set_setting
    from tests.helpers import create_node, create_soldier

    branch_a = create_node(admin_session, level="branch", name="branch_a")
    branch_b = create_node(admin_session, level="branch", name="branch_b")
    unit_a = create_node(admin_session, level="unit", name="unit_a", parent=branch_a)
    unit_b = create_node(admin_session, level="unit", name="unit_b", parent=branch_b)
    requester = create_soldier(admin_session, personal_number="7970001", hierarchy_node_id=unit_a.id)
    target = create_soldier(admin_session, personal_number="7970002", hierarchy_node_id=unit_b.id)
    set_setting(admin_session, key="swaps.restrict_to_hierarchy_level", value="branch", actor_id=None)
    admin_session.commit()

    with pytest.raises(SwapError, match="hierarchy_level"):
        create_request(
            admin_session, requesting_soldier_id=requester.id,
            duty_assignment_id=None, target_soldier_id=target.id, reason=None,
        )
```

(Adjust `create_request`'s exact required kwargs to match its real signature — read `swaps.py:22-90` fully before finalizing this test; the plan author only confirmed the function starts at line 22.)

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_swaps.py -k restrict_to_hierarchy_level -v`
Expected: FAIL — no error raised

- [ ] **Step 7: Add the restriction check to `create_request`**

At the point in `create_request` where `target_soldier_id` is validated (after confirming the target soldier exists), add:

```python
    if target_soldier_id is not None:
        from app.services.settings_loader import SettingNotFound, get_setting
        try:
            level = get_setting(session, "swaps.restrict_to_hierarchy_level")
        except SettingNotFound:
            level = None
        if level:
            requester = session.get(Soldier, requesting_soldier_id)
            target = session.get(Soldier, target_soldier_id)
            from app.services.hierarchy import ancestor_id_at_level
            req_ancestor = ancestor_id_at_level(session, requester.hierarchy_node_id, level) if requester.hierarchy_node_id else None
            tgt_ancestor = ancestor_id_at_level(session, target.hierarchy_node_id, level) if target.hierarchy_node_id else None
            if req_ancestor is None or req_ancestor != tgt_ancestor:
                raise SwapError("hierarchy_level_mismatch")
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_swaps.py -v`
Expected: PASS

- [ ] **Step 9: Add the setting to the admin settings page**

```typescript
// frontend/src/pages/SystemSettingsPage.tsx — add a new group
  {
    label: "החלפות",
    settings: [
      { key: "swaps.require_manager_approval", label: "דורש אישור מפקד", description: "האם החלפות דורשות אישור מפקד", type: "boolean", defaultValue: true },
      { key: "swaps.restrict_to_hierarchy_level", label: "הגבלת החלפות לרמת היררכיה", description: "מגביל בקשות החלפה לחיילים החולקים אב משותף ברמה זו (ריק = ללא הגבלה)", type: "select", defaultValue: "", options: [] },
    ],
  },
```

(Populate `options` from the actual `hierarchy_level_types` rows via a query fetched on page load — check whether `SystemSettingsPage.tsx` already fetches hierarchy level types anywhere for a similar dropdown, e.g. duty-type eligible-node pickers, and reuse that query rather than adding a new one from scratch.)

- [ ] **Step 10: Run frontend typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/hierarchy.py backend/app/services/swaps.py backend/app/services/tests/test_hierarchy.py backend/app/services/tests/test_swaps.py frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat: add system setting to restrict swaps to within a hierarchy level"
```

---

## Task C2: System setting to fully disable Telegram

**Files:**
- Modify: `backend/app/routes/public_settings.py` (`_PUBLIC_KEYS`)
- Modify: `backend/app/services/notifications.py` (Telegram delivery gate, ~line 152-190)
- Modify: `frontend/src/App.tsx` (or router config — hide `TelegramSetupPage` route/nav)
- Modify: `frontend/src/components/TelegramBadge.tsx`
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Test: `backend/app/services/tests/test_notifications.py`

**Interfaces:**
- Produces: system setting `telegram.enabled` (bool, default `true`)

- [ ] **Step 1: Write the failing test**

```python
# backend/app/services/tests/test_notifications.py — add
def test_telegram_delivery_skipped_when_disabled(admin_session, monkeypatch):
    from app.services.settings_loader import set_setting
    from app.services import notifications as notif_svc
    from tests.helpers import create_soldier

    set_setting(admin_session, key="telegram.enabled", value=False, actor_id=None)
    admin_session.commit()

    called = {"n": 0}

    def fake_send(*args, **kwargs):
        called["n"] += 1

    monkeypatch.setattr(notif_svc, "_send_telegram_message", fake_send)
    soldier = create_soldier(admin_session, personal_number="7980001")
    notif_svc.send_telegram_notification(
        admin_session, soldier_id=soldier.id, title="test", body=None,
        notification_type=None,
    )
    assert called["n"] == 0
```

(Confirm the exact function name for Telegram delivery — the plan author identified it as being around `notifications.py:152-190` but did not pin the exact name; read that section first and adjust `_send_telegram_message`/`send_telegram_notification` to the real names before writing this test.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_notifications.py -k telegram_delivery_skipped -v`
Expected: FAIL — delivery still attempted

- [ ] **Step 3: Gate Telegram delivery on the setting**

At the top of the Telegram-sending function in `notifications.py` (~line 152), add:

```python
    from app.services.settings_loader import SettingNotFound, get_setting
    try:
        if not bool(get_setting(session, "telegram.enabled")):
            return
    except SettingNotFound:
        pass  # default: enabled
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_notifications.py -v`
Expected: PASS

- [ ] **Step 5: Also force off `registration.telegram_required` when disabled**

In `system_settings.py`'s `update_settings`, add a guard: if the merged settings would set `telegram.enabled` to `False`, also force `registration.telegram_required` to `False` in the same merged dict before writing (mirrors the existing `t > r` density guard style already in that function).

- [ ] **Step 6: Expose the flag publicly and hide Telegram UI when off**

```python
# backend/app/routes/public_settings.py — add to _PUBLIC_KEYS
_PUBLIC_KEYS = {
    "gimalim.enabled",
    "gimalim.default_rest_days",
    "gimalim.reserve_fate",
    "shifts.auto_split_node_quotas",
    "telegram.enabled",
}
```

In `frontend/src/App.tsx`, fetch `getPublicSettings()` (already used elsewhere per `frontend/src/api/publicSettings.ts`) and conditionally omit the `TelegramSetupPage` route/nav link when `settings["telegram.enabled"] === false` (default to `true` if the key is absent, matching backend's default-enabled fallback). In `frontend/src/components/TelegramBadge.tsx`, return `null` early when the same flag is off (fetch via the existing public-settings query, not a new one — check whether a shared hook/context already exposes `getPublicSettings()`'s result to avoid duplicate fetches).

- [ ] **Step 7: Add the setting to the admin settings page**

```typescript
// frontend/src/pages/SystemSettingsPage.tsx — add a new group
  {
    label: "טלגרם",
    settings: [
      { key: "telegram.enabled", label: "טלגרם מופעל", description: "כיבוי מסתיר את כל ממשק הטלגרם ומפסיק שליחת התראות דרכו", type: "boolean", defaultValue: true },
    ],
  },
```

- [ ] **Step 8: Run backend + frontend checks**

Run: `cd backend && pytest app/services/tests/test_notifications.py -v` then `cd frontend && npm run typecheck`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/routes/public_settings.py backend/app/services/notifications.py frontend/src/App.tsx frontend/src/components/TelegramBadge.tsx frontend/src/pages/SystemSettingsPage.tsx backend/app/services/tests/test_notifications.py
git commit -m "feat: add telegram.enabled kill-switch system setting"
```

---

## Task C3a: Hierarchy transfer requests — backend (model, service, routes, notifications)

**Files:**
- Create: `backend/alembic/versions/<new>_hierarchy_transfer_requests.py` (run `alembic revision -m "add hierarchy transfer requests"` from `backend/` to get the real filename/revision id — do not hand-invent one)
- Modify: `backend/app/db/models.py` (new `HierarchyTransferRequest` model, new `NotificationType.transfer_request_pending`, `transfer_request_rejected`)
- Create: `backend/app/services/hierarchy_transfers.py`
- Create: `backend/app/routes/hierarchy_transfers.py`
- Modify: `backend/app/main.py` (register the new router)
- Test: `backend/app/services/tests/test_hierarchy_transfers.py`, `backend/app/routes/tests/test_hierarchy_transfers.py`

**Interfaces:**
- Produces: `hierarchy_transfers.create_request(session, *, soldier_id, from_node_id, to_node_id, requested_by) -> HierarchyTransferRequest`, `hierarchy_transfers.approve_request(session, *, request_id, actor_id) -> HierarchyTransferRequest`, `hierarchy_transfers.reject_request(session, *, request_id, actor_id, decision_note) -> HierarchyTransferRequest`, `hierarchy_transfers.list_pending_for_approver(session, *, approver_id) -> list[HierarchyTransferRequest]`
- Consumes: `authz.authorize`, `notifications.create_notification`, `hierarchy.ancestor_id_at_level` is not needed here — this task moves a soldier to an exact node, no level matching involved

- [ ] **Step 1: Create the Alembic migration**

Run: `cd backend && alembic revision -m "add hierarchy transfer requests"`

Edit the generated file's `upgrade()`/`downgrade()`:

```python
def upgrade() -> None:
    op.create_table(
        "hierarchy_transfer_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id"), nullable=True),
        sa.Column("to_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id"), nullable=False),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id"), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'transfer_request_pending'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'transfer_request_rejected'")


def downgrade() -> None:
    op.drop_table("hierarchy_transfer_requests")
```

(`ALTER TYPE ... ADD VALUE` cannot run inside the same transaction as other DDL on some PG versions — check how a prior migration in this repo that added a `NotificationType` enum value handled this, e.g. `git log --oneline -- backend/alembic/versions | grep -i notif` to find precedent, and follow that pattern exactly, including any `autocommit_block()` usage.)

- [ ] **Step 2: Run the migration**

Run: `cd backend && alembic upgrade head`
Expected: succeeds, new table exists

- [ ] **Step 3: Add the model**

```python
# backend/app/db/models.py — add near HierarchyNode
class HierarchyTransferRequest(Base):
    __tablename__ = "hierarchy_transfer_requests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE"))
    from_node_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id"), nullable=True, default=None)
    to_node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), default="pending")
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=True, default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
```

Add `transfer_request_pending = "transfer_request_pending"` and `transfer_request_rejected = "transfer_request_rejected"` to `NotificationType` (models.py:829-853).

- [ ] **Step 4: Write the failing test for `create_request`**

```python
# backend/app/services/tests/test_hierarchy_transfers.py
from __future__ import annotations
import pytest


def test_create_request_does_not_move_soldier_immediately(admin_session):
    from app.services.hierarchy_transfers import create_request
    from tests.helpers import create_node, create_soldier

    src = create_node(admin_session, level="unit", name="src_unit")
    dst = create_node(admin_session, level="unit", name="dst_unit")
    soldier = create_soldier(admin_session, personal_number="7990001", hierarchy_node_id=src.id)
    requester = create_soldier(admin_session, personal_number="7990002", role="commander")

    req = create_request(admin_session, soldier_id=soldier.id, to_node_id=dst.id, requested_by=requester.id)
    admin_session.commit()

    assert req.status == "pending"
    assert soldier.hierarchy_node_id == src.id  # unchanged until approved


def test_approve_request_moves_soldier(admin_session):
    from app.services.hierarchy_transfers import create_request, approve_request
    from tests.helpers import create_node, create_soldier

    src = create_node(admin_session, level="unit", name="src_unit2")
    dst = create_node(admin_session, level="unit", name="dst_unit2")
    soldier = create_soldier(admin_session, personal_number="7990003", hierarchy_node_id=src.id)
    requester = create_soldier(admin_session, personal_number="7990004", role="commander")
    approver = create_soldier(admin_session, personal_number="7990005", role="commander")

    req = create_request(admin_session, soldier_id=soldier.id, to_node_id=dst.id, requested_by=requester.id)
    admin_session.commit()
    approve_request(admin_session, request_id=req.id, actor_id=approver.id)
    admin_session.commit()

    assert req.status == "approved"
    assert soldier.hierarchy_node_id == dst.id


def test_reject_request_leaves_soldier_in_place_and_notifies_requester(admin_session):
    from sqlalchemy import select
    from app.db.models import Notification, NotificationType
    from app.services.hierarchy_transfers import create_request, reject_request
    from tests.helpers import create_node, create_soldier

    src = create_node(admin_session, level="unit", name="src_unit3")
    dst = create_node(admin_session, level="unit", name="dst_unit3")
    soldier = create_soldier(admin_session, personal_number="7990006", hierarchy_node_id=src.id)
    requester = create_soldier(admin_session, personal_number="7990007", role="commander")
    approver = create_soldier(admin_session, personal_number="7990008", role="commander")

    req = create_request(admin_session, soldier_id=soldier.id, to_node_id=dst.id, requested_by=requester.id)
    admin_session.commit()
    reject_request(admin_session, request_id=req.id, actor_id=approver.id, decision_note="no room")
    admin_session.commit()

    assert req.status == "rejected"
    assert soldier.hierarchy_node_id == src.id
    notif = admin_session.execute(
        select(Notification).where(
            Notification.soldier_id == requester.id,
            Notification.type == NotificationType.transfer_request_rejected,
        )
    ).scalar_one_or_none()
    assert notif is not None
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_hierarchy_transfers.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 6: Implement `hierarchy_transfers.py`**

```python
# backend/app/services/hierarchy_transfers.py
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import HierarchyTransferRequest, NotificationType, Soldier
from app.services.notifications import create_notification


class HierarchyTransferError(Exception):
    """Raised on an invalid hierarchy transfer operation."""


def create_request(
    session: Session, *, soldier_id: uuid.UUID, to_node_id: uuid.UUID,
    requested_by: uuid.UUID,
) -> HierarchyTransferRequest:
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise HierarchyTransferError("soldier_not_found")
    req = HierarchyTransferRequest(
        soldier_id=soldier_id, from_node_id=soldier.hierarchy_node_id,
        to_node_id=to_node_id, requested_by=requested_by,
    )
    session.add(req)
    session.flush()
    _notify_destination_approvers(session, req)
    write_audit(
        session, actor_id=requested_by, action="hierarchy_transfer.request",
        entity_type="hierarchy_transfer_request", entity_id=req.id,
        after={"soldier_id": str(soldier_id), "to_node_id": str(to_node_id)},
    )
    return req


def _notify_destination_approvers(session: Session, req: HierarchyTransferRequest) -> None:
    from app.db.models import DutyManagerScope, HierarchyNode
    node = session.get(HierarchyNode, req.to_node_id)
    approver_ids: set[uuid.UUID] = set()
    if node and node.commander_id:
        approver_ids.add(node.commander_id)
    dm_rows = session.execute(
        select(DutyManagerScope.duty_manager_id).where(DutyManagerScope.hierarchy_node_id == req.to_node_id)
    ).scalars().all()
    approver_ids.update(dm_rows)
    for approver_id in approver_ids:
        create_notification(
            session, soldier_id=approver_id, type=NotificationType.transfer_request_pending,
            title="בקשת העברת חייל למסגרת שלך ממתינה לאישור",
            reference_type="hierarchy_transfer_request", reference_id=req.id,
        )


def approve_request(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID,
) -> HierarchyTransferRequest:
    req = session.get(HierarchyTransferRequest, request_id)
    if req is None:
        raise HierarchyTransferError("request_not_found")
    if req.status != "pending":
        raise HierarchyTransferError("not_pending")
    soldier = session.get(Soldier, req.soldier_id)
    soldier.hierarchy_node_id = req.to_node_id
    req.status = "approved"
    req.decided_by = actor_id
    write_audit(
        session, actor_id=actor_id, action="hierarchy_transfer.approve",
        entity_type="hierarchy_transfer_request", entity_id=req.id,
        after={"to_node_id": str(req.to_node_id)},
    )
    return req


def reject_request(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID, decision_note: str | None = None,
) -> HierarchyTransferRequest:
    req = session.get(HierarchyTransferRequest, request_id)
    if req is None:
        raise HierarchyTransferError("request_not_found")
    if req.status != "pending":
        raise HierarchyTransferError("not_pending")
    req.status = "rejected"
    req.decided_by = actor_id
    req.decision_note = decision_note
    create_notification(
        session, soldier_id=req.requested_by, type=NotificationType.transfer_request_rejected,
        title="בקשת העברת החייל נדחתה", reference_type="hierarchy_transfer_request",
        reference_id=req.id, actor_id=actor_id,
    )
    write_audit(
        session, actor_id=actor_id, action="hierarchy_transfer.reject",
        entity_type="hierarchy_transfer_request", entity_id=req.id,
        after={"decision_note": decision_note},
    )
    return req


def list_pending_for_approver(session: Session, *, approver_id: uuid.UUID) -> list[HierarchyTransferRequest]:
    from app.db.models import DutyManagerScope, HierarchyNode
    commanded_nodes = session.execute(
        select(HierarchyNode.id).where(HierarchyNode.commander_id == approver_id)
    ).scalars().all()
    dm_nodes = session.execute(
        select(DutyManagerScope.hierarchy_node_id).where(DutyManagerScope.duty_manager_id == approver_id)
    ).scalars().all()
    node_ids = set(commanded_nodes) | set(dm_nodes)
    if not node_ids:
        return []
    return list(session.execute(
        select(HierarchyTransferRequest).where(
            HierarchyTransferRequest.to_node_id.in_(node_ids),
            HierarchyTransferRequest.status == "pending",
        )
    ).scalars())
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_hierarchy_transfers.py -v`
Expected: PASS

- [ ] **Step 8: Write the failing route test**

```python
# backend/app/routes/tests/test_hierarchy_transfers.py
from tests.helpers import auth_headers, create_node, create_soldier


def test_create_and_approve_transfer_via_api(client, admin_session):
    src = create_node(admin_session, level="unit", name="api_src")
    dst = create_node(admin_session, level="unit", name="api_dst")
    soldier = create_soldier(admin_session, personal_number="7991001", hierarchy_node_id=src.id)
    admin = create_soldier(admin_session, personal_number="7991002", role="admin")

    resp = client.post(
        "/api/hierarchy-transfers",
        json={"soldier_id": str(soldier.id), "to_node_id": str(dst.id)},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    req_id = resp.json()["id"]

    resp2 = client.post(f"/api/hierarchy-transfers/{req_id}/approve", headers=auth_headers(admin))
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "approved"
```

- [ ] **Step 9: Run test to verify it fails**

Run: `cd backend && pytest app/routes/tests/test_hierarchy_transfers.py -v`
Expected: FAIL — 404

- [ ] **Step 10: Implement the routes**

```python
# backend/app/routes/hierarchy_transfers.py
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import hierarchy_transfers as svc

router = APIRouter(prefix="/hierarchy-transfers", tags=["hierarchy_transfers"])


class CreateTransferBody(BaseModel):
    soldier_id: uuid.UUID
    to_node_id: uuid.UUID


class DecisionBody(BaseModel):
    decision_note: str | None = None


class TransferOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    from_node_id: uuid.UUID | None
    to_node_id: uuid.UUID
    status: str


def _out(req) -> TransferOut:
    return TransferOut(
        id=req.id, soldier_id=req.soldier_id, from_node_id=req.from_node_id,
        to_node_id=req.to_node_id, status=req.status,
    )


@router.post("", response_model=TransferOut)
def create_transfer(
    body: CreateTransferBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransferOut:
    soldier = session.get(Soldier, body.soldier_id)
    if soldier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="soldier_not_found")
    source_node = session.get(HierarchyNode, soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=source_node)
    try:
        req = svc.create_request(session, soldier_id=body.soldier_id, to_node_id=body.to_node_id, requested_by=user.id)
    except svc.HierarchyTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    session.commit()
    return _out(req)


@router.post("/{request_id}/approve", response_model=TransferOut)
def approve_transfer(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransferOut:
    from app.db.models import HierarchyTransferRequest
    req = session.get(HierarchyTransferRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request_not_found")
    dest_node = session.get(HierarchyNode, req.to_node_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=dest_node)
    try:
        req = svc.approve_request(session, request_id=request_id, actor_id=user.id)
    except svc.HierarchyTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    session.commit()
    return _out(req)


@router.post("/{request_id}/reject", response_model=TransferOut)
def reject_transfer(
    request_id: uuid.UUID,
    body: DecisionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransferOut:
    from app.db.models import HierarchyTransferRequest
    req = session.get(HierarchyTransferRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request_not_found")
    dest_node = session.get(HierarchyNode, req.to_node_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=dest_node)
    try:
        req = svc.reject_request(session, request_id=request_id, actor_id=user.id, decision_note=body.decision_note)
    except svc.HierarchyTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    session.commit()
    return _out(req)


@router.get("/pending", response_model=list[TransferOut])
def list_pending(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[TransferOut]:
    return [_out(r) for r in svc.list_pending_for_approver(session, approver_id=user.id)]
```

Register the router in `backend/app/main.py` next to the other `include_router` calls:

```python
    app.include_router(hierarchy_transfer_routes.router, prefix="/api")
```

(and the matching import at the top of `main.py`, following the existing `from app.routes import ... as ..._routes` pattern used for every other router.)

- [ ] **Step 11: Run test to verify it passes**

Run: `cd backend && pytest app/routes/tests/test_hierarchy_transfers.py -v`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
git add backend/alembic/versions backend/app/db/models.py backend/app/services/hierarchy_transfers.py backend/app/routes/hierarchy_transfers.py backend/app/main.py backend/app/services/tests/test_hierarchy_transfers.py backend/app/routes/tests/test_hierarchy_transfers.py
git commit -m "feat: add hierarchy transfer requests requiring destination approval"
```

---

## Task C3b: Hierarchy transfer requests — frontend integration

**Files:**
- Create: `frontend/src/api/hierarchyTransfers.ts`
- Modify: `frontend/src/components/EntriesExitsPanel.tsx` (`handleMove`)
- Modify: `frontend/src/pages/ApprovalsPage.tsx` (new "transfers" tab)
- Modify: `frontend/src/i18n/he.json`
- Test: `frontend/src/components/EntriesExitsPanel.test.tsx` (check first), `frontend/src/pages/ApprovalsPage.test.tsx`

**Interfaces:**
- Consumes: `POST /hierarchy-transfers`, `POST /hierarchy-transfers/{id}/approve`, `POST /hierarchy-transfers/{id}/reject`, `GET /hierarchy-transfers/pending` (Task C3a)

- [ ] **Step 1: Add the API client**

```typescript
// frontend/src/api/hierarchyTransfers.ts
import { api } from "./client";

export interface TransferRequest {
  id: string;
  soldier_id: string;
  from_node_id: string | null;
  to_node_id: string;
  status: string;
}

export async function createTransferRequest(soldierId: string, toNodeId: string): Promise<TransferRequest> {
  return (await api.post<TransferRequest>("/hierarchy-transfers", { soldier_id: soldierId, to_node_id: toNodeId })).data;
}

export async function approveTransferRequest(id: string): Promise<TransferRequest> {
  return (await api.post<TransferRequest>(`/hierarchy-transfers/${id}/approve`)).data;
}

export async function rejectTransferRequest(id: string, decisionNote?: string): Promise<TransferRequest> {
  return (await api.post<TransferRequest>(`/hierarchy-transfers/${id}/reject`, { decision_note: decisionNote ?? null })).data;
}

export async function listPendingTransferRequests(): Promise<TransferRequest[]> {
  return (await api.get<TransferRequest[]>("/hierarchy-transfers/pending")).data;
}
```

- [ ] **Step 2: Write the failing test for `EntriesExitsPanel`'s move flow**

```typescript
// frontend/src/components/EntriesExitsPanel.test.tsx (create if missing — check first)
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import EntriesExitsPanel from "./EntriesExitsPanel";

vi.mock("../api/hierarchyTransfers", () => ({
  createTransferRequest: vi.fn().mockResolvedValue({ id: "t1", status: "pending" }),
}));
vi.mock("../api/soldiers", () => ({ softDeleteSoldier: vi.fn(), updateSoldier: vi.fn() }));
vi.mock("../api/hierarchy", () => ({ fetchTree: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/exemptions", () => ({ grantExemption: vi.fn() }));
vi.mock("../api/dutyConfig", () => ({ listExemptionTypes: vi.fn().mockResolvedValue([]) }));

it("moving a soldier creates a transfer request instead of moving them directly", async () => {
  const { createTransferRequest } = await import("../api/hierarchyTransfers");
  render(<EntriesExitsPanel soldiers={[{ id: "s1", full_name: "test", status: "active" } as any]} onRefresh={() => {}} />);
  fireEvent.click(screen.getAllByText(/העבר/)[0]);
  // ... select a target node via the Combobox, then confirm
  // exact interaction depends on Combobox's test API — follow the pattern
  // already used in this repo's Combobox.test.tsx for selecting an option
  await waitFor(() => expect(createTransferRequest).toHaveBeenCalled());
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm test -- EntriesExitsPanel`
Expected: FAIL — `updateSoldier` still called directly, not `createTransferRequest`

- [ ] **Step 4: Update `handleMove` to create a transfer request**

```typescript
// frontend/src/components/EntriesExitsPanel.tsx:56-62 — replace handleMove
  async function handleMove() {
    if (!moveTarget || !targetNodeId) return;
    await createTransferRequest(moveTarget.id, targetNodeId);
    setMoveTarget(null);
    setTargetNodeId("");
    onRefresh();
  }
```

Import `createTransferRequest` from `"../api/hierarchyTransfers"`; remove the now-unused `updateSoldier` import if nothing else in the file uses it. Update the "confirm" button's label (`t("command_dashboard.move_confirm")`) copy in `he.json` if it implied an immediate move (e.g. change `"אשר העברה"` wording to `"שלח בקשת העברה"` if that key's current text implies immediacy — check the current string first).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test -- EntriesExitsPanel`
Expected: PASS

- [ ] **Step 6: Add a "transfers" tab to `ApprovalsPage`**

In `frontend/src/pages/ApprovalsPage.tsx`:
- Add `"transfers"` to the `Tab` type and `VALID_TABS` array (line ~47-49).
- Add a query using `listPendingTransferRequests()` (react-query, following the same pattern as the existing `listPendingSwaps`/`listPendingEnrollments` queries in this file).
- Render a list of pending transfers with soldier name, from-node name, to-node name, and approve/reject buttons calling `approveTransferRequest`/`rejectTransferRequest`, followed by `queryClient.invalidateQueries` for the transfers query key — mirror the existing swaps/enrollment tab's approve/reject button markup and `data-testid` naming convention exactly (e.g. `transfer-approve-${req.id}`) for consistency.
- Add the new tab's label to `he.json` (e.g. `"approvals.tabs.transfers": "העברות"` — check the exact existing key path for tab labels first).

- [ ] **Step 7: Write the failing test for the new tab**

```typescript
// frontend/src/pages/ApprovalsPage.test.tsx — add
it("shows pending transfer requests with approve/reject actions", async () => {
  // mock listPendingTransferRequests to return one pending request,
  // render ApprovalsPage on the "transfers" tab, assert the approve button
  // renders and calling it invokes approveTransferRequest.
  // Follow this file's existing mock/render pattern for the swaps tab.
});
```

- [ ] **Step 8: Run test to verify it fails, then implement, then verify it passes**

Run: `cd frontend && npm test -- ApprovalsPage`
Expected: FAIL, then implement per Step 6, then PASS

- [ ] **Step 9: Run full frontend typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS

- [ ] **Step 10: Manual verification**

Start `.\dev.ps1`, log in as a commander, use the entries/exits panel to move a soldier to a sub-node you don't directly command, confirm no immediate move happens and a notification/pending item appears for that node's commander, then approve it from the Approvals page as that commander and confirm the soldier's hierarchy node actually changes.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/api/hierarchyTransfers.ts frontend/src/components/EntriesExitsPanel.tsx frontend/src/pages/ApprovalsPage.tsx frontend/src/i18n/he.json frontend/src/components/EntriesExitsPanel.test.tsx frontend/src/pages/ApprovalsPage.test.tsx
git commit -m "feat: route hierarchy transfers through destination-commander approval in the UI"
```

---

## Final check

- [ ] **Run the fast backend suite**: `cd backend && pytest -q`
- [ ] **Run the frontend suite**: `cd frontend && npm test && npm run lint && npm run typecheck`
- [ ] **Run the slow backend suite once, before merge**: `cd backend && pytest --slow -q`
- [ ] Hand off to the `merge-worktree-to-dev` skill to merge `feedback-batch-2026-07-19` into `dev`.
