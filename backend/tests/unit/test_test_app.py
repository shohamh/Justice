import asyncio
import os

import pytest

from tests.support import app as test_app_support


def test_test_app_sets_testing_flag_only_for_its_context(monkeypatch) -> None:
    """Catch a helper that leaks JUSTICE_TESTING into later app lifecycles."""
    monkeypatch.setenv("JUSTICE_TESTING", "preserved-value")

    with test_app_support.test_app():
        assert os.environ["JUSTICE_TESTING"] == "1"

    assert os.environ["JUSTICE_TESTING"] == "preserved-value"


def test_test_client_isolates_client_and_rate_limit_state(monkeypatch) -> None:
    """Catch a session-scoped client that retains one test's mutable process state."""
    import app.main as main

    from app.rate_limit import limiter

    monkeypatch.setattr(main, "_fail_orphaned_algorithm_jobs", lambda: None)
    key = "test-test-client-isolation"
    with test_app_support.test_client() as first_client:
        first_app = first_client.app
        first_client.headers["Authorization"] = "Bearer first-client-token"
        first_client.cookies.set("refresh_token", "first-client-cookie")
        assert limiter._storage.incr(key, expiry=60) == 1

    with test_app_support.test_client() as second_client:
        assert second_client.app is not first_app
        assert second_client.headers.get("Authorization") is None
        assert second_client.cookies.get("refresh_token") is None
        assert limiter._storage.get(key) == 0


def test_test_lifespan_does_not_start_background_workers(monkeypatch) -> None:
    """Catch removal of the test-only worker suppression branch in lifespan."""
    import app.main as main

    started_workers: list[str] = []

    async def worker_that_must_not_start() -> None:
        started_workers.append("started")
        await asyncio.Event().wait()

    for worker_name in (
        "run_email_worker",
        "run_swap_expiry_worker",
        "run_range_reminder_worker",
        "run_range_attendance_worker",
        "run_duty_eligibility_worker",
        "run_rank_advancement_worker",
        "run_qualification_expiry_worker",
    ):
        monkeypatch.setattr(main, worker_name, worker_that_must_not_start)
    monkeypatch.setattr(main, "_fail_orphaned_algorithm_jobs", lambda: None)

    with test_app_support.test_client():
        pass

    assert started_workers == []


def test_test_lifespan_recovers_orphaned_jobs_before_worker_suppression(monkeypatch) -> None:
    """Catch a test-mode branch that skips startup data recovery with workers."""
    import app.main as main

    recoveries: list[str] = []
    monkeypatch.setattr(main, "_fail_orphaned_algorithm_jobs", lambda: recoveries.append("recovered"))

    with test_app_support.test_client():
        pass

    assert recoveries == ["recovered"]


@pytest.mark.parametrize("fixture_invocation", [1, 2])
def test_client_fixture_does_not_share_client_state_between_test_invocations(client, fixture_invocation) -> None:
    """Catch changing pytest's real client fixture from function to session scope."""
    if fixture_invocation == 1:
        client.headers["Authorization"] = "Bearer fixture-token"
        client.cookies.set("refresh_token", "fixture-cookie")
        return

    assert client.headers.get("Authorization") is None
    assert client.cookies.get("refresh_token") is None
