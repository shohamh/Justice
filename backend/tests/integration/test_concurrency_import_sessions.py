"""C6 — import session confirmed twice / confirm vs cancel (audit inventory I1).

``confirm_session`` reads the import session, checks ``status == 'draft'``,
applies every row, and only at the end sets ``status = 'confirmed'``. There is
no row lock and no conditional ``UPDATE ... WHERE status = 'draft'``, so a
second confirm (double submit, second tab, retry) or a concurrent cancel that
read ``draft`` is not stopped.

Schedules reproduced here (two independent sessions = two HTTP requests):
  confirm vs confirm:
    1. both requests read the session (status=draft);
    2. both meet at a rendezvous right after that SELECT returns;
    3. both create the import's duty shift and commit.
  confirm vs cancel:
    1. the confirm request reads the session (status=draft) and parks;
    2. the cancel request reads draft, sets cancelled and commits;
    3. the confirm request resumes, creates the shift, sets confirmed, commits.

Fixed (Task 3): confirm_session and cancel_session load the import session
with ``SELECT ... FOR UPDATE``. The second request blocks on the row lock, so
the first request's wait times out and it commits alone; the second then reads
the committed status and fails with ``only_draft_sessions_can_be_*``.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import DutyLocation, DutyShift, DutyType, ImportSession, Soldier
from app.services import import_sessions as import_service
from tests.helpers import create_soldier


def _seed_draft(session):
    admin = create_soldier(session, personal_number="race-import-admin", role="admin")
    dt = DutyType(name="race-import-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="race-import-loc")
    session.add_all([dt, loc])
    session.flush()
    start = date.today() + timedelta(days=30)
    row = {
        "row": 2, "action": "new",
        "resolved_duty_type_id": str(dt.id), "resolved_duty_location_id": str(loc.id),
        "start_date": start.isoformat(), "end_date": (start + timedelta(days=1)).isoformat(),
        "required_count": 1,
    }
    import_session = ImportSession(
        filename="race.xlsx", status="draft", parsed_state={"duty_shifts": [row]},
        user_selections={}, created_by=admin.id,
    )
    session.add(import_session)
    session.commit()
    return import_session.id, admin.id


def _shift_count(session) -> int:
    session.expire_all()
    return session.execute(select(func.count()).select_from(DutyShift)).scalar_one()


def test_concurrent_confirms_apply_the_import_once(race, admin_session):
    session_id, admin_id = _seed_draft(admin_session)
    after_status_read = race.rendezvous(2, "both confirms read status=draft")

    def confirm():
        s = race.session()
        race.pause_after_select(s, ImportSession, after_status_read.wait)
        actor = s.get(Soldier, admin_id)
        result = import_service.confirm_session(s, session_id=session_id, actor=actor)
        s.commit()
        return result

    outcomes = race.run(confirm, confirm)

    for outcome in outcomes:
        if not outcome.ok and not isinstance(outcome.error, import_service.ImportSessionError):
            raise RuntimeError(f"confirm crashed: {outcome.error!r}") from outcome.error
    shifts = _shift_count(admin_session)
    assert shifts == 1, f"the one-row import created {shifts} duty shifts; outcomes={outcomes}"
    assert sum(o.ok for o in outcomes) == 1
    loser = next(o for o in outcomes if not o.ok)
    assert str(loser.error) == "only_draft_sessions_can_be_confirmed"


def test_cancel_committed_during_confirm_stops_the_import(race, admin_session):
    session_id, admin_id = _seed_draft(admin_session)
    confirm_read = race.signal("confirm read status=draft")
    cancel_done = race.signal("cancel committed")

    def confirm():
        s = race.session()

        def park():
            confirm_read.set()
            cancel_done.wait()

        race.pause_after_select(s, ImportSession, park)
        actor = s.get(Soldier, admin_id)
        result = import_service.confirm_session(s, session_id=session_id, actor=actor)
        s.commit()
        return result

    def cancel():
        confirm_read.wait()
        s = race.session()
        try:
            actor = s.get(Soldier, admin_id)
            import_service.cancel_session(s, session_id=session_id, actor=actor)
            s.commit()
        finally:
            cancel_done.set()
        return "cancelled"

    outcomes = race.run(confirm, cancel)

    for outcome in outcomes:
        if not outcome.ok and not isinstance(outcome.error, import_service.ImportSessionError):
            raise RuntimeError(f"racer crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    status = admin_session.get(ImportSession, session_id).status
    shifts = _shift_count(admin_session)
    assert sum(o.ok for o in outcomes) == 1, f"both confirm and cancel succeeded; final status={status!r}, shifts={shifts}"
    assert (status, shifts) in {("cancelled", 0), ("confirmed", 1)}, (status, shifts)
    # The confirm holds the row lock from its draft check, so the cancel waits
    # for it and then loses.
    assert (status, shifts) == ("confirmed", 1)
    assert str(outcomes[1].error) == "only_draft_sessions_can_be_cancelled"
