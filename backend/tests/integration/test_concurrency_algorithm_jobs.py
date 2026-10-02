"""C13 — algorithm job status transitions race with a cancel (audit inventory J1, J4).

Three schedules, each with independent sessions:

* **Start vs cancel.** ``run_algorithm_job`` reads the job (``pending``), and
  only then writes ``running`` unconditionally. A user cancel that commits in
  between (``failed`` / ``cancelled_by_user``) is overwritten with ``running``
  and the solve goes ahead.
* **Cancel vs finish.** ``DELETE /algorithm/jobs/{id}`` checks
  ``status in (pending, running)`` on an unlocked read and writes ``failed``.
  If the runner commits ``done`` (drafts persisted, "done" notification sent)
  after that read, the cancel overwrites it, so the job reports a cancel the
  user never got.
* **Startup hook vs live job.** ``_fail_orphaned_algorithm_jobs`` runs in every
  web worker process at startup and fails every ``running`` job, including one
  that a sibling process is solving right now.

The audit's original J1 hypothesis (a cancel committing between the runner's
``session.refresh(job)`` and its final commit) cannot happen as written: by
then ``persist_results`` has flushed an UPDATE of the job row, so the cancel
blocks on that row lock until the runner commits. The second schedule above
is what that cancel actually does once the lock is released.

Fixed (Task 4):
* the runner claims the job with ``UPDATE ... WHERE status='pending'`` and
  returns when the claim matches no row;
* ``cancel_job`` (and the timeout watchdog) re-read the job ``FOR UPDATE``
  before checking its status, so a finished job gets 409 ``not_cancellable``;
* the runner holds a session-level advisory lock for the job on a dedicated
  connection for the whole run; the startup hook fails a ``running`` job only
  when it can take that lock (its owner connection is gone).
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal

from app.db.models import AlgorithmJob, DutyLocation, DutyShift, DutyType, Soldier
from tests.helpers import create_node, create_soldier


class _StopRun(Exception):
    pass


def _seed(session, pn: str, *, status: str = "pending"):
    node = create_node(session, level="branch", name=f"race-job-{pn}")
    dm = create_soldier(session, personal_number=f"race-job-{pn}-dm", role="duty_manager", hierarchy_node_id=node.id)
    create_soldier(session, personal_number=f"race-job-{pn}-s", hierarchy_node_id=node.id)
    dt = DutyType(name=f"race-job-{pn}-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"race-job-{pn}-loc")
    session.add_all([dt, loc])
    session.flush()
    shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id, start_date="2028-06-01",
                      end_date="2028-06-01", required_count=1)
    session.add(shift)
    session.flush()
    job = AlgorithmJob(
        planning_start=shift.start_date, planning_end=shift.end_date, shift_ids=[str(shift.id)],
        settings_json={"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 10},
        mode="shadow", created_by=dm.id, status=status,
    )
    session.add(job)
    session.commit()
    return job.id, dm.id


def _status(session, job_id):
    session.expire_all()
    job = session.get(AlgorithmJob, job_id)
    return job.status, job.error_message


def _cancel(race, job_id, dm_id):
    from app.routes import algorithm as algorithm_routes

    s = race.session()
    algorithm_routes.cancel_job(job_id=job_id, session=s, user=s.get(Soldier, dm_id))
    return "cancelled"


def _hook_runner_session(race, monkeypatch, hook):
    """Park the runner's first session right after its first AlgorithmJob SELECT."""
    import app.db.session as db_session

    real_scope = db_session.session_scope
    hooked = False

    @contextmanager
    def scope():
        nonlocal hooked
        with real_scope() as s:
            if not hooked:
                hooked = True
                race.pause_after_select(s, AlgorithmJob, hook)
            yield s

    monkeypatch.setattr(db_session, "session_scope", scope)


def test_cancel_committed_before_the_runner_starts_is_not_overwritten(race, admin_session, monkeypatch):
    from app.services import algorithm_bridge

    job_id, dm_id = _seed(admin_session, "start")
    runner_read = race.signal("runner read the pending job")
    cancel_done = race.signal("cancel committed")
    solved_after_cancel: list[str] = []

    def _after_read():
        runner_read.set()
        cancel_done.wait()

    _hook_runner_session(race, monkeypatch, _after_read)

    def stop_before_solving(session, settings_json):
        # Reached only once the runner has committed its own 'running'
        # transition; record what it overwrote, then stop the run here.
        with race.session() as probe:
            solved_after_cancel.append(probe.get(AlgorithmJob, job_id).status)
        raise _StopRun("stopped by test")

    monkeypatch.setattr(algorithm_bridge, "resolve_solver_settings", stop_before_solving)

    def runner():
        algorithm_bridge.run_algorithm_job(job_id, None)

    def cancel():
        runner_read.wait()
        try:
            return _cancel(race, job_id, dm_id)
        finally:
            cancel_done.set()

    run_outcome, cancel_outcome = race.run(runner, cancel)

    assert cancel_outcome.ok, cancel_outcome
    assert run_outcome.ok, run_outcome
    assert solved_after_cancel == [], f"runner moved the cancelled job to {solved_after_cancel} and started solving"
    assert _status(admin_session, job_id) == ("failed", "cancelled_by_user")


def test_cancel_cannot_overwrite_a_job_that_finished_after_its_read(race, admin_session):
    from fastapi import HTTPException

    from app.routes import algorithm as algorithm_routes

    job_id, dm_id = _seed(admin_session, "finish", status="running")

    def finish(s):
        # Stand-in for the runner's final commit (status='done' plus drafts
        # and the 'done' notification in the real run).
        job = s.get(AlgorithmJob, job_id)
        job.status = "done"
        return "done"

    def late_cancel(s, _job):
        algorithm_routes.cancel_job(job_id=job_id, session=s, user=s.get(Soldier, dm_id))
        return "cancelled"

    cancelled, finished = race.stale_write(
        read=lambda s: s.get(AlgorithmJob, job_id), write=late_cancel, decide=finish,
    )

    if not cancelled.ok and not isinstance(cancelled.error, HTTPException):
        raise RuntimeError(f"cancel crashed: {cancelled.error!r}") from cancelled.error
    final = _status(admin_session, job_id)
    assert final == ("done", None), f"finish={finished!r}, cancel={cancelled!r}; final={final}"
    assert (cancelled.error.status_code, cancelled.error.detail) == (409, "not_cancellable")


def test_startup_hook_does_not_fail_a_job_another_process_is_solving(race, admin_session, monkeypatch):
    from app.main import _fail_orphaned_algorithm_jobs
    from app.services import algorithm_bridge

    job_id, _dm_id = _seed(admin_session, "orphan")
    runner_solving = race.signal("runner is mid-solve")
    hook_done = race.signal("startup hook ran")
    status_after_hook: list[tuple] = []
    real_resolve = algorithm_bridge.resolve_solver_settings

    def resolve_mid_run(session, settings_json):
        runner_solving.set()
        hook_done.wait()
        return real_resolve(session, settings_json)

    monkeypatch.setattr(algorithm_bridge, "resolve_solver_settings", resolve_mid_run)

    def runner():
        algorithm_bridge.run_algorithm_job(job_id, None)

    def sibling_process_starts():
        runner_solving.wait()
        try:
            _fail_orphaned_algorithm_jobs()
            with race.session() as probe:
                job = probe.get(AlgorithmJob, job_id)
                status_after_hook.append((job.status, job.error_message))
        finally:
            hook_done.set()

    race.run(runner, sibling_process_starts)

    assert status_after_hook == [("running", None)], f"startup hook left the live job as {status_after_hook}"
    final_status, final_error = _status(admin_session, job_id)
    assert "server_restarted" not in (final_error or ""), (final_status, final_error)
    assert final_status in ("done", "failed")


def test_startup_hook_still_fails_a_job_whose_runner_is_gone(admin_session):
    """Control: with no live runner holding the job's lock, the row is an orphan."""
    from app.main import _fail_orphaned_algorithm_jobs

    job_id, _dm_id = _seed(admin_session, "dead", status="running")

    _fail_orphaned_algorithm_jobs()

    assert _status(admin_session, job_id) == (
        "failed", '{"status": "INTERRUPTED", "reason": "server_restarted"}',
    )
