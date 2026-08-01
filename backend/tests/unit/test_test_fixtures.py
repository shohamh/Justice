from types import SimpleNamespace

import pytest

from tests.conftest import _item_needs_database


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
