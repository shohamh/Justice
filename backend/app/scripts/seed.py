"""Seed the database with realistic test data.

Usage: python -m app.scripts.seed [--clear] [--with-assignments]

Flags:
  --clear / --force      Drop and re-create all seed data.
  --with-assignments     Also pre-fill shift assignments (default: shifts are
                         created empty so the algorithm can assign them).
"""

from datetime import date
from decimal import Decimal
import math

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
    ScoreAdjustment,
    Soldier,
    SoldierExemption,
    SoldierFieldUpdate,
    SwapRequest,
)
from app.db.session import SessionLocal


def seed(*, force: bool = False, with_assignments: bool = False):
    clear = force
    with SessionLocal() as session:
        hashed = hash_password("1234567890")

        if clear:
            session.query(ExemptionRequest).delete()
            session.query(PersonalConstraint).delete()
            session.query(ScoreAdjustment).delete()
            session.query(SoldierExemption).delete()
            session.query(SwapRequest).delete()
            session.query(ExemptionDutyTypeMap).delete()
            session.query(DutyReserveLink).delete()
            session.query(DutyAssignment).delete()
            session.query(DutyShift).delete()
            session.query(HierarchyNode).delete()
            session.query(Soldier).delete()
            session.query(DutyType).delete()
            session.query(DutyLocation).delete()
            session.query(ExemptionType).delete()
            session.commit()

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
        psips = HierarchyNode(level="department", name="פסיפס", path_ids=[])
        session.add(psips)
        session.flush()
        psips.path_ids = [psips.id]

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

        _MANDATORY_MONTHS = 32  # 2 years 8 months

        def _mandatory_end(enlist: date) -> date:
            m = enlist.month + _MANDATORY_MONTHS
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

        # Admin — department commander (קבע, officer, veteran 15+ years)
        s_admin = make_soldier(
            "1000001",
            "מפמר פסיפס",
            "admin",
            psips.id,
            is_officer=True,
            rank='אל"מ',
            bahad1_graduate=True,
            enlistment_date=date(2010, 1, 1),
            mandatory_end_date=_mandatory_end(date(2010, 1, 1)),
            discharge_date=date(2035, 1, 1),
            gender="male",
        )
        all_soldiers.append(s_admin)
        psips.commander_id = s_admin.id

        # Branch commanders (קבע, officers, 10+ years)
        s_focus = make_soldier(
            "2000001",
            "רען פוקוס",
            "commander",
            branches[0].id,
            is_officer=True,
            rank='רס"ן',
            bahad1_graduate=True,
            enlistment_date=date(2015, 1, 1),
            mandatory_end_date=_mandatory_end(date(2015, 1, 1)),
            discharge_date=date(2030, 1, 1),
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

        # Mador commanders — 3 senior (early career קבע) + 3 junior (late חובה)
        mador_commanders = {
            "מחקר": ("3000001", "commander"),
            "שבירה": ("3000002", "commander"),
            "גוליבר": ("3000003", "commander"),
            "אינפרה": ("3000004", "commander"),
            "פלאש": ("3000005", "commander"),
            "ספקטרה": ("3000006", "commander"),
        }
        for idx, node in enumerate(focus_groups + alom_groups):
            pn_str, role = mador_commanders[node.name]
            if idx < 3:
                # Senior mador commanders — recently became קבע
                enl = date(2021, 1, 1)
                s = make_soldier(
                    pn_str,
                    f"רמד {node.name}",
                    role,
                    node.id,
                    is_officer=True,
                    rank="סרן",
                    bahad1_graduate=True,
                    enlistment_date=enl,
                    mandatory_end_date=_mandatory_end(enl),
                    discharge_date=date(2028, 1, 1),
                    gender="male",
                )
            else:
                # Junior mador commanders — late חובה, nearing end
                enl = date(2023, 10, 1)
                s = make_soldier(
                    pn_str,
                    f"רמד {node.name}",
                    role,
                    node.id,
                    is_officer=True,
                    rank="סרן",
                    bahad1_graduate=True,
                    enlistment_date=enl,
                    mandatory_end_date=_mandatory_end(enl),
                    gender="male",
                )
            all_soldiers.append(s)
            node.commander_id = s.id

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
        for team_idx, team in enumerate(all_teams):
            short = team_names_he[team.name]
            # Team leader (רשצ, NCO) — vary by team index: some mid-service, some late
            if team_idx < 5:
                enl = date(2023, 3, 1)
            else:
                enl = date(2024, 7, 1)
            pn = next_pn()
            s = make_soldier(
                pn,
                f"רשצ {short}",
                "commander",
                team.id,
                is_officer=False,
                rank="רסמ",
                enlistment_date=enl,
                mandatory_end_date=_mandatory_end(enl),
                gender="male",
            )
            team_soldiers.append(s)
            team.commander_id = s.id
            # 5 members per team: 3 enlisted חובה, 1 enlisted קבע, 1 officer חובה
            _team_profiles = [
                # (enl_year, enl_month, rank, is_officer, discharge_year, gender)
                (2024, 1, "סמל", False, None, "female"),  # enlisted חובה late-service
                (2025, 3, 'רב"ט', False, None, "male"),  # enlisted חובה mid-service
                (2026, 1, "טוראי", False, None, "male"),  # enlisted חובה fresh
                (2019, 6, "רסר", False, 2035, "male"),  # enlisted קבע experienced
                (2024, 3, "סגן", True, None, "male"),  # officer חובה junior
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
                    mandatory_end_date=_mandatory_end(enl),
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
            (2023, 8, "סמל", False, None, "male"),  # 0 enlisted חובה senior
            (2024, 1, "סמל", False, None, "female"),  # 1 enlisted חובה
            (2024, 6, 'רב"ט', False, None, "male"),  # 2 enlisted חובה
            (2024, 11, 'רב"ט', False, None, "male"),  # 3 enlisted חובה
            (2025, 3, 'רב"ט', False, None, "female"),  # 4 enlisted חובה
            (2025, 7, "טוראי", False, None, "male"),  # 5 enlisted חובה
            (2025, 11, "טוראי", False, None, "male"),  # 6 enlisted חובה
            (2026, 2, "טוראי", False, None, "female"),  # 7 enlisted חובה fresh
            (2018, 4, "רסב", False, 2035, "male"),  # 8 enlisted קבע
            (2019, 8, "רסר", False, 2034, "male"),  # 9 enlisted קבע
            (2020, 2, "רסר", False, 2033, "female"),  # 10 enlisted קבע
            (2023, 10, "סגן", True, None, "male"),  # 11 officer חובה
            (2024, 4, "סגן", True, None, "female"),  # 12 officer חובה
            (2017, 1, "סרן", True, 2032, "male"),  # 13 officer קבע
            (2026, 3, "טוראי", False, None, "male"),  # 14 enlisted חובה very fresh
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
                    mandatory_end_date=_mandatory_end(enl),
                    discharge_date=disc,
                    bahad1_graduate=is_off,
                    gender=g,
                )
                mador_soldiers.append(s)

        all_soldiers += mador_soldiers

        # ── Duty types ──────────────────────────────────────────────
        # (name, score_per_day, description, requirements, reserve_ratio, reserve_minimum)
        dt_defs = [
            (
                "שמירות",
                Decimal("1.125"),
                "שמירה בבסיס",
                {"officers_allowed": False, "allowed_service_types": ["חובה"]},
                Decimal("0.300"),
                3,
            ),
            (
                "ליווים",
                Decimal("1.00"),
                "ליווי אסירים/משאיות",
                {"officers_allowed": False, "allowed_service_types": ["חובה"]},
                Decimal("0.200"),
                2,
            ),
            (
                'עבודות רס"ר',
                Decimal("1.00"),
                'עבודות רס"ר שונות',
                {"officers_allowed": False, "allowed_service_types": ["חובה"]},
                Decimal("0.250"),
                2,
            ),
            (
                'אבט"ש',
                Decimal(9) / Decimal(7),
                "אבטחה שוטפת",
                {"officers_allowed": False, "allowed_service_types": ["חובה"]},
                Decimal("0.350"),
                4,
            ),
            (
                'הגנ"ש',
                Decimal(9) / Decimal(7),
                'הגנה"ש',
                {"enlisted_allowed": False},
                Decimal("0.400"),
                2,
            ),
            (
                "קצין תורן",
                Decimal("1.125"),
                "קצין תורן בבסיס",
                {"enlisted_allowed": False, "allowed_service_types": ["חובה"]},
                Decimal("0.500"),
                1,
            ),
            (
                "מפקד תורן",
                Decimal("1.125"),
                "מפקד תורן בבסיס",
                {
                    "enlisted_allowed": False,
                    "allowed_service_types": ["חובה"],
                    "requires_bahad1": True,
                },
                Decimal("0.500"),
                1,
            ),
            (
                'קצין מלווה אבט"ש',
                Decimal(9) / Decimal(7),
                "קצין מלווה לאבטחה",
                {"enlisted_allowed": False, "allowed_service_types": ["חובה"]},
                Decimal("0.300"),
                1,
            ),
            (
                "אבות בית",
                Decimal("1.00"),
                "אבות בית",
                {"officers_allowed": False, "allowed_service_types": ["חובה"]},
                Decimal("0.150"),
                1,
            ),
            (
                'עבודות רס"ר בינוי',
                Decimal("1.00"),
                'עבודות רס"ר בנושא בינוי',
                {"officers_allowed": False, "allowed_service_types": ["חובה"]},
                Decimal("0.150"),
                1,
            ),
        ]
        duty_types = []
        for name, spd, desc, reqs, rr, rmin in dt_defs:
            dt = DutyType(
                name=name,
                score_per_day=spd,
                description=desc,
                requirements=reqs,
                reserve_ratio=rr,
                reserve_minimum=rmin,
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
        for i, s in enumerate(all_soldiers[:15]):
            offset = i % 30
            pc = PersonalConstraint(
                soldier_id=s.id,
                start_date=today + timedelta(days=offset),
                end_date=today + timedelta(days=offset + randint(0, 2)),
                reason=constraint_reasons[i % len(constraint_reasons)],
                status=choice(["pending", "approved", "approved", "rejected"]),
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
        non_global_types = [et for et in exemption_types if not et.is_global]
        for i, s in enumerate(all_soldiers[:12]):
            offset = i % 30
            se = SoldierExemption(
                soldier_id=s.id,
                exemption_type_id=choice(non_global_types).id,
                start_date=today + timedelta(days=offset),
                end_date=today + timedelta(days=offset + randint(3, 14)),
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
            start_date=today + timedelta(days=5),
            end_date=today + timedelta(days=10),
            reason="פטור לשמירות - אושר",
            status="approved",
            decided_by=s_admin.id,
            decision_note="מאושר לשבוע",
        )
        session.add(er_approved)

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

        next_mon = _next_weekday(today, 0)
        next_thu = _next_weekday(today, 3)
        next_sun = _next_weekday(today, 6)

        loc_cycle = itertools.cycle(locations)
        dt_by_name = {dt.name: dt for dt in duty_types}
        shifts_created = []
        shift_assignments = 0

        # 1. שמירות — Mon-to-Mon, 4 weeks, 10 primaries
        dt = dt_by_name["שמירות"]
        for w in range(4):
            start = next_mon + timedelta(weeks=w)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                required_count=10,
                notes="שמירות שבועית",
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 2. אבט"ש — Mon-to-Mon, 4 weeks
        dt = dt_by_name['אבט"ש']
        for w in range(4):
            start = next_mon + timedelta(weeks=w)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                required_count=2,
                notes='אבט"ש שבועית',
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 3. הגנ"ש — Thu-to-Thu, 4 weeks
        dt = dt_by_name['הגנ"ש']
        for w in range(4):
            start = next_thu + timedelta(weeks=w)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                required_count=2,
                notes='הגנ"ש שבועית',
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 4. ליווים — Sun-Thu single days, 4 weeks
        dt = dt_by_name["ליווים"]
        for w in range(4):
            for d in range(5):
                day = next_sun + timedelta(weeks=w, days=d)
                s = DutyShift(
                    duty_type_id=dt.id,
                    duty_location_id=next(loc_cycle).id,
                    start_date=day,
                    end_date=day,
                    required_count=2,
                    notes="ליווי יומי",
                    created_by=s_admin.id,
                )
                session.add(s)
                session.flush()
                shifts_created.append(s)

        # 5. עבודות רס"ר — Sun-Thu single days, 4 weeks
        dt = dt_by_name['עבודות רס"ר']
        for w in range(4):
            for d in range(5):
                day = next_sun + timedelta(weeks=w, days=d)
                s = DutyShift(
                    duty_type_id=dt.id,
                    duty_location_id=next(loc_cycle).id,
                    start_date=day,
                    end_date=day,
                    required_count=2,
                    notes='עבודות רס"ר יומיות',
                    created_by=s_admin.id,
                )
                session.add(s)
                session.flush()
                shifts_created.append(s)

        # 6. קצין תורן — Mon-to-Mon, 4 weeks
        dt = dt_by_name["קצין תורן"]
        for w in range(4):
            start = next_mon + timedelta(weeks=w)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                required_count=1,
                notes="קצין תורן שבועי",
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 7. מפקד תורן — Mon-to-Mon, 4 weeks
        dt = dt_by_name["מפקד תורן"]
        for w in range(4):
            start = next_mon + timedelta(weeks=w)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                required_count=1,
                notes="מפקד תורן שבועי",
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 8. קצין מלווה אבט"ש — Mon-to-Mon, 4 weeks
        dt = dt_by_name['קצין מלווה אבט"ש']
        for w in range(4):
            start = next_mon + timedelta(weeks=w)
            s = DutyShift(
                duty_type_id=dt.id,
                duty_location_id=next(loc_cycle).id,
                start_date=start,
                end_date=start + timedelta(days=7),
                required_count=1,
                notes='קצין מלווה אבט"ש שבועי',
                created_by=s_admin.id,
            )
            session.add(s)
            session.flush()
            shifts_created.append(s)

        # 9. אבות בית — Sun-Thu single days, 4 weeks
        dt = dt_by_name["אבות בית"]
        for w in range(4):
            for d in range(5):
                day = next_sun + timedelta(weeks=w, days=d)
                s = DutyShift(
                    duty_type_id=dt.id,
                    duty_location_id=next(loc_cycle).id,
                    start_date=day,
                    end_date=day,
                    required_count=2,
                    notes="אבות בית יומי",
                    created_by=s_admin.id,
                )
                session.add(s)
                session.flush()
                shifts_created.append(s)

        # 10. עבודות רס"ר בינוי — Sun-Thu single days, 4 weeks
        dt = dt_by_name['עבודות רס"ר בינוי']
        for w in range(4):
            for d in range(5):
                day = next_sun + timedelta(weeks=w, days=d)
                s = DutyShift(
                    duty_type_id=dt.id,
                    duty_location_id=next(loc_cycle).id,
                    start_date=day,
                    end_date=day,
                    required_count=2,
                    notes='עבודות רס"ר בינוי יומיות',
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
            # indices: 0-3 שמירות, 4-11 other weekly, 12-91 daily (80), 92-103 new weekly (12)
            for i, shift in enumerate(shifts_created):
                if i < 4:
                    # שמירות — assign all required_count (10)
                    for k in range(shift.required_count):
                        soldier = enlisted[(i * 3 + k) % len(enlisted)]
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
                elif i < 12:
                    # other weekly shifts (req=2) — assign 2 soldiers each
                    for k in range(min(2, shift.required_count)):
                        soldier = enlisted[(i * 3 + k) % len(enlisted)]
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
                elif 12 <= i < 92:
                    # daily shifts (req=2) — assign 1 soldier to each
                    soldier = enlisted[i % len(enlisted)]
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
                else:
                    # new weekly officer shifts (req=1) — assign 1 each
                    soldier = officer_soldiers[(i - 92) % len(officer_soldiers)]
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
                pool = officer_soldiers if i >= 92 else enlisted
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
                    session.add(
                        DutyReserveLink(
                            primary_assignment_id=primary.id,
                            reserve_assignment_id=reserve.id,
                            hierarchy_distance=0,
                        )
                    )
                    links_created += 1

            # ── Swap requests ──────────────────────────────────────────
            # Pick future assignments for swaps
            from datetime import timedelta

            today = date.today()
            future_assignments = [
                a for a in created_assignments if a.start_date >= today - timedelta(days=1)
            ]
            if len(future_assignments) >= 6:
                # Swap 1: open — soldier wants to swap, no specific target
                s_a = future_assignments[0]
                session.add(
                    SwapRequest(
                        duty_assignment_id=s_a.id,
                        duty_date=s_a.start_date,
                        requesting_soldier_id=s_a.soldier_id,
                        status="open",
                        reason="מבקש להחליף תורנות",
                    )
                )
                # Swap 2: open with target
                s_b = future_assignments[1]
                target_s = session.query(Soldier).filter(Soldier.id != s_b.soldier_id).first()
                session.add(
                    SwapRequest(
                        duty_assignment_id=s_b.id,
                        duty_date=s_b.start_date,
                        requesting_soldier_id=s_b.soldier_id,
                        target_soldier_id=target_s.id,
                        status="open",
                        reason="מבקש להחליף עם חייל ספציפי",
                    )
                )
                # Swap 3: pending_approval — covering soldier agreed, waiting for approval
                s_c = future_assignments[2]
                cover_s = session.query(Soldier).filter(Soldier.id != s_c.soldier_id).first()
                session.add(
                    SwapRequest(
                        duty_assignment_id=s_c.id,
                        duty_date=s_c.start_date,
                        requesting_soldier_id=s_c.soldier_id,
                        covering_soldier_id=cover_s.id,
                        status="pending_approval",
                        reason="סוכם עם המחליף",
                    )
                )
                # Swap 4: applied — completed swap
                s_d = future_assignments[3]
                cover_d = session.query(Soldier).filter(Soldier.id != s_d.soldier_id).first()
                session.add(
                    SwapRequest(
                        duty_assignment_id=s_d.id,
                        duty_date=s_d.start_date,
                        requesting_soldier_id=s_d.soldier_id,
                        covering_soldier_id=cover_d.id,
                        status="applied",
                        requester_side_approved=True,
                        covering_side_approved=True,
                        reason="החלפה אושרה ובוצעה",
                    )
                )

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
            f'  {len(shifts_created)} duty shifts (4 \u05e9\u05de\u05d9\u05e8\u05d5\u05ea, 4 \u05d0\u05d1\u05d8"\u05e9, 4 \u05d4\u05d2\u05e0"\u05e9, 20 \u05dc\u05d9\u05d5\u05d5\u05d9\u05dd, 20 \u05e2\u05d1\u05d5\u05d3\u05d5\u05ea \u05e8\u05e1"\u05e8, 4 \u05e7\u05e6\u05d9\u05df \u05ea\u05d5\u05e8\u05df, 4 \u05de\u05e4\u05e7\u05d3 \u05ea\u05d5\u05e8\u05df, 4 \u05e7\u05e6\u05d9\u05df \u05de\u05dc\u05d5\u05d5\u05d4 \u05d0\u05d1\u05d8"\u05e9, 20 \u05d0\u05d1\u05d5\u05ea \u05d1\u05d9\u05ea, 20 \u05e2\u05d1\u05d5\u05d3\u05d5\u05ea \u05e8\u05e1"\u05e8 \u05d1\u05d9\u05e0\u05d5\u05d9)'
        )
        if with_assignments:
            _safe_print(f"  {shift_assignments} primary duty assignments")
            _safe_print(f"  {reserve_count_total} reserve assignments")
            _safe_print(f"  {links_created} reserve-to-primary links")
            _safe_print(
                "  4 swap requests (1 open, 1 open with target, 1 pending approval, 1 applied)"
            )
        else:
            _safe_print("  0 shift assignments (pass --with-assignments to include)")
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
    )
