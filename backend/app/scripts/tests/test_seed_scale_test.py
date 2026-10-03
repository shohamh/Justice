from collections import Counter
from datetime import date

import pytest

from app.scripts import seed_scale_test as seed


def test_scale_url_requires_an_explicit_safe_postgres_target() -> None:
    with pytest.raises(ValueError, match="JUSTICE_SCALE_DATABASE_URL"):
        seed.validate_target_database_url(None)

    safe_url = "postgresql+psycopg://scale-user:secret@localhost/justice_scale_20k"
    with pytest.raises(ValueError) as error:
        seed.validate_target_database_url(
            "postgresql://scale-user:secret@localhost/justice"
        )
    assert "secret" not in str(error.value)
    with pytest.raises(ValueError):
        seed.validate_target_database_url(
            "postgresql://scale-user:secret@localhost/postgres"
        )
    with pytest.raises(ValueError):
        seed.validate_target_database_url(
            "postgresql://scale-user:secret@localhost/justice_dev"
        )

    parsed = seed.validate_target_database_url(safe_url)
    assert parsed.database == "justice_scale_20k"


def test_normal_database_url_is_never_used_as_a_fallback() -> None:
    with pytest.raises(ValueError, match="JUSTICE_SCALE_DATABASE_URL"):
        seed.target_database_url({"DATABASE_URL": "postgresql://u:p@localhost/justice_scale"})


def test_unsafe_target_is_rejected_before_engine_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(seed, "create_engine", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(ValueError):
        seed.create_scale_engine(
            {"JUSTICE_SCALE_DATABASE_URL": "postgresql://u:p@localhost/justice"}
        )

    assert calls == []


@pytest.mark.parametrize(
    ("root_level", "level_ranks", "error_match"),
    [
        ("corps", {"corps": 1}, "no configured team"),
        ("corps", {"team": 7}, "root hierarchy level is not configured"),
        ("corps", {"corps": 7, "team": 7}, "must be below the root level"),
        ("corps", {"corps": 8, "team": 7}, "must be below the root level"),
    ],
)
def test_team_hierarchy_level_must_exist_below_root(
    root_level: str,
    level_ranks: dict[str, int],
    error_match: str,
) -> None:
    with pytest.raises(ValueError, match=error_match):
        seed.validate_team_hierarchy_level(root_level, level_ranks)


def test_team_hierarchy_level_accepts_configured_descendant_rank() -> None:
    seed.validate_team_hierarchy_level("corps", {"corps": 1, "team": 7})


def test_read_base_fixtures_reads_root_from_explicit_core_row_mapping() -> None:
    root_id = seed.synthetic_uuid("test-root", "1")
    duty_type_id = seed.synthetic_uuid("test-duty-type", "1")
    location_id = seed.synthetic_uuid("test-location", "1")

    class FakeScalars:
        def __init__(self, values: list[object]) -> None:
            self.values = values

        def __iter__(self):
            return iter(self.values)

        def all(self) -> list[object]:
            return self.values

    class FakeResult:
        def __init__(
            self, rows: list[object], scalar_values: list[object] | None = None
        ) -> None:
            self.rows = rows
            self.scalar_values = scalar_values or []

        def mappings(self) -> "FakeResult":
            return self

        def all(self) -> list[object]:
            return self.rows

        def scalars(self) -> FakeScalars:
            return FakeScalars(self.scalar_values)

    class FakeConnection:
        def __init__(self) -> None:
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)
            match len(self.statements):
                case 1:
                    return FakeResult(
                        [{"id": root_id, "level": "corps", "path_ids": [root_id]}],
                        [root_id],
                    )
                case 2:
                    return FakeResult([("corps", 1), ("team", 7)])
                case 3:
                    return FakeResult([], [duty_type_id])
                case 4:
                    return FakeResult([], [location_id])
                case _:
                    raise AssertionError("Unexpected query in fixture preflight")

    connection = FakeConnection()
    fixtures = seed._read_base_fixtures(connection)

    assert fixtures == (root_id, [root_id], [duty_type_id], [location_id])
    assert [column.key for column in connection.statements[0].selected_columns] == [
        "id",
        "level",
        "path_ids",
    ]


def test_default_synthetic_dataset_has_stable_counts_ids_and_date_range() -> None:
    config = seed.ScaleSeedConfig()

    assert config.soldiers == 20_000
    assert config.team_count == 400
    assert config.assignment_count == 1_000_000
    assert config.hr_profile_count == 20_000
    assert config.hr_exception_count == 200

    soldier_rows = list(seed.iter_soldier_rows(config, password_hash="test-hash"))
    assert len(soldier_rows) == 20_000
    assert soldier_rows[0]["personal_number"] == "SCALE20-00001"
    assert soldier_rows[-1]["personal_number"] == "SCALE20-20000"
    assert soldier_rows[0]["id"] == seed.synthetic_uuid("soldier", "00001")
    assert soldier_rows[0]["hierarchy_node_id"] == seed.synthetic_uuid("team", "0001")
    assert soldier_rows[-1]["hierarchy_node_id"] == seed.synthetic_uuid("team", "0400")
    assert soldier_rows == list(seed.iter_soldier_rows(config, password_hash="test-hash"))

    assignment_count = 0
    first_assignment = None
    last_assignment = None
    for assignment in seed.iter_assignment_specs(config):
        first_assignment = first_assignment or assignment
        last_assignment = assignment
        assignment_count += 1

    assert assignment_count == 1_000_000
    assert first_assignment["id"] == seed.synthetic_uuid("duty-assignment", "0000001")
    assert last_assignment["id"] == seed.synthetic_uuid("duty-assignment", "1000000")
    assert first_assignment["start_date"] == date(2024, 9, 30)
    assert last_assignment["start_date"] == date(2026, 9, 29)
    assert last_assignment["end_date"] == date(2026, 9, 29)


def test_hr_profiles_have_a_deterministic_one_percent_exception_split() -> None:
    config = seed.ScaleSeedConfig()
    profiles = list(seed.iter_hr_profile_rows(config))
    assert len(profiles) == 20_000
    assert profiles[0]["personal_number"] == "SCALE20-00001"
    assert profiles[-1]["personal_number"] == "SCALE20-20000"

    kinds = Counter(
        seed.hr_exception_kind(config, index) for index in range(config.soldiers)
    )
    assert {kind: count for kind, count in kinds.items() if kind is not None} == {
        "held": 50,
        "divergent": 50,
        "vanished": 50,
        "conflict": 50,
    }
    assert sum(row["sync_status"] == "held_for_review" for row in profiles) == 100
    assert sum(row["sync_status"] == "vanished" for row in profiles) == 50
    assert len(list(seed.iter_rank_conflict_rows(config))) == 50


def test_database_batches_are_capped_at_ten_thousand_rows() -> None:
    batches = list(seed.iter_batches(range(20_001)))

    assert [len(batch) for batch in batches] == [10_000, 10_000, 1]
    with pytest.raises(ValueError, match="10,000"):
        list(seed.iter_batches(range(1), batch_size=10_001))
