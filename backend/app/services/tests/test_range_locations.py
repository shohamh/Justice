from __future__ import annotations


def test_range_location_can_be_created_with_defaults(app_session):
    from app.db.models import RangeLocation

    loc = RangeLocation(name="מטווח בדיקה")
    app_session.add(loc)
    app_session.flush()

    assert loc.id is not None
    assert loc.active is True
    assert loc.created_at is not None
