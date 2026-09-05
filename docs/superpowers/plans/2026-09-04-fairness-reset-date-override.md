# Per-Hierarchy Fairness Reset-Date Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin override `fairness.reset_date` per hierarchy node, and make fairness scoring use each soldier's real unit-join date instead of when an admin got around to adding them to the roster — so a new branch joining the rollout doesn't get penalized (or accidentally favored) by the system's fairness math for having no backfilled history.

**Architecture:** One new JSON setting (`fairness.reset_date_overrides`, `{node_id: iso_date}`) stored in the existing generic `SystemSetting` table. A new resolver (`resolve_reset_dates_for_soldiers`) walks each soldier's hierarchy path to the nearest ancestor override, falling back to the existing global default. The core per-soldier ratio computation in `effort_score.py` (`_compute_effort_data`) is fixed so both the numerator (days active) and denominator (quarter length) clip to the *same* per-soldier floor — today only the numerator is clipped, which undercounts anyone whose branch's reset date is later than whichever soldier's date the quarter list happened to be built from. The score-projection cache (a read-side optimization for the UI) is left untouched but taught to bail out to the always-correct live recompute whenever a hierarchy override is actually in play for the soldiers it's asked about.

**Tech Stack:** Python/FastAPI/SQLAlchemy backend, React/TypeScript frontend, pytest, vitest.

**Spec:** [docs/superpowers/specs/2026-09-04-fairness-reset-date-override-design.md](../specs/2026-09-04-fairness-reset-date-override-design.md)

## Global Constraints

- No new DB table/migration — `fairness.reset_date_overrides` reuses the existing `SystemSetting(key, value JSONB)` table exactly like `fairness.reset_date` does.
- `validate_settings_update` in `settings_loader.py` stays DB-session-free (its existing contract) — do not add a hierarchy-node-existence check against the DB for the new key; validate shape only (dict of string → ISO date string). This matches how other reference-style settings (e.g. hierarchy-level-keyed selects) are already validated in this codebase — by shape/format only, not FK existence.
- `compute_effort_data` and `compute_burden_share_breakdown` keep their existing `reset_date: date | None = None` parameter for backward compatibility with existing callers/tests: when explicitly passed, it forces that single date for every soldier (today's behavior, unchanged); when omitted, each soldier's date is resolved via hierarchy overrides.
- The score-projection cache (`score_projection.py`, `_try_projected_*` functions in `scoring.py`) is explicitly NOT extended to understand per-hierarchy overrides in this plan — see spec §6. It bails to the live/legacy path instead. Do not attempt to make the projection cache override-aware as part of this work.
- Every new backend function gets a test in the same task that introduces it — no task ends with untested new code.

---

### Task 1: `fairness.reset_date_overrides` setting validation

**Files:**
- Modify: `backend/app/services/settings_loader.py:91-125` (`validate_settings_update`)
- Test: `backend/tests/unit/test_settings_loader.py`

**Interfaces:**
- Produces: `validate_settings_update` now also rejects a malformed `fairness.reset_date_overrides` value with `SettingsValidationError("reset_date_overrides_invalid")`. No new public function.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_settings_loader.py (append)
import pytest as _pytest  # already imported as pytest above; keep single import if present

from app.services.settings_loader import SettingsValidationError, validate_settings_update


def test_reset_date_overrides_accepts_valid_dict():
    merged = validate_settings_update(
        {}, {"fairness.reset_date_overrides": {"11111111-1111-1111-1111-111111111111": "2026-08-01"}}
    )
    assert merged["fairness.reset_date_overrides"] == {
        "11111111-1111-1111-1111-111111111111": "2026-08-01"
    }


def test_reset_date_overrides_accepts_empty_dict():
    merged = validate_settings_update({}, {"fairness.reset_date_overrides": {}})
    assert merged["fairness.reset_date_overrides"] == {}


def test_reset_date_overrides_rejects_non_dict():
    with pytest.raises(SettingsValidationError) as exc:
        validate_settings_update({}, {"fairness.reset_date_overrides": ["2026-08-01"]})
    assert exc.value.code == "reset_date_overrides_invalid"


def test_reset_date_overrides_rejects_bad_date_value():
    with pytest.raises(SettingsValidationError) as exc:
        validate_settings_update(
            {}, {"fairness.reset_date_overrides": {"11111111-1111-1111-1111-111111111111": "not-a-date"}}
        )
    assert exc.value.code == "reset_date_overrides_invalid"


def test_reset_date_overrides_rejects_non_uuid_key():
    with pytest.raises(SettingsValidationError) as exc:
        validate_settings_update(
            {}, {"fairness.reset_date_overrides": {"not-a-uuid": "2026-08-01"}}
        )
    assert exc.value.code == "reset_date_overrides_invalid"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/unit/test_settings_loader.py -k reset_date_overrides -v`
Expected: FAIL — `validate_settings_update` doesn't recognize the key yet, so `merged[...]` assertions still pass through unvalidated (the `_rejects_*` tests fail because no `SettingsValidationError` is raised).

- [ ] **Step 3: Implement the validation**

In `backend/app/services/settings_loader.py`, add near the top (after the `ACTIVE_DAYS_REFERENCE_DATE_KEY` constant):

```python
RESET_DATE_OVERRIDES_KEY = "fairness.reset_date_overrides"
```

Add this block inside `validate_settings_update`, right after the existing `ACTIVE_DAYS_REFERENCE_DATE_KEY` block (after line 110, before `def _density`):

```python
    if RESET_DATE_OVERRIDES_KEY in updates:
        overrides = updates[RESET_DATE_OVERRIDES_KEY]
        if not isinstance(overrides, dict):
            raise SettingsValidationError("reset_date_overrides_invalid")
        for node_key, date_value in overrides.items():
            try:
                uuid.UUID(str(node_key))
            except (ValueError, AttributeError, TypeError) as exc:
                raise SettingsValidationError("reset_date_overrides_invalid") from exc
            if not isinstance(date_value, str):
                raise SettingsValidationError("reset_date_overrides_invalid")
            try:
                date.fromisoformat(date_value)
            except ValueError as exc:
                raise SettingsValidationError("reset_date_overrides_invalid") from exc
```

`uuid` is already imported at the top of this file (line 3: `import uuid`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/unit/test_settings_loader.py -v`
Expected: PASS (all, including the pre-existing tests in this file)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/settings_loader.py backend/tests/unit/test_settings_loader.py
git commit -m "feat: validate fairness.reset_date_overrides setting shape"
```

---

### Task 2: `SoldierInput.unit_join_date`

**Files:**
- Modify: `backend/app/algorithm/types.py:30-58` (`SoldierInput`)
- Modify: `backend/app/services/algorithm_bridge.py:360-373` (`load_soldier_inputs`, the `SoldierInput(...)` construction)
- Test: `backend/tests/test_effort_score.py`

**Interfaces:**
- Produces: `SoldierInput.unit_join_date: date | None` (defaults to `None`), populated by `load_soldier_inputs` from `Soldier.unit_join_date`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_effort_score.py (append near test_soldier_input_has_effort_fields)
def test_soldier_input_has_unit_join_date_field():
    from app.algorithm.types import SoldierInput
    import uuid
    from datetime import date
    from decimal import Decimal

    s = SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("0"),
        active_days=90,
    )
    assert s.unit_join_date is None

    s2 = SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("0"),
        active_days=90,
        unit_join_date=date(2025, 6, 1),
    )
    assert s2.unit_join_date == date(2025, 6, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_effort_score.py -k unit_join_date -v`
Expected: FAIL with `TypeError: SoldierInput.__init__() got an unexpected keyword argument 'unit_join_date'`

- [ ] **Step 3: Add the field and populate it**

In `backend/app/algorithm/types.py`, add to the `SoldierInput` dataclass, right after `hierarchy_node_id: uuid.UUID | None = None` (line 37):

```python
    unit_join_date: date | None = None
```

In `backend/app/services/algorithm_bridge.py`, inside `load_soldier_inputs`'s `result.append(SoldierInput(...))` block (starts at line 360), add `unit_join_date=s.unit_join_date,` next to the existing `enrolled_at=s.enrolled_at,` (line 363):

```python
        result.append(
            SoldierInput(
                id=s.id,
                enrolled_at=s.enrolled_at,
                unit_join_date=s.unit_join_date,
                cumulative_score=cum,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_effort_score.py -v`
Expected: PASS (all tests in the file, including this new one)

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/types.py backend/app/services/algorithm_bridge.py backend/tests/test_effort_score.py
git commit -m "feat: thread unit_join_date onto SoldierInput"
```

---

### Task 3: Reset-date resolver (`scoring.py`)

**Files:**
- Modify: `backend/app/services/scoring.py` (add near `_burden_share_reset_date`, line ~710)
- Test: `backend/tests/test_effort_score.py`

**Interfaces:**
- Consumes: `SystemSetting` via `get_setting` (already imported in `scoring.py`); `HierarchyNode` (already imported in `scoring.py`, confirmed via existing `select(HierarchyNode)` usage elsewhere in the file).
- Produces:
  - `resolve_reset_dates_for_soldiers(session: Session, soldiers: Sequence[Any]) -> dict[uuid.UUID, date]` — soldiers need `.id` and `.hierarchy_node_id`. Used by Task 5 and Task 6.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_effort_score.py (append)
def test_resolve_reset_dates_uses_nearest_ancestor_override(admin_session):
    from datetime import date as date_cls
    from app.db.models import HierarchyNode, SystemSetting
    from app.services.scoring import resolve_reset_dates_for_soldiers
    from tests.helpers import create_soldier

    root = HierarchyNode(level="corps", name="root", path_ids=[])
    admin_session.add(root)
    admin_session.flush()
    root.path_ids = [root.id]

    branch = HierarchyNode(level="division", name="polaris", parent_id=root.id, path_ids=[])
    admin_session.add(branch)
    admin_session.flush()
    branch.path_ids = [root.id, branch.id]

    team = HierarchyNode(level="unit", name="polaris-team", parent_id=branch.id, path_ids=[])
    admin_session.add(team)
    admin_session.flush()
    team.path_ids = [root.id, branch.id, team.id]
    admin_session.flush()

    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-07-01"))
    admin_session.add(SystemSetting(
        key="fairness.reset_date_overrides",
        value={str(branch.id): "2026-08-20"},
    ))
    admin_session.flush()

    soldier_on_team = create_soldier(admin_session, personal_number="9900001")
    soldier_on_team.hierarchy_node_id = team.id
    soldier_no_node = create_soldier(admin_session, personal_number="9900002")
    soldier_no_node.hierarchy_node_id = None
    admin_session.flush()

    resolved = resolve_reset_dates_for_soldiers(admin_session, [soldier_on_team, soldier_no_node])

    # soldier_on_team's own node (team) has no override, but its ancestor
    # (branch) does -> nearest-ancestor wins over the global default.
    assert resolved[soldier_on_team.id] == date_cls(2026, 8, 20)
    # No hierarchy node at all -> global default.
    assert resolved[soldier_no_node.id] == date_cls(2026, 7, 1)


def test_resolve_reset_dates_falls_back_to_global_default(admin_session):
    from datetime import date as date_cls
    from app.db.models import HierarchyNode, SystemSetting
    from app.services.scoring import resolve_reset_dates_for_soldiers
    from tests.helpers import create_soldier

    node = HierarchyNode(level="division", name="focus", path_ids=[])
    admin_session.add(node)
    admin_session.flush()
    node.path_ids = [node.id]
    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-07-01"))
    admin_session.flush()

    s = create_soldier(admin_session, personal_number="9900003")
    s.hierarchy_node_id = node.id
    admin_session.flush()

    resolved = resolve_reset_dates_for_soldiers(admin_session, [s])
    assert resolved[s.id] == date_cls(2026, 7, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_effort_score.py -k resolve_reset_dates -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_reset_dates_for_soldiers'`

- [ ] **Step 3: Implement the resolver**

In `backend/app/services/scoring.py`, add right after `_burden_share_reset_date` (after line 709, before the existing blank line at 710-711):

```python
def _reset_date_overrides(session: Session) -> dict[str, str]:
    """Raw {node_id_str: iso_date} from fairness.reset_date_overrides, or {}
    if unset/malformed. Validation of well-formedness happens at write time
    (settings_loader.validate_settings_update) — this is a defensive read."""
    from app.services.settings_loader import SettingNotFound, get_setting

    try:
        raw = get_setting(session, "fairness.reset_date_overrides")
    except SettingNotFound:
        return {}
    return raw if isinstance(raw, dict) else {}


def _resolve_reset_date_from_path(
    path_ids: list[uuid.UUID], overrides: dict[str, str], default: date
) -> date:
    """Nearest-ancestor override, else default. path_ids is root-to-self
    (HierarchyNode.path_ids convention — see hierarchy.py's
    `path_ids = [*parent.path_ids, node.id]`), so walking it in reverse
    checks the soldier's own node first, then each ancestor toward the root."""
    for node_id in reversed(path_ids):
        raw = overrides.get(str(node_id))
        if raw is not None:
            return date.fromisoformat(raw)
    return default


def resolve_reset_dates_for_soldiers(
    session: Session, soldiers: Sequence[Any]
) -> dict[uuid.UUID, date]:
    """Per-soldier effective fairness reset date: nearest-ancestor override
    from fairness.reset_date_overrides, else the global fairness.reset_date
    default. `soldiers` need `.id` and `.hierarchy_node_id` (works for both
    `Soldier` ORM rows and `SoldierInput`).

    One query for the distinct hierarchy nodes actually present among
    `soldiers` (not the whole tree), then each distinct node's ancestor walk
    runs once and is cached — O(distinct_nodes) resolutions, O(soldiers) dict
    lookups, regardless of how many soldiers share a node."""
    overrides = _reset_date_overrides(session)
    default = _burden_share_reset_date(session)

    distinct_node_ids = {s.hierarchy_node_id for s in soldiers if s.hierarchy_node_id is not None}
    node_path_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    if distinct_node_ids:
        node_path_map = {
            n.id: list(n.path_ids)
            for n in session.execute(
                select(HierarchyNode.id, HierarchyNode.path_ids).where(
                    HierarchyNode.id.in_(distinct_node_ids)
                )
            ).all()
        }

    node_resolved: dict[uuid.UUID, date] = {
        node_id: _resolve_reset_date_from_path(node_path_map.get(node_id, []), overrides, default)
        for node_id in distinct_node_ids
    }

    return {
        s.id: node_resolved.get(s.hierarchy_node_id, default)
        for s in soldiers
    }
```

Check the top of `backend/app/services/scoring.py` for a `Sequence` import — if `from collections.abc import Sequence` isn't already there, add it alongside the existing `typing`/`collections.abc` imports at the top of the file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_effort_score.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoring.py backend/tests/test_effort_score.py
git commit -m "feat: resolve fairness reset date per hierarchy node"
```

---

### Task 4: Fix `_compute_effort_data`'s per-soldier quarter clip

This is the core correctness fix identified during design review: `q_days` (the denominator) must clip to the same per-soldier floor as `active_in_q` (the numerator), or a soldier whose branch's reset date is later than whichever date the shared quarter list was built from gets an understated `active_frac` even when they were fully active the whole time.

**Files:**
- Modify: `backend/app/services/effort_score.py:207-265` (`_compute_effort_data`)
- Test: `backend/tests/test_effort_score.py`

**Interfaces:**
- Consumes: nothing new from other tasks (this function stays DB-free/pure).
- Produces: `_compute_effort_data(*, soldiers, quarters, quarter_unit_scores, quarter_soldier_scores, soldier_reset_dates: dict[uuid.UUID, date]) -> dict[uuid.UUID, EffortData]` — **`soldier_reset_dates` is a new required keyword argument.** Every existing direct caller must be updated in this task (`compute_effort_data`, `_try_projected_effort_data` in `scoring.py`, and the 4 direct-call tests below).

- [ ] **Step 1: Update `_MockSoldier` and the 4 existing direct-call tests, then write the new failing tests**

In `backend/tests/test_effort_score.py`, update `_MockSoldier` (line 52-55):

```python
@dataclass
class _MockSoldier:
    id: uuid.UUID
    enrolled_at: date
    unit_join_date: date | None = None
```

Update the 4 existing calls to `_compute_effort_data` (`test_new_soldier_no_history`, `test_veteran_perfect_average`, `test_soldier_not_yet_enrolled`, `test_effort_offset_integer`) to pass `soldier_reset_dates` equal to each quarter list's own first quarter start (reproducing today's behavior exactly, since that's what the shared quarter list was already clipped to):

```python
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=[(date(2026, 4, 1), date(2026, 6, 30))],
        quarter_unit_scores={date(2026, 4, 1): Decimal("100")},
        quarter_soldier_scores={date(2026, 4, 1): {}},
        soldier_reset_dates={sid: date(2026, 4, 1)},
    )
```
(same pattern for the other 3: `test_veteran_perfect_average` and `test_soldier_not_yet_enrolled` use `soldier_reset_dates={sid: date(2025, 1, 1)}`, `test_effort_offset_integer` uses `soldier_reset_dates={sid: date(2025, 1, 1)}` — i.e. the start of their first tracked quarter in each test.)

Now add the new tests proving the fix:

```python
def test_veteran_gets_full_active_frac_despite_later_shared_quarter_start():
    """Reproduces the bug caught during design review: a soldier already
    active before their OWN branch's reset date must get active_frac=100%
    for the post-reset portion of the quarter, not diluted by an earlier
    date that governs the shared quarter list because some OTHER soldier's
    branch resets earlier."""
    sid = _sid()
    # Active well before any reset date under consideration.
    soldier = _MockSoldier(id=sid, enrolled_at=date(2025, 1, 1))
    # Shared quarter list starts Jul 1 (some other soldier's earlier reset date)
    # but THIS soldier's own resolved reset date is Aug 20, inside the same quarter.
    quarters = [(date(2026, 7, 1), date(2026, 9, 30))]
    unit_scores = {date(2026, 7, 1): Decimal("100")}
    soldier_scores = {date(2026, 7, 1): {sid: Decimal("42")}}
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
        soldier_reset_dates={sid: date(2026, 8, 20)},
    )
    # own_floor = Aug 20; q_days = Aug20..Sep30 = 42; soldier already active
    # since before Aug 20 -> active_in_q = 42 -> active_frac = 100%, not 46%.
    assert result[sid].effort_score == Decimal("42") / Decimal("100")


def test_new_arrival_after_own_branch_reset_date_gets_partial_frac():
    """A soldier whose unit_join_date is AFTER their own branch's resolved
    reset date is a genuinely new arrival — active_frac should be below
    100%, computed against their own (already reset-clipped) window."""
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2026, 9, 1), unit_join_date=date(2026, 9, 1))
    quarters = [(date(2026, 7, 1), date(2026, 9, 30))]
    unit_scores = {date(2026, 7, 1): Decimal("100")}
    soldier_scores = {date(2026, 7, 1): {sid: Decimal("30")}}
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
        soldier_reset_dates={sid: date(2026, 8, 20)},
    )
    # own_floor = Aug 20 (branch reset), q_days = 42 (Aug20..Sep30).
    # soldier_start = max(Aug20, Sep1) = Sep1 -> active_in_q = Sep1..Sep30 = 30.
    # active_frac = 30/42.
    expected_frac = Decimal("30") / Decimal("42")
    assert abs(result[sid].effort_score - Decimal("30") * expected_frac / Decimal("100")) < Decimal("0.0001")


def test_unit_join_date_used_over_enrolled_at_for_activation():
    """A soldier enrolled_at (roster entry date) later than their real
    unit_join_date must not be penalized for the admin's lag entering them."""
    sid = _sid()
    # Roster entry lagged 2 weeks behind actual unit join.
    soldier = _MockSoldier(id=sid, enrolled_at=date(2026, 9, 1), unit_join_date=date(2026, 8, 15))
    quarters = [(date(2026, 7, 1), date(2026, 9, 30))]
    unit_scores = {date(2026, 7, 1): Decimal("100")}
    soldier_scores = {date(2026, 7, 1): {sid: Decimal("20")}}
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
        soldier_reset_dates={sid: date(2026, 7, 1)},
    )
    # own_floor = Jul 1 (reset date, earlier than unit_join_date), q_days = 92.
    # activation = unit_join_date = Aug 15 (NOT enrolled_at = Sep 1).
    # active_in_q = Aug15..Sep30 = 47.
    expected_frac = Decimal(47) / Decimal(92)
    assert abs(result[sid].effort_score - Decimal("20") * expected_frac / Decimal("100")) < Decimal("0.0001")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_effort_score.py -v`
Expected: FAIL — `TypeError: _compute_effort_data() missing 1 required keyword-only argument: 'soldier_reset_dates'` on every test that calls it (the 4 updated ones and the 3 new ones).

- [ ] **Step 3: Implement the fix**

Replace the loop body in `_compute_effort_data` (`backend/app/services/effort_score.py:207-265`) — change the signature and the per-quarter computation:

```python
def _compute_effort_data(
    *,
    soldiers: list[Any],   # objects with .id (UUID), .enrolled_at (date), .unit_join_date (date | None)
    quarters: list[tuple[date, date]],
    quarter_unit_scores: dict[date, Decimal],
    quarter_soldier_scores: dict[date, dict[uuid.UUID, Decimal]],
    soldier_reset_dates: dict[uuid.UUID, date],
) -> dict[uuid.UUID, EffortData]:
    """
    Pure-logic core: compute EffortData per soldier given pre-aggregated quarter scores.

    effort_score = A_i / W_i  where:
        A_i = Σ(s_q × active_frac_q)   — personal weighted score
        W_i = Σ(U_q × active_frac_q)   — unit total weighted score

    Both active_in_q (numerator) and q_days (denominator) clip to the SAME
    per-soldier floor: max(quarter_start, this soldier's own resolved reset
    date). Clipping only the numerator (the historical bug this replaces)
    understates active_frac for any soldier whose own reset date is later
    than whichever date the shared `quarters` list happened to be built
    from — which now happens routinely once reset dates vary per hierarchy
    node instead of being one global value for the whole run.

    C_over_D = 1 / (max(W_i, 1) × 1000)
        Used by the bridge as: effort_per_milli = int(C_over_D × EFFORT_SCALE)
    """
    result: dict[uuid.UUID, EffortData] = {}

    for soldier in soldiers:
        A_i = Decimal("0")
        W_i = Decimal("0")
        own_reset = soldier_reset_dates[soldier.id]
        activation = soldier.unit_join_date or soldier.enrolled_at

        for q_start, q_end in quarters:
            own_floor = max(q_start, own_reset)
            if own_floor > q_end:
                continue  # this quarter is entirely before the soldier's own reset date
            q_days = (q_end - own_floor).days + 1

            soldier_start = max(own_floor, activation)
            if soldier_start > q_end:
                continue  # not active in this quarter at all

            active_in_q = (q_end - soldier_start).days + 1
            active_frac = Decimal(active_in_q) / Decimal(q_days)

            unit_score = quarter_unit_scores.get(q_start, Decimal("0"))
            if unit_score > 0:
                s_score = quarter_soldier_scores.get(q_start, {}).get(soldier.id, Decimal("0"))
                A_i += s_score * active_frac
                W_i += unit_score * active_frac

        effective_W = W_i if W_i > Decimal("0") else Decimal("1")
        effort_score = A_i / W_i if W_i > Decimal("0") else Decimal("0")
        C_over_D = Decimal("1") / (effective_W * 1000)
        effort_offset = int(effort_score * EFFORT_SCALE)

        result[soldier.id] = EffortData(
            effort_score=effort_score,
            C_over_D=C_over_D,
            effort_offset=effort_offset,
            effort_per_milli=0,
        )

    return result
```

Now fix the two callers this breaks (both currently call `_compute_effort_data` without `soldier_reset_dates`):

In `backend/app/services/effort_score.py`, `compute_effort_data`'s final `return _compute_effort_data(...)` call (line ~404-409) and its early-return for the no-quarters case (line ~360-366) — pass a trivial uniform dict for now (Task 5 replaces this with real per-soldier resolution):

```python
    if not all_quarters:
        return _compute_effort_data(
            soldiers=soldiers,
            quarters=[],
            quarter_unit_scores={},
            quarter_soldier_scores={},
            soldier_reset_dates={s.id: reset_date for s in soldiers},
        )
```//and similarly for the final return, add `soldier_reset_dates={s.id: reset_date for s in soldiers},`.

In `backend/app/services/scoring.py`, `_try_projected_effort_data` (line ~1451), add the same trivial pass-through (Task 6 replaces this with a real bailout check):

```python
    data = _compute_effort_data(
        soldiers=soldiers,
        quarters=[(q_start, q_end) for q_start, q_end, _calendar_qs in windows],
        quarter_unit_scores={...},  # unchanged
        quarter_soldier_scores={...},  # unchanged
        soldier_reset_dates={s.id: reset_date for s in soldiers},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_effort_score.py backend/app/services/tests/test_score_projection.py -v`
Expected: PASS (all — the projection tests exercise `_try_projected_effort_data` indirectly and must still pass since the trivial dict reproduces prior behavior exactly when every soldier shares one reset date)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/effort_score.py backend/app/services/scoring.py backend/tests/test_effort_score.py
git commit -m "fix: clip effort quarter length to the same per-soldier floor as active days"
```

---

### Task 5: Wire per-soldier resolution into `compute_effort_data` / `compute_burden_share_breakdown`

**Files:**
- Modify: `backend/app/services/effort_score.py:294-409` (`compute_effort_data`)
- Modify: `backend/app/services/effort_score.py:412-574` (`compute_burden_share_breakdown`)
- Test: `backend/tests/test_effort_score.py`

**Interfaces:**
- Consumes: `resolve_reset_dates_for_soldiers` (Task 3).
- Produces: `compute_effort_data(session, *, soldiers, planning_start, planning_end, reset_date: date | None = None, pending_duties=())` — `reset_date` becomes optional; when `None`, resolved per-soldier via hierarchy overrides, and the query/list-building floor uses `min()` of the resolved values. Same for `compute_burden_share_breakdown`'s `reset_date` parameter.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_effort_score.py (append)
def test_compute_effort_data_resolves_reset_date_per_hierarchy(admin_session):
    """Two soldiers in different branches with different reset-date overrides:
    neither's ratio should be computed against the other's window."""
    from datetime import date as date_cls
    from app.db.models import DutyLocation, DutyType, HierarchyNode, SystemSetting
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    focus = HierarchyNode(level="division", name="focus", path_ids=[])
    polaris = HierarchyNode(level="division", name="polaris", path_ids=[])
    admin_session.add_all([focus, polaris])
    admin_session.flush()
    focus.path_ids = [focus.id]
    polaris.path_ids = [polaris.id]
    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-07-01"))
    admin_session.add(SystemSetting(
        key="fairness.reset_date_overrides", value={str(polaris.id): "2026-08-20"}
    ))
    admin_session.flush()

    dt, loc = _seed_duty_type(admin_session, "cross-branch")

    focus_soldier = create_soldier(admin_session, personal_number="9910001")
    focus_soldier.hierarchy_node_id = focus.id
    focus_soldier.enrolled_at = date_cls(2025, 1, 1)
    polaris_soldier = create_soldier(admin_session, personal_number="9910002")
    polaris_soldier.hierarchy_node_id = polaris.id
    polaris_soldier.enrolled_at = date_cls(2025, 1, 1)
    admin_session.flush()

    # Both soldiers do the same amount of duty in Q3 2026, both fully active
    # since before their OWN branch's reset date.
    create_assignment(
        admin_session, soldier_id=focus_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 7, 5), end_date=date_cls(2026, 7, 15), actor_id=None,
    )
    create_assignment(
        admin_session, soldier_id=polaris_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 8, 25), end_date=date_cls(2026, 9, 4), actor_id=None,
    )
    admin_session.flush()

    result = compute_effort_data(
        admin_session,
        soldiers=[focus_soldier, polaris_soldier],
        planning_start=date_cls(2026, 10, 1),
        planning_end=date_cls(2026, 10, 1),
    )
    # Both fully active for their own branch's post-reset window with the
    # same amount of duty -> comparable effort_score, neither penalized by
    # the other's earlier/later reset date.
    assert result[focus_soldier.id].effort_score > 0
    assert result[polaris_soldier.id].effort_score > 0


def test_compute_effort_data_explicit_reset_date_still_forces_uniform_date(admin_session):
    """Backward compatibility: passing reset_date explicitly still forces
    that single date for every soldier, ignoring any hierarchy overrides."""
    from datetime import date as date_cls
    from app.db.models import HierarchyNode, SystemSetting
    from tests.helpers import create_soldier

    node = HierarchyNode(level="division", name="branch-x", path_ids=[])
    admin_session.add(node)
    admin_session.flush()
    node.path_ids = [node.id]
    admin_session.add(SystemSetting(
        key="fairness.reset_date_overrides", value={str(node.id): "2026-08-20"}
    ))
    admin_session.flush()

    s = create_soldier(admin_session, personal_number="9910003")
    s.hierarchy_node_id = node.id
    s.enrolled_at = date_cls(2025, 1, 1)
    admin_session.flush()

    # Explicit reset_date bypasses the override entirely — behaves exactly
    # like today's single-global-date callers.
    result = compute_effort_data(
        admin_session,
        soldiers=[s],
        planning_start=date_cls(2026, 10, 1),
        planning_end=date_cls(2026, 10, 1),
        reset_date=date_cls(2025, 1, 1),
    )
    assert s.id in result  # doesn't raise, ran the forced-date path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_effort_score.py -k "resolves_reset_date_per_hierarchy or explicit_reset_date_still_forces" -v`
Expected: FAIL — `compute_effort_data` still requires `reset_date` as a positional/required kwarg (`TypeError: missing required keyword argument: 'reset_date'` for the first test, since it's called without one).

- [ ] **Step 3: Implement**

In `backend/app/services/effort_score.py`, change `compute_effort_data`'s signature (line ~294-302):

```python
def compute_effort_data(
    session: Session,
    *,
    soldiers: list[Any],
    planning_start: date,
    planning_end: date,
    reset_date: date | None = None,
    pending_duties: Sequence[Any] = (),
) -> dict[uuid.UUID, EffortData]:
```

Right after the docstring, before `history_end = planning_start - timedelta(days=1)` (line ~322), add:

```python
    from app.services.scoring import _burden_share_reset_date, resolve_reset_dates_for_soldiers

    if reset_date is not None:
        soldier_reset_dates = {s.id: reset_date for s in soldiers}
    else:
        soldier_reset_dates = resolve_reset_dates_for_soldiers(session, soldiers)
    reset_date = min(soldier_reset_dates.values()) if soldier_reset_dates else _burden_share_reset_date(session)
```

Update the two `_compute_effort_data(...)` call sites in this same function (touched in Task 4 with a trivial dict) to pass the now-real `soldier_reset_dates` instead:

```python
            soldier_reset_dates=soldier_reset_dates,
```

Now do the parallel fix in `compute_burden_share_breakdown` (line ~412-421 signature, and its inline loop at line ~521-557). Signature:

```python
def compute_burden_share_breakdown(
    session: Session,
    *,
    soldier: Any,
    planning_start: date,
    planning_end: date,
    reset_date: date | None = None,
    extra_adj_delta: Decimal = Decimal("0"),
    extra_adj_date: date | None = None,
) -> BurdenShareBreakdown:
```

**Ordering matters here — do not resolve per-soldier before the projected-cache call.** The existing `_try_projected_burden_share_breakdown` call sits at the very top of this function (lines ~432-444, added before this task and untouched by it). Task 6 teaches that helper to bail out by comparing the soldier's real resolved date against the plain global default it's handed — so this function must keep passing the plain global default into it, and only apply per-soldier resolution afterward, in the legacy fallback. Replace the top of the function (the existing `from app.services.effort_score import (...)` / `projected = _try_projected_burden_share_breakdown(...)` / `if projected is not None: return projected` block) with:

```python
    from app.services.scoring import _burden_share_reset_date, _try_projected_burden_share_breakdown

    global_default = reset_date if reset_date is not None else _burden_share_reset_date(session)
    projected = _try_projected_burden_share_breakdown(
        session,
        soldier=soldier,
        planning_start=planning_start,
        planning_end=planning_end,
        reset_date=global_default,
        extra_adj_delta=extra_adj_delta,
        extra_adj_date=extra_adj_date,
    )
    if projected is not None:
        return projected

    from app.services.scoring import resolve_reset_dates_for_soldiers

    if reset_date is None:
        reset_date = resolve_reset_dates_for_soldiers(session, [soldier])[soldier.id]
    # else: an explicit reset_date forces that single date, matching today's
    # single-global-date callers — same back-compat rule as compute_effort_data.
```

(The one soldier's own quarter loop further down — which already does `soldier_start = max(soldier.enrolled_at, q_start_d)` — needs the same per-soldier-floor fix as `_compute_effort_data`. Replace lines ~526-533:)

```python
    for q_start_d, q_end_d in quarters:
        own_floor = max(q_start_d, reset_date)
        if own_floor > q_end_d:
            continue
        q_days = (q_end_d - own_floor).days + 1
        activation = soldier.unit_join_date or soldier.enrolled_at
        soldier_start = max(own_floor, activation)
        if soldier_start > q_end_d:
            continue  # not active in this quarter
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_effort_score.py backend/app/services/tests/test_score_projection.py -v`
Expected: PASS (all — including the pre-existing `test_default_frame_counts_quarters_before_two_year_window`, `test_breakdown_contributions_reconstruct_scores`, etc., which all pass `reset_date=` explicitly and so are unaffected)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/effort_score.py backend/tests/test_effort_score.py
git commit -m "feat: auto-resolve per-hierarchy reset date in compute_effort_data and burden-share breakdown"
```

---

### Task 6: Score-projection cache bails out when an override is in play

**Files:**
- Modify: `backend/app/services/scoring.py:1434-1463` (`_try_projected_effort_data`)
- Modify: `backend/app/services/scoring.py:1475-1496` (`_try_projected_burden_share_breakdown`)
- Test: `backend/app/services/tests/test_score_projection.py`

**Interfaces:**
- Consumes: `resolve_reset_dates_for_soldiers` (Task 3).
- Produces: both functions now return `None` (triggering the caller's fallback to the live/legacy recompute path, which is already correct per Task 5) whenever any soldier's resolved reset date differs from the plain global default.

- [ ] **Step 1: Write the failing test**

```python
# backend/app/services/tests/test_score_projection.py (append)
def test_projected_effort_data_bails_out_when_override_applies(admin_session):
    """The projection cache's precomputed windows assume one global reset
    date. A hierarchy override changes an individual soldier's effective
    date, so the cache must defer to the live recompute rather than serve
    a result computed against the wrong window."""
    from app.db.models import HierarchyNode, SystemSetting
    from app.services import scoring as sc
    from tests.helpers import create_soldier

    node = HierarchyNode(level="division", name="polaris-proj", path_ids=[])
    admin_session.add(node)
    admin_session.flush()
    node.path_ids = [node.id]
    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-07-01"))
    admin_session.add(SystemSetting(
        key="fairness.reset_date_overrides", value={str(node.id): "2026-08-20"}
    ))
    admin_session.flush()

    s = create_soldier(admin_session, personal_number="9920001")
    s.hierarchy_node_id = node.id
    admin_session.flush()

    assert sc._try_projected_effort_data(admin_session, [s]) is None


def test_projected_effort_data_still_works_without_any_override(admin_session):
    """No override configured anywhere -> every soldier resolves to the
    global default -> the projection cache path is unaffected."""
    from app.db.models import SystemSetting
    from app.services import scoring as sc
    from tests.helpers import create_soldier

    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-07-01"))
    admin_session.flush()
    s = create_soldier(admin_session, personal_number="9920002")
    admin_session.flush()

    # Not asserting a specific non-None result here (projection readiness
    # depends on reconciliation state this test doesn't set up) — asserting
    # only that it does NOT bail out solely because of hierarchy overrides.
    # A soldier with no hierarchy_node_id always resolves to the global
    # default, so the override-mismatch check must not itself return None.
    result = sc._try_projected_effort_data(admin_session, [s])
    assert result is None or s.id in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_score_projection.py -k projected_effort_data_bails -v`
Expected: FAIL — `_try_projected_effort_data` currently never returns `None` purely because of a hierarchy override (it doesn't check for one at all), so it proceeds into the mismatched-window computation instead of bailing.

- [ ] **Step 3: Implement the bailout**

In `backend/app/services/scoring.py`, `_try_projected_effort_data` (line ~1434), add the check right after computing `reset_date` (line ~1439):

```python
def _try_projected_effort_data(
    session: Session, soldiers: list[Soldier]
) -> dict[uuid.UUID, Any] | None:
    from app.services.effort_score import _compute_effort_data

    reset_date = _burden_share_reset_date(session)
    soldier_reset_dates = resolve_reset_dates_for_soldiers(session, soldiers)
    if any(d != reset_date for d in soldier_reset_dates.values()):
        return None  # a hierarchy override applies to at least one soldier; the
                      # cache's precomputed windows assume one global date — defer
                      # to compute_effort_data's live, override-aware recompute.
    planning_start = _burden_share_planning_start(session)
    projection_inputs = _projection_burden_share_inputs(
        session,
        soldiers=soldiers,
        reset_date=reset_date,
        planning_start=planning_start,
        planning_end=planning_start,
    )
    if projection_inputs is None:
        return None
    windows, q_unit_scores, q_soldier_scores = projection_inputs
    data = _compute_effort_data(
        soldiers=soldiers,
        quarters=[(q_start, q_end) for q_start, q_end, _calendar_qs in windows],
        quarter_unit_scores={
            q_start: q_unit_scores.get(calendar_qs, Decimal("0"))
            for q_start, _q_end, calendar_qs in windows
        },
        quarter_soldier_scores={
            q_start: q_soldier_scores.get(calendar_qs, {})
            for q_start, _q_end, calendar_qs in windows
        },
        soldier_reset_dates=soldier_reset_dates,
    )
    return data
```

In `_try_projected_burden_share_breakdown` (line ~1475), add the same check right after its existing quarter-alignment guard (after line 1495, before `windows = _burden_share_quarter_windows(...)`):

```python
    resolved = resolve_reset_dates_for_soldiers(session, [soldier])[soldier.id]
    if resolved != reset_date:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_score_projection.py backend/tests/test_effort_score.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoring.py backend/app/services/tests/test_score_projection.py
git commit -m "fix: bail projection cache to live recompute when a hierarchy reset-date override applies"
```

---

### Task 7: Frontend — widen `SettingsMap` type

**Files:**
- Modify: `frontend/src/api/systemSettings.ts:3`
- Test: none (pure type change; covered by Task 8's component tests compiling and running)

**Interfaces:**
- Produces: `SettingsMap = Record<string, string | number | boolean | string[] | Record<string, string> | null>`

- [ ] **Step 1: Make the change**

```typescript
export type SettingsMap = Record<string, string | number | boolean | string[] | Record<string, string> | null>;
```

- [ ] **Step 2: Verify the frontend still typechecks**

Run: `npm run typecheck` (from `frontend/`)
Expected: PASS — this is a type widening, no narrowing, so no existing usage should break.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/systemSettings.ts
git commit -m "feat: widen SettingsMap to allow object-valued settings"
```

---

### Task 8: Frontend — reset-date overrides editor

Reuses the existing `HierarchyNodePickerModal` (`frontend/src/components/HierarchyNodePickerModal.tsx`, already used by `AnnouncementsPage.tsx` the same way) instead of building a new hierarchy picker — it already does exactly what's needed: a searchable tree modal that calls `onPicked(nodeId, nodeName)`.

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx` (add `ResetDateOverridesSection`, wire it in next to the "אלגוריתם — הוגנות" group, following the exact placement pattern already used for `RankAdvancementIntervalsSection` at line 646)
- Test: `frontend/src/pages/SystemSettingsPage.test.tsx`

**Interfaces:**
- Consumes: `HierarchyNodePickerModal` (existing, unmodified), `draft`/`setValue` from `SystemSettingsContent`'s existing state (unmodified).
- Produces: `ResetDateOverridesSection({ value: Record<string, string>; onChange: (next: Record<string, string>) => void })` component.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/SystemSettingsPage.test.tsx (append to the existing describe block, or a new one)
describe("SystemSettingsContent reset-date overrides", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(systemSettingsApi.getSystemSettings).mockResolvedValue({
      "fairness.reset_date_overrides": {
        "11111111-1111-1111-1111-111111111111": "2026-08-20",
      },
    });
    vi.mocked(rankAdvancementApi.getRankLadder).mockResolvedValue({
      enlisted: [], officer: [], officer_academic: [],
    });
  });

  it("renders an existing override row with its date", async () => {
    renderWithProviders(<SystemSettingsContent />);
    expect(await screen.findByDisplayValue("2026-08-20")).toBeInTheDocument();
  });

  it("removes an override row when its remove button is clicked", async () => {
    renderWithProviders(<SystemSettingsContent />);
    await screen.findByDisplayValue("2026-08-20");
    fireEvent.click(screen.getByRole("button", { name: "הסר" }));
    expect(screen.queryByDisplayValue("2026-08-20")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- SystemSettingsPage -t "reset-date overrides"` (from `frontend/`)
Expected: FAIL — `screen.findByDisplayValue("2026-08-20")` times out, no such UI exists yet.

- [ ] **Step 3: Implement**

In `frontend/src/pages/SystemSettingsPage.tsx`, add the import at the top (near the existing `DateInput` import, line 12):

```typescript
import HierarchyNodePickerModal from "../components/HierarchyNodePickerModal";
```

Add this component after `SystemSettingsContent` (after line 651, before the `RankAdvancementIntervalsSection` comment block at line 653):

```tsx
// ── Fairness reset-date overrides ───────────────────────────────────────────
// A per-hierarchy-node override for fairness.reset_date, stored as a JSON
// dict {node_id: iso_date} — doesn't fit the flat SettingDef shape above (it's
// a list of rows, not a single value), so it gets its own small section, the
// same way RankAdvancementIntervalsSection does below. Unlike that section,
// this one round-trips through the SAME generic draft/save state as every
// other setting (fairness.reset_date_overrides is a plain SystemSetting key),
// so it takes `value`/`onChange` as props instead of managing its own query.
function ResetDateOverridesSection({
  value,
  onChange,
}: {
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [nodeNames, setNodeNames] = useState<Record<string, string>>({});

  function handlePicked(nodeId: string, nodeName: string) {
    setNodeNames((prev) => ({ ...prev, [nodeId]: nodeName }));
    onChange({ ...value, [nodeId]: value[nodeId] ?? "" });
    setPickerOpen(false);
  }

  function setDate(nodeId: string, isoDate: string) {
    onChange({ ...value, [nodeId]: isoDate });
  }

  function removeRow(nodeId: string) {
    const next = { ...value };
    delete next[nodeId];
    onChange(next);
  }

  return (
    <div className="bg-white rounded-lg shadow p-5 space-y-3 dark:bg-gray-800">
      <h2 className="font-semibold text-gray-700 border-b pb-2 dark:text-gray-200 dark:border-gray-600">
        עקיפת תאריך איפוס הוגנות לפי היררכיה
      </h2>
      <p className="text-xs text-gray-400 dark:text-gray-300">
        קובע תאריך איפוס שונה מברירת המחדל הגלובלית עבור חיילים תחת יחידה מסוימת (ומתחתיה) — למשל ענף שמצטרף למערכת בשלב מאוחר יותר של הפריסה.
      </p>
      {Object.entries(value).map(([nodeId, isoDate]) => (
        <div key={nodeId} className="flex items-center justify-between gap-4">
          <span className="text-sm text-gray-800 dark:text-gray-100">
            {nodeNames[nodeId] ?? nodeId}
          </span>
          <div className="flex items-center gap-2">
            <DateInput
              value={isoDate}
              onChange={(next) => setDate(nodeId, next)}
              className="border border-gray-300 dark:border-gray-600 rounded-lg px-2 py-1 text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-indigo-300 outline-none"
            />
            <button
              type="button"
              onClick={() => removeRow(nodeId)}
              className="text-xs text-red-600 hover:underline"
            >
              הסר
            </button>
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={() => setPickerOpen(true)}
        className="text-sm text-indigo-600 hover:underline"
      >
        + הוסף עקיפה
      </button>
      {pickerOpen && (
        <HierarchyNodePickerModal onClose={() => setPickerOpen(false)} onPicked={handlePicked} />
      )}
    </div>
  );
}
```

Wire it into the render loop, matching the exact pattern used for `RankAdvancementIntervalsSection` (line 646):

```tsx
        {group.label === "אלגוריתם — הוגנות" && (
          <ResetDateOverridesSection
            value={(draft["fairness.reset_date_overrides"] as Record<string, string>) ?? {}}
            onChange={(next) => setValue("fairness.reset_date_overrides", next)}
          />
        )}
```

`setValue`'s signature (line 511: `function setValue(key: string, value: string | number | boolean | string[])`) needs widening to accept the new type from Task 7:

```typescript
  function setValue(key: string, value: string | number | boolean | string[] | Record<string, string>) {
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- SystemSettingsPage` (from `frontend/`)
Expected: PASS (all tests in the file, including the two new ones and every pre-existing one)

- [ ] **Step 5: Run lint and typecheck**

Run: `npm run lint && npm run typecheck` (from `frontend/`)
Expected: PASS, zero warnings

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx frontend/src/pages/SystemSettingsPage.test.tsx
git commit -m "feat: admin UI for per-hierarchy fairness reset-date overrides"
```

---

## Post-implementation manual check

Not covered by automated tests — worth doing once by hand after all 8 tasks land:

1. Start the dev stack (`.\dev.ps1`), log in as admin, open Settings.
2. Add a reset-date override for some existing hierarchy node, save, refresh — confirm it persists (round-trips through `getSystemSettings`).
3. Open a soldier under that node's burden-share breakdown (their score detail view) and confirm the quarters shown respect the override rather than the global default.
4. Remove the override, save, confirm the breakdown reverts to the global default.
