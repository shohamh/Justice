# Live-Computed Approval Scope + Export/Import for Requests, Exemptions & Constraints

**Date:** 2026-07-22

## Problem

**Swap approval chain.** `SwapManagerApproval` rows are pre-populated for the entire
required-approver roster the moment a swap enters `pending_approval`
(`_create_manager_approval_rows`, `backend/app/services/swaps.py:258-277`). This has
four concrete problems:

1. **Duty-manager approval is org-wide, not scoped.** `duty_manager_ids(session)`
   (`swaps.py:219-220`) selects every `Soldier` with `role == "duty_manager"` — any
   duty manager anywhere in the org can satisfy the requirement, not one actually
   responsible for the soldier's part of the hierarchy.
2. **A commander who is also a duty-manager for the same scope never gets a
   duty-manager row at all** (role-priority in `recompute_role`, `app/services/dm_scope.py`,
   forces `role="commander"`), so the "one click satisfies both" behavior happens only
   as an accidental side effect of that priority rule — and the accident breaks once
   duty-manager approval is properly scoped (see #1), because then some *other*,
   unrelated duty manager becomes the required approver instead of the same person.
3. **Rejection has no per-person attribution.** `SwapManagerApproval` only has
   `approved: bool`; a reject is a separate whole-swap action
   (`reject_request`, `swaps.py:639-670`) that sets `SwapRequest.status="rejected"`
   with no column recording *who* rejected.
4. **The soldier's own approval is a redundant extra click.** Both `claim_request`
   (`swaps.py:576-577`) and `cover_offer` (`swaps.py:828-829`) reset
   `requester_side_approved`/`covering_side_approved` to `None` even though asking for
   the swap (requester) or clicking "אני מכסה" (covering) already implied consent —
   forcing a second, separate approve click from someone who already acted.
5. **The roster is a stale snapshot.** Rows are written once, at
   `pending_approval` time, from whatever the hierarchy/scope looks like *then* — if
   the org changes before the swap resolves, the persisted roster doesn't reflect it.
6. **The UI shows only the nearest chain member**, collapsed into one satisfied/pending
   dot (`DirectCommanderApproval.tsx`, `approvals[0]`), with no clickable identity and
   no visibility into rejection.

**The other four request types** (`ExemptionRequest`, `PersonalConstraint`,
`SoldierFieldUpdate`, `SoldierEnrollmentRequest`) have no persisted chain at all —
each is a single `status`/`decided_by`/`decided_at`/`decision_note` (exemptions are a
sequential commander→duty-manager two-step; the other three need exactly one
qualifying approver, gated by existing `authorize()`/`Action` checks in
`app/auth/authz.py`). None of them expose *who* the relevant commander/duty-manager
even is, so a viewer has no visibility into who's expected to act.

**Export/import.** None of exemptions (standalone `SoldierExemption`), personal
constraints, or the 5 request types can be exported or imported at all today. Any
export design has to reflect the corrected approval model below, not the old
pre-populated-roster one, or the round-trip will re-import a schema that no longer
matches reality.

## Goal

1. A shared, generic, **live-computed** (nothing pre-written to the DB) lookup for
   "who is the nearest commander / nearest duty-manager for this soldier right now,"
   reusable by all 5 request types and by the export code.
2. Swaps: replace the pre-populated roster with a pure decision log (rows created only
   when someone actually approves/rejects), fix duty-manager scoping, generalize the
   "one click resolves everything this person is required for" rule so it isn't
   special-cased for dual roles, auto-approve the soldier's own side on ask/cover, and
   attribute every rejection to a specific person.
3. The other 4 types: **no change to their approval-count policy or authorization** —
   they adopt the same live lookup purely to *display* the direct commander/duty-manager
   by name (clickable to their profile) with a status indicator.
4. One shared frontend component rendering "commander: NAME ✓/✗/— · duty-manager: NAME
   ✓/✗/—", reused by `SwapsPage` (per side) and `ApprovalsPage`'s other tabs (single).
5. Backend-generated multi-sheet xlsx export (mirroring `config_export.py`'s exact
   `_WRITERS`/`ALL_SHEETS`/`sheets`-param/`StreamingResponse` pattern) for 6 sheets:
   `swap_requests`, `exemption_requests`, `soldier_field_updates`,
   `soldier_enrollment_requests`, `personal_constraints`, `soldier_exemptions` — full
   round-trip (every field including status/decision metadata), reflecting the
   corrected swap model (decision log, not roster).
6. Full round-trip import for the same 6 sheets: create new pending records, and
   update/restore existing ones (matched by `id`) including their decided/rejected
   history.
7. One combined "ייצוא" button on `ApprovalsPage`, authenticated fetch + blob download,
   `require_duty_manager_or_admin` scope — matching `ExportPage.tsx`'s existing
   `getAccessToken()` fetch pattern.
8. End-to-end tests that actually write an xlsx file, export real data into it, and
   re-import it, asserting the restored records match.

Out of scope: `swaps.restrict_to_hierarchy_level` (already correctly enforced at every
swap creation/claim/cover entry point — no change needed). Changing the *approval-count
policy* of exemptions/constraints/field-updates/enrollment (explicitly rejected —
they keep their current single-approver-or-sequential rules).

---

## Part A: Live-computed approval scope

### A1. Shared service — `app/services/approval_scope.py` (new file)

```python
def commander_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]:
    # Moved verbatim from swaps.py:223-255 (nearest-first, walks node.path_ids
    # reversed, collects each distinct HierarchyNode.commander_id). swaps.py
    # imports it back from here so nothing else changes call-sites-wise.

def duty_manager_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]:
    # NEW. Mirrors commander_chain_for_soldier's walk but sources duty
    # managers from DutyManagerScope.hierarchy_node_id instead of
    # HierarchyNode.commander_id: for each node in reversed(node.path_ids),
    # collect every DISTINCT DutyManagerScope.duty_manager_id whose
    # hierarchy_node_id == that node's id, nearest-node-first. A node can
    # have multiple duty managers scoped to it (unlike commander_id, which
    # is 0-or-1) — within one node, order by soldier.full_name for
    # determinism (no other natural order exists at that granularity).

def nearest_commander_for_soldier(session: Session, soldier_id: uuid.UUID) -> uuid.UUID | None:
    chain = commander_chain_for_soldier(session, soldier_id)
    return chain[0] if chain else None

def nearest_duty_manager_for_soldier(session: Session, soldier_id: uuid.UUID) -> uuid.UUID | None:
    chain = duty_manager_chain_for_soldier(session, soldier_id)
    return chain[0] if chain else None
```

Pure queries, no writes. `nearest_*` are what the UI/export use to show one name;
`*_chain_for_soldier` are what approval-eligibility checks use (any member of the
chain qualifies, not just the nearest).

### A2. Swaps — decision log instead of pre-populated roster

`_create_manager_approval_rows` is **deleted**. Nothing is written to
`swap_manager_approvals` when a swap enters `pending_approval` — rows are created
lazily, one at a time, only when a real decision happens.

**Schema (new migration):**
- `SwapManagerApproval` gains `rejected: bool` (default `False`), `rejected_by: uuid | None`,
  `rejected_at: datetime | None`.
- `SwapRequest` gains `rejected_by: uuid | None`.
- Unique constraint on `SwapManagerApproval(swap_request_id, side, commander_id, approver_kind)`
  — replaces the old implicit one-row-per-chain-position assumption, since rows are
  now upserted lazily instead of bulk-inserted with a `chain_order`. `chain_order` stays
  on the model (harmless, no longer written) rather than being dropped, since removing
  a column is a heavier migration than leaving an unused one — flag this as a
  candidate for cleanup in a later, unrelated migration.

**`_all_approved` (satisfaction check) becomes a live computation:**

```python
def _all_approved(session: Session, req: SwapRequest) -> bool:
    if not (req.requester_side_approved and req.covering_side_approved):
        return False
    require_dm = _require_duty_manager_approval(session)
    for side, soldier_id in (("requester", req.requesting_soldier_id), ("covering", req.covering_soldier_id)):
        if soldier_id is None:
            return False
        if commander_chain_for_soldier(session, soldier_id) and not _has_approved_decision(session, req.id, side, "commander"):
            return False
        if require_dm and duty_manager_chain_for_soldier(session, soldier_id) and not _has_approved_decision(session, req.id, side, "duty_manager"):
            return False
    return True

def _has_approved_decision(session: Session, request_id: uuid.UUID, side: str, kind: str) -> bool:
    return session.execute(
        select(SwapManagerApproval.id).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.approver_kind == kind,
            SwapManagerApproval.approved == True,  # noqa: E712
        ).limit(1)
    ).first() is not None
```

A requirement with an empty live chain (no commander at all, or duty-manager approval
off, or no duty manager in scope) is vacuously satisfied — same semantics as today's
"has_rows is None → continue," just computed from the live chain length instead of a
persisted row count.

**Approving:** `approve_manager_row` becomes "does the actor currently qualify (live)
as a commander-in-scope or duty-manager-in-scope for EITHER side of this request, for
EITHER kind — approve (upsert) every row they qualify for, all at once":

```python
def approve_manager_row(session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    qualifying = _qualifying_rows_for_actor(session, req, actor_id)
    if not qualifying:
        raise SwapError("not_required_approver")
    now = datetime.utcnow()
    for side, kind in qualifying:
        row = session.execute(
            select(SwapManagerApproval).where(
                SwapManagerApproval.swap_request_id == request_id,
                SwapManagerApproval.side == side,
                SwapManagerApproval.commander_id == actor_id,
                SwapManagerApproval.approver_kind == kind,
            )
        ).scalar_one_or_none()
        if row is None:
            row = SwapManagerApproval(
                swap_request_id=request_id, side=side, commander_id=actor_id, approver_kind=kind,
            )
            session.add(row)
        if not row.approved:
            row.approved = True
            row.approved_by = actor_id
            row.approved_at = now
            write_audit(session, actor_id=actor_id, action="swap.manager_approve",
                        entity_type="swap_request", entity_id=req.id,
                        after={"side": side, "kind": kind})
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req


def _qualifying_rows_for_actor(session: Session, req: SwapRequest, actor_id: uuid.UUID) -> list[tuple[str, str]]:
    """Every (side, kind) this actor is CURRENTLY (live) a required approver
    for on this request — no `side` param needed any more, since one click
    now resolves everything the actor is eligible for across both sides and
    both kinds in a single pass (generalizes the old "same person both
    sides" cascade to "same person any side/kind combination")."""
    require_dm = _require_duty_manager_approval(session)
    out: list[tuple[str, str]] = []
    for side, soldier_id in (("requester", req.requesting_soldier_id), ("covering", req.covering_soldier_id)):
        if soldier_id is None:
            continue
        if actor_id in commander_chain_for_soldier(session, soldier_id):
            out.append((side, "commander"))
        if require_dm and actor_id in duty_manager_chain_for_soldier(session, soldier_id):
            out.append((side, "duty_manager"))
    return out
```

This single function replaces both the old `approve_manager_row`'s narrow
same-kind-other-side cascade AND the dual-role special case the docstring warned about
— a person who is commander of both soldiers, or duty-manager of both, or both roles
for one or both soldiers, simply has more `(side, kind)` tuples in `qualifying`, and
every one of them gets approved in the same call, no special-casing.

`reject_manager_row` mirrors this exactly but sets `rejected`/`rejected_by`/`rejected_at`
on every qualifying row, THEN calls the existing whole-request `reject_request(...,
actor_id=actor_id)` (unchanged: still kills the whole swap immediately) — `reject_request`
also now sets the new `SwapRequest.rejected_by = actor_id`.

**Soldier-side auto-approval** (`claim_request` line ~576, `cover_offer` line ~828):

```python
# was: req.requester_side_approved = None; req.covering_side_approved = None
req.requester_side_approved = True   # asking already implied consent
req.covering_side_approved = True    # clicking "אני מכסה" already implied consent
```

`approve_soldier_side`/its route stay in place (idempotent no-op in the normal flow —
harmless if ever called, e.g. by an older client). Soldier-side reject
(`routes/swaps.py` soldier reject) is unaffected — still available at any point before
finalization, now also stamps `SwapRequest.rejected_by`.

**Routes** (`backend/app/routes/swaps.py`): `POST /swaps/{id}/manager-approve` and
`/manager-reject` drop their `{side}` body param (no longer needed — the backend
figures out every side/kind the actor qualifies for). `approve_manager_side`/
`approve_manager_side_override` (the broader-scope-authorization bulk-approve path,
`swaps.py:453-513`) keep their existing shape — that's a *different* mechanism (an
authorized non-chain-member overriding a whole side), untouched by this change.

### A3. The other 4 types — display only, no policy change

Each existing list/detail response (`exemption_requests.py`, `constraints.py`,
`soldiers.py` field-updates, `enrollment.py`) gains two additional read-only fields,
populated via `A1`'s `nearest_commander_for_soldier`/`nearest_duty_manager_for_soldier`
for the request's `soldier_id`:

```python
"nearest_commander": {"id": ..., "name": ...} | None,
"nearest_duty_manager": {"id": ..., "name": ...} | None,
```

No schema change (these are computed at response-serialization time, not persisted),
no change to `authorize()`/`Action` gating, no change to who is actually allowed to
click approve/reject — purely additive display data.

### A4. Frontend — one shared component

Generalize `DirectCommanderApproval.tsx` into `ApprovalChainStatus.tsx`:

```tsx
interface ApproverStatus { id: string; name: string; status: "approved" | "rejected" | "pending"; approvedByOther?: string }
interface Props { commander: ApproverStatus | null; dutyManager: ApproverStatus | null }
```

Each name renders via the existing `SoldierLink` component (already used elsewhere in
the codebase for clickable-to-profile soldier names) with a ✓/✗/— indicator, preserving
the current "(אושר ע״י X)" note when a non-direct chain member was the actual approver
(the existing `isSideSatisfied`/note logic in `DirectCommanderApproval.tsx` moves here
largely unchanged, just no longer limited to `approvals[0]` from a pre-populated array
— now fed by a live-fetched `{commander, dutyManager}` pair).

`SwapsPage.tsx`'s `PendingApprovalCard` renders one `ApprovalChainStatus` per side (2
total). `ApprovalsPage.tsx`'s exemption/constraint/field-update/enrollment tabs render
one each (no side), fed by the new `nearest_commander`/`nearest_duty_manager` fields
from A3.

---

## Part B: Export/Import for exemptions, personal constraints & all 5 requests

### B1. Backend export (`backend/app/routes/approvals_export.py`, new file)

Mirrors `config_export.py`'s exact pattern (`_WRITERS` dict, `ALL_SHEETS` list,
`sheets` query param, `StreamingResponse`, `require_duty_manager_or_admin`). Six sheets:

| Sheet | Columns |
|---|---|
| `swap_requests` | id, requesting/target/covering soldier personal_number+name, duty_date, status, reason, requester_side_approved, covering_side_approved, rejected_by (personal_number), decision_note, **approval_log** (flattened: `side:kind:person_pn:approved\|rejected:at;...` — one segment per actual `SwapManagerApproval` decision-log row that exists; since rows are now created lazily, this list is exactly the real decisions made, no longer a padded-out roster), created_at, updated_at |
| `exemption_requests` | id, soldier personal_number+name, exemption_type_name, start/end_date, reason, status, commander_approved_by_name, decided_by_name, decision_note, **files** (flattened filenames), created_at |
| `soldier_field_updates` | id, soldier personal_number+name, field_name, new_value, previous_value, status, decided_by_name, decision_note, created_at |
| `soldier_enrollment_requests` | id, soldier personal_number+name, requested_node_name, status, decided_by_name, decision_note, created_at |
| `personal_constraints` | id, soldier personal_number+name, start/end_date, reason, status, decided_by_name, decision_note, created_at |
| `soldier_exemptions` (standalone granted) | id, soldier personal_number+name, exemption_type_name, start/end_date, reason, granted_by_name, granted_at, revoked_at, revoked_by_name, revoke_reason |

`id` included on every sheet (no natural business key) so import can match-and-update
existing rows. Every name column is resolved (personal_number/full_name), never a raw
UUID, matching `config_export.py`'s convention.

### B2. Backend import (`backend/app/services/approvals_import.py`, new file, +
routes in `backend/app/routes/approvals_import.py`)

Follows the **existing session-based import pattern** already used for the 8
config/data sheets (`backend/app/services/import_sessions.py`,
`backend/app/services/import_parsers/`): upload → parse → resolve/preview (draft,
editable) → confirm. Reuses the same `ImportSession` model and
`/import/sessions` upload/review/confirm route family, adding these 6 sheets to
`KNOWN_SHEETS`/`ParsedImportData`/the parser registry — NOT a separate ad hoc import
mechanism. Each sheet's resolver:

- Matches by `id` if present and it resolves to an existing row of the right type →
  `action="update"`.
- No `id` (or an id that doesn't resolve) → `action="new"`, subject to the same
  new-record validation the live create paths already enforce (e.g. a new
  `exemption_request` still needs a valid `exemption_type_name` and `soldier`
  personal_number that resolves).
- On confirm: an "update" row restores `status`/`decided_by`/`decision_note`/etc.
  directly (admin-level restore, bypassing the normal single-step
  `approve_*`/`reject_*` service calls, since this is explicitly a data-restore
  operation, not someone re-living the approval flow) — but for `swap_requests`,
  restoring the **approval_log** column means re-creating the exact
  `SwapManagerApproval` decision-log rows it lists (one insert per flattened
  segment), not re-deriving them from a live chain (a live chain could differ by now
  from what it was when exported — restoring history must reproduce the *recorded
  facts*, not recompute them).

### B3. Frontend

One "ייצוא" button on `ApprovalsPage.tsx`: authenticated `fetch('/api/approvals/export?sheets=...')`
+ blob download, same `getAccessToken()`/`Bearer` pattern as `ExportPage.tsx`. Import
entry point reuses the existing Import UI (`ImportUploadPage.tsx`/
`ImportSessionReviewPage.tsx`) — the 6 new sheets simply appear as new tabs there, same
review/confirm flow as every other import sheet, no new page.

### B4. End-to-end round-trip tests

New backend test file, `backend/app/routes/tests/test_approvals_export_import_e2e.py`
(or alongside `test_import_sessions_service.py` — decide at plan time based on which
existing test module's fixtures are the better fit). Each test: seed real DB rows for a
sheet (including decided/rejected/approval-log state), call the real `/approvals/export`
endpoint, get back real xlsx bytes, feed those bytes into the real import
upload→confirm pipeline (no mocking of either side), then assert the newly
created/updated DB rows match the originals field-for-field — proving the round trip
is lossless, not just that each half works in isolation.

---

## Sequencing

Part A (approval-chain fix) must land and be stable before Part B's export/import
schema is finalized in detail, since B1's `swap_requests`/`approval_log` column
depends directly on A2's decision-log model (columns, upsert semantics) rather than
the old pre-populated roster. These become two separate implementation plans, executed
in order: Part A first, Part B second.

## Testing

- Part A: extend `backend/app/services/tests/test_swaps_service.py` (or wherever swap
  service tests live) — commander/duty-manager scoping (in-scope vs. out-of-scope,
  empty chain), one-click-resolves-everything (both sides, both kinds, all
  combinations), soldier-side auto-approval on claim/cover, per-row + per-request
  rejection attribution, and a regression test proving a commander-who-is-also-a-
  duty-manager for the same scope needs only one click even when duty-manager
  approval is scoped (not org-wide).
- Part A frontend: no new test framework — extend existing `SwapsPage`/`ApprovalsPage`
  test files for the new shared component's rendering (name, link, status per side/kind).
- Part B: real xlsx-based end-to-end tests per B4, plus the standard per-resolver
  unit tests (new/update/error paths) matching the existing `import_sessions`
  convention.
