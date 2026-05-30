# v2 Re-scope — Brainstorm

**Date:** 2026-05-30
**Status:** Agreed scope, pre-plan
**Supersedes:** the v2 sketch in §9.3 of [the master design](2026-05-27-army-duty-management-design.md)

---

## Why re-scope

The original v2 (design §9.3) bundled four things — replacement marketplace, greedy
online assignment, punishment duties, and a compensation workflow — sketched at the very
start of the project. After slices 1–10 (v1 foundation + v1.5 CP-SAT algorithm + shifts),
the real priorities have shifted. This document re-scopes v2 around what's actually wanted now.

## Problem statement

Two real-world needs anchor v2:

1. **Soldiers need to swap/cover duties** — both by asking a specific peer and by posting to
   an open board — without the DM hand-editing the roster every time.
2. **The unit runs the same shifts over and over.** Building each `duty_shift` by hand is
   tedious. The DM wants reusable recurring shift definitions with sensible defaults
   (e.g. default number of soldiers per shift).

## Scope — two features, one v2 plan

The two features are designed together as a single v2 effort and sliced internally during
planning (not shipped as separate sequential projects).

### Feature A — Shift templates + recurring shifts

- **A template is primarily a recurrence rule** that generates concrete `duty_shifts`. It
  also carries the shift attributes the generated shifts need: duty type, location,
  time-of-day, **default number of soldiers**, and eligibility requirements (mirrors the
  `DutyType.requirements` JSONB pattern from slice 8).
- **Recurrence is a simple weekly pattern:** pick days-of-week + time-of-day
  (e.g. Sun/Tue/Thu, 22:00–06:00), bounded by start/end dates. No iCal/RRULE complexity.
- **Org-wide, DM-managed library.** One shared set of templates at the top; any DM can use
  any template when generating shifts for their scope. Matches the single-branch pilot;
  per-unit scoping is a later concern if multi-branch ever lands.
- **Hybrid generation.** A background job continuously keeps a rolling horizon
  (e.g. the next 30 days) of `duty_shifts` materialized from active templates. The DM can
  **preview, edit, or cancel** upcoming generated shifts before they're filled. Generated
  shifts start **empty**; the existing CP-SAT algorithm fills them exactly as today.
  Generation is audited and idempotent (re-rolling a window never duplicates shifts).

Builds directly on the first-class `duty_shifts` entity (slices 9–10).

### Feature B — Duty swapping / cover

- **Two mechanisms, both in scope:**
  - **Direct request** — soldier A asks a specific soldier B to cover/trade.
  - **Open marketplace** — A posts "need cover for this duty"; any eligible peer can
    offer/claim, ranked by hierarchy distance + match quality (the design's
    `replacement_listings` / `replacement_offers` idea).
- **One-way cover is the primary flow:** B takes A's duty; the score follows B automatically
  via the existing `duty_day_overrides.effective_soldier_id` layer. **Two-way trade**
  (A and B exchange duties) is built on the same primitive.
- **Configurable approval.** A `system_settings` toggle (mirroring
  `constraints.require_manager_approval`) decides whether an agreed swap needs approval
  before it takes effect. **When approval is required, both sides' managers approve** —
  each involved soldier's commander/DM — which matters for cross-unit covers and two-way
  trades. With approval off, an eligible swap applies immediately.
- **Hard constraints always respected:** the covering soldier must pass eligibility,
  exemptions, and no-overlap before a cover can apply (DM force-override is an open question).

## Explicitly out / deferred

Carried over from the old v2 sketch but **not** in this re-scope:

- Greedy / online single-duty assignment mode (the algorithm still runs in batch).
- Punishment duties (no-show penalties, הקפצה-triggered punitive no-score duties).
- Structured compensation workflow on `score_adjustments`.
- Notifications (SMS / email / push) for swap offers, approvals, or generated shifts.
- Per-unit template ownership / inheritance (org-wide library only for now).

## Open questions for the plan stage

- **Template entity:** new `shift_templates` table; how the weekly rule + time-of-day +
  default soldier count + eligibility are stored (structured columns vs small JSONB).
- **Auto-roll mechanics:** horizon length; what drives the background roll (FastAPI
  BackgroundTasks, a periodic task, or roll-on-access); how a DM-edited or DM-cancelled
  generated shift is protected from being re-created by the next roll; dedupe key for idempotency.
- **Swap/cover entities:** likely `replacement_listings` + `replacement_offers` (open board)
  plus a direct-request path; how an accepted swap maps to a `duty_day_override`; statuses.
- **Two-sided approval:** how the two approvers are resolved, ordering, and what happens on
  partial approval / one side rejecting.
- **Eligibility override:** can a DM force a cover by an otherwise-ineligible soldier?
- **Match-quality ranking:** concrete definition for marketplace ordering (start simple —
  hierarchy distance + fairness — and refine).
- **Published vs proposed:** can soldiers only swap/cover *published* shifts?

## Starting point

The repo is clean and current as of commit `f1c349a` (soldier profile, field-update
approvals, exemption `is_global`, duty-config/approvals UI). Backend imports fine; migrations
through `0022`. v2 builds on the first-class `duty_shifts` entity and the
`duty_day_overrides` layer already in place.

## Success criteria

- **Feature A:** a DM defines a recurring weekly template once; the rolling horizon
  auto-fills the calendar with empty shifts (DM can preview/edit/cancel before they're
  filled); the algorithm fills them — replacing manual per-shift creation. Generation is
  audited and idempotent.
- **Feature B:** a soldier arranges cover either by asking a specific peer or by posting to
  the board; with approval off it applies immediately (respecting eligibility), with approval
  on it queues to both sides' managers; the scoreboard correctly credits whoever actually
  does the duty.
