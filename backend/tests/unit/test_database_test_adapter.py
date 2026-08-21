from pathlib import Path

from tests.support import database


def test_reset_tables_keep_referencing_tables_before_their_dependencies() -> None:
    tables = database.RESET_TABLES

    assert len(tables) == len(set(tables))
    assert tables.index("audit_log") < tables.index("soldiers")
    assert tables.index("duty_assignments") < tables.index("duty_types")
    assert tables.index("range_events") < tables.index("range_locations")
    assert tables.index("hierarchy_nodes") == len(tables) - 1


def test_reset_statement_restarts_identities_and_cascades() -> None:
    statement = database.RESET_DATABASE_STATEMENT

    assert statement.startswith("TRUNCATE audit_log, bug_reports")
    assert statement.endswith("RESTART IDENTITY CASCADE")


def test_seed_statements_preserve_current_settings_and_hierarchy_defaults() -> None:
    settings = dict(database.SYSTEM_SETTINGS_DEFAULTS)
    hierarchy = {
        key: (label, rank)
        for key, label, rank in database.HIERARCHY_LEVEL_TYPE_DEFAULTS
    }

    assert settings["auth.session_minutes"] == "15"
    assert settings["eligibility.mitvahim_months"] == "6"
    assert settings["mitvachim.excusal_approve_min_commander_level"] == '"מדור"'
    assert hierarchy["corps"] == ("אגף", 1)
    assert hierarchy["team"] == ("צוות", 7)
    assert "INSERT INTO system_settings" in database.SYSTEM_SETTINGS_SEED_STATEMENT
    assert "INSERT INTO hierarchy_level_types" in database.HIERARCHY_LEVEL_TYPES_SEED_STATEMENT


def test_focused_runtime_migrates_but_shared_worker_clone_does_not(monkeypatch) -> None:
    migrated_urls: list[str] = []
    monkeypatch.setattr(database, "run_migrations", lambda url, root: migrated_urls.append(url))

    focused = database.TestDatabaseRuntime.for_database(
        "postgresql+psycopg://db_admin:db_admin_pw@localhost/focused",
        Path("."),
        cloned_from_template=False,
    )
    shared_worker = database.TestDatabaseRuntime.for_database(
        "postgresql+psycopg://db_admin:db_admin_pw@localhost/worker_clone",
        Path("."),
        cloned_from_template=True,
    )

    focused.migrate_schema()
    shared_worker.migrate_schema()

    assert focused.requires_migration is True
    assert shared_worker.requires_migration is False
    assert migrated_urls == [focused.database_url]
