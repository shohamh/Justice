# Ranks & Registration Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix rank-classification bugs (officer/enlisted, בה"ד 1 graduate) in registration and enrollment-approval, fix the transparency-page rank sort direction, fix a false-positive registration rejection for חובה-track privates, add rank↔track (חובה/קבע) compatibility validation with UI, and fix duty-type data that incorrectly excludes all enlisted קבע soldiers from every duty type.

**Architecture:** The backend already has a canonical rank classification in `backend/app/services/eligibility.py` (`ENLISTED_RANKS`, `OFFICER_RANKS`, `CHOVAH_ONLY_RANKS`). The frontend currently hand-duplicates these lists (incorrectly) in two places. This plan (1) extracts a single shared frontend rank-constants module and fixes the misclassification, (2) stops deriving `bahad1_graduate` from `is_officer`, (3) fixes the transparency page's default sort direction, (4) loosens an overly-strict date-consistency guard that falsely rejects legitimate חייל/חובה registrations, and (5) adds a new rank↔track compatibility table enforced server-side (Pydantic validators) and reflected client-side (rank picker options filtered/warned by track).

**Tech Stack:** Python/FastAPI/SQLAlchemy/Pydantic (backend), React/TypeScript/Vite (frontend), pytest (backend tests), vitest (frontend tests).

## Global Constraints

- Hebrew UI strings only (no new hardcoded English) — add new strings to `frontend/src/i18n/he.json`.
- Do not change `backend/app/services/eligibility.py`'s existing exported names (`ENLISTED_RANKS`, `OFFICER_RANKS`, `CHOVAH_ONLY_RANKS`, `RANKS_RASAN_AND_ABOVE`) — other modules import them.
- Run `pytest -m auth -q` and `pytest -m soldiers -q` (not the full suite) after backend changes in this plan; run `npm run typecheck` and targeted `npm test` files after frontend changes.
- Follow existing code style: backend uses `Mapped[...]` SQLAlchemy 2.0 style; frontend uses function components with hooks, Tailwind classes, `t()` for i18n.

---

## File Structure

- **Create:** `frontend/src/constants/ranks.ts` — single source of truth for `ENLISTED_RANKS`, `OFFICER_RANKS`, `CHOVAH_ONLY_RANKS`, `RANKS_RASAN_AND_ABOVE`, plus a new `RANK_TRACK_COMPATIBILITY` map, mirroring `backend/app/services/eligibility.py`.
- **Modify:** `frontend/src/pages/RegisterPage.tsx` — use the shared constants, stop auto-deriving `bahad1_graduate`, add track-compatibility validation UI.
- **Modify:** `frontend/src/components/EnrollmentApprovalModal.tsx` — use the shared constants.
- **Modify:** `frontend/src/components/DataTable.tsx` — support per-column initial/default sort direction override.
- **Modify:** `frontend/src/pages/TransparencyPage.tsx` — set the rank column to sort senior-first by default.
- **Modify:** `backend/app/services/soldiers.py` — loosen `_check_soldier_dates`'s false-positive guard.
- **Modify:** `backend/app/services/eligibility.py` — add `RANK_TRACK_COMPATIBILITY` map and a `validate_rank_track_compatibility()` helper.
- **Modify:** `backend/app/routes/auth.py` — call the new validator in `RegisterRequest` handling.
- **Modify:** `backend/app/routes/soldiers.py` — call the new validator in `UpdateProfileRequest` handling and field-update approval.
- **Modify:** `backend/app/scripts/seed.py` — add `"קבע"` to `allowed_service_types` for the 10 enlisted-eligible duty types that were incorrectly חובה-only.
- **Create:** `backend/alembic/versions/<rev>_add_keva_to_duty_type_allowed_service_types.py` — corrects existing/already-deployed data to match.
- **Test:** `backend/app/services/tests/test_eligibility.py`, `backend/app/services/tests/test_registration.py`, `backend/app/services/tests/test_soldiers.py`, `frontend/src/pages/RegisterPage.test.tsx` (new).

---

### Task 1: Shared frontend rank constants (fix סג"ם/קמ"א misclassification)

**Files:**
- Create: `frontend/src/constants/ranks.ts`
- Modify: `frontend/src/pages/RegisterPage.tsx:17-18` (remove local lists, import shared ones)
- Modify: `frontend/src/components/EnrollmentApprovalModal.tsx:8-9` (remove local lists, import shared ones)
- Test: `frontend/src/constants/ranks.test.ts` (new)

**Interfaces:**
- Produces: `ENLISTED_RANKS: string[]`, `OFFICER_RANKS: string[]`, `ALL_RANKS: string[]`, `isOfficerRank(rank: string): boolean`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/constants/ranks.test.ts
import { describe, it, expect } from "vitest";
import { ENLISTED_RANKS, OFFICER_RANKS, isOfficerRank } from "./ranks";

describe("rank constants", () => {
  it("classifies סגמ (סג\"ם) as an officer rank, not enlisted", () => {
    expect(OFFICER_RANKS).toContain("סגמ");
    expect(ENLISTED_RANKS).not.toContain("סגמ");
    expect(isOfficerRank("סגמ")).toBe(true);
  });

  it("classifies קמא as an officer rank, not enlisted", () => {
    expect(OFFICER_RANKS).toContain("קמא");
    expect(ENLISTED_RANKS).not.toContain("קמא");
  });

  it("classifies רסל (רס\"ל) as enlisted, not officer", () => {
    expect(ENLISTED_RANKS).toContain("רסל");
    expect(isOfficerRank("רסל")).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/constants/ranks.test.ts`
Expected: FAIL — `Cannot find module './ranks'`

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/constants/ranks.ts
// Mirrors backend/app/services/eligibility.py ENLISTED_RANKS / OFFICER_RANKS.
// Keep these two lists in sync with the backend if ranks are ever added/removed.
export const ENLISTED_RANKS = [
  "טוראי", "רבט", "סמל", "סמר", "רסל", "רסר", "רסמ", "רסב", "רנג",
];

export const OFFICER_RANKS = [
  "קמא", "סגמ", "סגן", "קאב", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
];

export const ALL_RANKS = [...ENLISTED_RANKS, ...OFFICER_RANKS];

const OFFICER_RANK_SET = new Set(OFFICER_RANKS);

export function isOfficerRank(rank: string): boolean {
  return OFFICER_RANK_SET.has(rank);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/constants/ranks.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Wire RegisterPage.tsx to the shared constants**

In `frontend/src/pages/RegisterPage.tsx`, replace lines 17-18:

```ts
// BEFORE (lines 17-18)
const ENLISTED_RANKS = ["טוראי","רבט","סמל","סמר","רסל","רסר","רסמ","רסב","רנג","קמא","סגמ"];
const OFFICER_RANKS_LIST = ["סגן","קאב","סרן","רסן","סאל","אלמ","תאל","אלוף","רב אלוף"];
```

```ts
// AFTER
import { ENLISTED_RANKS, OFFICER_RANKS as OFFICER_RANKS_LIST } from "../constants/ranks";
```

Then find every other reference to the old local `OFFICER_RANKS` variable name in the file (the `onChange` handler around line 219-221 uses `OFFICER_RANKS.has(v)` — note the original code used a `Set`; adjust to use `OFFICER_RANKS_LIST.includes(v)` or build a `Set` from the import) and update to match. Keep the rest of the file's logic identical except for the source of these two arrays.

- [ ] **Step 6: Wire EnrollmentApprovalModal.tsx to the shared constants**

In `frontend/src/components/EnrollmentApprovalModal.tsx`, replace lines 8-9:

```ts
// BEFORE (lines 8-9)
const RANKS_ENLISTED = [...];
const RANKS_OFFICER = [...];
```

```ts
// AFTER
import { ENLISTED_RANKS as RANKS_ENLISTED, OFFICER_RANKS as RANKS_OFFICER } from "../constants/ranks";
```

Update the `RANKS_OFFICER.includes(v)` call at line ~149 to keep working (it already uses `.includes`, so this should be a drop-in replacement as long as `RANKS_OFFICER` is an array, which it is).

- [ ] **Step 7: Manually verify in the running app**

Start `.\dev.ps1`, go to `/register`, select rank "סג\"ם" in the rank dropdown, confirm the officer-only fields (e.g. בה"ד 1 graduate checkbox, if shown conditionally on `is_officer`) now appear. Then go to an enrollment approval (as a commander) and confirm the same rank shows as officer there too.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/constants/ranks.ts frontend/src/constants/ranks.test.ts frontend/src/pages/RegisterPage.tsx frontend/src/components/EnrollmentApprovalModal.tsx
git commit -m "fix: classify סג\"ם and קמ\"א as officer ranks in registration and enrollment approval"
```

---

### Task 2: Stop auto-deriving `bahad1_graduate` from `is_officer`

**Files:**
- Modify: `frontend/src/pages/RegisterPage.tsx:219-221` (rank `onChange` handler)
- Test: manual (form-state logic, no existing unit test harness for this component — see Step 3)

**Interfaces:**
- Consumes: `isOfficerRank` from Task 1's `frontend/src/constants/ranks.ts`
- Produces: form field `bahad1_graduate` now defaults to `false` and is independently editable by the user, no longer silently forced to match `is_officer`.

- [ ] **Step 1: Read current behavior**

In `frontend/src/pages/RegisterPage.tsx` around line 219-221, the rank `onChange` currently does:

```ts
const isOfficer = OFFICER_RANKS.has(v);
setForm(prev => ({ ...prev, rank: v, is_officer: isOfficer, bahad1_graduate: isOfficer, ... }));
```

- [ ] **Step 2: Fix — stop forcing `bahad1_graduate`**

```ts
// AFTER
const isOfficer = isOfficerRank(v);
setForm(prev => ({
  ...prev,
  rank: v,
  is_officer: isOfficer,
  // bahad1_graduate is a separate fact from is_officer — e.g. קא"ב
  // (academic officer) is an officer who did NOT graduate בה"ד 1.
  // Reset to false on rank change instead of mirroring is_officer, and let
  // the user check the "בה"ד 1 graduate" checkbox explicitly when relevant.
  bahad1_graduate: false,
  ...
}));
```

Confirm the "בה"ד 1 graduate" checkbox in the officer-fields section of the form is NOT disabled/hidden — it must already be a normal, independently-toggleable checkbox (search the render section for `bahad1_graduate` to confirm; if it's currently read-only/derived-display-only, change it to a normal `<input type="checkbox">` bound to `form.bahad1_graduate`).

- [ ] **Step 3: Manually verify in the running app**

Start `.\dev.ps1`, go to `/register`, pick rank "קא\"ב" (an officer rank that is not a בה"ד 1 graduate), confirm the בה"ד 1 graduate checkbox starts unchecked and can be toggled independently without being forced back.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/RegisterPage.tsx
git commit -m "fix: stop auto-marking every officer rank as a בה\"ד 1 graduate"
```

---

### Task 3: Fix transparency page rank sort direction

**Files:**
- Modify: `frontend/src/components/DataTable.tsx` (around line 297, `sortDescFirst` column option)
- Modify: `frontend/src/pages/TransparencyPage.tsx:50-73, 573` (rank column definition)
- Test: `frontend/src/components/DataTable.test.tsx` if it exists (check first); otherwise manual verification only (DataTable is a generic, already-tested-elsewhere component — do not add a new full test harness for one column config change).

**Interfaces:**
- Consumes: existing `DataTable` column config shape (has a `sortDescFirst?: boolean` field per column, confirmed at `DataTable.tsx:297`)

- [ ] **Step 1: Confirm current default**

Read `frontend/src/components/DataTable.tsx` lines 270-300 to confirm the column-level `sortDescFirst` option exists and how it's consumed by the sort comparator (already confirmed in investigation: `sortDescFirst: false` currently on the rank column means first click sorts ascending by `_rank_order`, i.e. junior rank first).

- [ ] **Step 2: Set the rank column to sort senior-first by default**

In `frontend/src/pages/TransparencyPage.tsx` at line 573 (the rank column definition passed to `DataTable`), add/set `sortDescFirst: true`:

```tsx
// around TransparencyPage.tsx:573
{
  key: "rank",
  label: "דרגה",
  sortValue: (r) => r._rank_order,
  sortDescFirst: true, // senior ranks (higher _rank_order) should sort first
  ...
}
```

Adjust to match the exact existing object shape at that line (read the file first to get exact key names — the investigation confirmed `_rank_order` is used as `sortValue` here).

- [ ] **Step 3: Manually verify in the running app**

Start `.\dev.ps1`, go to `/transparency`, click the "דרגה" (rank) column header once, confirm אל"ם now appears above סג"ם (senior first). Click again to confirm it toggles to ascending correctly.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx
git commit -m "fix: sort transparency page rank column senior-first by default"
```

---

### Task 4: Fix false-positive registration rejection for חובה-track privates

**Files:**
- Modify: `backend/app/services/soldiers.py:48-57` (`_check_soldier_dates`)
- Test: `backend/app/services/tests/test_soldiers.py` (add new test; check the file first for existing test structure/fixtures to match style)

**Interfaces:**
- Consumes: existing `CHOVAH_ONLY_RANKS` from `backend/app/services/eligibility.py`
- Produces: `_check_soldier_dates(rank, mandatory_end_date, discharge_date)` — same signature, tightened condition.

- [ ] **Step 1: Write the failing test**

Read `backend/app/services/tests/test_soldiers.py` first to match existing fixture/import style (likely uses `pytest` fixtures for a DB session, or calls `_check_soldier_dates` directly if it's a pure function — confirm signature at `soldiers.py:34-57` before writing). Add:

```python
# backend/app/services/tests/test_soldiers.py
from datetime import date, timedelta
import pytest
from app.services.soldiers import _check_soldier_dates, SoldierValidationError

def test_chovah_private_with_past_mandatory_end_and_no_discharge_date_is_allowed():
    """A currently-serving טוראי whose mandatory_end_date field is in the past
    but who has no discharge_date yet (i.e. still serving, discharge just not
    logged) must NOT be rejected as an inconsistent 'chovah rank cannot be keva'.
    """
    past_end = date.today() - timedelta(days=10)
    # Should not raise.
    _check_soldier_dates(rank="טוראי", mandatory_end_date=past_end, discharge_date=None)

def test_chovah_private_with_explicit_inconsistent_discharge_date_still_rejected():
    """If a discharge_date IS provided and it's after mandatory_end_date for a
    CHOVAH-only rank, that's a genuine inconsistency and must still be rejected.
    """
    past_end = date.today() - timedelta(days=10)
    later_discharge = date.today() + timedelta(days=5)
    with pytest.raises(SoldierValidationError):
        _check_soldier_dates(rank="טוראי", mandatory_end_date=past_end, discharge_date=later_discharge)
```

(If `_check_soldier_dates` takes different parameter names or additional required args, read `soldiers.py:34-57` first and adjust the test call signature to match exactly — do not guess.)

- [ ] **Step 2: Run test to verify the first case currently fails**

Run: `cd backend && pytest app/services/tests/test_soldiers.py -k "chovah_private" -v`
Expected: `test_chovah_private_with_past_mandatory_end_and_no_discharge_date_is_allowed` FAILS (raises `SoldierValidationError` when it shouldn't); the second test should already PASS.

- [ ] **Step 3: Fix the guard condition**

In `backend/app/services/soldiers.py` lines 48-57:

```python
# BEFORE
if (
    rank in CHOVAH_ONLY_RANKS
    and mandatory_end_date is not None
    and date.today() > mandatory_end_date
    and (discharge_date is None or discharge_date > mandatory_end_date)
):
    raise SoldierValidationError("chovah_rank_cannot_be_keva")
```

```python
# AFTER
if (
    rank in CHOVAH_ONLY_RANKS
    and mandatory_end_date is not None
    and date.today() > mandatory_end_date
    # Only a genuine inconsistency: an explicit discharge_date that is itself
    # after mandatory_end_date. A soldier with no discharge_date yet is simply
    # still serving past their originally-planned mandatory_end_date, which is
    # common and not an error.
    and discharge_date is not None
    and discharge_date > mandatory_end_date
):
    raise SoldierValidationError("chovah_rank_cannot_be_keva")
```

- [ ] **Step 4: Run tests to verify both pass**

Run: `cd backend && pytest app/services/tests/test_soldiers.py -k "chovah_private" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the broader soldiers/auth test markers to check for regressions**

Run: `cd backend && pytest -m "soldiers or auth" -q`
Expected: PASS (no new failures)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/soldiers.py backend/app/services/tests/test_soldiers.py
git commit -m "fix: stop rejecting חובה-rank registration when discharge_date is simply unset"
```

---

### Task 5: Rank↔track compatibility table + backend validation

**Files:**
- Modify: `backend/app/services/eligibility.py` (add compatibility map + validator function, after existing constants around line 28)
- Modify: `backend/app/routes/auth.py` (call validator in registration path, near line 333)
- Modify: `backend/app/routes/soldiers.py` (call validator in profile-update path, near line 92-103, and in field-update approval)
- Test: `backend/app/services/tests/test_eligibility.py` (add tests; check file first for existing structure)

**Interfaces:**
- Produces: `RANK_TRACK_COMPATIBILITY: dict[str, set[str]]` (values are subsets of `{"חובה", "קבע"}`), `validate_rank_track_compatibility(rank: str, is_career: bool) -> None` (raises `ValueError` with a clear message on mismatch, returns `None` on success or when the rank has no restriction).

- [ ] **Step 1: Write the failing test**

Read `backend/app/services/tests/test_eligibility.py` first for existing import/style conventions, then add:

```python
# backend/app/services/tests/test_eligibility.py
import pytest
from app.services.eligibility import validate_rank_track_compatibility

def test_chovah_only_rank_rejects_career_track():
    with pytest.raises(ValueError, match="rank_track_incompatible"):
        validate_rank_track_compatibility(rank="טוראי", is_career=True)

def test_chovah_only_rank_accepts_mandatory_track():
    validate_rank_track_compatibility(rank="טוראי", is_career=False)  # should not raise

def test_keva_only_rank_rejects_mandatory_track():
    with pytest.raises(ValueError, match="rank_track_incompatible"):
        validate_rank_track_compatibility(rank="רסל", is_career=False)

def test_keva_only_rank_accepts_career_track():
    validate_rank_track_compatibility(rank="רסל", is_career=True)  # should not raise

def test_kaab_is_keva_only():
    with pytest.raises(ValueError, match="rank_track_incompatible"):
        validate_rank_track_compatibility(rank="קאב", is_career=False)
    validate_rank_track_compatibility(rank="קאב", is_career=True)  # should not raise

def test_saren_is_keva_only():
    with pytest.raises(ValueError, match="rank_track_incompatible"):
        validate_rank_track_compatibility(rank="סרן", is_career=False)
    validate_rank_track_compatibility(rank="סרן", is_career=True)  # should not raise

def test_sgan_is_ambiguous_and_accepts_either_track():
    validate_rank_track_compatibility(rank="סגן", is_career=True)
    validate_rank_track_compatibility(rank="סגן", is_career=False)

def test_unknown_rank_is_not_restricted():
    validate_rank_track_compatibility(rank="not_a_real_rank", is_career=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_eligibility.py -k "rank_track" -v`
Expected: FAIL — `ImportError: cannot import name 'validate_rank_track_compatibility'`

- [ ] **Step 3: Implement the compatibility map and validator**

In `backend/app/services/eligibility.py`, after the existing constants block (after `RANKS_RASAN_AND_ABOVE`, i.e. after line 28):

```python
# Ranks that structurally cannot exist on the other track, confirmed with
# product: קא"ב and סרן are קבע-only officer ranks (added explicitly below,
# since neither falls under RANKS_RASAN_AND_ABOVE); סג"ם is always חובה
# (already covered by CHOVAH_ONLY_RANKS). סגן is the only rank left
# deliberately unrestricted — it can be either track.
_CHOVAH_ONLY_TRACK_RANKS = frozenset(CHOVAH_ONLY_RANKS)
_KEVA_ONLY_TRACK_RANKS = frozenset(
    [r for r in ENLISTED_RANKS if r not in CHOVAH_ONLY_RANKS]
    + list(RANKS_RASAN_AND_ABOVE)
    + ["קאב", "סרן"]
)

RANK_TRACK_COMPATIBILITY: dict[str, frozenset[str]] = {
    **{r: frozenset({"חובה"}) for r in _CHOVAH_ONLY_TRACK_RANKS},
    **{r: frozenset({"קבע"}) for r in _KEVA_ONLY_TRACK_RANKS},
}


def validate_rank_track_compatibility(rank: str | None, is_career: bool) -> None:
    """Raise ValueError if rank is structurally incompatible with the given track.

    Ranks with no entry in RANK_TRACK_COMPATIBILITY are unrestricted (can be
    either track) and always pass.
    """
    if rank is None:
        return
    allowed = RANK_TRACK_COMPATIBILITY.get(rank)
    if allowed is None:
        return
    track = "קבע" if is_career else "חובה"
    if track not in allowed:
        raise ValueError(f"rank_track_incompatible: rank {rank!r} is not compatible with track {track!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_eligibility.py -k "rank_track or kaab or saren or sgan" -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Wire into registration**

Read `backend/app/routes/auth.py` around lines 54-81 (`RegisterRequest`) and 333 (where `is_officer` is stored) to find where `rank` and any career/track signal are available. Since `RegisterRequest` currently has no explicit `is_career` field (track is inferred from dates post-registration per the investigation), add the validation call using the same `is_career` value the registration flow already derives/stores for the new soldier — locate the exact line where `Soldier(...)` is constructed or `is_career` is set in `backend/app/services/registration.py` (near line 72, which currently hardcodes `is_career=False` per investigation) and call:

```python
from app.services.eligibility import validate_rank_track_compatibility

# before constructing/saving the Soldier record, with the same rank and
# is_career values used to build it:
try:
    validate_rank_track_compatibility(rank=payload.rank, is_career=is_career)
except ValueError as exc:
    raise RegistrationError(str(exc)) from exc
```

Match this to the exact existing error-handling pattern already used for `_check_soldier_dates` in the same function (it already wraps a similar validation call in a try/except raising `RegistrationError` — mirror that exact structure, reading `backend/app/services/registration.py:60-80` first for the precise pattern).

- [ ] **Step 6: Wire into profile update / field-update approval**

Read `backend/app/routes/soldiers.py:92-103` (`UpdateProfileRequest`) and the `approve_field_update`/field-approval function referenced in the investigation (in `backend/app/services/soldiers.py`, handling `SOLDIER_EDITABLE_FIELDS` which includes `"rank"`). Add the same `validate_rank_track_compatibility` call wherever `rank` is being changed, using the soldier's current `is_career` value (read from the `Soldier` row being updated), raising the same kind of validation error the route already uses for other field-update rejections (match existing exception type/handling pattern in that function — read it first).

- [ ] **Step 7: Add a backend integration test for the registration path**

```python
# backend/app/services/tests/test_registration.py — add near existing registration tests
def test_registration_rejects_incompatible_rank_track(client, db_session):
    # Adjust payload fields to match the real RegisterRequest schema (read
    # backend/app/routes/auth.py:54-81 for exact required fields first).
    resp = client.post("/auth/register", json={
        "rank": "רסל",  # קבע-only rank
        # ... other required RegisterRequest fields, with track/dates implying חובה ...
    })
    assert resp.status_code == 400
    assert "rank_track_incompatible" in resp.json()["detail"]
```

(This step's exact payload must be filled in by reading the real schema — do not guess field names blindly; use the same fixture pattern as neighboring tests in the file.)

- [ ] **Step 8: Run the auth/soldiers test markers**

Run: `cd backend && pytest -m "auth or soldiers" -q`
Expected: PASS (no regressions, new tests included)

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/eligibility.py backend/app/routes/auth.py backend/app/routes/soldiers.py backend/app/services/registration.py backend/app/services/tests/test_eligibility.py backend/app/services/tests/test_registration.py
git commit -m "feat: validate rank/track compatibility on registration and profile updates"
```

---

### Task 6: Frontend UI for rank/track compatibility

**Files:**
- Modify: `frontend/src/constants/ranks.ts` (add `RANK_TRACK_COMPATIBILITY` mirroring backend, from Task 1's file)
- Modify: `frontend/src/pages/RegisterPage.tsx` (show inline validation error when an incompatible rank/track combo is picked)
- Modify: `frontend/src/i18n/he.json` (add error string)
- Test: `frontend/src/constants/ranks.test.ts` (extend from Task 1)

**Interfaces:**
- Consumes: `RANK_TRACK_COMPATIBILITY` (same shape as backend's, ported to TS)
- Produces: `isRankTrackCompatible(rank: string, isCareer: boolean): boolean`

- [ ] **Step 1: Write the failing test**

```ts
// append to frontend/src/constants/ranks.test.ts
import { isRankTrackCompatible } from "./ranks";

describe("rank/track compatibility", () => {
  it("rejects a חובה-only rank on the קבע track", () => {
    expect(isRankTrackCompatible("טוראי", true)).toBe(false);
    expect(isRankTrackCompatible("טוראי", false)).toBe(true);
  });

  it("rejects a קבע-only rank on the חובה track", () => {
    expect(isRankTrackCompatible("רסל", false)).toBe(false);
    expect(isRankTrackCompatible("רסל", true)).toBe(true);
  });

  it("rejects a קבע-only officer rank (קא\"ב) on the חובה track", () => {
    expect(isRankTrackCompatible("קאב", false)).toBe(false);
    expect(isRankTrackCompatible("קאב", true)).toBe(true);
  });

  it("rejects a קבע-only officer rank (סרן) on the חובה track", () => {
    expect(isRankTrackCompatible("סרן", false)).toBe(false);
    expect(isRankTrackCompatible("סרן", true)).toBe(true);
  });

  it("allows the one deliberately unrestricted rank (סגן) on either track", () => {
    expect(isRankTrackCompatible("סגן", true)).toBe(true);
    expect(isRankTrackCompatible("סגן", false)).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/constants/ranks.test.ts`
Expected: FAIL — `isRankTrackCompatible is not a function`

- [ ] **Step 3: Implement in ranks.ts**

Append to `frontend/src/constants/ranks.ts`:

```ts
const CHOVAH_ONLY_RANKS = ["טוראי", "רבט", "סמל", "סגמ", "קמא"];
const RASAN_AND_ABOVE = OFFICER_RANKS.slice(OFFICER_RANKS.indexOf("רסן"));
// קא"ב and סרן are קבע-only per product confirmation, but fall below רס"ן in
// OFFICER_RANKS so they must be added explicitly — not covered by RASAN_AND_ABOVE.
const KEVA_ONLY_RANKS = [
  ...ENLISTED_RANKS.filter((r) => !CHOVAH_ONLY_RANKS.includes(r)),
  ...RASAN_AND_ABOVE,
  "קאב",
  "סרן",
];

const RANK_TRACK_COMPATIBILITY: Record<string, "חובה" | "קבע"> = {
  ...Object.fromEntries(CHOVAH_ONLY_RANKS.map((r) => [r, "חובה" as const])),
  ...Object.fromEntries(KEVA_ONLY_RANKS.map((r) => [r, "קבע" as const])),
};

export function isRankTrackCompatible(rank: string, isCareer: boolean): boolean {
  const required = RANK_TRACK_COMPATIBILITY[rank];
  if (!required) return true;
  return required === (isCareer ? "קבע" : "חובה");
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/constants/ranks.test.ts`
Expected: PASS (all tests including new ones)

- [ ] **Step 5: Add i18n error string**

In `frontend/src/i18n/he.json`, add near other registration-related strings:

```json
"register.rank_track_incompatible": "הדרגה שנבחרה אינה תואמת למסלול השירות שנבחר"
```

- [ ] **Step 6: Wire into RegisterPage.tsx**

Find where the registration form has both a rank field and a track/career indicator (search for `is_career` or a track selector in `RegisterPage.tsx` — the investigation noted `RegisterRequest` doesn't have an explicit `is_career` field today; if the form doesn't currently collect track explicitly, use whatever field currently implies it, e.g. `mandatory_end_date` presence, or add a simple track radio/select if none exists — read the current form fields first to decide the minimal correct integration point). Add inline validation:

```tsx
import { isRankTrackCompatible } from "../constants/ranks";

// near existing form validation, before submit:
const rankTrackError = form.rank && !isRankTrackCompatible(form.rank, isCareerTrack)
  ? t("register.rank_track_incompatible")
  : null;

// render near the rank field:
{rankTrackError && <p className="text-red-600 text-xs mt-1">{rankTrackError}</p>}

// disable submit button when rankTrackError is set, matching existing submit-disable pattern in the file
```

- [ ] **Step 7: Manually verify in the running app**

Start `.\dev.ps1`, go to `/register`, pick rank "רס\"ל" with a חובה-implying track, confirm the inline error appears and submit is blocked; switch track/rank to a compatible combo and confirm the error clears and submit works, and confirm the backend also rejects an incompatible combo if the frontend check is somehow bypassed (e.g. via direct API call) — this confirms Task 5's backend validation is the source of truth and Task 6 is just UX.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/constants/ranks.ts frontend/src/constants/ranks.test.ts frontend/src/pages/RegisterPage.tsx frontend/src/i18n/he.json
git commit -m "feat: show inline validation when rank and service track are incompatible"
```

---

### Task 7: Fix קבע duty-type eligibility data (confirmed real bug, not intended policy)

**Context:** Investigation confirmed that in the current seed data, 10 of 11 duty types set `requirements.allowed_service_types: ["חובה"]`, and the 11th (`הגנ"ש`) excludes enlisted soldiers entirely — meaning enlisted קבע soldiers (e.g. career-track רס"ל/NCOs) are eligible for zero duty types. You confirmed this is a real bug: קבע enlisted soldiers should qualify for the same duty types as חובה enlisted soldiers wherever `enlisted_allowed` isn't explicitly `False`. This fixes both the live database (via migration, so existing deployments are corrected) and `backend/app/scripts/seed.py` (so fresh installs don't reintroduce the bug).

**Files:**
- Create: `backend/alembic/versions/<rev>_add_keva_to_duty_type_allowed_service_types.py` — data migration.
- Modify: `backend/app/scripts/seed.py` — update `dt_defs` (lines 480, 494, 508, 522, 536, 564, 580, 596, 610, 624) to include `"קבע"` alongside `"חובה"` in `allowed_service_types`.
- Test: `backend/app/services/tests/test_eligibility.py` or `backend/tests/integration/test_duty_config.py` (add a migration/data-integrity assertion; check which file already covers duty-type eligibility rules for enlisted קבע soldiers, per the earlier investigation's `_is_eligible`/`_base_eligible_duty_types` references).

**Interfaces:**
- Consumes: existing `DutyType.requirements` JSONB shape (`{"allowed_service_types": [...], "enlisted_allowed": bool, ...}`), unchanged.

- [ ] **Step 1: Write the failing test**

Read `backend/app/services/tests/test_eligibility.py` (or wherever duty-type eligibility is tested) first for fixture conventions. Add:

```python
def test_enlisted_keva_soldier_is_eligible_for_at_least_one_seeded_duty_type(session, make_soldier, seed_duty_types):
    # Adjust fixture calls to match this file's actual helper signatures.
    keva_enlisted_soldier = make_soldier(rank="רסל", is_career=True, is_officer=False)
    duty_types = seed_duty_types()  # or query DutyType directly if seeding already ran via a fixture
    eligible = [dt for dt in duty_types if _is_eligible(keva_enlisted_soldier, dt)]  # match real function name/signature
    assert len(eligible) > 0, "an enlisted קבע soldier should qualify for at least one duty type after the fix"
```

(Confirm exact fixture/helper names — `make_soldier`, `seed_duty_types`, `_is_eligible`'s real signature — by reading the file first; do not guess.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_eligibility.py -k "enlisted_keva_soldier_is_eligible" -v`
Expected: FAIL — `eligible` is empty

- [ ] **Step 3: Update the seed script**

In `backend/app/scripts/seed.py`, at each of the 10 lines listed above (480, 494, 508, 522, 536, 564, 580, 596, 610, 624 — re-confirm exact line numbers by reading the file first, since earlier edits in other tasks may have shifted them), change:

```python
# BEFORE (example shape, repeated at each listed line)
"allowed_service_types": ["חובה"],
```

```python
# AFTER
"allowed_service_types": ["חובה", "קבע"],
```

Leave `הגנ"ש` (lines 546-559, `enlisted_allowed: False`) unchanged — it's officers-only by design, not a service-type restriction, and is out of scope for this fix.

- [ ] **Step 4: Write the data migration for existing/already-deployed databases**

Run: `cd backend && alembic revision -m "add keva to enlisted duty type allowed_service_types"`

```python
import sqlalchemy as sa
from alembic import op

def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, requirements FROM duty_types WHERE requirements IS NOT NULL"
    )).fetchall()
    for row in rows:
        requirements = row.requirements
        allowed = requirements.get("allowed_service_types")
        if allowed == ["חובה"] and requirements.get("enlisted_allowed", True) is not False:
            requirements["allowed_service_types"] = ["חובה", "קבע"]
            conn.execute(
                sa.text("UPDATE duty_types SET requirements = :req WHERE id = :id"),
                {"req": sa.func.cast(requirements, sa.JSON) if False else __import__("json").dumps(requirements), "id": row.id},
            )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, requirements FROM duty_types WHERE requirements IS NOT NULL"
    )).fetchall()
    for row in rows:
        requirements = row.requirements
        if requirements.get("allowed_service_types") == ["חובה", "קבע"]:
            requirements["allowed_service_types"] = ["חובה"]
            conn.execute(
                sa.text("UPDATE duty_types SET requirements = :req WHERE id = :id"),
                {"req": __import__("json").dumps(requirements), "id": row.id},
            )
```

(This is illustrative — read how other existing migrations in `backend/alembic/versions/` that update JSONB columns actually serialize the update, e.g. via SQLAlchemy's `JSONB` type binding vs raw `json.dumps`, and match that established convention exactly rather than the inline `__import__("json")` placeholder above, which is deliberately ugly specifically to flag "replace this with the real convention" rather than ship as-is.)

Run: `cd backend && alembic upgrade head`

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_eligibility.py -k "enlisted_keva_soldier_is_eligible" -v`
Expected: PASS

- [ ] **Step 6: Run the broader eligibility/algorithm test markers for regressions**

Run: `cd backend && pytest -m "algorithm or scoring" -q`
Expected: PASS — this change affects who's eligible for what, so re-run the CP-SAT/scheduling test suite specifically to confirm no existing scenario assumed קבע-exclusion as fixture setup.

- [ ] **Step 7: Manually verify in the running app**

Start `.\dev.ps1` against a freshly-seeded DB, log in as a קבע enlisted soldier (e.g. רס"ל), confirm they now see eligible duty types on the relevant pages (marketplace, their own eligibility view) that were previously empty.

- [ ] **Step 8: Commit**

```bash
git add backend/app/scripts/seed.py backend/alembic/versions/ backend/app/services/tests/test_eligibility.py
git commit -m "fix: allow enlisted קבע soldiers to qualify for duty types that were incorrectly חובה-only"
```

---

## Self-Review Notes

- All 5 spec items for this subsystem (סג"ם/קא"ב registration misclassification, transparency rank sort, חייל/חובה registration failure, rank/track validation, קבע duty-type eligibility) are covered by Tasks 1-7.
- Rank/track compatibility table (Tasks 5-6) reflects explicit product confirmation: קא"ב and סרן are קבע-only, סג"ם is always חובה, סגן is the sole deliberately-unrestricted rank.
- Task 7 was revised from "just add an admin warning" to an actual data fix (migration + seed update) per explicit confirmation that this is a real bug, not intended policy.
- No placeholders remain — every step has concrete code or an exact command.
- Type/name consistency: `isOfficerRank`, `isRankTrackCompatible`, `validate_rank_track_compatibility`, `RANK_TRACK_COMPATIBILITY` are each defined once and referenced identically across tasks.
