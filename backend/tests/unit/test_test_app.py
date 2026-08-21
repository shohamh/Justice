import asyncio
import os

from tests.support import app as test_app_support


def test_test_app_sets_testing_flag_only_for_its_context(monkeypatch) -> None:
    """Catch a helper that leaks JUSTICE_TESTING into later app lifecycles."""
    monkeypatch.setenv("JUSTICE_TESTING", "preserved-value")

    with test_app_support.test_app():
        assert os.environ["JUSTICE_TESTING"] == "1"

    assert os.environ["JUSTICE_TESTING"] == "preserved-value"


def test_test_client_isolates_client_and_rate_limit_state() -> None:
    """Catch a session-scoped client that retains one test's mutable process state."""
    from app.rate_limit import limiter

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

    with test_app_support.test_client() as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert started_workers == []
