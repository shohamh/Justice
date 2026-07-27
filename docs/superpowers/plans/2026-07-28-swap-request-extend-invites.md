# Extend Open Swap Requests With More Invites / Marketplace — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a requester invite more specific people and/or publish to the marketplace on an already-open `SwapRequest`, while preventing re-inviting anyone already reached or re-publishing an already-published request — visibly, via greyed-out UI with an explanation, not just a rejected API call.

**Architecture:** Two new service functions (`add_targets`, `publish_to_marketplace`) in `backend/app/services/swaps.py` reuse the existing `_add_invited_candidate` helper and `_lock_request` locking convention. Two new routes expose them under `/me/swaps/{id}/...`. The frontend's `AskSwapModal` gains an optional `editingSwap` prop that switches it into edit mode: already-invited candidates and an already-published marketplace flag render disabled with explanatory labels, and submit calls only the endpoints for what actually changed.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + React Query + vitest/testing-library (frontend), pytest (backend tests).

## Global Constraints

- Cap: `swaps.max_specific_targets` (system setting, default 5) applies to the **running total** of candidates on a request across its whole lifetime — invites added later count against the same cap as invites made at creation (per spec).
- "Already invited" blocks re-inviting regardless of the existing candidate's status (pending, declined, accepted, applied, or cancelled) — any existing `SwapCandidate` row for that soldier on that request blocks a new invite to them (per spec).
- All new mutating service functions must call `_lock_request` as their first DB interaction (existing codebase invariant, documented at `backend/app/services/swaps.py:228-257`).
- Hebrew is the UI language; all new user-facing strings go in `frontend/src/i18n/he.json` under the existing `"swaps"` key.
- Only the requester (owner) of a `SwapRequest` may add targets or publish it — enforced at the route level (same pattern as the existing `DELETE /me/swaps/{id}` cancel route at `backend/app/routes/swaps.py:546-561`).

---

### Task 1: `add_targets` and `publish_to_marketplace` service functions

**Files:**
- Modify: `backend/app/services/swaps.py` (add two functions after `create_request`/`_add_invited_candidate`, i.e. after line 165)
- Test: `backend/tests/unit/test_swaps_service.py` (append new tests)

**Interfaces:**
- Consumes: `SwapError` (existing exception class, `swaps.py:23`), `_lock_request(session, request_id) -> SwapRequest | None` (`swaps.py:228`), `_add_invited_candidate(session, *, req, requesting_soldier_id, target_soldier_id, actor_id) -> SwapCandidate` (`swaps.py:145`), `_max_specific_targets(session) -> int` (`swaps.py:57`), `write_audit` (`app.audit.writer`), `SwapCandidate`/`SwapRequest` models (`app.db.models`).
- Produces:
  - `add_targets(session: Session, *, request_id: uuid.UUID, target_soldier_ids: list[uuid.UUID], actor_id: uuid.UUID | None = None) -> SwapRequest`
  - `publish_to_marketplace(session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> SwapRequest`
  - Both raise `SwapError("request_not_found")`, `SwapError("not_open")`; `add_targets` additionally raises `SwapError(f"already_invited:{target_id}")` and `SwapError("target_limit_reached")`; `publish_to_marketplace` additionally raises `SwapError("already_on_marketplace")`.
  - Task 2 (routes) calls these directly by name.

- [ ] **Step 1: Write the failing unit tests**

Append to `backend/tests/unit/test_swaps_service.py` (reuses the `_published_assignment` helper already defined at the top of that file):

```python
def test_add_targets_happy_path(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-addtargets-1")
    requester = create_soldier(admin_session, personal_number="7720001", hierarchy_node_id=node.id)
    target1 = create_soldier(admin_session, personal_number="7720002", hierarchy_node_id=node.id)
    target2 = create_soldier(admin_session, personal_number="7720003", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target1.id], reason=None,
    )
    admin_session.flush()

    result = svc.add_targets(admin_session, request_id=req.id, target_soldier_ids=[target2.id])
    admin_session.flush()

    assert result.id == req.id
    candidates = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).all()
    assert {c.soldier_id for c in candidates} == {target1.id, target2.id}
    added = next(c for c in candidates if c.soldier_id == target2.id)
    assert added.source == "invited"
    assert added.status == "pending"


def test_add_targets_rejects_already_invited_soldier(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-addtargets-2")
    requester = create_soldier(admin_session, personal_number="7720004", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7720005", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target.id], reason=None,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match=f"already_invited:{target.id}"):
        svc.add_targets(admin_session, request_id=req.id, target_soldier_ids=[target.id])


def test_add_targets_rejects_duplicate_within_same_call(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-addtargets-dup")
    requester = create_soldier(admin_session, personal_number="7720006", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7720007", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match=f"already_invited:{target.id}"):
        svc.add_targets(admin_session, request_id=req.id, target_soldier_ids=[target.id, target.id])


def test_add_targets_counts_existing_candidates_against_cap(admin_session):
    from app.services.settings_loader import set_setting

    node = create_node(admin_session, level="unit", name="swap-svc-addtargets-cap")
    requester = create_soldier(admin_session, personal_number="7720008", hierarchy_node_id=node.id)
    t1 = create_soldier(admin_session, personal_number="7720009", hierarchy_node_id=node.id)
    t2 = create_soldier(admin_session, personal_number="7720010", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    set_setting(admin_session, "swaps.max_specific_targets", "1")
    admin_session.flush()

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[t1.id], reason=None,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match="target_limit_reached"):
        svc.add_targets(admin_session, request_id=req.id, target_soldier_ids=[t2.id])


def test_add_targets_rejects_when_request_not_open(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-addtargets-notopen")
    requester = create_soldier(admin_session, personal_number="7720011", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7720012", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()
    svc.cancel_request(admin_session, request_id=req.id)
    admin_session.flush()

    with pytest.raises(SwapError, match="not_open"):
        svc.add_targets(admin_session, request_id=req.id, target_soldier_ids=[target.id])


def test_publish_to_marketplace_happy_path(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-publish-1")
    requester = create_soldier(admin_session, personal_number="7720013", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7720014", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target.id], reason=None,
    )
    admin_session.flush()
    assert req.open_to_marketplace is False

    result = svc.publish_to_marketplace(admin_session, request_id=req.id)
    admin_session.flush()

    assert result.open_to_marketplace is True


def test_publish_to_marketplace_rejects_when_already_published(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-publish-2")
    requester = create_soldier(admin_session, personal_number="7720015", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match="already_on_marketplace"):
        svc.publish_to_marketplace(admin_session, request_id=req.id)


def test_publish_to_marketplace_rejects_when_request_not_open(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-publish-3")
    requester = create_soldier(admin_session, personal_number="7720016", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7720017", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target.id], reason=None,
    )
    admin_session.flush()
    svc.cancel_request(admin_session, request_id=req.id)
    admin_session.flush()

    with pytest.raises(SwapError, match="not_open"):
        svc.publish_to_marketplace(admin_session, request_id=req.id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_swaps_service.py -k "add_targets or publish_to_marketplace" -v`
Expected: FAIL with `AttributeError: module 'app.services.swaps' has no attribute 'add_targets'` (and similarly for `publish_to_marketplace`).

- [ ] **Step 3: Implement the two service functions**

In `backend/app/services/swaps.py`, insert immediately after `_add_invited_candidate` (after line 165, before `def list_open_board`):

```python
def add_targets(
    session: Session, *, request_id: uuid.UUID, target_soldier_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    """Invite additional specific soldiers on an already-open SwapRequest,
    on top of whoever was invited at creation or in a previous call. The
    running total of invited candidates (any status) still counts against
    swaps.max_specific_targets. Raises SwapError("not_open") if the request
    is no longer open, SwapError("target_limit_reached") if the total would
    exceed the cap, or SwapError(f"already_invited:{soldier_id}") if any
    target already has a SwapCandidate row on this request (any status) —
    checked both against existing rows and against duplicates within this
    same call."""
    req = _lock_request(session, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_open")

    existing_candidates = session.execute(
        select(SwapCandidate).where(SwapCandidate.swap_request_id == request_id)
    ).scalars().all()
    existing_soldier_ids = {c.soldier_id for c in existing_candidates}

    seen_this_call: set[uuid.UUID] = set()
    for target_id in target_soldier_ids:
        if target_id in existing_soldier_ids or target_id in seen_this_call:
            raise SwapError(f"already_invited:{target_id}")
        seen_this_call.add(target_id)

    if len(existing_candidates) + len(target_soldier_ids) > _max_specific_targets(session):
        raise SwapError("target_limit_reached")

    for target_id in target_soldier_ids:
        _add_invited_candidate(
            session, req=req, requesting_soldier_id=req.requesting_soldier_id,
            target_soldier_id=target_id, actor_id=actor_id,
        )

    write_audit(
        session, actor_id=actor_id, action="swap.add_targets", entity_type="swap_request",
        entity_id=req.id, after={"target_soldier_ids": [str(t) for t in target_soldier_ids]},
    )
    session.flush()
    return req


def publish_to_marketplace(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    """Flip open_to_marketplace on an already-open SwapRequest that wasn't
    published at creation time. Raises SwapError("not_open") if the request
    is no longer open, or SwapError("already_on_marketplace") if it's
    already published."""
    req = _lock_request(session, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_open")
    if req.open_to_marketplace:
        raise SwapError("already_on_marketplace")
    req.open_to_marketplace = True
    write_audit(
        session, actor_id=actor_id, action="swap.publish", entity_type="swap_request",
        entity_id=req.id, after={"open_to_marketplace": True},
    )
    session.flush()
    return req
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_swaps_service.py -k "add_targets or publish_to_marketplace" -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/swaps.py backend/tests/unit/test_swaps_service.py
git commit -m "feat: add service functions to extend an open swap request with more invites/marketplace"
```

---

### Task 2: `POST /me/swaps/{id}/targets` and `POST /me/swaps/{id}/publish` routes

**Files:**
- Modify: `backend/app/routes/swaps.py` (add two Pydantic models and two routes after the `create` route, i.e. after line 477)
- Test: `backend/tests/integration/test_swaps_api.py` (append new tests; reuses the `_setup`/`_uid` helpers already defined at the top of that file)

**Interfaces:**
- Consumes: `svc.add_targets`, `svc.publish_to_marketplace` (Task 1), `svc.SwapError`, `_out(r, session) -> SwapOut` (`routes/swaps.py:226`), `_err(exc) -> HTTPException` (`routes/swaps.py:285`), `require_enrolled` (`app.auth.deps`).
- Produces: `POST /api/me/swaps/{request_id}/targets` (body `{"target_ids": [<uuid>, ...]}`, 200 → `SwapOut`), `POST /api/me/swaps/{request_id}/publish` (no body, 200 → `SwapOut`). Both 404 if the request doesn't exist, 403 if the caller isn't the requester, 400 with the `SwapError` string as `detail` on business-rule violations. Frontend Task 3 calls these two paths.

- [ ] **Step 1: Write the failing integration tests**

Append to `backend/tests/integration/test_swaps_api.py`:

```python
def _create_open_request(session, requester, *, target_ids=None, open_to_marketplace=False):
    from app.services import swaps as svc
    return svc.create_request(
        session, requesting_soldier_id=requester.id, duty_assignment_id=_published_assignment_for(session, requester).id,
        target_soldier_id=None, target_soldier_ids=target_ids or [], reason=None,
        open_to_marketplace=open_to_marketplace,
    )


def _published_assignment_for(session, requester):
    dt = DutyType(name=f"api_dt_addt_{_uid()}", score_per_day=1)
    loc = DutyLocation(name=f"api_loc_addt_{_uid()}")
    session.add_all([dt, loc])
    session.flush()
    assignment = DutyAssignment(
        duty_type_id=dt.id, duty_location_id=loc.id, soldier_id=requester.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        status="published",
    )
    session.add(assignment)
    session.flush()
    return assignment


def test_add_targets_route_happy_path(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name=f"api_addt_{_uid()}")
    requester = create_soldier(admin_session, personal_number=f"api_addt_req_{_uid()}", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number=f"api_addt_tgt_{_uid()}", hierarchy_node_id=node.id)
    admin_session.commit()
    req = _create_open_request(admin_session, requester, open_to_marketplace=True)
    admin_session.commit()

    r = client.post(
        f"/api/me/swaps/{req.id}/targets", headers=auth_headers(requester),
        json={"target_ids": [str(target.id)]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(c["soldier_id"] == str(target.id) for c in body["candidates"])


def test_add_targets_route_rejects_non_owner(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name=f"api_addt_no_{_uid()}")
    requester = create_soldier(admin_session, personal_number=f"api_addtno_req_{_uid()}", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number=f"api_addtno_tgt_{_uid()}", hierarchy_node_id=node.id)
    stranger = create_soldier(admin_session, personal_number=f"api_addtno_str_{_uid()}")
    admin_session.commit()
    req = _create_open_request(admin_session, requester, open_to_marketplace=True)
    admin_session.commit()

    r = client.post(
        f"/api/me/swaps/{req.id}/targets", headers=auth_headers(stranger),
        json={"target_ids": [str(target.id)]},
    )
    assert r.status_code == 403


def test_add_targets_route_rejects_already_invited(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name=f"api_addt_dup_{_uid()}")
    requester = create_soldier(admin_session, personal_number=f"api_addtdup_req_{_uid()}", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number=f"api_addtdup_tgt_{_uid()}", hierarchy_node_id=node.id)
    admin_session.commit()
    req = _create_open_request(admin_session, requester, target_ids=[target.id])
    admin_session.commit()

    r = client.post(
        f"/api/me/swaps/{req.id}/targets", headers=auth_headers(requester),
        json={"target_ids": [str(target.id)]},
    )
    assert r.status_code == 400
    assert "already_invited" in r.json()["detail"]


def test_publish_route_happy_path(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name=f"api_pub_{_uid()}")
    requester = create_soldier(admin_session, personal_number=f"api_pub_req_{_uid()}", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number=f"api_pub_tgt_{_uid()}", hierarchy_node_id=node.id)
    admin_session.commit()
    req = _create_open_request(admin_session, requester, target_ids=[target.id])
    admin_session.commit()

    r = client.post(f"/api/me/swaps/{req.id}/publish", headers=auth_headers(requester))
    assert r.status_code == 200, r.text
    assert r.json()["open_to_marketplace"] is True


def test_publish_route_rejects_already_published(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name=f"api_pub_dup_{_uid()}")
    requester = create_soldier(admin_session, personal_number=f"api_pubdup_req_{_uid()}", hierarchy_node_id=node.id)
    admin_session.commit()
    req = _create_open_request(admin_session, requester, open_to_marketplace=True)
    admin_session.commit()

    r = client.post(f"/api/me/swaps/{req.id}/publish", headers=auth_headers(requester))
    assert r.status_code == 400
    assert r.json()["detail"] == "already_on_marketplace"


def test_publish_route_rejects_non_owner(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name=f"api_pub_no_{_uid()}")
    requester = create_soldier(admin_session, personal_number=f"api_pubno_req_{_uid()}", hierarchy_node_id=node.id)
    stranger = create_soldier(admin_session, personal_number=f"api_pubno_str_{_uid()}")
    admin_session.commit()
    req = _create_open_request(admin_session, requester)
    admin_session.commit()

    r = client.post(f"/api/me/swaps/{req.id}/publish", headers=auth_headers(stranger))
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_swaps_api.py -k "add_targets_route or publish_route" -v`
Expected: FAIL with 404 (route doesn't exist yet).

- [ ] **Step 3: Implement the routes**

In `backend/app/routes/swaps.py`, add after the `create` route (after line 477, before `class TakeFreeDutyRequest`):

```python
class AddSwapTargetsRequest(BaseModel):
    target_ids: list[uuid.UUID] = Field(min_length=1)


@router.post("/me/swaps/{request_id}/targets", response_model=SwapOut)
def add_targets(
    request_id: uuid.UUID,
    body: AddSwapTargetsRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_enrolled),
) -> SwapOut:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if req.requesting_soldier_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    try:
        r = svc.add_targets(session, request_id=request_id, target_soldier_ids=body.target_ids, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)


@router.post("/me/swaps/{request_id}/publish", response_model=SwapOut)
def publish_swap(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_enrolled),
) -> SwapOut:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if req.requesting_soldier_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    try:
        r = svc.publish_to_marketplace(session, request_id=request_id, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)
```

`require_enrolled` is already imported at the top of the file (`app.auth.deps`) since `create` uses it (`swaps.py:12,464`) — no new import needed. `Field` is already imported from `pydantic` (`swaps.py:7`).

Also add the two small test helper functions (`_create_open_request`, `_published_assignment_for`) directly above the tests in Step 1 — they were written inline in that step already.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_swaps_api.py -k "add_targets_route or publish_route" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full backend swap test suite to check for regressions**

Run: `cd backend && pytest tests/unit/test_swaps_service.py tests/integration/test_swaps_api.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/swaps.py backend/tests/integration/test_swaps_api.py
git commit -m "feat: add routes to add targets / publish to marketplace on an open swap request"
```

---

### Task 3: Frontend API wrappers

**Files:**
- Modify: `frontend/src/api/swaps.ts` (add two functions after `createSwap`, i.e. after line 99)

**Interfaces:**
- Consumes: `api` (axios wrapper, `./client`), `SwapRequest` interface (already defined in this file).
- Produces: `addSwapTargets(id: string, targetIds: string[]): Promise<SwapRequest>`, `publishSwapToMarketplace(id: string): Promise<SwapRequest>`. Task 4 (AskSwapModal) imports both.

- [ ] **Step 1: Add the two functions**

In `frontend/src/api/swaps.ts`, insert after `createSwap` (after line 99):

```ts
export async function addSwapTargets(id: string, targetIds: string[]): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/me/swaps/${id}/targets`, { target_ids: targetIds })).data;
}

export async function publishSwapToMarketplace(id: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/me/swaps/${id}/publish`, {})).data;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/swaps.ts
git commit -m "feat: add frontend API wrappers for add-targets and publish-to-marketplace"
```

---

### Task 4: i18n strings

**Files:**
- Modify: `frontend/src/i18n/he.json` (add keys inside the existing `"swaps"` object, after `"filter_node_all"` around line 880 — insert wherever convenient inside that object; exact position doesn't matter for a flat JSON object)

**Interfaces:**
- Produces: translation keys `swaps.manage_button`, `swaps.manage_swap_title`, `swaps.already_invited`, `swaps.invite_limit_reached`, `swaps.already_on_marketplace`, `swaps.nothing_new_selected`, consumed by Task 5 (AskSwapModal) and Task 6 (SwapsPage).

- [ ] **Step 1: Add the keys**

In `frontend/src/i18n/he.json`, inside the `"swaps"` object (e.g. right after the `"filter_node_all"` entry), add:

```json
    "manage_button": "נהל",
    "manage_swap_title": "ניהול בקשת החלפה",
    "already_invited": "כבר הוזמן",
    "invite_limit_reached": "הגעת למגבלת ההזמנות",
    "already_on_marketplace": "כבר פורסם בשוק ההחלפות",
    "nothing_new_selected": "לא נבחר דבר חדש להוספה",
```

Remember to keep valid JSON (comma placement) — check the key immediately before and after your insertion point.

- [ ] **Step 2: Verify JSON is valid**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/he.json','utf8')); console.log('ok')"`
Expected: prints `ok`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "feat: add i18n strings for swap request extend-invites/publish UI"
```

---

### Task 5: `AskSwapModal` edit mode

**Files:**
- Modify: `frontend/src/components/AskSwapModal.tsx`
- Test: `frontend/src/components/AskSwapModal.test.tsx` (append new tests)

**Interfaces:**
- Consumes: `addSwapTargets`, `publishSwapToMarketplace` (Task 3), i18n keys (Task 4), existing `createSwap`, `listEligibleTargets`, `getSwapConfig`, `CreateSwapInput`, `EffectiveDuty`.
- Produces: `AskSwapModal` gains an optional prop `editingSwap?: { id: string; open_to_marketplace: boolean; candidates: { soldier_id: string }[] }`. When present, the modal opens in edit mode. The `duty` prop's type narrows from `EffectiveDuty` to `Pick<EffectiveDuty, "assignment_id" | "start_date" | "end_date">` (backward compatible — existing callers passing a full `EffectiveDuty` still satisfy this). Task 6 (SwapsPage) passes `editingSwap` and a narrowed `duty` object built from a `SwapRequest`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/AskSwapModal.test.tsx`. First add the two new mocked functions to the existing `vi.mock("../api/swaps", ...)` block (replace the existing mock block near the top of the file with this expanded version):

```tsx
const mockCreateSwap = vi.fn().mockResolvedValue({});
const mockAddSwapTargets = vi.fn().mockResolvedValue({});
const mockPublishSwapToMarketplace = vi.fn().mockResolvedValue({});
const mockListEligibleTargets = vi.fn().mockResolvedValue([{ soldier_id: "s1", full_name: "Yossi", node_name: null, hierarchy_distance: 1 }]);
const mockGetSwapConfig = vi.fn().mockResolvedValue({ require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 5 });
vi.mock("../api/swaps", () => ({
  createSwap: (...args: unknown[]) => mockCreateSwap(...args),
  addSwapTargets: (...args: unknown[]) => mockAddSwapTargets(...args),
  publishSwapToMarketplace: (...args: unknown[]) => mockPublishSwapToMarketplace(...args),
  listEligibleTargets: (...args: unknown[]) => mockListEligibleTargets(...args),
  getSwapConfig: (...args: unknown[]) => mockGetSwapConfig(...args),
}));
```

Then append these new test cases inside the existing `describe("AskSwapModal", ...)` block, and add a `renderEditModal` helper alongside the existing `renderModal` helper:

```tsx
function renderEditModal(editingSwap: { id: string; open_to_marketplace: boolean; candidates: { soldier_id: string }[] }) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <AskSwapModal
        duty={{ assignment_id: "a1", start_date: "2026-08-01", end_date: "2026-08-02" } as never}
        dutyTypeName="Guard"
        editingSwap={editingSwap}
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

test("edit mode: an already-invited person's checkbox is disabled with an explanation", async () => {
  renderEditModal({ id: "req1", open_to_marketplace: false, candidates: [{ soldier_id: "s1" }] });
  const checkbox = (await screen.findAllByRole("checkbox"))[1];
  expect(checkbox).toBeDisabled();
  expect(await screen.findByText("swaps.already_invited")).toBeInTheDocument();
});

test("edit mode: an already-published marketplace checkbox is checked, disabled, with an explanation", async () => {
  renderEditModal({ id: "req1", open_to_marketplace: true, candidates: [] });
  const marketplaceCheckbox = await screen.findByTestId("ask-swap-marketplace-checkbox");
  expect(marketplaceCheckbox).toBeChecked();
  expect(marketplaceCheckbox).toBeDisabled();
  expect(await screen.findByText("swaps.already_on_marketplace")).toBeInTheDocument();
});

test("edit mode: submit only calls addSwapTargets for newly selected people", async () => {
  mockAddSwapTargets.mockClear();
  mockPublishSwapToMarketplace.mockClear();
  renderEditModal({ id: "req1", open_to_marketplace: false, candidates: [] });
  const targetCheckbox = (await screen.findAllByRole("checkbox"))[1];
  fireEvent.click(targetCheckbox);
  fireEvent.click(screen.getByText("swaps.save"));
  await waitFor(() => expect(mockAddSwapTargets).toHaveBeenCalledWith("req1", ["s1"]));
  expect(mockPublishSwapToMarketplace).not.toHaveBeenCalled();
});

test("edit mode: submit only calls publishSwapToMarketplace when the marketplace box is newly checked", async () => {
  mockAddSwapTargets.mockClear();
  mockPublishSwapToMarketplace.mockClear();
  renderEditModal({ id: "req1", open_to_marketplace: false, candidates: [] });
  fireEvent.click(await screen.findByTestId("ask-swap-marketplace-checkbox"));
  fireEvent.click(screen.getByText("swaps.save"));
  await waitFor(() => expect(mockPublishSwapToMarketplace).toHaveBeenCalledWith("req1"));
  expect(mockAddSwapTargets).not.toHaveBeenCalled();
});

test("edit mode: submit is disabled when nothing new is selected", async () => {
  renderEditModal({ id: "req1", open_to_marketplace: true, candidates: [{ soldier_id: "s1" }] });
  await screen.findAllByRole("checkbox");
  expect(screen.getByText("swaps.save")).toBeDisabled();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- AskSwapModal`
Expected: FAIL — `editingSwap` prop doesn't exist yet / no elements matching the new expectations.

- [ ] **Step 3: Implement edit mode**

Replace the full contents of `frontend/src/components/AskSwapModal.tsx` with:

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthContext";
import { queryKeys } from "../queryKeys";
import { createSwap, addSwapTargets, publishSwapToMarketplace, listEligibleTargets, getSwapConfig, CreateSwapInput } from "../api/swaps";
import { EffectiveDuty } from "../api/assignments";
import { lastDutyDay } from "../utils/formatDate";
import { translateApiError } from "../utils/translateApiError";

function extractErrorMessage(err: unknown, t: (key: string, options?: Record<string, unknown>) => string, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string" && detail) {
    if (detail.startsWith("cover_not_eligible:")) {
      return detail.slice("cover_not_eligible:".length) || fallback;
    }
  }
  if (Array.isArray(detail)) {
    // Pydantic v2 validation errors — list of {loc, msg, type}. The msg
    // itself is English framework text, so we don't surface it — just the field.
    const fields = (detail as { loc?: string[] }[])
      .map((d) => d.loc?.slice(1).join(".") ?? "?")
      .join(", ");
    return fields ? `נתונים לא תקינים בשדות: ${fields}` : fallback;
  }
  return translateApiError(err, t, fallback);
}

export interface EditingSwap {
  id: string;
  open_to_marketplace: boolean;
  candidates: { soldier_id: string }[];
}

export default function AskSwapModal({
  duty, dutyTypeName, onClose, onCreated, editingSwap,
}: {
  duty: Pick<EffectiveDuty, "assignment_id" | "start_date" | "end_date">;
  dutyTypeName: string;
  onClose: () => void;
  onCreated: () => void;
  editingSwap?: EditingSwap;
}) {
  const { t } = useTranslation();
  const { enrollmentPending } = useAuth();
  const [openToMarketplace, setOpenToMarketplace] = useState(editingSwap?.open_to_marketplace ?? false);
  const [selectedTargets, setSelectedTargets] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const eligibleQuery = useQuery({
    queryKey: ["swaps", "eligible-targets", duty.assignment_id],
    queryFn: () => listEligibleTargets(duty.assignment_id),
  });
  const eligibleTargets = eligibleQuery.data ?? [];
  const configQuery = useQuery({ queryKey: queryKeys.swapConfig(), queryFn: getSwapConfig });
  const maxTargets = configQuery.data?.max_specific_targets ?? 5;

  const alreadyInvitedIds = new Set((editingSwap?.candidates ?? []).map((c) => c.soldier_id));
  const remainingSlots = Math.max(0, maxTargets - alreadyInvitedIds.size);
  const marketplaceAlreadyPublished = editingSwap?.open_to_marketplace === true;

  function toggleTarget(id: string) {
    setSelectedTargets((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < remainingSlots) next.add(id);
      return next;
    });
  }

  const newlyPublishing = openToMarketplace && !marketplaceAlreadyPublished;
  const nothingSelected = editingSwap
    ? selectedTargets.size === 0 && !newlyPublishing
    : selectedTargets.size === 0 && !openToMarketplace;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (nothingSelected) {
      setError(editingSwap ? t("swaps.nothing_new_selected") : t("swaps.select_at_least_one"));
      return;
    }
    try {
      if (editingSwap) {
        if (selectedTargets.size > 0) {
          await addSwapTargets(editingSwap.id, Array.from(selectedTargets));
        }
        if (newlyPublishing) {
          await publishSwapToMarketplace(editingSwap.id);
        }
      } else {
        const input: CreateSwapInput = {
          duty_assignment_id: duty.assignment_id,
          reason: reason || null,
          target_soldier_ids: Array.from(selectedTargets),
          open_to_marketplace: openToMarketplace,
        };
        await createSwap(input);
      }
      onCreated();
    } catch (err: unknown) {
      setError(extractErrorMessage(err, t, "שגיאה"));
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold dark:text-gray-100">
            {editingSwap ? t("swaps.manage_swap_title") : t("swaps.ask_swap")}: {dutyTypeName}
          </h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3" dir="ltr">
          {(() => {
            const last = lastDutyDay(duty.end_date);
            return duty.start_date === last ? duty.start_date : `${duty.start_date} → ${last}`;
          })()}
        </p>
        {enrollmentPending && (
          <div className="rounded border border-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 text-sm text-yellow-800 dark:text-yellow-200 mb-2">
            בקשת הקליטה שלך למסגרת עדיין ממתינה לאישור — לא ניתן להגיש בקשות חדשות עד לאישור.
          </div>
        )}
        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
            <input
              type="checkbox"
              data-testid="ask-swap-marketplace-checkbox"
              checked={openToMarketplace}
              disabled={marketplaceAlreadyPublished}
              onChange={(e) => setOpenToMarketplace(e.target.checked)}
            />
            {t("swaps.post_open")}
            {marketplaceAlreadyPublished && (
              <span className="text-xs text-gray-400">({t("swaps.already_on_marketplace")})</span>
            )}
          </label>
          <div className="space-y-1">
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {t("swaps.select_up_to", { n: maxTargets })} ({alreadyInvitedIds.size + selectedTargets.size}/{maxTargets})
            </p>
            <div className="max-h-48 overflow-y-auto border rounded dark:border-gray-600">
              {eligibleTargets.length === 0 ? (
                <p className="text-sm text-gray-500 p-2">{t("swaps.no_eligible_targets")}</p>
              ) : (
                <ul>
                  {eligibleTargets.map((s) => {
                    const alreadyInvited = alreadyInvitedIds.has(s.soldier_id);
                    const limitReached = !alreadyInvited && !selectedTargets.has(s.soldier_id) && selectedTargets.size >= remainingSlots;
                    return (
                      <li key={s.soldier_id} className="flex items-center gap-2 px-2 py-1 border-b last:border-b-0 dark:border-gray-700 text-sm">
                        <input
                          type="checkbox"
                          checked={alreadyInvited || selectedTargets.has(s.soldier_id)}
                          disabled={alreadyInvited || limitReached}
                          onChange={() => toggleTarget(s.soldier_id)}
                        />
                        <span>{s.full_name}{s.node_name ? ` — ${s.node_name}` : ""} ({s.hierarchy_distance})</span>
                        {alreadyInvited && <span className="text-xs text-gray-400">({t("swaps.already_invited")})</span>}
                        {limitReached && <span className="text-xs text-gray-400">({t("swaps.invite_limit_reached")})</span>}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
          {!editingSwap && (
            <textarea placeholder={t("swaps.personal_message")} value={reason}
              onChange={e => setReason(e.target.value)} rows={3}
              className="w-full border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          )}
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded dark:border-gray-600 dark:text-gray-300">{t("swaps.cancel")}</button>
            <button type="submit" disabled={enrollmentPending || nothingSelected} className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">{t("swaps.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

The target-picker section always renders regardless of marketplace-published status — publishing to the marketplace and inviting specific people are independent actions, so a request that's already on the marketplace can still gain more specific invites.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- AskSwapModal`
Expected: PASS (all tests, old and new — 9 total)

- [ ] **Step 5: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AskSwapModal.tsx frontend/src/components/AskSwapModal.test.tsx
git commit -m "feat: add edit mode to AskSwapModal for extending an open swap request"
```

---

### Task 6: "Manage" button on `SwapsPage`'s open request cards

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx`
- Test: `frontend/src/pages/SwapsPage.test.tsx` (append new test)

**Interfaces:**
- Consumes: `AskSwapModal` with `editingSwap` prop (Task 5), `swaps.manage_button` i18n key (Task 4).
- Produces: no new exports — purely wires an existing open `SwapRequest` card to open `AskSwapModal` in edit mode via a new `manageSwap` state variable.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/pages/SwapsPage.test.tsx`, inside the existing `describe` block (or a new one):

```tsx
test("shows a Manage button on an open request that opens the edit modal", async () => {
  renderPage();
  const manageButton = await screen.findByText("swaps.manage_button");
  fireEvent.click(manageButton);
  expect(await screen.findByText("swaps.manage_swap_title: Guard")).toBeInTheDocument();
});
```

This requires importing `fireEvent` from `@testing-library/react` at the top of the file — check the existing import line (`import { render, screen } from "@testing-library/react";`) and change it to `import { render, screen, fireEvent } from "@testing-library/react";`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- SwapsPage`
Expected: FAIL — no element with text `swaps.manage_button`.

- [ ] **Step 3: Wire up the Manage button and edit modal**

In `frontend/src/pages/SwapsPage.tsx`:

1. Find the component's existing `askSwapDuty` state declaration (used to open the create-mode `AskSwapModal`) and add a sibling state variable right after it:

```tsx
const [manageSwap, setManageSwap] = useState<SwapRequest | null>(null);
```

2. In `renderMySwapCard` (starting at line 325), find the closing "Cancel" button block:

```tsx
      {swap.status === "open" && (
        <button type="button" onClick={() => handleCancel(swap.id)} className="text-red-600 text-xs hover:underline">
          {t("swaps.cancel")}
        </button>
      )}
```

Replace it with a flex row containing both the Manage and Cancel buttons:

```tsx
      {swap.status === "open" && (
        <div className="flex gap-3">
          <button type="button" onClick={() => setManageSwap(swap)} className="text-indigo-600 text-xs hover:underline">
            {t("swaps.manage_button")}
          </button>
          <button type="button" onClick={() => handleCancel(swap.id)} className="text-red-600 text-xs hover:underline">
            {t("swaps.cancel")}
          </button>
        </div>
      )}
```

3. Near the existing `{askSwapDuty && (<AskSwapModal ... />)}` block (around line 638-645), add a sibling block for edit mode:

```tsx
      {manageSwap && (
        <AskSwapModal
          duty={{
            assignment_id: manageSwap.duty_assignment_id,
            start_date: manageSwap.duty_start_date ?? manageSwap.duty_date,
            end_date: manageSwap.duty_end_date ?? manageSwap.duty_date,
          }}
          dutyTypeName={manageSwap.duty_type_name ?? ""}
          editingSwap={{
            id: manageSwap.id,
            open_to_marketplace: manageSwap.open_to_marketplace,
            candidates: manageSwap.candidates.map((c) => ({ soldier_id: c.soldier_id })),
          }}
          onClose={() => setManageSwap(null)}
          onCreated={async () => { setManageSwap(null); await refreshSwapData(); }}
        />
      )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- SwapsPage`
Expected: PASS (both tests)

- [ ] **Step 5: Run the full frontend test suite, typecheck, and lint**

Run: `cd frontend && npm test && npm run typecheck && npm run lint`
Expected: all PASS, zero lint warnings.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SwapsPage.tsx frontend/src/pages/SwapsPage.test.tsx
git commit -m "feat: add Manage button to extend an open swap request with more invites/marketplace"
```

---

### Task 7: Manual verification in the running app

**Files:** none (verification only)

- [ ] **Step 1: Start the dev stack**

Run: `.\dev.ps1` (from repo root, per `CLAUDE.md`)

- [ ] **Step 2: Manual walkthrough**

1. Log in as a soldier with an upcoming published duty.
2. Go to Swaps → ask for a swap on that duty, inviting exactly one specific person (leave marketplace unchecked).
3. Go to the "מ ​הבקשות שלי" (mine) tab, find the new open request, click "נהל" (Manage).
4. Confirm the modal shows the previously-invited person greyed out with "כבר הוזמן", and the marketplace checkbox is still enabled (not yet published).
5. Check the marketplace checkbox and click Save — confirm no error, modal closes, and reopening Manage now shows the marketplace checkbox checked, disabled, with "כבר פורסם בשוק ההחלפות".
6. Reopen Manage again, select a second (previously-uninvited) person, and save — confirm that person now also shows as "כבר הוזמן" the next time Manage is opened.
7. Repeat step 6 until `max_specific_targets` (default 5, check via `/api/swaps/config` or the admin settings page) is reached — confirm remaining not-yet-invited people grey out with "הגעת למגבלת ההזמנות" and the modal will not let you select more.

- [ ] **Step 3: Report findings**

If any step doesn't match, note it — do not proceed to code review until manual verification passes.

---

## Self-Review Notes

- **Spec coverage:** every spec requirement (add-targets endpoint + cap enforcement across lifetime, publish endpoint + already-published guard, "any status blocks re-invite" dedup, greyed-out UI with explanation for both already-invited and already-published/limit-reached cases, edit-mode entry point via a "Manage" action on the existing card) maps to a task above (Tasks 1–2 backend, Tasks 3–6 frontend, Task 7 manual verification).
- **Placeholder scan:** no TBD/TODO; every step has complete, runnable code.
- **Type consistency:** `add_targets(session, *, request_id, target_soldier_ids, actor_id=None)` and `publish_to_marketplace(session, *, request_id, actor_id=None)` signatures are used identically in Task 1 (definition), Task 2 (route call sites), matching the existing `_lock_request`/`SwapError` conventions. `addSwapTargets(id, targetIds)` / `publishSwapToMarketplace(id)` signatures match between Task 3 (definition) and Task 5 (call sites). `EditingSwap` shape (`id`, `open_to_marketplace`, `candidates: {soldier_id}[]`) matches between Task 5 (prop definition) and Task 6 (the object SwapsPage constructs and passes in).
- A correction was caught and folded into Task 5 Step 3 itself (the target-picker must stay visible regardless of marketplace-published status, since publishing and inviting are independent) rather than left as a loose thread — the final code block reflects the corrected, always-visible picker.
