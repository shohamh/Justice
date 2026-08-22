import pytest

from tests import conftest


class _CollectedItem:
    def __init__(self, nodeid: str, *fixturenames: str) -> None:
        self.nodeid = nodeid
        self.fixturenames = list(fixturenames)
        self.keywords: dict[str, object] = {}
        self.markers: list[str] = []

    def add_marker(self, marker) -> None:
        self.markers.append(marker.name)


class _DeselectionHook:
    def pytest_deselected(self, *, items: list[_CollectedItem]) -> None:
        raise AssertionError(f"no regular item should be deselected: {items}")


class _CollectionConfig:
    hook = _DeselectionHook()

    @staticmethod
    def getoption(option: str) -> bool:
        return option == "--slow"


def _collected_item(nodeid: str, *fixturenames: str) -> _CollectedItem:
    return _CollectedItem(nodeid, *fixturenames)


@pytest.mark.parametrize(
    ("item", "expected_markers"),
    [
        (
            _collected_item(
                "app/algorithm/tests/test_solver.py::test_solve_basic",
                "request",
                "_apply_schema",
                "_reset_rate_limiter",
                "_truncate_tables",
            ),
            ["pure"],
        ),
        (
            _collected_item(
                "tests/unit/test_model.py::test_fairness_all_zero_scores_distributes",
                "request",
                "_apply_schema",
                "_reset_rate_limiter",
                "_truncate_tables",
            ),
            ["pure", "algorithm"],
        ),
    ],
)
def test_pure_algorithm_items_do_not_require_database_fixtures_and_receive_markers(
    item: _CollectedItem, expected_markers: list[str]
) -> None:
    assert conftest._item_needs_database(item) is False
    assert conftest.item_layer(item) == "pure"
    _assign_collection_markers(item)
    assert item.markers == expected_markers


@pytest.mark.parametrize(
    ("item", "expected_layer", "expected_markers"),
    [
        (
            _collected_item(
                "tests/unit/test_algorithm_bridge.py::test_load_soldier_inputs_basic",
                "request",
                "admin_session",
                "admin_engine",
                "db_admin_url",
                "_apply_schema",
                "_reset_rate_limiter",
                "_truncate_tables",
            ),
            "database",
            ["database", "algorithm"],
        ),
        (
            _collected_item(
                "tests/integration/test_health.py::test_health_returns_ok",
                "request",
                "client",
                "_apply_schema",
                "_reset_rate_limiter",
                "_truncate_tables",
            ),
            "http",
            ["http", "misc"],
        ),
    ],
)
def test_service_and_route_items_are_classified_and_marked_by_required_fixture(
    item: _CollectedItem, expected_layer: str, expected_markers: list[str]
) -> None:
    assert conftest._item_needs_database(item) is True
    assert conftest.item_layer(item) == expected_layer
    _assign_collection_markers(item)
    assert item.markers == expected_markers


def _assign_collection_markers(item: _CollectedItem) -> None:
    conftest.pytest_collection_modifyitems(_CollectionConfig(), [item])
