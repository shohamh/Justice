# HR Field Mapping & Local-Override Tracking (Subsystem 2 of HR Integration) — Design

## Context

This is subsystem 2 of the larger HR integration project (see
[2026-09-22-hr-api-client-design.md](2026-09-22-hr-api-client-design.md)
for the full six-subsystem roadmap and subsystem 1, the `HrApiClient`,
which is already built and merged to `dev`).

Subsystem roadmap recap:
1. HR API client + fixtures — **done**
2. **Data model & field mapping — this document**
3. Org hierarchy sync (HR groups → Justice tree, auto-create nodes, holding
   node fallback)
4. Person sync engine (idempotent per-record transactional sync, vanished
   flagging, abort-on-anomaly safety, dependent-logic reruns)
5. Activation-code security system
6. Admin review UI + cron wiring

This document specs **subsystem 2 only**: translating a raw `HrUser` (from
subsystem 1's `app/services/hr/schemas.py`) into Justice's field vocabulary,
storing the raw DTO and sync bookkeeping, and giving admins a way to lock a
field against future HR overwrites via the *existing* dual-approval flow.

**Non-goals** (deferred to later subsystems):
- Creating or updating `Soldier` rows (subsystem 4's person sync engine
  calls into this subsystem's mapping function per record, but the
  create/update/loop/transaction/pagination logic lives there).
- Looping over all HR users or talking to `HrApiClient` at all — this
  subsystem operates on one `HrUser` at a time, purely as data
  transformation, testable entirely against fixtures.
- Hierarchy node placement (subsystem 3).
- Downloading/storing image bytes from HR's `/image` endpoint — `photo`
  maps to `imageUrl` as a plain URL string, matching the existing
  `Soldier.profile_picture_url` column's existing usage (a URL, not a
  blob).
- Any FastAPI route or frontend UI.

## Goals

- A `map_hr_user(hr_user: HrUser) -> MappedSoldierFields | HeldForReview`
  pure function that translates one `HrUser` into Justice's field
  vocabulary, or reports exactly why it couldn't.
- A new `soldier_hr_profile` table storing the raw DTO, sync bookkeeping,
  and the set of fields an admin has locally overridden.
- A hook into the *existing* `SoldierFieldUpdate` dual-approval flow
  (`app/services/soldiers.py::approve_field_update`) so that approving an
  admin's edit to an HR-owned field marks it overridden — reusing existing
  approval infrastructure rather than building a parallel one.
- A `record_sync_divergence` audit helper (used by subsystem 4 later) that
  logs when a sync run skips an overridden field.

## Field mapping

### Vocabulary translation — explicit dicts, never guessed

Per the design spec's "Unknowns" rule: an HR value with no entry in the
relevant map is **held for review**, never silently passed through or
fuzzy-matched.

```python
GENDER_MAP: dict[str, str] = {
    "male": "male",
    "female": "female",
}

# Keys are HR's raw `rank` string; values are Justice's existing rank
# strings from eligibility.ENLISTED_RANKS / OFFICER_RANKS. Identity-shaped
# today because no real HR fixture data is available to confirm otherwise
# — if HR uses different rank spellings/abbreviations, this map is where
# that translation goes, one confirmed entry at a time.
RANK_MAP: dict[str, str] = {rank: rank for rank in (*ENLISTED_RANKS, *OFFICER_RANKS)}

# HR's `servicType` -> Soldier.rank_track ("חובה" mandatory / "קבע" career).
# Placeholder mapping — TODO: confirm HR's actual servicType values against
# real fixture data; currently only maps the values named in the original
# integration brief ("chova"/"kva" as HR API convention examples).
SERVICE_TYPE_TO_TRACK_MAP: dict[str, str] = {
    "chova": "חובה",
    "kva": "קבע",
}
```

`RANK_MAP`, `GENDER_MAP` import `ENLISTED_RANKS`/`OFFICER_RANKS` from
`app.services.eligibility` — never duplicated.

### Derived fields — reuse existing logic, don't reimplement

- `is_officer = mapped_rank in OFFICER_RANKS` (existing list from
  `eligibility.py`).
- `is_career` — computed by calling the *existing*
  `eligibility.derive_is_career(rank, mandatory_end_date, discharge_date)`
  unchanged. Notably **not** driven by `servicType`/track, matching how the
  codebase already computes this today.

### Date fields

`serviceStartDate` → `enlistment_date`, `endHovaDate` → `mandatory_end_date`,
`serviceEndDate` → `discharge_date`. HR's raw values are ISO date strings
(`YYYY-MM-DD` per subsystem 1's schema); parsed with `date.fromisoformat`.
A field with an unparseable date string is a mapping failure for that
field, added to `HeldForReview.reasons`.

### Direct passthroughs (no vocabulary translation needed)

`full_name` (`fullName`), `personal_number` (`personalNumber`, the merge
key), `email` (`mail`), `phone` (`phone`), `profile_picture_url`
(`imageUrl`).

### Result type

```python
@dataclass(frozen=True)
class MappedSoldierFields:
    full_name: str
    personal_number: str
    email: str | None
    phone: str | None
    profile_picture_url: str | None
    gender: str | None
    rank: str | None
    rank_track: str | None
    is_officer: bool
    is_career: bool
    enlistment_date: date | None
    mandatory_end_date: date | None
    discharge_date: date | None

@dataclass(frozen=True)
class HeldForReview:
    personal_number: str
    reasons: list[str]  # e.g. ["unmappable rank: 'רס״ן'", "unmappable gender: 'unspecified'"]

def map_hr_user(hr_user: HrUser) -> MappedSoldierFields | HeldForReview:
    ...
```

`personal_number` and `full_name` are required on `HrUser` already
(subsystem 1's schema); if either is somehow empty-string, that's also a
`HeldForReview` reason (defense in depth — subsystem 1's schema requires
them non-null, but doesn't forbid empty string).

## Storage: `soldier_hr_profile` table

One row per HR person, whether or not a `Soldier` row exists yet:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `soldier_id` | UUID, nullable, unique, FK → `soldiers.id` | Null while `sync_status = "held_for_review"` — no `Soldier` row exists yet. |
| `personal_number` | Text, unique | The merge key — matches even before a `Soldier` exists, so re-running mapping/review doesn't create duplicate rows. |
| `raw_dto` | JSONB | Full raw HR payload — the entire `HrUser.model_dump(by_alias=True)`, exactly as originally returned. |
| `sync_status` | Text | `"synced"` \| `"held_for_review"` \| `"vanished"`. Plain `Text`, matching the repo's existing status-column convention (e.g. `SoldierFieldUpdate.status`), not a pg enum — cheaper to extend later. |
| `review_reason` | Text, nullable | Populated when `sync_status = "held_for_review"` — human-readable, joins `HeldForReview.reasons`. |
| `overridden_fields` | JSONB, default `[]` | List of Justice field names (`"rank"`, `"phone"`, etc.) an admin has locally overridden; sync must skip these going forward. |
| `last_synced_at` | timestamptz, nullable | Set by subsystem 4's sync loop; null until the first successful sync. |
| `created_at` / `updated_at` | timestamptz | Standard bookkeeping, matching existing table conventions. |

Migration: new table via `op.create_table(...)`, `raw_dto`/`overridden_fields`
as `postgresql.JSONB(astext_type=sa.Text())`, FK to `soldiers.id`. Follows
the existing hand-named migration convention seen in
`20260901_field_update_dual_approval.py` (e.g.
`20260923_soldier_hr_profile.py`).

## Override hook: `approve_field_update`

In `app/services/soldiers.py::approve_field_update`, after a
`SoldierFieldUpdate` is approved and its value is applied to `Soldier`:

```python
HR_OWNED_FIELDS = frozenset({
    "full_name", "personal_number", "email", "phone", "gender", "rank",
    "profile_picture_url", "enlistment_date", "mandatory_end_date",
    "discharge_date",
})

def _mark_hr_field_overridden(session, soldier_id: UUID, field_name: str, actor_id: UUID) -> None:
    if field_name not in HR_OWNED_FIELDS:
        return
    profile = session.query(SoldierHrProfile).filter_by(soldier_id=soldier_id).one_or_none()
    if profile is None:
        return  # no HR profile for this soldier — nothing to mark
    if field_name not in profile.overridden_fields:
        profile.overridden_fields = [*profile.overridden_fields, field_name]
        write_audit(
            session, actor_id=actor_id, action="hr_sync.field_overridden",
            entity_type="soldier_hr_profile", entity_id=profile.id,
            context={"field_name": field_name, "soldier_id": str(soldier_id)},
        )
```

Called from the existing `approve_field_update` function, inside its
existing transaction — no new transaction boundary, no change to
`approve_field_update`'s existing behavior for non-HR-owned fields or for
soldiers with no `soldier_hr_profile` row (self-registered soldiers never
touched by HR sync are unaffected).

`personal_number` is technically HR-owned per the original brief but is
also the merge key; whether `personal_number` should ever be admin-editable
at all is an existing product question outside this subsystem's scope —
the hook treats it the same as any other HR-owned field for now (if it's
editable and approved, it gets marked overridden like anything else).

## Divergence recording

```python
def record_sync_divergence(
    session, *, soldier_hr_profile_id: UUID, field_name: str,
    hr_value: object, local_value: object,
) -> None:
    write_audit(
        session, actor_id=None, action="hr_sync.field_skipped_overridden",
        entity_type="soldier_hr_profile", entity_id=soldier_hr_profile_id,
        context={
            "field_name": field_name,
            "hr_value": hr_value,
            "local_value": local_value,
        },
    )
```

`actor_id=None` since this is a system/sync-triggered audit entry, not a
human action — matches `write_audit`'s existing nullable `actor_id` for
system-originated entries (confirm this is an accepted existing pattern
during implementation by checking other `write_audit` call sites with no
human actor, e.g. anything already called from a script/cron path).

This function is a primitive for subsystem 4 to call per skipped field
during its sync loop — subsystem 2 defines and unit-tests it, but nothing
in this subsystem calls it yet (no sync loop exists here).

## Module layout

New file `app/services/hr/mapping.py`:
- `GENDER_MAP`, `RANK_MAP`, `SERVICE_TYPE_TO_TRACK_MAP` (module constants)
- `MappedSoldierFields`, `HeldForReview` (dataclasses)
- `map_hr_user(hr_user: HrUser) -> MappedSoldierFields | HeldForReview`

New file `app/services/hr/divergence.py`:
- `record_sync_divergence(...)`

`app/db/models.py` gains `SoldierHrProfile` (new class, same file as every
other model per existing convention).

`app/services/soldiers.py::approve_field_update` gains the
`_mark_hr_field_overridden` call (existing file, targeted addition) plus
the module-level `HR_OWNED_FIELDS` constant — or `HR_OWNED_FIELDS` lives in
`app/services/hr/mapping.py` and is imported into `soldiers.py`, avoiding a
circular-looking "soldiers.py defines HR vocabulary" smell. (Decide exact
placement during implementation; `mapping.py` is the more natural home
since it's the file that already enumerates HR-owned fields implicitly via
its mapping functions.)

## Testing plan (TDD)

All tests fixture/unit-based, no live HR server, following subsystem 1's
pattern:

1. `map_hr_user` happy path — full valid `HrUser` → complete
   `MappedSoldierFields`, every field checked.
2. Unmappable `gender` → `HeldForReview` with the right reason string.
3. Unmappable `rank` → `HeldForReview`.
4. Unmappable/unparseable date → `HeldForReview`.
5. Multiple simultaneous failures → `HeldForReview.reasons` contains all of
   them (not just the first).
6. `is_officer`/`is_career` derivation — one enlisted case, one officer
   case, one career-track case, cross-checked against
   `eligibility.derive_is_career` directly (not reimplemented, so this is
   really testing the wiring, not the logic itself).
7. `_mark_hr_field_overridden` — marks an HR-owned field, no-ops for a
   non-HR-owned field, no-ops when no `soldier_hr_profile` row exists,
   idempotent on repeated calls (no duplicate entries), writes exactly one
   audit entry per new override.
8. `record_sync_divergence` — writes exactly one `AuditLog` row with the
   right `action`/`context`.
9. `SoldierHrProfile` model — basic round-trip (create, query by
   `personal_number`, JSONB columns serialize/deserialize correctly).

Target: 100% coverage of `mapping.py`, `divergence.py`, and the new
`_mark_hr_field_overridden` addition to `soldiers.py`.

## Open questions to resolve during implementation (not blocking the plan)

- `SERVICE_TYPE_TO_TRACK_MAP`'s actual HR value strings (`"chova"`/`"kva"`
  above are placeholders) — confirm against real fixture data when
  available; until then the map only handles those two placeholder keys
  and everything else is held for review, per the Unknowns rule.
- Whether `RANK_MAP` should stay a pure identity map or whether real HR
  data will require actual translation entries — structure supports either
  without an interface change.
- Exact placement of `HR_OWNED_FIELDS` (`mapping.py` vs `soldiers.py`) —
  design above recommends `mapping.py`, confirm no circular import issue
  during implementation.
