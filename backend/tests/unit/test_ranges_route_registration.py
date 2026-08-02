"""Regression tests for constructing the ranges router."""


def test_ranges_routes_can_be_imported():
    from app.routes import ranges

    assert ranges.router is not None


def test_delete_range_routes_have_no_response_model():
    from app.routes import ranges

    delete_routes = [
        route
        for route in ranges.router.routes
        if "DELETE" in (route.methods or set())
    ]

    assert delete_routes
    assert all(route.response_model is None for route in delete_routes)
