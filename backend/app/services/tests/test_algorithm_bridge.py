from __future__ import annotations

from app.services.algorithm_bridge import resolve_solver_settings
from app.services.settings_loader import set_setting


def test_resolve_solver_settings_uses_system_defaults(admin_session):
    set_setting(admin_session, "algorithm.max_duties_per_window", 6, actor_id=None)
    set_setting(admin_session, "algorithm.max_total_duties_per_window", 10, actor_id=None)
    set_setting(admin_session, "algorithm.window_t", 21, actor_id=None)
    set_setting(admin_session, "algorithm.window_r", 35, actor_id=None)
    set_setting(admin_session, "algorithm.relax_t_ceiling", 8, actor_id=None)
    set_setting(admin_session, "algorithm.relax_r_ceiling", 15, actor_id=None)
    admin_session.flush()

    s = resolve_solver_settings(admin_session, {})
    assert s.T == 6
    assert s.R == 10
    assert s.Wt == 21
    assert s.Wr == 35
    assert s.relax_t_ceiling == 8
    assert s.relax_r_ceiling == 15


def test_resolve_solver_settings_per_run_overrides_win(admin_session):
    set_setting(admin_session, "algorithm.max_total_duties_per_window", 10, actor_id=None)
    admin_session.flush()
    s = resolve_solver_settings(admin_session, {"T": 5, "R": 9, "Wt": 14, "Wr": 28})
    assert s.T == 5
    assert s.R == 9
    assert s.Wt == 14
    assert s.Wr == 28


def test_resolve_solver_settings_falls_back_to_hardcoded_defaults(admin_session):
    s = resolve_solver_settings(admin_session, {})
    assert s.T == 8
    assert s.R == 15
    assert s.Wt == 14
    assert s.Wr == 28
    assert s.relax_t_ceiling == 10
    assert s.relax_r_ceiling == 20
