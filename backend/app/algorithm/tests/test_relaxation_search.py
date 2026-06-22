import dataclasses

from app.algorithm.solver import _ladder_positions
from app.algorithm.types import SolverSettings


def test_ladder_positions_relaxes_r_before_t():
    settings = SolverSettings(R=15, T=8, relax_r_ceiling=20, relax_t_ceiling=10)
    ladder = _ladder_positions(settings)
    labels = [labels for labels, _ in ladder]
    assert labels == [
        ["R→17"],
        ["R→17", "R→19"],
        ["R→17", "R→19", "R→20"],
        ["R→17", "R→19", "R→20", "T→10"],
    ]
    # Each position's settings carries the cumulative R/T values.
    assert ladder[0][1].R == 17 and ladder[0][1].T == 8
    assert ladder[2][1].R == 20 and ladder[2][1].T == 8
    assert ladder[3][1].R == 20 and ladder[3][1].T == 10


def test_ladder_positions_empty_when_ceiling_equals_base():
    settings = SolverSettings(R=1, T=1, relax_r_ceiling=1, relax_t_ceiling=1)
    assert _ladder_positions(settings) == []


def test_ladder_positions_does_not_mutate_input_settings():
    settings = SolverSettings(R=15, T=8, relax_r_ceiling=20, relax_t_ceiling=10)
    _ladder_positions(settings)
    assert settings.R == 15
    assert settings.T == 8
