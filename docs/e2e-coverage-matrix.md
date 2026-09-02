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

Retry-passing tests remain failures for triage; a retry is diagnostic evidence, not a clean pass.
