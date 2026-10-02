"""C1 — email outbox drained by concurrent workers (audit inventory N1).

Production runs ``uvicorn --workers 4`` and every process starts
``run_email_worker``. ``_drain_email_outbox`` selects unsent rows without a
claim (no ``FOR UPDATE SKIP LOCKED`` / conditional UPDATE), sends SMTP, then
sets ``sent_at``. Two drainers that read the same unsent row both send it.

Schedule reproduced here (two independent sessions, one per worker process):
  1. drainer A and drainer B each SELECT the unsent row (sent_at IS NULL);
  2. both reach ``send_email`` and meet at a rendezvous inside the stub;
  3. both "send", set sent_at and commit.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import email_worker
from app.db.models import EmailOutbox


def _seed_row(session) -> None:
    session.add(EmailOutbox(to_address="soldier@example.test", subject="s", html_body="<p>b</p>"))
    session.commit()


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="C1: concurrent _drain_email_outbox calls both send the same outbox row (no claim)",
)
def test_concurrent_drainers_send_each_outbox_row_once(race, admin_session, monkeypatch):
    _seed_row(admin_session)
    at_send = race.rendezvous(2, "both drainers inside send_email")
    sends: list[str] = []

    def fake_send_email(*, to, subject, html_body):
        sends.append(to)
        at_send.wait()
        return True

    monkeypatch.setattr(email_worker, "send_email", fake_send_email)

    outcomes = race.run(email_worker._drain_email_outbox, email_worker._drain_email_outbox)

    for outcome in outcomes:
        if not outcome.ok:
            raise RuntimeError(f"drainer crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    rows = admin_session.execute(select(EmailOutbox)).scalars().all()
    assert all(r.sent_at is not None for r in rows)
    assert len(sends) == 1, f"one outbox row was sent {len(sends)} times"


def test_single_drainer_sends_each_row_once(admin_session, monkeypatch):
    """Control: one drainer sends the row once and marks it sent; a second
    sequential drain finds nothing to send."""
    _seed_row(admin_session)
    sends: list[str] = []
    monkeypatch.setattr(email_worker, "send_email", lambda **kw: sends.append(kw["to"]) or True)

    email_worker._drain_email_outbox()
    email_worker._drain_email_outbox()

    assert sends == ["soldier@example.test"]
