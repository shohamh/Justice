# Slice 3: Duty Configuration & Exemptions — Design

**Status:** Approved (brainstorm 2026-05-29). Builds on Slice 2 (`slice-3-duty-config-and-exemptions` branched off `slice-2-hierarchy-and-soldiers`, which is not yet merged to `master`).

## Goal

Add the duty-manager configuration surfaces and the exemption (פטור) system on top of Slice 2: global config for `duty_types`, `duty_locations`, `exemption_types`, and the `exemption_duty_type_map`, plus granting/revoking scoped `soldier_exemptions` — every mutation audited, all behind the role + scope authorization layer. No duty assignments, overrides, scoring, personal constraints, or algorithm yet (those are slices 4–5).

## Spec coverage

Implements design-doc §4.1 tables `duty_types`, `duty_locations`, `exemption_types`, `exemption_duty_type_map`, `soldier_exemptions`, and §5.2 permission rows "Grant / revoke exemptions", "View any soldier's exemptions (incl. private reason)", "View own active exemptions", "Edit duty type scoring", "Edit exemption ↔ duty-type mapping". Page surfaces: a duty-config settings page and the exemptions section on the profile/soldier view, plus a role-gated sidebar entry.

Explicitly **out** of this slice: `personal_constraints`, `duty_assignments`, `duty_day_overrides`, score computation, the fairness algorithm, and the v2 social layer.

## Decisions locked during brainstorming (2026-05-29)

- **Scope:** "Duty config + exemptions" — the smallest coherent chunk that sets up everything duty assignments will later reference.
- **Full stack, one branch, one PR** — backend (migrations, services, routes, RBAC, audit, tests) **and** the Hebrew RTL frontend (duty-config page, exemptions UI, i18n, Playwright e2e), mirroring Slice 2's shape.
- **Admin gets a global override:** the design restricts duty config to `duty_manager` and exemption-granting to commander(subtree)/DM(scope), excluding admin. We relax this so the bootstrap admin can also manage duty config and grant exemptions globally. This is consistent with the existing `authz.can()` `role == "admin"` short-circuit (admin already passes every action), and for duty config we use a coarse `require_roles("duty_manager", "admin")` gate.
- **Revoke = soft end-date:** revoking a currently-active `soldier_exemption` sets `end_date = today` (preserving the historical active window that slice 4/5 scoring needs); revoking a not-yet-started (future `start_date`) exemption hard-deletes the row. No `status` column added — `end_date` already encodes the active window.
- **Architecture: two domain service modules** (`duty_config.py`, `exemptions.py`) mirroring the Slice 2 grain — not one-module-per-table (boilerplate) and not a generic CRUD abstraction (premature, hides per-table rules).

## Architecture

Duty config (`duty_types`, `duty_locations`, `exemption_types`, `exemption_duty_type_map`) is **global** configuration — no hierarchy node attached — so it is guarded by a coarse role gate, not the scoped authorization engine. Exemptions (`soldier_exemptions`) are **scoped**: a grant/revoke/read is permitted when the actor's scope covers the *target soldier's* hierarchy node, resolved through the existing `app/auth/authz.py` engine.

Same layering as Slice 2: pure service functions (no HTTP) that mutate + `write_audit` in one transaction and raise domain errors; thin routes that parse the request, load targets, `authorize(...)`/role-gate, call the service, and return Pydantic models.

```
                 ┌─────────────────────────────────────┐
  duty-config →  │ require_roles("duty_manager","admin")│ → duty_config service → audit
  routes         └─────────────────────────────────────┘
                 ┌─────────────────────────────────────┐
  exemptions  →  │ authorize(EXEMPTION_*, target=node)  │ → exemptions service   → audit
  routes         │   or route-level self-read check     │
                 └─────────────────────────────────────┘
```

## Data model (migrations 0007–0011)

Next migration after Slice 2's `0006`. ORM models appended to `app/db/models.py`.

- **0007 `duty_types`** — `id uuid PK` (`gen_random_uuid()`), `name text NOT NULL UNIQUE`, `score_per_day numeric(6,2) NOT NULL`, `description text NULL`, `active boolean NOT NULL DEFAULT true`, `created_at`, `updated_at`.
- **0008 `duty_locations`** — `id uuid PK`, `name text NOT NULL`, `base text NULL`, `active boolean NOT NULL DEFAULT true`, `created_at`, `updated_at`.
- **0009 `exemption_types`** — `id uuid PK`, `name text NOT NULL UNIQUE`, `description text NULL`, `created_at`, `updated_at`.
- **0010 `exemption_duty_type_map`** — composite PK `(exemption_type_id, duty_type_id)`; both columns FK with `ON DELETE CASCADE` (deleting either side removes the mapping row).
- **0011 `soldier_exemptions`** — `id uuid PK`, `soldier_id uuid FK→soldiers(id) ON DELETE CASCADE`, `exemption_type_id uuid FK→exemption_types(id) ON DELETE RESTRICT`, `start_date date NOT NULL`, `end_date date NULL` (NULL = forever), `reason text NULL`, `granted_by uuid FK→soldiers(id) ON DELETE SET NULL`, `granted_at timestamptz NOT NULL DEFAULT now()`. Index `(soldier_id, start_date)`.

Soft-deactivation: `duty_types`, `duty_locations`, `exemption_types` are never hard-deleted via the API while referenced — they carry an `active` flag (exemption_types may be hard-deleted only when unreferenced by the map and by any grant). This keeps historical references intact for slice 4/5.

## Authorization

- **New actions** in `app/auth/authz.py` `Action`: `EXEMPTION_GRANT = "exemption.grant"`, `EXEMPTION_READ = "exemption.read"`.
- Add both to `_DM_ACTIONS` and `_COMMANDER_ACTIONS`. Admin already returns `True` for every action via the `role == "admin"` short-circuit, so no change is needed there.
- **Target node** for an exemption action = the target soldier's `hierarchy_node_id`. If the soldier has no node, `_node_in_scope` is false for everyone except admin — only admin can act, which is acceptable.
- **Self-read:** a plain soldier reading their **own** exemptions is allowed by a route-level `user.id == soldier_id` check (mirrors `/api/me`), not via `can()`.
- **Duty config:** new dependency usage `require_roles("duty_manager", "admin")` (the factory already exists from Slice 2) plus `require_password_changed`.

## Services

**`app/services/duty_config.py`** — raises `DutyConfigError`; no HTTP. All mutations `write_audit` in the same transaction.

- `create_duty_type / update_duty_type / set_duty_type_active` — `name` uniqueness, `score_per_day >= 0`.
- `create_location / update_location / set_location_active`.
- `create_exemption_type / update_exemption_type / delete_exemption_type` (delete only when unreferenced by the map and by any `soldier_exemptions`).
- `map_exemption_to_duty_type / unmap_exemption_from_duty_type` — idempotent; both ids must exist.
- Audit actions: `duty_type.create|update|set_active`, `duty_location.create|update|set_active`, `exemption_type.create|update|delete`, `exemption_map.add|remove`.

**`app/services/exemptions.py`** — raises `ExemptionError`; no HTTP.

- `grant_exemption(session, *, soldier_id, exemption_type_id, start_date, end_date, reason, actor_id)` — soldier + type must exist; if both dates set, `end_date >= start_date`. Audited `exemption.grant`.
- `revoke_exemption(session, *, exemption_id, actor_id)` — if `start_date <= today`: set `end_date = today`; else delete the row. Audited `exemption.revoke`.
- `list_exemptions(session, *, soldier_id)` — all rows for a soldier (caller already authorized).
- `active_exemptions(session, *, soldier_id, on_date)` — pure query: rows where `start_date <= on_date AND (end_date IS NULL OR end_date >= on_date)`. Unit-tested now; consumed by slice 4/5 scoring.

## API routes

Thin routes (parse → load → authorize/role-gate → service → Pydantic out). Both routers wired in `app/main.py` under `/api`.

**`app/routes/duty_config.py`** — `prefix="/duty-config"`; every route depends on `require_roles("duty_manager","admin")` and `require_password_changed`:

- `GET /duty-types`, `POST /duty-types`, `PATCH /duty-types/{id}` (name/score/description/active).
- `GET /locations`, `POST /locations`, `PATCH /locations/{id}`.
- `GET /exemption-types`, `POST /exemption-types`, `PATCH /exemption-types/{id}`, `DELETE /exemption-types/{id}`.
- `GET /exemption-types/{id}/duty-types` (the mapped duty-type ids), `PUT /exemption-types/{id}/duty-types` (set the full list — diff against current, add/remove map rows).

**`app/routes/exemptions.py`** — `prefix="/soldiers/{soldier_id}/exemptions"`:

- `GET ""` — list; `authorize(EXEMPTION_READ, target=soldier's node)` **or** `user.id == soldier_id` (self read-only).
- `POST ""` — grant; `authorize(EXEMPTION_GRANT, …)`.
- `DELETE /{exemption_id}` — revoke; `authorize(EXEMPTION_GRANT, …)`; the exemption must belong to `soldier_id`.

## Frontend

- **API clients**: `src/api/dutyConfig.ts`, `src/api/exemptions.ts` — slice-2 axios pattern, typed responses.
- **`src/pages/DutyConfigPage.tsx`** — duty_manager/admin page, three tabbed sections: duty types (name, score/day, active toggle), locations (name, base, active), exemption types (name + multi-select of exempted duty types → the map). Reuses `ConfirmDialog` for deactivations.
- **Exemptions section** on the profile/soldier view: lists a soldier's exemptions; a grant form (type, start, optional end, reason) and revoke button shown only to authorized viewers (commander/DM/admin); read-only on the user's own profile.
- **`Layout.tsx`**: role-gated sidebar entry "הגדרות תורנויות" for duty_manager/admin. **`App.tsx`**: the new route.
- **i18n**: new Hebrew strings in `src/i18n/he.json`.

## Error handling

- Service layer raises `DutyConfigError` / `ExemptionError`; routes translate to `HTTPException(400)` with a stable `detail` code (`name_taken`, `score_negative`, `bad_date_range`, `soldier_not_found`, `exemption_type_not_found`, `exemption_not_found`, `exemption_mismatch`). The one exception is `exemption_type_in_use` (deleting a still-referenced exemption type), which returns `409 Conflict` — a referential conflict rather than a malformed request.
- Authorization failures raise `403` (`forbidden`) via `authorize()` / `require_roles`; `must_change_password` users get `403 must_change_password` from `require_password_changed`.
- Name-uniqueness is enforced in the service *and* by a DB unique constraint as a backstop.

## Testing (TDD throughout)

- **Unit** — `tests/unit/test_duty_config_service.py` (name uniqueness, `score_per_day >= 0`, map idempotency, exemption-type delete-only-when-unreferenced, audit rows), `tests/unit/test_exemptions_service.py` (grant validation, revoke soft-vs-hard fork, `active_exemptions` window incl. NULL end_date and boundary dates).
- **Integration** — `tests/integration/test_duty_config_api.py` (DM + admin allowed; soldier/commander 403; CRUD + active toggle; map PUT diff), `tests/integration/test_exemptions_api.py` (commander-in-subtree grants; out-of-subtree 403; soldier reads own / cannot grant; soft vs hard revoke; cross-soldier exemption id rejected).
- **RBAC** — extend `tests/integration/test_rbac_matrix.py` with the exemption actions and the duty-config role gate.
- **e2e** — `tests/e2e/duty_config.spec.ts` (admin creates a duty type and maps an exemption type), `tests/e2e/exemptions.spec.ts` (DM grants an exemption to a soldier, sees it listed, revokes it).

## File structure produced by this slice

```
backend/
├── alembic/versions/
│   ├── 0007_create_duty_types.py
│   ├── 0008_create_duty_locations.py
│   ├── 0009_create_exemption_types.py
│   ├── 0010_create_exemption_duty_type_map.py
│   └── 0011_create_soldier_exemptions.py
├── app/
│   ├── db/models.py                 # +DutyType, DutyLocation, ExemptionType, ExemptionDutyTypeMap, SoldierExemption
│   ├── auth/authz.py                # +EXEMPTION_GRANT/READ actions
│   ├── services/
│   │   ├── duty_config.py           # new
│   │   └── exemptions.py            # new
│   ├── routes/
│   │   ├── duty_config.py           # new
│   │   └── exemptions.py            # new
│   └── main.py                      # wire two routers
└── tests/
    ├── unit/{test_duty_config_service,test_exemptions_service}.py
    └── integration/{test_duty_config_api,test_exemptions_api}.py  # + rbac matrix edits

frontend/
├── src/
│   ├── api/{dutyConfig,exemptions}.ts
│   ├── pages/DutyConfigPage.tsx
│   ├── components/Layout.tsx        # +sidebar entry
│   ├── App.tsx                      # +route
│   └── i18n/he.json                 # +strings
└── tests/e2e/{duty_config,exemptions}.spec.ts
```
