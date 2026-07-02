# Password Strength Hint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shared `PasswordStrengthHint` component that shows live password-policy compliance (10+ chars, letter, digit) and wire it into `ChangePasswordPage`, `ResetPasswordPage`, and `RegisterPage` so users get feedback before submit instead of a server-side rejection.

**Architecture:** One new presentational component (`PasswordStrengthHint.tsx`) plus an exported pure function `passwordValid()`. The three existing pages import both, render the hint below the relevant password field, and use `passwordValid()` to gate their submit buttons (replacing ad-hoc length-only checks). Backend validation in `backend/app/services/soldiers.py` is untouched — it already enforces the same rule and remains the source of truth.

**Tech Stack:** React, TypeScript, `lucide-react` (icons), `react-i18next`, Vitest + Testing Library.

---

## File map

| File | Change |
|---|---|
| `frontend/src/components/PasswordStrengthHint.tsx` | New — component + `passwordValid()` export |
| `frontend/src/components/PasswordStrengthHint.test.tsx` | New — tests for `passwordValid()` and rendering |
| `frontend/src/i18n/he.json` | Add 3 keys under `change_password` |
| `frontend/src/pages/ChangePasswordPage.tsx` | Use hint + `passwordValid()`, remove manual length check |
| `frontend/src/pages/ResetPasswordPage.tsx` | Use hint + `passwordValid()` in disabled condition |
| `frontend/src/pages/RegisterPage.tsx` | Replace inline length-only check with hint + `passwordValid()` |

---

## Task 1: Create the `PasswordStrengthHint` component

**Files:**
- Create: `frontend/src/components/PasswordStrengthHint.tsx`
- Create: `frontend/src/components/PasswordStrengthHint.test.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add i18n keys**

In `frontend/src/i18n/he.json`, find the `change_password` block:

```json
  "change_password": {
    "title": "שינוי סיסמה",
    "current": "סיסמה נוכחית",
    "new": "סיסמה חדשה",
    "submit": "עדכן סיסמה",
    "forced_notice": "עליך לבחור סיסמה חדשה לפני המשך השימוש.",
    "min_length": "הסיסמה חייבת להכיל לפחות 10 תווים.",
    "wrong_current": "הסיסמה הנוכחית שגויה."
  },
```

Replace with (adds three keys, keeps existing ones):

```json
  "change_password": {
    "title": "שינוי סיסמה",
    "current": "סיסמה נוכחית",
    "new": "סיסמה חדשה",
    "submit": "עדכן סיסמה",
    "forced_notice": "עליך לבחור סיסמה חדשה לפני המשך השימוש.",
    "min_length": "הסיסמה חייבת להכיל לפחות 10 תווים.",
    "wrong_current": "הסיסמה הנוכחית שגויה.",
    "hint_length": "לפחות 10 תווים",
    "hint_letter": "לפחות אות אחת",
    "hint_digit": "לפחות ספרה אחת"
  },
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/components/PasswordStrengthHint.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import "../i18n";
import PasswordStrengthHint, { passwordValid } from "./PasswordStrengthHint";

describe("passwordValid", () => {
  test("rejects empty string", () => {
    expect(passwordValid("")).toBe(false);
  });

  test("rejects 9 characters", () => {
    expect(passwordValid("abcdefg1a".slice(0, 9))).toBe(false);
  });

  test("accepts exactly 10 characters with letter and digit", () => {
    expect(passwordValid("abcdefgh1a")).toBe(true);
  });

  test("rejects letters only, 10+ chars", () => {
    expect(passwordValid("abcdefghij")).toBe(false);
  });

  test("rejects digits only, 10+ chars", () => {
    expect(passwordValid("1234567890")).toBe(false);
  });

  test("accepts mixed letters and digits, 10+ chars", () => {
    expect(passwordValid("password123")).toBe(true);
  });
});

describe("PasswordStrengthHint", () => {
  test("renders nothing when password is empty", () => {
    const { container } = render(<PasswordStrengthHint password="" />);
    expect(container).toBeEmptyDOMElement();
  });

  test("shows all three rules when password is non-empty", () => {
    render(<PasswordStrengthHint password="abc" />);
    expect(screen.getByTestId("password-hint-length")).toBeInTheDocument();
    expect(screen.getByTestId("password-hint-letter")).toBeInTheDocument();
    expect(screen.getByTestId("password-hint-digit")).toBeInTheDocument();
  });

  test("marks length rule as met once 10+ chars are entered", () => {
    render(<PasswordStrengthHint password="abcdefghij" />);
    expect(screen.getByTestId("password-hint-length")).toHaveAttribute("data-met", "true");
  });

  test("marks length rule as unmet under 10 chars", () => {
    render(<PasswordStrengthHint password="abc" />);
    expect(screen.getByTestId("password-hint-length")).toHaveAttribute("data-met", "false");
  });

  test("marks digit rule as met when a digit is present", () => {
    render(<PasswordStrengthHint password="abc1" />);
    expect(screen.getByTestId("password-hint-digit")).toHaveAttribute("data-met", "true");
  });

  test("marks letter rule as unmet when password is digits only", () => {
    render(<PasswordStrengthHint password="123456" />);
    expect(screen.getByTestId("password-hint-letter")).toHaveAttribute("data-met", "false");
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run (from `frontend/`): `npx vitest run src/components/PasswordStrengthHint.test.tsx`
Expected: FAIL — `Cannot find module './PasswordStrengthHint'`

- [ ] **Step 4: Implement the component**

Create `frontend/src/components/PasswordStrengthHint.tsx`:

```tsx
import { Check, X } from "lucide-react";
import { useTranslation } from "react-i18next";

export function passwordValid(password: string): boolean {
  return password.length >= 10 && /[A-Za-z]/.test(password) && /[0-9]/.test(password);
}

interface Rule {
  key: "length" | "letter" | "digit";
  met: boolean;
  label: string;
}

export default function PasswordStrengthHint({ password }: { password: string }) {
  const { t } = useTranslation();

  if (password.length === 0) {
    return null;
  }

  const rules: Rule[] = [
    { key: "length", met: password.length >= 10, label: t("change_password.hint_length") },
    { key: "letter", met: /[A-Za-z]/.test(password), label: t("change_password.hint_letter") },
    { key: "digit", met: /[0-9]/.test(password), label: t("change_password.hint_digit") },
  ];

  return (
    <ul className="space-y-1 mt-1" data-testid="password-strength-hint">
      {rules.map((rule) => (
        <li
          key={rule.key}
          data-testid={`password-hint-${rule.key}`}
          data-met={rule.met}
          className={`flex items-center gap-1.5 text-xs ${rule.met ? "text-green-600 dark:text-green-400" : "text-gray-500 dark:text-gray-400"}`}
        >
          {rule.met ? <Check size={14} aria-hidden="true" /> : <X size={14} aria-hidden="true" />}
          <span>{rule.label}</span>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npx vitest run src/components/PasswordStrengthHint.test.tsx`
Expected: PASS, all 10 tests green

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/PasswordStrengthHint.tsx frontend/src/components/PasswordStrengthHint.test.tsx frontend/src/i18n/he.json
git commit -m "feat: add PasswordStrengthHint component with live policy feedback"
```

---

## Task 2: Wire into ChangePasswordPage

**Files:**
- Modify: `frontend/src/pages/ChangePasswordPage.tsx`

- [ ] **Step 1: Import the component and helper**

In `frontend/src/pages/ChangePasswordPage.tsx`, change the import block at the top:

```tsx
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AxiosError } from "axios";

import { useAuth } from "../auth/AuthContext";
```

to:

```tsx
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AxiosError } from "axios";

import { useAuth } from "../auth/AuthContext";
import PasswordStrengthHint, { passwordValid } from "../components/PasswordStrengthHint";
```

- [ ] **Step 2: Remove the manual length guard in onSubmit**

Replace:

```tsx
  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (next.length < 10) {
      setError(t("change_password.min_length"));
      return;
    }
    setSubmitting(true);
```

with:

```tsx
  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
```

- [ ] **Step 3: Render the hint and gate the submit button**

Replace:

```tsx
        <label className="block">
          <span className="text-sm font-medium">{t("change_password.new")}</span>
          <input type="password" required className="mt-1 block w-full rounded-md border p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={next}
                 onChange={(e) => setNext(e.target.value)} data-testid="new-password" />
        </label>
        {error && <div className="text-rejected text-sm" data-testid="change-password-error">{error}</div>}
        <button type="submit" disabled={submitting}
                className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-medium py-2 rounded-md"
                data-testid="change-password-submit">
          {t("change_password.submit")}
        </button>
```

with:

```tsx
        <label className="block">
          <span className="text-sm font-medium">{t("change_password.new")}</span>
          <input type="password" required className="mt-1 block w-full rounded-md border p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={next}
                 onChange={(e) => setNext(e.target.value)} data-testid="new-password" />
          <PasswordStrengthHint password={next} />
        </label>
        {error && <div className="text-rejected text-sm" data-testid="change-password-error">{error}</div>}
        <button type="submit" disabled={submitting || !passwordValid(next)}
                className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-medium py-2 rounded-md"
                data-testid="change-password-submit">
          {t("change_password.submit")}
        </button>
```

- [ ] **Step 4: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ChangePasswordPage.tsx
git commit -m "feat: gate change-password submit on live PasswordStrengthHint"
```

---

## Task 3: Wire into ResetPasswordPage

**Files:**
- Modify: `frontend/src/pages/ResetPasswordPage.tsx`

- [ ] **Step 1: Import the component and helper**

Change:

```tsx
import { useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { isAxiosError } from "axios";
import { resetPassword } from "../api/auth";
```

to:

```tsx
import { useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { isAxiosError } from "axios";
import { resetPassword } from "../api/auth";
import PasswordStrengthHint, { passwordValid } from "../components/PasswordStrengthHint";
```

- [ ] **Step 2: Render the hint below the new-password field**

Replace:

```tsx
        <label className="block text-sm">
          {t("reset_password.new_password")}
          <input
            type="password"
            className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            value={password}
            onChange={e => setPassword(e.target.value)}
          />
        </label>
```

with:

```tsx
        <label className="block text-sm">
          {t("reset_password.new_password")}
          <input
            type="password"
            className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            value={password}
            onChange={e => setPassword(e.target.value)}
          />
          <PasswordStrengthHint password={password} />
        </label>
```

- [ ] **Step 3: Gate the submit button**

Replace:

```tsx
        <button
          onClick={handleSubmit}
          disabled={submitting || !password || mismatch}
          className="w-full bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
        >
```

with:

```tsx
        <button
          onClick={handleSubmit}
          disabled={submitting || !passwordValid(password) || mismatch}
          className="w-full bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
        >
```

- [ ] **Step 4: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ResetPasswordPage.tsx
git commit -m "feat: gate reset-password submit on live PasswordStrengthHint"
```

---

## Task 4: Wire into RegisterPage

**Files:**
- Modify: `frontend/src/pages/RegisterPage.tsx`

- [ ] **Step 1: Import the component and helper**

Find the import block at the top of `frontend/src/pages/RegisterPage.tsx` and add the new import alongside the existing ones (keep all existing imports, just add this line):

```tsx
import PasswordStrengthHint, { passwordValid } from "../components/PasswordStrengthHint";
```

- [ ] **Step 2: Replace the inline length-only feedback with the shared hint**

Replace:

```tsx
            <label className="block text-sm">סיסמה <span className="text-red-500">*</span>
              <input type="password" className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={form.password} onChange={e => set("password", e.target.value)} />
            </label>
            {form.password.length > 0 && form.password.length < 10 && (
              <p className="text-amber-600 dark:text-amber-400 text-xs">{`${form.password.length}/10 תווים — נדרשים לפחות 10`}</p>
            )}
            {form.password.length >= 10 && (
              <p className="text-green-600 dark:text-green-400 text-xs">✓ אורך סיסמה תקין</p>
            )}
```

with:

```tsx
            <label className="block text-sm">סיסמה <span className="text-red-500">*</span>
              <input type="password" className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={form.password} onChange={e => set("password", e.target.value)} />
              <PasswordStrengthHint password={form.password} />
            </label>
```

- [ ] **Step 3: Update the step-2 "Next" button gate**

Replace:

```tsx
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={!form.personal_number || !form.full_name || form.password.length < 10 || form.password !== form.confirm_password}
                onClick={() => setStep(3)}>{t("register.next")}</button>
```

with:

```tsx
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={!form.personal_number || !form.full_name || !passwordValid(form.password) || form.password !== form.confirm_password}
                onClick={() => setStep(3)}>{t("register.next")}</button>
```

- [ ] **Step 4: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: no errors

- [ ] **Step 5: Lint**

Run (from `frontend/`): `npm run lint`
Expected: no warnings/errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/RegisterPage.tsx
git commit -m "feat: gate registration submit on live PasswordStrengthHint"
```

---

## Task 5: Full verification

- [ ] **Step 1: Run the full frontend test suite**

Run (from `frontend/`): `npm test`
Expected: all pass, including the new `PasswordStrengthHint.test.tsx`

- [ ] **Step 2: Manual smoke test via dev server**

Start the stack per `CLAUDE.md` (`.\dev.ps1`), open http://localhost:5173, and verify:
- On `/register` step 2: typing a password shows the three live rules updating as you type; the "Next" button stays disabled until all three are green.
- On `/change-password` (logged in, via profile menu): same behavior; submit button enables only when all three rules pass.
- On `/reset-password?token=...` (use a real or stubbed token): same behavior.

- [ ] **Step 3: Final commit if any smoke-test fixes were needed**

```bash
git add frontend/
git commit -m "fix: address smoke-test findings for password strength hint"
```
(Skip this step if no fixes were needed.)

---

## Self-review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `PasswordStrengthHint` component, hidden when empty | Task 1 |
| Three live rules (length/letter/digit) with check/x icons | Task 1 |
| `passwordValid()` export | Task 1 |
| i18n keys under `change_password` | Task 1 |
| `ChangePasswordPage` wiring, remove manual guard | Task 2 |
| `ResetPasswordPage` wiring | Task 3 |
| `RegisterPage` wiring, replace partial inline check | Task 4 |
| No backend changes | N/A — confirmed no task touches `backend/` |
| Component test for `passwordValid()` boundary cases | Task 1, Step 2 |

All spec items covered. No gaps found.
