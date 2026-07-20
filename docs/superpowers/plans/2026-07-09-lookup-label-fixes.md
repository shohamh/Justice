# Lookup Label Display Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two display bugs: (1) soldiers' own duty entries show a generic "תורנות" label instead of the real duty type name because the lookup endpoint 403s for non-managers, and (2) the exemption type is never shown on the exemption-request approval row even though the data and a lookup table are already available.

**Architecture:** (1) is a backend permission fix — `GET /duty-config/duty-types` moves from manager-only to any authenticated user, matching the existing precedent already used for `GET /duty-config/exemption-types`. (2) is a frontend-only fix — `ApprovalsPage.tsx` already loads an `exemptionTypes` id→name lookup for a different modal but never renders it on the exemption-request approval list; wire it in.

**Tech Stack:** FastAPI (backend); React, TypeScript (frontend).

## Global Constraints

- None beyond matching the existing `exemption-types` read-access precedent (`backend/app/routes/duty_config.py:380-386`).

---

### Task 1: Open duty-type listing to any authenticated soldier

**Files:**
- Modify: `backend/app/routes/duty_config.py`
- Test: `backend/tests/integration/test_duty_config_api.py`

**Interfaces:**
- Changes `GET /duty-config/duty-types` from `Depends(require_config_manager)` to `Depends(require_password_changed)`. No other duty-config endpoint changes — create/update/delete stay on `require_config_manager`.

- [ ] **Step 1: Write the failing test**

Check the existing file's fixtures first: `grep -n "^def test_\|^from\|^import" backend/tests/integration/test_duty_config_api.py | head -20`. Append a test matching its conventions:

```python
def test_plain_soldier_can_list_duty_types(client, admin_session):
    from tests.helpers import create_soldier, auth_headers
    from app.db.models import DutyType

    dt = DutyType(name="plain_soldier_read_test", score_per_day=1)
    admin_session.add(dt)
    admin_session.commit()

    s = create_soldier(admin_session, personal_number="7800001")
    r = client.get("/api/duty-config/duty-types", headers=auth_headers(s))
    assert r.status_code == 200
    assert any(d["name"] == "plain_soldier_read_test" for d in r.json())


def test_plain_soldier_cannot_create_duty_type(client, admin_session):
    from tests.helpers import create_soldier, auth_headers

    s = create_soldier(admin_session, personal_number="7800002")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(s),
        json={"name": "should_not_be_allowed", "score_per_day": "1"},
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_duty_config_api.py -k "plain_soldier" -v`
Expected: `test_plain_soldier_can_list_duty_types` FAILS with 403 (current gating); `test_plain_soldier_cannot_create_duty_type` already passes.

- [ ] **Step 3: Change the dependency**

In `backend/app/routes/duty_config.py`, change `list_duty_types` (line 116-120):

```python
@router.get("/duty-types", response_model=list[DutyTypeOut])
def list_duty_types(
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed)
) -> list[DutyTypeOut]:
    # Reference data: any authenticated (password-changed) user may list duty-type
    # names/details, same precedent as list_exemption_types below. Mutations stay
    # gated behind require_config_manager.
    return [_dt_out(d) for d in session.execute(select(DutyType)).scalars().all()]
```

(`require_password_changed` is already imported at the top of the file, line 15 — no import changes needed.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_duty_config_api.py -v`
Expected: all passed

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && pytest -q`
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/duty_config.py backend/tests/integration/test_duty_config_api.py
git commit -m "fix: allow any authenticated soldier to list duty types"
```

- [ ] **Step 7: Manually verify in the browser**

Log in as a plain soldier, open the home dashboard, and confirm their own duty entries now show the real duty type name instead of the generic "תורנות" fallback.

---

### Task 2: Show exemption type on the exemption-request approval row

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`

**Interfaces:**
- Consumes: `ExemptionRequest.exemption_type_id` (already present, `frontend/src/api/exemptions.ts`) and the page's existing `exemptionTypes: { id: string; name: string }[]` state (line 90).

- [ ] **Step 1: Confirm the data is present but unused**

Run: `grep -n "exemption_type_id" frontend/src/api/exemptions.ts` — confirm the `ExemptionRequest` interface already has `exemption_type_id: string | null`. Run: `grep -n "exemption_type_id" frontend/src/pages/ApprovalsPage.tsx` — confirm it currently only appears in the import type, never rendered in the `tab === "exemptions"` block (lines 347-417).

- [ ] **Step 2: Add the display**

In `frontend/src/pages/ApprovalsPage.tsx`, inside the exemption-request row (right after the `<div className="flex items-center gap-2 mb-1">...soldier link...</div>` block, before the `<p className="text-xs text-gray-500 mb-1" ...>` stage line, around line 358), add:

```tsx
                  <p className="text-sm font-medium mb-1">
                    {exemptionTypes.find(et => et.id === er.exemption_type_id)?.name ?? t("exemptions.unknown_type")}
                  </p>
```

- [ ] **Step 3: Add the missing translation key**

Check `grep -rl "exemptions.forever" frontend/src/i18n/` to find the Hebrew locale file (already referenced a few lines below at `t("exemptions.forever")`), and add next to it:

```json
"exemptions.unknown_type": "סוג פטור לא ידוע"
```

- [ ] **Step 4: Manually verify in the browser**

As a commander with a pending exemption request to approve, open `/approvals` → exemptions tab, and confirm each row now shows the exemption type name above the date range.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx frontend/src/i18n/
git commit -m "fix: show exemption type name on the exemption-request approval row"
```
