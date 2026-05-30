"""Seed the database with realistic test data.

Usage: python -m app.scripts.seed
"""

from datetime import date, timedelta
from decimal import Decimal
from random import choice, randint

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
    with SessionLocal() as session:
        hashed = hash_password("1234567890")

        if force:
            # Wipe all existing data for a clean reseed
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

        # Ensure admin 1000001 always has the correct password, even if already seeded
        admin = session.query(Soldier).filter(Soldier.personal_number == "1000001").first()
        if admin:
            admin.password_hash = hashed
            admin.must_change_password = False
            session.flush()

        if session.query(Soldier).filter(Soldier.personal_number == "2000001").first():
            session.commit()
            print("Seed data already exists. Admin password updated.")
            return

        # ── Hierarchy ──────────────────────────────────────────────
        dept1 = HierarchyNode(level="department", name="אגף מבצעים", path_ids=[])
        dept2 = HierarchyNode(level="department", name="אגף מודיעין", path_ids=[])
        session.add_all([dept1, dept2])
        session.flush()
        dept1.path_ids = [dept1.id]
        dept2.path_ids = [dept2.id]

        branches = []
        for dept, bnames in [(dept1, ["זרוע אוויר", "זרוע ים"]), (dept2, ["זרוע סייבר", "זרוע יבשה"])]:
            for bname in bnames:
                b = HierarchyNode(level="branch", name=bname, parent_id=dept.id, path_ids=[])
                session.add(b)
                session.flush()
                b.path_ids = dept.path_ids + [b.id]
                branches.append(b)

        groups = []
        for branch, gnames in [
            (branches[0], ["טייסת קרב", "טייסת תובלה"]),
            (branches[1], ["שייטת 1", "שייטת 2"]),
            (branches[2], ["יחידת 8200", "יחידת לוחמת סייבר"]),
            (branches[3], ["גדוד חוד", "גדוד סדיר"]),
        ]:
            for gname in gnames:
                g = HierarchyNode(level="group", name=gname, parent_id=branch.id, path_ids=[])
                session.add(g)
                session.flush()
                g.path_ids = branch.path_ids + [g.id]
                groups.append(g)

        teams = []
        for group, tnames in [
            (groups[0], ["רביעיית 1", "רביעיית 2"]),
            (groups[1], ["צוות א׳", "צוות ב׳"]),
            (groups[2], ["מדור איסוף", "מדור עיבוד"]),
            (groups[3], ["כיתה א׳", "כיתה ב׳"]),
            (groups[4], ["פלגת מודיעין", "פלגת תקיפה"]),
            (groups[5], ["צוות הגנה", "צוות התקפה"]),
            (groups[6], ["פלוגה א׳", "פלוגה ב׳"]),
            (groups[7], ["מחלקה 1", "מחלקה 2"]),
        ]:
            for tname in tnames:
                t = HierarchyNode(level="team", name=tname, parent_id=group.id, path_ids=[])
                session.add(t)
                session.flush()
                t.path_ids = group.path_ids + [t.id]
                teams.append(t)

        all_nodes = [dept1, dept2] + branches + groups + teams

        # ── Soldiers ───────────────────────────────────────────────
        soldier_defs = [
            ("1000001", "מפקד על הראשי", "admin", 0),
            ("2000001", "מפקד מבצעים", "duty_manager", 1),
            ("3000001", "מפקדת מודיעין", "commander", 2),
            ("3000002", "מפקד אוויר", "commander", 3),
            ("3000003", "מפקד ים", "commander", 4),
            ("4000001", "לוחם מצטיין", "soldier", 8),
            ("4000002", "לוחם ותיק", "soldier", 9),
            ("4000003", "פקח מבצעים", "soldier", 10),
            ("4000004", "מפעיל מערכת", "soldier", 11),
            ("4000005", "אנליסט מודיעין", "soldier", 12),
            ("4000006", "לוחם סייבר", "soldier", 13),
            ("4000007", "מפקד צוות", "soldier", 14),
            ("4000008", "לוחם", "soldier", 15),
            ("5000001", "טייס קרב", "soldier", 8),
            ("5000002", "נווט", "soldier", 9),
            ("5000003", "מכונאי", "soldier", 10),
            ("5000004", "שייטת 1 לוחם", "soldier", 11),
            ("5000005", "שייטת 2 לוחם", "soldier", 12),
            ("5000006", "איסוף 1", "soldier", 13),
            ("5000007", "איסוף 2", "soldier", 14),
            ("5000008", "עיבוד 1", "soldier", 15),
            ("6000001", "לוחם חי״ר", "soldier", 22),
            ("6000002", "מקלען", "soldier", 23),
            ("6000003", "חובש", "soldier", 24),
            ("6000004", "נהג", "soldier", 25),
            ("6000005", "מודיעין 1", "soldier", 26),
            ("6000006", "מודיעין 2", "soldier", 27),
            ("6000007", "סייבר מגן", "soldier", 28),
            ("6000008", "סייבר תוקף", "soldier", 29),
        ]

        soldiers = []
        for pn, name, role, node_idx in soldier_defs:
            existing = session.query(Soldier).filter(Soldier.personal_number == pn).first()
            if existing:
                soldiers.append(existing)
                continue
            s = Soldier(
                personal_number=pn,
                full_name=name,
                password_hash=hashed,
                role=role,
                hierarchy_node_id=all_nodes[node_idx].id,
                enrolled_at=date(2026, 1, 15),
                must_change_password=False,
            )
            session.add(s)
            session.flush()
            soldiers.append(s)

        # ── Assign commanders to nodes ─────────────────────────────
        dept1.commander_id = soldiers[0].id
        dept2.commander_id = soldiers[2].id
        for i, node in enumerate(branches):
            node.commander_id = soldiers[i + 3].id if i + 3 < len(soldiers) else soldiers[0].id
        for i, node in enumerate(groups + teams):
            if i % 3 == 0 and (i + 7) < len(soldiers):
                node.commander_id = soldiers[i + 7].id

        # ── Duty Types ─────────────────────────────────────────────
        dt1 = DutyType(name="משמרת בוקר", score_per_day=Decimal("1.00"), description="06:00-14:00")
        dt2 = DutyType(name="משמרת ערב", score_per_day=Decimal("1.50"), description="14:00-22:00")
        dt3 = DutyType(name="משמרת לילה", score_per_day=Decimal("2.00"), description="22:00-06:00")
        dt4 = DutyType(name="שבת", score_per_day=Decimal("3.00"), description="יום שבת")
        dt5 = DutyType(name="חג", score_per_day=Decimal("4.00"), description="יום חג")
        session.add_all([dt1, dt2, dt3, dt4, dt5])
        session.flush()
        duty_types = [dt1, dt2, dt3, dt4, dt5]

        # ── Duty Locations ─────────────────────────────────────────
        loc1 = DutyLocation(name="מפקדה ראשית", base="בסיס מרכז")
        loc2 = DutyLocation(name="שער ראשי", base="בסיס מרכז")
        loc3 = DutyLocation(name="מוצב צפון", base="בסיס צפון")
        loc4 = DutyLocation(name="חדר מבצעים", base="בסיס מרכז")
        session.add_all([loc1, loc2, loc3, loc4])
        session.flush()
        locations = [loc1, loc2, loc3, loc4]

        # ── Exemption Types ────────────────────────────────────────
        et1 = ExemptionType(name="רפואי", description="פטור רפואי זמני")
        et2 = ExemptionType(name="אימונים", description="פטור עקב אימונים")
        et3 = ExemptionType(name="משפחתי", description="פטור עקב סיבה משפחתית")
        session.add_all([et1, et2, et3])
        session.flush()

        session.add_all([
            ExemptionDutyTypeMap(exemption_type_id=et1.id, duty_type_id=dt1.id),
            ExemptionDutyTypeMap(exemption_type_id=et1.id, duty_type_id=dt2.id),
            ExemptionDutyTypeMap(exemption_type_id=et1.id, duty_type_id=dt3.id),
            ExemptionDutyTypeMap(exemption_type_id=et2.id, duty_type_id=dt4.id),
            ExemptionDutyTypeMap(exemption_type_id=et2.id, duty_type_id=dt5.id),
            ExemptionDutyTypeMap(exemption_type_id=et3.id, duty_type_id=dt1.id),
        ])

        # ── Duty Assignments for next 30 days ──────────────────────
        today = date.today()
        for i in range(30):
            day = today + timedelta(days=i)
            for _ in range(randint(2, 4)):
                s = choice(soldiers[6:])
                dt = choice(duty_types)
                loc = choice(locations)
                block_end = day + timedelta(days=randint(1, 3))
                existing = (
                    session.query(DutyAssignment)
                    .filter(
                        DutyAssignment.soldier_id == s.id,
                        DutyAssignment.status == "published",
                        DutyAssignment.start_date <= block_end,
                        DutyAssignment.end_date >= day,
                    )
                    .first()
                )
                if not existing:
                    da = DutyAssignment(
                        soldier_id=s.id,
                        duty_type_id=dt.id,
                        duty_location_id=loc.id,
                        start_date=day,
                        end_date=block_end,
                        status="published",
                        created_by=soldiers[0].id,
                    )
                    session.add(da)

        # ── Personal Constraints ────────────────────────────────────
        for i, s in enumerate(soldiers[6:12]):
            start_c = today + timedelta(days=10 + i)
            end_c = start_c + timedelta(days=2)
            statuses = ["pending", "approved", "rejected"]
            pc = PersonalConstraint(
                soldier_id=s.id,
                start_date=start_c,
                end_date=end_c,
                reason=f"סיבה אישית {i + 1}",
                status=statuses[i % 3],
                decided_by=soldiers[1].id if i % 3 != 0 else None,
            )
            session.add(pc)

        # ── Exemptions (manager-granted) ───────────────────────────
        for i, s in enumerate(soldiers[6:10]):
            se = SoldierExemption(
                soldier_id=s.id,
                exemption_type_id=et1.id if i % 2 == 0 else et2.id,
                start_date=today + timedelta(days=5),
                end_date=today + timedelta(days=15),
                reason="פטור זמני",
                granted_by=soldiers[0].id,
            )
            session.add(se)

        # ── Score Adjustments ──────────────────────────────────────
        for i, s in enumerate(soldiers[6:8]):
            sa = ScoreAdjustment(
                soldier_id=s.id,
                delta=Decimal("5.00") if i == 0 else Decimal("-2.00"),
                reason="תיקון ידני",
                created_by=soldiers[0].id,
            )
            session.add(sa)

        session.commit()
        print("Seed complete! Created:")
        print(f"  {len(all_nodes)} hierarchy nodes")
        print(f"  {len(soldiers)} soldiers")
        print(f"  {len(duty_types)} duty types")
        print(f"  {len(locations)} duty locations")
        print("  3 exemption types with mappings")
        print("  30 days of duty assignments")
        print("  6 personal constraints")
        print("  4 soldier exemptions")
        print("  2 score adjustments")


if __name__ == "__main__":
    import sys
    seed(force="--force" in sys.argv)
