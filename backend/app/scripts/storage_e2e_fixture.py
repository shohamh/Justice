"""Create isolated database rows for the storage browser E2E harness."""

from __future__ import annotations

import json
import uuid
from datetime import date

from app.db.models import DutyAssignment, DutyDismissal, DutyLocation, DutyType, Soldier
from app.db.session import SessionLocal


def main() -> None:
    with SessionLocal() as session:
        soldier = session.query(Soldier).filter_by(personal_number="1000010").one()
        suffix = uuid.uuid4().hex[:12]
        duty_type = DutyType(name=f"Storage E2E {suffix}", score_per_day=1)
        location = DutyLocation(name=f"Storage E2E {suffix}")
        session.add_all([duty_type, location])
        session.flush()

        today = date.today()
        assignment = DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            start_date=today,
            end_date=today,
        )
        session.add(assignment)
        session.flush()

        dismissal = DutyDismissal(
            duty_assignment_id=assignment.id,
            dismissed_from=today,
            dismissed_to=today,
            is_gimelim=True,
        )
        session.add(dismissal)
        session.commit()
        print(json.dumps({"dismissal_id": str(dismissal.id)}))


if __name__ == "__main__":
    main()
