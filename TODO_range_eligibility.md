# Outstanding: range-eligibility warning/info work

Follow-up to the 2026-08-10 (4) release. Items 1-6, 8, 11-13 from the original
request (plus several live-feedback items) shipped. These three did not:

## Item 7 — Range status on service profile page

Show a soldier's own range-qualification status ("מצב מטווחים") on both:
- `ProfilePage.tsx` (self-view)
- `UnifiedSoldierModal.tsx`'s profile tab (viewing another soldier)

**What exists to build on:**
- `backend/app/services/ineligible_soldiers.py` — `_valid_qualifications_by_soldier`,
  `list_ineligible_soldiers` already compute per-soldier qualification status,
  but only as part of a list-of-soldiers response (`GET /ranges/ineligible-soldiers`,
  scoped to `audience=planning|commander`, not usable for self-service).
- `frontend/src/utils/rangeEligibilityExplanation.ts` — formats a
  `DutyEligibilityFact` into Hebrew explanation text; reusable as-is.
- `frontend/src/components/dashboard/IneligibleSoldiersPanel.tsx` /
  `frontend/src/components/ranges/IneligibleSoldiersTable.tsx` — existing UI
  precedent for how this status is displayed elsewhere.

**What's missing:** a soldier-scoped backend endpoint (e.g.
`GET /soldiers/{id}/range-status`) reusing the qualification-lookup logic from
`ineligible_soldiers.py`, plus a small section in `ProfilePage.tsx` /
`UnifiedSoldierModal.tsx` rendering it.

## Item 9 — Richer warning tooltip (last range done)

Currently the weapon-ineligibility warning tooltip
(`frontend/src/utils/rangeEligibilityExplanation.ts`, consumed by
`ShiftDetailPanel.tsx`) only explains why a duty is uncovered — it has no
concept of "when did this soldier last do a qualifying range at all."

Wanted: "אין מטווחים בתוקף" / "מטווח אחרון - <type> ב<date>" (or "אין מטווחים
בתוקף" if never done one).

**Why it's not trivial:** every query in this pipeline
(`_max_qualification_valid_untils` in `weapon_eligibility.py`,
`_valid_qualifications_by_soldier` in `ineligible_soldiers.py`) filters
`valid_until >= as_of`, so expired qualifications are excluded entirely —
there is currently no query anywhere for "the soldier's most recent range
record regardless of expiry." Needs:
1. A new query: latest `SoldierRangeQualification` per soldier/type, no
   `valid_until` filter, ordered descending.
2. A new field threaded through `DutyEligibilityFact` (backend) and its
   frontend mirror in `frontend/src/api/ineligibleSoldiers.ts`.
3. Wire it into `formatRangeEligibilityExplanation`.

## Item 10 — "Expected to do X on <date>" info icon

For a soldier without a currently valid range qualification but with an
upcoming *primary* (non-reserve) range scheduled that would cover the
requirement: show an info icon "צפוי לעשות אל"ל ב11.11.26".

**What exists to build on:** the underlying query already exists —
`_future_windows_by_soldier_and_required_type()` in
`backend/app/services/weapon_eligibility.py:121-199` already filters
`is_reserve=False`, `is_draft=False`, `status=planned`, future-dated — exactly
the "primary upcoming range" concept. It currently only feeds
`qualification_source == "planned_range"` internally to explain *duty
coverage*, not as a freestanding signal.

**What's missing:** expose this as its own field/endpoint independent of any
specific duty needing coverage, and a new info-icon component (parallel to
the existing warning-icon component) reading it.

---

Items 7, 9, and 10 share the same eligibility data model (`DutyEligibilityFact`
/ `weapon_eligibility.py` / `ineligible_soldiers.py`) — worth tackling together
in one plan rather than three separate passes, since they'll likely share the
new "latest/upcoming qualification per soldier" query layer.





Also

I want the warning and information icon to be badges on the event, shown to duty managers and commanders (not plain soldiers). Remove the general warning at the top of the unit calendar page.


Don't show a warning for "אין אל"ל מעודכן" in the homepage, for soldiers that are not eligible to do duties that require אל"ל (compute this and decide whether to show dynamically, cache it so it's fast)