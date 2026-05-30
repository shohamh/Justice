"""Seed the database with realistic test data.

Usage: python -m app.scripts.seed [--clear]
"""

from datetime import date
from decimal import Decimal

from app.auth.password import hash_password
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionRequest,
    ExemptionType,
    HierarchyNode,
    PersonalConstraint,
    ScoreAdjustment,
    Soldier,
    SoldierExemption,
)
from app.db.session import SessionLocal


def seed(*, force: bool = False):
    clear = force
    with SessionLocal() as session:
        hashed = hash_password("1234567890")

        if clear:
            session.query(ExemptionRequest).delete()
            session.query(PersonalConstraint).delete()
            session.query(ScoreAdjustment).delete()
            session.query(SoldierExemption).delete()
            session.query(ExemptionDutyTypeMap).delete()
            session.query(DutyAssignment).delete()
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

        all_nodes = [psips] + branches + focus_groups + alom_groups + all_teams
        pn_counter = 1000001

        def next_pn() -> str:
            nonlocal pn_counter
            pn_counter += 1
            return str(pn_counter)

        def make_soldier(pn: str, name: str, role: str, node_id: int):
            s = Soldier(
                personal_number=pn,
                full_name=name,
                password_hash=hashed,
                role=role,
                hierarchy_node_id=node_id,
                enrolled_at=date(2026, 1, 15),
                must_change_password=False,
            )
            session.add(s)
            session.flush()
            return s

        # ── Soldiers created bottom-up to own their node ids ────────
        all_soldiers = []

        # Admin — department commander
        s_admin = make_soldier("1000001", "מפמר פסיפס", "admin", psips.id)
        all_soldiers.append(s_admin)
        psips.commander_id = s_admin.id

        # Branch commanders
        s_focus = make_soldier("2000001", "רען פוקוס", "commander", branches[0].id)
        all_soldiers.append(s_focus)
        branches[0].commander_id = s_focus.id

        s_alom = make_soldier("2000002", "רען אלומות", "commander", branches[1].id)
        all_soldiers.append(s_alom)
        branches[1].commander_id = s_alom.id

        # Mador commanders
        mador_commanders = {
            "מחקר": ("3000001", "commander"),
            "שבירה": ("3000002", "commander"),
            "גוליבר": ("3000003", "commander"),
            "אינפרה": ("3000004", "commander"),
            "פלאש": ("3000005", "commander"),
            "ספקטרה": ("3000006", "commander"),
        }
        for node in focus_groups + alom_groups:
            pn_str, role = mador_commanders[node.name]
            s = make_soldier(pn_str, f"רמד {node.name}", role, node.id)
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
        for team in all_teams:
            short = team_names_he[team.name]
            for i in range(1, 4):
                pn = next_pn()
                s = make_soldier(pn, f"{short} {i}", "soldier", team.id)
                team_soldiers.append(s)

        all_soldiers += team_soldiers

        # Mador soldiers for group-level soldiers (3 per mador without teams)
        mador_soldiers = []
        for gnode, gshort in [("אינפרה", "אינפרה"), ("פלאש", "פלאש"), ("ספקטרה", "ספקטרה")]:
            node = [n for n in alom_groups if n.name == gnode][0]
            for i in range(1, 4):
                pn = next_pn()
                s = make_soldier(pn, f"{gshort} {i}", "soldier", node.id)
                mador_soldiers.append(s)

        all_soldiers += mador_soldiers

        # ── Duty types ──────────────────────────────────────────────
        dt_defs = [
            ("שמירות", Decimal("1.00"), "שמירה בבסיס"),
            ("ליווים", Decimal("1.50"), "ליווי אסירים/משאיות"),
            ("עבודות רס\"ר", Decimal("0.75"), "עבודות רס\"ר שונות"),
            ("אבט\"ש", Decimal("2.00"), "אבטחה שוטפת"),
            ("הגנ\"ש", Decimal("0.50"), "הגנה\"ש"),
            ("מטבח", Decimal("0.50"), "תורנות מטבח"),
            ("מרפאה", Decimal("0.75"), "תורנות מרפאה"),
            ("חמ\"ל", Decimal("1.25"), "עבודה בחמ\"ל"),
            ("מנהלה", Decimal("0.50"), "עבודות מנהלה"),
        ]
        duty_types = []
        for name, spd, desc in dt_defs:
            dt = DutyType(name=name, score_per_day=spd, description=desc)
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
            ("פטור שמירות", "פטור מכל סוגי השמירות"),
            ("פטור רפואי", "פטור רפואי זמני"),
            ("פטור משפחתי", "פטור עקב סיבה משפחתית"),
            ("פטור אימונים", "פטור עקב אימונים"),
            ("פטור נפשי", "פטור נפשי זמני"),
        ]
        exemption_types = []
        for ename, edesc in et_defs:
            et = ExemptionType(name=ename, description=edesc)
            session.add(et)
            session.flush()
            exemption_types.append(et)

        # ── Exemption → Duty mappings ──────────────────────────────
        mappings = [
            (0, [0, 1, 2]),       # פטור שמירות ← שמירות, ליווים, עבודות רס"ר
            (1, [0, 1, 5, 6]),    # פטור רפואי ← שמירות, ליווים, מטבח, מרפאה
            (2, [0, 3, 7]),       # פטור משפחתי ← שמירות, אבט"ש, חמ"ל
            (3, [4, 5, 8]),       # פטור אימונים ← הגנ"ש, מטבח, מנהלה
            (4, [0, 6, 8]),       # פטור נפשי ← שמירות, מרפאה, מנהלה
        ]
        for et_idx, dt_idxs in mappings:
            for dt_idx in dt_idxs:
                session.add(ExemptionDutyTypeMap(
                    exemption_type_id=exemption_types[et_idx].id,
                    duty_type_id=duty_types[dt_idx].id,
                ))

        # ── Duty assignments ────────────────────────────────────────
        from datetime import timedelta
        from random import choice, randint
        today = date.today()
        assignment_count = 0
        for i, s in enumerate(all_soldiers):
            num_days = randint(1, 4)
            for d in range(num_days):
                assignment_count += 1
                offset = (i + d * 7) % 30
                day = today + timedelta(days=offset)
                da = DutyAssignment(
                    soldier_id=s.id,
                    duty_type_id=choice(duty_types).id,
                    duty_location_id=choice(locations).id,
                    start_date=day,
                    end_date=day + timedelta(days=randint(0, 2)),
                    status=choice(["published", "published", "published", "pending"]),
                    created_by=s_admin.id,
                )
                session.add(da)

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
                    + [session.query(Soldier).filter(Soldier.personal_number == pn).first().id
                       for pn in ["3000001", "3000002", "3000003", "3000004", "3000005", "3000006"]]
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
        for i, s in enumerate(all_soldiers[:12]):
            offset = i % 30
            se = SoldierExemption(
                soldier_id=s.id,
                exemption_type_id=choice(exemption_types).id,
                start_date=today + timedelta(days=offset),
                end_date=today + timedelta(days=offset + randint(3, 14)),
                reason=exemption_reasons[i % len(exemption_reasons)],
                granted_by=s_admin.id,
            )
            session.add(se)

        # ── Score adjustments ───────────────────────────────────────
        sa_defs = [
            ("5000001", Decimal("10.00"), "תוספת שמירות חודשית"),
            ("5000004", Decimal("8.00"), "תוספת ליווי"),
            ("5000006", Decimal("-3.00"), "הפחתה על אי התייצבות"),
            ("4000003", Decimal("15.00"), "תוספת עבודות רס\"ר"),
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

        session.commit()
        print("Seed complete! Created:")
        print(f"  {len(all_nodes)} hierarchy nodes")
        print(f"  {len(all_soldiers)} soldiers")
        print(f"  {len(duty_types)} duty types")
        print(f"  {len(locations)} duty locations")
        print(f"  {len(exemption_types)} exemption types with {sum(len(dts) for _, dts in mappings)} mappings")
        print(f"  {assignment_count} duty assignments")
        print(f"  15 personal constraints")
        print(f"  12 soldier exemptions")
        print(f"  5 score adjustments")
        print(f"  8 exemption requests (6 pending, 1 approved, 1 rejected)")


if __name__ == "__main__":
    import sys
    seed(force="--clear" in sys.argv or "--force" in sys.argv)
