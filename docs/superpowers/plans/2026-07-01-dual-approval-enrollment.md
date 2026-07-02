# Dual-Approval Enrollment + Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dual-approval enrollment (commander + eligible duty manager approve in parallel before soldier is activated) and fix four independent bugs: dismiss permission guard, edit-soldier single-click, ALAL alert filter, and exemption type dropdown.

**Architecture:** DB gains two new columns (`soldiers.is_career`, `exemption_requests.enrollment_request_id`). A new `try_activate` function in the enrollment service gates soldier activation on both commander approval and all linked exemption requests being resolved. The existing `/exemption-requests/pending` and `/enrollment-requests/pending` endpoints are enriched; two PATCH endpoints are added so approvers can edit data before deciding. Frontend gains a full-screen enrollment approval modal and inline exemption editing in ApprovalsPage.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript/Tailwind (frontend), Alembic (migrations), pytest (tests), vitest (frontend tests).

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `backend/app/db/models.py` | Modify | Add `is_career` to `Soldier`, `enrollment_request_id` to `ExemptionRequest` |
| `backend/app/db/migrations/versions/<hash>_dual_approval.py` | Create | Alembic migration for both columns |
| `backend/app/services/enrollment.py` | Modify | Add `try_activate`, change `approve_enrollment` to set `commander_approved` then call `try_activate` |
| `backend/app/services/registration.py` | Modify | Accept `is_career`, reorder to create enrollment first, link exemptions, call `notify_enrollment_received` |
| `backend/app/services/exemption_requests.py` | Modify | Call `try_activate` after approve/reject when `enrollment_request_id` is set |
| `backend/app/services/notifications.py` | Modify | Add `notify_enrollment_received` that notifies commanders + eligible DMs of the requested node |
| `backend/app/routes/auth.py` | Modify | Add `GET /auth/exemption-types` (public, no auth) |
| `backend/app/routes/me.py` | Modify | Add `is_career` to `MeResponse` and the `/me` query |
| `backend/app/routes/enrollment.py` | Modify | Enrich `GET /pending` with full soldier data + exemptions; add `PATCH /{id}` |
| `backend/app/routes/exemption_requests.py` | Modify | Add `PATCH /{id}`; add DM level-rank filter to `GET /pending` for enrollment exemptions |
| `backend/app/services/tests/test_enrollment.py` | Modify | Update + add tests for `commander_approved` status, `try_activate` |
| `backend/app/services/tests/test_registration.py` | Modify | Update + add tests for `is_career`, exemption→enrollment linking |
| `frontend/src/api/auth.ts` | Modify | Add `is_career` to `Me`, add `listPublicExemptionTypes()` |
| `frontend/src/api/enrollment.ts` | Modify | Expand `EnrollmentRequestDTO`, add `patchEnrollment()` |
| `frontend/src/api/exemptions.ts` | Modify | Add `enrollment_request_id` to `ExemptionRequest`, add `patchExemptionRequest()` |
| `frontend/src/components/ShiftDetailPanel.tsx` | Modify | Wrap both dismiss buttons in DM/admin permission guard |
| `frontend/src/components/HierarchyTree.tsx` | Modify | Change button label from `view_profile` to `edit` |
| `frontend/src/components/dashboard/AlertBanners.tsx` | Modify | Show ALAL alert only for `is_officer \|\| is_career` users |
| `frontend/src/pages/RegisterPage.tsx` | Modify | Replace UUID input with `Combobox` for exemption type; send `is_career` |
| `frontend/src/components/EnrollmentApprovalModal.tsx` | Create | Full edit+approve modal for commander enrollment review |
| `frontend/src/pages/ApprovalsPage.tsx` | Modify | Open `EnrollmentApprovalModal` on row click; add inline edit for exemption requests |

---

## Task 1: Fix — Dismiss Buttons Permission Guard

**Files:**
- Modify: `frontend/src/components/ShiftDetailPanel.tsx`

- [ ] **Step 1: Wrap primary-soldier dismiss button**

In `ShiftDetailPanel.tsx` around line 218–233, the dismiss button for primary soldiers has no permission check. Wrap it:

```tsx
{!isCalledUp && (
  <div className="flex items-center gap-1">
    {a.soldier_id !== user?.id && canOfferReplace && (
      <button
        className="text-xs bg-indigo-100 text-indigo-800 px-2 py-0.5 rounded hover:bg-indigo-200"
        onClick={() => setOfferSwapTarget({ soldierId: a.soldier_id, soldierName: a.soldier_name, assignmentId: a.assignment_id })}
      >
        {t("swaps.offer_replace")}
      </button>
    )}
    {(user?.role === "admin" || user?.is_duty_manager) && (
      <button
        className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded hover:bg-amber-200"
        onClick={() => setDismissTarget(a)}
      >
        {t("dismiss_action")}
      </button>
    )}
  </div>
)}
```

- [ ] **Step 2: Wrap reserve-soldier dismiss button**

Around line 338–352, the reserve dismiss button also has no guard. Change the reserves `<div className="flex items-center gap-1">` block so the dismiss button is:

```tsx
<div className="flex items-center gap-1">
  {a.soldier_id !== user?.id && canOfferReplace && (
    <button
      className="text-xs bg-indigo-100 text-indigo-800 px-2 py-0.5 rounded hover:bg-indigo-200"
      onClick={() => setOfferSwapTarget({ soldierId: a.soldier_id, soldierName: a.soldier_name, assignmentId: a.assignment_id })}
    >
      {t("swaps.offer_replace")}
    </button>
  )}
  {(user?.role === "admin" || user?.is_duty_manager) && (
    <button
      className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded hover:bg-amber-200"
      onClick={() => setReserveDismissTarget(a)}
    >
      {t("dismiss_action")}
    </button>
  )}
  <span className={`text-xs px-2 py-0.5 rounded ${a.called_up_from ? "bg-blue-100 text-blue-800" : "bg-gray-100 text-gray-600"}`}>
    {a.called_up_from ? `${t("reserve_called_up")} ${a.called_up_from}–${a.called_up_to}` : t("reserve_standby")}
  </span>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ShiftDetailPanel.tsx
git commit -m "fix: hide dismiss-from-duty buttons for non-managers"
```

---

## Task 2: Fix — Edit Soldier Single Click

**Files:**
- Modify: `frontend/src/components/HierarchyTree.tsx`

- [ ] **Step 1: Change button label**

In `HierarchyTree.tsx` around line 97–103 inside `DraggableSoldier`, the button says `{t("team.view_profile")}`. Change it to `{t("team.edit")}`:

```tsx
{isAdmin && (
  <button
    className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline ml-auto"
    onClick={() => onEdit(s)}
    data-testid={`edit-soldier-${s.personal_number}`}
  >
    {t("team.edit")}
  </button>
)}
```

The `UnifiedSoldierModal` already receives `initialEditing={true}` (line 502), so the modal opens directly in edit mode on the details tab. This fix is purely the label.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/HierarchyTree.tsx
git commit -m "fix: change hierarchy edit button label to make edit intent clear"
```

---

## Task 3: Fix — ALAL Alert Filter + is_career in Me

**Files:**
- Modify: `backend/app/routes/me.py`
- Modify: `frontend/src/api/auth.ts`
- Modify: `frontend/src/components/dashboard/AlertBanners.tsx`

- [ ] **Step 1: Add `is_career` to `MeResponse` and the `/me` handler**

In `backend/app/routes/me.py`, add `is_career` to `MeResponse`:

```python
class MeResponse(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    is_commander: bool
    is_duty_manager: bool
    must_change_password: bool
    hierarchy_node_id: uuid.UUID | None
    telegram_linked: bool
    telegram_required: bool
    phone: str | None = None
    gender: str | None = None
    is_officer: bool | None = None
    is_career: bool = False          # ← NEW
    rank: str | None = None
    bahad1_graduate: bool = False
    enlistment_date: str | None = None
    mandatory_end_date: str | None = None
    discharge_date: str | None = None
    last_mitvahim_date: str | None = None
    last_alal_date: str | None = None
    email: str | None = None
    email_verified: bool = False
    direct_commander_id: uuid.UUID | None = None
    direct_commander_name: str | None = None
    profile_picture_url: str | None = None
```

Find the `/me` GET handler (it builds `MeResponse(...)`) and add `is_career=user.is_career` to the constructor call. (The `Soldier` model will have this field after Task 4's migration — add the attribute reference now, it won't break until the column exists, and migration runs before the server starts.)

- [ ] **Step 2: Add `is_career` to `Me` frontend type**

In `frontend/src/api/auth.ts`:

```typescript
export interface Me {
  id: string;
  personal_number: string;
  full_name: string;
  role: "soldier" | "commander" | "duty_manager" | "admin";
  is_commander: boolean;
  is_duty_manager: boolean;
  must_change_password: boolean;
  hierarchy_node_id: string | null;
  telegram_linked: boolean;
  telegram_required: boolean;
  phone?: string | null;
  gender?: string | null;
  is_officer?: boolean | null;
  is_career?: boolean;               // ← NEW
  rank?: string | null;
  bahad1_graduate?: boolean;
  enlistment_date?: string | null;
  mandatory_end_date?: string | null;
  discharge_date?: string | null;
  last_mitvahim_date?: string | null;
  last_alal_date?: string | null;
  email?: string | null;
  email_verified?: boolean;
  direct_commander_id?: string | null;
  direct_commander_name?: string | null;
  profile_picture_url?: string | null;
}
```

- [ ] **Step 3: Filter ALAL alert in AlertBanners**

In `frontend/src/components/dashboard/AlertBanners.tsx`, replace:

```typescript
const alalMsg = alertMessage(lastAlalDate, alalValidity, alalWarn, 'אל"ל');
if (alalMsg) alerts.push({ key: "alal", message: alalMsg });
```

with:

```typescript
const isAlalRelevant = user?.is_officer || user?.is_career;
if (isAlalRelevant) {
  const alalMsg = alertMessage(lastAlalDate, alalValidity, alalWarn, 'אל"ל');
  if (alalMsg) alerts.push({ key: "alal", message: alalMsg });
}
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/me.py frontend/src/api/auth.ts frontend/src/components/dashboard/AlertBanners.tsx
git commit -m "fix: ALAL alert shown only for officers and career soldiers"
```

---

## Task 4: DB Migration — is_career + enrollment_request_id

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/app/db/migrations/versions/<hash>_dual_approval_enrollment.py`

- [ ] **Step 1: Add columns to models**

In `backend/app/db/models.py`, in the `Soldier` class (after `is_officer` around line 51):

```python
is_career: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
```

In the `ExemptionRequest` class (after `reason` around line 507), add:

```python
enrollment_request_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True),
    ForeignKey("soldier_enrollment_requests.id", ondelete="SET NULL"),
    nullable=True,
    default=None,
)
```

- [ ] **Step 2: Generate migration**

```bash
cd backend
.venv\Scripts\activate  # Windows
alembic revision --autogenerate -m "dual_approval_enrollment"
```

Open the generated file and verify it contains:
- `op.add_column('soldiers', sa.Column('is_career', sa.Boolean(), server_default='false', nullable=False))`
- `op.add_column('exemption_requests', sa.Column('enrollment_request_id', postgresql.UUID(as_uuid=True), nullable=True))`
- `op.create_foreign_key(...)` for the FK to `soldier_enrollment_requests`

If autogenerate misses anything, add it manually.

- [ ] **Step 3: Apply migration**

```bash
alembic upgrade head
```

Expected: no errors, two columns added.

- [ ] **Step 4: Run existing enrollment + registration tests**

```bash
pytest backend/app/services/tests/test_enrollment.py backend/app/services/tests/test_registration.py -v
```

Expected: all pass (no logic changed yet, just columns added).

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/app/db/migrations/versions/
git commit -m "feat: add is_career to soldiers and enrollment_request_id to exemption_requests"
```

---

## Task 5: Public Exemption Types Endpoint

**Files:**
- Modify: `backend/app/routes/auth.py`
- Modify: `frontend/src/api/auth.ts`

- [ ] **Step 1: Add endpoint**

In `backend/app/routes/auth.py`, add the import and endpoint. At the top add:

```python
from app.db.models import ExemptionType
```

Then add the endpoint (no `Depends(get_current_user)` — public):

```python
class PublicExemptionTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None


@router.get("/exemption-types", response_model=list[PublicExemptionTypeOut])
def list_public_exemption_types(
    session: Session = Depends(get_session),
) -> list[PublicExemptionTypeOut]:
    types = session.execute(select(ExemptionType).order_by(ExemptionType.name)).scalars().all()
    return [PublicExemptionTypeOut(id=et.id, name=et.name, description=et.description) for et in types]
```

- [ ] **Step 2: Add frontend API function**

In `frontend/src/api/auth.ts`, add (using `api` which already points to the right base URL):

```typescript
export interface PublicExemptionType {
  id: string;
  name: string;
  description: string | null;
}

export async function listPublicExemptionTypes(): Promise<PublicExemptionType[]> {
  const r = await api.get<PublicExemptionType[]>("/auth/exemption-types");
  return r.data;
}
```

- [ ] **Step 3: Verify endpoint manually**

Start the backend: `.\dev.ps1 -NoBot` and visit `http://localhost:8000/auth/exemption-types` — should return JSON array (may be empty if no types seeded).

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/auth.py frontend/src/api/auth.ts
git commit -m "feat: public GET /auth/exemption-types endpoint for registration"
```

---

## Task 6: Fix — Exemption Type Combobox in RegisterPage

**Files:**
- Modify: `frontend/src/pages/RegisterPage.tsx`

- [ ] **Step 1: Add state for exemption types**

In `RegisterPage`, import `listPublicExemptionTypes` and `PublicExemptionType`:

```typescript
import { validateInviteCode, fetchRegisterNodes, register, NodeOut } from "../api/auth";
import { listPublicExemptionTypes, PublicExemptionType } from "../api/auth";
```

Add state in the component:

```typescript
const [exemptionTypes, setExemptionTypes] = useState<PublicExemptionType[]>([]);
```

Load them once when the component mounts (they're public, no auth needed):

```typescript
useEffect(() => {
  listPublicExemptionTypes().then(setExemptionTypes).catch(() => {});
}, []);
```

- [ ] **Step 2: Replace UUID input with Combobox in step 3**

In the step 3 section (around line 247–257), replace:

```tsx
<input placeholder="מזהה סוג פטור (UUID)" className="..." value={er.exemption_type_id}
  onChange={e => { ... }} />
```

with:

```tsx
<Combobox
  items={exemptionTypes.map(t => ({ id: t.id, name: t.name }))}
  value={er.exemption_type_id}
  onChange={v => {
    const rows = [...form.exemption_requests];
    rows[i] = { ...rows[i], exemption_type_id: v };
    set("exemption_requests", rows);
  }}
  placeholder="סוג פטור"
/>
```

- [ ] **Step 3: Add is_career to FormData and send it**

In `FormData` interface add `is_career: boolean`. In `INITIAL` add `is_career: false`.

The `is_career` checkbox already exists in the form (around line 207). Currently it only controls the `last_alal_date` field visibility but isn't sent. Update `handleSubmit` to include it in the `register(...)` call:

In `RegisterPayload` in `auth.ts` add `is_career: boolean`. In `handleSubmit`:

```typescript
const resp = await register({
  invite_code: form.invite_code,
  personal_number: form.personal_number,
  full_name: form.full_name,
  password: form.password,
  phone: form.phone || null,
  email: form.email || null,
  gender: form.gender || null,
  is_officer: form.is_officer,
  is_career: form.is_career,           // ← NEW
  rank: form.rank || null,
  bahad1_graduate: form.bahad1_graduate,
  enlistment_date: form.enlistment_date || null,
  mandatory_end_date: form.mandatory_end_date || null,
  discharge_date: form.discharge_date || null,
  last_mitvahim_date: form.last_mitvahim_date || null,
  last_alal_date: form.last_alal_date || null,
  requested_node_id: form.requested_node_id,
  exemption_requests: form.exemption_requests,
  personal_constraints: form.personal_constraints,
});
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/RegisterPage.tsx frontend/src/api/auth.ts
git commit -m "fix: exemption type combobox in registration; send is_career"
```

---

## Task 7: Enrollment Service — try_activate + commander_approved

**Files:**
- Modify: `backend/app/services/enrollment.py`
- Modify: `backend/app/services/tests/test_enrollment.py`

- [ ] **Step 1: Write failing tests**

Replace `backend/app/services/tests/test_enrollment.py` content with (keep existing tests and add new ones):

```python
from __future__ import annotations

import uuid
import pytest

from app.db.models import ExemptionRequest, ExemptionType, HierarchyNode, SoldierEnrollmentRequest, SystemSetting
from tests.helpers import create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _make_holding(session):
    node = HierarchyNode(level="division", name=f"holding_{_uid()}", parent_id=None, commander_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    session.flush()
    if session.get(SystemSetting, "system.holding_node_id") is None:
        session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    session.commit()
    return node


def _make_req(session, soldier, node):
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    session.add(req)
    session.commit()
    session.refresh(req)
    return req


def _make_exemption_type(session):
    et = ExemptionType(name=f"type_{_uid()}")
    session.add(et)
    session.flush()
    return et


def _make_exemption_req(session, soldier, et, enrollment_req):
    er = ExemptionRequest(
        soldier_id=soldier.id,
        exemption_type_id=et.id,
        start_date="2026-01-01",
        end_date=None,
        reason=None,
        status="pending",
        enrollment_request_id=enrollment_req.id,
    )
    session.add(er)
    session.commit()
    session.refresh(er)
    return er


# --- Existing tests (updated assertions) ---

def test_approve_without_exemptions_activates_immediately(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)

    from app.services.enrollment import approve_enrollment
    approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    # No pending exemptions → activates immediately
    assert soldier.hierarchy_node_id == node.id
    assert req.status == "approved"
    assert req.decided_by == decider.id


def test_approve_with_pending_exemptions_sets_commander_approved(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)
    et = _make_exemption_type(admin_session)
    _make_exemption_req(admin_session, soldier, et, req)

    from app.services.enrollment import approve_enrollment
    approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    # Has pending exemption → wait for DM
    assert soldier.hierarchy_node_id == holding.id
    assert req.status == "commander_approved"


def test_try_activate_activates_when_all_exemptions_closed(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)
    req.status = "commander_approved"
    admin_session.commit()
    et = _make_exemption_type(admin_session)
    er = _make_exemption_req(admin_session, soldier, et, req)
    er.status = "approved"
    admin_session.commit()

    from app.services.enrollment import try_activate
    try_activate(admin_session, req.id)
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    assert soldier.hierarchy_node_id == node.id
    assert req.status == "approved"


def test_try_activate_does_not_activate_when_exemption_still_pending(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)
    req.status = "commander_approved"
    admin_session.commit()
    et = _make_exemption_type(admin_session)
    _make_exemption_req(admin_session, soldier, et, req)

    from app.services.enrollment import try_activate
    try_activate(admin_session, req.id)
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    assert soldier.hierarchy_node_id == holding.id
    assert req.status == "commander_approved"


def test_reject_leaves_soldier_in_holding(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)

    from app.services.enrollment import reject_enrollment
    reject_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note="not eligible")
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    assert soldier.hierarchy_node_id == holding.id
    assert req.status == "rejected"
    assert req.decision_note == "not eligible"


def test_approve_already_decided_raises(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)

    from app.services.enrollment import approve_enrollment, EnrollmentError
    approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)
    admin_session.commit()

    with pytest.raises(EnrollmentError, match="already decided"):
        approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)


def test_list_pending_scoped_to_node_ids(admin_session):
    holding = _make_holding(admin_session)
    node_a = create_node(admin_session, level="unit", name=f"a_{_uid()}", parent=holding)
    node_b = create_node(admin_session, level="unit", name=f"b_{_uid()}", parent=holding)
    s1 = create_soldier(admin_session, personal_number=f"s1_{_uid()}", hierarchy_node_id=holding.id)
    s2 = create_soldier(admin_session, personal_number=f"s2_{_uid()}", hierarchy_node_id=holding.id)
    _make_req(admin_session, s1, node_a)
    _make_req(admin_session, s2, node_b)

    from app.services.enrollment import list_pending_for_node_ids
    results = list_pending_for_node_ids(admin_session, {node_a.id})
    assert len(results) == 1
    assert results[0].soldier_id == s1.id
```

- [ ] **Step 2: Run tests — expect failures on new tests**

```bash
pytest backend/app/services/tests/test_enrollment.py -v -k "commander_approved or try_activate"
```

Expected: FAIL — `try_activate` not defined yet, `approve_enrollment` still sets `"approved"` directly.

- [ ] **Step 3: Implement try_activate and update approve_enrollment**

Replace `backend/app/services/enrollment.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import ExemptionRequest, HierarchyNode, Soldier, SoldierEnrollmentRequest


class EnrollmentError(Exception):
    pass


def try_activate(
    session: Session,
    enrollment_request_id: uuid.UUID,
) -> None:
    """Move soldier to requested node if commander has approved and no exemptions are pending."""
    req = session.get(SoldierEnrollmentRequest, enrollment_request_id)
    if req is None or req.status != "commander_approved":
        return
    pending = session.execute(
        select(ExemptionRequest).where(
            ExemptionRequest.enrollment_request_id == enrollment_request_id,
            ExemptionRequest.status == "pending",
        )
    ).scalars().all()
    if pending:
        return
    soldier = session.get(Soldier, req.soldier_id)
    assert soldier is not None
    soldier.hierarchy_node_id = req.requested_node_id
    req.status = "approved"
    session.flush()
    write_audit(session, actor_id=None, action="enrollment.activate",
                entity_type="soldier_enrollment_request", entity_id=req.id,
                after={"soldier_id": str(req.soldier_id), "node_id": str(req.requested_node_id)})
    from app.services.notifications import _create_notif
    from app.db.models import NotificationType
    _create_notif(session, soldier_id=soldier.id,
                  type=NotificationType.enrollment_approved,
                  title="בקשת ההצטרפות שלך אושרה",
                  body=None, reference_type="enrollment_request",
                  reference_id=req.id, actor_id=None)


def approve_enrollment(
    session: Session,
    *,
    request_id: uuid.UUID,
    decider_id: uuid.UUID,
    decision_note: str | None,
) -> SoldierEnrollmentRequest:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise EnrollmentError("enrollment request not found")
    if req.status != "pending":
        raise EnrollmentError("already decided")
    req.status = "commander_approved"
    req.decided_by = decider_id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_note = decision_note
    session.flush()
    write_audit(session, actor_id=decider_id, action="enrollment.commander_approve",
                entity_type="soldier_enrollment_request", entity_id=req.id,
                after={"soldier_id": str(req.soldier_id), "node_id": str(req.requested_node_id)})
    try_activate(session, req.id)
    return req


def reject_enrollment(
    session: Session,
    *,
    request_id: uuid.UUID,
    decider_id: uuid.UUID,
    decision_note: str,
) -> SoldierEnrollmentRequest:
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
    write_audit(session, actor_id=decider_id, action="enrollment.reject",
                entity_type="soldier_enrollment_request", entity_id=req.id,
                after={"decision_note": decision_note})
    from app.services.notifications import _create_notif
    from app.db.models import NotificationType
    soldier = session.get(Soldier, req.soldier_id)
    if soldier:
        _create_notif(session, soldier_id=soldier.id,
                      type=NotificationType.enrollment_rejected,
                      title="בקשת ההצטרפות שלך נדחתה",
                      body=decision_note, reference_type="enrollment_request",
                      reference_id=req.id, actor_id=decider_id)
    return req


def list_pending_for_node_ids(
    session: Session, node_ids: set[uuid.UUID]
) -> list[SoldierEnrollmentRequest]:
    if not node_ids:
        return []
    all_pending = session.execute(
        select(SoldierEnrollmentRequest).where(SoldierEnrollmentRequest.status == "pending")
    ).scalars().all()
    result = []
    for req in all_pending:
        target = session.get(HierarchyNode, req.requested_node_id)
        if target and any(r in target.path_ids for r in node_ids):
            result.append(req)
    return result
```

- [ ] **Step 4: Run tests**

```bash
pytest backend/app/services/tests/test_enrollment.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/enrollment.py backend/app/services/tests/test_enrollment.py
git commit -m "feat: enrollment dual-approval — try_activate and commander_approved status"
```

---

## Task 8: Registration Service — is_career, Link Exemptions, Notify DMs

**Files:**
- Modify: `backend/app/services/registration.py`
- Modify: `backend/app/services/notifications.py`
- Modify: `backend/app/services/tests/test_registration.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/app/services/tests/test_registration.py`:

```python
def test_register_stores_is_career(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()
    soldier = register(
        admin_session, invite_code=invite.code, requested_node_id=node.id,
        exemption_requests=[], personal_constraints=[],
        **_base(is_career=True),
    )
    admin_session.commit()
    assert soldier.is_career is True


def test_register_links_exemptions_to_enrollment(admin_session):
    import sqlalchemy as sa
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.db.models import ExemptionRequest, ExemptionType, SoldierEnrollmentRequest
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    et = ExemptionType(name=f"et_{_uid()}")
    admin_session.add(et)
    admin_session.flush()
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()
    exemption_requests = [{
        "exemption_type_id": et.id,
        "start_date": date(2026, 1, 1),
        "end_date": None,
        "reason": "test",
    }]
    soldier = register(
        admin_session, invite_code=invite.code, requested_node_id=node.id,
        exemption_requests=exemption_requests, personal_constraints=[],
        **_base(),
    )
    admin_session.commit()
    enrollment_req = admin_session.execute(
        sa.select(SoldierEnrollmentRequest).where(SoldierEnrollmentRequest.soldier_id == soldier.id)
    ).scalar_one()
    exemption = admin_session.execute(
        sa.select(ExemptionRequest).where(ExemptionRequest.soldier_id == soldier.id)
    ).scalar_one()
    assert exemption.enrollment_request_id == enrollment_req.id
```

- [ ] **Step 2: Run new tests — expect FAIL**

```bash
pytest backend/app/services/tests/test_registration.py -v -k "is_career or links_exemptions"
```

Expected: FAIL — `is_career` not in `_base()`, `register()` doesn't accept it, no linking.

- [ ] **Step 3: Update `_base()` helper in test file**

In `test_registration.py`, update `_base()` to include `is_career`:

```python
def _base(**overrides):
    return {
        "personal_number": f"pn_{_uid()}",
        "full_name": "Test Soldier",
        "password": "password-secure-1",
        "phone": "050-0000000",
        "gender": "male",
        "is_officer": False,
        "is_career": False,           # ← NEW
        "rank": "טוראי",
        "bahad1_graduate": False,
        "enlistment_date": date(2023, 1, 1),
        "mandatory_end_date": date(2025, 1, 1),
        "discharge_date": date(2026, 1, 1),
        "last_mitvahim_date": None,
        "last_alal_date": None,
        **overrides,
    }
```

- [ ] **Step 4: Add `notify_enrollment_received` to notifications.py**

In `backend/app/services/notifications.py`, add import at top (with existing imports):

```python
from app.db.models import (
    ...,  # existing imports
    DutyManagerScope,
    HierarchyLevelType,
    SoldierEnrollmentRequest,
)
```

Add the function (after `notify_commanders_of_request`):

```python
def notify_enrollment_received(
    session: Session,
    *,
    soldier: Soldier,
    enrollment_req: SoldierEnrollmentRequest,
    has_exemptions: bool,
) -> None:
    """Notify commanders of the requested node and (if exemptions present) eligible DMs."""
    from app.services.settings_loader import get_setting, SettingNotFound

    requested_node = session.get(HierarchyNode, enrollment_req.requested_node_id)
    if not requested_node or not requested_node.path_ids:
        return

    title = f"בקשת הצטרפות: {soldier.full_name}"
    ref_type = "enrollment_request"
    ref_id = enrollment_req.id

    # Notify commanders with scope over any node in the requested node's path
    cmdr_scopes = session.execute(
        select(CommanderNotificationScope).where(
            CommanderNotificationScope.hierarchy_node_id.in_(requested_node.path_ids)
        )
    ).scalars().all()
    seen: set[uuid.UUID] = set()
    for scope in cmdr_scopes:
        if scope.commander_id in seen or scope.commander_id == soldier.id:
            continue
        seen.add(scope.commander_id)
        _create_notif(
            session, soldier_id=scope.commander_id,
            type=NotificationType.enrollment_request_received,
            title=title, body=None,
            reference_type=ref_type, reference_id=ref_id, actor_id=None,
        )

    if not has_exemptions:
        return

    # Notify eligible DMs (scope over path, level rank >= setting)
    try:
        min_rank = int(get_setting(session, "enrollment.min_dm_level_rank"))
    except SettingNotFound:
        min_rank = 0

    dm_scopes = session.execute(
        select(DutyManagerScope).where(
            DutyManagerScope.hierarchy_node_id.in_(requested_node.path_ids)
        )
    ).scalars().all()
    for dm_scope in dm_scopes:
        if dm_scope.duty_manager_id in seen or dm_scope.duty_manager_id == soldier.id:
            continue
        scope_node = session.get(HierarchyNode, dm_scope.hierarchy_node_id)
        if not scope_node:
            continue
        lt = session.execute(
            select(HierarchyLevelType).where(HierarchyLevelType.key == scope_node.level)
        ).scalar_one_or_none()
        if lt is None or lt.rank < min_rank:
            continue
        seen.add(dm_scope.duty_manager_id)
        _create_notif(
            session, soldier_id=dm_scope.duty_manager_id,
            type=NotificationType.enrollment_request_received,
            title=title, body=None,
            reference_type=ref_type, reference_id=ref_id, actor_id=None,
        )
```

- [ ] **Step 5: Update registration.py**

Replace `backend/app/services/registration.py`:

```python
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.db.models import (
    ExemptionRequest,
    HierarchyNode,
    PersonalConstraint,
    Soldier,
    SoldierEnrollmentRequest,
)
from app.services.invite_codes import InviteCodeError, consume_invite_code
from app.services.settings_loader import SettingNotFound, get_setting


class RegistrationError(Exception):
    pass


def register(
    session: Session,
    *,
    invite_code: str,
    personal_number: str,
    full_name: str,
    password: str,
    phone: str | None,
    email: str | None,
    gender: str | None,
    is_officer: bool | None,
    is_career: bool = False,           # ← NEW
    rank: str | None,
    bahad1_graduate: bool,
    enlistment_date: date | None,
    mandatory_end_date: date | None,
    discharge_date: date | None,
    last_mitvahim_date: date | None,
    last_alal_date: date | None,
    requested_node_id: uuid.UUID,
    exemption_requests: list[dict],
    personal_constraints: list[dict],
) -> Soldier:
    consume_invite_code(session, code=invite_code)

    if session.execute(
        select(Soldier.id).where(Soldier.personal_number == personal_number)
    ).first():
        raise RegistrationError("personal_number already exists")

    try:
        holding_node_id = uuid.UUID(get_setting(session, "system.holding_node_id"))
    except SettingNotFound as exc:
        raise RegistrationError("holding node not bootstrapped") from exc

    if session.get(HierarchyNode, holding_node_id) is None:
        raise RegistrationError("holding node not bootstrapped")

    if session.get(HierarchyNode, requested_node_id) is None:
        raise RegistrationError("requested node not found")

    soldier = Soldier(
        personal_number=personal_number,
        full_name=full_name,
        password_hash=hash_password(password),
        role="soldier",
        hierarchy_node_id=holding_node_id,
        phone=phone,
        email=email,
        must_change_password=False,
        gender=gender,
        is_officer=is_officer,
        is_career=is_career,           # ← NEW
        rank=rank,
        bahad1_graduate=bahad1_graduate,
        enlistment_date=enlistment_date,
        mandatory_end_date=mandatory_end_date,
        discharge_date=discharge_date,
        last_mitvahim_date=last_mitvahim_date,
        last_alal_date=last_alal_date,
    )
    session.add(soldier)
    session.flush()

    # Create enrollment request FIRST so exemptions can reference it
    enrollment_req = SoldierEnrollmentRequest(
        soldier_id=soldier.id,
        requested_node_id=requested_node_id,
        status="pending",
    )
    session.add(enrollment_req)
    session.flush()

    for er in exemption_requests:
        session.add(ExemptionRequest(
            soldier_id=soldier.id,
            enrollment_request_id=enrollment_req.id,   # ← NEW
            exemption_type_id=er["exemption_type_id"],
            start_date=er["start_date"],
            end_date=er.get("end_date"),
            reason=er.get("reason"),
            status="pending",
        ))

    for pc in personal_constraints:
        session.add(PersonalConstraint(
            soldier_id=soldier.id,
            start_date=pc["start_date"],
            end_date=pc["end_date"],
            reason=pc["reason"],
            status="pending",
        ))

    session.flush()

    from app.services.notifications import notify_enrollment_received
    notify_enrollment_received(
        session,
        soldier=soldier,
        enrollment_req=enrollment_req,
        has_exemptions=len(exemption_requests) > 0,
    )

    return soldier
```

- [ ] **Step 6: Run all registration + enrollment tests**

```bash
pytest backend/app/services/tests/test_registration.py backend/app/services/tests/test_enrollment.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/registration.py backend/app/services/notifications.py backend/app/services/tests/test_registration.py
git commit -m "feat: registration sends is_career, links exemptions to enrollment, notifies DMs"
```

---

## Task 9: Exemption Requests Service — Call try_activate

**Files:**
- Modify: `backend/app/services/exemption_requests.py`

- [ ] **Step 1: Update `approve_request` and `reject_request`**

In `backend/app/services/exemption_requests.py`, in `approve_request` after `session.flush()` (after creating the `SoldierExemption` and before the `create_notification` call), add:

```python
if req.enrollment_request_id:
    from app.services.enrollment import try_activate
    try_activate(session, req.enrollment_request_id)
```

In `reject_request` after `session.flush()`, add the same block:

```python
if req.enrollment_request_id:
    from app.services.enrollment import try_activate
    try_activate(session, req.enrollment_request_id)
```

- [ ] **Step 2: Run targeted tests**

```bash
pytest backend/app/services/tests/test_enrollment.py -v -k "try_activate"
```

Expected: all pass (try_activate is already tested via enrollment tests; exemption side is integration tested by the route).

- [ ] **Step 3: Run full suite marker**

```bash
pytest -m "enrollment or registration" -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/exemption_requests.py
git commit -m "feat: exemption approve/reject triggers enrollment activation check"
```

---

## Task 10: Enrich Enrollment Routes + PATCH

**Files:**
- Modify: `backend/app/routes/enrollment.py`

- [ ] **Step 1: Rewrite enrollment.py**

Replace `backend/app/routes/enrollment.py`:

```python
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import ExemptionRequest, HierarchyNode, Soldier, SoldierEnrollmentRequest
from app.db.session import get_session
from app.services import enrollment as svc

router = APIRouter(prefix="/enrollment-requests", tags=["enrollment"])


class EnrollmentExemptionOut(BaseModel):
    id: uuid.UUID
    exemption_type_id: uuid.UUID | None
    start_date: str
    end_date: str | None
    reason: str | None
    status: str


class EnrollmentRequestOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str
    soldier_personal_number: str
    requested_node_id: uuid.UUID
    requested_node_name: str | None = None
    status: str
    decided_by: uuid.UUID | None
    decision_note: str | None
    # Soldier profile fields
    phone: str | None = None
    email: str | None = None
    rank: str | None = None
    is_officer: bool | None = None
    is_career: bool = False
    gender: str | None = None
    enlistment_date: str | None = None
    mandatory_end_date: str | None = None
    discharge_date: str | None = None
    last_mitvahim_date: str | None = None
    last_alal_date: str | None = None
    exemption_requests: list[EnrollmentExemptionOut] = []


class DecisionBody(BaseModel):
    decision_note: str | None = None


class PatchEnrollmentBody(BaseModel):
    full_name: str | None = None
    personal_number: str | None = None
    requested_node_id: uuid.UUID | None = None
    phone: str | None = None
    email: str | None = None
    rank: str | None = None
    is_officer: bool | None = None
    is_career: bool | None = None
    gender: str | None = None
    enlistment_date: str | None = None
    mandatory_end_date: str | None = None
    discharge_date: str | None = None
    last_mitvahim_date: str | None = None
    last_alal_date: str | None = None


def _soldier_to_out(r: SoldierEnrollmentRequest, s: Soldier, node_name: str | None, exemptions: list[ExemptionRequest]) -> EnrollmentRequestOut:
    return EnrollmentRequestOut(
        id=r.id, soldier_id=r.soldier_id,
        soldier_name=s.full_name,
        soldier_personal_number=s.personal_number,
        requested_node_id=r.requested_node_id,
        requested_node_name=node_name,
        status=r.status, decided_by=r.decided_by, decision_note=r.decision_note,
        phone=s.phone, email=s.email, rank=s.rank,
        is_officer=s.is_officer, is_career=s.is_career,
        gender=s.gender,
        enlistment_date=s.enlistment_date.isoformat() if s.enlistment_date else None,
        mandatory_end_date=s.mandatory_end_date.isoformat() if s.mandatory_end_date else None,
        discharge_date=s.discharge_date.isoformat() if s.discharge_date else None,
        last_mitvahim_date=s.last_mitvahim_date.isoformat() if s.last_mitvahim_date else None,
        last_alal_date=s.last_alal_date.isoformat() if s.last_alal_date else None,
        exemption_requests=[
            EnrollmentExemptionOut(
                id=er.id,
                exemption_type_id=er.exemption_type_id,
                start_date=er.start_date.isoformat(),
                end_date=er.end_date.isoformat() if er.end_date else None,
                reason=er.reason,
                status=er.status,
            )
            for er in exemptions
        ],
    )


def _load_reqs(session: Session, reqs: list[SoldierEnrollmentRequest]) -> list[EnrollmentRequestOut]:
    soldier_ids = {r.soldier_id for r in reqs}
    soldiers = {
        s.id: s for s in session.execute(select(Soldier).where(Soldier.id.in_(soldier_ids))).scalars().all()
    }
    node_ids = {r.requested_node_id for r in reqs}
    nodes = {
        n.id: n for n in session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))).scalars().all()
    }
    req_ids = [r.id for r in reqs]
    exemptions_by_enrollment: dict[uuid.UUID, list[ExemptionRequest]] = {}
    for er in session.execute(
        select(ExemptionRequest).where(ExemptionRequest.enrollment_request_id.in_(req_ids))
    ).scalars().all():
        exemptions_by_enrollment.setdefault(er.enrollment_request_id, []).append(er)

    result = []
    for r in reqs:
        s = soldiers.get(r.soldier_id)
        if not s:
            continue
        node_name = nodes[r.requested_node_id].name if r.requested_node_id in nodes else None
        result.append(_soldier_to_out(r, s, node_name, exemptions_by_enrollment.get(r.id, [])))
    return result


@router.get("/pending", response_model=list[EnrollmentRequestOut])
def list_pending(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[EnrollmentRequestOut]:
    if user.role == "admin":
        reqs = session.execute(
            select(SoldierEnrollmentRequest).where(SoldierEnrollmentRequest.status == "pending")
        ).scalars().all()
    else:
        roots = scope_root_ids(session, user)
        reqs = svc.list_pending_for_node_ids(session, roots)
    return _load_reqs(session, list(reqs))


@router.patch("/{request_id}", response_model=EnrollmentRequestOut)
def patch_enrollment(
    request_id: uuid.UUID,
    body: PatchEnrollmentBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> EnrollmentRequestOut:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if req.status not in ("pending", "commander_approved"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="already decided")
    target_node = session.get(HierarchyNode, req.requested_node_id)
    authorize(session, user, Action.ENROLLMENT_APPROVE, target_node=target_node)
    s = session.get(Soldier, req.soldier_id)
    assert s is not None
    if body.full_name is not None:
        s.full_name = body.full_name
    if body.personal_number is not None:
        s.personal_number = body.personal_number
    if body.phone is not None:
        s.phone = body.phone or None
    if body.email is not None:
        s.email = body.email or None
    if body.rank is not None:
        s.rank = body.rank or None
    if body.is_officer is not None:
        s.is_officer = body.is_officer
    if body.is_career is not None:
        s.is_career = body.is_career
    if body.gender is not None:
        s.gender = body.gender or None
    if body.enlistment_date is not None:
        s.enlistment_date = date.fromisoformat(body.enlistment_date) if body.enlistment_date else None
    if body.mandatory_end_date is not None:
        s.mandatory_end_date = date.fromisoformat(body.mandatory_end_date) if body.mandatory_end_date else None
    if body.discharge_date is not None:
        s.discharge_date = date.fromisoformat(body.discharge_date) if body.discharge_date else None
    if body.last_mitvahim_date is not None:
        s.last_mitvahim_date = date.fromisoformat(body.last_mitvahim_date) if body.last_mitvahim_date else None
    if body.last_alal_date is not None:
        s.last_alal_date = date.fromisoformat(body.last_alal_date) if body.last_alal_date else None
    if body.requested_node_id is not None:
        if session.get(HierarchyNode, body.requested_node_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node not found")
        req.requested_node_id = body.requested_node_id
    session.flush()
    node_name = session.get(HierarchyNode, req.requested_node_id)
    exemptions = session.execute(
        select(ExemptionRequest).where(ExemptionRequest.enrollment_request_id == req.id)
    ).scalars().all()
    return _soldier_to_out(req, s, node_name.name if node_name else None, list(exemptions))


@router.post("/{request_id}/approve")
def approve(
    request_id: uuid.UUID,
    body: DecisionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    target_node = session.get(HierarchyNode, req.requested_node_id)
    authorize(session, user, Action.ENROLLMENT_APPROVE, target_node=target_node)
    try:
        svc.approve_enrollment(session, request_id=request_id, decider_id=user.id, decision_note=body.decision_note)
        session.commit()
        return {"status": "ok"}
    except svc.EnrollmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{request_id}/reject")
def reject(
    request_id: uuid.UUID,
    body: DecisionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if not body.decision_note:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="decision_note required")
    target_node = session.get(HierarchyNode, req.requested_node_id)
    authorize(session, user, Action.ENROLLMENT_APPROVE, target_node=target_node)
    try:
        svc.reject_enrollment(session, request_id=request_id, decider_id=user.id, decision_note=body.decision_note)
        session.commit()
        return {"status": "ok"}
    except svc.EnrollmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
```

- [ ] **Step 2: Run existing tests**

```bash
pytest -m enrollment -q
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/enrollment.py
git commit -m "feat: enrich enrollment pending list with soldier data; add PATCH /enrollment-requests/{id}"
```

---

## Task 11: Exemption Requests Route — PATCH + DM Level Filter

**Files:**
- Modify: `backend/app/routes/exemption_requests.py`

- [ ] **Step 1: Add `enrollment_request_id` to `ExemptionRequestOut`**

In `exemption_requests.py`, update `ExemptionRequestOut`:

```python
class ExemptionRequestOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str = ""
    node_name: str | None = None
    exemption_type_id: uuid.UUID | None
    start_date: str
    end_date: str | None
    reason: str | None
    status: str
    decided_by: uuid.UUID | None
    decision_note: str | None
    created_at: str
    files: list[ExemptionFileOut] = []
    enrollment_request_id: uuid.UUID | None = None   # ← NEW
```

Update `_out(...)` to include it:

```python
def _out(...) -> ExemptionRequestOut:
    return ExemptionRequestOut(
        ...
        enrollment_request_id=req.enrollment_request_id,   # ← NEW
    )
```

- [ ] **Step 2: Add `PATCH /exemption-requests/{id}`**

Add a `PatchExemptionRequestBody` schema and route in `exemption_requests.py`. Place it before the approve endpoint:

```python
class PatchExemptionRequestBody(BaseModel):
    exemption_type_id: uuid.UUID | None = None
    start_date: str | None = None
    end_date: str | None = None
    reason: str | None = None


@router.patch("/exemption-requests/{request_id}", response_model=ExemptionRequestOut)
def patch_exemption_request(
    request_id: uuid.UUID,
    body: PatchExemptionRequestBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_request_not_found")
    if req.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="exemption_request_not_pending")
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
    if body.exemption_type_id is not None:
        from app.db.models import ExemptionType
        if session.get(ExemptionType, body.exemption_type_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_type_not_found")
        req.exemption_type_id = body.exemption_type_id
    if body.start_date is not None:
        from datetime import date as _date
        req.start_date = _date.fromisoformat(body.start_date)
    if body.end_date is not None:
        from datetime import date as _date
        req.end_date = _date.fromisoformat(body.end_date) if body.end_date else None
    if body.reason is not None:
        req.reason = body.reason or None
    session.flush()
    return _out(req, include_sensitive=True)
```

- [ ] **Step 3: Add DM level-rank filter to `GET /exemption-requests/pending`**

In `get_pending_exemption_requests`, after building the `result` list, add a filter for enrollment-linked exemptions:

At the top of the function, after computing `root_ids`:

```python
# Compute minimum DM level rank for enrollment exemption approval
from app.db.models import DutyManagerScope as _DMS, HierarchyLevelType as _HLT
from app.services.settings_loader import get_setting, SettingNotFound
try:
    min_dm_rank = int(get_setting(session, "enrollment.min_dm_level_rank"))
except SettingNotFound:
    min_dm_rank = 0

# Find the minimum rank of the user's DM scope nodes
user_dm_node_ids = session.execute(
    select(_DMS.hierarchy_node_id).where(_DMS.duty_manager_id == user.id)
).scalars().all()
user_max_scope_rank = 0
for nid in user_dm_node_ids:
    n = session.get(HierarchyNode, nid)
    if n:
        lt = session.execute(select(_HLT).where(_HLT.key == n.level)).scalar_one_or_none()
        if lt and lt.rank > user_max_scope_rank:
            user_max_scope_rank = lt.rank
user_can_see_enrollment_exemptions = (
    user.role == "admin" or user_max_scope_rank >= min_dm_rank
)
```

Then in the result loop, skip enrollment-linked exemptions if the user is not eligible:

```python
for r in reqs:
    if r.enrollment_request_id and not user_can_see_enrollment_exemptions:
        continue
    s = soldiers_by_id.get(r.soldier_id)
    ...
    result.append(_out(r, ..., enrollment_request_id=r.enrollment_request_id))
```

- [ ] **Step 4: Run tests**

```bash
pytest -m "exemptions" -q
```

Expected: all pass (existing exemption tests don't rely on the new filter fields).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/exemption_requests.py
git commit -m "feat: PATCH /exemption-requests/{id} and DM level filter for enrollment exemptions"
```

---

## Task 12: Frontend API Types — Enrollment + Exemptions

**Files:**
- Modify: `frontend/src/api/enrollment.ts`
- Modify: `frontend/src/api/exemptions.ts`

- [ ] **Step 1: Expand `enrollment.ts`**

Replace `frontend/src/api/enrollment.ts`:

```typescript
import { api } from "./client";

export interface EnrollmentExemptionDTO {
  id: string;
  exemption_type_id: string | null;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  status: string;
}

export interface EnrollmentRequestDTO {
  id: string;
  soldier_id: string;
  soldier_name: string;
  soldier_personal_number: string;
  requested_node_id: string;
  requested_node_name: string | null;
  status: string;
  decided_by: string | null;
  decision_note: string | null;
  phone: string | null;
  email: string | null;
  rank: string | null;
  is_officer: boolean | null;
  is_career: boolean;
  gender: string | null;
  enlistment_date: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
  exemption_requests: EnrollmentExemptionDTO[];
}

export async function listPendingEnrollments(): Promise<EnrollmentRequestDTO[]> {
  const r = await api.get<EnrollmentRequestDTO[]>("/enrollment-requests/pending");
  return r.data;
}

export async function approveEnrollment(id: string, decision_note?: string): Promise<void> {
  await api.post(`/enrollment-requests/${id}/approve`, { decision_note: decision_note ?? null });
}

export async function rejectEnrollment(id: string, decision_note: string): Promise<void> {
  await api.post(`/enrollment-requests/${id}/reject`, { decision_note });
}

export async function patchEnrollment(id: string, data: {
  full_name?: string;
  personal_number?: string;
  requested_node_id?: string;
  phone?: string | null;
  email?: string | null;
  rank?: string | null;
  is_officer?: boolean | null;
  is_career?: boolean;
  gender?: string | null;
  enlistment_date?: string | null;
  mandatory_end_date?: string | null;
  discharge_date?: string | null;
  last_mitvahim_date?: string | null;
  last_alal_date?: string | null;
}): Promise<EnrollmentRequestDTO> {
  const r = await api.patch<EnrollmentRequestDTO>(`/enrollment-requests/${id}`, data);
  return r.data;
}
```

- [ ] **Step 2: Add `enrollment_request_id` and PATCH to `exemptions.ts`**

Add to the `ExemptionRequest` interface:

```typescript
export interface ExemptionRequest {
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  exemption_type_id: string | null;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decision_note: string | null;
  created_at: string;
  files: ExemptionFile[];
  enrollment_request_id: string | null;   // ← NEW
}
```

Add the PATCH function:

```typescript
export async function patchExemptionRequest(id: string, data: {
  exemption_type_id?: string;
  start_date?: string;
  end_date?: string | null;
  reason?: string | null;
}): Promise<ExemptionRequest> {
  const r = await api.patch<ExemptionRequest>(`/exemption-requests/${id}`, data);
  return r.data;
}
```

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/enrollment.ts frontend/src/api/exemptions.ts
git commit -m "feat: expand enrollment and exemption API types; add PATCH functions"
```

---

## Task 13: EnrollmentApprovalModal Component

**Files:**
- Create: `frontend/src/components/EnrollmentApprovalModal.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/EnrollmentApprovalModal.tsx`:

```tsx
import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { EnrollmentRequestDTO, patchEnrollment, approveEnrollment, rejectEnrollment } from "../api/enrollment";
import { NodeDTO } from "../api/hierarchy";
import { ExemptionType } from "../api/dutyConfig";
import { sortNodesByTree } from "../utils/sortNodesByTree";
import Combobox from "./Combobox";

interface Props {
  req: EnrollmentRequestDTO;
  nodes: NodeDTO[];
  exemptionTypes: ExemptionType[];
  onClose: () => void;
  onDone: () => void;
}

const RANKS_ENLISTED = ["טוראי","רבט","סמל","סמר","רסל","רסר","רסמ","רסב","רנג","קמא","סגמ"];
const RANKS_OFFICER = ["סגן","קאב","סרן","רסן","סאל","אלמ","תאל","אלוף","רב אלוף"];

export default function EnrollmentApprovalModal({ req, nodes, exemptionTypes, onClose, onDone }: Props) {
  const { t } = useTranslation();

  const [fullName, setFullName] = useState(req.soldier_name);
  const [personalNumber, setPersonalNumber] = useState(req.soldier_personal_number);
  const [requestedNodeId, setRequestedNodeId] = useState(req.requested_node_id);
  const [phone, setPhone] = useState(req.phone ?? "");
  const [email, setEmail] = useState(req.email ?? "");
  const [rank, setRank] = useState(req.rank ?? "");
  const [isOfficer, setIsOfficer] = useState(req.is_officer ?? false);
  const [isCareer, setIsCareer] = useState(req.is_career);
  const [gender, setGender] = useState(req.gender ?? "");
  const [enlistmentDate, setEnlistmentDate] = useState(req.enlistment_date ?? "");
  const [mandatoryEndDate, setMandatoryEndDate] = useState(req.mandatory_end_date ?? "");
  const [dischargeDate, setDischargeDate] = useState(req.discharge_date ?? "");
  const [lastMitvahimDate, setLastMitvahimDate] = useState(req.last_mitvahim_date ?? "");
  const [lastAlalDate, setLastAlalDate] = useState(req.last_alal_date ?? "");
  const [rejectNote, setRejectNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const typeById = Object.fromEntries(exemptionTypes.map(t => [t.id, t.name]));

  async function handleSaveAndApprove(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await patchEnrollment(req.id, {
        full_name: fullName,
        personal_number: personalNumber,
        requested_node_id: requestedNodeId,
        phone: phone || null,
        email: email || null,
        rank: rank || null,
        is_officer: isOfficer,
        is_career: isCareer,
        gender: gender || null,
        enlistment_date: enlistmentDate || null,
        mandatory_end_date: mandatoryEndDate || null,
        discharge_date: dischargeDate || null,
        last_mitvahim_date: lastMitvahimDate || null,
        last_alal_date: lastAlalDate || null,
      });
      await approveEnrollment(req.id);
      onDone();
    } catch {
      setError("שגיאה בשמירה");
    } finally {
      setSaving(false);
    }
  }

  async function handleReject() {
    if (!rejectNote) return;
    setSaving(true);
    try {
      await rejectEnrollment(req.id, rejectNote);
      onDone();
    } catch {
      setError("שגיאה בדחייה");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto"
        dir="rtl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h2 className="font-semibold text-lg">אישור הצטרפות — {req.soldier_name}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
        </div>

        {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

        <form onSubmit={handleSaveAndApprove} className="space-y-3 text-sm">
          <label className="block">
            <span className="text-xs text-gray-500">שם מלא</span>
            <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600" value={fullName} onChange={e => setFullName(e.target.value)} required />
          </label>
          <label className="block">
            <span className="text-xs text-gray-500">מספר אישי</span>
            <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600" value={personalNumber} onChange={e => setPersonalNumber(e.target.value)} required />
          </label>
          <label className="block">
            <span className="text-xs text-gray-500">מסגרת מבוקשת</span>
            <Combobox
              items={sortNodesByTree(nodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
              value={requestedNodeId}
              onChange={setRequestedNodeId}
              placeholder="—"
            />
          </label>
          <label className="block">
            <span className="text-xs text-gray-500">דרגה</span>
            <Combobox
              items={[
                ...RANKS_ENLISTED.map(r => ({ id: r, name: r, group: "חיילים" })),
                ...RANKS_OFFICER.map(r => ({ id: r, name: r, group: "קצינים" })),
              ]}
              value={rank}
              onChange={v => { setRank(v); setIsOfficer(RANKS_OFFICER.includes(v)); }}
              placeholder="בחר"
            />
          </label>
          <div className="flex gap-4">
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={isOfficer} onChange={e => setIsOfficer(e.target.checked)} />
              <span className="text-xs">קצין</span>
            </label>
            {!isOfficer && (
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={isCareer} onChange={e => setIsCareer(e.target.checked)} />
                <span className="text-xs">קבע</span>
              </label>
            )}
          </div>
          <label className="block">
            <span className="text-xs text-gray-500">מגדר</span>
            <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600" value={gender} onChange={e => setGender(e.target.value)}>
              <option value="">—</option>
              <option value="male">זכר</option>
              <option value="female">נקבה</option>
              <option value="other">אחר</option>
            </select>
          </label>
          {[
            ["טלפון", phone, setPhone, "tel"],
            ["אימייל", email, setEmail, "email"],
          ].map(([label, value, setter, type]) => (
            <label key={label as string} className="block">
              <span className="text-xs text-gray-500">{label as string}</span>
              <input type={type as string} className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600" value={value as string} onChange={e => (setter as (v: string) => void)(e.target.value)} />
            </label>
          ))}
          {[
            ["תאריך גיוס", enlistmentDate, setEnlistmentDate],
            ["סיום חובה", mandatoryEndDate, setMandatoryEndDate],
            ["שחרור", dischargeDate, setDischargeDate],
            ["מטווח אחרון", lastMitvahimDate, setLastMitvahimDate],
          ].map(([label, value, setter]) => (
            <label key={label as string} className="block">
              <span className="text-xs text-gray-500">{label as string}</span>
              <input type="date" lang="he" className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600" value={value as string} onChange={e => (setter as (v: string) => void)(e.target.value)} />
            </label>
          ))}
          {(isOfficer || isCareer) && (
            <label className="block">
              <span className="text-xs text-gray-500">אל"ל אחרון</span>
              <input type="date" lang="he" className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600" value={lastAlalDate} onChange={e => setLastAlalDate(e.target.value)} />
            </label>
          )}

          {req.exemption_requests.length > 0 && (
            <div className="border-t dark:border-gray-600 pt-2">
              <p className="text-xs font-medium text-gray-500 mb-1">פטורים מבוקשים (יטופלו ע"י אחראי תורנויות):</p>
              <ul className="space-y-1">
                {req.exemption_requests.map(er => (
                  <li key={er.id} className="text-xs bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-700 rounded px-2 py-1">
                    <span className="font-medium">{er.exemption_type_id ? (typeById[er.exemption_type_id] ?? er.exemption_type_id) : "—"}</span>
                    {" · "}{er.start_date} → {er.end_date ?? "ללא הגבלה"}
                    {er.reason && <span className="text-gray-500"> · {er.reason}</span>}
                    <span className={`mr-2 px-1 rounded text-xs ${er.status === "approved" ? "bg-green-100 text-green-700" : er.status === "rejected" ? "bg-red-100 text-red-700" : "bg-gray-100 text-gray-600"}`}>
                      {er.status === "pending" ? "ממתין" : er.status === "approved" ? "אושר" : "נדחה"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex gap-2 pt-2 border-t dark:border-gray-600">
            <button
              type="submit"
              disabled={saving}
              className="bg-green-600 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50"
            >
              {saving ? "שומר..." : "שמור ואשר"}
            </button>
            <div className="flex gap-1 flex-1">
              <input
                className="border rounded p-1 text-sm flex-1 dark:bg-gray-700 dark:border-gray-600"
                placeholder="סיבת דחייה (חובה)"
                value={rejectNote}
                onChange={e => setRejectNote(e.target.value)}
              />
              <button
                type="button"
                disabled={!rejectNote || saving}
                onClick={handleReject}
                className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
              >
                דחה
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/EnrollmentApprovalModal.tsx
git commit -m "feat: EnrollmentApprovalModal for commander enrollment review with edit capability"
```

---

## Task 14: ApprovalsPage — Wire Up Enrollment Modal + Exemption Editing

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`

- [ ] **Step 1: Import new dependencies**

At the top of `ApprovalsPage.tsx`, add:

```typescript
import { NodeDTO, fetchTree } from "../api/hierarchy";
import { ExemptionType, listExemptionTypes } from "../api/dutyConfig";
import { patchExemptionRequest } from "../api/exemptions";
import EnrollmentApprovalModal from "../components/EnrollmentApprovalModal";
```

- [ ] **Step 2: Add state for modal, nodes, exemption types, and exemption edits**

Inside `ApprovalsPage` component, add:

```typescript
const [selectedEnroll, setSelectedEnroll] = useState<EnrollmentRequestDTO | null>(null);
const [nodes, setNodes] = useState<NodeDTO[]>([]);
const [exemptionTypes, setExemptionTypes] = useState<ExemptionType[]>([]);
// Per-exemption-request local edits (keyed by exemption request id)
const [erEdits, setErEdits] = useState<Record<string, {
  exemption_type_id?: string;
  start_date?: string;
  end_date?: string | null;
  reason?: string | null;
}>>({});
```

Load nodes and exemption types once:

```typescript
useEffect(() => {
  void fetchTree().then(setNodes).catch(() => {});
  void listExemptionTypes().then(setExemptionTypes).catch(() => {});
}, []);
```

- [ ] **Step 3: Replace enrollment tab content**

Replace the `{tab === "enrollment" && ...}` block with:

```tsx
{tab === "enrollment" && (
  <div className="space-y-3" dir="rtl">
    {enrollItems.length === 0 && <p className="text-gray-500 text-sm">{t("enrollment.none")}</p>}
    {enrollItems.map(req => (
      <div
        key={req.id}
        className="border rounded p-3 text-sm space-y-1 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700"
        onClick={() => setSelectedEnroll(req)}
      >
        <div className="flex items-center gap-2">
          <strong>{req.soldier_name}</strong>
          <span className="text-xs text-gray-400">מ"א {req.soldier_personal_number}</span>
        </div>
        <p className="text-gray-500 text-xs">{t("enrollment.requested_node")}: {req.requested_node_name ?? req.requested_node_id.slice(0, 8)}</p>
        {req.exemption_requests.length > 0 && (
          <p className="text-xs text-amber-600">פטורים: {req.exemption_requests.length} (ממתינים לאחראי תורנויות)</p>
        )}
        <p className="text-xs text-indigo-600 dark:text-indigo-400">לחץ לפתיחה ועריכה</p>
      </div>
    ))}
    {selectedEnroll && (
      <EnrollmentApprovalModal
        req={selectedEnroll}
        nodes={nodes}
        exemptionTypes={exemptionTypes}
        onClose={() => setSelectedEnroll(null)}
        onDone={() => { setSelectedEnroll(null); void refresh(); }}
      />
    )}
  </div>
)}
```

- [ ] **Step 4: Add inline edit fields to exemption requests tab**

In the `{tab === "exemptions" && ...}` block, for each `er` in `erItems`, add edit fields above the approve/reject buttons. After the files section and before the action buttons, add:

```tsx
{er.enrollment_request_id && (
  <div className="mb-2 space-y-1 border-t dark:border-gray-600 pt-2">
    <p className="text-xs text-amber-600 font-medium">פטור מהרשמה — ניתן לעריכה לפני אישור</p>
    <Combobox
      items={exemptionTypes.map(t => ({ id: t.id, name: t.name }))}
      value={erEdits[er.id]?.exemption_type_id ?? er.exemption_type_id ?? ""}
      onChange={v => setErEdits(prev => ({ ...prev, [er.id]: { ...prev[er.id], exemption_type_id: v } }))}
      placeholder="סוג פטור"
    />
    <div className="flex gap-1">
      <input type="date" lang="he" className="border rounded p-1 text-xs dark:bg-gray-700 dark:border-gray-600"
        value={erEdits[er.id]?.start_date ?? er.start_date}
        onChange={e => setErEdits(prev => ({ ...prev, [er.id]: { ...prev[er.id], start_date: e.target.value } }))}
      />
      <input type="date" lang="he" className="border rounded p-1 text-xs dark:bg-gray-700 dark:border-gray-600"
        value={erEdits[er.id]?.end_date ?? er.end_date ?? ""}
        onChange={e => setErEdits(prev => ({ ...prev, [er.id]: { ...prev[er.id], end_date: e.target.value || null } }))}
      />
    </div>
    <input className="border rounded p-1 text-xs w-full dark:bg-gray-700 dark:border-gray-600"
      placeholder="סיבה"
      value={erEdits[er.id]?.reason ?? er.reason ?? ""}
      onChange={e => setErEdits(prev => ({ ...prev, [er.id]: { ...prev[er.id], reason: e.target.value } }))}
    />
  </div>
)}
```

Update `onErApprove` to save edits first:

```typescript
async function onErApprove(id: string) {
  const edits = erEdits[id];
  if (edits && Object.keys(edits).length > 0) {
    await patchExemptionRequest(id, edits);
  }
  await approveExemptionRequest(id);
  await refresh();
}
```

Also add `Combobox` import at the top:

```typescript
import Combobox from "../components/Combobox";
```

- [ ] **Step 5: Run typecheck + lint**

```bash
cd frontend && npm run typecheck && npm run lint
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx
git commit -m "feat: enrollment approval modal with edit; exemption inline editing in ApprovalsPage"
```

---

## Task 15: Update Backend auth.py for is_career in RegisterPayload

**Files:**
- Modify: `backend/app/routes/auth.py`

- [ ] **Step 1: Add `is_career` to `RegisterRequest` schema and call**

In `auth.py`, find `RegisterRequest` (or equivalent registration body class) and add `is_career: bool = False`. Then pass it to `reg_svc.register(...)`. Also ensure the `PublicExemptionTypeOut` and endpoint from Task 5 are already in this file.

Search for the class — it will look something like:

```python
class RegisterRequest(BaseModel):
    invite_code: str
    personal_number: str
    full_name: str
    password: str
    phone: str | None = None
    email: str | None = None
    gender: str | None = None
    is_officer: bool | None = None
    is_career: bool = False            # ← ADD THIS
    rank: str | None = None
    ...
```

And in the `/auth/register` route handler, add `is_career=body.is_career` to the `reg_svc.register(...)` call.

- [ ] **Step 2: Run registration tests**

```bash
pytest backend/app/services/tests/test_registration.py -v
```

Expected: all pass.

- [ ] **Step 3: Run full test suite**

```bash
pytest -q
```

Expected: all pass (or existing known failures only).

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/auth.py
git commit -m "feat: pass is_career through registration route"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task covering it |
|---|---|
| `enrollment_request_id` FK on ExemptionRequest | Task 4 |
| `is_career` on Soldier | Task 4 |
| `commander_approved` status + `try_activate` | Task 7 |
| `try_activate` called from exemption approve/reject | Task 9 |
| Registration links exemptions to enrollment | Task 8 |
| Registration stores `is_career` | Task 8 |
| Notify commanders + eligible DMs at registration | Task 8 |
| `enrollment.min_dm_level_rank` setting used in filter | Task 11 |
| Public `GET /auth/exemption-types` | Task 5 |
| Expose `is_career` in `/me` | Task 3 |
| `PATCH /enrollment-requests/{id}` | Task 10 |
| `PATCH /exemption-requests/{id}` | Task 11 |
| `GET /enrollment-requests/pending` enriched with soldier data | Task 10 |
| DM level-rank filter in `GET /exemption-requests/pending` | Task 11 |
| Fix dismiss button permissions | Task 1 |
| Fix edit soldier single click | Task 2 |
| Fix ALAL alert for relevant soldiers only | Task 3 |
| Exemption type Combobox in RegisterPage | Task 6 |
| `EnrollmentApprovalModal` for commander | Task 13 |
| Exemption inline editing in ApprovalsPage | Task 14 |
| `is_career` in registration payload | Task 6 + Task 15 |

**Placeholder scan:** No TBDs. All code blocks are complete.

**Type consistency:**
- `EnrollmentRequestDTO.exemption_requests` → `EnrollmentExemptionDTO[]` — matches backend `EnrollmentExemptionOut`
- `try_activate(session, enrollment_request_id: uuid.UUID)` — called consistently in Tasks 7, 9
- `notify_enrollment_received(session, soldier=..., enrollment_req=..., has_exemptions=...)` — matches definition in Task 8 and call in registration
- `_create_notif` is a private function in `notifications.py` — already imported via `from app.services.notifications import _create_notif` in Task 7; acceptable for internal use
- `patchEnrollment` returns `EnrollmentRequestDTO` — matches backend `EnrollmentRequestOut` shape
