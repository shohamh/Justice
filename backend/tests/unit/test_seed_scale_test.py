import uuid
from types import SimpleNamespace

import app.scripts.seed_scale_test as scale_seed
from app.scripts.seed_scale_test import ScaleSeedConfig, iter_soldier_rows


def test_scale_soldier_rows_include_canonical_ad_username_for_email():
    row = next(iter_soldier_rows(ScaleSeedConfig(soldiers=1), password_hash="test-hash"))

    assert row.get("ad_username") == row["email"].partition("@")[0]


def test_scale_soldier_preflight_compares_ad_username(monkeypatch):
    soldier_compare_columns = None

    def record_comparison(connection, *, model, rows, identity_columns, compare_columns):
        nonlocal soldier_compare_columns
        if model is scale_seed.Soldier:
            soldier_compare_columns = tuple(compare_columns)

    monkeypatch.setattr(scale_seed, "_assert_existing_rows_compatible", record_comparison)
    monkeypatch.setattr(scale_seed, "_preflight_profiles", lambda *_args: None)

    scale_seed._preflight(
        SimpleNamespace(rollback=lambda: None),
        ScaleSeedConfig(soldiers=1, history_years=1, assignments_per_year=1),
        root_id=uuid.uuid4(),
        root_path=(uuid.uuid4(),),
        duty_type_ids=(uuid.uuid4(),),
        duty_location_ids=(uuid.uuid4(),),
    )

    assert soldier_compare_columns == (
        "id",
        "personal_number",
        "full_name",
        "role",
        "hierarchy_node_id",
        "email",
        "ad_username",
        "gender",
    )
