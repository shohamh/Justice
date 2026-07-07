# Profile / Registration / Approvals Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix a batch of user-reported bugs: false-positive login lockouts on shared IPs, missing profile date fields, under-validated registration, a crash-prone exemption sub-form, silent approval failures, an unsearchable unit filter, and a mislabeled/raw-JSON military-license field.

**Architecture:** Each task is an independent bug fix touching a narrow vertical slice (one backend route/service + its Pydantic schema, or one frontend page/component). No new subsystems are introduced — everything reuses existing patterns already in the codebase (the `SOLDIER_EDITABLE_FIELDS` whitelist, the `Combobox` component, the `field_name`-keyed field-update flow, axios interceptors).

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend), React + TypeScript + react-i18next + axios + Vitest/RTL (frontend), pytest (backend tests).

## Global Constraints

- Hebrew UI copy only (no English user-facing strings) — all new/changed labels go in `frontend/src/i18n/he.json` under existing key namespaces.
- Backend business logic lives in `app/services/*`; routes stay thin (parse → call service → map exceptions to `HTTPException`). Follow this for every backend task below.
- Do not touch unrelated code in files you open — these files are large and shared by other features.
- Run `pytest -q` (backend) and `npm test` / `npm run typecheck` (frontend) only for the files you touched per task; the full suite is run once at the end of the plan, not after every task.

---

### Task 1: Raise the shared-IP login rate limit and surface retry time to the user

**Context:** `backend/app/rate_limit.py` keys the slowapi limiter by `get_remote_address` (per-IP), and `backend/app/settings.py:23` caps login at `5/5minutes`. Soldiers on the same base/NAT share one public IP, so unrelated users collectively exhaust the 5-request bucket and see a generic "too many attempts" error with no indication of when they can retry. There is a *separate*, correctly per-account lockout already in `backend/app/routes/auth.py:27-28` (`_LOCKOUT_THRESHOLD = 10`, 15 min) — that one does not need to change. Only the per-IP limiter is the false-positive source, and the frontend never reads the `Retry-After` header that both the per-IP limiter (via slowapi's `_inject_headers`) and the account-lock 429 (`auth.py:130-134`) already send.

**Files:**
- Modify: `backend/app/settings.py:23`
- Modify: `frontend/src/pages/LoginPage.tsx`
- Modify: `frontend/src/i18n/he.json` (login.errors.rate_limited)
- Test: `backend/tests/test_security_hardening.py`
- Test: `frontend/src/pages/LoginPage.test.tsx` (new file)

**Interfaces:**
- Produces: `Settings.login_rate_limit` default becomes `"10/5minutes"`.
- Produces: `LoginPage` reads `err.response?.headers["retry-after"]` (seconds, lowercase per axios header normalization) on a 429 and passes it into the translated error message via `t("login.errors.rate_limited", { seconds })`.

- [ ] **Step 1: Write the failing backend test for the new default**

```python
def test_login_rate_limit_default_is_10_per_5_minutes():
    from app.settings import Settings
    s = Settings(
        DATABASE_URL="postgresql+psycopg://x:y@localhost/z",
        DB_ADMIN_URL="postgresql+psycopg://x:y@localhost/z",
        JWT_SECRET="a" * 32,
        _env_file=None,
    )
    assert s.login_rate_limit == "10/5minutes"
```

Add this to `backend/tests/test_security_hardening.py`.

- [ ] **Step 2: Run it to confirm it fails**

Run: `pytest backend/tests/test_security_hardening.py::test_login_rate_limit_default_is_10_per_5_minutes -v`
Expected: FAIL — `assert '5/5minutes' == '10/5minutes'`

- [ ] **Step 3: Change the default**

In `backend/app/settings.py:23`, change:

```python
    login_rate_limit: str = Field(default="5/5minutes", alias="LOGIN_RATE_LIMIT")
```

to:

```python
    login_rate_limit: str = Field(default="10/5minutes", alias="LOGIN_RATE_LIMIT")
```

- [ ] **Step 4: Run the test again to confirm it passes**

Run: `pytest backend/tests/test_security_hardening.py::test_login_rate_limit_default_is_10_per_5_minutes -v`
Expected: PASS

- [ ] **Step 5: Add the Hebrew copy for a retry-after-aware message**

In `frontend/src/i18n/he.json`, change line 17 from:

```json
      "rate_limited": "יותר מדי ניסיונות. נסה שוב בעוד מספר דקות."
```

to:

```json
      "rate_limited": "יותר מדי ניסיונות. נסה שוב בעוד {{seconds}} שניות."
```

- [ ] **Step 6: Write the failing frontend test**

Create `frontend/src/pages/LoginPage.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AxiosError } from "axios";
import LoginPage from "./LoginPage";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) => opts ? `${key}:${JSON.stringify(opts)}` : key }),
}));

const mockLogin = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ login: mockLogin }),
}));

vi.mock("../components/JusticeLogo", () => ({ default: () => null }));

function makeRateLimitError(retryAfterSeconds: string) {
  const err = new AxiosError("rate limited");
  err.response = {
    status: 429,
    headers: { "retry-after": retryAfterSeconds },
    data: {},
    statusText: "Too Many Requests",
    // @ts-expect-error partial mock
    config: {},
  };
  return err;
}

test("shows retry-after seconds when login is rate limited", async () => {
  mockLogin.mockRejectedValueOnce(makeRateLimitError("42"));
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText ? screen.getByLabelText("") : document.querySelector("input")!, { target: { value: "123" } });
  const form = screen.getByTestId("login-form");
  fireEvent.submit(form);
  await waitFor(() => {
    expect(screen.getByText(/login.errors.rate_limited/)).toHaveTextContent('"seconds":"42"');
  });
});
```

- [ ] **Step 7: Run it to confirm it fails**

Run: `npm test -- LoginPage.test.tsx` (from `frontend/`)
Expected: FAIL — no retry-after handling exists yet, `errorKey` is a plain string key with no `seconds` interpolation.

- [ ] **Step 8: Implement retry-after handling in LoginPage**

In `frontend/src/pages/LoginPage.tsx`, change the error state to carry the interpolation data and the render to pass it through. Replace lines 9 and 22-42 and the render at line 97:

```tsx
type ErrKey = "invalid_credentials" | "network" | "rate_limited" | null;
```
stays the same. Add a second piece of state next to `errorKey`:

```tsx
  const [errorKey, setErrorKey] = useState<ErrKey>(null);
  const [retryAfterSeconds, setRetryAfterSeconds] = useState<string | null>(null);
```

Update the catch block:

```tsx
    } catch (err) {
      if (err instanceof AxiosError) {
        if (err.response?.status === 401) setErrorKey("invalid_credentials");
        else if (err.response?.status === 429) {
          setErrorKey("rate_limited");
          setRetryAfterSeconds(err.response.headers["retry-after"] ?? null);
        } else setErrorKey("network");
      } else {
        setErrorKey("network");
      }
    } finally {
      setSubmitting(false);
    }
```

Update the render (line 97) from:

```tsx
            {t(`login.errors.${errorKey}`)}
```

to:

```tsx
            {errorKey === "rate_limited" && retryAfterSeconds
              ? t("login.errors.rate_limited", { seconds: retryAfterSeconds })
              : t(`login.errors.${errorKey}`)}
```

- [ ] **Step 9: Run the frontend test again to confirm it passes**

Run: `npm test -- LoginPage.test.tsx` (from `frontend/`)
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/settings.py backend/tests/test_security_hardening.py frontend/src/pages/LoginPage.tsx frontend/src/pages/LoginPage.test.tsx frontend/src/i18n/he.json
git commit -m "fix: raise shared-IP login rate limit and show retry-after time"
```

---

### Task 2: Make `mandatory_end_date` and `discharge_date` editable on the profile page

**Context:** `Soldier.mandatory_end_date` and `Soldier.discharge_date` (`backend/app/db/models.py:65-66`) exist and are displayed read-only in `ProfilePage.tsx:248-249`, but there's no way to submit an update for them: `SOLDIER_EDITABLE_FIELDS` in `backend/app/services/eligibility.py:29` doesn't include them, and `approve_field_update` in `backend/app/services/soldiers.py:267-283` has no branch to write them back onto the `Soldier` row. i18n keys `soldier_profile.mandatory_end_date` / `discharge_date` already exist (`he.json:507-508`).

**Files:**
- Modify: `backend/app/services/eligibility.py:29`
- Modify: `backend/app/services/soldiers.py:267-283`
- Modify: `frontend/src/pages/ProfilePage.tsx`
- Test: `backend/tests/unit/test_soldiers_field_updates.py` (new file — check first whether an existing file covers `approve_field_update`; if one exists, add to it instead)

**Interfaces:**
- Consumes: existing `submit_field_update(session, *, soldier_id, field_name, new_value, actor_id)` and `approve_field_update(session, *, update, actor_id, decision_note=None)` signatures — unchanged.
- Produces: `SOLDIER_EDITABLE_FIELDS` now includes `"mandatory_end_date"` and `"discharge_date"`.

- [ ] **Step 1: Check for an existing field-update test file**

Run: `find backend/tests -iname "*field_update*"`

If a file is found, add the steps below into it instead of creating a new file; otherwise create `backend/tests/unit/test_soldiers_field_updates.py` with:

```python
from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.services.eligibility import SOLDIER_EDITABLE_FIELDS
from app.services.soldiers import approve_field_update, submit_field_update
from app.db.models import Soldier, SoldierFieldUpdate


def test_mandatory_end_date_and_discharge_date_are_editable():
    assert "mandatory_end_date" in SOLDIER_EDITABLE_FIELDS
    assert "discharge_date" in SOLDIER_EDITABLE_FIELDS


def test_approve_field_update_writes_mandatory_end_date(session, admin_session):
    from tests.helpers import create_node
    node = create_node(admin_session, level="unit", name=f"unit_{uuid.uuid4().hex[:8]}")
    soldier = Soldier(
        personal_number=f"pn_{uuid.uuid4().hex[:8]}",
        full_name="Test Soldier",
        password_hash="x",
        hierarchy_node_id=node.id,
    )
    admin_session.add(soldier)
    admin_session.flush()

    req = submit_field_update(
        admin_session,
        soldier_id=soldier.id,
        field_name="mandatory_end_date",
        new_value="2027-06-01",
        actor_id=soldier.id,
    )
    admin_session.flush()

    approve_field_update(admin_session, update=req, actor_id=soldier.id)

    assert soldier.mandatory_end_date == date(2027, 6, 1)
```

Adjust fixture names (`session`/`admin_session`) to whatever this repo's `conftest.py` actually exposes — check `backend/tests/conftest.py` before writing this step for real, since other integration tests use `admin_session` and `client` as pytest fixtures.

- [ ] **Step 2: Run it to confirm it fails**

Run: `pytest backend/tests/unit/test_soldiers_field_updates.py -v`
Expected: FAIL — `mandatory_end_date` not in `SOLDIER_EDITABLE_FIELDS`, and no branch writes it in `approve_field_update`.

- [ ] **Step 3: Add the two fields to the editable whitelist**

In `backend/app/services/eligibility.py:29`, change:

```python
SOLDIER_EDITABLE_FIELDS = {"last_mitvahim_date", "last_alal_date", "gender", "rank", "phone", "military_driving_license"}
```

to:

```python
SOLDIER_EDITABLE_FIELDS = {
    "last_mitvahim_date", "last_alal_date", "gender", "rank", "phone",
    "military_driving_license", "mandatory_end_date", "discharge_date",
}
```

- [ ] **Step 4: Add the write-back branches in `approve_field_update`**

In `backend/app/services/soldiers.py`, in `approve_field_update` (around line 269-283), add two `elif` branches next to the existing date-field branches:

```python
    if field == "last_mitvahim_date":
        soldier.last_mitvahim_date = date.fromisoformat(raw)
    elif field == "last_alal_date":
        soldier.last_alal_date = date.fromisoformat(raw)
    elif field == "mandatory_end_date":
        soldier.mandatory_end_date = date.fromisoformat(raw)
    elif field == "discharge_date":
        soldier.discharge_date = date.fromisoformat(raw)
    elif field == "gender":
```

- [ ] **Step 5: Run the backend test again to confirm it passes**

Run: `pytest backend/tests/unit/test_soldiers_field_updates.py -v`
Expected: PASS

- [ ] **Step 6: Add the two input rows to ProfilePage**

In `frontend/src/pages/ProfilePage.tsx`, add state near the other request states (after line 47):

```tsx
  const [mandatoryEndReq, setMandatoryEndReq] = useState("");
  const [dischargeReq, setDischargeReq] = useState("");
```

Reset them in `requestUpdate` (after line 120):

```tsx
      if (field === "mandatory_end_date") setMandatoryEndReq("");
      if (field === "discharge_date") setDischargeReq("");
```

Add two input rows after the `last_alal_date` row (after line 311, before the `military_driving_license` row):

```tsx
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.mandatory_end_date")}</label>
            <input type="date" lang="he" value={mandatoryEndReq} onChange={e => setMandatoryEndReq(e.target.value)} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("mandatory_end_date", mandatoryEndReq)} disabled={!mandatoryEndReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.discharge_date")}</label>
            <input type="date" lang="he" value={dischargeReq} onChange={e => setDischargeReq(e.target.value)} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("discharge_date", dischargeReq)} disabled={!dischargeReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
```

- [ ] **Step 7: Typecheck and lint the touched frontend file**

Run: `npm run typecheck` and `npm run lint` (from `frontend/`)
Expected: no new errors.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/eligibility.py backend/app/services/soldiers.py backend/tests/unit/test_soldiers_field_updates.py frontend/src/pages/ProfilePage.tsx
git commit -m "feat: allow soldiers to request mandatory-end and discharge date updates"
```

---

### Task 3: Require the fields registration was missing validation for

**Context:** `RegisterRequest` in `backend/app/routes/auth.py:48-67` only truly requires `invite_code`, `personal_number`, `full_name`, `password`, `requested_node_id`. Fields like `phone`, `email`, `gender`, `rank`, `enlistment_date`, `mandatory_end_date`, `discharge_date`, `last_mitvahim_date` are optional even though the business process needs them. `frontend/src/pages/RegisterPage.tsx` step 2 (lines 166-246) only red-asterisks personal_number/full_name/password/confirm_password and only disables "next" based on those four.

**Files:**
- Modify: `backend/app/routes/auth.py:48-67`
- Modify: `frontend/src/pages/RegisterPage.tsx`
- Test: `backend/tests/integration/test_registration_routes.py`

**Interfaces:**
- Produces: `RegisterRequest.phone`, `.email`, `.gender`, `.rank`, `.enlistment_date`, `.mandatory_end_date`, `.discharge_date`, `.last_mitvahim_date` become required (no `= None` default). `is_officer`, `is_career`, `bahad1_graduate`, `last_alal_date` stay optional (derived from rank / conditionally applicable).

- [ ] **Step 1: Write the failing backend test**

Add to `backend/tests/integration/test_registration_routes.py`:

```python
def test_register_rejects_missing_phone(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(invite.code, node.id)
    del payload["phone"]
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 422
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pytest backend/tests/integration/test_registration_routes.py::test_register_rejects_missing_phone -v`
Expected: FAIL — currently returns 200 because `phone` is optional.

- [ ] **Step 3: Make the fields required in the schema**

In `backend/app/routes/auth.py`, change lines 53-64 from:

```python
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=200)
    gender: str | None = None
    is_officer: bool | None = None
    is_career: bool = False
    rank: str | None = None
    bahad1_graduate: bool = False
    enlistment_date: date | None = None
    mandatory_end_date: date | None = None
    discharge_date: date | None = None
    last_mitvahim_date: date | None = None
    last_alal_date: date | None = None
```

to:

```python
    phone: str = Field(max_length=40)
    email: str = Field(max_length=200)
    gender: str
    is_officer: bool | None = None
    is_career: bool = False
    rank: str
    bahad1_graduate: bool = False
    enlistment_date: date
    mandatory_end_date: date
    discharge_date: date
    last_mitvahim_date: date
    last_alal_date: date | None = None
```

`reg_svc.register(...)` at line 279-293 already forwards these by name and its own signature (`backend/app/services/registration.py:33-44`) already types them as `str | None` / `date | None` for storage flexibility — that's fine to leave as-is since Pydantic guarantees non-None by the time they reach the service.

- [ ] **Step 4: Run the backend test again to confirm it passes, then run the full registration test file**

Run: `pytest backend/tests/integration/test_registration_routes.py -v`
Expected: All PASS — `_payload()` already fills in `phone`, `gender`, `rank`, `enlistment_date`, `mandatory_end_date`, `discharge_date` for every test, so no other test in this file breaks.

- [ ] **Step 5: Mark the frontend fields required and gate "next"**

In `frontend/src/pages/RegisterPage.tsx`, update the step-2 labels (lines 178-190, 217-222) to add the same red-asterisk pattern used for personal_number/full_name. Change:

```tsx
            <label className="block text-sm">טלפון
```
to
```tsx
            <label className="block text-sm">טלפון <span className="text-red-500">*</span>
```

Same for `אימייל` (line 182) and `מגדר` (line 186). For the date-fields loop (line 217), the labels are plain strings in a tuple array — change:

```tsx
            {([["enlistment_date","תאריך גיוס"],["mandatory_end_date","סיום חובה"],["discharge_date","שחרור"],["last_mitvahim_date","מטווח אחרון"]] as [keyof FormData, string][]).map(([key, label]) => (
              <label key={key as string} className="block text-sm">{label}
```

to:

```tsx
            {([["enlistment_date","תאריך גיוס"],["mandatory_end_date","סיום חובה"],["discharge_date","שחרור"],["last_mitvahim_date","מטווח אחרון"]] as [keyof FormData, string][]).map(([key, label]) => (
              <label key={key as string} className="block text-sm">{label} <span className="text-red-500">*</span>
```

Then update the "next" button's `disabled` condition (line 242) from:

```tsx
                disabled={!form.personal_number || !form.full_name || !passwordValid(form.password) || form.password !== form.confirm_password}
```

to:

```tsx
                disabled={
                  !form.personal_number || !form.full_name || !form.phone || !form.email ||
                  !form.gender || !form.rank || !form.enlistment_date || !form.mandatory_end_date ||
                  !form.discharge_date || !form.last_mitvahim_date ||
                  !passwordValid(form.password) || form.password !== form.confirm_password
                }
```

- [ ] **Step 6: Typecheck the frontend**

Run: `npm run typecheck` (from `frontend/`)
Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/auth.py backend/tests/integration/test_registration_routes.py frontend/src/pages/RegisterPage.tsx
git commit -m "feat: require phone, email, gender, rank and service dates at registration"
```

---

### Task 4: Stop the exemption sub-form from crashing registration with a raw network error

**Context:** `backend/app/services/registration.py:98-105` does raw dict indexing on each item in `exemption_requests` (`er["exemption_type_id"]`, `er["start_date"]`). `RegisterRequest.exemption_requests` is typed as `list[dict]` (`backend/app/routes/auth.py:66`), so Pydantic performs no validation on its contents. Because `frontend/src/pages/RegisterPage.tsx`'s exemption row always has all four keys present but empty-string-valued when unfilled (`INITIAL` pattern at line 273: `{exemption_type_id:"",start_date:"",end_date:"",reason:""}`), a partially-filled row (e.g. type selected, no start date) sends `start_date: ""` through to `session.get(ExemptionType, er["exemption_type_id"])` / `ExemptionRequest(start_date=er["start_date"], ...)`, which raises an unhandled driver-level error (not a `RegistrationError`), surfacing to the user as a generic network error instead of a validation message.

**Files:**
- Modify: `backend/app/services/registration.py:98-123`
- Modify: `frontend/src/pages/RegisterPage.tsx`
- Test: `backend/tests/integration/test_registration_routes.py`

**Interfaces:**
- Produces: `RegistrationError("exemption_missing_fields")` and `RegistrationError("constraint_missing_fields")` — new error codes the route already maps to a 400 (`auth.py:296-297`) generically via `str(exc)`.

- [ ] **Step 1: Write the failing backend test**

Add to `backend/tests/integration/test_registration_routes.py`:

```python
def test_register_rejects_partial_exemption_request(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(
        invite.code, node.id,
        exemption_requests=[{"exemption_type_id": "", "start_date": "", "end_date": "", "reason": ""}],
    )
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "exemption_missing_fields"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pytest backend/tests/integration/test_registration_routes.py::test_register_rejects_partial_exemption_request -v`
Expected: FAIL — currently raises an unhandled 500 (empty-string UUID lookup), not a clean 400 with `exemption_missing_fields`.

- [ ] **Step 3: Validate exemption/constraint rows before using them**

In `backend/app/services/registration.py`, replace the loop at lines 98-114:

```python
    for er in exemption_requests:
        et = session.get(ExemptionType, er["exemption_type_id"])
        if et is None:
            raise RegistrationError("exemption_type_not_found")
        if et.is_commander_exemption:
            raise RegistrationError("commander_exemption_not_requestable")
        if er.get("end_date") is not None and er["end_date"] < er["start_date"]:
            raise RegistrationError("bad_date_range")
        session.add(ExemptionRequest(
            soldier_id=soldier.id,
            exemption_type_id=er["exemption_type_id"],
            start_date=er["start_date"],
            end_date=er.get("end_date"),
            reason=er.get("reason"),
            status="pending_commander",
            enrollment_request_id=enrollment_req.id,
        ))
```

with:

```python
    for er in exemption_requests:
        if not er.get("exemption_type_id") or not er.get("start_date"):
            raise RegistrationError("exemption_missing_fields")
        try:
            exemption_type_id = uuid.UUID(str(er["exemption_type_id"]))
        except ValueError as exc:
            raise RegistrationError("exemption_missing_fields") from exc
        et = session.get(ExemptionType, exemption_type_id)
        if et is None:
            raise RegistrationError("exemption_type_not_found")
        if et.is_commander_exemption:
            raise RegistrationError("commander_exemption_not_requestable")
        if er.get("end_date") and er["end_date"] < er["start_date"]:
            raise RegistrationError("bad_date_range")
        session.add(ExemptionRequest(
            soldier_id=soldier.id,
            exemption_type_id=exemption_type_id,
            start_date=er["start_date"],
            end_date=er.get("end_date") or None,
            reason=er.get("reason"),
            status="pending_commander",
            enrollment_request_id=enrollment_req.id,
        ))
```

Apply the equivalent guard to the `personal_constraints` loop at lines 116-123 — replace:

```python
    for pc in personal_constraints:
        session.add(PersonalConstraint(
            soldier_id=soldier.id,
            start_date=pc["start_date"],
            end_date=pc["end_date"],
            reason=pc["reason"],
            status="pending",
        ))
```

with:

```python
    for pc in personal_constraints:
        if not pc.get("start_date") or not pc.get("end_date"):
            raise RegistrationError("constraint_missing_fields")
        session.add(PersonalConstraint(
            soldier_id=soldier.id,
            start_date=pc["start_date"],
            end_date=pc["end_date"],
            reason=pc.get("reason"),
            status="pending",
        ))
```

- [ ] **Step 4: Run the backend test again to confirm it passes**

Run: `pytest backend/tests/integration/test_registration_routes.py -v`
Expected: All PASS.

- [ ] **Step 5: Guard the frontend so a half-filled row can't reach "next" either**

In `frontend/src/pages/RegisterPage.tsx`, step 3's "next" button (line 278) currently has no `disabled` condition. Add one so a row must be either fully filled or removed:

```tsx
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(2)}>{t("register.back")}</button>
              <button
                className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={form.exemption_requests.some(er => !er.exemption_type_id || !er.start_date)}
                onClick={() => setStep(4)}
              >
                {t("register.next")}
              </button>
            </div>
```

Also strip fully-empty trailing rows before submit — in `handleSubmit` (line 96-120), change the `register({...})` call's `exemption_requests` value from `form.exemption_requests` to a filtered list:

```tsx
        exemption_requests: form.exemption_requests.filter(er => er.exemption_type_id && er.start_date),
```

- [ ] **Step 6: Map the new error codes to Hebrew messages**

In `frontend/src/pages/RegisterPage.tsx`, add two entries to the `knownErrors` map (line 125-131):

```tsx
      const knownErrors: Record<string, string> = {
        "invalid invite code": t("register.errors.invite_code_invalid"),
        "invite code exhausted": t("register.errors.invite_code_exhausted"),
        "personal_number already exists": t("register.errors.personal_number_exists"),
        "holding node not bootstrapped": t("register.errors.node_not_bootstrapped"),
        "requested node not found": t("register.errors.node_not_found"),
        "exemption_missing_fields": t("register.errors.exemption_missing_fields"),
        "constraint_missing_fields": t("register.errors.constraint_missing_fields"),
      };
```

Add the two new keys under the existing `register.errors` namespace in `frontend/src/i18n/he.json` (find that block — it's near the other `register.errors.*` keys already used above):

```json
      "exemption_missing_fields": "יש למלא סוג פטור ותאריך התחלה לכל בקשת פטור, או להסיר את השורה",
      "constraint_missing_fields": "יש למלא תאריך התחלה וסיום לכל אילוץ, או להסיר את השורה"
```

- [ ] **Step 7: Typecheck and lint**

Run: `npm run typecheck` and `npm run lint` (from `frontend/`)
Expected: no new errors.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/registration.py backend/tests/integration/test_registration_routes.py frontend/src/pages/RegisterPage.tsx frontend/src/i18n/he.json
git commit -m "fix: reject partially-filled exemption/constraint rows with a clear message instead of crashing"
```

---

### Task 5: Show approval/rejection failures to the user instead of failing silently

**Context:** None of the decision handlers in `frontend/src/pages/ApprovalsPage.tsx` (`onApprove`, `onReject`, `onErApproveCommander`, `onErApproveDutyManager`, `onErReject`, `onFuApprove`, `onFuReject`, `onSwapApproveSide`, `onSwapReject`, lines 128-181) have a `try`/`catch`. When the backend rejects a decision (e.g. `HTTPException(400, detail="...")` from `backend/app/routes/exemptions.py:133,180`), the promise rejects, `refresh()` never runs, and nothing is shown to the user beyond an uncaught-promise warning in the console.

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Test: `frontend/src/pages/ApprovalsPage.test.tsx` (new file)

**Interfaces:**
- Produces: a new `[actionError, setActionError]` state and `describeError(err): string` helper, rendered as a dismissible banner near the top of the page.

- [ ] **Step 1: Write the failing frontend test**

Create `frontend/src/pages/ApprovalsPage.test.tsx`. Check `frontend/src/pages/RegisterPage.tsx`'s and `UnifiedNav.test.tsx`'s mocking conventions before writing — mock every `../api/*` module `ApprovalsPage` imports (`constraints`, `exemptions`, `soldiers`, `swaps`, `enrollment`, `hierarchy`, `auth`) so the initial `Promise.all` in the mount effect resolves immediately:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ApprovalsPage from "./ApprovalsPage";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

vi.mock("../api/constraints", () => ({
  listPendingApprovals: () => Promise.resolve([{ id: "c1", start_date: "2026-01-01", end_date: null, reason: "x", soldier_name: "A" }]),
  approveConstraint: vi.fn(() => Promise.reject({ response: { status: 400, data: { detail: "already_decided" } } })),
  rejectConstraint: vi.fn(),
}));
vi.mock("../api/exemptions", () => ({
  listPendingExemptionRequests: () => Promise.resolve([]),
  approveExemptionRequestCommanderStep: vi.fn(),
  approveExemptionRequestDutyManagerStep: vi.fn(),
  rejectExemptionRequest: vi.fn(),
  exemptionFileDownloadUrl: () => "",
}));
vi.mock("../api/soldiers", () => ({
  listPendingFieldUpdates: () => Promise.resolve([]),
  approveFieldUpdate: vi.fn(),
  rejectFieldUpdate: vi.fn(),
}));
vi.mock("../api/swaps", () => ({
  listPendingSwaps: () => Promise.resolve([]),
  approveSwapSide: vi.fn(),
  rejectSwap: vi.fn(),
}));
vi.mock("../api/enrollment", () => ({
  listPendingEnrollments: () => Promise.resolve([]),
  approveEnrollment: vi.fn(),
  rejectEnrollment: vi.fn(),
}));
vi.mock("../api/hierarchy", () => ({ fetchFullTree: () => Promise.resolve([]) }));
vi.mock("../api/auth", () => ({ listPublicExemptionTypes: () => Promise.resolve([]) }));

test("shows the backend error message when approving a constraint fails", async () => {
  render(<MemoryRouter><ApprovalsPage /></MemoryRouter>);
  const approveBtn = await screen.findByText("approvals.approve");
  fireEvent.click(approveBtn);
  await waitFor(() => {
    expect(screen.getByText(/already_decided/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `npm test -- ApprovalsPage.test.tsx` (from `frontend/`)
Expected: FAIL — no error text is ever rendered.

- [ ] **Step 3: Add the error banner and wrap the decision handlers**

In `frontend/src/pages/ApprovalsPage.tsx`, add state near the other `useState` calls (after line 78):

```tsx
  const [actionError, setActionError] = useState<string | null>(null);
```

Add a helper above the component or near the top of the file, after the imports:

```tsx
function describeError(err: unknown): string {
  if (err && typeof err === "object" && "response" in err) {
    const resp = (err as { response?: { data?: { detail?: string } } }).response;
    if (resp?.data?.detail) return resp.data.detail;
  }
  return "שגיאה בביצוע הפעולה";
}
```

Wrap every decision handler (lines 128-181) in try/catch, e.g.:

```tsx
  async function onApprove(id: string) {
    try {
      await approveConstraint(id);
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }
  async function onReject(id: string) {
    const note = rejectNotes[id];
    if (!note) return;
    try {
      await rejectConstraint(id, note);
      const next = { ...rejectNotes };
      delete next[id];
      setRejectNotes(next);
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }
```

Apply the identical try/catch wrapping pattern to `onErApproveCommander`, `onErApproveDutyManager`, `onErReject`, `onFuApprove`, `onFuReject`, `onSwapApproveSide`, `onSwapReject`.

Render the banner near the top of the returned JSX (find the `<Layout>` opening and the first tab-bar/header row, and insert just inside it):

```tsx
        {actionError && (
          <div className="bg-red-50 dark:bg-red-950 border border-red-300 dark:border-red-800 text-red-700 dark:text-red-300 text-sm rounded p-2 flex items-center justify-between" dir="rtl">
            <span>{actionError}</span>
            <button className="text-red-500 hover:text-red-700" onClick={() => setActionError(null)}>✕</button>
          </div>
        )}
```

- [ ] **Step 4: Run the frontend test again to confirm it passes**

Run: `npm test -- ApprovalsPage.test.tsx` (from `frontend/`)
Expected: PASS

- [ ] **Step 5: Typecheck and lint**

Run: `npm run typecheck` and `npm run lint` (from `frontend/`)
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx frontend/src/pages/ApprovalsPage.test.tsx
git commit -m "fix: show backend error detail when an approval/rejection action fails"
```

---

### Task 6: Make the Transparency page's unit filter searchable

**Context:** `frontend/src/pages/TransparencyPage.tsx` renders its unit filter with a bespoke `TreeNode` component (lines 43-76, used at lines 913-928) — it IS hierarchical and indented, but has no text search. The codebase already has a `Combobox` component (`frontend/src/components/Combobox.tsx`) that supports fuzzy search (Fuse.js) *and* indentation via its `depth` prop (lines 165, 174), and a `sortNodesByTree` util (`frontend/src/utils/sortNodesByTree.ts`) that flattens a tree into `{node, depth}` pairs in DFS order — this exact pairing is already used for the same purpose in `ProfilePage.tsx:512-517`. Swap the custom tree-dropdown for `Combobox` fed by `sortNodesByTree`.

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx`

**Interfaces:**
- Consumes: `Combobox` (`items: ComboboxItem[]`, `value: string`, `onChange: (id: string) => void`, `placeholder?: string`) and `sortNodesByTree(nodes: NodeDTO[]): { node: NodeDTO; depth: number }[]` — both already exist, no signature changes.

- [ ] **Step 1: Import the reused pieces**

In `frontend/src/pages/TransparencyPage.tsx`, add to the imports (near line 12):

```tsx
import Combobox from "../components/Combobox";
import { sortNodesByTree } from "../utils/sortNodesByTree";
```

- [ ] **Step 2: Replace the `TreeNode` dropdown markup with a `Combobox`**

Replace the block at lines 913-928:

```tsx
            {treeOpen && (
              <div
                className="absolute left-0 top-full mt-1 z-20 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg p-2 min-w-52 max-h-72 overflow-y-auto"
                dir="rtl"
              >
                <div className="flex items-center justify-between mb-1 px-1">
                  <span className="text-xs text-gray-500">בחר יחידה לסינון</span>
                  {selectedNodeId && (
                    <button className="text-xs text-red-500 hover:underline" onClick={clearFilter}>הצג הכל</button>
                  )}
                </div>
                {treeNodes.map((node) => (
                  <TreeNode key={node.id} node={node} selectedId={selectedNodeId} onSelect={handleSelectNode} depth={0} />
                ))}
              </div>
            )}
```

with:

```tsx
            {treeOpen && (
              <div
                className="absolute left-0 top-full mt-1 z-20 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg p-2 min-w-64"
                dir="rtl"
              >
                <div className="flex items-center justify-between mb-1 px-1">
                  <span className="text-xs text-gray-500">בחר יחידה לסינון</span>
                  {selectedNodeId && (
                    <button className="text-xs text-red-500 hover:underline" onClick={clearFilter}>הצג הכל</button>
                  )}
                </div>
                <Combobox
                  items={sortNodesByTree(flatNodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
                  value={selectedNodeId ?? ""}
                  onChange={handleSelectNode}
                  placeholder="— כל הארגון —"
                  testId="transparency-unit-filter"
                />
              </div>
            )}
```

`flatNodes` is already computed at line 350 (`const flatNodes = useMemo(() => flattenTree(treeNodes), [treeNodes]);`) and `handleSelectNode`/`clearFilter`/`selectedNodeId` are unchanged — only the dropdown's internal rendering changes. `sortNodesByTree` expects `parent_id`-linked nodes, which `NodeDTO` already provides (used the same way in `ProfilePage.tsx:513`).

- [ ] **Step 3: Remove the now-unused `TreeNode` component**

Delete the `TreeNode` function definition (lines 43-76) since nothing references it anymore after Step 2. Confirm with a search first:

Run: `grep -n "TreeNode" frontend/src/pages/TransparencyPage.tsx`
Expected: no remaining references outside the definition itself before deleting it.

- [ ] **Step 4: Typecheck and lint**

Run: `npm run typecheck` and `npm run lint` (from `frontend/`)
Expected: no new errors, no unused-import warnings.

- [ ] **Step 5: Manually verify in the browser**

Start the dev stack (`.\dev.ps1`), open the Transparency page, click "סנן לפי יחידה", type a partial unit name, and confirm the filtered/indented list appears and selecting an entry filters the table as before.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx
git commit -m "feat: make the transparency page's unit filter searchable"
```

---

### Task 7: Clarify the military-license (רשנ"צ) date label and stop it rendering as raw JSON in approvals

**Context:** Two related complaints turned out to be about the same field: `has_military_driving_license` / `military_driving_license_expiry` (רשנ"צ = military driving license). (1) The label doesn't say the date is the license's validity/expiry as tracked in the army's "ארנק צהלי" app, so soldiers are unsure what date to enter. (2) `ProfilePage.tsx:23-40` already has a `formatFieldUpdateValue` helper that JSON-parses the `military_driving_license` field-update payload into a readable string — but `ApprovalsPage.tsx:370-371` renders `item.previous_value` / `item.new_value` directly with no such formatting, so a commander/duty-manager reviewing a pending license update sees the raw `{"has_license":true,"expiry_date":"2027-01-01"}` string instead of a formatted value.

**Files:**
- Modify: `frontend/src/i18n/he.json:504`
- Create: `frontend/src/utils/formatFieldUpdateValue.ts`
- Modify: `frontend/src/pages/ProfilePage.tsx`
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Test: `frontend/src/utils/formatFieldUpdateValue.test.ts` (new file)

**Interfaces:**
- Produces: `formatFieldUpdateValue(fieldName: string, value: string | null, t: (key: string) => string): string` — same signature as the function currently private to `ProfilePage.tsx`, now exported from its own module so both pages can use it.

- [ ] **Step 1: Clarify the label copy**

In `frontend/src/i18n/he.json:504`, change:

```json
    "military_driving_license_expiry": "תאריך תפוגה",
```

to:

```json
    "military_driving_license_expiry": "תאריך תפוגה (תוקף רשנ\"צ, כפי שמופיע באפליקציית ארנק צה\"לי)",
```

- [ ] **Step 2: Write the failing unit test for the extracted util**

Create `frontend/src/utils/formatFieldUpdateValue.test.ts`:

```ts
import { formatFieldUpdateValue } from "./formatFieldUpdateValue";

const t = (key: string) => key;

test("formats a military_driving_license JSON payload with a license and expiry", () => {
  const value = JSON.stringify({ has_license: true, expiry_date: "2027-01-01" });
  expect(formatFieldUpdateValue("military_driving_license", value, t)).toContain("✓");
});

test("formats a military_driving_license payload with no license as a dash", () => {
  const value = JSON.stringify({ has_license: false, expiry_date: null });
  expect(formatFieldUpdateValue("military_driving_license", value, t)).toBe("—");
});

test("returns the raw string unchanged for non-JSON fields", () => {
  expect(formatFieldUpdateValue("phone", "050-1234567", t)).toBe("050-1234567");
});

test("falls back to null-dash for empty values", () => {
  expect(formatFieldUpdateValue("phone", null, t)).toBe("—");
});
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `npm test -- formatFieldUpdateValue.test.ts` (from `frontend/`)
Expected: FAIL — the module doesn't exist yet.

- [ ] **Step 4: Extract the function into its own module**

Create `frontend/src/utils/formatFieldUpdateValue.ts` with the exact logic currently inline in `ProfilePage.tsx:23-40` (using `formatDate` from `../utils/formatDate`, already used the same way in `ProfilePage.tsx:6`):

```ts
import { formatDate } from "./formatDate";

export function formatFieldUpdateValue(
  fieldName: string,
  value: string | null,
  t: (key: string) => string
): string {
  if (!value) return "—";
  if (fieldName === "gender") return t(`soldier_profile.gender_${value}`);
  if (fieldName === "military_driving_license") {
    try {
      const parsed = JSON.parse(value) as { has_license: boolean; expiry_date: string | null };
      if (!parsed.has_license) return "—";
      return parsed.expiry_date ? `✓ (${formatDate(parsed.expiry_date)})` : "✓";
    } catch {
      return value;
    }
  }
  return value;
}
```

- [ ] **Step 5: Run the test again to confirm it passes**

Run: `npm test -- formatFieldUpdateValue.test.ts` (from `frontend/`)
Expected: PASS

- [ ] **Step 6: Update `ProfilePage.tsx` to import instead of defining it inline**

In `frontend/src/pages/ProfilePage.tsx`, delete the inline function definition (lines 23-40) and add an import near the top (next to the `formatDate` import at line 6):

```tsx
import { formatFieldUpdateValue } from "../utils/formatFieldUpdateValue";
```

No call sites change — `formatFieldUpdateValue(u.field_name, u.previous_value, t)` at lines 377/380 already match the extracted signature.

- [ ] **Step 7: Use the shared formatter in `ApprovalsPage.tsx`**

In `frontend/src/pages/ApprovalsPage.tsx`, add the import (next to the other imports near the top):

```tsx
import { formatFieldUpdateValue } from "../utils/formatFieldUpdateValue";
```

Replace lines 370-371:

```tsx
                <div className="text-gray-500 dark:text-gray-400">{t("soldier_profile.previous_value")}: <span className="font-mono">{item.new_value === null ? "מידע פרטי" : item.previous_value ? (item.field_name === "gender" ? t(`soldier_profile.gender_${item.previous_value}`) : item.previous_value) : "—"}</span></div>
                <div className="text-gray-600 dark:text-gray-300">{t("approvals.field_update_new_value")}<strong>{item.new_value === null ? "מידע פרטי" : item.field_name === "gender" ? t(`soldier_profile.gender_${item.new_value}`) : item.new_value}</strong></div>
```

with:

```tsx
                <div className="text-gray-500 dark:text-gray-400">{t("soldier_profile.previous_value")}: <span className="font-mono">{item.new_value === null ? "מידע פרטי" : formatFieldUpdateValue(item.field_name, item.previous_value, t)}</span></div>
                <div className="text-gray-600 dark:text-gray-300">{t("approvals.field_update_new_value")}<strong>{item.new_value === null ? "מידע פרטי" : formatFieldUpdateValue(item.field_name, item.new_value, t)}</strong></div>
```

(`item.new_value === null` is the existing "redacted private field" case from `PRIVATE_FIELD_NAMES` in `backend/app/routes/soldiers.py:203` — preserved as-is.)

- [ ] **Step 8: Typecheck and lint**

Run: `npm run typecheck` and `npm run lint` (from `frontend/`)
Expected: no new errors.

- [ ] **Step 9: Manually verify in the browser**

Start the dev stack, submit a military-license field update from a soldier's profile, then view it as a commander/duty-manager on the Approvals page's "field_updates" tab and confirm it shows `✓ (date)` or `—` rather than raw JSON.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/i18n/he.json frontend/src/utils/formatFieldUpdateValue.ts frontend/src/utils/formatFieldUpdateValue.test.ts frontend/src/pages/ProfilePage.tsx frontend/src/pages/ApprovalsPage.tsx
git commit -m "fix: clarify military-license date label and format its value in approvals"
```

---

### Task 8 (diagnostic, not a blind fix): Confirm the root cause of "login not remembered after refresh"

**Context:** Code inspection does not show a bug: `frontend/src/api/client.ts:10` intentionally keeps the access token in memory only; `frontend/src/auth/AuthContext.tsx:26-32` calls `POST /auth/refresh` on mount using the httpOnly `refresh_token` cookie and only then fetches `/me`; `frontend/src/auth/ProtectedRoute.tsx:6-8` correctly waits for `authLoading` before redirecting to `/login`. This is the standard "access token in memory, refresh token in httpOnly cookie" pattern and should survive a same-origin page refresh. Locally, `.env` already sets `COOKIE_SECURE=false` so the cookie isn't silently dropped over `http://localhost`. The likely candidates for a real-world failure are deployment-side: (a) `COOKIE_SECURE=true` (the default in `backend/app/settings.py:24`) while the app is actually served over plain HTTP in production/self-hosted, which makes browsers silently refuse to store the `Secure` cookie; (b) a reverse proxy not forwarding the `refresh_token` cookie or stripping it on the `/api/auth` path. Because this can't be confirmed by reading code alone, this task is a **verification step**, not a code change — do not "fix" this blindly.

**Files:** none changed by this task.

- [ ] **Step 1: Reproduce with the network tab open**

In the environment where the bug was reported (ask the user: local dev, or the deployed/Tailscale-funneled instance?), log in, open browser dev tools → Network tab, and inspect the `Set-Cookie` header on the `/api/auth/login` response: confirm whether it includes `Secure` and whether the page is being served over `https://`.

- [ ] **Step 2: Refresh and inspect the `/api/auth/refresh` request**

After refreshing the page, check whether the `refresh_token` cookie is present in the request headers for `/api/auth/refresh`, and what status code comes back.

- [ ] **Step 3: Decide the fix based on findings**

- If the cookie is missing from the refresh request because `Secure` was set but the page is HTTP: set `COOKIE_SECURE=false` in that environment's `.env` (if it will never be served over HTTPS) — this is a config change, not a code change, and should not be made speculatively without confirming step 1.
- If the cookie is present but `/auth/refresh` still returns 401: capture the exact `detail` value (`no_refresh_cookie` / `invalid_refresh_token` / `wrong_token_type` / `user_not_found` / `token_revoked` — see `backend/app/routes/auth.py:192-212`) and open a follow-up task, since each of those five codes points to a different root cause.

---

## Self-Review Notes

- Every task above is independently testable and independently committable — none depend on another task's code changes (Task 7 touches the same `ProfilePage.tsx`/`ApprovalsPage.tsx` files as Tasks 2 and 5 respectively, but different, non-overlapping sections of each; if executed by parallel subagents, run Task 2 and Task 5 before Task 7 to avoid merge conflicts on those two files).
- Task 8 intentionally produces no diff — it's there so the executing agent (or the user) doesn't skip straight to guessing a fix for the one item that static reading couldn't confirm.
- All copy changes are Hebrew-only, consistent with the existing `he.json` file (no `en.json` exists in this repo).
