# Design: UI Features, i18n Fixes, Seed Script, and E2E Tests

## Overview

Six independent improvements to the army duty management app: dynamic hierarchy tree UI, calendar view for personal duties, soldier exemption requests, i18n error translation fixes, a database seed script, and Playwright E2E coverage.

## Implementation Phases

### Phase 1: Foundation (no dependencies)

#### 1. i18n Error Fixes + Personal Constraint Form Fix

**Problem:** Backend error codes (`bad_date_range`, `start_date_in_past`, `cap_exceeded`, etc.) are returned as untranslated English strings. The constraint submit form in `MyRequestsPage` lacks error handling.

**Changes:**

- **`frontend/src/i18n/he.json`**: Add `errors` block:
  ```json
  "errors": {
    "bad_date_range": "טווח תאריכים לא תקין",
    "start_date_in_past": "תאריך התחלה לא יכול להיות בעבר",
    "cap_exceeded": "חרגת ממכסת הימים המותרת",
    "soldier_not_found": "חייל לא נמצא",
    "constraint_not_found": "הבקשה לא נמצאה",
    "not_pending": "הבקשה כבר טופלה",
    "generic": "שגיאה",
    "password_too_short": "הסיסמה חייבת להכיל לפחות 10 תווים",
    "date_range_invalid": "טווח תאריכים לא תקין",
    "exemption_not_found": "הפטור לא נמצא",
    "already_exists": "כבר קיים במערכת"
  }
  ```

- **`frontend/src/pages/MyRequestsPage.tsx`**: Add try/catch around `submitConstraint()`, display translated error message. Disable submit button while loading. Show success/error feedback toast or inline message.

- **`frontend/src/pages/DutyManagementPage.tsx`**: Change `"error"` fallback to `t("errors.generic")`.

- **`frontend/src/pages/ChangePasswordPage.tsx`**: Already partially translates errors — ensure `password_too_short` maps to the new `errors` key.

#### 2. Database Seed Script

**`backend/app/scripts/seed.py`** — A standalone script using SQLAlchemy session directly.

Creates:
- **Hierarchy**: 2 departments → 2 branches each → 2 groups each → 2 teams each = 30 nodes total
- **Soldiers**: ~40 soldiers distributed across teams, with roles (admin, duty_manager, commander, soldier)
- **Commanders**: Assign commanders to each hierarchy node
- **Duty Types**: 5 types (משמרת בוקר, משמרת ערב, משמרת לילה, שבת, חג)
- **Duty Locations**: 4 locations
- **Exemption Types**: 3 types (רפואי, אימונים, משפחתי) with duty type mappings
- **Assignments**: Duty assignments for next 30 days covering many soldiers
- **Personal Constraints**: Some pending, some approved, some rejected
- **Exemptions**: Manager-granted and soldier-requested exemptions
- **Score Adjustments**: A few manual adjustments

Run via: `python -m app.scripts.seed`

Uses `SessionLocal()` from the app's session factory with the app's models for consistency.

### Phase 2: Features

#### 3. Expandable Tree Hierarchy UI

**Components to create:**

- **`HierarchyTree.tsx`** — Recursive collapsible tree:
  - Expand/collapse arrow (toggles children visibility)
  - Node name + level badge (color-coded: department=blue, branch=green, group=yellow, team=gray)
  - Commander name shown below node name (if assigned)
  - Action buttons per node (appear on hover): Add Child, Set Commander, Rename, Delete
  - Icons: use simple SVG or Unicode symbols (no icon library dependency)

- **`AddChildNodeDialog.tsx`** — Modal:
  - Pre-filled parent node info
  - Name input
  - Level selector (auto-filtered to valid child levels: parent department → branch, parent branch → group, etc.)
  - Create button → calls `createNode()`

- **`AssignCommanderDialog.tsx`** — Modal:
  - Fetch soldiers belonging to this node's subtree (use existing `/soldiers` API filtered by node)
  - Searchable soldier list
  - Current commander shown
  - Assign button → calls `updateNode({ commander_id })`

- **`RenameNodeDialog.tsx`** — Simple modal with name input

- **Modified `TeamHierarchyPage.tsx`**:
  - Replace flat `<ul>` with `<HierarchyTree>`
  - Add "Add Root Department" button at top
  - Keep soldier onboarding form + soldier table at bottom
  - Keep ExemptionsPanel for selected soldier

**Backend changes needed:**
- None — existing API (POST `/hierarchy/nodes`, PATCH `/hierarchy/nodes/{id}`, DELETE `/hierarchy/nodes/{id}`, POST `/hierarchy/nodes/{id}/move`) fully supports all operations.

#### 4. Calendar with Duty List View

**Dependency:** `react-calendar` npm package

**Modified `MyDutiesPage.tsx`:**
- Import and render `<Calendar>` at top of page
- Use `tileContent` prop to show colored dots/indicators on days with duties
- Days with duties get highlighted background (color-coded by duty type)
- Clicking a day filters the duties table below to show only duties on that day
- "Today" button to jump back to current day
- Previous/next month navigation
- Even with 0 duties, calendar + empty list are shown

**Duty list below calendar:**
- Same table as before but filtered by selected day (or showing all if no day selected)
- Shows duty type, location, time range
- Empty state: "אין תורנויות ביום זה" / "אין תורנויות" depending on filter

#### 5. Exemption Requests Workflow

**New database table: `exemption_requests`**

```sql
CREATE TABLE exemption_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    soldier_id UUID NOT NULL REFERENCES soldiers(id),
    exemption_type_id UUID NOT NULL REFERENCES exemption_types(id),
    start_date DATE NOT NULL,
    end_date DATE,
    reason TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    decided_by UUID REFERENCES soldiers(id),
    decision_note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Model (`backend/app/db/models.py`):** Add `ExemptionRequest` SQLAlchemy model.

**New routes:**
- `POST /me/exemption-requests` — Soldier submits request (soldier_id from auth)
- `GET /me/exemption-requests` — List own requests
- `GET /exemption-requests/pending` — Manager views pending requests in scope
- `GET /exemption-requests/pending/count` — Badge count
- `POST /exemption-requests/{id}/approve` — Approve (status → approved, create SoldierExemption)
- `POST /exemption-requests/{id}/reject` — Reject (status → rejected, with decision_note)

On **approve**: Auto-create a `SoldierExemption` record so the exemption becomes active.

**Frontend:**
- **`MyRequestsPage.tsx`**: Add "בקשת פטור" section with form (exemption type dropdown, date range, reason). List existing requests with status badges.
- **`ApprovalsPage.tsx`**: Add tabs/sections. New "בקשות פטור" tab shows pending exemption requests with approve/reject buttons alongside existing personal constraints.
- **API (`frontend/src/api/exemptions.ts`):** Add functions for the new routes.

### Phase 3: Verification

#### 6. Playwright E2E Tests

New spec files in `frontend/tests/e2e/`:

- **`hierarchy.spec.ts`**:
  - Login as admin
  - Verify tree renders with existing nodes
  - Add child node under a department
  - Assign commander to a node
  - Rename a node
  - Verify changes appear

- **`personal_constraints.spec.ts`**:
  - Login as soldier
  - Submit personal constraint with valid dates → success
  - Submit with past start date → see Hebrew error
  - Login as commander
  - View pending constraints
  - Approve/reject a constraint
  - Verify status changes

- **`exemption_requests.spec.ts`**:
  - Login as soldier
  - Submit exemption request
  - Verify pending status
  - Login as commander
  - View pending exemption requests
  - Approve → verify it appears as active exemption
  - Submit another, reject → verify rejected

- **`duty_calendar.spec.ts`**:
  - Login as soldier
  - Verify calendar is visible (even with 0 duties)
  - Navigate months
  - Click a day with duties → filtered list shows
  - Verify duty list renders under calendar

- **`seed_views.spec.ts`**:
  - Login as admin after seed
  - Verify large tree renders without errors
  - Verify soldier list is populated
  - Verify unit calendar renders
  - Verify transparency page renders with scores

Each spec follows existing patterns: `loginAsAdmin` helper, `data-testid` selectors, unique test data via `Date.now()` suffix, serial test execution.
