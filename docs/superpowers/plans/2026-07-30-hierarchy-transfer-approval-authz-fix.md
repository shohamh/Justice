# Hierarchy Transfer Approval Authorization Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix "אישור העברת מסגרת לא באמת מעביר מסגרת" — a commander approving a hierarchy/frame transfer request gets a silent 403 and the transfer never happens, because the endpoint is gated on `Action.SOLDIER_UPDATE`, which is granted to duty managers and admins but was never added to `_COMMANDER_ACTIONS`.

**Architecture:** This is confirmed (via live integration test, not just code reading) to be purely an authorization-scope gap — `approve_request`'s actual mutation logic (`soldier.hierarchy_node_id = req.to_node_id`, committed correctly) works fine when it's allowed to run. The fix adds a dedicated action for this feature and grants it to commanders (matching the pattern every other approval action — `SWAP_APPROVE`, `ENROLLMENT_APPROVE`, `CONSTRAINT_APPROVE`, `EXEMPTION_GRANT` — already follows in `_COMMANDER_ACTIONS`), without touching the working mutation code.

**Tech Stack:** Python/FastAPI (backend only — this is a pure backend authorization fix, no frontend or data model change needed).

## Global Constraints

- Do not touch `backend/app/services/hierarchy_transfers.py`'s `approve_request` mutation logic — it is confirmed correct.
- Do not weaken `SOLDIER_UPDATE`'s existing scope (duty-manager-only) — other endpoints may rely on it staying duty-manager-restricted; add a new, narrower action instead of broadening the existing one.
- Any new test added for this must exercise a plain `commander` actor, not `admin` — admin bypasses `can()` entirely (`authz.py:145`) and is why this bug was previously invisible to tests.
- Run `pytest -m hierarchy -q` after the change (confirm the correct marker by checking how `test_hierarchy_transfers_api.py` is decorated).

---

## File Structure

- **Modify:** `backend/app/auth/authz.py` — add `Action.HIERARCHY_TRANSFER` (or reuse `Action.HIERARCHY_MANAGE`, see Task 1 Step 1 for the decision) to `_COMMANDER_ACTIONS`.
- **Modify:** `backend/app/routes/hierarchy_transfers.py:52, 71` (`create_transfer`, `approve_transfer`) and its `reject_transfer` counterpart — use the new/reused action instead of `Action.SOLDIER_UPDATE`.
- **Test:** `backend/tests/integration/test_hierarchy_transfers_api.py` — add commander-actor coverage.

---

### Task 1: Grant commanders the ability to create/approve/reject hierarchy transfers

**Files:**
- Modify: `backend/app/auth/authz.py` (`Action` enum if adding a new value, and `_COMMANDER_ACTIONS` set, near line 66 and the commander-actions block)
- Modify: `backend/app/routes/hierarchy_transfers.py:52, 71` and the `reject_transfer` endpoint (locate its exact line by reading the file — investigation confirmed `create_transfer`/`approve_transfer` line numbers but not `reject_transfer`'s)
- Test: `backend/tests/integration/test_hierarchy_transfers_api.py`

**Interfaces:**
- Consumes: existing `Action` enum and `authorize(session, user, action, target_node=...)` helper in `backend/app/auth/authz.py` — signature unchanged.
- Produces: commanders who command (or duty-manage) the relevant source/destination hierarchy node can now successfully create, approve, and reject transfer requests, matching the access level already granted for swaps/enrollments/constraints/exemptions.

- [ ] **Step 1: Decide between a new `Action.HIERARCHY_TRANSFER` and reusing `Action.HIERARCHY_MANAGE`**

Read `backend/app/auth/authz.py` in full to see how `Action.HIERARCHY_MANAGE` is used elsewhere (it's already in `_COMMANDER_ACTIONS` per investigation). If `HIERARCHY_MANAGE` is only used for structural hierarchy edits (renaming/adding/removing nodes — a different concern from "move one soldier between existing nodes"), prefer adding a new dedicated `Action.HIERARCHY_TRANSFER` so the two concerns stay separately auditable/revocable. If `HIERARCHY_MANAGE` is already loosely used for "any hierarchy-related management action" by convention in this codebase, reusing it is simpler and consistent — read the enum's other members and their usage sites before deciding, and prefer the new dedicated action unless the codebase clearly favors coarse-grained reuse.

- [ ] **Step 2: Write the failing test**

Read `backend/tests/integration/test_hierarchy_transfers_api.py` in full first to match its existing fixture/actor-setup conventions (how a `role="admin"` actor is constructed, per the investigation's own working example). Add:

```python
def test_commander_can_create_and_approve_hierarchy_transfer(client, make_soldier, make_hierarchy_node, login_as):
    # Adjust fixture calls to match this file's actual helper names/signatures.
    source_node = make_hierarchy_node(name="Source")
    dest_node = make_hierarchy_node(name="Dest")
    commander = make_soldier(role="commander", commands_node_id=source_node.id)  # adjust to real commander-assignment fixture
    # Ensure the same commander (or another commander) also commands dest_node,
    # or set up two commanders if approval requires the destination's commander
    # specifically — read create_transfer/approve_transfer's target_node logic
    # (source_node vs dest_node) to get this right.
    transferee = make_soldier(hierarchy_node_id=source_node.id)

    commander_token = login_as(commander)

    create_resp = client.post(
        "/api/hierarchy-transfers",
        json={"soldier_id": str(transferee.id), "to_node_id": str(dest_node.id)},
        headers={"Authorization": f"Bearer {commander_token}"},
    )
    assert create_resp.status_code == 201
    request_id = create_resp.json()["id"]

    approve_resp = client.post(
        f"/api/hierarchy-transfers/{request_id}/approve",
        headers={"Authorization": f"Bearer {commander_token}"},
    )
    assert approve_resp.status_code == 200

    soldier_resp = client.get(f"/api/soldiers/{transferee.id}", headers={"Authorization": f"Bearer {commander_token}"})
    assert soldier_resp.json()["hierarchy_node_id"] == str(dest_node.id)
```

(Field names like `soldier_id`/`to_node_id` and the exact create/approve URL paths must be confirmed by reading `backend/app/routes/hierarchy_transfers.py` in full before finalizing this test — the investigation confirmed the route file's line numbers for the auth checks but not every field name on the request bodies.)

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest backend/tests/integration/test_hierarchy_transfers_api.py -k "commander_can_create_and_approve" -v`
Expected: FAIL — 403 on the create or approve call

- [ ] **Step 4: Apply the authorization fix**

If adding a new action (Step 1's likely outcome), in `backend/app/auth/authz.py`:

```python
# In the Action enum, alongside the other action members:
HIERARCHY_TRANSFER = "hierarchy_transfer"
```

```python
# In _COMMANDER_ACTIONS, alongside SWAP_APPROVE/ENROLLMENT_APPROVE/etc.:
_COMMANDER_ACTIONS = {
    Action.SOLDIER_READ,
    Action.HIERARCHY_READ,
    Action.HIERARCHY_MANAGE,
    Action.EXEMPTION_GRANT,
    Action.EXEMPTION_READ,
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
    Action.SWAP_APPROVE,
    Action.ENROLLMENT_APPROVE,
    Action.HIERARCHY_TRANSFER,  # new
}
```

Also add `Action.HIERARCHY_TRANSFER` to `_DM_ACTIONS` (duty managers must keep working exactly as before — this action needs to be additive, not a replacement, for that role) and confirm `admin`'s blanket bypass at `authz.py:145` still covers it (it should, since it's a blanket bypass by role, not a per-action allowlist — confirm by reading that line's exact logic).

Then in `backend/app/routes/hierarchy_transfers.py`:

```python
# Line 52 (create_transfer) — BEFORE
authorize(session, user, Action.SOLDIER_UPDATE, target_node=source_node)
# AFTER
authorize(session, user, Action.HIERARCHY_TRANSFER, target_node=source_node)

# Line 71 (approve_transfer) — BEFORE
authorize(session, user, Action.SOLDIER_UPDATE, target_node=dest_node)
# AFTER
authorize(session, user, Action.HIERARCHY_TRANSFER, target_node=dest_node)
```

Find and update the `reject_transfer` endpoint identically (same file — locate its `authorize(...)` call, which almost certainly also uses `Action.SOLDIER_UPDATE` today given the pattern, and update it the same way).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest backend/tests/integration/test_hierarchy_transfers_api.py -k "commander_can_create_and_approve" -v`
Expected: PASS

- [ ] **Step 6: Run the full hierarchy transfers test file plus the broader auth test marker for regressions**

Run: `cd backend && pytest backend/tests/integration/test_hierarchy_transfers_api.py -q && pytest -m auth -q`
Expected: PASS (no regressions — in particular, confirm duty-manager and admin flows for this feature still work, since Step 4 was additive but double-check `_DM_ACTIONS` wasn't accidentally left without the new action, which would break duty managers instead of fixing commanders)

- [ ] **Step 7: Manually verify in the running app**

Start `.\dev.ps1`, log in as a plain commander (not a duty manager, not admin) who commands a node with soldiers in it, create a transfer request for one of their soldiers to a different node (via `CommandDashboardPage.tsx`'s move-soldier UI), then approve it from the "transfers" tab in `ApprovalsPage.tsx` (as the commander of the destination node, or the same commander if they command both). Confirm no error appears and the soldier's frame actually changes — check the soldier's profile or the hierarchy tree page afterward.

- [ ] **Step 8: Commit**

```bash
git add backend/app/auth/authz.py backend/app/routes/hierarchy_transfers.py backend/tests/integration/test_hierarchy_transfers_api.py
git commit -m "fix: allow commanders (not just duty managers) to approve hierarchy transfer requests"
```

---

## Self-Review Notes

- The single spec item ("frame transfer after approval doesn't actually transfer") is covered by Task 1, now correctly scoped to the real bug (authorization gap for commanders) rather than the originally-assumed swap-approval feature gap.
- This plan deliberately does NOT touch `backend/app/services/hierarchy_transfers.py`'s mutation logic, since live testing already proved it correct — changing it would be unjustified scope creep.
- The regression test specifically uses a `commander` actor (not `admin`) per the investigation's explicit warning that admin-only tests are why this bug shipped undetected.
