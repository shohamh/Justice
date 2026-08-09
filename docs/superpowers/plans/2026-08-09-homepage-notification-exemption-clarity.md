# Homepage/Notification/Exemption Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close four small, independent UX gaps: homepage reserve/primary/called-up clarity, detailed exemption-decision notifications, a permanent-exemption checkbox, and real approve/reject buttons on the two notification types with a simple binary decision.

**Architecture:** Backend changes are additive (new nullable columns/fields, richer notification text, one new manager-facing notification) — no existing behavior changes. Frontend changes touch four independent components (`UpcomingDutiesWidget`, `MyRequestsPage`, `NotificationBell`, `NotificationsPage`) that don't share state.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React + TypeScript + Vitest + Testing Library (frontend), Hebrew UI strings live in `frontend/src/i18n/he.json`.

## Global Constraints

- Hebrew UI, English code — all user-facing strings go through `t("...")` and `frontend/src/i18n/he.json`; never hardcode Hebrew literals outside i18n except where the existing code already does so (match surrounding style).
- No schema-breaking changes — every new column is nullable with a safe default; no backfill required.
- Follow existing patterns exactly: `create_notification`/`notify_duty_managers_in_scope` call signatures, `_out()` mapping style in routes, Vitest/`vi.mock` conventions already used in `NotificationBell.test.tsx`.
- `pytest -q` (backend) and `npm test` (frontend) must stay green after every task.

---

### Task 1: Surface `called_up_from`/`called_up_to` on effective duties

**Files:**
- Modify: `backend/app/services/scoring.py:146-163` (`effective_duty_spans` → `_make_span`)
- Modify: `backend/app/routes/assignments.py:55-70` (`EffectiveDutyOut`)
- Test: `backend/tests/integration/test_assignments_routes.py` (or the existing file covering `GET /assignments/effective` — search for `effective` in `backend/tests/integration/` to find the right file first)

**Interfaces:**
- Produces: `EffectiveDutyOut.called_up_from: date | None`, `EffectiveDutyOut.called_up_to: date | None` — consumed by Task 2's frontend type.

- [ ] **Step 1: Write the failing backend test**

Find the existing test file that covers `GET /assignments/effective` (grep for `"/assignments/effective"` under `backend/tests/integration/`). Add a test asserting the new fields round-trip:

```python
def test_effective_duties_includes_called_up_window(client, admin_session, soldier_factory, duty_type_factory, duty_location_factory):
    soldier = soldier_factory()
    dt = duty_type_factory()
    loc = duty_location_factory()
    resp = client.post("/assignments", json={
        "soldier_id": str(soldier.id), "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": "2026-09-01", "end_date": "2026-09-02", "is_reserve": True,
    }, headers=admin_session)
    assignment_id = resp.json()["id"]
    # directly set called_up_from/to via the DB session fixture, since there's
    # no dedicated "call up" endpoint exercised here — mirror how other tests
    # in this file set fields not reachable via a route.
    from app.db.models import DutyAssignment
    with client.app.dependency_overrides[get_session_dep_used_in_this_file]() as session:  # match this file's existing session-access pattern
        a = session.get(DutyAssignment, assignment_id)
        a.status = "published"
        a.called_up_from = date(2026, 9, 1)
        a.called_up_to = date(2026, 9, 2)
        session.commit()

    resp = client.get("/assignments/effective", params={"soldier_id": str(soldier.id)}, headers=admin_session)
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["assignment_id"] == assignment_id)
    assert row["called_up_from"] == "2026-09-01"
    assert row["called_up_to"] == "2026-09-02"
```

Before writing this for real, open the existing test file covering this route and copy its actual fixture/session-access idioms (factory names, how tests set a published status, how the DB session is reached from a test) — the snippet above uses placeholder fixture names (`soldier_factory`, `duty_type_factory`, `duty_location_factory`, `get_session_dep_used_in_this_file`) that must be replaced with whatever the file already uses.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/integration/<file> -k called_up_window -v`
Expected: FAIL — `KeyError: 'called_up_from'` (field not yet in response).

- [ ] **Step 3: Add the fields**

In `backend/app/routes/assignments.py`, extend `EffectiveDutyOut`:

```python
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
    called_up_from: date | None = None
    called_up_to: date | None = None
    weapon_ineligible: bool = False
    weapon_ineligible_reason: str | None = None
```

In `backend/app/services/scoring.py`, inside `_make_span` (around line 146), add the two fields to the returned dict, right after `"is_reserve": a.is_reserve,`:

```python
                "is_reserve": a.is_reserve,
                "called_up_from": a.called_up_from,
                "called_up_to": a.called_up_to,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/integration/<file> -k called_up_window -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/assignments.py backend/app/services/scoring.py backend/tests/integration/<file>
git commit -m "feat: surface called_up_from/to on effective duty spans"
```

---

### Task 2: Restyle `UpcomingDutiesWidget` for reserve/primary/called-up clarity

**Files:**
- Modify: `frontend/src/api/assignments.ts:16-32` (`EffectiveDuty`)
- Modify: `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx`
- Modify: `frontend/src/i18n/he.json` (reuse existing `reserve_called_up`/`called_up_from_to` keys; add one new key `home.duty_primary` if not present)
- Test: `frontend/src/components/dashboard/UpcomingDutiesWidget.test.tsx` (create if it doesn't exist yet — check first)

**Interfaces:**
- Consumes: `EffectiveDuty.called_up_from: string | null`, `EffectiveDuty.called_up_to: string | null` (Task 1's backend fields, ISO date strings over the wire).
- Produces: no new exports — this is a leaf UI component.

- [ ] **Step 1: Write the failing test**

Check whether `frontend/src/components/dashboard/UpcomingDutiesWidget.test.tsx` already exists. If not, create it:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import UpcomingDutiesWidget from "./UpcomingDutiesWidget";
import type { EffectiveDuty } from "../../api/assignments";

function makeDuty(overrides: Partial<EffectiveDuty> = {}): EffectiveDuty {
  return {
    assignment_id: "a1", soldier_id: "s1", duty_type_id: "dt1", duty_type_name: "שמירה",
    duty_location_id: "loc1", start_date: "2099-01-01", end_date: "2099-01-02",
    start_time: "22:00", end_time: "06:00", start_at: "2099-01-01T22:00:00",
    end_at: "2099-01-02T06:00:00", shift_id: null, is_reserve: false,
    called_up_from: null, called_up_to: null,
    weapon_ineligible: false, weapon_ineligible_reason: null,
    ...overrides,
  };
}

describe("UpcomingDutiesWidget", () => {
  it("labels a primary duty as ראשי", () => {
    render(
      <UpcomingDutiesWidget duties={[makeDuty()]} typeNames={{ dt1: "שמירה" }} locationNames={{ loc1: "שער" }} onOpenDuty={vi.fn()} />,
    );
    expect(screen.getByText("ראשי")).toBeInTheDocument();
  });

  it("labels a reserve duty as רזרבה", () => {
    render(
      <UpcomingDutiesWidget duties={[makeDuty({ is_reserve: true })]} typeNames={{ dt1: "שמירה" }} locationNames={{ loc1: "שער" }} onOpenDuty={vi.fn()} />,
    );
    expect(screen.getByText("רזרבה")).toBeInTheDocument();
  });

  it("labels a called-up reserve duty as הוקפץ instead of רזרבה", () => {
    render(
      <UpcomingDutiesWidget
        duties={[makeDuty({ is_reserve: true, called_up_from: "2099-01-01", called_up_to: "2099-01-02" })]}
        typeNames={{ dt1: "שמירה" }} locationNames={{ loc1: "שער" }} onOpenDuty={vi.fn()}
      />,
    );
    expect(screen.queryByText("רזרבה")).not.toBeInTheDocument();
    expect(screen.getByText(/הוקפץ/)).toBeInTheDocument();
  });

  it("does not show any assigned/required headcount", () => {
    render(
      <UpcomingDutiesWidget duties={[makeDuty()]} typeNames={{ dt1: "שמירה" }} locationNames={{ loc1: "שער" }} onOpenDuty={vi.fn()} />,
    );
    expect(screen.queryByText(/\d\/\d/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- UpcomingDutiesWidget -t "labels a primary duty"` (from `frontend/`)
Expected: FAIL — no element with text "ראשי" exists yet (current widget only ever renders a "רזרבה" badge, never a primary label).

- [ ] **Step 3: Add the fields and restyle the widget**

In `frontend/src/api/assignments.ts`, extend `EffectiveDuty`:

```ts
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
  called_up_from: string | null;
  called_up_to: string | null;
  weapon_ineligible: boolean;
  weapon_ineligible_reason: string | null;
}
```

Rewrite `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx` to render blocks instead of table rows:

```tsx
import { EffectiveDuty } from "../../api/assignments";
import { formatDutyRange } from "../../utils/formatDate";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
  locationNames: Record<string, string>;
  onOpenDuty: (duty: EffectiveDuty) => void;
}

function statusLabel(d: EffectiveDuty): { text: string; calledUp: boolean } {
  if (d.is_reserve && d.called_up_from) {
    const range = d.called_up_from === d.called_up_to
      ? d.called_up_from
      : `${d.called_up_from}–${d.called_up_to}`;
    return { text: `הוקפץ ${range}`, calledUp: true };
  }
  return { text: d.is_reserve ? "רזרבה" : "ראשי", calledUp: false };
}

export default function UpcomingDutiesWidget({ duties, typeNames, locationNames, onOpenDuty }: Props) {
  const today = new Date().toISOString().split("T")[0];
  const upcoming = duties
    .filter((d) => d.end_date > today)
    .sort((a, b) => a.start_date.localeCompare(b.start_date));

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">תורנויות קרובות</h2>
      {upcoming.length === 0 ? (
        <p className="text-sm text-gray-500">אין תורנויות קרובות</p>
      ) : (
        <div className="space-y-2">
          {upcoming.map((d) => {
            const status = statusLabel(d);
            return (
              <div
                key={d.assignment_id}
                role="button"
                tabIndex={0}
                className={`rounded-lg p-3 cursor-pointer transition ${
                  d.is_reserve
                    ? "border-2 border-dashed border-amber-400 dark:border-amber-500 bg-amber-50/50 dark:bg-amber-900/20 hover:bg-amber-50/80 dark:hover:bg-amber-900/30"
                    : "border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700/60 hover:bg-gray-100 dark:hover:bg-gray-700"
                }`}
                onClick={() => onOpenDuty(d)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onOpenDuty(d);
                  }
                }}
                title="פתח פרטים"
              >
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-medium text-sm">{typeNames[d.duty_type_id] ?? "—"}</div>
                    <div className={`text-xs mt-0.5 ${status.calledUp ? "text-amber-700 dark:text-amber-400 font-medium" : "text-gray-500 dark:text-gray-400"}`}>
                      {status.text}
                    </div>
                  </div>
                  <span className="text-gray-400 text-xs">›</span>
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {formatDutyRange(d.start_date, d.end_date)} · {locationNames[d.duty_location_id] ?? "—"}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Run all four tests to verify they pass**

Run: `npm test -- UpcomingDutiesWidget` (from `frontend/`)
Expected: PASS (all 4 tests)

- [ ] **Step 5: Run the existing HomePage test suite to check for regressions**

Run: `npm test -- HomePage` (from `frontend/`)
Expected: PASS — if `HomePage.test.tsx` asserts on the old table structure (`<table>`, `<th>סוג</th>`, etc.), update those assertions to match the new block layout rather than changing behavior back.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/assignments.ts frontend/src/components/dashboard/UpcomingDutiesWidget.tsx frontend/src/components/dashboard/UpcomingDutiesWidget.test.tsx
git commit -m "feat: restyle homepage duty widget for reserve/primary/called-up clarity"
```

---

### Task 3: Enrich exemption-decision notification titles and bodies

**Files:**
- Modify: `backend/app/services/exemption_requests.py:177-238` (`approve_duty_manager_step`, `reject_request`)
- Modify: `backend/app/services/exemptions.py:17-198` (`grant_exemption`, `grant_commander_exemption`, `revoke_exemption`)
- Test: `backend/app/services/tests/test_exemption_requests.py` (or wherever `reject_request`/`approve_duty_manager_step` are currently tested — search first) and `backend/app/services/tests/test_exemptions.py`

**Interfaces:**
- No new functions — this task only changes the `title`/`body` string content passed to the existing `create_notification` calls in these four functions.

- [ ] **Step 1: Write the failing tests**

In the test file covering `exemption_requests.py` (find via `grep -rn "def test.*reject_request\|def test.*approve_duty_manager_step" backend/app/services/tests/`), add:

```python
def test_reject_request_notification_includes_type_name_and_dates(app_session, exemption_type_factory, exemption_request_factory, soldier_factory):
    et = exemption_type_factory(name="חופשה")
    decider = soldier_factory()
    req = exemption_request_factory(
        exemption_type_id=et.id, start_date=date(2026, 8, 10), end_date=date(2026, 8, 15),
        status="pending_duty_manager",
    )
    svc.reject_request(app_session, request_id=req.id, decided_by=decider.id, decision_note="לא מספיק ימי חופשה")
    notif = app_session.execute(
        select(Notification).where(Notification.reference_id == req.id, Notification.type == NotificationType.exemption_rejected)
    ).scalar_one()
    assert "חופשה" in notif.title
    assert "2026-08-10" in notif.title and "2026-08-15" in notif.title
    assert notif.body == "לא מספיק ימי חופשה"


def test_reject_request_notification_marks_permanent_exemption(app_session, exemption_type_factory, exemption_request_factory, soldier_factory):
    et = exemption_type_factory(name="רפואי")
    decider = soldier_factory()
    req = exemption_request_factory(exemption_type_id=et.id, start_date=date(2026, 8, 10), end_date=None, status="pending_duty_manager")
    svc.reject_request(app_session, request_id=req.id, decided_by=decider.id)
    notif = app_session.execute(
        select(Notification).where(Notification.reference_id == req.id, Notification.type == NotificationType.exemption_rejected)
    ).scalar_one()
    assert "קבוע" in notif.title


def test_approve_duty_manager_step_notification_includes_type_name_and_dates(app_session, exemption_type_factory, exemption_request_factory, soldier_factory):
    et = exemption_type_factory(name="אישי")
    decider = soldier_factory()
    req = exemption_request_factory(exemption_type_id=et.id, start_date=date(2026, 9, 1), end_date=date(2026, 9, 3), status="pending_duty_manager")
    svc.approve_duty_manager_step(app_session, request_id=req.id, decided_by=decider.id)
    notif = app_session.execute(
        select(Notification).where(Notification.reference_id == req.id, Notification.type == NotificationType.exemption_approved)
    ).scalar_one()
    assert "אישי" in notif.title
    assert "2026-09-01" in notif.title and "2026-09-03" in notif.title
```

Replace `exemption_type_factory`/`exemption_request_factory`/`soldier_factory` with whatever fixtures the existing test file actually uses (check the file first — the codebase's `tests/` conftest pattern should already have equivalents; do not invent new fixture names without checking).

In the test file covering `exemptions.py`, add analogous tests for `grant_exemption`, `grant_commander_exemption`, and `revoke_exemption` titles including the exemption type name.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_exemption_requests.py -k "notification" -v`
Expected: FAIL — titles are still the static strings ("בקשת הפטור נדחתה" without type/dates).

- [ ] **Step 3: Add a shared period-formatting helper and enrich the four call sites**

In `backend/app/services/exemption_requests.py`, add near the top (after imports):

```python
def _format_exemption_period(start_date: date, end_date: date | None) -> str:
    if end_date is None:
        return "קבוע"
    return f"{start_date.isoformat()}–{end_date.isoformat()}"
```

Update `reject_request` (around line 214-238):

```python
def reject_request(
    session: Session,
    request_id: uuid.UUID,
    decided_by: uuid.UUID,
    decision_note: str | None = None,
) -> ExemptionRequest:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise ExemptionRequestError("exemption_request_not_found")
    if req.status not in ("pending_commander", "pending_duty_manager"):
        raise ExemptionRequestError("exemption_request_not_pending")

    req.status = "rejected"
    req.decided_by = decided_by
    req.decision_note = decision_note
    session.flush()
    et = session.get(ExemptionType, req.exemption_type_id)
    type_name = et.name if et else "פטור"
    period = _format_exemption_period(req.start_date, req.end_date)
    create_notification(session, soldier_id=req.soldier_id,
                        type=NotificationType.exemption_rejected,
                        title=f"בקשת הפטור נדחתה — {type_name}, {period}",
                        body=decision_note,
                        reference_type="exemption_request", reference_id=req.id,
                        actor_id=decided_by)
    if req.enrollment_request_id:
        from app.services.enrollment import try_activate
        try_activate(session, req.enrollment_request_id)
    return req
```

Update `approve_duty_manager_step` (around line 177-211) the same way:

```python
    et = session.get(ExemptionType, req.exemption_type_id)
    type_name = et.name if et else "פטור"
    period = _format_exemption_period(req.start_date, req.end_date)
    create_notification(session, soldier_id=req.soldier_id,
                        type=NotificationType.exemption_approved,
                        title=f"בקשת הפטור אושרה — {type_name}, {period}",
                        reference_type="exemption_request", reference_id=req.id,
                        actor_id=decided_by)
```

(place this right after `session.flush()`, before the existing `create_notification` call it replaces).

Add `ExemptionType` to the imports at the top of `exemption_requests.py` if not already imported (check current import block first).

In `backend/app/services/exemptions.py`, import the same helper (or duplicate the two-line function locally — it's small enough that a local copy avoids a cross-module import; match whichever the codebase's existing conventions favor for two-line helpers shared between two service files, defaulting to a local copy if unsure) and update the three notification titles:

- `grant_exemption` (line 62-69): `et` is already loaded at line 32 — change `title="ניתן לך פטור"` to `title=f"ניתן לך פטור — {et.name}, {_format_exemption_period(start_date, end_date)}"`.
- `grant_commander_exemption` (line 123-130): `et` is already loaded at line 91 — same pattern with `title=f"ניתן לך פטור מפקדתי — {et.name}, {_format_exemption_period(start_date, end_date)}"`.
- `revoke_exemption` (line 182-189): load `et = session.get(ExemptionType, ex.exemption_type_id)` right after loading `ex` (line 152), then `title=f"פטור בוטל — {et.name if et else 'פטור'}, {_format_exemption_period(ex.start_date, ex.end_date)}"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_exemption_requests.py backend/app/services/tests/test_exemptions.py -k "notification" -v`
Expected: PASS

- [ ] **Step 5: Run the full backend test suite for these two files to check for regressions**

Run: `pytest backend/app/services/tests/test_exemption_requests.py backend/app/services/tests/test_exemptions.py -v`
Expected: PASS — any existing test asserting the old static title text must be updated to match the new enriched title (this is an intentional, expected change, not a regression).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/exemption_requests.py backend/app/services/exemptions.py backend/app/services/tests/test_exemption_requests.py backend/app/services/tests/test_exemptions.py
git commit -m "feat: enrich exemption decision notifications with type name and date range"
```

---

### Task 4: Permanent-exemption checkbox in the request form

**Files:**
- Modify: `frontend/src/pages/MyRequestsPage.tsx`
- Modify: `frontend/src/i18n/he.json` (add `exemption_requests.permanent` key)
- Test: `frontend/src/pages/MyRequestsPage.test.tsx`

**Interfaces:**
- No new exports — purely internal component state (`erPermanent`) mapped to the existing `submitExemptionRequest` payload.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/MyRequestsPage.test.tsx` (check the file's existing render/setup helper and reuse it):

```tsx
it("permanent checkbox disables the end-date field and submits end_date: null", async () => {
  renderPage(); // use this file's existing render helper
  const user = userEvent.setup();
  await user.selectOptions(screen.getByTestId("er-type"), "type-1"); // adjust to match how type selection actually works in this file
  await user.type(screen.getByTestId("er-start"), "2026-09-01");
  await user.click(screen.getByTestId("er-permanent"));
  expect(screen.getByTestId("er-end")).toBeDisabled();
  await user.click(screen.getByText("שלח בקשת פטור"));
  await waitFor(() => {
    expect(vi.mocked(exemptionsApi.submitExemptionRequest)).toHaveBeenCalledWith(
      expect.objectContaining({ end_date: null }),
    );
  });
});

it("unchecking permanent re-enables and requires the end-date field", async () => {
  renderPage();
  const user = userEvent.setup();
  await user.click(screen.getByTestId("er-permanent"));
  await user.click(screen.getByTestId("er-permanent"));
  expect(screen.getByTestId("er-end")).not.toBeDisabled();
  expect(screen.getByTestId("er-end")).toBeRequired();
});
```

Before finalizing, read the actual top of `MyRequestsPage.test.tsx` to match its render helper name, mock setup (`vi.mock("../api/exemptions")` or similar), and how `erTypeId`/`DateInput` are currently driven in other tests in the same file — the snippet above uses placeholder selectors (`"type-1"`) that must match real fixture data already present in that file.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- MyRequestsPage -t "permanent checkbox"` (from `frontend/`)
Expected: FAIL — `getByTestId("er-permanent")` not found (checkbox doesn't exist yet).

- [ ] **Step 3: Add the checkbox and wire it to submission**

In `frontend/src/pages/MyRequestsPage.tsx`, add state near the other `er*` state (around line 38-46):

```tsx
const [erPermanent, setErPermanent] = useState(false);
```

Update the submit handler (around line 147-151) so a permanent request always sends `null`:

```tsx
const createdReq = await submitExemptionRequest({
  exemption_type_id: erTypeId,
  start_date: erStart,
  end_date: erPermanent ? null : (erEnd || null),
  reason: erReason || null,
```

Update the end-date field markup (around line 317-318) to add the checkbox right after it and disable the input when permanent is checked:

```tsx
<div>
  <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.end_date")}</label>
  <DateInput
    className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
    value={erPermanent ? "" : erEnd}
    onChange={(iso) => setErEnd(iso)}
    min={erStart || undefined}
    disabled={erPermanent}
    required={!erPermanent}
    data-testid="er-end"
  />
  <label className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400 mt-1">
    <input
      type="checkbox"
      checked={erPermanent}
      onChange={(e) => { setErPermanent(e.target.checked); if (e.target.checked) setErEnd(""); }}
      data-testid="er-permanent"
    />
    {t("exemption_requests.permanent")}
  </label>
</div>
```

Check `DateInput`'s props (`frontend/src/components/DateInput.tsx`) to confirm it accepts and forwards a `disabled` prop; if it doesn't, add `disabled?: boolean` to its prop type and pass it through to the underlying `<input>` — this is a small, additive change to a shared component, keep it minimal.

Update the submit-disabled condition (around line 421) to require an end date only when not permanent:

```tsx
disabled={erSubmitting || !erTypeId || (isMedical && uploadFiles.length === 0) || enrollmentPending || (!erPermanent && !isDateRangeValid(erStart, erEnd)) || (!erPermanent && !erEnd)}
```

In `frontend/src/i18n/he.json`, add to the `exemption_requests` block (near `end_date`, around line 541):

```json
"permanent": "פטור קבוע",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- MyRequestsPage` (from `frontend/`)
Expected: PASS (including pre-existing tests in the file — confirm none broke).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MyRequestsPage.tsx frontend/src/components/DateInput.tsx frontend/src/i18n/he.json frontend/src/pages/MyRequestsPage.test.tsx
git commit -m "feat: add permanent-exemption checkbox to exemption request form"
```

---

### Task 5: Add `Notification.metadata` column and thread it through `create_notification`

**Files:**
- Create: `backend/alembic/versions/<new_revision>_add_notification_metadata.py`
- Modify: `backend/app/db/models.py:1230-1241` (`Notification`)
- Modify: `backend/app/services/notifications.py:282-...` (`create_notification`), and the `notify_duty_managers_in_scope` function (line 554-...)
- Modify: `backend/app/routes/notifications.py:21-30` (`NotificationOut`), `:171-176` (`_out`)
- Test: `backend/app/services/tests/test_notifications.py` (or wherever `create_notification` is tested — search first)

**Interfaces:**
- Produces: `create_notification(..., metadata: dict | None = None)`, `notify_duty_managers_in_scope(..., metadata: dict | None = None)`, `Notification.metadata: dict | None`, `NotificationOut.metadata: dict | None` — consumed by Task 6 (range excusal) and Task 7 (frontend).

- [ ] **Step 1: Write the failing test**

In the test file covering `create_notification`:

```python
def test_create_notification_persists_metadata(app_session, soldier_factory):
    soldier = soldier_factory()
    notif = create_notification(
        app_session, soldier_id=soldier.id, type=NotificationType.announcement,
        title="test", metadata={"event_id": "abc-123"},
    )
    app_session.refresh(notif)
    assert notif.metadata == {"event_id": "abc-123"}


def test_create_notification_defaults_metadata_to_none(app_session, soldier_factory):
    soldier = soldier_factory()
    notif = create_notification(app_session, soldier_id=soldier.id, type=NotificationType.announcement, title="test")
    assert notif.metadata is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_notifications.py -k "metadata" -v`
Expected: FAIL — `TypeError: create_notification() got an unexpected keyword argument 'metadata'`.

- [ ] **Step 3: Add the column and thread the parameter**

Generate the migration:

```bash
cd backend && alembic revision -m "add_notification_metadata"
```

Edit the generated file:

```python
def upgrade() -> None:
    op.add_column("notifications", sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "metadata")
```

(Match the exact import style — `from alembic import op`, `import sqlalchemy as sa`, `from sqlalchemy.dialects import postgresql` — already used by other recent migrations in `backend/alembic/versions/`; check one, e.g. the file that added `weapon_ineligible_reason`, for the precise header/`revision`/`down_revision` boilerplate.)

In `backend/app/db/models.py`, add to `Notification` (after `reference_id`, around line 1238):

```python
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, default=None)
```

Note the attribute is named `metadata_json` (not `metadata`) because `metadata` is a reserved attribute name on SQLAlchemy declarative models (`Base.metadata` is the schema metadata object) — the column itself is still named `metadata` in the database via the explicit `"metadata"` argument. Check the top of `models.py` for the existing `JSONB` import (it's already used elsewhere, e.g. `DutyType.requirements`); add it if missing.

In `backend/app/services/notifications.py`, update `create_notification`:

```python
def create_notification(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    type: NotificationType,
    title: str,
    body: str | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> Notification | None:
    pref = session.execute(
        select(NotificationPreference).where(
            NotificationPreference.soldier_id == soldier_id,
            NotificationPreference.notification_type == type,
        )
    ).scalar_one_or_none()
    if pref is not None and not pref.in_app_enabled:
        return None
    notif = Notification(
        soldier_id=soldier_id, type=type, title=title, body=body,
        reference_type=reference_type, reference_id=reference_id,
        metadata_json=metadata,
    )
```

(Leave the rest of the function body unchanged.)

Update `notify_duty_managers_in_scope` (line 554-...) to accept and forward the same parameter — add `metadata: dict | None = None` to its signature and pass `metadata=metadata` in its internal call(s) to `create_notification`.

In `backend/app/routes/notifications.py`, add to `NotificationOut` (line 21-30):

```python
class NotificationOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    title: str
    body: str | None
    type: str
    reference_type: str | None
    reference_id: uuid.UUID | None
    is_read: bool
    created_at: datetime
    metadata: dict | None = None
```

Update `_out` (line 171-176):

```python
def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id, soldier_id=n.soldier_id, title=n.title, body=n.body,
        type=n.type.value, reference_type=n.reference_type,
        reference_id=n.reference_id, is_read=n.is_read, created_at=n.created_at,
        metadata=n.metadata_json,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_notifications.py -k "metadata" -v`
Expected: PASS

- [ ] **Step 5: Apply the migration locally and run the full notifications test suite**

Run: `cd backend && alembic upgrade head && pytest app/services/tests/test_notifications.py app/routes/tests/test_notifications_routes.py -v` (adjust the second path if the routes test file has a different name — search first)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/ backend/app/db/models.py backend/app/services/notifications.py backend/app/routes/notifications.py backend/app/services/tests/test_notifications.py
git commit -m "feat: add nullable metadata column to Notification"
```

---

### Task 6: Notify duty managers of pending range excusals (with event_id metadata)

**Files:**
- Modify: `backend/app/services/range_excusal.py:72-95` (`request_primary_excusal`)
- Test: `backend/app/services/tests/test_range_excusal.py` (search for the actual filename first — likely under `backend/app/services/tests/` or a ranges-specific test module)

**Interfaces:**
- Consumes: `create_notification(..., metadata=...)` and `notify_duty_managers_in_scope(..., metadata=...)` from Task 5.
- Produces: a second `Notification` row (type `range_excusal_pending`, recipient = duty managers in scope, `metadata={"event_id": ...}`) alongside the existing requester-facing one — consumed by Task 7's frontend decide buttons.

- [ ] **Step 1: Write the failing test**

```python
def test_request_primary_excusal_notifies_duty_managers_with_event_id(app_session, range_assignment_factory, duty_manager_factory):
    dm = duty_manager_factory()  # scoped to cover the assignment's soldier's hierarchy node
    assignment = range_assignment_factory(is_reserve=False)
    request = excusal_svc.request_primary_excusal(
        app_session, assignment=assignment, reason="סיבה", requested_by=assignment.soldier_id,
    )
    dm_notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == dm.id,
            Notification.type == NotificationType.range_excusal_pending,
            Notification.reference_id == request.id,
        )
    ).scalar_one()
    assert dm_notif.metadata_json == {"event_id": str(assignment.range_event_id)}
```

Replace `range_assignment_factory`/`duty_manager_factory` with the actual fixtures already used by this codebase's range-excusal tests (check `backend/app/services/tests/` or `backend/tests/integration/` for existing `request_primary_excusal` tests and copy their setup pattern, including however they establish `DutyManagerScope` coverage for the test soldier).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest <test_file> -k "notifies_duty_managers" -v`
Expected: FAIL — no such notification exists (duty managers aren't notified today).

- [ ] **Step 3: Add the manager-facing notification**

In `backend/app/services/range_excusal.py`, update `request_primary_excusal` (line 72-95):

```python
def request_primary_excusal(
    session: Session, *, assignment: RangeAssignment, reason: str, requested_by: uuid.UUID,
) -> RangeExcusalRequest:
    _load_future_event(session, assignment)
    if assignment.is_reserve:
        raise RangeValidationError("assignment_is_reserve")
    if requested_by != assignment.soldier_id:
        raise RangeValidationError("not_assignment_owner")
    _ensure_no_pending(session, assignment.id)
    request = RangeExcusalRequest(
        range_assignment_id=assignment.id, range_event_id=assignment.range_event_id, requested_by=requested_by,
        reason=_validate_reason(reason), status=RangeExcusalStatus.pending,
    )
    session.add(request)
    session.flush()
    _recheck_soldier_assignments(session, assignment.soldier_id)
    _range_notification(
        session, soldier_id=assignment.soldier_id, type=NotificationType.range_excusal_pending,
        title="בקשת ההיעדרות נשלחה", reference_type="range_excusal_request",
        reference_id=request.id, actor_id=requested_by,
    )
    notify_duty_managers_in_scope(
        session, soldier_id=assignment.soldier_id, type=NotificationType.range_excusal_pending,
        title="בקשת היעדרות ממתינה להחלטה", reference_type="range_excusal_request",
        reference_id=request.id, actor_id=requested_by,
        metadata={"event_id": str(assignment.range_event_id)},
    )
    session.commit()
    session.refresh(request)
    return request
```

`notify_duty_managers_in_scope` is already imported at the top of this file (line 17). Note `_range_notification` (the local wrapper around `create_notification` that gates on the `mitvachim.enabled` setting) is only used for the requester-facing copy here — call `notify_duty_managers_in_scope` directly since it isn't wrapped by `_range_notification` today and this task doesn't need to change that; if `mitvachim.enabled` gating should also apply to the manager notification, gate the whole call behind the same setting check `_range_notification` performs (read `_range_notification`'s body at line 21-26 and replicate its condition around the `notify_duty_managers_in_scope` call for consistency).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest <test_file> -k "notifies_duty_managers" -v`
Expected: PASS

- [ ] **Step 5: Run the full range_excusal test suite to check for regressions**

Run: `pytest <test_file> -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/range_excusal.py <test_file>
git commit -m "feat: notify duty managers in scope when a range excusal request is pending"
```

---

### Task 7: Fix `swap_offer_incoming` deep link

**Files:**
- Modify: `frontend/src/api/notifications.ts:34-53` (`getNotificationLink`)
- Test: `frontend/src/api/notifications.test.ts` (create if it doesn't exist — check first; if `getNotificationLink` has no dedicated test file, add one)

**Interfaces:**
- No signature change — `getNotificationLink` keeps its existing type.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from "vitest";
import { getNotificationLink } from "./notifications";

describe("getNotificationLink", () => {
  it("routes swap_offer_incoming to the incoming tab", () => {
    const link = getNotificationLink({ type: "swap_offer_incoming", reference_type: "swap_request", reference_id: "r1" });
    expect(link).toBe("/swaps?tab=incoming");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- notifications.test -t "swap_offer_incoming"` (from `frontend/`)
Expected: FAIL — currently returns `/swaps?tab=mine`.

- [ ] **Step 3: Fix the mapping**

In `frontend/src/api/notifications.ts`, update the `swap_request` branch (line 40-42):

```ts
  if (n.reference_type === "swap_request") {
    return (n.type === "swap_offer" || n.type === "swap_offer_incoming") ? "/swaps?tab=incoming" : "/swaps?tab=mine";
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- notifications.test` (from `frontend/`)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/notifications.ts frontend/src/api/notifications.test.ts
git commit -m "fix: route swap_offer_incoming notifications to the incoming swaps tab"
```

---

### Task 8: Real notification buttons — mark-read/dismiss always, approve/reject for quick-decision types

**Files:**
- Modify: `frontend/src/api/notifications.ts` (`NotificationDTO`)
- Modify: `frontend/src/components/NotificationBell.tsx`
- Modify: `frontend/src/pages/NotificationsPage.tsx`
- Modify: `frontend/src/i18n/he.json` (add `notifications.approve`, `notifications.reject`)
- Test: `frontend/src/components/NotificationBell.test.tsx`, `frontend/src/pages/NotificationsPage.test.tsx`

**Interfaces:**
- Consumes: `NotificationDTO.metadata: Record<string, unknown> | null` (Task 5/7's backend field), `soldierApproveSwap`/`soldierRejectSwap` from `frontend/src/api/swaps.ts:121-127`, `decideRangeExcusal` from `frontend/src/api/ranges.ts:26`.

- [ ] **Step 1: Write the failing tests**

Add to `NotificationBell.test.tsx` (reuse the file's existing `baseNotification`/`renderBell` helpers, add `metadata: null` to `baseNotification`):

```tsx
import * as swapsApi from "../api/swaps";
import * as rangesApi from "../api/ranges";

vi.mock("../api/swaps");
vi.mock("../api/ranges");

describe("NotificationBell quick decisions", () => {
  it("always shows mark-read and dismiss buttons regardless of type", async () => {
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({
      items: [{ ...baseNotification, id: "n1", title: "Announcement", type: "announcement" }],
      total: 1,
    });
    renderBell();
    (await screen.findByTestId("notification-bell")).click();
    await screen.findByText("Announcement");
    expect(screen.getByLabelText("notifications.mark_read")).toBeInTheDocument();
    expect(screen.getByLabelText("notifications.dismiss")).toBeInTheDocument();
    expect(screen.queryByLabelText("notifications.approve")).not.toBeInTheDocument();
  });

  it("shows approve/reject for swap_offer_incoming and calls the soldier-decision API", async () => {
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({
      items: [{ ...baseNotification, id: "n1", title: "Swap offer", type: "swap_offer_incoming", reference_type: "swap_request", reference_id: "req1" }],
      total: 1,
    });
    vi.mocked(swapsApi.soldierApproveSwap).mockResolvedValue({} as never);
    renderBell();
    (await screen.findByTestId("notification-bell")).click();
    await screen.findByText("Swap offer");
    screen.getByLabelText("notifications.approve").click();
    await waitFor(() => expect(swapsApi.soldierApproveSwap).toHaveBeenCalledWith("req1"));
  });

  it("shows approve/reject for range_excusal_pending and calls decideRangeExcusal with metadata.event_id", async () => {
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({
      items: [{
        ...baseNotification, id: "n1", title: "Excusal pending", type: "range_excusal_pending",
        reference_type: "range_excusal_request", reference_id: "req1", metadata: { event_id: "evt1" },
      }],
      total: 1,
    });
    vi.mocked(rangesApi.decideRangeExcusal).mockResolvedValue({} as never);
    renderBell();
    (await screen.findByTestId("notification-bell")).click();
    await screen.findByText("Excusal pending");
    screen.getByLabelText("notifications.reject").click();
    await waitFor(() => expect(rangesApi.decideRangeExcusal).toHaveBeenCalledWith("evt1", "req1", false));
  });
});
```

Add analogous tests to `NotificationsPage.test.tsx` for the same three behaviors (always-present base buttons, swap approve/reject, range excusal approve/reject) — copy that file's existing render/query-client setup.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- NotificationBell -t "quick decisions"` (from `frontend/`)
Expected: FAIL — no `aria-label`s exist yet (current buttons are bare `✓`/`✕` text with only a `title` attribute, no accessible label, and there's no approve/reject pair at all).

- [ ] **Step 3: Add `metadata` to the DTO and rebuild the button row**

In `frontend/src/api/notifications.ts`, extend `NotificationDTO`:

```ts
export interface NotificationDTO {
  id: string;
  soldier_id: string;
  title: string;
  body: string | null;
  type: string;
  reference_type: string | null;
  reference_id: string | null;
  is_read: boolean;
  created_at: string;
  metadata: Record<string, unknown> | null;
}
```

Create a small shared helper both surfaces will use — add to `frontend/src/api/notifications.ts`:

```ts
export const QUICK_DECISION_TYPES = ["swap_offer_incoming", "range_excusal_pending"] as const;

export function isQuickDecisionNotification(n: Pick<NotificationDTO, "type">): boolean {
  return (QUICK_DECISION_TYPES as readonly string[]).includes(n.type);
}
```

In `frontend/src/components/NotificationBell.tsx`, import lucide icons and the two decision APIs:

```tsx
import { Check, X, Trash2 } from "lucide-react";
import { soldierApproveSwap, soldierRejectSwap } from "../api/swaps";
import { decideRangeExcusal } from "../api/ranges";
import { isQuickDecisionNotification } from "../api/notifications";
```

Add a decision handler alongside the existing `handleMarkRead`/`handleDelete` (after line 54):

```tsx
async function handleDecision(n: NotificationDTO, approve: boolean) {
  try {
    if (n.type === "swap_offer_incoming" && n.reference_id) {
      await (approve ? soldierApproveSwap(n.reference_id) : soldierRejectSwap(n.reference_id));
    } else if (n.type === "range_excusal_pending" && n.reference_id) {
      const eventId = n.metadata?.event_id as string | undefined;
      if (!eventId) return;
      await decideRangeExcusal(eventId, n.reference_id, approve);
    } else {
      return;
    }
    setNotifications((prev) => prev.filter((x) => x.id !== n.id));
    setUnread((u) => Math.max(0, u - 1));
  } catch { /* ignore — surfaced via the full review page if it fails */ }
}
```

Replace the button row (line 129-132):

```tsx
<div className="flex gap-1">
  {isQuickDecisionNotification(n) && (
    <>
      <button
        onClick={() => handleDecision(n, true)}
        className="p-1.5 rounded bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900 dark:text-green-300 dark:hover:bg-green-800"
        aria-label={t("notifications.approve")}
        title={t("notifications.approve")}
      >
        <Check size={14} />
      </button>
      <button
        onClick={() => handleDecision(n, false)}
        className="p-1.5 rounded bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-900 dark:text-red-300 dark:hover:bg-red-800"
        aria-label={t("notifications.reject")}
        title={t("notifications.reject")}
      >
        <X size={14} />
      </button>
    </>
  )}
  <button
    onClick={() => handleMarkRead(n.id)}
    className="p-1.5 rounded text-gray-500 hover:bg-gray-200 dark:text-gray-400 dark:hover:bg-gray-600"
    aria-label={t("notifications.mark_read")}
    title={t("notifications.mark_read")}
  >
    <Check size={14} />
  </button>
  <button
    onClick={() => handleDelete(n.id)}
    className="p-1.5 rounded text-gray-500 hover:bg-red-100 hover:text-red-600 dark:text-gray-400 dark:hover:bg-red-900"
    aria-label={t("notifications.dismiss")}
    title={t("notifications.dismiss")}
  >
    <Trash2 size={14} />
  </button>
</div>
```

Apply the equivalent change to `frontend/src/pages/NotificationsPage.tsx`: import the same icons/APIs/helper, add the same `handleDecision` function (adjusted to use this file's `queryClient.invalidateQueries` pattern instead of local `setNotifications`/`setUnread` state — mirror how `handleMarkRead` already does the invalidation there), and replace its button row (line 96-105) the same way — but here the mark-read button should always render (drop the `{!n.is_read && ...}` guard at line 97, since Task's requirement is "always there"; clicking it when already read is a harmless no-op through the existing `markRead` call).

In `frontend/src/i18n/he.json`, add to the `notifications` block:

```json
"approve": "אשר",
"reject": "דחה",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- NotificationBell NotificationsPage` (from `frontend/`)
Expected: PASS

- [ ] **Step 5: Run the full frontend suite to check for regressions**

Run: `npm test` (from `frontend/`)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/notifications.ts frontend/src/components/NotificationBell.tsx frontend/src/pages/NotificationsPage.tsx frontend/src/i18n/he.json frontend/src/components/NotificationBell.test.tsx frontend/src/pages/NotificationsPage.test.tsx
git commit -m "feat: real icon buttons on notifications, with quick approve/reject for swap offers and range excusals"
```

---

## Final verification

- [ ] Run `pytest -q` from `backend/` (with venv activated) — full backend suite green.
- [ ] Run `npm test` from `frontend/` — full frontend suite green.
- [ ] Run `npm run lint` from `frontend/` — zero warnings.
- [ ] Run `npm run typecheck` from `frontend/` — no errors.
- [ ] Manually verify in the browser (via `.\dev.ps1`): homepage shows a called-up reserve duty as "הוקפץ" with dates; a rejected exemption notification includes the type name and dates; the permanent checkbox disables the end-date field; the notification bell shows real icon buttons with approve/reject only on a swap offer and a range excusal notification.
