from __future__ import annotations

import sys

import pytest

from tests.performance import transparency_keyset_read_model_benchmark as benchmark


def test_scale_target_requires_explicit_safe_database_url_and_never_uses_database_url():
    with pytest.raises(ValueError, match="JUSTICE_SCALE_DATABASE_URL"):
        benchmark.validate_scale_target_url({"DATABASE_URL": "postgresql://u:p@localhost/justice_scale"})

    for database_name in ("justice", "postgres", "justice_test"):
        url = f"postgresql://bench:secret@localhost/{database_name}"
        with pytest.raises(ValueError, match="isolated"):
            benchmark.validate_scale_target_url({"JUSTICE_SCALE_DATABASE_URL": url})

    parsed = benchmark.validate_scale_target_url({
        "JUSTICE_SCALE_DATABASE_URL": "postgresql://bench:secret@localhost/justice_scale_20k"
    })
    assert parsed.database == "justice_scale_20k"
    for unsafe_url in (
        "postgresql://bench:secret@localhost/justice_prod_scale",
        "postgresql://bench:secret@localhost/justice_prd_scale",
        "postgresql://bench:secret@prod-db.example.invalid/justice_scale_20k",
        "postgresql://bench:secret@prod1-db.example.invalid/justice_scale_20k",
        "postgresql://bench:secret@prd-db.example.invalid/justice_scale_20k",
        "postgresql:///justice_scale_20k",
    ):
        with pytest.raises(ValueError, match="isolated"):
            benchmark.validate_scale_target_url({"JUSTICE_SCALE_DATABASE_URL": unsafe_url})


def _valid_artifact() -> dict:
    sample = {
        "wall_ms": 12.5,
        "sql_count": 3,
        "sql_cursor_ms": 4.2,
        "response_bytes": 128,
        "status_code": 200,
    }
    return {
        "schema_version": 1,
        "captured_at_utc": "2026-10-05T12:00:00+00:00",
        "target": {"database_name": "justice_scale_20k", "postgres_version": "16.4"},
        "dataset": {"soldiers": 20121, "duty_assignments": 1000008},
        "measurements": {
            "model_build": {"wall_ms": 1000.0, "sql_count": 10, "sql_cursor_ms": 400.0},
            "current_model_first_page": {"warmups": 1, "samples": [sample], "summary": {"median_ms": 12.5}},
            "snapshot_fallback_first_page": sample,
            "continuation": {"warmups": 1, "samples": [sample], "summary": {"median_ms": 12.5}},
        },
        "query_plan": {"captured": True, "format": "json", "plan": []},
        "browser": {"status": "unavailable", "reason": "No browser run was captured."},
        "limitations": ["Local isolated scale database."],
    }


def test_artifact_schema_requires_all_api_phases_and_explicit_browser_status():
    artifact = _valid_artifact()
    assert benchmark.validate_artifact_schema(artifact) is None

    del artifact["measurements"]["continuation"]
    with pytest.raises(ValueError, match="continuation"):
        benchmark.validate_artifact_schema(artifact)

    artifact = _valid_artifact()
    artifact["query_plan"] = {"captured": False, "format": "json", "plan": []}
    with pytest.raises(ValueError, match="captured JSON plan"):
        benchmark.validate_artifact_schema(artifact)


def test_artifact_schema_checks_captured_browser_concurrency_and_readiness():
    artifact = _valid_artifact()
    artifact["browser"] = {
        "status": "captured",
        "captures": {
            label: {
                "concurrency": concurrency,
                "modes": {
                    mode: {
                        "page_ready_ms": {"p50": 100.0, "p95": 200.0},
                        "first_contentful_paint_ms": {"p50": 50.0, "p95": 75.0},
                    }
                    for mode in ("cold", "warm")
                },
            }
            for label, concurrency in (("c1", 1), ("c5", 5))
        },
    }
    assert benchmark.validate_artifact_schema(artifact) is None

    artifact["browser"]["captures"]["c5"]["modes"]["cold"]["page_ready_ms"].pop("p95")
    with pytest.raises(ValueError, match="page-ready p50/p95"):
        benchmark.validate_artifact_schema(artifact)

    artifact = _valid_artifact()
    artifact["browser"] = {
        "status": "captured",
        "captures": {
            label: {
                "concurrency": concurrency,
                "modes": {
                    mode: {"page_ready_ms": {"p50": 100.0, "p95": 200.0}}
                    for mode in ("cold", "warm")
                },
            }
            for label, concurrency in (("c1", 1), ("c5", 5))
        },
    }
    assert benchmark.validate_artifact_schema(artifact) is None

    artifact["browser"]["captures"]["c1"]["modes"]["cold"]["first_contentful_paint_ms"] = {
        "p50": 50.0,
    }
    with pytest.raises(ValueError, match="first-contentful-paint must include p50/p95"):
        benchmark.validate_artifact_schema(artifact)


@pytest.mark.parametrize(
    "credential_field,credential_value",
    [
        ("database_url", "postgresql://bench:secret@localhost/justice_scale_20k"),
        ("password", "secret"),
        ("access_token", "sensitive"),
        ("refresh_token", "sensitive"),
        ("cookie", "session=value"),
    ],
)
def test_artifact_rejects_credentials_and_connection_urls(credential_field, credential_value):
    artifact = _valid_artifact()
    artifact["target"][credential_field] = credential_value

    with pytest.raises(ValueError, match="credential"):
        benchmark.validate_artifact_schema(artifact)


def test_cli_summary_prints_single_fallback_sample_without_summary_object(monkeypatch, capsys):
    artifact = _valid_artifact()
    artifact["measurements"]["snapshot_fallback_first_page"] = {
        **artifact["measurements"]["snapshot_fallback_first_page"],
        "wall_ms": 20.0,
    }
    monkeypatch.setattr(sys, "argv", ["transparency_keyset_read_model_benchmark"])
    monkeypatch.setattr(benchmark, "run", lambda **_kwargs: artifact)

    benchmark.main()

    output = capsys.readouterr().out
    assert "snapshot_fallback_first_page" in output
    assert "wall_ms" in output
