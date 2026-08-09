from uuid import uuid4

from app.services.scoring import _build_fairness_components


def test_groups_by_shared_duty_types_and_isolates_exempt():
    A, B, C = uuid4(), uuid4(), uuid4()
    s1, s2, s3, s4, s5 = (uuid4() for _ in range(5))
    type_names = {A: "גדר", B: "שער", C: "מטבח"}
    # s1,s2 do {A,B}; s3,s4 do {C}; s5 exempt from everything
    eligible = {s1: {A, B}, s2: {A, B}, s3: {C}, s4: {C}, s5: set()}
    effort = {s1: 0.1, s2: 0.3, s3: 0.2, s4: 0.25, s5: 0.0}
    names = {s1: "a", s2: "b", s3: "c", s4: "d", s5: "e"}

    res = _build_fairness_components(eligible, type_names, effort, names)

    assert res["exempt_from_all"]["count"] == 1
    assert res["exempt_from_all"]["soldiers"][0]["soldier_id"] == s5

    comps = res["components"]
    assert len(comps) == 2
    by_types = {tuple(c["duty_type_names"]): c for c in comps}
    ab = by_types[("גדר", "שער")]
    assert ab["soldier_count"] == 2
    assert ab["effort"]["min"] == 0.1 and ab["effort"]["max"] == 0.3
    assert by_types[("מטבח",)]["soldier_count"] == 2


def test_transitive_link_merges_into_one_component():
    A, B, C = uuid4(), uuid4(), uuid4()
    s1, s2 = uuid4(), uuid4()
    # s1 does {A,B}, s2 does {B,C} -> linked via B -> single component covering {A,B,C}
    res = _build_fairness_components(
        {s1: {A, B}, s2: {B, C}}, {A: "A", B: "B", C: "C"},
        {s1: 0.1, s2: 0.2}, {s1: "x", s2: "y"},
    )
    assert res["exempt_from_all"]["count"] == 0
    assert len(res["components"]) == 1
    assert res["components"][0]["duty_type_names"] == ["A", "B", "C"]
    assert res["components"][0]["soldier_count"] == 2


def test_single_soldier_component_has_no_stats():
    A = uuid4()
    s1 = uuid4()
    res = _build_fairness_components({s1: {A}}, {A: "A"}, {s1: 0.5}, {s1: "x"})
    assert res["components"][0]["effort"] is None  # <2 soldiers -> no spread


def test_fairness_components_includes_duty_type_ids():
    A, B = uuid4(), uuid4()
    s1, s2 = uuid4(), uuid4()
    type_names = {A: "גדר", B: "שער"}
    # s1,s2 do {A,B}
    eligible = {s1: {A, B}, s2: {A, B}}
    effort = {s1: 0.1, s2: 0.3}
    names = {s1: "a", s2: "b"}

    res = _build_fairness_components(eligible, type_names, effort, names)

    assert len(res["components"]) == 1
    component = res["components"][0]
    assert "duty_type_ids" in component
    assert set(component["duty_type_ids"]) == {str(A), str(B)}
    # Verify they are sorted strings (consistent ordering)
    assert component["duty_type_ids"] == sorted([str(A), str(B)])
