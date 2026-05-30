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
        s_admin = make_soldier("1000001", "מפק פסיפס", "admin", psips.id)
        all_soldiers.append(s_admin)
        psips.commander_id = s_admin.id

        # Branch commanders
        s_focus = make_soldier("2000001", "מפק פוקוס", "commander", branches[0].id)
        all_soldiers.append(s_focus)
        branches[0].commander_id = s_focus.id

        s_alom = make_soldier("2000002", "מפק אלומות", "commander", branches[1].id)
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
        ]
        duty_types = []
        for name, spd, desc in dt_defs:
            dt = DutyType(name=name, score_per_day=spd, description=desc)
            session.add(dt)
            session.flush()
            duty_types.append(dt)

        loc = DutyLocation(name="בסיס מרכז", base="בסיס מרכז")
        session.add(loc)
        session.flush()

        et = ExemptionType(name="פטור שמירות", description="פטור מכל סוגי השמירות")
        session.add(et)
        session.flush()

        for dt in duty_types[:3]:
            session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt.id))

        # ── Sample assignments, constraints, exemptions ─────────────
        today = date.today()
        for i, s in enumerate(all_soldiers[-15:]):
            da = DutyAssignment(
                soldier_id=s.id,
                duty_type_id=duty_types[i % len(duty_types)].id,
                duty_location_id=loc.id,
                start_date=today,
                end_date=today,
                status="published",
                created_by=s_admin.id,
            )
            session.add(da)

        for i, s in enumerate(all_soldiers[-6:]):
            pc = PersonalConstraint(
                soldier_id=s.id,
                start_date=today,
                end_date=today,
                reason="אילוץ לדוגמה",
                status="approved",
                decided_by=s_admin.id,
            )
            session.add(pc)

        for i, s in enumerate(all_soldiers[-4:]):
            se = SoldierExemption(
                soldier_id=s.id,
                exemption_type_id=et.id,
                start_date=today,
                end_date=today,
                reason="פטור זמני",
                granted_by=s_admin.id,
            )
            session.add(se)

        session.commit()
        print("Seed complete! Created:")
        print(f"  {len(all_nodes)} hierarchy nodes")
        print(f"  {len(all_soldiers)} soldiers")
        print(f"  {len(duty_types)} duty types")
        print(f"  1 duty location")
        print(f"  1 exemption type with {len(duty_types[:3])} mappings")
        print(f"  15 duty assignments")
        print(f"  6 personal constraints")
        print(f"  4 soldier exemptions")


if __name__ == "__main__":
    import sys
    seed(force="--clear" in sys.argv or "--force" in sys.argv)
