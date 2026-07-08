# Date Format Investigation & Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether dates actually render in American (MM/DD/YYYY) format anywhere in the app and, if so, fix the specific spot — without guessing, since the codebase audit found no hardcoded American-format construction.

**Architecture:** This is a reproduce-first task, not a known bug with a known fix. `frontend/src/utils/formatDate.ts` already centralizes display as `dd.mm.yyyy`, and native `<input type="date">` elements already carry `lang="he"`. The most likely explanation is a native date-picker following the reporting user's OS/browser locale rather than a code defect — `lang="he"` only nudges some browsers' pickers, it doesn't force the format. Confirm with the reporting user before writing any fix.

**Tech Stack:** React, TypeScript (frontend). No backend involvement — dates are stored as ISO (`YYYY-MM-DD`) strings/`date` types throughout the API layer; only display formatting is in question.

## Global Constraints

- Do not change `formatDate.ts` or add a custom date-picker component speculatively. Only touch code once Task 1 has identified a concrete, reproducible spot where American format actually renders.

---

### Task 1: Reproduce

**Files:** none (investigation only).

- [ ] **Step 1: Get reproduction details from the reporting user**

Ask (or relay to whoever can ask the original reporter):
- Which screen/field specifically showed the American-format date? (a text label, or a date *input* field?)
- Browser and OS (e.g. Chrome on Windows, Safari on iPhone)? Native `<input type="date">` pickers render using the OS/browser's own locale — Windows in an English-language install often shows `MM/DD/YYYY` in the picker regardless of `lang="he"` on the element, because Chromium honors `lang` inconsistently across OS/browser combinations.
- A screenshot, if available.

- [ ] **Step 2: Search for any hardcoded/non-`formatDate` date rendering**

Run: `grep -rn "toLocaleDateString\|new Date(" frontend/src/pages frontend/src/components | grep -v "he-IL"` — review each hit. Anything calling `toLocaleDateString()` with no locale argument (defaults to the browser's locale, which could be English/American on an English-OS browser) is a real candidate; anything passing `"he-IL"` explicitly is already correct.

Run: `grep -rln "type=\"date\"" frontend/src/pages frontend/src/components` and cross-check each against `lang="he"` presence (`grep -n "type=\"date\"" <file>` then check the same `<input>` for `lang="he"`) — any `<input type="date">` missing `lang="he"` is a real gap (inconsistent with the rest of the app) even before considering OS-locale quirks.

- [ ] **Step 3: Report findings**

Summarize what was found: either (a) a specific unlocalized `toLocaleDateString()` call or a `<input type="date">` missing `lang="he"` — a real, fixable code gap — or (b) confirmation that every date-rendering call site already goes through `formatDate.ts` or passes `"he-IL"`/`lang="he"`, meaning the issue is a browser/OS locale quirk outside the app's control.

---

### Task 2: Fix (only if Task 1 found a concrete gap)

**Files:** whichever file(s) Task 1 identified.

- [ ] **Step 1: Write a regression test if the fix is testable**

If the gap was a `toLocaleDateString()` call missing a locale, add/adjust a component test asserting the rendered text matches `DD.MM.YYYY` shape for a known input date. Check `frontend/src/pages/*.test.tsx` for the existing testing pattern in this codebase (React Testing Library) before writing it.

- [ ] **Step 2: Apply the fix**

For a missing locale on `toLocaleDateString()`: change the call to `date.toLocaleDateString("he-IL")`, matching every other call site.

For an `<input type="date">` missing `lang="he"`: add `lang="he"` to that element, matching every other date input in the app.

- [ ] **Step 3: Run the test and verify**

Run: `cd frontend && npm test -- <affected test file>`
Expected: passing.

- [ ] **Step 4: Commit**

```bash
git add <affected files>
git commit -m "fix: use he-IL date formatting at <location>"
```

---

### Task 3: If Task 1 found no code gap

**Files:** none.

- [ ] **Step 1: Document the finding and close out**

No code change needed. Relay to the reporting user that the app's date rendering is already consistently Hebrew-locale, and the American-format sighting is very likely their browser/OS locale setting affecting the native date-picker widget (which the app's `lang="he"` hint can influence but not fully override on every browser/OS combination) — not something fixable from within the app's code. If the user can reproduce it again with a screenshot and browser/OS details, revisit Task 1.
