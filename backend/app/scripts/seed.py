"""Seed the database with realistic test data.

Usage: python -m app.scripts.seed [--clear] [--with-assignments] [--fair] [--db-url URL]

Flags:
  --clear / --force      Drop and re-create all seed data.
  --with-assignments     Also pre-fill shift assignments (default: shifts are
                         created empty so the algorithm can assign them).
  --fair                 Same soldiers, but skip personal constraints and
                         soldier exemptions so nothing blocks anyone from duty
                         — useful for verifying the algorithm distributes
                         shifts fairly with no special cases.
  --db-url URL           Override DATABASE_URL (useful when running outside
                         Docker where the host is 'localhost' not 'db').
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

import uuid
from datetime import date, time
from decimal import Decimal
import math

from app.algorithm.reserve import _hierarchy_distance
from app.auth.password import hash_password
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyReserveLink,
    DutyShift,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionRequest,
    ExemptionType,
    HierarchyNode,
    PersonalConstraint,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeEvent,
    RangeExcusalRequest,
    SoldierRangeQualification,
    RangeEventStatus,
    RangeType,
    RegistrationInviteCode,
    ScoreAdjustment,
    ShiftTemplate,
    Soldier,
    SoldierEnrollmentRequest,
    SoldierExemption,
    SoldierFieldUpdate,
    SwapCandidate,
    SwapRequest,
    SystemSetting,
)
from app.db.session import SessionLocal
from app.services.invite_codes import create_invite_code
from app.services.ranges import mark_attendance


def seed(*, force: bool = False, with_assignments: bool = False, fair: bool = False):
    clear = force
    with SessionLocal() as session:
        # All regular soldiers share this password.
        hashed = hash_password("1234567890")

        if clear:
            session.query(ExemptionRequest).delete()
            session.query(PersonalConstraint).delete()
            session.query(ScoreAdjustment).delete()
            session.query(SoldierExemption).delete()
            session.query(SwapRequest).delete()
            session.query(RangeExcusalRequest).delete()
            session.query(SoldierRangeQualification).delete()
            session.query(RangeAssignment).delete()
            session.query(RangeEvent).delete()
            session.query(ExemptionDutyTypeMap).delete()
            session.query(DutyReserveLink).delete()
            session.query(DutyAssignment).delete()
            session.query(DutyShift).delete()
            session.query(SoldierEnrollmentRequest).delete()
            session.query(SoldierFieldUpdate).delete()
            session.query(HierarchyNode).delete()
            session.query(Soldier).delete()
            session.query(ShiftTemplate).delete()
            session.query(DutyType).delete()
            session.query(DutyLocation).delete()
            session.query(ExemptionType).delete()
            session.query(SystemSetting).filter(
                SystemSetting.key.in_(["system.root_node_id", "system.holding_node_id"])
            ).delete(synchronize_session=False)
            session.commit()

        # Must run after the wipe above: it's idempotent based on these same
        # SystemSetting rows, so bootstrapping before a --clear wipe leaves
        # them dangling (pointing at hierarchy nodes the wipe just deleted)
        # and they never get recreated on any later run.
        from app.scripts.bootstrap import main as bootstrap_main
        bootstrap_main()

        # Keep feature settings present even when the idempotent seed exits
        # early because the regular demo data already exists.
        for key, value in (("mitvachim.enabled", False), ("mitvachim.reminder_days_before", 3)):
            if session.get(SystemSetting, key) is None:
                session.add(SystemSetting(key=key, value=value, updated_by=None))
        session.flush()

        admin = session.query(Soldier).filter(Soldier.personal_number == "1000001").first()
        if admin:
            admin.password_hash = hashed
            admin.must_change_password = False
            session.flush()

        if session.query(Soldier).filter(Soldier.personal_number == "2000001").first():
            session.commit()
            print("Seed data already exists. Admin password updated.")
            return

        # ── Hierarchy: department → branch → group → team ──────────
        # Attach under the bootstrapped root ("כלל המסגרת") rather than as its
        # own root, so the demo data lives under the one real top-level node.
        root_setting = session.get(SystemSetting, "system.root_node_id")
        root_node_id = uuid.UUID(root_setting.value) if root_setting else None
        root_path_ids = [root_node_id] if root_node_id else []
        psips = HierarchyNode(level="department", name="פסיפס", parent_id=root_node_id, path_ids=[])
        session.add(psips)
        session.flush()
        psips.path_ids = root_path_ids + [psips.id]

        branches = []
        for bname in ["פוקוס", "אלומות"]:
            b = HierarchyNode(level="branch", name=bname, parent_id=psips.id, path_ids=[])
            session.add(b)
            session.flush()
            b.path_ids = psips.path_ids + [b.id]
            branches.append(b)

        # Branch פוקוס → מחקר, שבירה, גוליבר
        focus_groups = []
        for gname in ["מחקר", "שבירה", "גוליבר"]:
            g = HierarchyNode(level="group", name=gname, parent_id=branches[0].id, path_ids=[])
            session.add(g)
            session.flush()
            g.path_ids = branches[0].path_ids + [g.id]
            focus_groups.append(g)

        # Branch אלומות → אינפרה, פלאש, ספקטרה (no teams)
        alom_groups = []
        for gname in ["אינפרה", "פלאש", "ספקטרה"]:
            g = HierarchyNode(level="group", name=gname, parent_id=branches[1].id, path_ids=[])
            session.add(g)
            session.flush()
            g.path_ids = branches[1].path_ids + [g.id]
            alom_groups.append(g)

        # Teams under מחקר
        teams_m = []
        for tname in ["צוות מארס", "צוות טוקסיק", "צוות רוקט", "צוות ורטיגו"]:
            t = HierarchyNode(level="team", name=tname, parent_id=focus_groups[0].id, path_ids=[])
            session.add(t)
            session.flush()
            t.path_ids = focus_groups[0].path_ids + [t.id]
            teams_m.append(t)

        # Teams under שבירה
        teams_sh = []
        for tname in ["צוות פלאש", "צוות ריי", "צוות ספארק"]:
            t = HierarchyNode(level="team", name=tname, parent_id=focus_groups[1].id, path_ids=[])
            session.add(t)
            session.flush()
            t.path_ids = focus_groups[1].path_ids + [t.id]
            teams_sh.append(t)

        # Teams under גוליבר
        teams_g = []
        for tname in ["צוות ארק", "צוות אקסודוס", "צוות נילוס"]:
            t = HierarchyNode(level="team", name=tname, parent_id=focus_groups[2].id, path_ids=[])
            session.add(t)
            session.flush()
            t.path_ids = focus_groups[2].path_ids + [t.id]
            teams_g.append(t)

        all_teams = teams_m + teams_sh + teams_g

        # ── Helpers ─────────────────────────────────────────────────
        def sid(pn: str):
            s = session.query(Soldier).filter(Soldier.personal_number == pn).first()
            if s:
                return s
            raise RuntimeError(f"Soldier {pn} not created yet — ordering bug")

        from datetime import timedelta

        seed_today = date.today()

        # Mandatory service: men 32 months (2 yrs 8 mo), women 24 months (2 yrs)
        _MANDATORY_MONTHS = {"male": 32, "female": 24}

        def _mandatory_end(enlist: date, gender: str = "male") -> date:
            m = enlist.month + _MANDATORY_MONTHS[gender]
            y = enlist.year + (m - 1) // 12
            mo = ((m - 1) % 12) + 1
            d = min(enlist.day, 28)
            return date(y, mo, d)

        all_nodes = [psips] + branches + focus_groups + alom_groups + all_teams
        pn_counter = 1000001

        def next_pn() -> str:
            nonlocal pn_counter
            pn_counter += 1
            return str(pn_counter)

        def make_soldier(pn: str, name: str, role: str, node_id: int, **extra):
            # Keep intended-חובה soldiers (no discharge_date) classified as חובה
            # even as the real-world clock advances past their hardcoded
            # mandatory_end_date. Otherwise inferred_service_type() flips them to
            # קבע and they become ineligible for every conscript-only duty type.
            # enrolled_at (below) drives active_days; this only corrects service
            # type so those soldiers stay assignable.
            med = extra.get("mandatory_end_date")
            if extra.get("discharge_date") is None and med is not None and med <= seed_today:
                extra["mandatory_end_date"] = seed_today + timedelta(days=365)
            s = Soldier(
                personal_number=pn,
                full_name=name,
                password_hash=hashed,
                role=role,
                hierarchy_node_id=node_id,
                enrolled_at=date(2026, 1, 15),
                must_change_password=False,
                **extra,
            )
            session.add(s)
            session.flush()
            return s

        # ── Soldiers created bottom-up to own their node ids ────────
        all_soldiers = []

        # Admin — department commander (קבע, officer, veteran 15+ years).
        # bootstrap.py may already have created this exact personal_number
        # (same "1000001" convention) before this ran; reuse that row instead
        # of inserting a duplicate.
        admin_attrs = dict(
            is_officer=True,
            rank='אל"מ',
            bahad1_graduate=True,
            enlistment_date=date(2010, 1, 1),
            mandatory_end_date=_mandatory_end(date(2010, 1, 1)),
            discharge_date=date(2035, 1, 1),
            gender="male",
        )
        if admin:
            admin.full_name = "מפמר פסיפס"
            admin.role = "admin"
            admin.hierarchy_node_id = psips.id
            admin.enrolled_at = date(2026, 1, 15)
            for k, v in admin_attrs.items():
                setattr(admin, k, v)
            session.flush()
            s_admin = admin
        else:
            s_admin = make_soldier("1000001", "מפמר פסיפס", "admin", psips.id, **admin_attrs)
        session.flush()
        all_soldiers.append(s_admin)
        psips.commander_id = s_admin.id

        # Branch commanders (קבע, officers)
        # פוקוס — סא"ל (~15 yr career), אלומות — רס"ן (~11 yr career)
        s_focus = make_soldier(
            "2000001",
            "רען פוקוס",
            "commander",
            branches[0].id,
            is_officer=True,
            rank='סא"ל',
            bahad1_graduate=True,
            enlistment_date=date(2011, 1, 1),
            mandatory_end_date=_mandatory_end(date(2011, 1, 1)),
            discharge_date=date(2032, 1, 1),
            gender="male",
        )
        all_soldiers.append(s_focus)
        branches[0].commander_id = s_focus.id

        s_alom = make_soldier(
            "2000002",
            "רען אלומות",
            "commander",
            branches[1].id,
            is_officer=True,
            rank='רס"ן',
            bahad1_graduate=True,
            enlistment_date=date(2015, 1, 1),
            mandatory_end_date=_mandatory_end(date(2015, 1, 1)),
            discharge_date=date(2030, 1, 1),
            gender="male",
        )
        all_soldiers.append(s_alom)
        branches[1].commander_id = s_alom.id

        # Mador commanders — all קבע officers, distributed סרן / רס"ן
        # (name → (personal_number, rank, enlistment, discharge))
        _mador_leader_defs = {
            "מחקר":   ("3000001", "סרן",   date(2021, 1,  1), date(2029, 1,  1)),  # ~5 yr
            "שבירה":  ("3000002", 'רס"ן',  date(2016, 6,  1), date(2030, 6,  1)),  # ~10 yr
            "גוליבר": ("3000003", "סרן",   date(2022, 3,  1), date(2030, 3,  1)),  # ~4 yr
            "אינפרה": ("3000004", "סרן",   date(2020, 8,  1), date(2029, 8,  1)),  # ~6 yr
            "פלאש":   ("3000005", "סרן",   date(2019, 11, 1), date(2028, 11, 1)),  # ~7 yr
            "ספקטרה": ("3000006", 'רס"ן',  date(2014, 4,  1), date(2030, 4,  1)),  # ~12 yr
        }
        for node in focus_groups + alom_groups:
            pn_str, rank, enl, disc = _mador_leader_defs[node.name]
            s = make_soldier(
                pn_str,
                f"רמד {node.name}",
                "commander",
                node.id,
                is_officer=True,
                rank=rank,
                bahad1_graduate=True,
                enlistment_date=enl,
                mandatory_end_date=_mandatory_end(enl, "male"),
                discharge_date=disc,
                gender="male",
            )
            all_soldiers.append(s)
            node.commander_id = s.id

        # Branch duty managers — one per branch, scoped (via DutyManagerScope)
        # to the whole branch subtree, so they can approve swaps/exemptions
        # for anyone under it. NCO קבע, not in the commander chain.
        from app.services.dm_scope import assign_dm_scope

        _branch_dm_defs = {
            "פוקוס":   ("2500001", 'רס"ל', date(2017, 9, 1), date(2029, 9, 1)),  # ~8 yr
            "אלומות":  ("2500002", 'רס"ל', date(2018, 2, 1), date(2029, 2, 1)),  # ~7 yr
        }
        for branch_node in branches:
            pn_str, rank, enl, disc = _branch_dm_defs[branch_node.name]
            s = make_soldier(
                pn_str,
                f"אחראי תורנויות {branch_node.name}",
                "soldier",
                branch_node.id,
                is_officer=False,
                rank=rank,
                bahad1_graduate=False,
                enlistment_date=enl,
                mandatory_end_date=_mandatory_end(enl, "male"),
                discharge_date=disc,
                gender="male",
            )
            all_soldiers.append(s)
            assign_dm_scope(session, soldier_id=s.id, node_id=branch_node.id, actor_id=s_admin.id)

        # Team soldiers (3 per team)
        team_soldiers = []
        team_names_he = {
            "צוות מארס": "מארס",
            "צוות טוקסיק": "טוקסיק",
            "צוות רוקט": "רוקט",
            "צוות ורטיגו": "ורטיגו",
            "צוות פלאש": "פלאש",
            "צוות ריי": "ריי",
            "צוות ספארק": "ספארק",
            "צוות ארק": "ארק",
            "צוות אקסודוס": "אקסודוס",
            "צוות נילוס": "נילוס",
        }
        # Team leader profiles: 3×רסל (NCO קבע), 3×סגם (officer), 3×סגן (officer), 1×סרן (officer)
        # רסל needs 5-8 yr career; סגם/סגן 2-5 yr; סרן 5-7 yr
        # Entries match all_teams order: מארס, טוקסיק, רוקט, ורטיגו, פלאש, ריי, ספארק, ארק, אקסודוס, נילוס
        # (rank, is_officer, enl_year, enl_month, disc_year, disc_month)  disc=None → חובה
        _team_leader_profiles = [
            ("רסל",  False, 2018, 3,  2030, 6),  # מארס    - NCO קבע ~8 yr
            ("רסל",  False, 2019, 7,  2031, 6),  # טוקסיק  - NCO קבע ~7 yr
            ("רסל",  False, 2020, 1,  2031, 6),  # רוקט    - NCO קבע ~6 yr
            ("סגם",  True,  2022, 8,  2029, 8),  # ורטיגו  - officer קבע ~4 yr
            ("סגם",  True,  2021, 5,  2028, 5),  # פלאש    - officer קבע ~5 yr
            ("סגם",  True,  2024, 1,  None, None),# ריי    - officer חובה, end Sep 2026
            ("סגן",  True,  2024, 2,  None, None),# ספארק  - officer חובה, end Oct 2026
            ("סגן",  True,  2021, 9,  2029, 9),  # ארק     - officer קבע ~5 yr
            ("סגן",  True,  2022, 3,  2029, 3),  # אקסודוס - officer קבע ~4 yr
            ("סרן",  True,  2020, 3,  2028, 3),  # נילוס   - captain officer קבע ~6 yr
        ]
        for team_idx, team in enumerate(all_teams):
            short = team_names_he[team.name]
            lrank, l_is_off, ley, lem, ldy, ldm = _team_leader_profiles[team_idx]
            l_enl = date(ley, lem, 1)
            l_disc = date(ldy, ldm, 1) if ldy else None
            pn = next_pn()
            s = make_soldier(
                pn,
                f"רשצ {short}",
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
            team_soldiers.append(s)
            team.commander_id = s.id
            # 5 members per team: 3 enlisted חובה, 1 enlisted קבע, 1 officer חובה
            _team_profiles = [
                # (enl_year, enl_month, rank, is_officer, discharge_year, gender)
                # Female: mandatory service = 24 months; enlist Aug 2024 → end Aug 2026 (still active)
                (2024, 8, "סמל", False, None, "female"),  # enlisted חובה late-service, ~22 months
                (2025, 3, 'רב"ט', False, None, "male"),   # enlisted חובה mid-service, ~15 months
                (2026, 1, "טוראי", False, None, "male"),   # enlisted חובה fresh, ~5 months
                (2019, 6, "רסר", False, 2035, "male"),     # enlisted קבע, ~7 yrs → רסר
                (2024, 3, "סגן", True, None, "male"),      # officer חובה: enlisted → bahad1 → סגן ~month 12, now ~27 months service
            ]
            for i, (ey, em, rank, is_off, dy, g) in enumerate(_team_profiles):
                pn = next_pn()
                enl = date(ey, em, 1)
                disc = date(dy, 6, 1) if dy else None
                s = make_soldier(
                    pn,
                    f"{short} {i + 1}",
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
                team_soldiers.append(s)

        all_soldiers += team_soldiers

        # Mador soldiers for groups without teams (15 per mador)
        # Mix: 8 enlisted חובה, 3 enlisted קבע, 2 officer חובה, 1 officer קבע, 1 enlisted חובה fresh
        _mador_profiles = [
            # (enl_year, enl_month, rank, is_officer, discharge_year, gender)
            (2023, 8,  "סמל",   False, None, "male"),    #  0 חובה senior, ~34 months → סמל ✓
            (2024, 8,  "סמל",   False, None, "female"),  #  1 חובה, ~22 months → סמל; end Aug 2026 ✓
            (2024, 6,  'רב"ט',  False, None, "male"),    #  2 חובה, ~24 months → סמל/רב"ט border, רב"ט ok
            (2024, 11, 'רב"ט',  False, None, "male"),    #  3 חובה, ~19 months → רב"ט ✓
            (2025, 3,  'רב"ט',  False, None, "female"),  #  4 חובה, ~15 months; end Mar 2027 → רב"ט ✓
            (2025, 7,  "טוראי", False, None, "male"),    #  5 חובה, ~11 months → טוראי/רב"ט border
            (2025, 11, "טוראי", False, None, "male"),    #  6 חובה, ~7 months → טוראי ✓
            (2026, 2,  "טוראי", False, None, "female"),  #  7 חובה fresh, ~4 months; end Feb 2028 → טוראי ✓
            (2018, 4,  "רסב",   False, 2035, "male"),    #  8 קבע, ~8 yrs → רסב ✓
            (2019, 8,  "רסר",   False, 2034, "male"),    #  9 קבע, ~7 yrs → רסר ✓
            (2020, 2,  "רסר",   False, 2033, "female"),  # 10 קבע female, ~6 yrs → רסר ✓
            (2023, 10, "סגן",   True,  None, "male"),    # 11 חובה officer: enlisted Oct 2023 → bahad1 Sep 2024 → סגן; end Jun 2026 ✓
            (2025, 3,  "סגן",   True,  None, "female"),  # 12 חובה officer female: bahad1 Feb 2026 → סגן; end Mar 2027 ✓
            (2017, 1,  "סרן",   True,  2032, "male"),    # 13 קבע officer, ~9 yrs → סרן ✓
            (2026, 3,  "טוראי", False, None, "male"),    # 14 חובה very fresh, ~3 months → טוראי ✓
        ]
        mador_soldiers = []
        for gnode, gshort in [("אינפרה", "אינפרה"), ("פלאש", "פלאש"), ("ספקטרה", "ספקטרה")]:
            node = [n for n in alom_groups if n.name == gnode][0]
            for i, (ey, em, rank, is_off, dy, g) in enumerate(_mador_profiles):
                pn = next_pn()
                enl = date(ey, em, 1)
                disc = date(dy, 1, 1) if dy else None
                s = make_soldier(
                    pn,
                    f"{gshort} {i + 1}",
                    "soldier",
                    node.id,
                    is_officer=is_off,
                    rank=rank,
                    enlistment_date=enl,
                    mandatory_end_date=_mandatory_end(enl, g),
                    discharge_date=disc,
                    bahad1_graduate=is_off,
                    gender=g,
                )
                mador_soldiers.append(s)

        all_soldiers += mador_soldiers

        # ── Duty types ──────────────────────────────────────────────
        # (name, score_per_day, description, requirements, reserve_ratio, reserve_minimum,
        #  is_external, contact_name, contact_phone, start_time, end_time, instructions)
        dt_defs = [
            (
                "שמירות",
                Decimal("1.125"),
                "שמירה בבסיס — כיסוי שער, מוצב ותצפיות פנים-בסיסיות",
                {"officers_allowed": False, "allowed_service_types": ["חובה", "קבע"]},
                Decimal("0.300"),
                3,
                False,
                "קצין שמירות",
                "050-1234567",
                time(7, 0),
                time(7, 0),
                "להתייצב בנקודת ריכוז שמירות ב-07:00 עם ציוד שלם. לקבל תדריך מקצין השמירה. לדווח על כל חריגה מיידית.",
            ),
            (
                "ליווים",
                Decimal("1.00"),
                "ליווי אסירים, כלי רכב ומטענים מחוץ לבסיס",
                {"officers_allowed": False, "allowed_service_types": ["חובה", "קבע"]},
                Decimal("0.200"),
                2,
                False,
                "מפקד הליווי",
                "050-2345678",
                time(7, 0),
                time(17, 0),
                "להגיע לנקודת הריכוז ב-07:00 עם ציוד אישי מלא ונשק. לדווח למפקד הליווי עם ההגעה. שהייה מחוץ לבסיס לכל אורך המשמרת.",
            ),
            (
                "משמרת לילה",
                Decimal("1.25"),
                "שמירה לילית בבסיס — כיסוי שער ותצפיות בשעות החשכה",
                {"officers_allowed": False, "allowed_service_types": ["חובה", "קבע"]},
                Decimal("0.300"),
                2,
                False,
                "קצין שמירות",
                "050-2456789",
                time(20, 0),
                time(8, 0),
                "להתייצב בנקודת ריכוז השמירות ב-20:00 עם ציוד שלם. לקבל תדריך מקצין השמירה. לדווח על כל חריגה מיידית עד ההחלפה בבוקר.",
            ),
            (
                'עבודות רס"ר',
                Decimal("1.00"),
                'עבודות רס"ר שוטפות — ניקיון, אחזקה, הפצה',
                {"officers_allowed": False, "allowed_service_types": ["חובה", "קבע"]},
                Decimal("0.250"),
                2,
                False,
                'רס"ר הבסיס',
                "050-3456789",
                time(8, 0),
                time(16, 0),
                'להתייצב אצל הרס"ר ב-08:00. לקבל משימות יומיות. לדווח על סיום כל משימה.',
            ),
            (
                'אבט"ש',
                Decimal(9) / Decimal(7),
                "אבטחה שוטפת — סיורים, בדיקות ואבטחת מתקנים",
                {"officers_allowed": False, "allowed_service_types": ["חובה", "קבע"]},
                Decimal("0.350"),
                4,
                True,
                "קצין ביטחון",
                "050-4567890",
                time(6, 0),
                time(6, 0),
                'להתייצב בחדר הביטחון. לקבל תדריך מקצין האבט"ש. מחייב ערנות מלאה לאורך כל המשמרת.',
            ),
            (
                'הגנ"ש',
                Decimal(9) / Decimal(7),
                'הגנה"ש — הגנה על שטח ומתקנים רגישים, לקצינים בלבד',
                {"enlisted_allowed": False},
                Decimal("0.400"),
                2,
                True,
                "קצין מבצעים",
                "050-5678901",
                time(7, 0),
                time(19, 0),
                'מחייב bahad1. להתייצב עם ציוד אישי מלא. לתאם מראש עם קצין המבצעים. אחריות על קו ההגנה.',
            ),
            (
                "קצין תורן",
                Decimal("1.125"),
                "קצין תורן בבסיס — אחראי על סדר, כוח אדם ואירועים",
                {"enlisted_allowed": False, "allowed_service_types": ["חובה", "קבע"]},
                Decimal("0.500"),
                1,
                False,
                "מפקד הבסיס",
                "050-6789012",
                time(8, 0),
                time(8, 0),
                "שמירה על סדר בבסיס לאורך 24 שעות. אחריות על דיווח אירועים חריגים. להעביר תדריך לקצין תורן מחליף.",
            ),
            (
                "מפקד תורן",
                Decimal("1.125"),
                "מפקד תורן בבסיס — פיקוד עליון על כל פעילות השמירה",
                {
                    "enlisted_allowed": False,
                    "allowed_service_types": ["חובה", "קבע"],
                    "requires_bahad1": True,
                },
                Decimal("0.500"),
                1,
                False,
                "מפקד הבסיס",
                "050-7890123",
                time(8, 0),
                time(8, 0),
                "מחייב bahad1. אחראי על מהלך כל הבסיס. לתדרך קצין תורן עם ההחלפה. יש להישאר זמין בכל עת.",
            ),
            (
                'קצין מלווה אבט"ש',
                Decimal(9) / Decimal(7),
                'ליווי קצינאי לסיור האבט"ש, כולל יציאה מחוץ לבסיס',
                {"enlisted_allowed": False, "allowed_service_types": ["חובה", "קבע"]},
                Decimal("0.300"),
                1,
                True,
                'קצין אבט"ש',
                "050-8901234",
                time(6, 0),
                time(18, 0),
                'ליווי פיקודי לסיור האבט"ש. ציוד מלא ונשק. לתאם עם קצין הביטחון לפני כל יציאה.',
            ),
            (
                "אבות בית",
                Decimal("1.00"),
                "תחזוקה שוטפת של מבני הבסיס ותשתיות",
                {"officers_allowed": False, "allowed_service_types": ["חובה", "קבע"]},
                Decimal("0.150"),
                1,
                False,
                "אב בית ראשי",
                "050-9012345",
                time(7, 0),
                time(15, 0),
                "תחזוקה שוטפת של מבנים וציוד. לדווח על ליקויים לאב הבית הראשי. כולל עבודות ניקיון ואחזקה.",
            ),
            (
                'עבודות רס"ר בינוי',
                Decimal("1.00"),
                'עבודות בינוי ושיפוץ בפיקוח הרס"ר',
                {"officers_allowed": False, "allowed_service_types": ["חובה", "קבע"]},
                Decimal("0.150"),
                1,
                False,
                'רס"ר בינוי',
                "050-0123456",
                time(7, 30),
                time(15, 30),
                'עבודות בינוי ושיפוץ בבסיס. יש להגיע עם ציוד עבודה מתאים. לדווח לרס"ר הבינוי על התקדמות.',
            ),
        ]
        duty_types = []
        for name, spd, desc, reqs, rr, rmin, is_ext, cname, cphone, stime, etime, instrs in dt_defs:
            dt = DutyType(
                name=name,
                score_per_day=spd,
                description=desc,
                requirements=reqs,
                reserve_ratio=rr,
                reserve_minimum=rmin,
                is_external=is_ext,
                contact_name=cname,
                contact_phone=cphone,
                start_time=stime,
                end_time=etime,
                instructions=instrs,
            )
            session.add(dt)
            session.flush()
            duty_types.append(dt)

        # ── Duty locations ──────────────────────────────────────────
        loc_defs = [
            ("בסיס מרכז", "בסיס מרכז"),
            ("בסיס צפון", "בסיס צפון"),
            ("בסיס דרום", "בסיס דרום"),
            ("מוצב פיקוד", "מוצב פיקוד קדמי"),
        ]
        locations = []
        for name, base in loc_defs:
            loc = DutyLocation(name=name, base=base)
            session.add(loc)
            session.flush()
            locations.append(loc)

        # ── Exemption types ─────────────────────────────────────────
        et_defs = [
            ("פטור שמירות", "פטור מכל סוגי השמירות", False),
            ("פטור רפואי", "פטור רפואי זמני", False),
            ("פטור משפחתי", "פטור עקב סיבה משפחתית", False),
            ("פטור אימונים", "פטור עקב אימונים", False),
            ("פטור נפשי", "פטור נפשי זמני", False),
            ("פטור גלובלי", "פטור מכל סוגי התורנויות", True),
        ]
        exemption_types = []
        for ename, edesc, eglobal in et_defs:
            et = ExemptionType(name=ename, description=edesc, is_global=eglobal)
            session.add(et)
            session.flush()
            exemption_types.append(et)

        # ── Exemption → Duty mappings ──────────────────────────────
        # Indices: 0=שמירות,1=ליווים,2=עבודות רס"ר,3=אבט"ש,4=הגנ"ש,5=קצין תורן,6=מפקד תורן,7=קצין מלווה אבט"ש,8=אבות בית,9=עבודות רס"ר בינוי
        mappings = [
            (0, [0, 1, 2]),  # פטור שמירות ← שמירות, ליווים, עבודות רס"ר
            (
                1,
                [0, 1, 3, 4, 8, 9],
            ),  # פטור רפואי ← שמירות, ליווים, אבט"ש, הגנ"ש, אבות בית, עבודות רס"ר בינוי
            (
                2,
                [0, 1, 2, 8, 9],
            ),  # פטור משפחתי ← שמירות, ליווים, עבודות רס"ר, אבות בית, עבודות רס"ר בינוי
            (3, [3, 4]),  # פטור אימונים ← אבט"ש, הגנ"ש
            (4, [0, 1, 3, 8]),  # פטור נפשי ← שמירות, ליווים, אבט"ש, אבות בית
        ]
        for et_idx, dt_idxs in mappings:
            for dt_idx in dt_idxs:
                session.add(
                    ExemptionDutyTypeMap(
                        exemption_type_id=exemption_types[et_idx].id,
                        duty_type_id=duty_types[dt_idx].id,
                    )
                )

        from datetime import timedelta
        from random import choice, randint

        today = date.today()

        # ── Personal constraints ────────────────────────────────────
        constraint_reasons = [
            "בדיקה רפואית",
            "יום הולדת",
            "חתונה במשפחה",
            "מבחן באוניברסיטה",
            "טיפול שיניים",
            "אירוע משפחתי",
            "ראיון עבודה",
            "קורס הכנה",
            "יום כיף",
            "שמירת שבת",
        ]
        if not fair:
            for i, s in enumerate(all_soldiers[:15]):
                offset = i % 30
                pc = PersonalConstraint(
                    soldier_id=s.id,
                    start_date=today + timedelta(days=offset),
                    end_date=today + timedelta(days=offset + randint(0, 2)),
                    reason=constraint_reasons[i % len(constraint_reasons)],
                    status=choice(["pending_commander", "pending_duty_manager", "approved", "approved", "rejected"]),
                    decided_by=choice(
                        [s_admin.id, s_focus.id, s_alom.id]
                        + [
                            session.query(Soldier).filter(Soldier.personal_number == pn).first().id
                            for pn in ["3000001", "3000002", "3000003", "3000004", "3000005", "3000006"]
                        ]
                    ),
                )
                session.add(pc)

        # ── Soldier exemptions ──────────────────────────────────────
        # All exemptions must start on or before today so load_soldier_inputs
        # (which checks start_date <= as_of) treats them as active.
        # Types cycle deterministically to keep seeding stable across runs.
        exemption_reasons = [
            "פטור זמני עקב ניתוח",
            "פטור עקב מילואים",
            "פטור עקב לימודים",
            "פטור עקב אבל במשפחה",
            "פטור עקב תעסוקה טיפולית",
            "פטור עקב הריון",
            "פטור עקב קורס מקצועי",
            "פטור זמני - החלמה",
        ]
        if not fair:
            # Cycle through the 5 non-global exemption types (indices 0-4)
            _exemption_cycle = [exemption_types[i % 5] for i in range(12)]
            for i, s in enumerate(all_soldiers[:12]):
                days_ago = i % 7  # started 0-6 days ago → already active
                se = SoldierExemption(
                    soldier_id=s.id,
                    exemption_type_id=_exemption_cycle[i].id,
                    start_date=today - timedelta(days=days_ago),
                    end_date=today + timedelta(days=14),
                    reason=exemption_reasons[i % len(exemption_reasons)],
                    granted_by=s_admin.id,
                )
                session.add(se)

            # Grant the global exemption (index 5) to one soldier
            global_et = next(et for et in exemption_types if et.is_global)
            session.add(
                SoldierExemption(
                    soldier_id=mador_soldiers[0].id,
                    exemption_type_id=global_et.id,
                    start_date=today - timedelta(days=10),
                    end_date=today + timedelta(days=20),
                    reason="פטור כללי זמני",
                    granted_by=s_admin.id,
                )
            )

            # Grant ספקטרה 8 an active פטור שמירות so the eligibility
            # distribution pie chart shows variance within the ספקטרה group.
            # mador_soldiers layout: אינפרה 0-14, פלאש 15-29, ספקטרה 30-44.
            # "ספקטרה 8" = the soldier named "ספקטרה 8" (i+1=8 → i=7) → index 37.
            spektra_8 = mador_soldiers[37]
            session.add(
                SoldierExemption(
                    soldier_id=spektra_8.id,
                    exemption_type_id=exemption_types[0].id,  # פטור שמירות
                    start_date=today - timedelta(days=30),
                    end_date=today + timedelta(days=60),
                    reason="פטור שמירות",
                    granted_by=s_admin.id,
                )
            )

        # ── Score adjustments ───────────────────────────────────────
        sa_defs = [
            ("5000001", Decimal("10.00"), "תוספת שמירות חודשית"),
            ("5000004", Decimal("8.00"), "תוספת ליווי"),
            ("5000006", Decimal("-3.00"), "הפחתה על אי התייצבות"),
            ("4000003", Decimal("15.00"), 'תוספת עבודות רס"ר'),
            ("4000007", Decimal("-5.00"), "הפחתה על איחור"),
        ]
        for pn, delta, reason in sa_defs:
            s_to_adjust = session.query(Soldier).filter(Soldier.personal_number == pn).first()
            if s_to_adjust:
                sa = ScoreAdjustment(
                    soldier_id=s_to_adjust.id,
                    delta=delta,
                    reason=reason,
                    created_by=s_admin.id,
                )
                session.add(sa)

        # ── Invite code ────────────────────────────────────────────
        if not session.query(RegistrationInviteCode).first():
            create_invite_code(session, uses_left=10, actor_id=s_admin.id)

        # ── Unassigned soldiers + enrollment requests ───────────────
        if not session.query(Soldier).filter(Soldier.personal_number == "9000001").first():
            unassigned = []
            for i, pn in enumerate(["9000001", "9000002", "9000003", "9000004"]):
                s = make_soldier(
                    pn,
                    f"חייל ממתין {i + 1}",
                    "soldier",
                    None,
                    enlistment_date=date(2025, 6, 1),
                    mandatory_end_date=_mandatory_end(date(2025, 6, 1)),
                    gender="male",
                )
                unassigned.append(s)

            node_mars = next(n for n in all_teams if n.name == "צוות מארס")
            node_mehkar = next(n for n in focus_groups if n.name == "מחקר")
            node_rei = next(n for n in all_teams if n.name == "צוות ריי")
            node_ark = next(n for n in all_teams if n.name == "צוות ארק")

            for soldier, node_id, status, decided_by in [
                (unassigned[0], node_mars.id, "pending", None),
                (unassigned[1], node_mehkar.id, "pending", None),
                (unassigned[2], node_rei.id, "approved", s_admin.id),
                (unassigned[3], node_ark.id, "rejected", s_admin.id),
            ]:
                session.add(SoldierEnrollmentRequest(
                    soldier_id=soldier.id,
                    requested_node_id=node_id,
                    status=status,
                    decided_by=decided_by,
                ))

        # ── Exemption requests (pending, from soldiers) ────────────
        er_reasons = [
            ("מבקש פטור משמירות בגלל ניתוח", 0),
            ("זקוק לפטור רפואי זמני לבדיקות", 1),
            ("פטור בגלל חתונה במשפחה", 2),
            ("תקופת מבחנים באוניברסיטה", 3),
            ("מצב נפשי לא טוב מבקש הקלה", 4),
            ("צריך ליווי לאבא חולה", 2),
        ]
        for i, (reason, et_idx) in enumerate(er_reasons):
            s = all_soldiers[-(i + 3)]
            er = ExemptionRequest(
                soldier_id=s.id,
                exemption_type_id=exemption_types[et_idx].id,
                start_date=today + timedelta(days=i * 3),
                end_date=today + timedelta(days=i * 3 + randint(2, 7)),
                reason=reason,
                status="pending",
            )
            session.add(er)

        # ── One approved and one rejected request for variety ───────
        er_approved = ExemptionRequest(
            soldier_id=all_soldiers[-8].id,
            exemption_type_id=exemption_types[0].id,
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=5),
            reason="פטור לשמירות - אושר",
            status="approved",
            decided_by=s_admin.id,
            decision_note="מאושר לשבוע",
        )
        session.add(er_approved)
        if not fair:
            # Mirror the approved request as an actual SoldierExemption so the exemptions tab shows it.
            session.add(SoldierExemption(
                soldier_id=all_soldiers[-8].id,
                exemption_type_id=exemption_types[0].id,
                start_date=today - timedelta(days=5),
                end_date=today + timedelta(days=5),
                reason="פטור לשמירות - אושר",
                granted_by=s_admin.id,
            ))

        er_rejected = ExemptionRequest(
            soldier_id=all_soldiers[-9].id,
            exemption_type_id=exemption_types[2].id,
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=15),
            reason="פטור משפחתי - נדחה",
            status="rejected",
            decided_by=s_admin.id,
            decision_note="אין מספיק סיבה",
        )
        session.add(er_rejected)

        # ── Profile field update requests ───────────────────────────
        field_updates = [
            # (soldier index offset, field, new_value, status, decision_note)
            (0, "last_mitvahim_date", (today - timedelta(days=30)).isoformat(), "pending", None),
            (3, "gender", "female", "pending", None),
            (7, "last_alal_date", (today - timedelta(days=14)).isoformat(), "pending", None),
            (2, "gender", "male", "approved", "מאושר"),
            (
                5,
                "last_mitvahim_date",
                (today - timedelta(days=21)).isoformat(),
                "approved",
                "מאושר",
            ),
            (1, "last_alal_date", (today - timedelta(days=7)).isoformat(), "rejected", "לא נדרש"),
            (4, "gender", "male", "rejected", "אין צורך בשינוי"),
        ]
        fu_count = 0
        for offset_idx, field, value, status, note in field_updates:
            soldier = all_soldiers[offset_idx % len(all_soldiers)]
            decided_by = s_admin.id if status != "pending" else None
            decided_at = today if status != "pending" else None
            session.add(
                SoldierFieldUpdate(
                    soldier_id=soldier.id,
                    field_name=field,
                    new_value=value,
                    status=status,
                    decided_by=decided_by,
                    decided_at=decided_at,
                    decision_note=note,
                )
            )
            fu_count += 1

        # ── Duty shifts ──────────────────────────────────────────────
        from datetime import timedelta
        import itertools

        today = date.today()

        def _next_weekday(from_date: date, target: int) -> date:
            days = (target - from_date.weekday()) % 7
            return from_date + timedelta(days=7 if days == 0 else days)

        def _duty_hours(dt: DutyType) -> tuple[str, str]:
            """Hours are a feature of the duty type: read its own configured
            start_time/end_time (set in dt_defs above) rather than defaulting
            to a full calendar day."""
            start_time = dt.start_time.strftime("%H:%M") if dt.start_time else "00:00"
            end_time = dt.end_time.strftime("%H:%M") if dt.end_time else "23:59"
            return start_time, end_time

        def _single_day_shift_span(day: date, dt: DutyType) -> tuple[date, date, str, str]:
            """A single-day duty slot for `dt`. When the duty type's own
            hours cross midnight (e.g. an overnight ליווים shift), the span
            covers two calendar days so the night is fully represented."""
            start_time, end_time = _duty_hours(dt)
            crosses_midnight = end_time <= start_time
            end_date = day + timedelta(days=2 if crosses_midnight else 1)
            return day, end_date, start_time, end_time

        next_mon = _next_weekday(today, 0)
        next_thu = _next_weekday(today, 3)
        next_sun = _next_weekday(today, 6)

        loc_cycle = itertools.cycle(locations)
        dt_by_name = {dt.name: dt for dt in duty_types}
        shifts_created = []
        shift_assignments = 0

        # 1. שמירות — Mon-to-Mon, 8 weeks, 10 primaries
        dt = dt_by_name["שמירות"]
        for w in range(8):
            start = next_mon + timedelta(weeks=w)
            start_time, end_time = _duty_hours(dt)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                start_time=start_time,
                end_time=end_time,
                required_count=10,
                notes="שמירות שבועית",
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 2. אבט"ש — Mon-to-Mon, 8 weeks
        dt = dt_by_name['אבט"ש']
        for w in range(8):
            start = next_mon + timedelta(weeks=w)
            start_time, end_time = _duty_hours(dt)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                start_time=start_time,
                end_time=end_time,
                required_count=2,
                notes='אבט"ש שבועית',
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 3. הגנ"ש — Thu-to-Thu, 8 weeks
        dt = dt_by_name['הגנ"ש']
        for w in range(8):
            start = next_thu + timedelta(weeks=w)
            start_time, end_time = _duty_hours(dt)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                start_time=start_time,
                end_time=end_time,
                required_count=2,
                notes='הגנ"ש שבועית',
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 4. ליווים — Sun-Thu single days, 8 weeks
        dt = dt_by_name["ליווים"]
        for w in range(8):
            for d in range(5):
                day = next_sun + timedelta(weeks=w, days=d)
                start_date, end_date, start_time, end_time = _single_day_shift_span(day, dt)
                s = DutyShift(
                    duty_type_id=dt.id,
                    duty_location_id=next(loc_cycle).id,
                    start_date=start_date,
                    end_date=end_date,
                    start_time=start_time,
                    end_time=end_time,
                    required_count=2,
                    notes="ליווי יומי",
                    created_by=s_admin.id,
                )
                session.add(s)
                session.flush()
                shifts_created.append(s)

        # 5. עבודות רס"ר — Sun-Thu single days, 8 weeks
        dt = dt_by_name['עבודות רס"ר']
        for w in range(8):
            for d in range(5):
                day = next_sun + timedelta(weeks=w, days=d)
                start_date, end_date, start_time, end_time = _single_day_shift_span(day, dt)
                s = DutyShift(
                    duty_type_id=dt.id,
                    duty_location_id=next(loc_cycle).id,
                    start_date=start_date,
                    end_date=end_date,
                    start_time=start_time,
                    end_time=end_time,
                    required_count=2,
                    notes='עבודות רס"ר יומיות',
                    created_by=s_admin.id,
                )
                session.add(s)
                session.flush()
                shifts_created.append(s)

        # 6. קצין תורן — Mon-to-Mon, 8 weeks
        dt = dt_by_name["קצין תורן"]
        for w in range(8):
            start = next_mon + timedelta(weeks=w)
            start_time, end_time = _duty_hours(dt)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                start_time=start_time,
                end_time=end_time,
                required_count=1,
                notes="קצין תורן שבועי",
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 7. מפקד תורן — Mon-to-Mon, 8 weeks
        dt = dt_by_name["מפקד תורן"]
        for w in range(8):
            start = next_mon + timedelta(weeks=w)
            start_time, end_time = _duty_hours(dt)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                start_time=start_time,
                end_time=end_time,
                required_count=1,
                notes="מפקד תורן שבועי",
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 8. קצין מלווה אבט"ש — Mon-to-Mon, 8 weeks
        dt = dt_by_name['קצין מלווה אבט"ש']
        for w in range(8):
            start = next_mon + timedelta(weeks=w)
            start_time, end_time = _duty_hours(dt)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                start_time=start_time,
                end_time=end_time,
                required_count=1,
                notes='קצין מלווה אבט"ש שבועי',
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 9. אבות בית — Sun-Thu single days, 8 weeks
        dt = dt_by_name["אבות בית"]
        for w in range(8):
            for d in range(5):
                day = next_sun + timedelta(weeks=w, days=d)
                start_date, end_date, start_time, end_time = _single_day_shift_span(day, dt)
                s = DutyShift(
                    duty_type_id=dt.id,
                    duty_location_id=next(loc_cycle).id,
                    start_date=start_date,
                    end_date=end_date,
                    start_time=start_time,
                    end_time=end_time,
                    required_count=2,
                    notes="אבות בית יומי",
                    created_by=s_admin.id,
                )
                session.add(s)
                session.flush()
                shifts_created.append(s)

        # 10. עבודות רס"ר בינוי — Sun-Thu single days, 8 weeks
        dt = dt_by_name['עבודות רס"ר בינוי']
        for w in range(8):
            for d in range(5):
                day = next_sun + timedelta(weeks=w, days=d)
                start_date, end_date, start_time, end_time = _single_day_shift_span(day, dt)
                s = DutyShift(
                    duty_type_id=dt.id,
                    duty_location_id=next(loc_cycle).id,
                    start_date=start_date,
                    end_date=end_date,
                    start_time=start_time,
                    end_time=end_time,
                    required_count=2,
                    notes='עבודות רס"ר בינוי יומיות',
                    created_by=s_admin.id,
                )
                session.add(s)
                session.flush()
                shifts_created.append(s)

        # 11. משמרת לילה — Sun-Thu single nights, 8 weeks
        dt = dt_by_name["משמרת לילה"]
        for w in range(8):
            for d in range(5):
                day = next_sun + timedelta(weeks=w, days=d)
                start_date, end_date, start_time, end_time = _single_day_shift_span(day, dt)
                s = DutyShift(
                    duty_type_id=dt.id,
                    duty_location_id=next(loc_cycle).id,
                    start_date=start_date,
                    end_date=end_date,
                    start_time=start_time,
                    end_time=end_time,
                    required_count=2,
                    notes="משמרת לילה יומית",
                    created_by=s_admin.id,
                )
                session.add(s)
                session.flush()
                shifts_created.append(s)

        # ── Assign soldiers to shifts (only with --with-assignments) ──
        created_assignments = []
        if with_assignments:
            enlisted = [s for s in all_soldiers if not s.is_officer]
            officer_soldiers = [s for s in all_soldiers if s.is_officer]
            dt_by_id_map = {dt.id: dt for dt in duty_types}

            for i, shift in enumerate(shifts_created):
                dt_obj = dt_by_id_map[shift.duty_type_id]
                reqs = dt_obj.requirements or {}
                if reqs.get("enlisted_allowed") is False:
                    pool = officer_soldiers
                elif reqs.get("officers_allowed") is False:
                    pool = enlisted
                else:
                    pool = enlisted  # mixed: use enlisted for variety

                # Fill large headcount shifts fully; others assign up to 2
                assign_count = shift.required_count if shift.required_count >= 5 else min(shift.required_count, 2)

                for k in range(assign_count):
                    soldier = pool[(i * 3 + k) % len(pool)]
                    da = DutyAssignment(
                        soldier_id=soldier.id,
                        duty_type_id=shift.duty_type_id,
                        duty_location_id=shift.duty_location_id,
                        start_date=shift.start_date,
                        end_date=shift.end_date,
                        duty_shift_id=shift.id,
                        status="published",
                        created_by=s_admin.id,
                    )
                    session.add(da)
                    session.flush()
                    created_assignments.append(da)
                    shift_assignments += 1

            # ── Reserve assignments ──────────────────────────────────────
            dt_by_id = {dt.id: dt for dt in duty_types}
            reserve_count_total = 0
            for i, shift in enumerate(shifts_created):
                dt = dt_by_id[shift.duty_type_id]
                rcount = max(
                    int(dt.reserve_minimum or 0),
                    math.ceil(shift.required_count * float(dt.reserve_ratio or 0)),
                )
                # Cap reserves at number of primaries assigned to this shift
                primary_count = sum(
                    1
                    for a in created_assignments
                    if a.duty_shift_id == shift.id and not a.is_reserve
                )
                rcount = min(rcount, primary_count)
                if rcount == 0:
                    continue
                r_reqs = dt_by_id[shift.duty_type_id].requirements or {}
                pool = officer_soldiers if r_reqs.get("enlisted_allowed") is False else enlisted
                for k in range(rcount):
                    idx = (i * 7 + k * 13 + 5) % len(pool)
                    soldier = pool[idx]
                    tries = 0
                    while tries < len(pool) and any(
                        a.soldier_id == soldier.id and a.duty_shift_id == shift.id
                        for a in created_assignments
                    ):
                        tries += 1
                        soldier = pool[(idx + tries) % len(pool)]
                    da = DutyAssignment(
                        soldier_id=soldier.id,
                        duty_type_id=shift.duty_type_id,
                        duty_location_id=shift.duty_location_id,
                        start_date=shift.start_date,
                        end_date=shift.end_date,
                        duty_shift_id=shift.id,
                        status="published",
                        created_by=s_admin.id,
                        is_reserve=True,
                    )
                    session.add(da)
                    session.flush()
                    created_assignments.append(da)
                    reserve_count_total += 1

            # ── Link reserves to primaries ──────────────────────────────
            hier_nodes = session.query(HierarchyNode).all()
            hierarchy_parent = {n.id: n.parent_id for n in hier_nodes}
            soldiers = session.query(Soldier).filter(Soldier.left_at.is_(None)).all()
            soldier_node = {s.id: s.hierarchy_node_id for s in soldiers if s.hierarchy_node_id}
            assignments_by_shift: dict[uuid.UUID, list[DutyAssignment]] = {}
            for a in created_assignments:
                assignments_by_shift.setdefault(a.duty_shift_id, []).append(a)
            links_created = 0
            for sa_group in assignments_by_shift.values():
                primaries = [a for a in sa_group if not a.is_reserve]
                reserves = [a for a in sa_group if a.is_reserve]
                if not primaries or not reserves:
                    continue
                for i, primary in enumerate(primaries):
                    reserve = reserves[i % len(reserves)]
                    p_node = soldier_node.get(primary.soldier_id)
                    r_node = soldier_node.get(reserve.soldier_id)
                    if p_node and r_node:
                        dist = _hierarchy_distance(p_node, r_node, hierarchy_parent)
                    else:
                        dist = 10
                    session.add(
                        DutyReserveLink(
                            primary_assignment_id=primary.id,
                            reserve_assignment_id=reserve.id,
                            hierarchy_distance=dist,
                        )
                    )
                    links_created += 1

            # ── Swap requests ────────────────────────────────────────
            today = date.today()
            future_assignments = [
                a for a in created_assignments if a.start_date >= today - timedelta(days=1)
            ]

            def _other(exclude_id):
                return session.query(Soldier).filter(Soldier.id != exclude_id).first()

            def _make_swap_request(*, assignment, requesting_soldier_id, status, reason, extra):
                """Build a SwapRequest (+ single SwapCandidate, if the old
                fixture implied one) from the pre-unified-swap-requests shape
                these fixtures used to encode directly on SwapRequest
                (target_soldier_id / covering_soldier_id / covering_side_approved
                / offered_assignment_ids, plus a "pending_approval" status).
                `status="pending_approval"` maps to the new `SwapRequest.status
                == "open"` with a live SwapCandidate representing the covering
                soldier; `"applied"` gets a matching applied SwapCandidate."""
                target_soldier_id = extra.get("target_soldier_id")
                covering_soldier_id = extra.get("covering_soldier_id")
                requester_side_approved = extra.get("requester_side_approved")
                covering_side_approved = extra.get("covering_side_approved")
                offered_assignment_ids = extra.get("offered_assignment_ids")

                req_status = "open" if status == "pending_approval" else status
                candidate_soldier_id = covering_soldier_id or target_soldier_id

                req = SwapRequest(
                    duty_assignment_id=assignment.id,
                    duty_date=assignment.start_date,
                    requesting_soldier_id=requesting_soldier_id,
                    status=req_status,
                    reason=reason,
                    open_to_marketplace=not candidate_soldier_id,
                    requester_side_approved=requester_side_approved,
                )
                session.add(req)
                session.flush()

                if candidate_soldier_id:
                    if req_status == "applied":
                        candidate_status = "applied"
                    elif covering_side_approved:
                        candidate_status = "accepted"
                    else:
                        candidate_status = "pending"
                    candidate = SwapCandidate(
                        swap_request_id=req.id,
                        soldier_id=candidate_soldier_id,
                        source="invited" if target_soldier_id else "marketplace",
                        status=candidate_status,
                        soldier_side_approved=covering_side_approved,
                    )
                    if offered_assignment_ids:
                        candidate.offered_assignment_ids = offered_assignment_ids
                    session.add(candidate)
                return req

            if len(future_assignments) >= 20:

                swap_reasons = [
                    "בקשת החלפה לצורכי בדיקה",
                    "אירוע משפחתי",
                    "מבחן באוניברסיטה",
                    "טיפול רפואי",
                    "חתונה",
                    "נסיעה מחוץ לבסיס",
                    "אירוע חברתי",
                    "ימי חופש מאושרים",
                ]
                swap_defs = [
                    # ── Open requests (no covering soldier yet) ──────────────
                    (0, "open", {}),
                    (1, "open", {"target_soldier_id": _other(future_assignments[1].soldier_id).id}),
                    (2, "open", {}),
                    (3, "open", {}),
                    (13, "open", {}),
                    (14, "open", {"target_soldier_id": _other(future_assignments[14].soldier_id).id}),
                    (15, "open", {}),
                    # ── Pending approval ─────────────────────────────────────
                    (4, "pending_approval", {"covering_soldier_id": _other(future_assignments[4].soldier_id).id}),
                    (5, "pending_approval", {"covering_soldier_id": _other(future_assignments[5].soldier_id).id}),
                    # Trade offer: covering soldier offered one of their own duties
                    (10, "pending_approval", {
                        "covering_soldier_id": _other(future_assignments[10].soldier_id).id,
                        "offered_assignment_ids": [str(future_assignments[11].id)],
                    }),
                    # One-sided approval: requester approved, covering has not yet
                    (11, "pending_approval", {
                        "covering_soldier_id": _other(future_assignments[11].soldier_id).id,
                        "requester_side_approved": True,
                        "covering_side_approved": None,
                    }),
                    (16, "pending_approval", {"covering_soldier_id": _other(future_assignments[16].soldier_id).id}),
                    (17, "pending_approval", {
                        "covering_soldier_id": _other(future_assignments[17].soldier_id).id,
                        "requester_side_approved": True,
                        "covering_side_approved": None,
                    }),
                    # ── Applied (both sides approved) ────────────────────────
                    (6, "applied", {
                        "covering_soldier_id": _other(future_assignments[6].soldier_id).id,
                        "requester_side_approved": True,
                        "covering_side_approved": True,
                    }),
                    (7, "applied", {
                        "covering_soldier_id": _other(future_assignments[7].soldier_id).id,
                        "requester_side_approved": True,
                        "covering_side_approved": True,
                    }),
                    # Applied trade: both approved a trade
                    (12, "applied", {
                        "covering_soldier_id": _other(future_assignments[12].soldier_id).id,
                        "offered_assignment_ids": [str(future_assignments[10].id)],
                        "requester_side_approved": True,
                        "covering_side_approved": True,
                    }),
                    (18, "applied", {
                        "covering_soldier_id": _other(future_assignments[18].soldier_id).id,
                        "requester_side_approved": True,
                        "covering_side_approved": True,
                    }),
                    (19, "applied", {
                        "covering_soldier_id": _other(future_assignments[19].soldier_id).id,
                        "offered_assignment_ids": [str(future_assignments[18].id)],
                        "requester_side_approved": True,
                        "covering_side_approved": True,
                    }),
                    # ── Rejected / cancelled ─────────────────────────────────
                    (8, "rejected", {}),
                    (9, "cancelled", {}),
                ]
                for swap_i, (idx, status, extra) in enumerate(swap_defs):
                    a = future_assignments[idx]
                    _make_swap_request(
                        assignment=a,
                        requesting_soldier_id=a.soldier_id,
                        status=status,
                        reason=swap_reasons[swap_i % len(swap_reasons)],
                        extra=extra,
                    )

            # ── Swap requests for מפמר פסיפס (admin) ───────────────────
            admin_future = [
                a for a in created_assignments
                if a.soldier_id == s_admin.id and a.start_date >= today - timedelta(days=1)
            ]
            admin_swap_defs = [
                ("open", {}, "ישיבת מפקדים דחופה"),
                ("open", {"target_soldier_id": _other(s_admin.id).id}, "כנס בכירים"),
                ("pending_approval", {"covering_soldier_id": _other(s_admin.id).id}, "ביקור רפואי"),
                ("pending_approval", {
                    "covering_soldier_id": _other(s_admin.id).id,
                    "requester_side_approved": True,
                    "covering_side_approved": None,
                }, "אירוע משפחתי דחוף"),
                ("applied", {
                    "covering_soldier_id": _other(s_admin.id).id,
                    "requester_side_approved": True,
                    "covering_side_approved": True,
                }, "טיול שנתי"),
                ("rejected", {}, "בקשה שלא אושרה"),
            ]
            for a, (status, extra, reason) in zip(admin_future, admin_swap_defs):
                _make_swap_request(
                    assignment=a,
                    requesting_soldier_id=s_admin.id,
                    status=status,
                    reason=reason,
                    extra=extra,
                )

        # ── Always-on marketplace demo swaps ──────────────────────────────────────────────────
        # Use real DutyShifts so duty_shift_id is populated and the shift
        # detail panel can be opened from the marketplace board.
        _enlisted_type_ids = {duty_types[0].id, duty_types[1].id}
        _demo_shifts = [
            s for s in shifts_created
            if s.duty_type_id in _enlisted_type_ids and s.start_date >= today
        ][:8]
        demo_enlisted = [
            s for s in all_soldiers
            if not s.is_officer and s.personal_number not in ("1000001",)
        ][-len(_demo_shifts):]
        demo_reasons = [
            "בדיקה רפואית",
            "אירוע משפחתי",
            "מבחן באוניברסיטה",
            "חתונה",
            "נסיעה מחוץ לבסיס",
            "ימי חופש מאושרים",
            "קורס מקצועי",
            "בעיה אישית",
        ]
        for i, (sol, shift) in enumerate(zip(demo_enlisted, _demo_shifts)):
            da_demo = DutyAssignment(
                soldier_id=sol.id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=shift.start_date,
                end_date=shift.end_date,
                duty_shift_id=shift.id,
                status="published",
                created_by=s_admin.id,
            )
            session.add(da_demo)
            session.flush()
            # open_to_marketplace=True: these are meant to always show up on
            # the marketplace board (see comment above) — that visibility
            # gate is new with the unified-swap-requests schema change and
            # this fixture was never updated to set it, so it silently
            # defaulted to False (invisible on the board) until now.
            session.add(SwapRequest(
                duty_assignment_id=da_demo.id,
                duty_date=da_demo.start_date,
                requesting_soldier_id=sol.id,
                status="open",
                open_to_marketplace=True,
                reason=demo_reasons[i % len(demo_reasons)],
            ))

        # ── מטווחים (ranges) demo data ──────────────────────────────
        # "שמירות"/"ליווים" require a weapon (eligible_node_ids stays None ==
        # unrestricted, so this alone keeps everyone range-eligible per the
        # exemption rule) and mitvachim.enabled is flipped on so the seeded
        # events are actually visible without a manual admin-settings toggle.
        dt_by_name["שמירות"].requires_weapon = True
        dt_by_name["ליווים"].requires_weapon = True

        mitvachim_setting = session.get(SystemSetting, "mitvachim.enabled")
        if mitvachim_setting is not None:
            mitvachim_setting.value = True

        range_node = all_teams[0]
        range_soldiers = [s for s in all_soldiers if s.hierarchy_node_id == range_node.id]
        if len(range_soldiers) >= 4:
            # Past laser range: attended (present ×2), one no-show — exercises
            # qualification-expiry and score-penalty side effects end to end.
            past_event = RangeEvent(
                hierarchy_node_id=range_node.id,
                range_type=RangeType.laser,
                date=today - timedelta(days=14),
                location="מטווח דרום",
                required_count=3,
                reserve_count=1,
                status=RangeEventStatus.planned,
                arrival_instructions="התייצבות בשער הראשי בשעה 06:30, ציוד אישי מלא.",
                contact_name="סמל מטווחים",
                contact_phone="050-1112233",
                created_by=s_admin.id,
                notes="מטווח לייזר תקופתי",
            )
            session.add(past_event)
            session.flush()

            past_assignments = []
            for i, s in enumerate(range_soldiers[:4]):
                a = RangeAssignment(range_event_id=past_event.id, soldier_id=s.id, is_reserve=(i == 3))
                session.add(a)
                session.flush()
                past_assignments.append(a)

            mark_attendance(
                session, assignment=past_assignments[0],
                status=RangeAttendanceStatus.present, marked_by=s_admin.id,
            )
            mark_attendance(
                session, assignment=past_assignments[1],
                status=RangeAttendanceStatus.present, marked_by=s_admin.id,
            )
            mark_attendance(
                session, assignment=past_assignments[2], status=RangeAttendanceStatus.no_show,
                marked_by=s_admin.id, note="לא הגיע ולא דיווח מראש",
            )

            # Upcoming live-fire range, roster + reserves already assigned.
            upcoming_event = RangeEvent(
                hierarchy_node_id=range_node.id,
                range_type=RangeType.live,
                date=today + timedelta(days=10),
                location="מטווח חי - שדה האש הצפוני",
                required_count=4,
                reserve_count=2,
                status=RangeEventStatus.planned,
                arrival_instructions="התייצבות ליד מוסך הרכבים בשעה 05:30. חובה קסדה ואפוד.",
                contact_name="קצין מטווחים",
                contact_phone="050-2223344",
                created_by=s_admin.id,
            )
            session.add(upcoming_event)
            session.flush()
            for i, s in enumerate(range_soldiers):
                session.add(RangeAssignment(
                    range_event_id=upcoming_event.id, soldier_id=s.id, is_reserve=(i >= 4),
                ))

            # Further-out אל"ל, no roster yet — exercises the empty-roster/
            # planning-page create flow.
            far_event = RangeEvent(
                hierarchy_node_id=range_node.id,
                range_type=RangeType.alal,
                date=today + timedelta(days=30),
                location="שטח אימונים - אלל",
                required_count=6,
                reserve_count=2,
                status=RangeEventStatus.planned,
                created_by=s_admin.id,
                notes='אימון לפני לחימה - שיבוץ יבוצע בהמשך',
            )
            session.add(far_event)

        session.commit()
        import sys

        _safe_print = lambda s: sys.stdout.buffer.write(s.encode("utf-8", errors="replace") + b"\n")
        _safe_print("Seed complete! Created:")
        _safe_print(f"  {len(all_nodes)} hierarchy nodes")
        _safe_print(f"  {len(all_soldiers)} soldiers")
        _safe_print(f"  {len(duty_types)} duty types")
        _safe_print(f"  {len(locations)} duty locations")
        _safe_print(
            f"  {len(exemption_types)} exemption types with {sum(len(dts) for _, dts in mappings)} mappings"
        )
        _safe_print(
            f'  {len(shifts_created)} duty shifts '
            f'(8 \u05e9\u05de\u05d9\u05e8\u05d5\u05ea, 8 \u05d0\u05d1\u05d8"\u05e9, 8 \u05d4\u05d2\u05e0"\u05e9, 40 \u05dc\u05d9\u05d5\u05d5\u05d9\u05dd, 40 \u05e2\u05d1\u05d5\u05d3\u05d5\u05ea \u05e8\u05e1"\u05e8, '
            f'8 \u05e7\u05e6\u05d9\u05df \u05ea\u05d5\u05e8\u05df, 8 \u05de\u05e4\u05e7\u05d3 \u05ea\u05d5\u05e8\u05df, 8 \u05e7\u05e6\u05d9\u05df \u05de\u05dc\u05d5\u05d5\u05d4 \u05d0\u05d1\u05d8"\u05e9, 40 \u05d0\u05d1\u05d5\u05ea \u05d1\u05d9\u05ea, 40 \u05e2\u05d1\u05d5\u05d3\u05d5\u05ea \u05e8\u05e1"\u05e8 \u05d1\u05d9\u05e0\u05d5\u05d9, '
            f'40 \u05de\u05e9\u05de\u05e8\u05ea \u05dc\u05d9\u05dc\u05d4)'
        )
        if with_assignments:
            _safe_print(f"  {shift_assignments} primary duty assignments")
            _safe_print(f"  {reserve_count_total} reserve assignments")
            _safe_print(f"  {links_created} reserve-to-primary links")
            _safe_print("  21+ swap requests incl. 6 for מפמר פסיפס (2 open, 2 pending, 1 applied, 1 rejected)")
        else:
            _safe_print("  0 shift assignments (pass --with-assignments to include)")
        _safe_print(f"  1 invite code")
        _safe_print(f"  4 enrollment requests (2 pending, 1 approved, 1 rejected)")
        if fair:
            _safe_print(f"  0 personal constraints, 0 soldier exemptions (--fair)")
        else:
            _safe_print(f"  15 personal constraints")
            _safe_print(f"  12 soldier exemptions")
        _safe_print(f"  5 score adjustments")
        _safe_print(f"  8 exemption requests (6 pending, 1 approved, 1 rejected)")
        _safe_print(f"  {fu_count} profile field update requests")


if __name__ == "__main__":
    import sys

    seed(
        force="--clear" in sys.argv or "--force" in sys.argv,
        with_assignments="--with-assignments" in sys.argv,
        fair="--fair" in sys.argv,
    )
