# Transparency & Duty-History Visibility Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current `transparency.visible_commander_levels` multiselect with a single rank-threshold setting plus two "levels above scope" settings, unify all transparency/duty-history permission checks behind one shared function, and close the resulting visibility bugs (plain soldiers seeing other soldiers' duty history unchecked, the transparency page's `fairness-components`/`effort-breakdown` cards bypassing the setting, and the frontend race where the page renders before reacting to a 403).

**Architecture:** A new permission core (`can_view_soldier_scope` + `has_any_visibility`) lives in `backend/app/services/authority.py` alongside the existing level-rank helpers it reuses (`get_level_rank`, the `dm_scope_covers_level` pattern). Every route that currently guards transparency/duty-history data — `/scoring/transparency`, `/scoring/fairness-components`, `/scoring/soldiers/{id}/effort-breakdown`, `/soldiers/{id}/duty-history` — calls into this one function instead of the three inconsistent checks that exist today. The frontend adds `can_view_transparency` to `/me` so `TransparencyPage` can gate before rendering instead of reacting to a 403 after the fact.

**Tech Stack:** FastAPI + SQLAlchemy (backend/app), Alembic migrations, pytest; React + TanStack Query + i18next (frontend/src).

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-09-transparency-visibility-rework-design.md`](../specs/2026-08-09-transparency-visibility-rework-design.md) — follow it exactly; this plan implements it task by task.
- New system settings: `transparency.min_visible_level` (level key or sentinel `"every_soldier"`, default `"every_soldier"`), `transparency.commander_levels_above` (int ≥ 0, default `0`), `transparency.duty_manager_levels_above` (int ≥ 0, default `0`).
- `HierarchyNode.path_ids` is root-first, self-last (confirmed in `backend/app/services/hierarchy.py:81-85`) — any ancestor-walking code must index from the end of the list, not the start.
- Rank comparison convention used throughout this codebase: **lower `HierarchyLevelType.rank` = closer to the root = more senior**. "At or above a level" means `rank <= threshold_rank`. This matches `dm_scope_covers_level` in `backend/app/services/authority.py:24-30`.
- Existing tests must stay green throughout — do not run the full slow suite per task; run only the targeted tests for each task (`pytest -q -k <name>` or the specific file), full suite only at the end.
- Follow `CLAUDE.md`'s branch workflow: this work happens on a feature branch off `dev`.

---

### Task 1: Alembic migration — new settings + migrate old value

**Files:**
- Create: `backend/alembic/versions/<generated>_transparency_settings_rework.py`

**Interfaces:**
- Produces: three new `system_settings` rows may or may not exist after migration (see logic below) — later tasks read them via `get_setting`/`get_setting_int` with in-code defaults, so absence is valid and expected for fresh installs.

- [ ] **Step 1: Generate the revision file**

Run (from `backend/`, with venv active):
```bash
alembic revision -m "transparency settings rework"
```
Note the generated revision id and file path for the next step.

- [ ] **Step 2: Write the migration**

Edit the generated file to:
```python
"""transparency settings rework

Revision ID: <generated>
Revises: 5abac7d1ec0b
Create Date: <generated>
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "<generated>"
down_revision: Union[str, Sequence[str], None] = "5abac7d1ec0b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    old = conn.execute(
        sa.text("SELECT value FROM system_settings WHERE key = 'transparency.visible_commander_levels'")
    ).scalar()

    if old:
        # old value is a JSON array of level keys; migrate to the single most
        # senior (lowest-rank) level among them.
        ranks = conn.execute(
            sa.text(
                "SELECT key, rank FROM hierarchy_level_types WHERE key = ANY(:keys)"
            ),
            {"keys": list(old)},
        ).all()
        min_level = min(ranks, key=lambda r: r.rank).key if ranks else "every_soldier"
    else:
        min_level = "every_soldier"

    conn.execute(
        sa.text(
            "INSERT INTO system_settings (key, value) VALUES ('transparency.min_visible_level', :v)"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"v": f'"{min_level}"'},
    )
    conn.execute(sa.text("DELETE FROM system_settings WHERE key = 'transparency.visible_commander_levels'"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM system_settings WHERE key = 'transparency.min_visible_level'"))
    conn.execute(sa.text("DELETE FROM system_settings WHERE key = 'transparency.commander_levels_above'"))
    conn.execute(sa.text("DELETE FROM system_settings WHERE key = 'transparency.duty_manager_levels_above'"))
```

Note: `value` is a `JSONB` column, so a plain string must be inserted as a JSON-quoted string (`'"every_soldier"'`), matching the `::jsonb`-cast convention used elsewhere in this repo's migrations. `commander_levels_above`/`duty_manager_levels_above` are intentionally left unseeded — `get_setting_int(session, key, default=0)` (used in Task 2) already returns `0` when the row is absent, so no explicit insert is needed for them.

- [ ] **Step 3: Run the migration**

```bash
alembic upgrade head
```
Expected: no errors; `SELECT value FROM system_settings WHERE key = 'transparency.min_visible_level';` returns `"every_soldier"` on a fresh dev DB (no prior `visible_commander_levels` row).

- [ ] **Step 4: Write an automated migration test**

This repo tests data migrations against a throwaway Postgres container rather than the shared session-scoped test DB (which is already migrated to head) — follow the exact pattern in `backend/tests/unit/test_migration_6b45caf468c2_keva.py` (`_db_at_down_revision` context manager). Create `backend/tests/unit/test_migration_<generated>_transparency_settings.py`:

```python
"""Tests for migration <generated> (transparency settings rework)."""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from testcontainers.postgres import PostgresContainer

DOWN_REVISION = "5abac7d1ec0b"
REVISION = "<generated>"


@contextmanager
def _db_at_down_revision():
    from app.settings import get_settings

    saved_database_url = os.environ.get("DATABASE_URL")
    saved_db_admin_url = os.environ.get("DB_ADMIN_URL")

    with PostgresContainer(
        "postgres:16-alpine", username="db_admin", password="db_admin_pw", dbname="justice"
    ).with_command(
        "postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off"
    ) as pg:
        url = make_url(pg.get_connection_url()).set(drivername="postgresql+psycopg")
        db_url = url.render_as_string(hide_password=False)
        try:
            os.environ["DATABASE_URL"] = db_url
            os.environ["DB_ADMIN_URL"] = db_url
            get_settings.cache_clear()

            from alembic import command
            from alembic.config import Config

            cfg = Config("alembic.ini")
            cfg.set_main_option("script_location", "alembic")
            command.upgrade(cfg, DOWN_REVISION)

            engine = create_engine(db_url, future=True)
            try:
                yield engine, (lambda: command.upgrade(cfg, REVISION))
            finally:
                engine.dispose()
        finally:
            if saved_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = saved_database_url
            if saved_db_admin_url is None:
                os.environ.pop("DB_ADMIN_URL", None)
            else:
                os.environ["DB_ADMIN_URL"] = saved_db_admin_url
            get_settings.cache_clear()


def test_nonempty_old_array_migrates_to_most_senior_level():
    with _db_at_down_revision() as (engine, run_migration):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO hierarchy_level_types (id, key, label, rank) VALUES "
                "(gen_random_uuid(), 'אגף', 'אגף', 1), (gen_random_uuid(), 'ענף', 'ענף', 2)"
            ))
            conn.execute(text(
                "INSERT INTO system_settings (key, value) VALUES "
                "('transparency.visible_commander_levels', '[\"ענף\", \"אגף\"]'::jsonb)"
            ))
        run_migration()
        with engine.begin() as conn:
            row = conn.execute(text(
                "SELECT value FROM system_settings WHERE key = 'transparency.min_visible_level'"
            )).scalar()
            old_row = conn.execute(text(
                "SELECT value FROM system_settings WHERE key = 'transparency.visible_commander_levels'"
            )).scalar()
        assert row == "אגף"  # rank 1 is more senior than rank 2
        assert old_row is None


def test_empty_or_missing_old_value_migrates_to_every_soldier():
    with _db_at_down_revision() as (engine, run_migration):
        run_migration()
        with engine.begin() as conn:
            row = conn.execute(text(
                "SELECT value FROM system_settings WHERE key = 'transparency.min_visible_level'"
            )).scalar()
        assert row == "every_soldier"
```

- [ ] **Step 5: Run the migration test**

```bash
pytest backend/tests/unit/test_migration_<generated>_transparency_settings.py -q
```
Expected: both PASS. This spins up a real Postgres container and will take longer than a typical unit test (consistent with the existing `test_migration_6b45caf468c2_keva.py`) — that's expected, not a hang.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/<generated>_transparency_settings_rework.py backend/tests/unit/test_migration_<generated>_transparency_settings.py
git commit -m "feat: migrate transparency setting to single rank threshold"
```

---

### Task 2: Core permission function — `can_view_soldier_scope` / `has_any_visibility`

**Files:**
- Modify: `backend/app/services/authority.py`
- Test: `backend/app/services/tests/test_authority.py`

**Interfaces:**
- Consumes: `get_level_rank(session, level_key) -> int | None` (already in `app.services.hierarchy`, imported at top of `authority.py`); `get_setting`/`get_setting_int`/`SettingNotFound` from `app.services.settings_loader`; `HierarchyNode`, `DutyManagerScope`, `Soldier` from `app.db.models`.
- Produces:
  - `can_view_soldier_scope(session: Session, viewer: Soldier, target_node: HierarchyNode | None) -> bool`
  - `has_any_visibility(session: Session, viewer: Soldier) -> bool`
  - Both consumed by Tasks 3-6.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_authority.py` (after the existing imports, extend the import line and add these tests at the end of the file):

```python
from app.services.authority import can_view_soldier_scope, has_any_visibility


def _node(session, level, name="N", commander_id=None):
    n = HierarchyNode(level=level, name=name, path_ids=[], commander_id=commander_id)
    session.add(n)
    session.flush()
    n.path_ids = [n.id]
    session.flush()
    return n


def _child(session, parent, level, name="Child"):
    n = HierarchyNode(level=level, name=name, parent_id=parent.id, path_ids=[])
    session.add(n)
    session.flush()
    n.path_ids = [*parent.path_ids, n.id]
    session.flush()
    return n


def _soldier(session, personal_number, role="soldier"):
    s = Soldier(personal_number=personal_number, full_name="X", password_hash="x", role=role)
    session.add(s)
    session.flush()
    return s


def test_admin_sees_everything(app_session):
    _level(app_session, "אגף", 1)
    node = _node(app_session, "אגף")
    admin = _soldier(app_session, "100", role="admin")
    assert can_view_soldier_scope(app_session, admin, node) is True


def test_plain_soldier_blocked_by_default(app_session):
    _level(app_session, "אגף", 1)
    node = _node(app_session, "אגף")
    plain = _soldier(app_session, "101")
    assert can_view_soldier_scope(app_session, plain, node) is False


def test_plain_soldier_allowed_when_every_soldier(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "אגף", 1)
    node = _node(app_session, "אגף")
    plain = _soldier(app_session, "102")
    set_setting(app_session, "transparency.min_visible_level", "every_soldier", actor_id=None)
    app_session.flush()
    assert can_view_soldier_scope(app_session, plain, node) is True


def test_commander_sees_own_subtree_always(app_session):
    _level(app_session, "מרכז", 1)
    _level(app_session, "ענף", 2)
    cmd = _soldier(app_session, "103", role="commander")
    root = _node(app_session, "מרכז", commander_id=cmd.id)
    child = _child(app_session, root, "ענף")
    assert can_view_soldier_scope(app_session, cmd, child) is True


def test_commander_cannot_see_outside_subtree_with_zero_expansion(app_session):
    _level(app_session, "מרכז", 1)
    cmd = _soldier(app_session, "104", role="commander")
    _node(app_session, "מרכז", commander_id=cmd.id)
    other = _node(app_session, "מרכז", name="Other")
    assert can_view_soldier_scope(app_session, cmd, other) is False


def test_commander_sees_ancestor_with_levels_above(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "אגף", 1)
    _level(app_session, "מרכז", 2)
    _level(app_session, "ענף", 3)
    top = _node(app_session, "אגף", name="Top")
    center = _child(app_session, top, "מרכז", name="Center")
    cmd = _soldier(app_session, "105", role="commander")
    branch = _child(app_session, center, "ענף", name="Branch")
    branch.commander_id = cmd.id
    app_session.flush()
    sibling_branch = _child(app_session, center, "ענף", name="SiblingBranch")

    # Without expansion, the commander's peer branch isn't visible.
    assert can_view_soldier_scope(app_session, cmd, sibling_branch) is False

    set_setting(app_session, "transparency.commander_levels_above", 1, actor_id=None)
    app_session.flush()
    # One level up from "ענף" is "מרכז" — the sibling branch is under that same
    # center, so it's now visible.
    assert can_view_soldier_scope(app_session, cmd, sibling_branch) is True


def test_duty_manager_sees_ancestor_with_levels_above(app_session):
    from app.services.settings_loader import set_setting
    from app.db.models import DutyManagerScope

    _level(app_session, "אגף", 1)
    _level(app_session, "מרכז", 2)
    _level(app_session, "ענף", 3)
    top = _node(app_session, "אגף", name="Top")
    center = _child(app_session, top, "מרכז", name="Center")
    dm = _soldier(app_session, "106", role="duty_manager")
    branch = _child(app_session, center, "ענף", name="Branch")
    sibling_branch = _child(app_session, center, "ענף", name="SiblingBranch")
    app_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=branch.id))
    app_session.flush()

    assert can_view_soldier_scope(app_session, dm, sibling_branch) is False

    set_setting(app_session, "transparency.duty_manager_levels_above", 1, actor_id=None)
    app_session.flush()
    assert can_view_soldier_scope(app_session, dm, sibling_branch) is True


def test_senior_enough_commander_sees_unrelated_soldier(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "אגף", 1)
    _level(app_session, "ענף", 2)
    cmd = _soldier(app_session, "107", role="commander")
    _node(app_session, "אגף", commander_id=cmd.id)
    unrelated = _node(app_session, "ענף", name="Unrelated")
    set_setting(app_session, "transparency.min_visible_level", "אגף", actor_id=None)
    app_session.flush()
    assert can_view_soldier_scope(app_session, cmd, unrelated) is True


def test_junior_commander_below_threshold_blocked(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "אגף", 1)
    _level(app_session, "ענף", 2)
    cmd = _soldier(app_session, "108", role="commander")
    _node(app_session, "ענף", commander_id=cmd.id)
    unrelated = _node(app_session, "אגף", name="Unrelated")
    set_setting(app_session, "transparency.min_visible_level", "אגף", actor_id=None)
    app_session.flush()
    assert can_view_soldier_scope(app_session, cmd, unrelated) is False


def test_has_any_visibility_true_for_any_commanded_node(app_session):
    _level(app_session, "אגף", 1)
    cmd = _soldier(app_session, "109", role="commander")
    _node(app_session, "אגף", commander_id=cmd.id)
    assert has_any_visibility(app_session, cmd) is True


def test_has_any_visibility_false_for_plain_soldier_by_default(app_session):
    plain = _soldier(app_session, "110")
    assert has_any_visibility(app_session, plain) is False


def test_has_any_visibility_true_when_every_soldier(app_session):
    from app.services.settings_loader import set_setting

    plain = _soldier(app_session, "111")
    set_setting(app_session, "transparency.min_visible_level", "every_soldier", actor_id=None)
    app_session.flush()
    assert has_any_visibility(app_session, plain) is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest backend/app/services/tests/test_authority.py -q
```
Expected: `ImportError: cannot import name 'can_view_soldier_scope'`.

- [ ] **Step 3: Implement in `backend/app/services/authority.py`**

Add near the top, extend the existing import line for `settings_loader` and `models`:
```python
from app.db.models import DutyManagerScope, HierarchyNode, Soldier
from app.services.hierarchy import get_level_rank
from app.services.settings_loader import SettingNotFound, get_setting, get_setting_int
```
(`get_setting_int` is new to this file's imports; `DutyManagerScope` is new too — both already exist in `settings_loader`/`models`.)

Append at the end of the file:
```python
def _min_visible_level(session: Session) -> str:
    try:
        value = get_setting(session, "transparency.min_visible_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return "every_soldier"


def _commanded_nodes(session: Session, soldier_id: uuid.UUID) -> list[HierarchyNode]:
    return list(
        session.execute(
            select(HierarchyNode).where(HierarchyNode.commander_id == soldier_id)
        ).scalars().all()
    )


def _dm_scope_nodes(session: Session, soldier_id: uuid.UUID) -> list[HierarchyNode]:
    root_ids = session.execute(
        select(DutyManagerScope.hierarchy_node_id).where(DutyManagerScope.duty_manager_id == soldier_id)
    ).scalars().all()
    if not root_ids:
        return []
    return list(
        session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(root_ids))).scalars().all()
    )


def _ancestor_n_up(session: Session, node: HierarchyNode, n: int) -> HierarchyNode:
    """Walk `n` steps toward the root along node.path_ids (root-first, self-last).
    Caps at the root if `n` exceeds the number of ancestors."""
    if n <= 0:
        return node
    target_idx = max(0, len(node.path_ids) - 1 - n)
    ancestor_id = node.path_ids[target_idx]
    if ancestor_id == node.id:
        return node
    ancestor = session.get(HierarchyNode, ancestor_id)
    return ancestor if ancestor is not None else node


def _best_commanded_rank(session: Session, soldier_id: uuid.UUID) -> int | None:
    """Most senior (lowest) rank among every node the soldier commands or
    duty-manages, or None if they hold neither role."""
    nodes = [*_commanded_nodes(session, soldier_id), *_dm_scope_nodes(session, soldier_id)]
    ranks = [get_level_rank(session, node.level) for node in nodes]
    ranks = [r for r in ranks if r is not None]
    return min(ranks) if ranks else None


def can_view_soldier_scope(
    session: Session, viewer: Soldier, target_node: HierarchyNode | None,
) -> bool:
    """True iff `viewer` may see transparency/duty-history data belonging to a
    soldier assigned to `target_node`. Single source of truth for the
    transparency page, its fairness-components/effort-breakdown cards, and the
    other-soldier branch of GET /soldiers/{id}/duty-history."""
    if viewer.role == "admin":
        return True

    commander_expand = get_setting_int(session, "transparency.commander_levels_above", 0)
    for node in _commanded_nodes(session, viewer.id):
        ancestor = _ancestor_n_up(session, node, commander_expand)
        if target_node is not None and ancestor.id in target_node.path_ids:
            return True

    dm_expand = get_setting_int(session, "transparency.duty_manager_levels_above", 0)
    for node in _dm_scope_nodes(session, viewer.id):
        ancestor = _ancestor_n_up(session, node, dm_expand)
        if target_node is not None and ancestor.id in target_node.path_ids:
            return True

    threshold = _min_visible_level(session)
    if threshold == "every_soldier":
        return True

    threshold_rank = get_level_rank(session, threshold)
    if threshold_rank is None:
        return False
    best_rank = _best_commanded_rank(session, viewer.id)
    return best_rank is not None and best_rank <= threshold_rank


def has_any_visibility(session: Session, viewer: Soldier) -> bool:
    """Cheap endpoint-level gate: True iff `viewer` can see *something* under
    the transparency rule — used to 403 early instead of computing full row
    sets for someone who'd end up seeing nothing."""
    if viewer.role == "admin":
        return True
    if _commanded_nodes(session, viewer.id) or _dm_scope_nodes(session, viewer.id):
        return True
    return _min_visible_level(session) == "every_soldier"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest backend/app/services/tests/test_authority.py -q
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/authority.py backend/app/services/tests/test_authority.py
git commit -m "feat: add shared can_view_soldier_scope/has_any_visibility permission core"
```

---

### Task 3: Wire `/scoring/transparency` — endpoint gate + per-row filtering

**Files:**
- Modify: `backend/app/services/scoring.py` (`transparency_rows`, around line 503-615)
- Modify: `backend/app/routes/scoring.py` (`_transparency_allowed`/`transparency`, lines 106-134)
- Test: `backend/tests/integration/test_scoring_api.py`, `backend/tests/unit/test_scoring_service.py`

**Interfaces:**
- Consumes: `can_view_soldier_scope`, `has_any_visibility` from Task 2 (`app.services.authority`).
- Produces: `transparency_rows(session, *, viewer=None)` now excludes rows the viewer isn't allowed to see (previously returned every active soldier regardless of scope). `GET /scoring/transparency` 403s when `has_any_visibility` is False, instead of the old level-multiselect check.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_scoring_service.py` (find existing fixtures for soldiers/hierarchy in that file and follow the same setup style — likely a `session` fixture plus factory helpers already used by nearby tests for `transparency_rows`):
```python
def test_transparency_rows_excludes_out_of_scope_soldiers_for_junior_commander(session):
    # Arrange: two sibling nodes under different parents, a commander of one,
    # a soldier under the other, min_visible_level left at default "every_soldier"
    # is NOT set here — set it to a level the commander doesn't meet.
    from app.services.settings_loader import set_setting
    from app.db.models import HierarchyLevelType, HierarchyNode, Soldier

    session.add(HierarchyLevelType(key="אגף", label="אגף", rank=1))
    session.add(HierarchyLevelType(key="ענף", label="ענף", rank=2))
    session.flush()
    own = HierarchyNode(level="ענף", name="Own", path_ids=[])
    other = HierarchyNode(level="ענף", name="Other", path_ids=[])
    session.add_all([own, other])
    session.flush()
    own.path_ids = [own.id]
    other.path_ids = [other.id]
    cmd = Soldier(personal_number="900", full_name="Cmd", password_hash="x", role="commander", left_at=None)
    outsider = Soldier(personal_number="901", full_name="Outsider", password_hash="x", hierarchy_node_id=other.id, left_at=None)
    session.add_all([cmd, outsider])
    session.flush()
    own.commander_id = cmd.id
    set_setting(session, "transparency.min_visible_level", "אגף", actor_id=None)
    session.flush()

    from app.services.scoring import transparency_rows
    result = transparency_rows(session, viewer=cmd)
    ids = {r["soldier_id"] for r in result["rows"]}
    assert outsider.id not in ids
```

Add to `backend/tests/integration/test_scoring_api.py` (follow the existing auth/client fixture patterns already used by other tests in that file for `/scoring/transparency`):
```python
def test_transparency_403_for_plain_soldier_by_default(client, plain_soldier_auth_headers):
    resp = client.get("/scoring/transparency", headers=plain_soldier_auth_headers)
    assert resp.status_code == 403


def test_transparency_200_when_every_soldier(client, plain_soldier_auth_headers, db_session):
    from app.services.settings_loader import set_setting
    set_setting(db_session, "transparency.min_visible_level", "every_soldier", actor_id=None)
    db_session.commit()
    resp = client.get("/scoring/transparency", headers=plain_soldier_auth_headers)
    assert resp.status_code == 200
```
(Adjust fixture names — `client`, `plain_soldier_auth_headers`, `db_session` — to whatever this file's existing tests actually use; check the top of `test_scoring_api.py` for the real fixture names before writing this step.)

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest backend/tests/unit/test_scoring_service.py -k transparency_rows_excludes -q
pytest backend/tests/integration/test_scoring_api.py -k transparency_403 -q
```
Expected: FAIL (old behavior returns all rows / old behavior allows plain soldiers by default when unset).

- [ ] **Step 3: Implement — `transparency_rows` row filtering**

In `backend/app/services/scoring.py`, add the import at the top (alongside the existing `from app.auth.authz import scope_root_ids` at line 27):
```python
from app.services.authority import can_view_soldier_scope
```

In `transparency_rows` (around line 550, the `for s in soldiers:` loop), skip soldiers the viewer can't see:
```python
    for s in soldiers:
        node = nodes.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        if viewer is not None and viewer.role != "admin" and not can_view_soldier_scope(session, viewer, node):
            continue
        cum = duty_scores.get(s.id, Decimal("0")) + adj_scores.get(s.id, Decimal("0"))
        ad = active_days_map.get(s.id, 1)
        soldier_exemptions = exemptions_by_soldier.get(s.id, [])
        ...
```
(Move the existing `node = nodes.get(...)` line that's currently a few lines further down up to this point — don't duplicate it; the existing line reading `node = nodes.get(s.hierarchy_node_id) if s.hierarchy_node_id else None` at the current line ~553 is what you're relocating to the top of the loop body, before the new `if` check.)

- [ ] **Step 4: Implement — route-level gate**

In `backend/app/routes/scoring.py`:
- Remove `_transparency_allowed` (lines 106-120) and its now-unused `get_setting`/`SettingNotFound` import if nothing else in the file uses them (check with `grep -n "get_setting\|SettingNotFound" backend/app/routes/scoring.py` — `effort_breakdown` at line 154 also imports these locally inside the function, so the module-level import at line 17 may become unused; remove it if so, or leave the local import in `effort_breakdown` untouched since it's a separate inline import).
- Add import: `from app.services.authority import has_any_visibility`.
- Replace the `transparency` handler's gate:
```python
@router.get("/transparency", response_model=TransparencyOut)
def transparency(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransparencyOut:
    if not has_any_visibility(session, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="transparency_hidden")
    result = svc.transparency_rows(session, viewer=user)
    return TransparencyOut(
        rows=[TransparencyRow(**row) for row in result["rows"]],
        can_see_exemption_aggregates=result["can_see_exemption_aggregates"],
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest backend/tests/unit/test_scoring_service.py -k transparency -q
pytest backend/tests/integration/test_scoring_api.py -k transparency -q
```
Expected: all PASS. Also run the pre-existing transparency tests in both files to confirm no regression:
```bash
pytest backend/tests/unit/test_scoring_service.py backend/tests/integration/test_scoring_api.py -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/scoring.py backend/app/routes/scoring.py backend/tests/unit/test_scoring_service.py backend/tests/integration/test_scoring_api.py
git commit -m "feat: filter transparency rows and gate endpoint via can_view_soldier_scope"
```

---

### Task 4: Wire `/scoring/fairness-components`

**Files:**
- Modify: `backend/app/services/scoring.py` (`fairness_components`, lines 744-764)
- Modify: `backend/app/routes/scoring.py` (`fairness_components` route handler, lines 137-144)
- Test: `backend/tests/integration/test_scoring_api.py`

**Interfaces:**
- Consumes: `transparency_rows` from Task 3 (now scope-filtered when a `viewer` is passed).
- Produces: `fairness_components(session, *, viewer=None)` (new `viewer` kwarg) — `soldiers`/`exempt_from_all` lists only include soldiers the viewer can see.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_scoring_api.py`:
```python
def test_fairness_components_403_for_plain_soldier_by_default(client, plain_soldier_auth_headers):
    resp = client.get("/scoring/fairness-components", headers=plain_soldier_auth_headers)
    assert resp.status_code == 403
```
(Match real fixture names as in Task 3.)

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest backend/tests/integration/test_scoring_api.py -k fairness_components_403 -q
```
Expected: FAIL (currently 200 for everyone).

- [ ] **Step 3: Implement**

In `backend/app/services/scoring.py`, change `fairness_components` signature (line 744):
```python
def fairness_components(session: Session, *, viewer: Soldier | None = None) -> dict[str, Any]:
    """Effort spread (פיזור) split by connected components of soldiers who share
    duty-type eligibility, plus the soldiers exempt from every active duty type.
    Soldier lists are scoped to what `viewer` may see (see can_view_soldier_scope)."""
    from app.services.algorithm_bridge import load_soldier_inputs

    rows = transparency_rows(session, viewer=viewer)["rows"]
    visible_ids = {r["soldier_id"] for r in rows}
    effort_by_id = {r["soldier_id"]: float(r["effort_score"]) for r in rows}
    name_by_id = {r["soldier_id"]: r["full_name"] for r in rows}

    active_type_ids = _active_duty_type_ids(session)
    type_names = {
        dt.id: dt.name
        for dt in session.execute(
            select(DutyType).where(DutyType.id.in_(active_type_ids))
        ).scalars().all()
    }
    inputs = load_soldier_inputs(session, as_of=date.today())
    eligible_types = {
        si.id: (active_type_ids - set(si.exempted_duty_type_ids))
        for si in inputs
        if si.id in visible_ids
    }
    return _build_fairness_components(eligible_types, type_names, effort_by_id, name_by_id, soldier_eligible_types=eligible_types)
```

In `backend/app/routes/scoring.py`, update the route (lines 137-144) to gate and pass the viewer:
```python
@router.get("/fairness-components")
def fairness_components(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    """Effort spread (פיזור) split per connected component of soldiers who share
    duty-type eligibility, plus the count of soldiers exempt from every duty."""
    if not has_any_visibility(session, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="transparency_hidden")
    return svc.fairness_components(session, viewer=user)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest backend/tests/integration/test_scoring_api.py -k fairness_components -q
```
Expected: PASS, plus any pre-existing `fairness_components` tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoring.py backend/app/routes/scoring.py backend/tests/integration/test_scoring_api.py
git commit -m "feat: gate and scope fairness-components by can_view_soldier_scope"
```

---

### Task 5: Wire `/scoring/soldiers/{id}/effort-breakdown`

**Files:**
- Modify: `backend/app/routes/scoring.py` (`effort_breakdown`, lines 147-160)
- Test: `backend/tests/integration/test_scoring_api.py`

**Interfaces:**
- Consumes: `can_view_soldier_scope` from Task 2.

- [ ] **Step 1: Write the failing test**

```python
def test_effort_breakdown_403_for_unrelated_plain_soldier(client, plain_soldier_auth_headers, other_soldier_id):
    resp = client.get(f"/scoring/soldiers/{other_soldier_id}/effort-breakdown", headers=plain_soldier_auth_headers)
    assert resp.status_code == 403
```
(Use whatever fixture in this file already provides a second soldier's id — check nearby tests, e.g. those covering `SOLDIER_READ`/duty-history, for the existing fixture name instead of inventing `other_soldier_id`.)

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest backend/tests/integration/test_scoring_api.py -k effort_breakdown_403 -q
```
Expected: FAIL if `authorize(SOLDIER_READ)` currently grants it, or ERROR/different status if it currently 403s for a different reason — confirm current behavior first with `git stash` if needed, then restore.

- [ ] **Step 3: Implement**

In `backend/app/routes/scoring.py`, replace lines 159-160:
```python
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
```
with:
```python
    if s.id != user.id:
        if not can_view_soldier_scope(session, user, _node_of(session, s)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```
Add `can_view_soldier_scope` to the `app.services.authority` import added in Task 3/4.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest backend/tests/integration/test_scoring_api.py -k effort_breakdown -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/scoring.py backend/tests/integration/test_scoring_api.py
git commit -m "feat: gate effort-breakdown via can_view_soldier_scope"
```

---

### Task 6: Wire `GET /soldiers/{id}/duty-history`

**Files:**
- Modify: `backend/app/routes/soldiers.py` (`get_soldier_duty_history`, lines 522-545)
- Test: `backend/tests/integration/test_soldiers_api.py`

**Interfaces:**
- Consumes: `can_view_soldier_scope` from Task 2.
- Produces: 403 for a plain soldier viewing another soldier's history when not permitted (previously silently returned a filtered list with no permission check at all — this is the main bug from the design spec).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_soldiers_api.py`:
```python
def test_duty_history_403_for_unrelated_plain_soldier_by_default(client, plain_soldier_auth_headers, other_soldier_id):
    resp = client.get(f"/soldiers/{other_soldier_id}/duty-history", headers=plain_soldier_auth_headers)
    assert resp.status_code == 403


def test_duty_history_200_for_own_commander(client, commander_auth_headers, subordinate_soldier_id):
    resp = client.get(f"/soldiers/{subordinate_soldier_id}/duty-history", headers=commander_auth_headers)
    assert resp.status_code == 200
```
(Match real fixture names used elsewhere in this file for a commander/subordinate pair and an unrelated soldier — check existing tests around `SOLDIER_READ`/`authorize` in this file first.)

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest backend/tests/integration/test_soldiers_api.py -k duty_history -q
```
Expected: `test_duty_history_403_for_unrelated_plain_soldier_by_default` FAILs (currently 200).

- [ ] **Step 3: Implement**

In `backend/app/routes/soldiers.py`, add the import:
```python
from app.services.authority import can_view_soldier_scope
```
Replace lines 529-545:
```python
    s = _load(session, soldier_id)
    is_self = s.id == user.id
    is_plain_soldier = user.role == "soldier"

    if not is_self and not is_plain_soldier:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    elif not is_self and is_plain_soldier:
        if not can_view_soldier_scope(session, user, _node_of(session, s)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    if include_drafts and user.role != "admin" and not is_duty_manager(session, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    include_sensitive = can_see_private(session, user, s)
    events = get_duty_history(
        session, soldier_id, include_drafts=include_drafts, include_sensitive=include_sensitive
    )

    if is_plain_soldier and not is_self:
        events = [e for e in events if e.event_type in _PUBLIC_EVENT_TYPES]
```
(The event-type filter for plain-soldier non-self viewers stays exactly as-is — it's now a second, independent restriction layered on top of the new access check, per the design spec.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest backend/tests/integration/test_soldiers_api.py -k duty_history -q
```
Expected: PASS, including pre-existing duty-history tests (self-view, commander-view, admin-view).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/soldiers.py backend/tests/integration/test_soldiers_api.py
git commit -m "fix: gate other-soldier duty-history access via can_view_soldier_scope"
```

---

### Task 7: Add `can_view_transparency` to `/me`

**Files:**
- Modify: `backend/app/routes/me.py` (`MeResponse`, `me()`)
- Test: `backend/tests/integration/test_soldiers_api.py` or wherever existing `/me` tests live (check `backend/tests/integration/` for a `test_me_api.py`-style file first)

**Interfaces:**
- Consumes: `has_any_visibility` from Task 2.
- Produces: `MeResponse.can_view_transparency: bool`, consumed by frontend Task 9.

- [ ] **Step 1: Write the failing test**

Locate the existing `/me` integration test file (`grep -rl "\"/me\"" backend/tests/integration/` if unsure) and add:
```python
def test_me_includes_can_view_transparency(client, plain_soldier_auth_headers):
    resp = client.get("/me", headers=plain_soldier_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["can_view_transparency"] is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest backend/tests/integration/ -k can_view_transparency -q
```
Expected: FAIL — `KeyError`/missing field.

- [ ] **Step 3: Implement**

In `backend/app/routes/me.py`, add the import:
```python
from app.services.authority import has_any_visibility
```
Add the field to `MeResponse` (after `enrollment_pending`):
```python
    enrollment_pending: bool = False
    theme_preference: str = "system"
    can_view_transparency: bool = False
```
In the `me()` handler, add before the `return MeResponse(...)`:
```python
    can_view_transparency = has_any_visibility(session, user)
```
And add `can_view_transparency=can_view_transparency,` to the `MeResponse(...)` call.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest backend/tests/integration/ -k can_view_transparency -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/me.py backend/tests/integration/
git commit -m "feat: expose can_view_transparency on /me"
```

---

### Task 8: Frontend — `Me` interface + settings admin UI

**Files:**
- Modify: `frontend/src/api/auth.ts` (`Me` interface)
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Modify: `frontend/src/i18n/he.json`

**Interfaces:**
- Produces: `Me.can_view_transparency: boolean` (consumed by Task 9); three new setting entries in `SETTING_GROUPS` replacing the old multiselect.

- [ ] **Step 1: Add the field to `Me`**

In `frontend/src/api/auth.ts`, add to the `Me` interface (after `is_career?: boolean;`):
```ts
  can_view_transparency?: boolean;
```

- [ ] **Step 2: Replace the transparency setting group**

In `frontend/src/pages/SystemSettingsPage.tsx`, replace lines 315-325 (the `"שקיפות"` group) with:
```ts
  {
    label: "שקיפות",
    settings: [
      {
        key: "transparency.min_visible_level",
        label: t("admin_settings.transparency_min_visible_level"),
        description: t("admin_settings.transparency_min_visible_level_desc"),
        type: "select" as const,
        defaultValue: "every_soldier",
      },
      {
        key: "transparency.commander_levels_above",
        label: t("admin_settings.transparency_commander_levels_above"),
        description: t("admin_settings.transparency_levels_above_desc"),
        type: "number" as const,
        defaultValue: 0,
      },
      {
        key: "transparency.duty_manager_levels_above",
        label: t("admin_settings.transparency_duty_manager_levels_above"),
        description: t("admin_settings.transparency_levels_above_desc"),
        type: "number" as const,
        defaultValue: 0,
      },
    ],
  },
```
Note: `SETTING_GROUPS` is currently a module-level `const` built without access to `t()` (translations are looked up separately at render time via the `def.key === ...` special-casing at lines 514-518). Since this task introduces labels that need translation, either (a) keep `SETTING_GROUPS` as plain Hebrew strings directly (simplest, matches this group's sibling settings like `constraints.reset_period` which hardcodes `label` in Hebrew already) — **do this**, not the `t()` call above (that was illustrative; `SETTING_GROUPS` has no `t` in scope). Use:
```ts
  {
    label: "שקיפות",
    settings: [
      {
        key: "transparency.min_visible_level",
        label: "החל ממפקדים/אחראי תורנויות באיזה דרג ניתן לראות נתוני שקיפות במערכת",
        type: "select" as const,
        defaultValue: "every_soldier",
      },
      {
        key: "transparency.commander_levels_above",
        label: "כמה דרגים מעל תחום הפיקוד יכול מפקד לראות (לצורך השוואה)",
        type: "number" as const,
        defaultValue: 0,
      },
      {
        key: "transparency.duty_manager_levels_above",
        label: "כמה דרגים מעל תחום האחריות יכול אחראי תורנויות לראות (לצורך השוואה)",
        type: "number" as const,
        defaultValue: 0,
      },
    ],
  },
```

- [ ] **Step 3: Add the "every soldier" option list and wire the select**

In the component body (around line 367-379, next to `hierarchyLevelOptions`/`commanderExemptionLevelOptions`), add:
```ts
  const transparencyMinVisibleLevelOptions = [
    { value: "every_soldier", label: "כל חייל" },
    ...levelTypes.map(lt => ({ value: lt.key, label: lt.label })),
  ];
```
In the `select` rendering branch (around line 564-569), add a case for the new key:
```ts
                      {(def.key === "transparency.min_visible_level"
                        ? transparencyMinVisibleLevelOptions
                        : def.key === "swaps.restrict_to_hierarchy_level"
                        ? hierarchyLevelOptions
                        : MIN_LEVEL_SETTING_KEYS.has(def.key)
                        ? commanderExemptionLevelOptions
                        : def.options ?? []
                      ).map((opt) => (
```

- [ ] **Step 4: Remove now-dead special-casing**

Around line 514-518, the block that special-cases the label for `def.key === "transparency.visible_commander_levels"` (which pulled from `t("admin_settings.transparency_visible_levels")`) is now dead code since that key no longer exists in `SETTING_GROUPS`. Remove that `? :` branch, leaving:
```ts
                    {def.key === "constraints.reset_period"
                      ? t("admin_settings.constraints_reset_period")
                      : def.label}
```

- [ ] **Step 5: Verify in the browser**

Start the dev stack (`.\dev.ps1`), log in as admin, navigate to System Settings → שקיפות group. Confirm: a single select showing "כל חייל" plus every configured hierarchy level, and two number inputs default to `0`. Change the select, save, reload — value persists.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/auth.ts frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat: replace transparency multiselect with rank-threshold settings UI"
```

---

### Task 9: Frontend — gate `TransparencyPage` on `can_view_transparency` before rendering

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx`
- Modify: `frontend/src/auth/AuthContext.tsx` (only if `user` isn't already exposed there — verify first; per Task research, `useAuth()` already exposes `user: Me | null`, so likely no change needed here)

**Interfaces:**
- Consumes: `useAuth().user.can_view_transparency` (from Task 7/8).

- [ ] **Step 1: Read the current top of `TransparencyPage.tsx`**

Confirm `useAuth` is already imported (per research, it is — used for other role checks in this file). If not, add:
```ts
import { useAuth } from "../auth/AuthContext";
```

- [ ] **Step 2: Add the proactive gate**

Near the top of the component, alongside the existing `transparencyQuery`/`transparencyForbidden` logic (lines ~294-300), add:
```ts
  const { user } = useAuth();
  const canViewTransparency = user?.can_view_transparency ?? true; // true until /me loads, avoids a flash-then-hide for allowed users
```
Change the query to only run once we know the answer either way:
```ts
  const transparencyQuery = useQuery({
    queryKey: queryKeys.transparency(),
    queryFn: getTransparency,
    enabled: canViewTransparency,
  });
```
Do the same for `fairnessComponentsQuery` (line ~305-309):
```ts
  const fairnessComponentsQuery = useQuery({
    queryKey: queryKeys.fairnessComponents(),
    queryFn: getFairnessComponents,
    enabled: canViewTransparency,
  });
```
Update the forbidden check (line ~300) to treat a known-false `can_view_transparency` the same as a 403, so the "no permission" branch renders immediately without waiting on a query:
```ts
  const transparencyForbidden =
    user?.can_view_transparency === false ||
    (isAxiosError(transparencyQuery.error) && transparencyQuery.error.response?.status === 403);
```

- [ ] **Step 3: Verify in the browser**

Log in as a plain soldier with `transparency.min_visible_level` left at a restrictive setting (not `every_soldier`), navigate to the transparency page. Confirm: the "no permission" message (`transparency.no_permission`) shows immediately, with no flash of table/fairness content beforehand. Check the Network tab: `/scoring/transparency` and `/scoring/fairness-components` should not fire at all in this case (since `enabled: false`).

Then set `transparency.min_visible_level` to `every_soldier` as admin, reload as the plain soldier — confirm the page renders normally.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx
git commit -m "fix: gate TransparencyPage on can_view_transparency before querying"
```

---

### Task 10: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend fast suite**

```bash
cd backend && pytest -q
```
Expected: all green.

- [ ] **Step 2: Run frontend checks**

```bash
cd frontend && npm run lint && npm run typecheck && npm test
```
Expected: zero lint warnings, no type errors, all tests pass.

- [ ] **Step 3: Manual smoke test in the browser**

Using `.\dev.ps1`: as a plain soldier, confirm `GET /soldiers/{other_id}/duty-history` (via the "view soldier" modal on any roster page) shows "אין הרשאה להציג מידע זה" for an unrelated soldier by default, and works for a commander viewing their own subordinate. As admin, exercise the three new System Settings fields end-to-end (set a threshold, set both "levels above" numbers, verify a duty manager one level below their configured scope root can now see a comparison unit's transparency rows).

- [ ] **Step 4: Report status**

If anything fails, fix it within the relevant task above (don't add new ad hoc tasks) and re-run this task's steps.
