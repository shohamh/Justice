# Date Format & Duty History Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all raw ISO date displays (YYYY-MM-DD → DD.MM.YYYY) and rename two duty-history filter chips.

**Architecture:** `formatDate()` already exists in `frontend/src/utils/formatDate.ts` and produces DD.MM.YYYY. Every place that renders a date string directly in JSX must call it. The i18n keys for the two filter chips and their underlying filter logic in `DutyHistoryPanel` also change.

**Tech Stack:** React, TypeScript, i18next (he.json)

---

## File Map

| File | Change |
|------|--------|
| `frontend/src/i18n/he.json` | Rename two `duty_history` filter keys |
| `frontend/src/components/DutyHistoryPanel.tsx` | Use `formatDate`, update "published"/"official" filter logic |
| `frontend/src/components/ExemptionsPanel.tsx` | Use `formatDate` for exemption date ranges |
| `frontend/src/components/UnifiedSoldierModal.tsx` | Use `formatDate` for enrolled_at, profile dates, constraint dates |
| `frontend/src/pages/ProfilePage.tsx` | Use `formatDate` for profile date fields |

---

### Task 1: Rename filter chip labels in he.json and update filter logic

**Files:**
- Modify: `frontend/src/i18n/he.json` (lines ~745–748)
- Modify: `frontend/src/components/DutyHistoryPanel.tsx` (StatusFilter filtered switch)

- [ ] **Step 1: Update i18n keys**

In `frontend/src/i18n/he.json`, find:
```json
"filter_published": "פורסם",
"filter_draft": "טיוטה",
"filter_reserve": "רזרבה",
"filter_official": "רשמי"
```
Change to:
```json
"filter_published": "שיבוץ בפועל (לא רזרבה)",
"filter_draft": "טיוטה",
"filter_reserve": "רזרבה",
"filter_official": "בוטל"
```

- [ ] **Step 2: Update "published" filter logic in DutyHistoryPanel**

In `frontend/src/components/DutyHistoryPanel.tsx`, find the `StatusFilter` switch (around line 599):
```typescript
      case "published":
        return typeFiltered.filter(
          (e) => e.status === "published" || e.status === "active" || e.status === "approved"
        );
```
Replace with (adds `is_reserve !== "true"` to match the new label):
```typescript
      case "published":
        return typeFiltered.filter(
          (e) =>
            (e.status === "published" || e.status === "active" || e.status === "approved") &&
            e.metadata.is_reserve !== "true"
        );
```

- [ ] **Step 3: Update "official" filter logic — now means "cancelled"**

In the same switch, find:
```typescript
      case "official":
        return typeFiltered.filter(
          (e) => e.event_type === "assignment" && e.metadata.is_reserve !== "true"
        );
```
Replace with:
```typescript
      case "official":
        return typeFiltered.filter(
          (e) => e.status === "cancelled" || e.event_type === "cancellation"
        );
```

- [ ] **Step 4: Verify in browser**

Start dev stack (`.\dev.ps1 -NoBot`), open a soldier's duty history, and confirm:
- Filter chip formerly labelled "פורסם" now shows "שיבוץ בפועל (לא רזרבה)" and only shows published non-reserve assignments
- Filter chip formerly labelled "רשמי" now shows "בוטל" and only shows cancelled events

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/he.json frontend/src/components/DutyHistoryPanel.tsx
git commit -m "fix: rename duty-history filter chips and align filter logic"
```

---

### Task 2: Fix raw dates in DutyHistoryPanel

**Files:**
- Modify: `frontend/src/components/DutyHistoryPanel.tsx`

- [ ] **Step 1: Add formatDate import**

At the top of `frontend/src/components/DutyHistoryPanel.tsx`, add after the existing imports:
```typescript
import { formatDate } from "../utils/formatDate";
```

- [ ] **Step 2: Fix event date display in EventCard**

Find (around line 163):
```tsx
            <p className="text-xs text-gray-500" dir="ltr">
              {e.date}{e.end_date && e.end_date !== e.date ? ` → ${e.end_date}` : ""}
            </p>
```
Replace with:
```tsx
            <p className="text-xs text-gray-500">
              {formatDate(e.date)}{e.end_date && e.end_date !== e.date ? ` – ${formatDate(e.end_date)}` : ""}
            </p>
```

- [ ] **Step 3: Fix today divider**

Find (around line 714):
```tsx
            <span className="text-xs text-gray-400">{today}</span>
```
Replace with:
```tsx
            <span className="text-xs text-gray-400">{formatDate(today)}</span>
```

- [ ] **Step 4: Verify and commit**

Open duty history panel; confirm dates show as DD.MM.YYYY with em-dash separator.

```bash
git add frontend/src/components/DutyHistoryPanel.tsx
git commit -m "fix: format dates as DD.MM.YYYY in duty history panel"
```

---

### Task 3: Fix raw dates in ExemptionsPanel

**Files:**
- Modify: `frontend/src/components/ExemptionsPanel.tsx`

- [ ] **Step 1: Add formatDate import**

At top of `frontend/src/components/ExemptionsPanel.tsx`:
```typescript
import { formatDate } from "../utils/formatDate";
```

- [ ] **Step 2: Fix exemption date range display**

Find (around line 107):
```tsx
                <span className="text-gray-500 dark:text-gray-400 text-xs" dir="ltr">{ex.start_date} → {ex.end_date ?? t("exemptions.forever")}</span>
```
Replace with:
```tsx
                <span className="text-gray-500 dark:text-gray-400 text-xs">{formatDate(ex.start_date)} → {ex.end_date ? formatDate(ex.end_date) : t("exemptions.forever")}</span>
```

- [ ] **Step 3: Verify and commit**

Check a soldier's exemptions panel; dates show as DD.MM.YYYY.

```bash
git add frontend/src/components/ExemptionsPanel.tsx
git commit -m "fix: format exemption dates as DD.MM.YYYY"
```

---

### Task 4: Fix raw dates in UnifiedSoldierModal

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx`

- [ ] **Step 1: Add formatDate import**

At top of `frontend/src/components/UnifiedSoldierModal.tsx`:
```typescript
import { formatDate } from "../utils/formatDate";
```

- [ ] **Step 2: Fix enrolled_at in details tab**

Find (around line 231):
```tsx
                  <span dir="ltr">{soldier.enrolled_at}</span>
```
(The one inside `{soldier.enrolled_at && (...)}`.)
Replace with:
```tsx
                  <span>{formatDate(soldier.enrolled_at!)}</span>
```

- [ ] **Step 3: Fix profile view dates**

Find and replace each date display in the profile view tab (around lines 325–329). These are the `{soldier.enlistment_date && ...}` blocks. Change each:
```tsx
                  <span dir="ltr">{soldier.enlistment_date}</span>
```
→
```tsx
                  <span>{formatDate(soldier.enlistment_date!)}</span>
```
Apply the same pattern to `mandatory_end_date`, `discharge_date`, `last_mitvahim_date`, and `last_alal_date`.

- [ ] **Step 4: Fix constraint dates in constraints tab**

Find (around line 427):
```tsx
                  <span className="text-gray-500" dir="ltr">{c.start_date} → {c.end_date}</span>
```
Replace with:
```tsx
                  <span className="text-gray-500">{formatDate(c.start_date)} → {formatDate(c.end_date)}</span>
```

- [ ] **Step 5: Verify and commit**

Open any soldier modal; dates in details, profile, and constraints tabs show as DD.MM.YYYY.

```bash
git add frontend/src/components/UnifiedSoldierModal.tsx
git commit -m "fix: format soldier modal dates as DD.MM.YYYY"
```

---

### Task 5: Fix raw dates in ProfilePage

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx`

- [ ] **Step 1: Add formatDate import**

At top of `frontend/src/pages/ProfilePage.tsx`:
```typescript
import { formatDate } from "../utils/formatDate";
```

- [ ] **Step 2: Fix profile date fields**

Find each raw date display in the profile section (around lines 160–164):
```tsx
          {user?.enlistment_date && <div>...: {user.enlistment_date}</div>}
          {user?.mandatory_end_date && <div>...: {user.mandatory_end_date}</div>}
          {user?.discharge_date && <div>...: {user.discharge_date}</div>}
          {user?.last_mitvahim_date && <div>...: {user.last_mitvahim_date}</div>}
          {user?.last_alal_date && <div>...: {user.last_alal_date}</div>}
```
For each, change `{user.xxx_date}` to `{formatDate(user.xxx_date!)}`.

- [ ] **Step 3: Verify and commit**

Open profile page; all date fields show as DD.MM.YYYY.

```bash
git add frontend/src/pages/ProfilePage.tsx
git commit -m "fix: format profile page dates as DD.MM.YYYY"
```
