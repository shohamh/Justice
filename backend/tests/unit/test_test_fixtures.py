from types import SimpleNamespace

import pytest

from tests.conftest import _apply_schema, _item_needs_database, _truncate_tables


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
