"""Seed the "פולאריס" demo scenario on top of the regular seed data.

Usage: python -m app.scripts.seed_polaris [--clear-polaris] [--db-url URL]

Requires `python -m app.scripts.seed` to have already run — this script only
adds to that base data, it does not create it.

What this does:
  1. Adds a new פולאריס branch (150 soldiers across 3 מדורים / 29 צוותים,
     named differently from פוקוס) as a sibling of פוקוס/אלומות. Every
     פולאריס soldier gets the same unit_join_date: 2026-09-01.
  2. Backfills the existing פוקוס branch with duty history going back to
     2026-07-01: weekly/daily DutyShift + DutyAssignment records for every
     duty type, assigned across eligible פוקוס soldiers in a fair-but-varied
     way (least-loaded-first with some randomness, not a perfect round
     robin). Also gives every פוקוס soldier a *varied* unit_join_date and
     sets the shared fairness.reset_date setting so active-day
     fairness calculations line up with the backfilled history.

Both parts are idempotent: re-running skips whatever's already there.
  --clear-polaris   Delete the פולאריס branch subtree + soldiers before
                    recreating them. Does not touch פוקוס/אלומות or the
                    already-generated פוקוס duty history.
  --db-url URL      Override DATABASE_URL (useful outside Docker).
"""

# Must happen before any app import that touches the DB engine.
import os as _os, sys as _sys
for _i, _a in enumerate(_sys.argv):
    if _a.startswith("--db-url="):
        _os.environ["DATABASE_URL"] = _a.split("=", 1)[1]
        break
    if _a == "--db-url" and _i + 1 < len(_sys.argv):
        _os.environ["DATABASE_URL"] = _sys.argv[_i + 1]
        break

import random
import uuid
from datetime import date, timedelta

from app.auth.password import hash_password
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    HierarchyNode,
    Soldier,
    SystemSetting,
)
from app.scripts.seed import _duty_hours, _mandatory_end, _single_day_shift_span
from app.services.dm_scope import assign_dm_scope
from app.services.rank_advancement import resolve_track
from app.services.settings_loader import FAIRNESS_RESET_DATE_KEY, set_setting

def _safe_print(s: str) -> None:
    import sys

    sys.stdout.buffer.write(s.encode("utf-8", errors="replace") + b"\n")


HISTORY_START = date(2026, 7, 1)
POLARIS_JOIN_DATE = date(2026, 9, 1)
PN_BASE = 6000001
_FOCUS_BACKFILL_MARKER_KEY = "polaris_scenario.focus_backfill_done"

_POLARIS_MADORIM = ["מצפן", "קוטב", "מסלול"]
_POLARIS_TEAM_NAMES = [
    "אוריון", "קסיופיאה", "דרקו", "פגסוס", "אנדרומדה", "פרסאוס",
    "הדב הגדול", "הדב הקטן", "הצלב הדרום", "נשר",
    "כינור", "ברבור", "דולפין", "הידרה", "עטרה", "ענק", "ספינה",
    "טלה", "שור", "תאום", "סרטן", "אריה", "בתולה", "מאזניים",
    "עקרב", "קשת", "גדי", "דלי", "דגים",
]
_TEAMS_PER_MADOR = [10, 10, 9]
assert len(_POLARIS_TEAM_NAMES) == sum(_TEAMS_PER_MADOR) == 29

# (rank, is_officer, enl_year, enl_month, disc_year, disc_month) — disc=None → חובה.
# All enlistment dates are safely before POLARIS_JOIN_DATE.
_TEAM_LEADER_PROFILE_POOL = [
    ("רסל", False, 2016, 4, 2029, 6),
    ("רסל", False, 2017, 9, 2030, 3),
    ("סגם", True, 2020, 6, 2028, 6),
    ("סגם", True, 2021, 11, 2028, 11),
    ("סגן", True, 2023, 2, None, None),
    ("סגן", True, 2023, 8, None, None),
    ("סרן", True, 2019, 5, 2027, 5),
    ("רסל", False, 2018, 1, 2030, 1),
    ("סגם", True, 2022, 3, 2029, 3),
    ("סגן", True, 2024, 1, None, None),
]

# (enl_year, enl_month, rank, is_officer, discharge_year, gender)
_TEAM_MEMBER_PROFILE_POOL = [
    (2024, 9, "סמל", False, None, "female"),
    (2025, 2, 'רב"ט', False, None, "male"),
    (2025, 10, "טוראי", False, None, "male"),
    (2026, 3, "טוראי", False, None, "female"),
    (2019, 6, "רסר", False, 2035, "male"),
    (2023, 11, "סגן", True, None, "male"),
]

_MADOR_LEADER_DEFS = [
    ("סרן", 2021, 6, 2029, 6),
    ('רס"ן', 2017, 3, 2030, 3),
    ("סרן", 2022, 9, 2030, 9),
]


def _create_polaris_branch(session, psips, hashed: str, today: date) -> list[Soldier]:
    hashed_pw = hashed
    pn_counter = PN_BASE

    def next_pn() -> str:
        nonlocal pn_counter
        pn = str(pn_counter)
        pn_counter += 1
        return pn

    def make_soldier(pn: str, name: str, role: str, node_id, **extra) -> Soldier:
        med = extra.get("mandatory_end_date")
        if extra.get("discharge_date") is None and med is not None and med <= today:
            extra["mandatory_end_date"] = today + timedelta(days=365)
        s = Soldier(
            personal_number=pn,
            full_name=name,
            password_hash=hashed_pw,
            role=role,
            hierarchy_node_id=node_id,
            enrolled_at=POLARIS_JOIN_DATE,
            unit_join_date=POLARIS_JOIN_DATE,
            must_change_password=False,
            **extra,
            rank_track=resolve_track(extra.get("rank"), None),
        )
        session.add(s)
        session.flush()
        return s

    branch = HierarchyNode(level="branch", name="פולאריס", parent_id=psips.id, path_ids=[])
    session.add(branch)
    session.flush()
    branch.path_ids = psips.path_ids + [branch.id]

    madorim = []
    for mname in _POLARIS_MADORIM:
        m = HierarchyNode(level="group", name=mname, parent_id=branch.id, path_ids=[])
        session.add(m)
        session.flush()
        m.path_ids = branch.path_ids + [m.id]
        madorim.append(m)

    teams = []
    team_to_mador = []
    name_iter = iter(_POLARIS_TEAM_NAMES)
    for mador_idx, team_count in enumerate(_TEAMS_PER_MADOR):
        for _ in range(team_count):
            tname = f"צוות {next(name_iter)}"
            t = HierarchyNode(level="team", name=tname, parent_id=madorim[mador_idx].id, path_ids=[])
            session.add(t)
            session.flush()
            t.path_ids = madorim[mador_idx].path_ids + [t.id]
            teams.append(t)
            team_to_mador.append(mador_idx)

    all_soldiers: list[Soldier] = []

    # Branch commander (קבע officer, ~13 yr career)
    s_branch = make_soldier(
        next_pn(),
        "רען פולאריס",
        "commander",
        branch.id,
        is_officer=True,
        rank='סא"ל',
        bahad1_graduate=True,
        enlistment_date=date(2013, 1, 1),
        mandatory_end_date=_mandatory_end(date(2013, 1, 1)),
        discharge_date=date(2032, 1, 1),
        gender="male",
    )
    all_soldiers.append(s_branch)
    branch.commander_id = s_branch.id

    # Branch duty manager (NCO קבע, scoped to the whole branch subtree)
    s_branch_dm = make_soldier(
        next_pn(),
        "אחראי תורנויות פולאריס",
        "soldier",
        branch.id,
        is_officer=False,
        rank='רס"ל',
        bahad1_graduate=False,
        enlistment_date=date(2018, 1, 1),
        mandatory_end_date=_mandatory_end(date(2018, 1, 1)),
        discharge_date=date(2029, 1, 1),
        gender="male",
    )
    all_soldiers.append(s_branch_dm)
    assign_dm_scope(session, soldier_id=s_branch_dm.id, node_id=branch.id, actor_id=s_branch.id)

    # מדור commanders
    for mador_idx, mador in enumerate(madorim):
        rank, ey, em, dy, dm = _MADOR_LEADER_DEFS[mador_idx]
        s = make_soldier(
            next_pn(),
            f"רמד {mador.name}",
            "commander",
            mador.id,
            is_officer=True,
            rank=rank,
            bahad1_graduate=True,
            enlistment_date=date(ey, em, 1),
            mandatory_end_date=_mandatory_end(date(ey, em, 1)),
            discharge_date=date(dy, dm, 1),
            gender="male",
        )
        all_soldiers.append(s)
        mador.commander_id = s.id

    # Teams: leader + 4 members each
    for team_idx, team in enumerate(teams):
        lrank, l_is_off, ley, lem, ldy, ldm = _TEAM_LEADER_PROFILE_POOL[team_idx % len(_TEAM_LEADER_PROFILE_POOL)]
        l_enl = date(ley, lem, 1)
        l_disc = date(ldy, ldm, 1) if ldy else None
        team_short = team.name.removeprefix("צוות ")
        leader = make_soldier(
            next_pn(),
            f"רשצ {team_short}",
            "commander",
            team.id,
            is_officer=l_is_off,
            rank=lrank,
            bahad1_graduate=l_is_off,
            enlistment_date=l_enl,
            mandatory_end_date=_mandatory_end(l_enl, "male"),
            discharge_date=l_disc,
            gender="male",
        )
        all_soldiers.append(leader)
        team.commander_id = leader.id

        for member_idx in range(4):
            ey, em, rank, is_off, dy, g = _TEAM_MEMBER_PROFILE_POOL[
                (team_idx * 4 + member_idx) % len(_TEAM_MEMBER_PROFILE_POOL)
            ]
            enl = date(ey, em, 1)
            disc = date(dy, 6, 1) if dy else None
            member = make_soldier(
                next_pn(),
                f"{team_short} {member_idx + 1}",
                "soldier",
                team.id,
                is_officer=is_off,
                rank=rank,
                enlistment_date=enl,
                mandatory_end_date=_mandatory_end(enl, g),
                discharge_date=disc,
                bahad1_graduate=is_off,
                gender=g,
            )
            all_soldiers.append(member)

    return all_soldiers


def _delete_polaris_subtree(session, branch: HierarchyNode) -> None:
    all_nodes = session.query(HierarchyNode).all()
    subtree_ids = {n.id for n in all_nodes if branch.id in n.path_ids} | {branch.id}

    # Null out commander_id references before deleting soldiers (FK is RESTRICT).
    for n in all_nodes:
        if n.id in subtree_ids:
            n.commander_id = None
    session.flush()

    session.query(Soldier).filter(Soldier.hierarchy_node_id.in_(subtree_ids)).delete(
        synchronize_session=False
    )
    session.flush()

    # Delete deepest nodes first (teams → מדורים → branch).
    for level in ("team", "group", "branch"):
        session.query(HierarchyNode).filter(
            HierarchyNode.id.in_(subtree_ids), HierarchyNode.level == level
        ).delete(synchronize_session=False)
    session.flush()


# (name, required_count, cadence) — cadence anchors the weekday(s) shifts start on.
_HISTORY_DUTY_DEFS = [
    ("שמירות", 10, "weekly_mon"),
    ('אבט"ש', 2, "weekly_mon"),
    ('הגנ"ש', 2, "weekly_thu"),
    ("ליווים", 2, "daily_sun_thu"),
    ('עבודות רס"ר', 2, "daily_sun_thu"),
    ("קצין תורן", 1, "weekly_mon"),
    ("מפקד תורן", 1, "weekly_mon"),
    ('קצין מלווה אבט"ש', 1, "weekly_mon"),
    ("אבות בית", 2, "daily_sun_thu"),
    ('עבודות רס"ר בינוי', 2, "daily_sun_thu"),
    ("משמרת לילה", 2, "daily_sun_thu"),
    ("נהג תורן", 1, "daily_sun_thu"),
]


def _first_weekday_on_or_after(d: date, target: int) -> date:
    return d + timedelta(days=(target - d.weekday()) % 7)


def _vary_focus_unit_join_dates(session, focus_soldiers: list[Soldier], rng: random.Random) -> None:
    lower_floor = date(2025, 6, 1)
    upper_ceiling = date(2026, 7, 1)  # stay on/before the history window's start
    for s in focus_soldiers:
        lower = max(s.enlistment_date or lower_floor, lower_floor)
        upper = max(upper_ceiling, lower)
        span_days = (upper - lower).days
        chosen = lower + timedelta(days=rng.randint(0, span_days)) if span_days > 0 else lower
        s.unit_join_date = chosen
        # Keep enrolled_at (registration date) internally consistent — it can
        # never precede the unit_join_date it's paired with.
        if s.enrolled_at is not None and s.enrolled_at < chosen:
            s.enrolled_at = chosen


def _backfill_focus_history(session, focus_branch: HierarchyNode, s_admin: Soldier, today: date, rng: random.Random) -> None:
    if session.get(SystemSetting, _FOCUS_BACKFILL_MARKER_KEY) is not None:
        _safe_print("פוקוס duty history already backfilled — skipping.")
        return

    all_nodes = session.query(HierarchyNode).all()
    focus_node_ids = {n.id for n in all_nodes if focus_branch.id in n.path_ids} | {focus_branch.id}
    focus_soldiers = (
        session.query(Soldier).filter(Soldier.hierarchy_node_id.in_(focus_node_ids)).all()
    )
    if not focus_soldiers:
        _safe_print("No פוקוס soldiers found — skipping duty history backfill.")
        return

    _vary_focus_unit_join_dates(session, focus_soldiers, rng)
    # This function itself is about to create the backfilled duty history, so
    # the guarded registration-time bootstrap (which skips once real duty
    # history exists) doesn't apply here -- set it directly instead.
    if session.get(SystemSetting, FAIRNESS_RESET_DATE_KEY) is None:
        set_setting(session, FAIRNESS_RESET_DATE_KEY, HISTORY_START.isoformat(), actor_id=None)

    officers = [s for s in focus_soldiers if s.is_officer]
    enlisted = [s for s in focus_soldiers if not s.is_officer]

    duty_types = {dt.name: dt for dt in session.query(DutyType).all()}
    locations = session.query(DutyLocation).all()
    if not locations:
        _safe_print("No duty locations found — skipping duty history backfill.")
        return

    first_mon = _first_weekday_on_or_after(HISTORY_START, 0)
    first_thu = _first_weekday_on_or_after(HISTORY_START, 3)
    first_sun = _first_weekday_on_or_after(HISTORY_START, 6)

    load: dict[uuid.UUID, int] = {s.id: 0 for s in focus_soldiers}

    def pick_soldiers(pool: list[Soldier], count: int) -> list[Soldier]:
        chosen_ids: set[uuid.UUID] = set()
        chosen: list[Soldier] = []
        for _ in range(min(count, len(pool))):
            candidates = sorted(
                (s for s in pool if s.id not in chosen_ids), key=lambda s: load[s.id]
            )
            top = candidates[: min(5, len(candidates))]
            soldier = rng.choice(top)
            chosen.append(soldier)
            chosen_ids.add(soldier.id)
            load[soldier.id] += 1
        return chosen

    loc_idx = 0
    shifts_created = 0
    assignments_created = 0

    for name, required_count, cadence in _HISTORY_DUTY_DEFS:
        dt = duty_types.get(name)
        if dt is None:
            continue
        reqs = dt.requirements or {}
        if reqs.get("enlisted_allowed") is False:
            pool = officers
        elif reqs.get("officers_allowed") is False:
            pool = enlisted
        else:
            pool = enlisted
        if not pool:
            continue

        if cadence == "weekly_mon":
            anchor = first_mon
        elif cadence == "weekly_thu":
            anchor = first_thu
        else:
            anchor = first_sun

        starts: list[date] = []
        if cadence in ("weekly_mon", "weekly_thu"):
            w = 0
            while anchor + timedelta(weeks=w) <= today:
                starts.append(anchor + timedelta(weeks=w))
                w += 1
        else:  # daily_sun_thu
            w = 0
            while anchor + timedelta(weeks=w) <= today:
                for d in range(5):
                    day = anchor + timedelta(weeks=w, days=d)
                    if day <= today:
                        starts.append(day)
                w += 1

        for start in starts:
            loc = locations[loc_idx % len(locations)]
            loc_idx += 1
            if cadence == "weekly_mon" or cadence == "weekly_thu":
                start_time, end_time = _duty_hours(dt)
                start_date, end_date = start, start + timedelta(days=7)
            else:
                start_date, end_date, start_time, end_time = _single_day_shift_span(start, dt)

            shift = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=loc.id,
                start_date=start_date,
                end_date=end_date,
                start_time=start_time,
                end_time=end_time,
                required_count=required_count,
                notes=f"{name} (היסטוריה — תרחיש פולאריס)",
                created_by=s_admin.id,
            )
            session.add(shift)
            session.flush()
            shifts_created += 1

            for soldier in pick_soldiers(pool, required_count):
                session.add(
                    DutyAssignment(
                        soldier_id=soldier.id,
                        duty_type_id=dt.id,
                        duty_location_id=loc.id,
                        start_date=start_date,
                        end_date=end_date,
                        duty_shift_id=shift.id,
                        status="published",
                        created_by=s_admin.id,
                    )
                )
                assignments_created += 1

    session.add(SystemSetting(key=_FOCUS_BACKFILL_MARKER_KEY, value=True, updated_by=s_admin.id))
    session.flush()
    _safe_print(
        f"פוקוס history: {shifts_created} duty shifts, {assignments_created} assignments "
        f"since {HISTORY_START.isoformat()} across {len(focus_soldiers)} soldiers."
    )


def seed_polaris(*, clear_polaris: bool = False) -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        psips = (
            session.query(HierarchyNode)
            .filter(HierarchyNode.level == "department", HierarchyNode.name == "פסיפס")
            .first()
        )
        s_admin = session.query(Soldier).filter(Soldier.personal_number == "1000001").first()
        focus_branch = (
            session.query(HierarchyNode)
            .filter(HierarchyNode.level == "branch", HierarchyNode.name == "פוקוס")
            .first()
        )
        if psips is None or s_admin is None or focus_branch is None:
            raise SystemExit(
                "Base seed data not found. Run `python -m app.scripts.seed` first, "
                "then re-run this script."
            )

        today = date.today()
        rng = random.Random(42)
        hashed = hash_password("1234567890")

        existing_polaris = (
            session.query(HierarchyNode)
            .filter(HierarchyNode.level == "branch", HierarchyNode.name == "פולאריס")
            .first()
        )
        if existing_polaris is not None and clear_polaris:
            _delete_polaris_subtree(session, existing_polaris)
            session.commit()
            existing_polaris = None

        if existing_polaris is not None:
            _safe_print("פולאריס branch already exists — skipping (pass --clear-polaris to rebuild).")
        else:
            polaris_soldiers = _create_polaris_branch(session, psips, hashed, today)
            session.commit()
            _safe_print(f"Created פולאריס branch: {len(polaris_soldiers)} soldiers, all joined {POLARIS_JOIN_DATE.isoformat()}.")

        _backfill_focus_history(session, focus_branch, s_admin, today, rng)
        session.commit()


if __name__ == "__main__":
    seed_polaris(clear_polaris="--clear-polaris" in _sys.argv)
