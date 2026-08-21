from types import SimpleNamespace

import pytest

from tests import conftest
from tests.conftest import (
    _apply_schema,
    _item_needs_database,
    _shared_postgres_enabled,
    _truncate_tables,
    _worker_database_name,
    pytest_collection_modifyitems,
)


@pytest.mark.parametrize(
    "fixturenames",
    [
        [],
        ["tmp_path"],
        ["monkeypatch", "caplog"],
    ],
)
def test_item_needs_database_returns_false_without_database_fixtures(
    fixturenames: list[str],
) -> None:
    item = SimpleNamespace(fixturenames=fixturenames)

    assert _item_needs_database(item) is False


@pytest.mark.parametrize("fixture_name", ["client", "admin_session"])
def test_item_needs_database_returns_true_for_database_fixture(fixture_name: str) -> None:
    item = SimpleNamespace(fixturenames=[fixture_name])

    assert _item_needs_database(item) is True


def test_apply_schema_skips_database_url_for_pure_collected_items() -> None:
    requested_fixtures: list[str] = []
    request = SimpleNamespace(
        session=SimpleNamespace(items=[SimpleNamespace(fixturenames=["tmp_path"])]),
        getfixturevalue=requested_fixtures.append,
    )

    _apply_schema.__wrapped__(request)

    assert requested_fixtures == []


def test_apply_schema_requests_database_url_for_database_collected_items() -> None:
    class DatabaseUrlRequested(Exception):
        pass

    def getfixturevalue(fixture_name: str) -> str:
        assert fixture_name == "db_admin_url"
        raise DatabaseUrlRequested

    request = SimpleNamespace(
        session=SimpleNamespace(items=[SimpleNamespace(fixturenames=["client"])]),
        getfixturevalue=getfixturevalue,
    )

    with pytest.raises(DatabaseUrlRequested):
        _apply_schema.__wrapped__(request)


def test_truncate_tables_skips_admin_engine_for_pure_item() -> None:
    requested_fixtures: list[str] = []
    request = SimpleNamespace(
        node=SimpleNamespace(fixturenames=["tmp_path"]),
        getfixturevalue=requested_fixtures.append,
    )

    fixture = _truncate_tables.__wrapped__(request)

    next(fixture)
    with pytest.raises(StopIteration):
        next(fixture)
    assert requested_fixtures == []


def test_truncate_tables_requests_admin_engine_for_database_item() -> None:
    class AdminEngineRequested(Exception):
        pass

    def getfixturevalue(fixture_name: str) -> None:
        assert fixture_name == "admin_engine"
        raise AdminEngineRequested

    request = SimpleNamespace(
        node=SimpleNamespace(fixturenames=["client"]),
        getfixturevalue=getfixturevalue,
    )

    fixture = _truncate_tables.__wrapped__(request)

    with pytest.raises(AdminEngineRequested):
        next(fixture)


def test_shared_postgres_enabled_for_full_parallel_suite(tmp_path) -> None:
    config = SimpleNamespace(
        workerinput=None,
        option=SimpleNamespace(numprocesses=4, markexpr=""),
        rootpath=tmp_path,
        args=[],
    )

    assert _shared_postgres_enabled(config) is True


@pytest.mark.parametrize(
    "markexpr",
    [
        "pure",
        "  pure  ",
        "pure and not slow",
        "not slow and pure",
        "(pure)",
        "((pure and not slow))",
        "pure and algorithm",
        "pure and not algorithm",
    ],
)
def test_pure_only_selected_accepts_conjunctions_requiring_pure(markexpr: str) -> None:
    config = SimpleNamespace(option=SimpleNamespace(markexpr=markexpr))

    assert conftest._pure_only_selected(config) is True


@pytest.mark.parametrize(
    "markexpr",
    [
        "",
        "database",
        "http",
        "not pure",
        "pure or pure",
        "pure or database",
        "pure and database",
        "pure and not database",
        "pure and http",
        "pure and not http",
        "pure and unknown_marker",
        "pure and not unknown_marker",
        "pure and (not slow or algorithm)",
    ],
)
def test_pure_only_selected_rejects_expressions_that_may_not_be_pure(markexpr: str) -> None:
    config = SimpleNamespace(option=SimpleNamespace(markexpr=markexpr))

    assert conftest._pure_only_selected(config) is False


@pytest.mark.parametrize(
    ("markexpr", "expected"),
    [
        ("pure", False),
        ("pure and not slow", False),
        ("not slow and (pure)", False),
        ("database", True),
        ("http", True),
        ("pure and unknown_marker", True),
        ("pure or database", True),
    ],
)
def test_shared_postgres_starts_only_when_marker_selection_can_need_database(
    tmp_path, markexpr: str, expected: bool
) -> None:
    config = SimpleNamespace(
        workerinput=None,
        option=SimpleNamespace(numprocesses=4, markexpr=markexpr),
        rootpath=tmp_path,
        args=[],
    )

    assert _shared_postgres_enabled(config) is expected


@pytest.mark.parametrize(
    ("markexpr", "args"),
    [
        ("pure", []),
        ("pure and not slow", []),
        ("not slow and (pure)", []),
        ("pure", ["tests/unit/test_model.py::test_fairness_all_zero_scores_distributes"]),
    ],
)
def test_pytest_configure_does_not_create_container_for_pure_only_selection(
    monkeypatch, tmp_path, markexpr: str, args: list[str]
) -> None:
    configured_markers: list[tuple[str, str]] = []
    config = SimpleNamespace(
        workerinput=None,
        option=SimpleNamespace(numprocesses=4, markexpr=markexpr),
        rootpath=tmp_path,
        args=args,
        addinivalue_line=lambda name, value: configured_markers.append((name, value)),
    )

    def unexpected_container():
        raise AssertionError("pure-only selection must not create a PostgreSQL container")

    monkeypatch.setattr(conftest, "_new_postgres_container", unexpected_container)

    conftest.pytest_configure(config)

    assert len(configured_markers) == 3


@pytest.mark.parametrize(
    ("numprocesses", "args", "workerinput"),
    [
        (0, [], None),
        (4, ["tests"], None),
        (4, ["tests/unit/test_jwt_tokens.py"], None),
        (4, [], {"workerid": "gw0"}),
    ],
)
def test_shared_postgres_disabled_outside_full_parallel_controller(
    tmp_path, numprocesses, args, workerinput
) -> None:
    config = SimpleNamespace(
        workerinput=workerinput,
        option=SimpleNamespace(numprocesses=numprocesses, markexpr=""),
        rootpath=tmp_path,
        args=[str(tmp_path / arg) for arg in args],
    )

    assert _shared_postgres_enabled(config) is False


def test_worker_database_name_is_safe_and_bounded() -> None:
    name = _worker_database_name({"testrunuid": "ABC-123/unsafe" * 10, "workerid": "gw-7"})

    assert name.startswith("pytest_")
    assert name.replace("_", "").isalnum()
    assert name == name.lower()
    assert len(name) <= 63


class _CollectedItem:
    def __init__(self, nodeid: str, *, slow: bool = False) -> None:
        self.nodeid = nodeid
        self.fixturenames: list[str] = []
        self.keywords = {"slow": object()} if slow else {}
        self.markers: list[str] = []

    def add_marker(self, marker) -> None:
        self.markers.append(marker.name)


class _DeselectionHook:
    def __init__(self) -> None:
        self.items: list[_CollectedItem] = []

    def pytest_deselected(self, *, items: list[_CollectedItem]) -> None:
        self.items.extend(items)


@pytest.mark.parametrize("include_slow", [False, True])
def test_collection_includes_slow_items_only_with_slow_option(include_slow: bool) -> None:
    slow_item = _CollectedItem("tests/unit/test_fairness_e2e.py::test_large")
    slow_item.keywords["slow"] = object()
    regular_item = _CollectedItem("tests/unit/test_model.py::test_small")
    deselection_hook = _DeselectionHook()
    config = SimpleNamespace(
        getoption=lambda option: include_slow if option == "--slow" else None,
        hook=deselection_hook,
    )
    items = [slow_item, regular_item]

    pytest_collection_modifyitems(config, items)

    expected_items = [slow_item, regular_item] if include_slow else [regular_item]
    expected_deselected = [] if include_slow else [slow_item]
    assert items == expected_items
    assert deselection_hook.items == expected_deselected
    assert regular_item.markers == ["pure", "algorithm"]
    assert slow_item.markers == (["pure", "algorithm"] if include_slow else [])
