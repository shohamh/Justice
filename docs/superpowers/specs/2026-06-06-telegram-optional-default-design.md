# Design: Telegram Linking Optional by Default

**Date:** 2026-06-06
**Status:** Approved

## Summary

Make Telegram linking optional by default. New soldiers are not forced to link a Telegram account after registration unless an admin has explicitly enabled the `registration.telegram_required` system setting.

## Root Cause

`backend/app/routes/me.py` reads the `registration.telegram_required` setting and exposes it to the frontend via the `/me` response. When the setting has not yet been saved (e.g., a fresh deployment), the `get_setting()` call throws and the `except` block falls back to `telegram_required = True`, making Telegram mandatory. The intended default is `False`.

## What Already Works

- **System Settings UI** (`frontend/src/pages/SystemSettingsPage.tsx`) — renders the `registration.telegram_required` toggle with `defaultValue: false`. No change needed.
- **Skip button** (`frontend/src/pages/TelegramSetupPage.tsx`) — already rendered when `!telegramRequired`. No change needed.
- **TelegramGate** (`frontend/src/App.tsx`) — already redirects only when `telegramRequired && !telegramLinked`. No change needed.

## Change

**File:** `backend/app/routes/me.py`

```python
# Before
except Exception:
    telegram_required = True

# After
except Exception:
    telegram_required = False  # default: telegram linking is optional
```

## Testing

Existing integration tests cover the `/me` endpoint. One additional case:

- When `registration.telegram_required` has never been saved, `GET /me` returns `telegram_required: false`.

## Out of Scope

- Seeding the setting in a migration (not needed; the fallback is the correct fix)
- Any UI or frontend changes
