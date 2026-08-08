from __future__ import annotations

from unittest.mock import patch

from app.duty_eligibility_worker import _recheck_all_published_weapon_assignments


def test_worker_function_calls_recheck_assignments_and_handles_errors() -> None:
    with patch("app.duty_eligibility_worker.session_scope") as mock_scope, \
         patch("app.duty_eligibility_worker.recheck_assignments") as mock_recheck:
        mock_session = mock_scope.return_value.__enter__.return_value
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        mock_recheck.return_value = 0
        _recheck_all_published_weapon_assignments()
        mock_scope.assert_called_once()
