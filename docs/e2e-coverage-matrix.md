# Browser E2E coverage matrix

The default browser projects are Chrome at 1440x1000 and 390x844. Tests run serially against a dedicated seeded PostgreSQL database.

| Role | Journey | Critical assertion | Viewports | Tier | Spec |
| --- | --- | --- | --- | --- | --- |
| Soldier | Submit personal request | Created request remains visible after reload | Desktop/mobile | Smoke | `smoke/soldier_requests.spec.ts` |
| Soldier, commander, duty manager | Approve request | Each approval advances visible status | Desktop/mobile | Smoke | `smoke/approval_workflow.spec.ts` |
| Soldier, unauthorized soldier | Authorization boundary | Forbidden reviewer action does not mutate request | Desktop/mobile | Smoke | `smoke/authorization_boundaries.spec.ts` |
| Soldier | Core views | Home, requests, calendar, and refresh render without page errors | Desktop/mobile | Smoke | `smoke/regular_user_views.spec.ts` |
| Admin | Planning configuration | Configuration page renders real duty types/locations | Desktop/mobile | Full | `smoke/admin_configuration.spec.ts` |
| Admin | Hierarchy table | Filtering, sorting, and empty state are usable | Desktop/mobile | Full | `smoke/table_interactions.spec.ts` |
| Admin | Seeded navigation | Hierarchy, calendar, transparency render seeded data | Desktop/mobile | Smoke | `seed_views.spec.ts` |
| Duty manager, commander, soldiers, reserves | Multi-user duty problems | Algorithm and manual assignment plus exemption, Gimelim, absence, Hakpaza, reserve replacement, and visible commander problem state | Desktop | Full | `smoke/multi_user_duty_problems.spec.ts` |
| Soldiers, commander, duty manager | Duty swaps | Marketplace ask+free cover, board trade cover, take-free, and proactive offer-swap journeys; dual-role (commander/duty-manager) manager approval exercised independently per (side, approver_kind); notification bell click-through (including a case where the destination tab genuinely shows the row); post-finalize duty ownership verified on `/my-duties`. `take-free` is intentionally covered (it does have a UI path, via `OfferSwapModal`'s free radio); the calendar's "shift-modal claim" entry point is intentionally NOT covered — confirmed unreachable for a plain soldier (`GET /swaps/for-assignment/{id}` 403s for non-owners without `SWAP_APPROVE`), flagged separately for a fix. | Desktop | Full | `smoke/swaps.spec.ts` |
| Duty manager, commander | Range scheduling, attendance, and excusal | Event creation + primary/reserve assignment via the verified candidate-checkbox testids; attendance marked on the seeded past event and confirmed via the read-only status text after refresh; self-excusal + duty-manager decision confirmed via the real post-approval effect (assignment deleted, reserve promoted into the primary slot, pending queue empties) rather than a nonexistent "approved" badge; qualification tab renders an eligibility warning. Self-excusal is driven as `commander` rather than a plain soldier — confirmed via `GET /ranges/{event_id}`'s authorization that a plain soldier assigned to a `dutyManager`-created event has no UI path to view it at all (no assignee exception on that route), flagged separately for a fix. | Desktop | Full | `smoke/ranges.spec.ts` |

Retry-passing tests remain failures for triage; a retry is diagnostic evidence, not a clean pass.
