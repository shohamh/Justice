# Feedback Batch (2026-07-21): 8 Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 8 independent product fixes/features requested by the product owner in one bundled feature branch off `dev`: (1) redesign swap approval to require one commander AND one duty-manager sign-off per side (config'able), with matching help copy and a page-level help icon; (2) a system setting restricting who can view the transparency page; (3) a quarterly/semi-annual/annual-resetting "constraint days remaining" indicator; (4) fix the discharge button's confirm flow to ask for a start date first; (5) an eligible/available-soldier picker (sorted by hierarchy distance, capped at N) for targeted swap requests; (6) fix the untranslated `cover_not_eligible` error string; (7) reorder the calendar view buttons (3-day, week, month) while keeping month the default; (8) surface driving-license fields (editable) and קבע status (read-only) in the soldier profile modal.

**Architecture:** Each item is a vertical slice touching a `backend/app/services/*.py` + `backend/app/routes/*.py` pair (where backend changes are needed) and the corresponding `frontend/src/**` consumer. New system settings go through the existing `SystemSetting`/`settings_loader.py` JSONB key-value store — no new tables except where noted (item 1 adds a column; item 3 adds two columns).

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React + TypeScript + react-i18next + TanStack Query (frontend), pytest (backend tests), vitest (frontend tests, where an area already has coverage).

## Global Constraints

- Hebrew UI text only (English code/identifiers) — every new user-facing string goes in `frontend/src/i18n/he.json`, dot-path keys following the existing per-page prefix convention (`swaps.*`, `transparency.*`, `soldier_profile.*`, `command_dashboard.*`, `unit_calendar.*`).
- New system settings are stored via `app.services.settings_loader.get_setting`/`set_setting` against the existing `system_settings` JSONB table — do not create new settings tables.
- New Alembic migrations: `alembic revision -m "description"` from `backend/`, then hand-edit `upgrade()`/`downgrade()`. Do not use `--autogenerate` blindly — review the diff.
- Every backend service function takes `session: Session` first and returns/raises via a module-level `*Error` exception class (`SwapError`, `ConstraintError`, etc.) — follow the existing pattern per file, do not introduce a new error-handling style.
- Run targeted tests only per task (`pytest -m <area> -q` / `npm test -- <file>`); the full suite is not required until the branch is ready to merge.
- No commits directly to `master` or `dev` — this is one bundled feature branch per the user's explicit choice for this batch.

---

## Item 1 — Swap approval: commander + duty-manager per side

**Current behavior** (`backend/app/services/swaps.py`): when a swap needs approval, one `SwapManagerApproval` row is created per commander in each side's chain (`commander_chain_for_soldier`), and `_all_approved` requires only one approved row per side (any chain commander suffices). The product owner wants, per side: one commander approval **and** one duty-manager approval, gated by a new default-on system setting, with a same-person shortcut (if the same person is the required approver for both sides, approving once satisfies both).

### Task 1.1: Add `approver_kind` column + duty-manager rows to the approval model

**Files:**
- Create: `backend/alembic/versions/<new>_swap_approver_kind.py`
- Modify: `backend/app/db/models.py:536-567` (`SwapManagerApproval`)
- Modify: `backend/app/services/swaps.py:202-212` (`_create_manager_approval_rows`), `:160-164` (near `_require_approval`)
- Test: `backend/tests/services/test_swaps.py` (existing swap-approval tests — find via `pytest --collect-only -q -m swaps` or grep `_all_approved` / `_create_manager_approval_rows` usages)

**Interfaces:**
- Produces: `SwapManagerApproval.approver_kind: str` (`"commander"` | `"duty_manager"`), `swaps.duty_manager_ids(session) -> list[uuid.UUID]`, `swaps._require_duty_manager_approval(session) -> bool` (default `True` when the `swaps.require_duty_manager_approval` setting is unset).

- [ ] **Step 1: Write the failing test** — assert that after `claim_request` puts a swap into `pending_approval` (with approval required), `SwapManagerApproval` rows exist for both `approver_kind="commander"` and `approver_kind="duty_manager"` on each side that has a commander/duty-manager respectively:

```python
def test_claim_creates_commander_and_duty_manager_rows(session, ...):
    # ... build requester + covering soldiers each under a commander, and one
    # soldier with role="duty_manager" ...
    req = swaps.create_request(session, requesting_soldier_id=requester.id,
                                duty_assignment_id=assignment.id, target_soldier_id=None, reason=None)
    swaps.claim_request(session, request_id=req.id, covering_soldier_id=coverer.id)
    rows = session.execute(
        select(SwapManagerApproval).where(SwapManagerApproval.swap_request_id == req.id)
    ).scalars().all()
    kinds_by_side = {(r.side, r.approver_kind) for r in rows}
    assert ("requester", "commander") in kinds_by_side
    assert ("requester", "duty_manager") in kinds_by_side
    assert ("covering", "commander") in kinds_by_side
    assert ("covering", "duty_manager") in kinds_by_side
```

- [ ] **Step 2: Run test to verify it fails** — `pytest backend/tests/services/test_swaps.py -k duty_manager_rows -v` — expect a `TypeError`/`AttributeError` since `approver_kind` doesn't exist yet.

- [ ] **Step 3: Migration** — create and edit the Alembic revision:

```python
"""add approver_kind to swap_manager_approvals

Revision ID: <generated>
Revises: <current head>
"""
from alembic import op
import sqlalchemy as sa

revision = "<generated>"
down_revision = "<current head>"

def upgrade() -> None:
    op.add_column(
        "swap_manager_approvals",
        sa.Column("approver_kind", sa.Text(), nullable=False, server_default="commander"),
    )

def downgrade() -> None:
    op.drop_column("swap_manager_approvals", "approver_kind")
```

- [ ] **Step 4: Model + service changes.** In `models.py`, add to `SwapManagerApproval`:

```python
    # "commander" | "duty_manager" — which approval requirement this row satisfies.
    approver_kind: Mapped[str] = mapped_column(Text, server_default=text("'commander'"), default="commander")
```

In `swaps.py`, add helpers near `_require_approval`:

```python
def _require_duty_manager_approval(session: Session) -> bool:
    try:
        return bool(get_setting(session, "swaps.require_duty_manager_approval"))
    except SettingNotFound:
        return True


def duty_manager_ids(session: Session) -> list[uuid.UUID]:
    return list(session.execute(select(Soldier.id).where(Soldier.role == "duty_manager")).scalars().all())
```

Replace `_create_manager_approval_rows`:

```python
def _create_manager_approval_rows(session: Session, *, req: SwapRequest) -> None:
    """Populate swap_manager_approvals for both sides: one row per chain
    commander, plus (if swaps.require_duty_manager_approval) one row per
    duty manager. Called once, when a swap enters pending_approval with a
    known covering soldier."""
    dm_ids = duty_manager_ids(session) if _require_duty_manager_approval(session) else []
    for side, soldier_id in (("requester", req.requesting_soldier_id), ("covering", req.covering_soldier_id)):
        if soldier_id is None:
            continue
        for idx, commander_id in enumerate(commander_chain_for_soldier(session, soldier_id)):
            session.add(SwapManagerApproval(
                swap_request_id=req.id, side=side, commander_id=commander_id,
                chain_order=idx, approver_kind="commander",
            ))
        for idx, dm_id in enumerate(dm_ids):
            session.add(SwapManagerApproval(
                swap_request_id=req.id, side=side, commander_id=dm_id,
                chain_order=idx, approver_kind="duty_manager",
            ))
    session.flush()
```

- [ ] **Step 5: Run test to verify it passes** — `pytest backend/tests/services/test_swaps.py -k duty_manager_rows -v`.

- [ ] **Step 6: Commit** — `git add backend/alembic/versions backend/app/db/models.py backend/app/services/swaps.py backend/tests/services/test_swaps.py && git commit -m "feat: swap approvals track commander vs duty-manager rows"`

### Task 1.2: Require both kinds in `_all_approved`; cascade same-approver to the other side

**Files:**
- Modify: `backend/app/services/swaps.py:215-341` (`_all_approved`, `approve_manager_row`)
- Test: `backend/tests/services/test_swaps.py`

**Interfaces:**
- Consumes: `SwapManagerApproval.approver_kind` from Task 1.1.
- Produces: `_all_approved` now false unless every present `(side, kind)` combination has ≥1 approved row; `approve_manager_row` auto-approves the same `commander_id`'s row on the opposite side if one exists and is unapproved.

- [ ] **Step 1: Write the failing test** — a swap with a commander shared between both sides (requester and coverer report to the same immediate commander) should finalize after that one commander approves once for `side="requester"`, *and* after the duty manager approves once for either side (same duty-manager id row exists on both sides) — but NOT before both kinds are satisfied on both sides:

```python
def test_shared_commander_approval_cascades_to_other_side(session, ...):
    # requester and coverer share the same direct commander `cmd`
    ...
    swaps.approve_soldier_side(session, request_id=req.id, soldier_id=requester.id)
    swaps.approve_soldier_side(session, request_id=req.id, soldier_id=coverer.id)
    swaps.approve_manager_row(session, request_id=req.id, side="requester", commander_id=cmd.id, actor_id=cmd.id)
    rows = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == req.id,
            SwapManagerApproval.commander_id == cmd.id,
        )
    ).scalars().all()
    assert all(r.approved for r in rows)  # both sides' rows for this commander now approved
    assert session.get(SwapRequest, req.id).status == "pending_approval"  # duty manager still required

    dm = ...  # the one duty_manager soldier
    swaps.approve_manager_row(session, request_id=req.id, side="requester", commander_id=dm.id, actor_id=dm.id)
    dm_rows = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == req.id,
            SwapManagerApproval.commander_id == dm.id,
        )
    ).scalars().all()
    assert all(r.approved for r in dm_rows)
    assert session.get(SwapRequest, req.id).status == "applied"
```

- [ ] **Step 2: Run test to verify it fails** — `pytest backend/tests/services/test_swaps.py -k shared_commander_cascade -v`.

- [ ] **Step 3: Implement.** Replace `_all_approved`:

```python
def _all_approved(session: Session, req: SwapRequest) -> bool:
    """Both soldiers must have approved, and — for each (side, approver_kind)
    combination that has at least one required row — at least one of that
    combination's rows must be approved (any single required approver of
    that kind suffices; a combination with zero rows is trivially satisfied,
    e.g. no duty manager exists, or a side has no commander in its chain)."""
    if not (req.requester_side_approved and req.covering_side_approved):
        return False
    for side in ("requester", "covering"):
        for kind in ("commander", "duty_manager"):
            has_rows = session.execute(
                select(SwapManagerApproval.id).where(
                    SwapManagerApproval.swap_request_id == req.id,
                    SwapManagerApproval.side == side,
                    SwapManagerApproval.approver_kind == kind,
                ).limit(1)
            ).first()
            if has_rows is None:
                continue
            has_approved = session.execute(
                select(SwapManagerApproval.id).where(
                    SwapManagerApproval.swap_request_id == req.id,
                    SwapManagerApproval.side == side,
                    SwapManagerApproval.approver_kind == kind,
                    SwapManagerApproval.approved == True,  # noqa: E712
                ).limit(1)
            ).first()
            if has_approved is None:
                return False
    return True
```

In `approve_manager_row`, after the existing `if not row.approved:` block that sets `row.approved = True` and writes the audit row, add the cascade before `session.flush()`:

```python
        # Same person may be the required approver for both sides at once
        # (one commander over both soldiers, or the org's one duty manager)
        # — approving once should satisfy both sides instead of asking for
        # a second click.
        other_side = "covering" if side == "requester" else "requester"
        other_row = session.execute(
            select(SwapManagerApproval).where(
                SwapManagerApproval.swap_request_id == request_id,
                SwapManagerApproval.side == other_side,
                SwapManagerApproval.commander_id == commander_id,
                SwapManagerApproval.approved == False,  # noqa: E712
            )
        ).scalar_one_or_none()
        if other_row is not None:
            other_row.approved = True
            other_row.approved_by = actor_id
            other_row.approved_at = row.approved_at
            write_audit(
                session, actor_id=actor_id, action="swap.manager_approve", entity_type="swap_request",
                entity_id=req.id, after={"side": other_side, "commander_id": str(commander_id), "cascaded": True},
            )
        session.flush()
```

- [ ] **Step 4: Run test to verify it passes** — `pytest backend/tests/services/test_swaps.py -k "shared_commander_cascade or duty_manager_rows" -v`.

- [ ] **Step 5: Commit** — `git add backend/app/services/swaps.py backend/tests/services/test_swaps.py && git commit -m "feat: require commander+duty-manager approval per swap side, cascade shared approver"`

### Task 1.3: Expose `approver_kind` and the new setting through the API

**Files:**
- Modify: `backend/app/routes/swaps.py:26-33` (`SwapManagerApprovalOut`), `:99-118` (`_manager_approvals_out`), `:121-140` (`_manager_approvals_out_bulk`), `:205-210` (`swap_config`)
- Test: `backend/tests/routes/test_swaps_routes.py` (or wherever the `/swaps/config` and manager-approve routes are covered — grep `swap_config`)

**Interfaces:**
- Produces: `SwapManagerApprovalOut.approver_kind: str`; `GET /swaps/config` now returns `{"require_manager_approval": bool, "require_duty_manager_approval": bool}`.

- [ ] **Step 1: Write the failing test:**

```python
def test_swap_config_reports_duty_manager_setting(client, admin_token, session):
    set_setting(session, "swaps.require_duty_manager_approval", False, actor_id=None)
    session.commit()
    r = client.get("/swaps/config", headers=auth_header(admin_token))
    assert r.json() == {"require_manager_approval": True, "require_duty_manager_approval": False}
```

- [ ] **Step 2: Run test to verify it fails** — `pytest backend/tests -k swap_config_reports_duty_manager -v`.

- [ ] **Step 3: Implement.** Add `approver_kind: str` to `SwapManagerApprovalOut`; set it from `row.approver_kind` in both `_manager_approvals_out` and `_manager_approvals_out_bulk`. Update `swap_config`:

```python
@router.get("/swaps/config")
def swap_config(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    return {
        "require_manager_approval": svc._require_approval(session),
        "require_duty_manager_approval": svc._require_duty_manager_approval(session),
    }
```

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Commit** — `git add backend/app/routes/swaps.py backend/tests && git commit -m "feat: expose approver_kind and duty-manager setting on swap API"`

### Task 1.4: Frontend — show commander vs duty-manager approval status separately

**Files:**
- Modify: `frontend/src/api/swaps.ts:3-10` (`SwapManagerApproval`), `:125-127` (`getSwapConfig`)
- Modify: `frontend/src/components/DirectCommanderApproval.tsx`
- Modify: `frontend/src/pages/SwapsPage.tsx:73-91` (`PendingSide`), `:156-171` (`ApprovalStatus`), `:293-297` (config query)
- Modify: `frontend/src/i18n/he.json` (add keys)

**Interfaces:**
- Consumes: `SwapManagerApprovalOut.approver_kind` from Task 1.3.
- Produces: `DirectCommanderApproval` renamed usage stays the same component name (avoid a rename churn across the file) but now accepts an `approverKindLabel` prop and groups by kind internally via a new exported helper `groupByKind(approvals): { commander: DirectCommanderApprovalRow[]; duty_manager: DirectCommanderApprovalRow[] }`.

- [ ] **Step 1:** In `api/swaps.ts`, add `approver_kind: "commander" | "duty_manager";` to the `SwapManagerApproval` interface, and change `getSwapConfig`'s return type to `{ require_manager_approval: boolean; require_duty_manager_approval: boolean }`.

- [ ] **Step 2:** In `DirectCommanderApproval.tsx`, add and export:

```tsx
export function groupByKind(approvals: (DirectCommanderApprovalRow & { approver_kind: "commander" | "duty_manager" })[]) {
  return {
    commander: approvals.filter((a) => a.approver_kind === "commander"),
    duty_manager: approvals.filter((a) => a.approver_kind === "duty_manager"),
  };
}
```

Update the component to accept the fuller row type (extend `DirectCommanderApprovalRow` with `approver_kind`) — no other change needed since it already shows "any one approves = satisfied" per the list it's given; callers will now pass it one kind's list at a time and label which kind it is.

- [ ] **Step 3:** In `SwapsPage.tsx`, add he.json keys `swaps.approver_kind_commander` = `"מפקד"`, `swaps.approver_kind_duty_manager` = `"אחראי תורנויות"`. In `ApprovalStatus`, replace the single `DirectCommanderApproval` call per side with two calls (commander + duty manager, the latter only rendered when `requireDutyManagerApproval` is true), each preceded by its label:

```tsx
function ApprovalStatus({ swap, requireManagerApproval, requireDutyManagerApproval }: {
  swap: SwapRequest; requireManagerApproval: boolean; requireDutyManagerApproval: boolean;
}) {
  const { t } = useTranslation();
  if (!requireManagerApproval || swap.status !== "pending_approval") return null;
  const reqGroups = groupByKind(swap.requester_manager_approvals);
  const covGroups = groupByKind(swap.covering_manager_approvals);
  return (
    <div className="text-xs text-gray-500 dark:text-gray-400 space-y-1 mt-1">
      <div className="flex flex-wrap gap-3">
        <span>{t("swaps.requester_approval")}: <ApprovalDot value={swap.requester_side_approved} /></span>
        <span>{t("swaps.covering_approval")}: <ApprovalDot value={swap.covering_side_approved} /></span>
      </div>
      <div className="flex flex-col gap-1">
        <span>{t("swaps.requester_managers")} ({t("swaps.approver_kind_commander")}): <DirectCommanderApproval approvals={reqGroups.commander} /></span>
        {requireDutyManagerApproval && (
          <span>{t("swaps.requester_managers")} ({t("swaps.approver_kind_duty_manager")}): <DirectCommanderApproval approvals={reqGroups.duty_manager} /></span>
        )}
        <span>{t("swaps.covering_managers")} ({t("swaps.approver_kind_commander")}): <DirectCommanderApproval approvals={covGroups.commander} /></span>
        {requireDutyManagerApproval && (
          <span>{t("swaps.covering_managers")} ({t("swaps.approver_kind_duty_manager")}): <DirectCommanderApproval approvals={covGroups.duty_manager} /></span>
        )}
      </div>
    </div>
  );
}
```

Thread `requireDutyManagerApproval` from `configQuery.data?.require_duty_manager_approval ?? true` down through `SwapsPage`'s two `<ApprovalStatus .../>` call sites and `<PendingApprovalCard .../>` (add the same prop there, mirroring how `requireManagerApproval` is already threaded).

- [ ] **Step 4:** Run `npm run typecheck` from `frontend/` — expect 0 new errors.

- [ ] **Step 5: Commit** — `git add frontend/src/api/swaps.ts frontend/src/components/DirectCommanderApproval.tsx frontend/src/pages/SwapsPage.tsx frontend/src/i18n/he.json && git commit -m "feat: show commander/duty-manager approval status separately in swaps UI"`

### Task 1.5: Fix the Help modal's swap copy + add a page-level "?" help icon (deep-link, no duplication)

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx:58-112` (`SwapsTab`), and the modal's props/signature (grep for where `activeTab` state is declared, likely just above line 1009 per the survey)
- Modify: `frontend/src/components/Layout.tsx:12-29` (lift `helpOpen`/`setHelpOpen`) — add a way for pages to open the modal to a specific tab.
- Modify: `frontend/src/pages/SwapsPage.tsx` (add "?" icon)

**Interfaces:**
- Produces: `HelpModal` accepts an `initialTab?: string` prop (defaults to `"swaps"`, unchanged from today). `Layout` exposes a new render-prop/context so a child page can call `openHelp("swaps")`. Simplest implementation matching existing patterns in this codebase (no new context provider needed elsewhere): change `Layout`'s children signature to `children: ReactNode | ((openHelp: (tab?: string) => void) => ReactNode)` — if `children` is a function, call it with `openHelp`; otherwise render as today. `SwapsPage` switches to the function-children form to get `openHelp`.

- [ ] **Step 1:** In `HelpModal.tsx`, fix `SwapsTab`'s flow diagram and bullet list to describe the new rule (one commander AND one duty manager per side, unless the same person covers both sides). Replace the `"נדרש אישור מפקד"` / `"ללא אישור"` two-column diagram block (lines ~76-90) with a three-column version (`"מפקד + אחראי תורנויות"` / `"רק מפקד"` — n/a here, keep it simple: this app doesn't need a third "commander only" branch since the setting is global) — concretely, replace the inner two-column `<div className="grid grid-cols-2 gap-2">` block with:

```tsx
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <div className="text-center text-xs text-gray-400">נדרש אישור</div>
            <FlowStep icon="👮" text="מפקד אחד מהשרשרת מאשר" color="amber" />
            <FlowStep icon="🗂️" text="אחראי תורנויות מאשר" color="amber" />
            <Arrow />
            <FlowStep icon="✅" text="ההחלפה בוצעה!" color="green" />
          </div>
          <div className="space-y-1">
            <div className="text-center text-xs text-gray-400">ללא אישור</div>
            <div className="h-16" />
            <Arrow />
            <FlowStep icon="✅" text="ההחלפה בוצעה!" color="green" />
          </div>
        </div>
```

Add a bullet under the `⚠️ חשוב לדעת` box: `<li>אם אותו מפקד או אותו אחראי תורנויות אחראים על שני הצדדים, אישור אחד שלו מספיק לשניהם.</li>`.

- [ ] **Step 2:** Change `HelpModal`'s props to accept `initialTab?: string` and initialize `activeTab` state from it (`useState(initialTab ?? "swaps")`), keeping the default identical to today when omitted.

- [ ] **Step 3:** In `Layout.tsx`, change the component to support function-children:

```tsx
export default function Layout({ children }: { children: ReactNode | ((openHelp: (tab?: string) => void) => ReactNode) }) {
  ...
  const [helpTab, setHelpTab] = useState<string | undefined>(undefined);
  function openHelp(tab?: string) { setHelpTab(tab); setHelpOpen(true); }
  ...
  {helpOpen && <HelpModal onClose={() => setHelpOpen(false)} gimelimEnabled={gimelimEnabled} initialTab={helpTab} />}
  ...
  <main className="flex-1 overflow-y-auto px-4 py-6 pb-24 md:pb-6">
    {typeof children === "function" ? children(openHelp) : children}
  </main>
```

Also change the existing header `HelpCircle` button's `onClick` to `() => openHelp()` (keeps default "swaps" tab landing, unchanged behavior).

- [ ] **Step 4:** In `SwapsPage.tsx`, wrap the existing `return (<Layout>...</Layout>)` body so `Layout`'s children become `(openHelp) => (<>...</>)`, and add a "?" button next to the page title:

```tsx
<div className="flex items-center gap-2 mb-4">
  <h2 className="text-xl font-semibold dark:text-gray-100">{t("swaps.title")}</h2>
  <button
    type="button"
    onClick={() => openHelp("swaps")}
    aria-label={t("swaps.help_aria")}
    className="text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-300"
  >
    <HelpCircle size={16} />
  </button>
</div>
```

(import `HelpCircle` from `lucide-react`; add he.json key `swaps.help_aria` = `"עזרה על החלפות"`.)

- [ ] **Step 5:** Manual check — start the dev stack, open the Swaps page, click the new "?" icon, confirm the Help modal opens already on the swaps tab (no duplicated content, since it reuses `HelpModal`'s existing `SwapsTab`).

- [ ] **Step 6: Commit** — `git add frontend/src/components/HelpModal.tsx frontend/src/components/Layout.tsx frontend/src/pages/SwapsPage.tsx frontend/src/i18n/he.json && git commit -m "feat: swap help copy for commander+duty-manager approval, page-level help icon"`

---

## Item 2 — Transparency page visibility setting

**Files:**
- Modify: `backend/app/routes/scoring.py:103-112` (`transparency` route)
- Test: `backend/tests/routes/test_scoring_routes.py` (or wherever transparency route tests live — grep `/scoring/transparency`)

**Design:** `role` alone is too coarse for "מפקדי מדור/ענף/צוות" (commanders of a *specific hierarchy level*, e.g. section/branch/team) — a soldier's `role` field is just a derived `soldier`/`commander`/`duty_manager`/`admin` label with no level information. This app already models levels properly via `HierarchyLevelType` (admin-defined, keyed, ranked) and `HierarchyNode.commander_id`/`HierarchyNode.level` (see `backend/app/services/hierarchy.py`, `GET /hierarchy/level-types`) — a soldier genuinely commands level `X` iff a `HierarchyNode` exists with `level == X` and `commander_id == soldier.id`. Use that directly instead of approximating with the `role` string.

New setting `transparency.visible_commander_levels`: a JSON array of `HierarchyLevelType.key` strings, or unset/`null`/`[]` (default) meaning **no restriction — everyone can view**, matching today's behavior exactly. When set to a non-empty list, a viewer is allowed iff: `user.role == "admin"`, or `user.role == "duty_manager"`, or the viewer commands at least one `HierarchyNode` whose `level` is in the list (checked via `HierarchyNode.commander_id == user.id`, level-aware, not role-aware — a `commander`-role soldier who commands a node at an excluded level is correctly denied even though their `role` string says "commander").

### Task 2.1: Backend — gate the transparency route by commanded hierarchy level

**Files:**
- Modify: `backend/app/routes/scoring.py:1-18` (imports), `:103-112` (`transparency`)
- Test: `backend/tests/routes/test_scoring_routes.py`

**Interfaces:**
- Produces: `_transparency_allowed(session, user) -> bool` in `scoring.py`.

- [ ] **Step 1: Write the failing test:**

```python
def test_transparency_denied_for_commander_at_excluded_level(client, session, soldier_token, hierarchy_factory):
    # soldier_token's soldier commands a node at level "team"
    node = hierarchy_factory.node(level="team", commander_id=soldier_id_for(soldier_token))
    set_setting(session, "transparency.visible_commander_levels", ["brigade"], actor_id=None)
    session.commit()
    r = client.get("/scoring/transparency", headers=auth_header(soldier_token))
    assert r.status_code == 403

def test_transparency_allowed_for_commander_at_included_level(client, session, soldier_token, hierarchy_factory):
    node = hierarchy_factory.node(level="team", commander_id=soldier_id_for(soldier_token))
    set_setting(session, "transparency.visible_commander_levels", ["team", "branch"], actor_id=None)
    session.commit()
    r = client.get("/scoring/transparency", headers=auth_header(soldier_token))
    assert r.status_code == 200

def test_transparency_allowed_for_duty_manager_regardless_of_level(client, session, duty_manager_token):
    set_setting(session, "transparency.visible_commander_levels", ["team"], actor_id=None)
    session.commit()
    r = client.get("/scoring/transparency", headers=auth_header(duty_manager_token))
    assert r.status_code == 200

def test_transparency_allowed_by_default(client, session, soldier_token):
    r = client.get("/scoring/transparency", headers=auth_header(soldier_token))
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails** — `pytest backend/tests/routes/test_scoring_routes.py -k transparency_denied_for_commander -v`.

- [ ] **Step 3: Implement.** Add near the top of `scoring.py`:

```python
from sqlalchemy import select as _select  # if `select` isn't already imported under that name — check existing imports first, reuse the existing `select` import instead of adding a second one
from app.db.models import HierarchyNode
from app.services.settings_loader import SettingNotFound, get_setting


def _transparency_allowed(session: Session, user: Soldier) -> bool:
    try:
        levels = get_setting(session, "transparency.visible_commander_levels")
    except SettingNotFound:
        levels = None
    if not levels:
        return True  # no restriction configured — everyone can view (default, matches today)
    if user.role in ("admin", "duty_manager"):
        return True
    return session.execute(
        select(HierarchyNode.id).where(
            HierarchyNode.commander_id == user.id,
            HierarchyNode.level.in_(levels),
        ).limit(1)
    ).first() is not None
```

(`scoring.py` already imports `select` from `sqlalchemy` at the top — reuse it, do not add a duplicate import; `HierarchyNode` may already be imported too, per the existing `_node_of` helper at `scoring.py:99-100` — check before adding.)

Update the route:

```python
@router.get("/transparency", response_model=TransparencyOut)
def transparency(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransparencyOut:
    if not _transparency_allowed(session, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="transparency_hidden")
    result = svc.transparency_rows(session, viewer=user)
    return TransparencyOut(
        rows=[TransparencyRow(**row) for row in result["rows"]],
        can_see_exemption_aggregates=result["can_see_exemption_aggregates"],
    )
```

(`HTTPException`/`status` are already imported at the top of the file.)

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Commit** — `git add backend/app/routes/scoring.py backend/tests && git commit -m "feat: gate transparency page by commanded hierarchy level"`

### Task 2.2: Admin settings UI — level-picker for the new setting

**Files:**
- Modify: whichever admin settings page renders the existing `swaps.restrict_to_hierarchy_level`-style controls (locate via `Grep "restrict_to_hierarchy_level"` under `frontend/src/pages`) — expected to be `frontend/src/pages/AdminSettingsPage.tsx` or similar.
- Modify: `frontend/src/pages/TransparencyPage.tsx` — handle the 403 gracefully.

**Interfaces:**
- Consumes: `listLevelTypes(): Promise<LevelTypeDTO[]>` from `frontend/src/api/levelTypes.ts` (already exists, backs `GET /hierarchy/level-types`) — `LevelTypeDTO = { id: string; key: string; label: string; rank: number }`.

- [ ] **Step 1:** In the admin settings page, fetch `listLevelTypes()` and render a checkbox per level type (label = `lt.label`, value = `lt.key`), bound to the `transparency.visible_commander_levels` setting (a `string[]`). Add he.json key `admin_settings.transparency_visible_levels` = `"אילו רמות פיקוד רשאיות לצפות בדף השקיפות (בנוסף לאחראי תורנויות ומנהל)"`. Leave the setting's stored value empty/unset when no checkbox is checked (= no restriction, everyone can view — the backend default), so unchecking everything reproduces today's behavior rather than blocking all non-admins.

- [ ] **Step 2:** In `TransparencyPage.tsx`, wrap the `transparencyQuery` error path: if `transparencyQuery.error` has HTTP status 403, render a simple "אין לך הרשאה לצפות בדף זה" message instead of the table (mirroring the existing `loadError`-style pattern already used in `SwapsPage.tsx:334-336`).

- [ ] **Step 3:** Manual check — as admin, set `transparency.visible_commander_levels` to a level the test soldier does *not* command, log in as that soldier, confirm the page shows the permission message instead of a blank/broken table; log in as a soldier who commands a node at an included level, confirm access; log in as a duty manager, confirm access regardless of the list; reset the setting to empty afterward.

- [ ] **Step 4: Commit** — `git add frontend/src/pages/AdminSettingsPage.tsx frontend/src/pages/TransparencyPage.tsx frontend/src/i18n/he.json && git commit -m "feat: admin control for transparency page visibility by commanded hierarchy level"`

---

## Item 3 — Constraint days remaining, resetting quarterly/semi-annually/annually

**Design:** Add a per-soldier **quota** setting `constraints.reset_period` (`"quarter"` | `"half_year"` | `"year"`, default `"quarter"`) and a **cap** (reuse the existing `constraints.personal_cap_days` setting already read in `submit_constraint`, default 15 — do not introduce a second cap setting). "Remaining days" = cap − days used within the *current period*, where the period boundaries are computed on-the-fly from `reset_period` and `date.today()` (no background job — matches the `fairness.reset_date` on-the-fly pattern already in the codebase; a period start is always the calendar quarter/half-year/year boundary, not an admin-set anchor date, so no extra setting is needed for the anchor).

### Task 3.1: Backend — compute remaining constraint days for the current period

**Files:**
- Modify: `backend/app/services/constraints.py` (add period helpers + `remaining_days`)
- Create: `backend/app/routes/constraints.py` endpoint if one doesn't already exist for "my remaining days" (grep `router.get.*constraints` under `backend/app/routes/` first — if a constraints router exists, add to it instead of assuming a new file)
- Test: `backend/tests/services/test_constraints.py`

**Interfaces:**
- Produces: `constraints.period_bounds(reset_period: str, today: date) -> tuple[date, date]` (inclusive start, exclusive end), `constraints.remaining_days(session, soldier_id: uuid.UUID) -> dict` returning `{"cap_days": int, "used_days": int, "remaining_days": int, "period_start": date, "period_end": date}`.

- [ ] **Step 1: Write the failing test:**

```python
def test_period_bounds_quarter():
    assert constraints.period_bounds("quarter", date(2026, 8, 15)) == (date(2026, 7, 1), date(2026, 10, 1))

def test_period_bounds_half_year():
    assert constraints.period_bounds("half_year", date(2026, 8, 15)) == (date(2026, 7, 1), date(2027, 1, 1))

def test_period_bounds_year():
    assert constraints.period_bounds("year", date(2026, 8, 15)) == (date(2026, 1, 1), date(2027, 1, 1))

def test_remaining_days_counts_only_current_period(session, soldier_factory):
    s = soldier_factory()
    # a constraint entirely inside a past quarter must not count against remaining_days
    constraints.submit_constraint(session, soldier_id=s.id, start_date=date(2026, 1, 5), end_date=date(2026, 1, 10), reason="x")
    with freeze_time(...) or by directly passing today=... if remaining_days accepts it:
        result = constraints.remaining_days(session, soldier_id=s.id, today=date(2026, 8, 1))
    assert result["used_days"] == 0
    assert result["remaining_days"] == result["cap_days"]
```

(Use whatever date-freezing convention this test suite already uses — grep `freeze_time` or a `today` kwarg pattern in `test_constraints.py`; if the suite passes `today` explicitly instead of freezing the clock, give `remaining_days` a `today: date | None = None` parameter defaulting to `date.today()`, matching `_is_eligible`'s `today` param style in `eligibility.py`.)

- [ ] **Step 2: Run test to verify it fails** — `pytest backend/tests/services/test_constraints.py -k "period_bounds or remaining_days" -v`.

- [ ] **Step 3: Implement** in `constraints.py`:

```python
def period_bounds(reset_period: str, today: date) -> tuple[date, date]:
    """Inclusive start / exclusive end of the reset period containing `today`."""
    if reset_period == "half_year":
        start_month = 1 if today.month <= 6 else 7
        start = date(today.year, start_month, 1)
        end = date(today.year, 7, 1) if start_month == 1 else date(today.year + 1, 1, 1)
        return start, end
    if reset_period == "year":
        return date(today.year, 1, 1), date(today.year + 1, 1, 1)
    # default: quarter
    q_start_month = ((today.month - 1) // 3) * 3 + 1
    start = date(today.year, q_start_month, 1)
    end_month = q_start_month + 3
    end = date(today.year, end_month, 1) if end_month <= 12 else date(today.year + 1, 1, 1)
    return start, end


def remaining_days(session: Session, *, soldier_id: uuid.UUID, today: date | None = None) -> dict:
    today = today or date.today()
    reset_period = str(_get_setting_with_default(session, "constraints.reset_period", "quarter"))
    period_start, period_end = period_bounds(reset_period, today)
    cap_days = int(_get_setting_with_default(session, "constraints.personal_cap_days", 15))
    rows = session.execute(
        select(PersonalConstraint).where(
            PersonalConstraint.soldier_id == soldier_id,
            PersonalConstraint.status.in_(["pending", "approved"]),
            PersonalConstraint.start_date < period_end,
            PersonalConstraint.end_date >= period_start,
        )
    ).scalars().all()
    used = 0
    for r in rows:
        overlap_start = max(r.start_date, period_start)
        overlap_end = min(r.end_date, date.fromordinal(period_end.toordinal() - 1))
        used += (overlap_end - overlap_start).days + 1
    return {
        "cap_days": cap_days,
        "used_days": used,
        "remaining_days": max(0, cap_days - used),
        "period_start": period_start,
        "period_end": period_end,
    }
```

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Route.** Grep `backend/app/routes/` for an existing constraints router; add (or create `backend/app/routes/constraints.py` if none exists, following the router-registration pattern in `backend/app/main.py` — check how other routers are included):

```python
@router.get("/me/constraints/remaining", response_model=RemainingDaysOut)
def my_remaining_constraint_days(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RemainingDaysOut:
    return RemainingDaysOut(**constraints_svc.remaining_days(session, soldier_id=user.id))
```

with `RemainingDaysOut` a `BaseModel` mirroring the dict shape (`cap_days: int`, `used_days: int`, `remaining_days: int`, `period_start: date`, `period_end: date`).

- [ ] **Step 6: Commit** — `git add backend/app/services/constraints.py backend/app/routes backend/tests && git commit -m "feat: compute remaining personal-constraint days for the current reset period"`

### Task 3.2: Admin setting for reset period + frontend display

**Files:**
- Modify: admin settings page (same file as Task 2.2) — add a select for `constraints.reset_period` with options quarter/half_year/year, default quarter.
- Modify: `frontend/src/api/constraints.ts` — add `getRemainingConstraintDays()`.
- Modify: wherever a soldier submits/views their own constraints (likely `frontend/src/pages/MyRequestsPage.tsx` or similar — grep `submitConstraint`/`listSoldierConstraints` usages in `pages/`) — show "נותרו X מתוך Y ימי אילוץ (עד DD/MM/YYYY)".

- [ ] **Step 1:** Add `getRemainingConstraintDays(): Promise<{cap_days: number; used_days: number; remaining_days: number; period_start: string; period_end: string}>` to `api/constraints.ts`, calling `GET /me/constraints/remaining`.

- [ ] **Step 2:** In the constraint-submission page, add a `useQuery` for it and render a small summary line above the submit form using he.json key `constraints.remaining_summary` = `"נותרו {{remaining}} מתוך {{cap}} ימי אילוץ (עד {{until}})"` (interpolated via `t("constraints.remaining_summary", { remaining, cap, until: formatDate(period_end) })`).

- [ ] **Step 3:** Admin settings page: add the `constraints.reset_period` select, he.json key `admin_settings.constraints_reset_period` = `"תקופת איפוס ימי אילוץ"`, options labeled `"רבעון"` / `"חצי שנה"` / `"שנה"`.

- [ ] **Step 4:** Manual check — submit a constraint, confirm the remaining-days line updates after refetch.

- [ ] **Step 5: Commit** — `git add frontend/src/api/constraints.ts frontend/src/pages frontend/src/i18n/he.json && git commit -m "feat: show remaining constraint days and admin reset-period setting"`

---

## Item 4 — Discharge button: start date first, not the confirm dialog

**Files:**
- Modify: `frontend/src/components/EntriesExitsPanel.tsx:1-40, 64-87` (`handleRelease`, the release button, and a new modal)
- Modify: `frontend/src/i18n/he.json`

**Current:** clicking "שחרר" triggers a native `window.confirm()`, then immediately calls `softDeleteSoldier(soldierId)` — no date is ever collected. **Requested:** the first click should open a small modal whose first field is a start date (i.e. discharge/leave date), not a generic yes/no confirm.

Check whether `softDeleteSoldier` (`api/soldiers.ts:68-70`, `DELETE /soldiers/{id}`) accepts a date at all — grep the backend route (`backend/app/routes/soldiers.py`, `DELETE /{soldier_id}`) before assuming. If the backend delete endpoint has no date parameter, extend it to accept one (map to `Soldier.left_at`, which already exists per `models.py:40`).

### Task 4.1: Backend — accept a discharge date on soldier release

**Files:**
- Modify: `backend/app/routes/soldiers.py` (`DELETE /{soldier_id}` route — locate via `Grep "DELETE" backend/app/routes/soldiers.py` or the existing `@router.delete` decorator)
- Modify: `backend/app/services/soldiers.py` (whatever function implements soft-delete — grep `left_at` assignment)
- Test: `backend/tests/routes/test_soldiers_routes.py`

- [ ] **Step 1: Write the failing test:**

```python
def test_release_soldier_sets_left_at_to_given_date(client, session, admin_token, soldier_factory):
    s = soldier_factory()
    r = client.delete(f"/soldiers/{s.id}", params={"left_at": "2026-08-01"}, headers=auth_header(admin_token))
    assert r.status_code == 204
    session.refresh(s)
    assert s.left_at == date(2026, 8, 1)
```

- [ ] **Step 2: Run test to verify it fails** — `pytest backend/tests/routes/test_soldiers_routes.py -k release_soldier_sets_left_at -v`.

- [ ] **Step 3: Implement.** In the soft-delete service function, accept `left_at: date | None = None` and set `soldier.left_at = left_at or date.today()` (preserve today-as-default so any other caller of the service function keeps working unchanged). In the route, add `left_at: date | None = Query(default=None)` and pass it through.

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Commit** — `git add backend/app/routes/soldiers.py backend/app/services/soldiers.py backend/tests && git commit -m "feat: accept a discharge date when releasing a soldier"`

### Task 4.2: Frontend — start-date-first release modal

**Files:**
- Modify: `frontend/src/api/soldiers.ts:68-70` (`softDeleteSoldier`)
- Modify: `frontend/src/components/EntriesExitsPanel.tsx`

- [ ] **Step 1:** Change `softDeleteSoldier` to `softDeleteSoldier(id: string, leftAt: string): Promise<void>` sending `left_at` as a query param:

```ts
export async function softDeleteSoldier(id: string, leftAt: string): Promise<void> {
  await api.delete(`/soldiers/${id}`, { params: { left_at: leftAt } });
}
```

- [ ] **Step 2:** In `EntriesExitsPanel.tsx`, add state `releaseTarget: SoldierWithStatus | null` and `releaseDate: string` (defaulting to today's ISO date, `new Date().toISOString().slice(0, 10)`). Replace `handleRelease`'s direct call with opening the modal:

```tsx
function openReleaseModal(s: SoldierWithStatus) {
  setReleaseTarget(s);
  setReleaseDate(new Date().toISOString().slice(0, 10));
}

async function handleConfirmRelease() {
  if (!releaseTarget) return;
  await softDeleteSoldier(releaseTarget.id, releaseDate);
  setReleaseTarget(null);
  onRefresh();
}
```

Change the release button's `onClick` from `() => handleRelease(s.id)` to `() => openReleaseModal(s)`. Add a modal (mirroring the existing `exemptTarget`/`moveTarget` modal pattern already in this file) whose *first* field is the date:

```tsx
{releaseTarget && (
  <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setReleaseTarget(null)}>
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
      <h3 className="font-bold text-lg mb-4">{t("command_dashboard.release")} - {releaseTarget.full_name}</h3>
      <div className="space-y-3">
        <label className="block text-sm">{t("command_dashboard.release_date")}</label>
        <input type="date" lang="he" className="w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          value={releaseDate} onChange={(e) => setReleaseDate(e.target.value)} autoFocus />
        <div className="flex gap-2 justify-end pt-2">
          <button onClick={() => setReleaseTarget(null)} className="px-3 py-1 border rounded text-sm">{t("command_dashboard.cancel")}</button>
          <button onClick={handleConfirmRelease} className="px-3 py-1 bg-red-600 text-white rounded text-sm">{t("command_dashboard.confirm_release")}</button>
        </div>
      </div>
    </div>
  </div>
)}
```

Remove the now-unused `handleRelease`/`window.confirm` code. Add he.json key `command_dashboard.release_date` = `"תאריך שחרור"` (`command_dashboard.confirm_release` already exists as the old confirm-dialog text — repurpose it as the modal's confirm-button label, which is consistent with its existing meaning).

- [ ] **Step 3:** Manual check — click "שחרר", confirm a modal opens with a date field pre-filled to today (editable), confirm submitting calls the API with that date and refreshes the roster.

- [ ] **Step 4: Commit** — `git add frontend/src/api/soldiers.ts frontend/src/components/EntriesExitsPanel.tsx frontend/src/i18n/he.json && git commit -m "feat: collect discharge start date before releasing a soldier"`

---

## Item 5 — Targeted swap request: eligible/available soldier picker sorted by hierarchy distance, capped at N

**Design:** Add a backend endpoint that, given a duty assignment, returns every soldier who is both eligible (`check_soldier_for_assignment`) and available, each annotated with hierarchy distance from the requesting soldier (reuse `_hierarchy_distance` logic — algorithm-layer code can't import DB models, so port a session-based equivalent into `hierarchy.py`), sorted ascending by that distance, excluding soldiers beyond the existing `swaps.restrict_to_hierarchy_level` cutoff when set. Add a system setting `swaps.max_specific_targets` (int, default e.g. 5) capping how many soldiers `AskSwapModal` lets the user select. `target_soldier_id` on `SwapRequest`/`create_request` is currently singular — this plan extends it to a list without breaking the single-target `target_soldier_id` column (see below).

### Task 5.1: Backend — hierarchy-distance helper + eligible-soldiers endpoint

**Files:**
- Modify: `backend/app/services/hierarchy.py` (add `node_distance`)
- Modify: `backend/app/services/eligibility.py` or a new `backend/app/services/swap_targets.py` (compute the picker list)
- Modify: `backend/app/routes/swaps.py` (new `GET /swaps/eligible-targets` route)
- Test: `backend/tests/services/test_hierarchy.py`, `backend/tests/routes/test_swaps_routes.py`

**Interfaces:**
- Produces: `hierarchy.node_distance(session, node_a: uuid.UUID | None, node_b: uuid.UUID | None) -> int` (symmetric-difference of ancestor path sets, mirroring `app.algorithm.reserve._hierarchy_distance` but against `HierarchyNode.path_ids` already loaded via SQLAlchemy instead of a pre-built `hierarchy_parent` dict — returns a large sentinel, e.g. `10**6`, if either node is `None`, so unassigned soldiers sort last). `swap_targets.list_eligible_targets(session, *, requesting_soldier_id, duty_assignment_id) -> list[dict]` returning `{"soldier_id", "full_name", "node_name", "hierarchy_distance"}` sorted ascending by distance, filtered to `check_soldier_for_assignment(...)[0] is True` and passing `_enforce_hierarchy_level_restriction` (catch `SwapError` per-candidate and skip rather than raising, since this is a listing endpoint not a mutation).

- [ ] **Step 1: Write the failing test** for `node_distance`:

```python
def test_node_distance_siblings_vs_self(session, hierarchy_factory):
    root = hierarchy_factory.node(level="brigade")
    a = hierarchy_factory.node(level="team", parent=root)
    b = hierarchy_factory.node(level="team", parent=root)
    assert hierarchy.node_distance(session, a.id, a.id) == 0
    assert hierarchy.node_distance(session, a.id, b.id) == 2  # each has one ancestor the other lacks... adjust based on path_ids semantics
    assert hierarchy.node_distance(session, a.id, None) >= 10**6
```

(Pin down the exact expected sibling distance by running `_hierarchy_distance`'s existing algorithm-layer tests first — grep `backend/tests` for `_hierarchy_distance` to copy the established semantics exactly, since `node_distance` must match it.)

- [ ] **Step 2: Run test to verify it fails.**

- [ ] **Step 3: Implement** `node_distance` in `hierarchy.py`:

```python
_UNREACHABLE_DISTANCE = 10**6


def node_distance(session: Session, node_a: uuid.UUID | None, node_b: uuid.UUID | None) -> int:
    """Symmetric-difference distance between two nodes' ancestor chains
    (self included), mirroring app.algorithm.reserve._hierarchy_distance but
    reading HierarchyNode.path_ids directly instead of a pre-built parent map."""
    if node_a is None or node_b is None:
        return _UNREACHABLE_DISTANCE
    if node_a == node_b:
        return 0
    a = session.get(HierarchyNode, node_a)
    b = session.get(HierarchyNode, node_b)
    if a is None or b is None:
        return _UNREACHABLE_DISTANCE
    set_a, set_b = set(a.path_ids), set(b.path_ids)
    return len(set_a.symmetric_difference(set_b))
```

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Write the failing test** for `list_eligible_targets` (new file `backend/app/services/swap_targets.py` — service test in `backend/tests/services/test_swap_targets.py`):

```python
def test_list_eligible_targets_sorted_by_distance_and_excludes_ineligible(session, ...):
    # requester under node R; candidate close under R's sibling (distance 2),
    # candidate far under an unrelated branch (distance 6); candidate with an
    # active exemption for the duty type (must be excluded)
    results = swap_targets.list_eligible_targets(
        session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id
    )
    ids_in_order = [r["soldier_id"] for r in results]
    assert ids_in_order == [close.id, far.id]  # sorted ascending, exempt one excluded
```

- [ ] **Step 6: Run test to verify it fails.**

- [ ] **Step 7: Implement** `swap_targets.py`:

```python
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, Soldier
from app.services import hierarchy as hierarchy_svc
from app.services.eligibility import check_soldier_for_assignment
from app.services.swaps import SwapError, _enforce_hierarchy_level_restriction


def list_eligible_targets(
    session: Session, *, requesting_soldier_id: uuid.UUID, duty_assignment_id: uuid.UUID
) -> list[dict]:
    assignment = session.get(DutyAssignment, duty_assignment_id)
    if assignment is None:
        return []
    requester = session.get(Soldier, requesting_soldier_id)
    if requester is None:
        return []
    candidates = session.execute(
        select(Soldier).where(Soldier.id != requesting_soldier_id, Soldier.left_at.is_(None))
    ).scalars().all()

    out: list[dict] = []
    for c in candidates:
        eligible, _reason = check_soldier_for_assignment(session, c.id, duty_assignment_id)
        if not eligible:
            continue
        try:
            _enforce_hierarchy_level_restriction(
                session, requesting_soldier_id=requesting_soldier_id, other_soldier_id=c.id
            )
        except SwapError:
            continue
        distance = hierarchy_svc.node_distance(session, requester.hierarchy_node_id, c.hierarchy_node_id)
        node_name = None
        if c.hierarchy_node_id:
            node = session.get(hierarchy_svc.HierarchyNode, c.hierarchy_node_id)
            node_name = node.name if node else None
        out.append({
            "soldier_id": c.id, "full_name": c.full_name,
            "node_name": node_name, "hierarchy_distance": distance,
        })
    out.sort(key=lambda r: r["hierarchy_distance"])
    return out
```

(`_enforce_hierarchy_level_restriction` is currently a "private" `swaps.py` helper — either import it as-is, since Python doesn't enforce the underscore, or promote it to a public name; keep the change minimal and just import the underscore name to avoid an unrelated rename.)

- [ ] **Step 8: Run test to verify it passes.**

- [ ] **Step 9: Route.** In `routes/swaps.py`, add:

```python
class EligibleTargetOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    node_name: str | None
    hierarchy_distance: int


@router.get("/swaps/eligible-targets", response_model=list[EligibleTargetOut])
def eligible_targets(
    duty_assignment_id: uuid.UUID = Query(...),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_enrolled),
) -> list[EligibleTargetOut]:
    from app.services import swap_targets
    return [EligibleTargetOut(**r) for r in swap_targets.list_eligible_targets(
        session, requesting_soldier_id=user.id, duty_assignment_id=duty_assignment_id,
    )]
```

- [ ] **Step 10: Commit** — `git add backend/app/services/hierarchy.py backend/app/services/swap_targets.py backend/app/routes/swaps.py backend/tests && git commit -m "feat: eligible-swap-target listing sorted by hierarchy distance"`

### Task 5.2: Backend — allow multiple targeted soldiers per swap request, N-cap setting

**Files:**
- Modify: `backend/app/services/swaps.py:55-124` (`create_request`)
- Modify: `backend/app/routes/swaps.py` (`CreateSwapRequest`)
- Test: `backend/tests/services/test_swaps.py`

**Design:** Keep `SwapRequest.target_soldier_id` singular (schema stability — it's a directed-request-to-one-peer model), but let `create_request` accept `target_soldier_ids: list[uuid.UUID] | None` and fan out into **one `SwapRequest` row per target** (each independently claimable/cancelable — this matches "בקשה ממוקדת" already being a single-target concept end-to-end; requesting N soldiers becomes N parallel open requests for the same duty, and whichever one is claimed first cancels the rest via the existing `already_pending` guard... but that guard keys off `duty_assignment_id` alone and would block the 2nd-Nth from being created. Extend the "existing open request" uniqueness check to be per-`(duty_assignment_id, target_soldier_id)` instead of per-`duty_assignment_id`, and when *any* of the N is claimed/applied, auto-cancel the sibling requests for the same assignment.

- [ ] **Step 1: Write the failing test:**

```python
def test_create_request_fans_out_to_multiple_targets_capped_at_setting(session, ...):
    set_setting(session, "swaps.max_specific_targets", 2, actor_id=None)
    session.commit()
    with pytest.raises(swaps.SwapError, match="too_many_targets"):
        swaps.create_request(session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
                              target_soldier_ids=[s1.id, s2.id, s3.id], reason=None)

    reqs = swaps.create_request(session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
                                 target_soldier_ids=[s1.id, s2.id], reason=None)
    assert len(reqs) == 2
    assert {r.target_soldier_id for r in reqs} == {s1.id, s2.id}


def test_claiming_one_targeted_request_cancels_siblings(session, ...):
    reqs = swaps.create_request(session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
                                 target_soldier_ids=[s1.id, s2.id], reason=None)
    req_for_s1 = next(r for r in reqs if r.target_soldier_id == s1.id)
    swaps.claim_request(session, request_id=req_for_s1.id, covering_soldier_id=s1.id)
    req_for_s2 = next(r for r in reqs if r.target_soldier_id == s2.id)
    session.refresh(req_for_s2)
    assert req_for_s2.status == "cancelled"
```

- [ ] **Step 2: Run test to verify it fails.**

- [ ] **Step 3: Implement.** Add setting helper:

```python
def _max_specific_targets(session: Session) -> int:
    try:
        return int(get_setting(session, "swaps.max_specific_targets"))
    except SettingNotFound:
        return 5
```

Change `create_request`'s signature to accept `target_soldier_ids: list[uuid.UUID] | None = None` in addition to the existing `target_soldier_id` (keep both for backward compatibility — if `target_soldier_ids` is given, ignore `target_soldier_id`; existing single-target callers keep working unmodified). At the top of the function body:

```python
def create_request(
    session: Session, *, requesting_soldier_id: uuid.UUID, duty_assignment_id: uuid.UUID,
    target_soldier_id: uuid.UUID | None, reason: str | None,
    target_soldier_ids: list[uuid.UUID] | None = None,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest | list[SwapRequest]:
    targets = target_soldier_ids if target_soldier_ids is not None else (
        [target_soldier_id] if target_soldier_id is not None else [None]
    )
    if len(targets) > _max_specific_targets(session):
        raise SwapError("too_many_targets")
    if len(targets) > 1:
        return [
            _create_single_request(session, requesting_soldier_id=requesting_soldier_id,
                                    duty_assignment_id=duty_assignment_id, target_soldier_id=t,
                                    reason=reason, actor_id=actor_id)
            for t in targets
        ]
    return _create_single_request(session, requesting_soldier_id=requesting_soldier_id,
                                   duty_assignment_id=duty_assignment_id, target_soldier_id=targets[0],
                                   reason=reason, actor_id=actor_id)
```

Rename the existing function body (everything currently in `create_request`, unchanged) to `_create_single_request` with the same signature minus `target_soldier_ids`, and change its "already pending" uniqueness check from:

```python
    existing = session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == duty_assignment_id,
            SwapRequest.status.in_(["open", "pending_approval"]),
        )
    ).scalar_one_or_none()
```

to:

```python
    existing = session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == duty_assignment_id,
            SwapRequest.target_soldier_id == target_soldier_id,
            SwapRequest.status.in_(["open", "pending_approval"]),
        )
    ).scalar_one_or_none()
```

(this is only reachable for targeted requests since open-board requests, `target_soldier_id is None`, still only ever have one live row per assignment via the pre-existing check path — add `SwapRequest.target_soldier_id.is_(None)` isn't needed because `==None` in SQLAlchemy already handles it via `.is_(None)` translation... actually `Column == None` in SQLAlchemy *does* correctly compile to `IS NULL`, so this is safe as written.)

In `_apply_cover` or right after a targeted request transitions to `"applied"`/`"pending_approval"` inside `claim_request`, cancel sibling open requests for the same assignment+requester (add near the end of `claim_request`, after `session.flush()`):

```python
    session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == req.duty_assignment_id,
            SwapRequest.requesting_soldier_id == req.requesting_soldier_id,
            SwapRequest.id != req.id,
            SwapRequest.status == "open",
        )
    )
    siblings = session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == req.duty_assignment_id,
            SwapRequest.requesting_soldier_id == req.requesting_soldier_id,
            SwapRequest.id != req.id,
            SwapRequest.status == "open",
        )
    ).scalars().all()
    for sib in siblings:
        sib.status = "cancelled"
    session.flush()
```

(Remove the redundant first duplicate `session.execute` line above before committing — keep only the `siblings = ...` query.)

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Route.** In `routes/swaps.py`, change `CreateSwapRequest` to add `target_soldier_ids: list[uuid.UUID] | None = None`, and in the `create` route, call `svc.create_request(..., target_soldier_ids=body.target_soldier_ids)`; when the result is a list, return the *first* item for backward API-shape compatibility but the frontend (Task 5.3) will instead call a variant that returns the array — add a second route `POST /me/swaps/bulk` returning `list[SwapOut]` for the multi-target case, leaving `POST /me/swaps` untouched for the single-target/open-board case used elsewhere (mobile/bot integrations may depend on its current single-object shape).

- [ ] **Step 6: Commit** — `git add backend/app/services/swaps.py backend/app/routes/swaps.py backend/tests && git commit -m "feat: allow targeted swap requests to fan out to up to N soldiers"`

### Task 5.3: Frontend — eligible-soldier table in `AskSwapModal`, capped multi-select

**Files:**
- Modify: `frontend/src/api/swaps.ts` (add `listEligibleTargets`, `createBulkSwap`)
- Modify: `frontend/src/pages/SwapsPage.tsx:173-247` (`AskSwapModal`)
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1:** Add to `api/swaps.ts`:

```ts
export interface EligibleTarget {
  soldier_id: string;
  full_name: string;
  node_name: string | null;
  hierarchy_distance: number;
}

export async function listEligibleTargets(dutyAssignmentId: string): Promise<EligibleTarget[]> {
  return (await api.get<EligibleTarget[]>("/swaps/eligible-targets", {
    params: { duty_assignment_id: dutyAssignmentId },
  })).data;
}

export async function createBulkSwap(input: {
  duty_assignment_id: string; target_soldier_ids: string[]; reason: string | null;
}): Promise<SwapRequest[]> {
  return (await api.post<SwapRequest[]>("/me/swaps/bulk", input)).data;
}

export async function getSwapMaxTargets(): Promise<number> {
  const r = await api.get<{ max_specific_targets: number }>("/swaps/config");
  return r.data.max_specific_targets ?? 5;
}
```

(Extend the `/swaps/config` route from Task 1.3 to also return `max_specific_targets: svc._max_specific_targets(session)`, and add that field to `getSwapConfig`'s return type.)

- [ ] **Step 2:** In `AskSwapModal` (`SwapsPage.tsx`), replace the single `SoldierSearchAutocomplete` (mode === "soldier" branch) with a table fed by `listEligibleTargets(duty.assignment_id)`, sorted as returned (already ascending by distance from the backend), each row showing `full_name` + `(hierarchy_distance)`, with a checkbox per row and a running count against the `n` cap from `getSwapConfig`:

```tsx
const [selectedTargets, setSelectedTargets] = useState<Set<string>>(new Set());
const eligibleQuery = useQuery({
  queryKey: ["swaps", "eligible-targets", duty.assignment_id],
  queryFn: () => listEligibleTargets(duty.assignment_id),
  enabled: mode === "soldier",
});
const eligibleTargets = eligibleQuery.data ?? [];
const configQuery = useQuery({ queryKey: queryKeys.swapConfig(), queryFn: getSwapConfig });
const maxTargets = configQuery.data?.max_specific_targets ?? 5;

function toggleTarget(id: string) {
  setSelectedTargets((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id);
    else if (next.size < maxTargets) next.add(id);
    return next;
  });
}
```

Render (replacing the `mode === "soldier"` block):

```tsx
{mode === "soldier" && (
  <div className="space-y-1">
    <p className="text-xs text-gray-500 dark:text-gray-400">
      {t("swaps.select_up_to", { n: maxTargets })} ({selectedTargets.size}/{maxTargets})
    </p>
    <div className="max-h-48 overflow-y-auto border rounded dark:border-gray-600">
      {eligibleTargets.length === 0 ? (
        <p className="text-sm text-gray-500 p-2">{t("swaps.no_eligible_targets")}</p>
      ) : (
        <ul>
          {eligibleTargets.map((s) => (
            <li key={s.soldier_id} className="flex items-center gap-2 px-2 py-1 border-b last:border-b-0 dark:border-gray-700 text-sm">
              <input
                type="checkbox"
                checked={selectedTargets.has(s.soldier_id)}
                disabled={!selectedTargets.has(s.soldier_id) && selectedTargets.size >= maxTargets}
                onChange={() => toggleTarget(s.soldier_id)}
              />
              <span>{s.full_name}{s.node_name ? ` — ${s.node_name}` : ""} ({s.hierarchy_distance})</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  </div>
)}
```

Update `handleSubmit` to call `createBulkSwap` when `mode === "soldier"` and `selectedTargets.size > 0`, else fall back to the existing `createSwap` (open-board) call.

- [ ] **Step 3:** he.json keys: `swaps.select_up_to` = `"בחר עד {{n}} חיילים לבקש מהם"`, `swaps.no_eligible_targets` = `"אין חיילים זמינים וכשירים לתורנות זו"`.

- [ ] **Step 4:** Manual check — open "בקש החלפה" on a duty, switch to "שלח לחייל", confirm the table lists only eligible/available soldiers sorted by ascending distance-in-parens, confirm selecting beyond the cap disables further checkboxes, confirm submit creates one request per selected soldier and they all appear as separate "ממתין" cards, and confirm accepting one auto-cancels the others.

- [ ] **Step 5: Commit** — `git add frontend/src/api/swaps.ts frontend/src/pages/SwapsPage.tsx frontend/src/i18n/he.json && git commit -m "feat: eligible-soldier picker for targeted swap requests, capped multi-select"`

---

## Item 6 — `cover_not_eligible` untranslated string

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx:49-57` (`extractErrorMessage`)
- Modify: `frontend/src/i18n/he.json`

**Root cause** (already confirmed by the survey): the backend raises `f"cover_not_eligible:{reason}"` where `reason` is already a Hebrew string (from `check_soldier_for_assignment`, e.g. `"פטור מסוג תורנות זו"`). `CoverOfferModal.tsx:41-42` already strips the `"cover_not_eligible:"` prefix correctly; `SwapsPage.tsx`'s `extractErrorMessage` (used by the targeted-request create-flow) does not.

- [ ] **Step 1: Write the failing test** (if `SwapsPage.tsx` or `extractErrorMessage` has existing vitest coverage — grep `extractErrorMessage` under `frontend/src/**/*.test.*`; if none exists, extract the function to a small pure-function test since it needs no React rendering):

```ts
test("extractErrorMessage strips the cover_not_eligible prefix", () => {
  const err = { response: { data: { detail: "cover_not_eligible:פטור מסוג תורנות זו" } } };
  expect(extractErrorMessage(err, "שגיאה")).toBe("פטור מסוג תורנות זו");
});
```

- [ ] **Step 2: Run test to verify it fails** — `npm test -- extractErrorMessage` (or the relevant spec file) from `frontend/`.

- [ ] **Step 3: Implement.** In `SwapsPage.tsx`, update `extractErrorMessage`:

```ts
function extractErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string" && detail) {
    if (detail.startsWith("cover_not_eligible:")) {
      return detail.slice("cover_not_eligible:".length) || fallback;
    }
    return detail;
  }
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: unknown } | undefined;
    if (first && typeof first.msg === "string") return first.msg;
  }
  return fallback;
}
```

(No he.json key is needed since the reason text arrives pre-translated in Hebrew from the backend — the prefix was purely an internal error-code marker, not a string meant for display.)

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Commit** — `git add frontend/src/pages/SwapsPage.tsx && git commit -m "fix: strip cover_not_eligible prefix in swap-request error display"`

---

## Item 7 — Calendar view order: 3-day, week, month (month stays default)

**Files:**
- Modify: `frontend/src/components/UnitCalendar.tsx:156-181`

- [ ] **Step 1:** Change `headerToolbar.right` from `"dayGridMonth,timeGridWeek,timeGridThreeDay"` to `"timeGridThreeDay,timeGridWeek,dayGridMonth"`. Leave `initialView="dayGridMonth"` unchanged (month stays the default view on load — only the button *order* changes, not which view opens first).

- [ ] **Step 2:** Manual check — open the unit calendar, confirm it opens on the month view by default, and confirm the toolbar buttons read (right-to-left as rendered, but check visually) 3 ימים / שבוע / חודש in that left-to-right order.

- [ ] **Step 3: Commit** — `git add frontend/src/components/UnitCalendar.tsx && git commit -m "fix: reorder calendar view buttons to 3-day, week, month"`

---

## Item 8 — Soldier profile: driving-license fields (editable) + קבע status (read-only)

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx`
- Modify: `frontend/src/i18n/he.json`

**Design decision (per product owner):** קבע stays derived/read-only (no backend change) — just display it. Driving-license fields (`has_military_driving_license`, `military_driving_license_expiry`) already exist on `Soldier` and are already in `SOLDIER_EDITABLE_FIELDS`/the profile PATCH DTO (`api/soldiers.ts:81`) — they're simply missing from the modal's UI entirely. Note `has_military_driving_license` is **not** in `eligibility.SOLDIER_EDITABLE_FIELDS` (`military_driving_license` is, a different/legacy field-update key used by the self-service field-update flow with its own `Action.MILITARY_LICENSE_DECIDE` approval gate) — the modal's "profile" tab edits go through `updateSoldierProfile`/`PATCH /soldiers/{id}/profile` (the privileged direct-edit path, not the self-service approval path), so no new approval-routing logic is needed there; only `canManage`-gated users and the soldier themself can already reach this tab per the existing `TABS` logic (`UnifiedSoldierModal.tsx:58-62`).

However, the product owner specifically asked: *"if part of the fields requires duty-manager permission, show that it's requesting from the duty manager and ask them"* — this describes the **self-service field-update** flow (`submitFieldUpdate` → `Action.MILITARY_LICENSE_DECIDE`), which is a *different* editable field name (`military_driving_license`, boolean-only, no expiry) than the profile-tab field (`has_military_driving_license` + `military_driving_license_expiry`). Do not conflate them — add the read-only display + privileged edit to the **profile tab** (Task 8.1/8.2) as the primary ask, and separately confirm (Task 8.3) that a self soldier without `canManage` who wants to change their license status is already routed through the existing self-service `military_driving_license` field-update flow with its existing duty-manager approval UI — if that self-service entry point isn't reachable from `UnifiedSoldierModal` today, add it.

### Task 8.1: Display driving-license + קבע fields (read-only view)

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx:354-364` (read-only "profile" tab block)
- Modify: `frontend/src/api/soldiers.ts:3-29` (`SoldierDTO`) — confirm `is_career` is present; if not, add it.
- Modify: `backend/app/routes/soldiers.py` — confirm the soldier serializer includes `is_career`; if not, add it (grep the `SoldierOut`-equivalent Pydantic model).

- [ ] **Step 1:** Grep `backend/app/routes/soldiers.py` for the soldier response model (e.g. `class SoldierOut(BaseModel)`) and confirm `is_career: bool` is already a field (it's a plain column on `Soldier`, `models.py:52`, so it's likely already serialized — verify, don't assume). If missing, add `is_career: bool` to the model and its construction.

- [ ] **Step 2:** If missing, add `is_career: boolean;` to `SoldierDTO` in `frontend/src/api/soldiers.ts`.

- [ ] **Step 3:** In `UnifiedSoldierModal.tsx`'s read-only "profile" tab block, add three rows:

```tsx
<div className="flex justify-between">
  <span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.service_type")}</span>
  <span>{soldierData.is_career ? t("soldier_profile.career") : t("soldier_profile.mandatory")}</span>
</div>
<div className="flex justify-between">
  <span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.has_driving_license")}</span>
  <span>{soldierData.has_military_driving_license ? t("common.yes") : t("common.no")}</span>
</div>
{soldierData.has_military_driving_license && soldierData.military_driving_license_expiry && (
  <div className="flex justify-between">
    <span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.driving_license_expiry")}</span>
    <span>{formatDate(soldierData.military_driving_license_expiry)}</span>
  </div>
)}
```

he.json keys: `soldier_profile.service_type` = `"סוג שירות"`, `soldier_profile.career` = `"קבע"`, `soldier_profile.mandatory` = `"חובה"`, `soldier_profile.has_driving_license` = `"רישיון נהיגה צבאי"`, `soldier_profile.driving_license_expiry` = `"תוקף רישיון נהיגה צבאי"` (`common.yes`/`common.no` — grep first, these likely already exist given the app's scale; add them if not).

- [ ] **Step 4:** Manual check — open a soldier's profile tab (view mode), confirm קבע/חובה shows correctly for a career vs. mandatory-service soldier, and the license fields show when set.

- [ ] **Step 5: Commit** — `git add frontend/src/components/UnifiedSoldierModal.tsx frontend/src/api/soldiers.ts backend/app/routes/soldiers.py frontend/src/i18n/he.json && git commit -m "feat: show service-type and driving-license fields in soldier profile"`

### Task 8.2: Editable driving-license fields in the profile-edit form

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx:366-435` (editable "profile" tab form)

- [ ] **Step 1:** Add state:

```tsx
const [profileHasLicense, setProfileHasLicense] = useState(soldier.has_military_driving_license ?? false);
const [profileLicenseExpiry, setProfileLicenseExpiry] = useState(soldier.military_driving_license_expiry ?? "");
```

(and reset them in the existing `useEffect(() => { setFullName(...); ... }, [soldierData])` block alongside the other profile-field resets — check whether that effect currently covers `profile*` fields at all; if the profile fields are only initialized once from `soldier` at mount, as the current code (`useState(soldier.rank ?? "")` etc.) suggests, follow that same one-time-init pattern for consistency rather than introducing a new reset effect.)

- [ ] **Step 2:** Add form fields inside the editable "profile" tab's `<div className="grid ...">`, after the mitvahim/alal date fields:

```tsx
<label className="flex items-center gap-2 mt-1">
  <input type="checkbox" checked={profileHasLicense} onChange={(e) => setProfileHasLicense(e.target.checked)} />
  <span className="text-xs">{t("soldier_profile.has_driving_license")}</span>
</label>
{profileHasLicense && (
  <label className="block">
    <span className="text-xs">{t("soldier_profile.driving_license_expiry")}</span>
    <input type="date" lang="he" className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
      value={profileLicenseExpiry} onChange={(e) => setProfileLicenseExpiry(e.target.value)} />
  </label>
)}
```

- [ ] **Step 3:** In `handleProfileSave`, add to the `updateSoldierProfile(...)` payload:

```tsx
has_military_driving_license: profileHasLicense,
military_driving_license_expiry: profileHasLicense ? (profileLicenseExpiry || null) : null,
```

- [ ] **Step 4:** Manual check — as a commander/duty-manager, edit a soldier's profile, toggle the driving-license checkbox on, set an expiry date, save, reopen the modal, confirm the read-only view (Task 8.1) shows the saved values.

- [ ] **Step 5: Commit** — `git add frontend/src/components/UnifiedSoldierModal.tsx && git commit -m "feat: make driving-license fields editable in soldier profile modal"`

### Task 8.3: Confirm/wire the self-service duty-manager-approval path for license changes

**Files:**
- Read-only investigation first: grep `military_driving_license` (the self-service field-update key, distinct from `has_military_driving_license`) across `frontend/src/**` to find whether any UI currently calls `submitFieldUpdate(soldierId, "military_driving_license", ...)`. If none does, this field-update path is currently dead/unreachable from the UI despite existing end-to-end on the backend (`SOLDIER_EDITABLE_FIELDS`, `Action.MILITARY_LICENSE_DECIDE`).
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx` (add the self-service entry point if missing)

- [ ] **Step 1:** Run `Grep -r "military_driving_license" frontend/src` and inspect results. If a self-service submit UI already exists elsewhere (e.g. a generic field-update form), confirm it surfaces the "ממתין לאישור אחראי תורנויות" state (check `FieldUpdateDTO.status` rendering) and stop here — nothing to build.

- [ ] **Step 2:** If no self-service UI exists for this field, add a small inline control to the read-only "profile" tab, visible to `isSelf && !canManage` (a plain soldier viewing/editing their own profile without direct-edit rights): a checkbox that, on change, calls `submitFieldUpdate(soldierData.id, "military_driving_license", String(newValue))` and shows a pending-approval note (`t("soldier_profile.pending_duty_manager_approval")` = `"השינוי ממתין לאישור אחראי תורנויות"`) once a `FieldUpdateDTO` with `status === "pending"` exists for that field (reuse whatever existing hook loads a soldier's pending field-updates elsewhere in this modal or a sibling component — grep `listFieldUpdates` usages first rather than duplicating the fetch logic).

- [ ] **Step 3:** Manual check — as a plain soldier (not self, not commander/duty-manager — i.e. `isSelf` true, `canManage` false), attempt to change your own driving-license status, confirm it goes to pending rather than applying immediately, and confirm a duty manager sees it in whatever pending-field-updates queue already exists (`listPendingFieldUpdates`) and can approve it.

- [ ] **Step 4: Commit** — `git add frontend/src/components/UnifiedSoldierModal.tsx frontend/src/i18n/he.json && git commit -m "feat: route self-service driving-license changes through duty-manager approval"` (skip this commit entirely if Step 1 found the path already wired — note that in the task tracker instead).

---

## Final steps (after all 8 items are done)

- [ ] Run the fast backend suite: `pytest -q` from `backend/` (with `.venv` active).
- [ ] Run frontend checks: `npm run lint` and `npm test` from `frontend/`.
- [ ] Run `npm run typecheck` from `frontend/`.
- [ ] Use the `merge-worktree-to-dev` project skill to merge this branch into `dev` (never directly into `master`).
