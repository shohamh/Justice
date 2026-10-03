"""Schema regression for the transparency planning-horizon lookup."""

from sqlalchemy import text


def test_published_assignment_end_date_has_leading_status_index(admin_session):
    index_definition = admin_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = current_schema() "
            "AND tablename = 'duty_assignments' "
            "AND indexname = 'ix_duty_assignments_status_end_date'"
        )
    ).scalar_one_or_none()

    assert index_definition is not None
    assert "(status, end_date DESC)" in index_definition
