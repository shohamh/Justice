from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def test_weapon_ineligible_columns_exist_with_correct_defaults(app_session: Session) -> None:
    row = app_session.execute(
        text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'duty_assignments' AND column_name = 'weapon_ineligible'"
        )
    ).mappings().first()
    assert row is not None
    assert row["data_type"] == "boolean"
    assert row["is_nullable"] == "NO"

    reason_row = app_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'duty_assignments' AND column_name = 'weapon_ineligible_reason'"
        )
    ).mappings().first()
    assert reason_row is not None
    assert reason_row["is_nullable"] == "YES"

    detected_row = app_session.execute(
        text(
            "SELECT is_nullable, data_type FROM information_schema.columns "
            "WHERE table_name = 'duty_assignments' AND column_name = 'weapon_ineligible_detected_at'"
        )
    ).mappings().first()
    assert detected_row is not None
    assert detected_row["is_nullable"] == "YES"
    assert detected_row["data_type"] == "timestamp with time zone"


def test_weapon_ineligible_partial_index_exists(app_session: Session) -> None:
    row = app_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'duty_assignments' AND indexname = 'ix_duty_assignments_weapon_ineligible'"
        )
    ).mappings().first()
    assert row is not None
    assert "weapon_ineligible" in row["indexdef"]
