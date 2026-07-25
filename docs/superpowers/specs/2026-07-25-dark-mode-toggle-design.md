# Dark mode toggle — design spec

## Goal

Add a sun/moon toggle to the app header that lets a user switch between light
mode, dark mode, and "follow system preference". The choice is saved to the
user's profile so it follows them across devices/sessions, with a
`localStorage` cache used only to avoid a flash-of-wrong-theme before the
profile loads.

## Current state

- `frontend/tailwind.config.cjs` has `darkMode: "media"` — dark styling is
  driven purely by the OS `prefers-color-scheme`, with no manual override.
  Components already use `dark:` Tailwind classes extensively (e.g.
  `frontend/src/components/Layout.tsx`), so no new dark-mode styling is
  needed — only the toggle mechanism.
- The header lives in `frontend/src/components/Layout.tsx`. The right-side
  icon group currently holds: help icon, `NotificationBell`, logout button.
- There's an existing precedent for a lightweight, non-RBAC'd, per-user
  preference endpoint: `GET/PUT /notifications/preferences` in
  `backend/app/routes/notifications.py`, keyed off `user.id` from the auth
  dependency, no hierarchy-based authorization, no audit log.
- `Soldier` (`backend/app/db/models.py`) is the user table (`soldiers`).
  Profile fields are updated either via a DM/admin-authorized direct PATCH
  (`PATCH /soldiers/{id}/profile`, RBAC-checked via `Action.SOLDIER_UPDATE`)
  or via an approval workflow for self-service edits to protected fields
  (`submit_field_update`). Neither fits a pure UI preference — it should
  save instantly for the user themselves with no approval and no audit
  trail noise.

## Backend

**Migration:** add `theme_preference` column to `soldiers`:
- Type: `Text`
- Allowed values (enforced at the Pydantic layer, not a DB enum, to keep
  the migration simple): `"light" | "dark" | "system"`
- `server_default='system'`, `default="system"`

**New endpoint** in `backend/app/routes/soldiers.py`, following the
notifications-preferences pattern:

```
PUT /soldiers/me/theme-preference
body: { "theme_preference": "light" | "dark" | "system" }
-> 200 { "theme_preference": "light" | "dark" | "system" }
```

- Requires only authentication (`require_password_changed` dependency,
  same as other self-service endpoints) — no hierarchy-based `authorize()`
  check, since a user is always allowed to set their own UI preference.
- No audit log entry (matches notification preferences — this isn't a
  personnel record change).
- Validated via Pydantic `Literal["light", "dark", "system"]`.

**Response schema:** add `theme_preference` to the `Me`/`SoldierOut` output
so it's returned from `GET /auth/me` (or wherever `fetchMe()` hits) and
available in `AuthContext` immediately after login.

## Frontend

**Tailwind config:** switch `frontend/tailwind.config.cjs` `darkMode` from
`"media"` to `"class"`. All existing `dark:` classes continue to work
unchanged — they'll now respond to a `dark` class on `<html>` instead of
the OS media query directly.

**Pre-mount flash prevention:** add a small inline script in
`frontend/index.html` `<head>`, before the app bundle loads:
- Read `localStorage.getItem("theme")` (`"light" | "dark" | "system"`,
  default `"system"` if absent).
- If `"dark"`, or (`"system"` and `matchMedia('(prefers-color-scheme: dark)').matches`),
  add the `dark` class to `<html>`. Otherwise leave it off.

**`frontend/src/theme/ThemeContext.tsx`** (new):
- State: `theme: "light" | "dark" | "system"`, initialized from
  `localStorage`.
- `setTheme(next)`:
  1. Update React state.
  2. Write to `localStorage` immediately.
  3. Apply/remove the `dark` class on `document.documentElement` based on
     the resolved value (resolving `"system"` via `matchMedia`).
  4. Fire `PUT /soldiers/me/theme-preference` in the background
     (optimistic — UI already updated; on failure, the choice still
     persists locally in `localStorage` for this device but a toast/log
     notes the sync failed silently, no blocking UI).
- When `theme === "system"`, subscribe to
  `matchMedia('(prefers-color-scheme: dark)')` changes and re-resolve the
  `dark` class live, so OS-level changes are picked up without a page
  reload.
- On login / `fetchMe()` resolving: if `user.theme_preference` differs from
  what's currently applied, adopt the profile's value as source of truth,
  update `localStorage` and the applied class. This makes the profile
  value authoritative once known — `localStorage` is only a bridge for the
  pre-auth/first-paint moment.
- Wrap the app with `ThemeProvider` in `frontend/src/main.tsx` (or
  wherever the top-level providers are).

**`frontend/src/api/theme.ts`** (new): thin wrapper —
`updateThemePreference(theme: "light" | "dark" | "system"): Promise<void>`
calling the new `PUT` endpoint.

**`Layout.tsx`:** add a toggle button to the right-side icon group, next to
the help icon. Behavior: click cycles Light → Dark → System → Light. Icon
shown reflects current mode (`Sun` / `Moon` / `Monitor` from
`lucide-react`, already a project dependency). `aria-label` describes the
current state and what clicking does, following the existing pattern of
Hebrew labels on icon-only buttons in this header (e.g. `aria-label="עזרה"`
for help).

## Testing

- Backend: targeted pytest for the new endpoint — requires auth, rejects
  invalid values, round-trips a valid value, returns it on the user's next
  `/me` fetch. Not a full-suite run.
- Frontend: vitest for `ThemeContext` — cycling order, `localStorage`
  persistence, `dark` class application, and system-preference resolution;
  plus a test that clicking the `Layout` toggle button advances the state
  and applies the class change.

## Out of scope

- No new preferences table — a single column is sufficient for one
  setting.
- No admin-facing control over other users' theme.
- No visual/style changes beyond what `dark:` classes already cover.
