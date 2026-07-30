from __future__ import annotations

from datetime import date

from app.services.bug_reports import BugReportRateLimitError, write_bug_report
from tests.helpers import create_soldier


def test_write_bug_report_daily_cap_enforced(admin_session):
    reporter = create_soldier(admin_session, personal_number="7900001")
    for i in range(50):
        write_bug_report(
            admin_session, reporter=reporter, description=f"bug {i}", severity="low",
            screenshot=None, route="/test", nav_history=[],
        )
        admin_session.flush()
    import pytest
    with pytest.raises(BugReportRateLimitError, match="daily_bug_report_limit_exceeded"):
        write_bug_report(
            admin_session, reporter=reporter, description="bug 51", severity="low",
            screenshot=None, route="/test", nav_history=[],
        )


def test_write_bug_report_cap_is_per_reporter(admin_session):
    reporter1 = create_soldier(admin_session, personal_number="7900002")
    reporter2 = create_soldier(admin_session, personal_number="7900003")
    for i in range(50):
        write_bug_report(
            admin_session, reporter=reporter1, description=f"bug {i}", severity="low",
            screenshot=None, route="/test", nav_history=[],
        )
        admin_session.flush()
    # reporter2 has made zero reports — must not be blocked by reporter1's cap
    result = write_bug_report(
        admin_session, reporter=reporter2, description="bug", severity="low",
        screenshot=None, route="/test", nav_history=[],
    )
    assert result.persisted_to_db is True
