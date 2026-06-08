# Design: היומן שלי — Statistics Dashboard

**Date:** 2026-06-08
**Status:** Approved

## Problem

`MyDutiesPage` (היומן שלי) is a FullCalendar duplicate of the homepage. It shows the same `listEffectiveDuties` data already visible in `DutyCalendarWidget` and `UpcomingDutiesWidget` on the home page. Soldiers get no additional value from visiting it.

## Solution

Replace the page entirely with a personal statistics dashboard. No backend changes required — all data comes from existing APIs.

## Data Sources

| API | Data Used |
|-----|-----------|
| `GET /scoring/transparency` | Unit-wide rows for rank calculation and unit averages |
| `GET /scoring/soldiers/{id}` | Per-duty-type breakdown (days + score), manual score adjustments |
| `GET /assignments/effective?soldier_id={id}` | Past duty count and total days served |

## New Dependency

Install `recharts` (standard React chart library, ~50 KB gzipped). No other new dependencies.

## Page Layout (RTL, top to bottom)

### Section 1 — Headline stat cards (2×2 grid)

Four cards, each showing the soldier's value and unit average below it:

| Card | Value | Sub-label |
|------|-------|-----------|
| תורנויות שירתתי | count of past duties | ממוצע יחידה: N |
| ימי תורנות | total days of past duties | ממוצע יחידה: N |
| ניקוד מנורמל | `normalised_score` | ממוצע יחידה: X.XXX |
| דירוג ביחידה | "12 מתוך 45" | (rank ascending by normalised_score) |

Cards use indigo accent for the main value, gray sub-label beneath.

### Section 2 — Breakdown by duty type (horizontal bar chart)

- Library: `recharts` `BarChart` with `layout="vertical"`
- One bar per duty type from `Breakdown.per_type`
- X-axis: days served
- Y-axis: duty type name (Hebrew)
- Bar tooltip: shows days + score for that type
- Title: "פירוט לפי סוג תורנות"
- Empty state: "אין נתוני פירוט" if `per_type` is empty

### Section 3 — Score vs unit average (two-bar chart)

- Library: `recharts` `BarChart` with `layout="horizontal"`
- Two bars: "הניקוד שלי" (soldier's normalised_score) and "ממוצע יחידה"
- Uses a contrasting color (indigo vs gray)
- Title: "ניקוד מנורמל — אני מול הממוצע"
- Only shown when `allRows.length > 1`

### Section 4 — Score adjustments (conditional)

- Only rendered when `Breakdown.adjustments.length > 0`
- Simple table: תאריך | שינוי (colored +/- delta) | סיבה
- Title: "התאמות ניקוד ידניות"

## Component Structure

```
MyDutiesPage.tsx          ← full rewrite (remove FullCalendar entirely)
  StatCard                ← inline sub-component (4 instances)
  DutyTypeBreakdownChart  ← inline sub-component (recharts BarChart)
  ScoreComparisonChart    ← inline sub-component (recharts BarChart)
  AdjustmentsTable        ← inline sub-component (conditional)
```

All sub-components defined in the same file — no new files needed, the page is self-contained.

## Loading State

While any fetch is pending: show a pulsing "טוען..." text in place of each section.

## Error Handling

Each fetch wrapped in `.catch(() => fallback)` — same pattern as HomePage. Stats degrade gracefully if one API fails.

## What Is Removed

- `FullCalendar` import and all calendar state (`rows`, `events`, `selectedDuty`, `whyTarget`)
- `@fullcalendar/*` imports (packages can remain installed — still used on the home page via `DutyCalendarWidget`)

## Out of Scope

- No new backend endpoints
- No score history over time (no time-series data available)
- No export
