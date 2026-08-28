from uuid import uuid4

from app.services.scoring import _build_fairness_components, _soldier_burden_share


def test_returns_rank_and_anonymized_peers():
    A, B = uuid4(), uuid4()
    s1, s2, s3 = uuid4(), uuid4(), uuid4()
    type_names = {A: "גדר", B: "שער"}
    eligible = {s1: {A, B}, s2: {A, B}, s3: {A, B}}
    effort = {s1: 0.5, s2: 0.3, s3: 0.1}
    names = {s1: "a", s2: "b", s3: "c"}

    built = _build_fairness_components(eligible, type_names, effort, names)
    result = _soldier_burden_share(built, s2)

    assert result["burden_share"] == 0.3
    assert result["rank"] == 2  # sorted desc: s1(0.5), s2(0.3), s3(0.1)
    assert result["group_size"] == 3
    assert result["duty_type_names"] == ["גדר", "שער"]
    assert sorted(result["peer_scores"], reverse=True) == [0.5, 0.3, 0.1]
    assert result["low_sample"] is False


def test_peer_scores_carry_no_identity():
    A = uuid4()
    s1, s2 = uuid4(), uuid4()
    eligible = {s1: {A}, s2: {A}}
    effort = {s1: 0.4, s2: 0.6}
    names = {s1: "a", s2: "b"}

    built = _build_fairness_components(eligible, {A: "A"}, effort, names)
    result = _soldier_burden_share(built, s1)

    assert "soldier_id" not in result
    assert "full_name" not in result
    assert all(isinstance(v, float) for v in result["peer_scores"])


def test_returns_none_for_exempt_soldier():
    s1 = uuid4()
    built = _build_fairness_components({s1: set()}, {}, {s1: 0.0}, {s1: "a"})
    assert _soldier_burden_share(built, s1) is None


def test_low_sample_flag_true_when_group_under_three():
    A = uuid4()
    s1, s2 = uuid4(), uuid4()
    eligible = {s1: {A}, s2: {A}}
    effort = {s1: 0.4, s2: 0.6}
    names = {s1: "a", s2: "b"}

    built = _build_fairness_components(eligible, {A: "A"}, effort, names)
    result = _soldier_burden_share(built, s1)

    assert result["group_size"] == 2
    assert result["low_sample"] is True


def test_single_soldier_component_has_no_stats():
    A = uuid4()
    s1 = uuid4()
    built = _build_fairness_components({s1: {A}}, {A: "A"}, {s1: 0.5}, {s1: "x"})
    result = _soldier_burden_share(built, s1)

    assert result["mean"] is None
    assert result["stddev"] is None
    assert result["cv"] is None
    assert result["low_sample"] is True
