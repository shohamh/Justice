# Password Strength Hint — Design

**Goal:** Surface the server-side password complexity policy (min 10 chars, at least one letter, at least one digit — see `backend/app/services/soldiers.py`) as live client-side feedback, so users see compliance before submitting instead of hitting a server error.

**Scope:** Frontend only. No backend changes — the backend remains the source of truth and validates independently.

## Component

`frontend/src/components/PasswordStrengthHint.tsx`

- Props: `{ password: string }`
- Renders nothing when `password === ""`.
- Otherwise renders three rows, each evaluated live against `password`:
  - at least 10 characters
  - at least one letter (`/[A-Za-z]/`)
  - at least one digit (`/[0-9]/`)
- Each row shows a `lucide-react` check icon (green) when satisfied, or an x icon (muted/red) when not.
- Exports `passwordValid(password: string): boolean` — true only when all three rules pass. Used by consuming pages to gate the submit button.

## Integration

**`ChangePasswordPage.tsx`**
- Render `<PasswordStrengthHint password={next} />` below the new-password input.
- Remove the manual `next.length < 10` pre-submit check; instead disable the submit button when `!passwordValid(next)`.
- Server error handling (`password_too_short`) stays as a fallback for edge cases (e.g. stale client).

**`ResetPasswordPage.tsx`**
- Render `<PasswordStrengthHint password={password} />` below the new-password input.
- Extend the existing `disabled={submitting || !password || mismatch}` condition to also require `passwordValid(password)`.

**`RegisterPage.tsx`**
- Already has a partial inline check (length-only, `frontend/src/pages/RegisterPage.tsx:226-229`). Replace it with `<PasswordStrengthHint password={form.password} />` and gate the submit button with `passwordValid(form.password)`.

## i18n

Add to `change_password` namespace (reused by both pages, since the hint is shared UI):
- `change_password.hint_length` — "לפחות 10 תווים"
- `change_password.hint_letter` — "לפחות אות אחת"
- `change_password.hint_digit` — "לפחות ספרה אחת"

(English locale file gets matching keys.)

## Out of scope

- No change to backend validation (`backend/app/services/soldiers.py` already enforces this).
- No special-character requirement (matches existing relaxed-for-Hebrew-keyboards policy).

## Testing

- Component-level test for `passwordValid()` covering boundary cases (9 vs 10 chars, letter-only, digit-only, both).
- Existing `ChangePasswordPage`/`ResetPasswordPage` tests (if any) updated to reflect disabled-button gating instead of pre-submit error.
