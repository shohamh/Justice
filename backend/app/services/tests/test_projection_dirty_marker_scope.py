from datetime import date

from sqlalchemy import event

from app.db.models import ScoreProjectionDirtyBucket
from app.services.score_projection import projection_is_current
from tests.helpers import create_soldier


def test_required_bucket_read_selects_scoped_scalar_dirty_keys(admin_session, admin_engine):
    required = create_soldier(admin_session, personal_number="dirty-scope-required")
    unrelated = create_soldier(admin_session, personal_number="dirty-scope-unrelated")
    target = date(2026, 7, 1)
    other_quarter = date(2026, 10, 1)
    unrelated_marker = ScoreProjectionDirtyBucket(
        soldier_id=unrelated.id, quarter_start=target, status="dirty"
    )
    wrong_quarter_marker = ScoreProjectionDirtyBucket(
        soldier_id=required.id, quarter_start=other_quarter, status="dirty"
    )
    admin_session.add_all([unrelated_marker, wrong_quarter_marker])
    admin_session.flush()

    statements = []

    def capture_dirty_reads(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "FROM score_projection_dirty_buckets" in statement:
            statements.append(statement)

    event.listen(admin_engine, "before_cursor_execute", capture_dirty_reads)
    try:
        assert projection_is_current(admin_session, {(required.id, target)})
        assert len(statements) == 1
        selected, predicate = statements[0].split("FROM score_projection_dirty_buckets", 1)
        assert "score_projection_dirty_buckets.soldier_id" in selected
        assert "score_projection_dirty_buckets.quarter_start" in selected
        assert "score_projection_dirty_buckets.id" not in selected
        assert "score_projection_dirty_buckets.old_node_ids" not in selected
        assert "score_projection_dirty_buckets.soldier_id" in predicate
        assert "score_projection_dirty_buckets.quarter_start" in predicate

        exact_marker = ScoreProjectionDirtyBucket(
            soldier_id=required.id, quarter_start=target, status="dirty"
        )
        admin_session.add(exact_marker)
        admin_session.flush()
        assert not projection_is_current(admin_session, {(required.id, target)})

        exact_marker.status = "current"
        admin_session.flush()
        assert not projection_is_current(admin_session, {target})
        unrelated_marker.status = "current"
        admin_session.flush()
        assert projection_is_current(admin_session, {target})
    finally:
        event.remove(admin_engine, "before_cursor_execute", capture_dirty_reads)
