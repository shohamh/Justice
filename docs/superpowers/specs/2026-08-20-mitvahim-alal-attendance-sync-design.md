# Sync מטווחים/אל"ל attendance into profile dates + expiry notifications

Date: 2026-08-20

## Background

The soldier profile has two manually-entered date fields,
`last_mitvahim_date` and `last_alal_date` (`backend/app/db/models.py`),
which already feed the eligibility check in `backend/app/services/eligibility.py`
(a simple `last_date + validity_months` expiry) and drive the existing
home-page warning banner (`frontend/src/components/dashboard/AlertBanners.tsx`).

Separately, there is a full מטווחים (range) subsystem — `RangeEvent`,
`RangeAssignment`, `SoldierRangeQualification` (`backend/app/services/ranges.py`)
— that already records per-event attendance and computed qualification
validity, but is currently opt-in (`mitvachim.enabled` setting, off by
default) and **never writes back** to the two profile date fields. So a
soldier who attends a real, in-system מטווח doesn't get their profile date
(and therefore their eligibility / home-page warning) updated — it stays
whatever was last typed in at registration or by an admin.

This spec covers two independent, small changes:
1. Sync attendance back onto the profile date fields.
2. Add a proactive notification for approaching/passed expiry (the
   home-page banner already warns visually, but only when the soldier
   happens to visit the home page).

Both keep the two existing eligibility systems (legacy date-based,
newer qualification-based) as-is and decoupled — this is purely about
keeping the legacy date fields honest, not consolidating the two systems.

## 1. Sync range attendance into `last_mitvahim_date` / `last_alal_date`

**Where:** `backend/app/services/ranges.py`, inside `mark_attendance()`,
at the point where a `SoldierRangeQualification` row is recorded for a
`present` attendance (`_record_qualification`, ~line 503-508).

**On marking present:**
- Map `RangeType` to the profile field: `laser` / `live` → `last_mitvahim_date`,
  `alal` → `last_alal_date`.
- Update the field as `new_value = max(current_value, event.date)` —
  i.e. only move the date forward. A backdated or out-of-order event
  attendance record never overwrites a more recent existing value
  (whether that value came from a prior sync or a manual/imported entry).

**On reversal** (attendance changed away from `present`, or the
`RangeAssignment`/`RangeEvent` is deleted):
- Recompute the field as the max `event.date` among the soldier's
  remaining `present` assignments of that category (mitvahim: `laser`/`live`;
  alal: `alal`).
- If no such assignments remain, leave the field untouched — do not
  clear it. It may still hold a legitimate manually-entered or imported
  value that predates any tracked range event, and we have no way to
  distinguish that from a synced value once merged.

**No changes to `eligibility.py`** — it already reads these two fields
directly, so eligibility checks and `AlertBanners.tsx` automatically
reflect real attendance once the fields are kept in sync.

## 2. Proactive expiry notification

**Settings (reused, none new):** `home.mitvahim_validity_days`,
`home.mitvahim_warn_days`, `home.alal_validity_days`, `home.alal_warn_days`
— the same settings already driving `AlertBanners.tsx`, so the banner and
the notification always agree on thresholds.

**New worker:** `backend/app/qualification_expiry_worker.py`, following
the daily-loop pattern in `backend/app/rank_advancement_worker.py`
(`while True: await asyncio.sleep(86400)` then run checks via
`asyncio.to_thread`, wrapped in try/except logging). Registered in
`backend/app/main.py` alongside the other background workers
(`run_email_worker`, `run_range_reminder_worker`, etc.).

**Check logic**, run once per day, separately for מטווחים and אל"ל
(אל"ל scoped to soldiers where `is_alal_relevant()` is true, same helper
`AlertBanners.tsx` uses):
- `expiry = last_date + validity_days`
- If `expiry == today + warn_days` → notify "expiring soon" (fires exactly
  once, on the boundary day — same exact-date-match trick
  `rank_advancement_worker.py` uses to avoid repeat notifications).
- If `expiry == today` → notify "expired" (also fires exactly once).

**New `NotificationType` values** (`backend/app/db/models.py`):
`mitvahim_expiring_soon`, `mitvahim_expired`, `alal_expiring_soon`,
`alal_expired`.

**Audience:** soldier + commander chain. Using the existing
`create_notification()` helper (`backend/app/services/notifications.py`)
gets this for free — it already cascades most notification types to the
soldier's relevant commanders.

**i18n:** add Hebrew title/body strings for the four new notification
types to `frontend/src/i18n/he.json`. Check for existing similar keys
first (this repo has had silent duplicate-key bugs before when a
shared-looking key was reused across unrelated call sites).

## Testing

- `mark_attendance` unit tests: date advances on a newer present event,
  is a no-op on an older one, and correctly recomputes (or leaves
  untouched) on reversal.
- Worker unit tests: fires "expiring soon" exactly on the warn-day
  boundary, fires "expired" exactly on the expiry day, doesn't double-fire
  on adjacent days, skips אל"ל for non-`alal_relevant` soldiers, and
  confirms the commander-cascade happens via `create_notification`.
- A regression test confirming a synced date flows through the existing
  `eligibility.py` check correctly — this is the crux of the feature even
  though `eligibility.py` itself isn't changed.
- No frontend changes needed — `AlertBanners.tsx` already works correctly
  once the backend dates are kept in sync.
