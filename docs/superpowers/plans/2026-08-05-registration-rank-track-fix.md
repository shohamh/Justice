# Registration Rank/Track Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix registration so a soldier whose mandatory (חובה) service has already ended can register with a קבע-only rank (רס"ן, סרן, קא"ב, and the new קא"ם), and remove the manual "בוגר בה\"ד 1" checkbox in favor of deriving it from rank.

**Architecture:** Registration currently hardcodes `is_career=False` for its two validation calls (`_check_soldier_dates`, `validate_rank_track_compatibility`), so any קבע-only rank is rejected even when the submitted `mandatory_end_date` is already in the past (which should imply קבע). The fix derives `is_career` from the submitted dates using the existing `derive_is_career` helper, adds a registration-only guard that `discharge_date` isn't already in the past, adds the new קא"ם rank (קבע-only, positioned directly below רס"ן), and derives `bahad1_graduate` from rank instead of accepting it as user input.

**Tech Stack:** FastAPI + Pydantic + SQLAlchemy (backend/), React + TypeScript + Vitest (frontend/), pytest (backend tests).

## Global Constraints

- Backend and frontend rank/track-compatibility tables must stay in sync (existing convention — see comments in `backend/app/services/eligibility.py` and `frontend/src/constants/ranks.ts`).
- Do not touch the shared `_check_soldier_dates` (`backend/app/services/soldiers.py`) — it is also used by admin profile edits (`update_soldier_profile`, `approve_field_update`) for entering historical data on already-discharged soldiers, where a past `discharge_date` is legitimate. The new "discharge date must not be in the past" rule is registration-only.
- Hebrew UI strings go in `frontend/src/i18n/he.json` (single locale file, no `en.json` exists).

---

## Task 1: Add קא"ם rank (backend)

**Files:**
- Modify: `backend/app/services/eligibility.py:21-23,42-46`
- Test: `backend/app/services/tests/test_eligibility.py`

**Interfaces:**
- Produces: `"קאם"` added to `OFFICER_RANKS` (positioned directly before `"רסן"`, i.e. below it in rank order) and to `_KEVA_ONLY_TRACK_RANKS`, so `RANK_TRACK_COMPATIBILITY["קאם"] == frozenset({"קבע"})`.

- [ ] **Step 1: Write the failing test**

Add to `backend/app/services/tests/test_eligibility.py`:

```python
def test_kaam_is_officer_rank_below_rasan():
    from app.services.eligibility import OFFICER_RANKS
    assert "קאם" in OFFICER_RANKS
    assert OFFICER_RANKS.index("קאם") < OFFICER_RANKS.index("רסן")


def test_kaam_is_keva_only():
    from app.services.eligibility import validate_rank_track_compatibility
    import pytest
    with pytest.raises(ValueError, match="rank_track_incompatible"):
        validate_rank_track_compatibility(rank="קאם", is_career=False)
    validate_rank_track_compatibility(rank="קאם", is_career=True)  # should not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_eligibility.py -k kaam -v`
Expected: FAIL (`"קאם" in OFFICER_RANKS` is False)

- [ ] **Step 3: Add the rank**

In `backend/app/services/eligibility.py`, change:

```python
OFFICER_RANKS = [
    "קמא", "סגמ", "סגן", "קאב", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
]
```

to:

```python
OFFICER_RANKS = [
    "קמא", "סגמ", "סגן", "קאב", "סרן", "קאם", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
]
```

and change:

```python
_KEVA_ONLY_TRACK_RANKS = frozenset(
    [r for r in ENLISTED_RANKS if r not in CHOVAH_ONLY_RANKS]
    + list(RANKS_RASAN_AND_ABOVE)
    + ["קאב", "סרן"]
)
```

to:

```python
_KEVA_ONLY_TRACK_RANKS = frozenset(
    [r for r in ENLISTED_RANKS if r not in CHOVAH_ONLY_RANKS]
    + list(RANKS_RASAN_AND_ABOVE)
    + ["קאב", "סרן", "קאם"]
)
```

(`RANKS_RASAN_AND_ABOVE = OFFICER_RANKS[OFFICER_RANKS.index("רסן"):]` is computed after this edit and is unaffected — it still starts at `רסן`.)

Update the comment above `_CHOVAH_ONLY_TRACK_RANKS` (currently: `# Ranks that structurally cannot exist on the other track, confirmed with product: קא"ב and סרן are קבע-only officer ranks...`) to also mention קא"ם:

```python
# Ranks that structurally cannot exist on the other track, confirmed with
# product: קא"ב, סרן, and קא"ם are קבע-only officer ranks (added explicitly
# below, since none of them fall under RANKS_RASAN_AND_ABOVE); סג"ם is always
# חובה (already covered by CHOVAH_ONLY_RANKS). סגן is the only rank left
# deliberately unrestricted — it can be either track.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_eligibility.py -k kaam -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/eligibility.py backend/app/services/tests/test_eligibility.py
git commit -m "feat: add קא\"ם rank as קבע-only, below רס\"ן"
```

---

## Task 2: Add קא"ם rank (frontend, mirrored)

**Files:**
- Modify: `frontend/src/constants/ranks.ts`
- Test: `frontend/src/constants/ranks.test.ts`

**Interfaces:**
- Consumes: none new.
- Produces: `OFFICER_RANKS` (frontend) and `isRankTrackCompatible` behave identically to Task 1's backend change.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/constants/ranks.test.ts`:

```ts
describe("קא\"ם rank", () => {
  it("classifies קאם as an officer rank positioned below רסן", () => {
    expect(OFFICER_RANKS).toContain("קאם");
    expect(OFFICER_RANKS.indexOf("קאם")).toBeLessThan(OFFICER_RANKS.indexOf("רסן"));
  });

  it("rejects קאם on the חובה track and accepts it on קבע", () => {
    expect(isRankTrackCompatible("קאם", false)).toBe(false);
    expect(isRankTrackCompatible("קאם", true)).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm test -- ranks.test.ts`
Expected: FAIL

- [ ] **Step 3: Add the rank**

In `frontend/src/constants/ranks.ts`, change:

```ts
export const OFFICER_RANKS = [
  "קמא", "סגמ", "סגן", "קאב", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
];
```

to:

```ts
export const OFFICER_RANKS = [
  "קמא", "סגמ", "סגן", "קאב", "סרן", "קאם", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
];
```

and change:

```ts
const KEVA_ONLY_RANKS = [
  ...ENLISTED_RANKS.filter((r) => !CHOVAH_ONLY_RANKS.includes(r)),
  ...RASAN_AND_ABOVE,
  "קאב",
  "סרן",
];
```

to:

```ts
const KEVA_ONLY_RANKS = [
  ...ENLISTED_RANKS.filter((r) => !CHOVAH_ONLY_RANKS.includes(r)),
  ...RASAN_AND_ABOVE,
  "קאב",
  "סרן",
  "קאם",
];
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm test -- ranks.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/constants/ranks.ts frontend/src/constants/ranks.test.ts
git commit -m "feat: mirror קא\"ם rank addition on frontend"
```

---

## Task 3: `derive_bahad1_graduate` helper (backend + frontend)

**Files:**
- Modify: `backend/app/services/eligibility.py`
- Modify: `frontend/src/constants/ranks.ts`
- Test: `backend/app/services/tests/test_eligibility.py`
- Test: `frontend/src/constants/ranks.test.ts`

**Interfaces:**
- Produces: `derive_bahad1_graduate(rank: str | None) -> bool` (backend, in `eligibility.py`) and `deriveBahad1Graduate(rank: string): boolean` (frontend, in `ranks.ts`, exported). Both return `True`/`true` iff `rank` is an officer rank and not one of `קמ"א`, `קא"ב`, `קא"ם`.

- [ ] **Step 1: Write the failing backend test**

Add to `backend/app/services/tests/test_eligibility.py`:

```python
def test_derive_bahad1_graduate_true_for_regular_officer():
    from app.services.eligibility import derive_bahad1_graduate
    assert derive_bahad1_graduate("סרן") is True
    assert derive_bahad1_graduate("רסן") is True
    assert derive_bahad1_graduate("סגן") is True


def test_derive_bahad1_graduate_false_for_excluded_officer_ranks():
    from app.services.eligibility import derive_bahad1_graduate
    assert derive_bahad1_graduate("קמא") is False
    assert derive_bahad1_graduate("קאב") is False
    assert derive_bahad1_graduate("קאם") is False


def test_derive_bahad1_graduate_false_for_enlisted_and_unknown():
    from app.services.eligibility import derive_bahad1_graduate
    assert derive_bahad1_graduate("טוראי") is False
    assert derive_bahad1_graduate(None) is False
    assert derive_bahad1_graduate("not_a_real_rank") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_eligibility.py -k bahad1_graduate -v`
Expected: FAIL (`ImportError`/`AttributeError`: no `derive_bahad1_graduate`)

- [ ] **Step 3: Implement backend helper**

In `backend/app/services/eligibility.py`, add right after `derive_is_career` (after line 110, before `_is_eligible`):

```python
BAHAD1_EXCLUDED_OFFICER_RANKS = ["קמא", "קאב", "קאם"]


def derive_bahad1_graduate(rank: str | None) -> bool:
    """Every officer rank is a בה"ד 1 graduate except קמ"א, קא"ב, and קא"ם."""
    if rank not in OFFICER_RANKS:
        return False
    return rank not in BAHAD1_EXCLUDED_OFFICER_RANKS
```

- [ ] **Step 4: Run backend test to verify it passes**

Run: `pytest backend/app/services/tests/test_eligibility.py -k bahad1_graduate -v`
Expected: PASS

- [ ] **Step 5: Write the failing frontend test**

Add to `frontend/src/constants/ranks.test.ts` (add `deriveBahad1Graduate` to the existing import line):

```ts
import { ENLISTED_RANKS, OFFICER_RANKS, isOfficerRank, isRankTrackCompatible, deriveBahad1Graduate } from "./ranks";
```

```ts
describe("deriveBahad1Graduate", () => {
  it("is true for regular officer ranks", () => {
    expect(deriveBahad1Graduate("סרן")).toBe(true);
    expect(deriveBahad1Graduate("רסן")).toBe(true);
    expect(deriveBahad1Graduate("סגן")).toBe(true);
  });

  it("is false for קמא, קאב, קאם", () => {
    expect(deriveBahad1Graduate("קמא")).toBe(false);
    expect(deriveBahad1Graduate("קאב")).toBe(false);
    expect(deriveBahad1Graduate("קאם")).toBe(false);
  });

  it("is false for enlisted ranks", () => {
    expect(deriveBahad1Graduate("טוראי")).toBe(false);
  });
});
```

- [ ] **Step 6: Run frontend test to verify it fails**

Run (from `frontend/`): `npm test -- ranks.test.ts`
Expected: FAIL

- [ ] **Step 7: Implement frontend helper**

In `frontend/src/constants/ranks.ts`, add at the end of the file:

```ts
const BAHAD1_EXCLUDED_OFFICER_RANKS = ["קמא", "קאב", "קאם"];

// Mirrors backend/app/services/eligibility.py derive_bahad1_graduate.
export function deriveBahad1Graduate(rank: string): boolean {
  if (!OFFICER_RANK_SET.has(rank)) return false;
  return !BAHAD1_EXCLUDED_OFFICER_RANKS.includes(rank);
}
```

- [ ] **Step 8: Run frontend test to verify it passes**

Run (from `frontend/`): `npm test -- ranks.test.ts`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/eligibility.py backend/app/services/tests/test_eligibility.py frontend/src/constants/ranks.ts frontend/src/constants/ranks.test.ts
git commit -m "feat: derive בוגר בה\"ד 1 from rank instead of manual input"
```

---

## Task 4: `deriveIsCareer` helper (frontend mirror of backend `derive_is_career`)

**Files:**
- Modify: `frontend/src/constants/ranks.ts`
- Test: `frontend/src/constants/ranks.test.ts`

**Interfaces:**
- Consumes: `CHOVAH_ONLY_RANKS` (already defined privately in `ranks.ts`).
- Produces: `deriveIsCareer(rank: string, mandatoryEndDate: string, dischargeDate: string, todayIso?: string): boolean`, exported. Dates are ISO `YYYY-MM-DD` strings (same format `DateInput`/the rest of the codebase already uses), compared lexicographically (safe for ISO dates, avoids `Date`/timezone parsing pitfalls). `todayIso` defaults to today's date; tests always pass it explicitly.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/constants/ranks.test.ts`:

```ts
import { deriveIsCareer } from "./ranks"; // add to the existing import line instead if easier
```

```ts
describe("deriveIsCareer", () => {
  it("is false before mandatory end date", () => {
    expect(deriveIsCareer("טוראי", "2027-01-01", "", "2026-07-19")).toBe(false);
  });

  it("is true after mandatory end date with no discharge date, for a non-חובה-only rank", () => {
    expect(deriveIsCareer("רסן", "2025-01-01", "", "2026-07-19")).toBe(true);
  });

  it("is false if discharged before mandatory end date", () => {
    expect(deriveIsCareer("רסן", "2027-01-01", "2026-06-01", "2026-07-19")).toBe(false);
  });

  it("is never true for a חובה-only rank regardless of dates", () => {
    expect(deriveIsCareer("טוראי", "2020-01-01", "", "2026-07-19")).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm test -- ranks.test.ts`
Expected: FAIL

- [ ] **Step 3: Implement**

Add to `frontend/src/constants/ranks.ts` (needs read access to `CHOVAH_ONLY_RANKS`, which is already module-private in this file — no export needed):

```ts
// Mirrors backend/app/services/eligibility.py derive_is_career. Dates are ISO
// "YYYY-MM-DD" strings, compared lexicographically (safe for this format,
// avoids `Date` timezone-parsing pitfalls for a same-day comparison).
export function deriveIsCareer(
  rank: string,
  mandatoryEndDate: string,
  dischargeDate: string,
  todayIso: string = new Date().toISOString().slice(0, 10),
): boolean {
  if (CHOVAH_ONLY_RANKS.includes(rank)) return false;
  if (!mandatoryEndDate) return false;
  if (todayIso <= mandatoryEndDate) return false;
  return !dischargeDate || dischargeDate > mandatoryEndDate;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm test -- ranks.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/constants/ranks.ts frontend/src/constants/ranks.test.ts
git commit -m "feat: add deriveIsCareer frontend helper mirroring backend"
```

---

## Task 5: Fix registration service to derive `is_career`, reject past discharge dates, and derive `bahad1_graduate`

**Files:**
- Modify: `backend/app/services/registration.py`
- Modify: `backend/app/routes/auth.py:54-75,316-346`
- Test: `backend/app/services/tests/test_registration.py`
- Test: `backend/tests/integration/test_registration_routes.py`

**Interfaces:**
- Consumes: `derive_is_career(rank, mandatory_end_date, discharge_date, today=None)` and `derive_bahad1_graduate(rank)` from `app.services.eligibility` (Task 3, already exists as `derive_is_career`).
- Produces: `register(...)` no longer takes a `bahad1_graduate` parameter; it computes both `is_career` and `bahad1_graduate` internally and persists both on the new `Soldier` row. Raises `RegistrationError("discharge_date_in_past")` if `discharge_date < date.today()`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_registration.py`:

```python
def test_register_allows_keva_only_rank_once_mandatory_service_has_ended(admin_session):
    """Regression: registration used to hardcode is_career=False, so a soldier
    whose mandatory service already ended (mandatory_end_date in the past,
    rank is קבע-only) was incorrectly rejected as a track mismatch."""
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    soldier = register(
        admin_session, invite_code=invite.code, requested_node_id=node.id,
        exemption_requests=[], personal_constraints=[],
        **_base(
            rank="רסן",
            mandatory_end_date=date.today() - timedelta(days=30),
            discharge_date=date.today() + timedelta(days=365 * 3),
        ),
    )
    admin_session.commit()

    assert soldier.is_career is True
    assert soldier.rank == "רסן"


def test_register_rejects_discharge_date_in_past(admin_session):
    from app.services.registration import register, RegistrationError
    from app.services.invite_codes import create_invite_code

    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    with pytest.raises(RegistrationError, match="discharge_date_in_past"):
        register(
            admin_session, invite_code=invite.code, requested_node_id=node.id,
            exemption_requests=[], personal_constraints=[],
            **_base(discharge_date=date.today() - timedelta(days=1)),
        )


def test_register_derives_bahad1_graduate_from_rank(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=2, actor_id=None)
    admin_session.commit()

    officer = register(
        admin_session, invite_code=invite.code, requested_node_id=node.id,
        exemption_requests=[], personal_constraints=[],
        **_base(rank="סרן", is_officer=True, mandatory_end_date=date.today() + timedelta(days=200)),
    )
    admin_session.commit()
    assert officer.bahad1_graduate is True

    invite2 = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()
    kaab_officer = register(
        admin_session, invite_code=invite2.code, requested_node_id=node.id,
        exemption_requests=[], personal_constraints=[],
        **_base(rank="קאב", is_officer=True, mandatory_end_date=date.today() + timedelta(days=200)),
    )
    admin_session.commit()
    assert kaab_officer.bahad1_graduate is False
```

Also update the existing `_base()` helper (drop `"bahad1_graduate": False,` — the parameter no longer exists on `register()`) and the docstring/comment on `test_register_rejects_incompatible_rank_track` (it currently says "Registration always starts a soldier as חובה" — no longer universally true once `is_career` is derived; the test still passes because its `_base()` dates keep `mandatory_end_date` in the future, so update the comment to say that instead):

```python
def _base(**overrides):
    return {
        "personal_number": f"pn_{_uid()}",
        "full_name": "Test Soldier",
        "password": "password-secure-1",
        "phone": "050-0000000",
        "email": None,
        "gender": "male",
        "is_officer": False,
        "rank": "טוראי",
        # Relative to today so a חובה-only rank never accidentally looks like it
        # outlived its own mandatory-service window as the real calendar advances.
        "enlistment_date": date.today() - timedelta(days=600),
        "mandatory_end_date": date.today() + timedelta(days=200),
        "discharge_date": date.today() + timedelta(days=600),
        "last_mitvahim_date": None,
        "last_alal_date": None,
        **overrides,
    }
```

```python
def test_register_rejects_incompatible_rank_track(admin_session):
    # is_career is derived from mandatory_end_date/discharge_date (see
    # test_register_allows_keva_only_rank_once_mandatory_service_has_ended);
    # _base()'s mandatory_end_date is in the future, so is_career is still
    # False here, making a קבע-only rank like רסל incompatible.
    from app.services.registration import register, RegistrationError
    from app.services.invite_codes import create_invite_code

    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    with pytest.raises(RegistrationError, match="rank_track_incompatible"):
        register(
            admin_session, invite_code=invite.code, requested_node_id=node.id,
            exemption_requests=[], personal_constraints=[],
            **_base(rank="רסל"),
        )
```

In `backend/tests/integration/test_registration_routes.py`, remove `"bahad1_graduate": False,` from `_payload()` (the field no longer exists on `RegisterRequest`; Pydantic ignores unknown fields by default, but leaving it would be misleading dead weight — remove it for cleanliness).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_registration.py -v`
Expected: FAIL on the 3 new tests (`test_register_allows_keva_only_rank_once_mandatory_service_has_ended` fails with `rank_track_incompatible`; `test_register_rejects_discharge_date_in_past` fails because no such check exists yet; `test_register_derives_bahad1_graduate_from_rank` fails with a `TypeError` since `register()` still requires `bahad1_graduate`)

- [ ] **Step 3: Implement the registration service fix**

In `backend/app/services/registration.py`:

Change the import line:

```python
from app.services.eligibility import validate_rank_track_compatibility
```

to:

```python
from app.services.eligibility import derive_bahad1_graduate, derive_is_career, validate_rank_track_compatibility
```

Remove `bahad1_graduate: bool,` from the `register(...)` signature (it was at line 40, between `rank: str | None,` and `enlistment_date: date | None,`).

Replace:

```python
    try:
        _check_soldier_dates(
            rank=rank, enlistment_date=enlistment_date, discharge_date=discharge_date,
            mandatory_end_date=mandatory_end_date, is_career=False,
        )
    except SoldierError as exc:
        raise RegistrationError(str(exc)) from exc

    try:
        validate_rank_track_compatibility(rank=rank, is_career=False)
    except ValueError as exc:
        raise RegistrationError(str(exc)) from exc
```

with:

```python
    if discharge_date is not None and discharge_date < date.today():
        raise RegistrationError("discharge_date_in_past")

    is_career = derive_is_career(rank, mandatory_end_date, discharge_date)

    try:
        _check_soldier_dates(
            rank=rank, enlistment_date=enlistment_date, discharge_date=discharge_date,
            mandatory_end_date=mandatory_end_date, is_career=is_career,
        )
    except SoldierError as exc:
        raise RegistrationError(str(exc)) from exc

    try:
        validate_rank_track_compatibility(rank=rank, is_career=is_career)
    except ValueError as exc:
        raise RegistrationError(str(exc)) from exc

    bahad1_graduate = derive_bahad1_graduate(rank)
```

(The `discharge_date_in_past` check runs before `is_career` is derived and before `_check_soldier_dates`/`validate_rank_track_compatibility`, since it's an unconditional registration-only rule, independent of track.)

Update the `Soldier(...)` construction to persist the derived values — change:

```python
        gender=gender,
        is_officer=is_officer,
        rank=rank,
        bahad1_graduate=bahad1_graduate,
        enlistment_date=enlistment_date,
```

to:

```python
        gender=gender,
        is_officer=is_officer,
        rank=rank,
        is_career=is_career,
        bahad1_graduate=bahad1_graduate,
        enlistment_date=enlistment_date,
```

- [ ] **Step 4: Update the route (drop `bahad1_graduate` from the request schema and call)**

In `backend/app/routes/auth.py`, remove the line `bahad1_graduate: bool = False` from `RegisterRequest` (was line 64), and remove `bahad1_graduate=body.bahad1_graduate,` from the `reg_svc.register(...)` call (was line 335).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_registration.py backend/tests/integration/test_registration_routes.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 6: Add the Hebrew error message for `discharge_date_in_past`**

In `frontend/src/i18n/he.json`, in the top-level `"errors"` block (around line 456-460, alongside `discharge_date_before_enlistment`/`career_discharge_in_past`), add:

```json
    "discharge_date_in_past": "תאריך השחרור חייב להיות בעתיד",
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/registration.py backend/app/routes/auth.py backend/app/services/tests/test_registration.py backend/tests/integration/test_registration_routes.py frontend/src/i18n/he.json
git commit -m "fix: derive is_career and bahad1_graduate at registration instead of hardcoding"
```

---

## Task 6: Frontend `RegisterPage.tsx` — live track-specific error, discharge-date-in-future error, remove בה"ד 1 checkbox

**Files:**
- Modify: `frontend/src/pages/RegisterPage.tsx`
- Modify: `frontend/src/i18n/he.json`

**Interfaces:**
- Consumes: `deriveIsCareer`, `deriveBahad1Graduate` from `../constants/ranks` (Tasks 3-4).

No dedicated test file exists for `RegisterPage.tsx` today (checked — none found); this task does not add one, consistent with existing coverage in this file.

- [ ] **Step 1: Update imports**

In `frontend/src/pages/RegisterPage.tsx`, change:

```tsx
import { ENLISTED_RANKS, OFFICER_RANKS as OFFICER_RANKS_LIST, isOfficerRank, isRankTrackCompatible } from "../constants/ranks";
```

to:

```tsx
import { ENLISTED_RANKS, OFFICER_RANKS as OFFICER_RANKS_LIST, isOfficerRank, isRankTrackCompatible, deriveIsCareer, deriveBahad1Graduate } from "../constants/ranks";
```

- [ ] **Step 2: Remove `bahad1_graduate` from form state**

In the `FormData` interface, remove `bahad1_graduate: boolean;` (it was part of the `gender: string; is_officer: boolean; rank: string; bahad1_graduate: boolean;` line — becomes `gender: string; is_officer: boolean; rank: string;`).

In `INITIAL`, remove `bahad1_graduate: false,` from the object literal.

- [ ] **Step 3: Compute `is_career` live and use it for the rank/track error and payload**

Replace:

```tsx
  const selectedNode = nodes.find(n => n.id === form.requested_node_id);
  // Registration always starts a soldier as חובה (is_career=False — see
  // backend/app/services/registration.py), so the compatibility check always
  // runs against the חובה track here.
  const rankTrackError = form.rank && !isRankTrackCompatible(form.rank, false)
    ? t("register.rank_track_incompatible")
    : null;
```

with:

```tsx
  const selectedNode = nodes.find(n => n.id === form.requested_node_id);
  // is_career mirrors backend/app/services/registration.py's derive_is_career
  // call: a soldier whose mandatory service already ended (mandatory_end_date
  // in the past) is קבע even at registration time, not always חובה.
  const isCareer = form.mandatory_end_date
    ? deriveIsCareer(form.rank, form.mandatory_end_date, form.discharge_date)
    : false;
  const rankTrackError = form.rank && !isRankTrackCompatible(form.rank, isCareer)
    ? t(isCareer ? "register.rank_track_incompatible_keva" : "register.rank_track_incompatible_chovah")
    : null;
  const dischargeDateError = form.discharge_date && form.discharge_date <= new Date().toISOString().slice(0, 10)
    ? t("register.discharge_date_must_be_future")
    : null;
```

- [ ] **Step 4: Remove the בה"ד 1 checkbox and derive it on rank change**

Replace the `Combobox onChange` handler for rank (currently resets `bahad1_graduate: false` and has a comment explaining the manual checkbox):

```tsx
                onChange={v => {
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
                    last_alal_date: isOfficer ? prev.last_alal_date : "",
                  }));
                }}
```

with:

```tsx
                onChange={v => {
                  const isOfficer = isOfficerRank(v);
                  setForm(prev => ({
                    ...prev,
                    rank: v,
                    is_officer: isOfficer,
                    last_alal_date: isOfficer ? prev.last_alal_date : "",
                  }));
                }}
```

Remove the checkbox block entirely:

```tsx
            {form.is_officer && (
              <label className="flex items-center gap-1 text-sm">
                <input type="checkbox" checked={form.bahad1_graduate}
                  onChange={e => set("bahad1_graduate", e.target.checked)} />
                בוגר בה&quot;ד 1
              </label>
            )}
```

- [ ] **Step 5: Pull `discharge_date` out of the generic date-fields loop into its own labeled field with an error slot**

Replace:

```tsx
            {([["enlistment_date","תאריך גיוס"],["mandatory_end_date","סיום חובה"],["discharge_date","שחרור"],["last_mitvahim_date","מטווח אחרון"]] as [keyof FormData, string][]).map(([key, label]) => (
              <label key={key as string} className="block text-sm">{label} <span className="text-red-500">*</span>
                <DateInput className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  value={form[key] as string} onChange={iso => set(key, iso)} />
              </label>
            ))}
```

with:

```tsx
            {([["enlistment_date","תאריך גיוס"],["mandatory_end_date","סיום חובה"],["last_mitvahim_date","מטווח אחרון"]] as [keyof FormData, string][]).map(([key, label]) => (
              <label key={key as string} className="block text-sm">{label} <span className="text-red-500">*</span>
                <DateInput className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  value={form[key] as string} onChange={iso => set(key, iso)} />
              </label>
            ))}
            <label className="block text-sm">שחרור <span className="text-red-500">*</span>
              <DateInput className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                value={form.discharge_date} onChange={iso => set("discharge_date", iso)} />
              {dischargeDateError && <p className="text-red-600 text-xs mt-1">{dischargeDateError}</p>}
            </label>
```

(This changes rendering order — `discharge_date`'s field now renders after `last_mitvahim_date` instead of between `mandatory_end_date` and `last_mitvahim_date`. This is a minor, acceptable UI change; if exact field order must be preserved, insert the new `discharge_date` label between the `mandatory_end_date` and `last_mitvahim_date` entries in the array-driven loop instead by splitting the loop into two separate `.map()` calls around the new label — either is fine, pick the array-split approach if field order matters more than proximity to the code above.)

- [ ] **Step 6: Block submit on the new error and stop sending `bahad1_graduate`**

In the step-2 "next" button, change:

```tsx
                disabled={
                  !form.personal_number || !form.full_name || !isValidIsraeliPhone(form.phone) || !form.email ||
                  !form.gender || !form.rank || !!rankTrackError || !form.enlistment_date || !form.mandatory_end_date ||
                  !form.discharge_date || !form.last_mitvahim_date ||
                  !passwordValid(form.password) || form.password !== form.confirm_password
                }
```

to:

```tsx
                disabled={
                  !form.personal_number || !form.full_name || !isValidIsraeliPhone(form.phone) || !form.email ||
                  !form.gender || !form.rank || !!rankTrackError || !form.enlistment_date || !form.mandatory_end_date ||
                  !form.discharge_date || !!dischargeDateError || !form.last_mitvahim_date ||
                  !passwordValid(form.password) || form.password !== form.confirm_password
                }
```

In `handleSubmit`, remove `bahad1_graduate: form.bahad1_graduate,` from the `register({...})` call body.

Update the error-mapping block (`mappedDetail`) to handle the new backend error and both track messages:

```tsx
      const mappedDetail = detail && detail.startsWith("rank_track_incompatible")
        ? t(isCareer ? "register.rank_track_incompatible_keva" : "register.rank_track_incompatible_chovah")
        : detail === "discharge_date_in_past"
        ? t("register.discharge_date_must_be_future")
        : detail ? knownErrors[detail] : undefined;
```

- [ ] **Step 7: Update `frontend/src/api/auth.ts`'s `register()` request type**

In `frontend/src/api/auth.ts`, remove `bahad1_graduate: boolean;` (line 61) from `RegisterPayload` (the request body type used by `register(...)`, mirroring `RegisterRequest` in `backend/app/routes/auth.py`). Do **not** touch `bahad1_graduate?: boolean;` on the `Me` interface (line 26) — that's the read-only profile field exposed by `/me`, unrelated to the registration request body, and still populated (now server-derived) after login.

- [ ] **Step 8: Update i18n**

In `frontend/src/i18n/he.json`, in the `"register"` block (around line 1197-1208), replace:

```json
    "rank_track_incompatible": "הדרגה שנבחרה אינה תואמת למסלול השירות שנבחר"
```

with:

```json
    "rank_track_incompatible_chovah": "לא ניתן להיות בדרגה זו במסלול חובה",
    "rank_track_incompatible_keva": "לא ניתן להיות בדרגה זו במסלול קבע",
    "discharge_date_must_be_future": "תאריך השחרור חייב להיות בעתיד"
```

(This removes the old single `rank_track_incompatible` key from the `register` namespace — grep the codebase for `register.rank_track_incompatible` after this edit to confirm no other call site references the removed key. The top-level `errors.rank_track_incompatible` key at line 458, used elsewhere for the generic admin-side error, is untouched.)

- [ ] **Step 9: Manual verification**

Run the dev stack (`.\dev.ps1`) and in the browser at `http://localhost:5173/register`:
1. Pick rank "רסן", leave dates at their defaults (mandatory end date in the future) — confirm the error "לא ניתן להיות בדרגה זו במסלול חובה" appears and blocks the "הבא" button.
2. Set "סיום חובה" to a past date and "שחרור" to a future date after it — confirm the רסן error disappears (soldier is now inferred קבע).
3. Set "שחרור" to a past date — confirm "תאריך השחרור חייב להיות בעתיד" appears and blocks submit.
4. Pick an officer rank other than קא"ב/קא"ם/קמ"א — confirm there is no בה"ד 1 checkbox anywhere on the page.
5. Complete registration successfully with a קבע-derived רסן soldier and confirm no 400 error from the backend.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/pages/RegisterPage.tsx frontend/src/api/auth.ts frontend/src/i18n/he.json
git commit -m "feat: live track-specific rank error, discharge-date-in-future check, remove בה\"ד 1 checkbox"
```

---

## Task 7: Full-suite verification

- [ ] **Step 1: Run backend tests**

Run: `pytest -m auth -q` (registration is marked `auth: login, JWT, password policy, RBAC, registration/enrollment, security hardening` per `backend/pyproject.toml`; alternatively run `pytest backend/app/services/tests/test_registration.py backend/app/services/tests/test_eligibility.py backend/tests/integration/test_registration_routes.py -v` directly since those are the exact files this plan touched)
Expected: all PASS

- [ ] **Step 2: Run frontend tests and lint**

Run (from `frontend/`): `npm test -- ranks.test.ts && npm run lint && npm run typecheck`
Expected: all PASS, zero lint warnings

- [ ] **Step 3: Commit if any fixups were needed**

If Step 1 or 2 required fixes, commit them separately with a clear message (e.g. `fix: address lint warnings from registration rank/track fix`).
