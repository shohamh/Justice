"""Measure Transparency read-model build and isolated scale API paths.

Run from ``backend`` with ``JUSTICE_SCALE_DATABASE_URL`` set to an isolated
PostgreSQL database whose URL has an explicit loopback host, whose name
contains ``_scale`` or ``_perf``, and whose name and host have no
production-like marker. The script never seeds business rows and never prints
or writes the connection URL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any
from uuid import UUID

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.scripts.seed_scale_test import target_database_url  # noqa: E402

API_PATH = "/api/scoring/transparency/page"
PAGE_SIZE = 100
DEFAULT_REPETITIONS = 5
DEFAULT_WARMUPS = 2
OUTPUT_PATH = (
    REPO_DIR
    / "docs"
    / "benchmarks"
    / "data"
    / "transparency-keyset-read-model-20261005.json"
)
_CREDENTIAL_KEY_PARTS = (
    "password",
    "secret",
    "credential",
    "database_url",
    "connection_string",
    "token",
    "cookie",
    "jwt",
    "authorization",
)
_DATABASE_URL_PATTERN = re.compile(r"postgres(?:ql)?(?:\+[^:/]+)?://", re.IGNORECASE)


def validate_scale_target_url(environ: Mapping[str, str] | None = None):
    """Use the seed script's strict isolated-target validation without fallback."""
    return target_database_url(environ)


def _walk_artifact(value: Any, path: str = "artifact") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).casefold()
            if any(part in lowered for part in _CREDENTIAL_KEY_PARTS):
                raise ValueError(f"artifact contains a credential field at {path}.{key}")
            _walk_artifact(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _walk_artifact(nested, f"{path}[{index}]")
    elif isinstance(value, str) and _DATABASE_URL_PATTERN.search(value):
        raise ValueError(f"artifact contains a database connection URL at {path}")


def validate_artifact_schema(artifact: Mapping[str, Any]) -> None:
    """Validate the measurement contract and reject credential-bearing output."""
    _walk_artifact(artifact)
    required = {
        "schema_version",
        "captured_at_utc",
        "target",
        "dataset",
        "measurements",
        "query_plan",
        "browser",
        "limitations",
    }
    missing = required - artifact.keys()
    if missing:
        raise ValueError(f"artifact is missing required sections: {', '.join(sorted(missing))}")
    if artifact["schema_version"] != 1:
        raise ValueError("unsupported artifact schema_version")
    target = artifact["target"]
    if not isinstance(target, Mapping) or not target.get("database_name"):
        raise ValueError("artifact target must include database_name")
    database_name = str(target["database_name"]).casefold()
    if "_scale" not in database_name and "_perf" not in database_name:
        raise ValueError("artifact target database_name must contain _scale or _perf")
    measurements = artifact["measurements"]
    if not isinstance(measurements, Mapping):
        raise ValueError("artifact measurements must be an object")
    for operation in (
        "model_build",
        "current_model_first_page",
        "snapshot_fallback_first_page",
        "continuation",
    ):
        if operation not in measurements:
            raise ValueError(f"artifact measurements missing {operation}")
    _validate_timed_sample(measurements["model_build"], operation="model_build", needs_bytes=False)
    _validate_timed_sample(
        measurements["snapshot_fallback_first_page"],
        operation="snapshot_fallback_first_page",
        needs_bytes=True,
    )
    for operation in ("current_model_first_page", "continuation"):
        value = measurements[operation]
        if not isinstance(value, Mapping) or not isinstance(value.get("samples"), list):
            raise ValueError(f"artifact {operation} must include a samples array")
        if not value["samples"]:
            raise ValueError(f"artifact {operation} samples must not be empty")
        for sample in value["samples"]:
            _validate_timed_sample(sample, operation=operation, needs_bytes=True)
    browser = artifact["browser"]
    if not isinstance(browser, Mapping) or browser.get("status") not in {"captured", "unavailable"}:
        raise ValueError("artifact browser.status must be captured or unavailable")
    if browser["status"] == "unavailable" and not browser.get("reason"):
        raise ValueError("unavailable browser measurement requires an explicit reason")
    if browser["status"] == "captured":
        captures = browser.get("captures")
        if not isinstance(captures, Mapping) or not {"c1", "c5"}.issubset(captures):
            raise ValueError("captured browser measurement must include c1 and c5 captures")
        for label, concurrency in (("c1", 1), ("c5", 5)):
            capture = captures[label]
            if not isinstance(capture, Mapping) or capture.get("concurrency") != concurrency:
                raise ValueError(f"captured browser {label} concurrency is invalid")
            modes = capture.get("modes")
            if not isinstance(modes, Mapping) or not {"cold", "warm"}.issubset(modes):
                raise ValueError(f"captured browser {label} must include cold and warm modes")
            for mode in ("cold", "warm"):
                value = modes[mode]
                page_ready = value.get("page_ready_ms") if isinstance(value, Mapping) else None
                if (
                    not isinstance(page_ready, Mapping)
                    or not isinstance(page_ready.get("p50"), (int, float))
                    or not isinstance(page_ready.get("p95"), (int, float))
                ):
                    raise ValueError(f"captured browser {label} {mode} mode needs page-ready p50/p95")
                first_contentful_paint = (
                    value.get("first_contentful_paint_ms") if isinstance(value, Mapping) else None
                )
                if first_contentful_paint is not None and (
                    not isinstance(first_contentful_paint, Mapping)
                    or not isinstance(first_contentful_paint.get("p50"), (int, float))
                    or not isinstance(first_contentful_paint.get("p95"), (int, float))
                ):
                    raise ValueError(
                        f"captured browser {label} {mode} first-contentful-paint "
                        "must include p50/p95 when present"
                    )
    query_plan = artifact["query_plan"]
    if (
        not isinstance(query_plan, Mapping)
        or query_plan.get("captured") is not True
        or query_plan.get("format") != "json"
        or not isinstance(query_plan.get("plan"), list)
    ):
        raise ValueError("artifact query_plan must contain a captured JSON plan")


def _validate_timed_sample(sample: Any, *, operation: str, needs_bytes: bool) -> None:
    if not isinstance(sample, Mapping):
        raise ValueError(f"artifact {operation} measurement must be an object")
    required = {"wall_ms", "sql_count", "sql_cursor_ms"}
    if needs_bytes:
        required.update({"response_bytes", "status_code"})
    missing = required - sample.keys()
    if missing:
        raise ValueError(f"artifact {operation} measurement missing: {', '.join(sorted(missing))}")


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, int((percentile / 100) * len(ordered) + 0.999999))
    return ordered[rank - 1]


def _summary(samples: list[dict[str, Any]]) -> dict[str, float]:
    values = [float(sample["wall_ms"]) for sample in samples]
    return {
        "min_ms": round(min(values), 3),
        "median_ms": round(median(values), 3),
        "mean_ms": round(mean(values), 3),
        "p95_ms_nearest_rank": round(_percentile(values, 95), 3),
        "max_ms": round(max(values), 3),
    }


def _details(engine) -> dict[str, Any]:
    from sqlalchemy import text

    with engine.connect() as connection:
        postgres_version, work_mem, db_name = connection.execute(text("""
            SELECT current_setting('server_version'), current_setting('work_mem'), current_database()
        """)).one()
        connection.rollback()
    return {
        "database_name": db_name,
        "postgres_version": postgres_version,
        "work_mem": work_mem,
    }


def _assert_database(engine, expected_name: str) -> None:
    from sqlalchemy import text

    with engine.connect() as connection:
        actual_name = connection.execute(text("SELECT current_database()")).scalar_one()
        connection.rollback()
    if actual_name != expected_name:
        raise RuntimeError("scale benchmark database identity changed during measurement")


def _dataset_counts(engine) -> dict[str, int]:
    from sqlalchemy import text

    with engine.connect() as connection:
        values = connection.execute(text("""
            SELECT
              (SELECT count(*) FROM soldiers) AS soldiers,
              (SELECT count(*) FROM soldiers WHERE personal_number LIKE 'SCALE20-%') AS synthetic_soldiers,
              (SELECT count(*) FROM soldiers
                 WHERE left_at IS NULL AND (discharge_date IS NULL OR discharge_date >= CURRENT_DATE)) AS active_soldiers,
              (SELECT count(*) FROM duty_assignments) AS duty_assignments,
              (SELECT count(*) FROM soldier_score_projection) AS score_projection_rows,
              (SELECT count(*) FROM transparency_read_model_rows) AS read_model_rows
        """)).mappings().one()
        connection.rollback()
    return {key: int(value) for key, value in values.items()}


def _find_admin(engine):
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import Soldier

    with Session(engine) as session:
        admin = session.execute(
            select(Soldier)
            .where(Soldier.role == "admin", Soldier.must_change_password.is_(False))
            .order_by(Soldier.personal_number)
            .limit(1)
        ).scalar_one_or_none()
        if admin is None:
            raise RuntimeError("isolated scale database has no administrator for authenticated API timing")
        actor = {"id": admin.id, "role": admin.role}
        session.rollback()
    return actor


def _api_sample(
    client, headers: dict[str, str], *, cursor: str | None = None, search: str = "",
) -> dict[str, Any]:
    from time import perf_counter

    started = perf_counter()
    response = client.get(
        API_PATH,
        params={"page_size": PAGE_SIZE, "search": search, **({"cursor": cursor} if cursor else {})},
        headers=headers,
    )
    wall_ms = (perf_counter() - started) * 1_000
    if response.status_code != 200:
        # Keep response bodies out of terminal output and artifacts: a driver
        # error can include deployment details that do not belong in evidence.
        raise RuntimeError(f"Transparency API benchmark returned HTTP {response.status_code}")
    payload = response.json()
    return {
        "wall_ms": round(wall_ms, 3),
        "server_ms": _header_float(response, "x-scale-server-ms"),
        "sql_count": _header_int(response, "x-scale-db-queries"),
        "sql_cursor_ms": _header_float(response, "x-scale-db-ms"),
        "response_bytes": len(response.content),
        "status_code": response.status_code,
        "item_count": len(payload.get("items", [])),
        "summary_row_count": payload.get("summary", {}).get("row_count"),
        "has_more": payload.get("has_more"),
        "has_next_cursor": bool(payload.get("next_cursor")),
        "_next_cursor": payload.get("next_cursor"),
    }


def _header_int(response, name: str) -> int:
    value = response.headers.get(name)
    return int(value) if value is not None else 0


def _header_float(response, name: str) -> float:
    value = response.headers.get(name)
    return round(float(value), 3) if value is not None else 0.0


def _query_plan(engine, generation_id: UUID) -> dict[str, Any]:
    from sqlalchemy import text

    statement = text("""
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        SELECT rows.*
        FROM transparency_read_model_rows AS rows
        WHERE rows.generation_id = :generation_id
        ORDER BY rows.burden_share DESC, rows.soldier_id ASC
        LIMIT 101
    """)
    with engine.connect() as connection:
        started = time.perf_counter()
        result = connection.execute(statement, {"generation_id": generation_id}).scalar_one()
        elapsed_ms = (time.perf_counter() - started) * 1_000
        connection.rollback()
    return {
        "captured": True,
        "format": "json",
        "statement_shape": "authorized default first-page read (admin scope), order by burden_share DESC, soldier_id ASC, limit 101",
        "explain_elapsed_ms": round(elapsed_ms, 3),
        "plan": result,
    }


def _build_generation(engine, profile):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.services import transparency_read_model

    stats = profile.QueryStats()
    token = profile._request_stats.set(stats)
    started = time.perf_counter()
    try:
        with Session(engine) as session:
            generation = transparency_read_model.rebuild_generation(session)
            session.rollback()
    finally:
        wall_ms = (time.perf_counter() - started) * 1_000
        profile._request_stats.reset(token)
    if generation is None:
        raise RuntimeError(
            "transparency read-model build was not published; confirm score projections are ready and current"
        )
    with engine.connect() as connection:
        row_count = connection.execute(text("""
            SELECT count(*) FROM transparency_read_model_rows
            WHERE generation_id = :generation_id
        """), {"generation_id": generation["id"]}).scalar_one()
        connection.rollback()
    return {
        "wall_ms": round(wall_ms, 3),
        "sql_count": stats.count,
        "sql_cursor_ms": round(stats.elapsed_seconds * 1_000, 3),
        "generation_id": str(generation["id"]),
        "source_generation": generation["source_generation"],
        "as_of": generation["as_of"].isoformat(),
        "published_at": generation["published_at"].isoformat(),
        "row_count": int(row_count),
        "normalization_denominator": str(generation["normalization_denominator"]),
    }


def _request_samples(client, headers, *, repetitions: int, warmups: int, cursor: str | None = None):
    warmup_results = [
        _api_sample(client, headers, cursor=cursor)
        for _ in range(warmups)
    ]
    results = [
        _api_sample(client, headers, cursor=cursor)
        for _ in range(repetitions)
    ]
    next_cursor = results[-1].pop("_next_cursor", None)
    # A signed pagination cursor is operational input, not benchmark evidence.
    for sample in (*warmup_results, *results):
        sample.pop("_next_cursor", None)
    return {
        "warmups": warmups,
        "warmup_status_codes": [sample["status_code"] for sample in warmup_results],
        "samples": results,
        "summary": _summary(results),
    }, next_cursor


def run(*, repetitions: int = DEFAULT_REPETITIONS, warmups: int = DEFAULT_WARMUPS, output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    if repetitions < 1 or warmups < 0:
        raise ValueError("repetitions must be positive and warmups must not be negative")

    parsed_url = validate_scale_target_url()
    # Environment setup happens only after the explicit scale URL passed the
    # seed script's safety checks. Do not log or persist the rendered URL.
    safe_url = parsed_url.render_as_string(hide_password=False)
    os.environ["DATABASE_URL"] = safe_url
    os.environ["DB_ADMIN_URL"] = safe_url
    os.environ["JUSTICE_TESTING"] = "1"
    os.environ["TRANSPARENCY_READ_MODEL_ENABLED"] = "true"

    from fastapi.testclient import TestClient

    from app.settings import get_settings

    get_settings.cache_clear()
    from app.db import session as db_session

    db_session.reset_engine()
    from app.auth.jwt_tokens import issue_access_token
    from app.main import create_app
    from app.scripts import profile_scale_server as profile
    from app.services import transparency_read_model

    engine = db_session.get_engine()
    profile._install_sql_timers()
    _details_before = _details(engine)
    if _details_before["database_name"] != parsed_url.database:
        raise RuntimeError("connected database does not match the validated scale target")

    _assert_database(engine, parsed_url.database)
    build = _build_generation(engine, profile)
    _assert_database(engine, parsed_url.database)
    counts = _dataset_counts(engine)
    if build["row_count"] < 1:
        raise RuntimeError("transparency read-model build produced no active rows")

    actor = _find_admin(engine)
    token = issue_access_token(user_id=actor["id"], role=actor["role"])
    headers = {"Authorization": f"Bearer {token}"}
    app = create_app()
    settings = get_settings()
    route_settings = {
        "jwt_secret": settings.jwt_secret,
        "jwt_algorithm": settings.jwt_algorithm,
        "transparency_read_model_enabled": True,
    }
    # The wrapper records request-scoped SQL counters without changing route behavior.
    wrapped_app = profile.ScaleProfileMiddleware(app)
    measurements: dict[str, Any] = {}
    with TestClient(wrapped_app) as client:
        import app.routes.scoring as scoring_route

        original_settings = scoring_route.get_settings
        from types import SimpleNamespace

        scoring_route.get_settings = lambda: SimpleNamespace(**route_settings)
        try:
            # Prime model-path caches and retain the returned cursor for the
            # separate continuation sample set.
            _assert_database(engine, parsed_url.database)
            first_page, cursor = _request_samples(
                client, headers, repetitions=repetitions, warmups=warmups,
            )
            _assert_database(engine, parsed_url.database)
            if not cursor:
                raise RuntimeError("current-model first page did not return a continuation cursor")
            measurements["current_model_first_page"] = first_page
            measurements["current_model_first_page"]["model_generation_id"] = build["generation_id"]
            measurements["current_model_first_page"]["source_generation"] = build["source_generation"]
            _assert_database(engine, parsed_url.database)
            continuation, _continuation_cursor = _request_samples(
                client, headers, repetitions=repetitions, warmups=warmups, cursor=cursor,
            )
            _assert_database(engine, parsed_url.database)
            measurements["continuation"] = continuation

            from app.db.models import Soldier
            from app.services import transparency_page_store

            with db_session.session_scope() as session:
                admin = session.get(Soldier, actor["id"])
                source_generation, _source_snapshot = transparency_read_model.capture_source_state(session)
                fallback_search = " "
                cached_snapshot = None
                for whitespace_count in range(1, 33):
                    fallback_search = " " * whitespace_count
                    request_binding = scoring_route._transparency_page_binding(
                        session=session,
                        user=admin,
                        node_id=None,
                        officer_filter="all",
                        service_type=None,
                        group_keys=[],
                        rank_filter=None,
                        search=fallback_search,
                        sort="burden_share",
                        descending=True,
                        page_size=PAGE_SIZE,
                        rank_order=[],
                    )
                    cached_snapshot = transparency_page_store.find_reusable(
                        session, request_binding, source_generation, date.today(),
                    )
                    if cached_snapshot is None:
                        break
                else:
                    raise RuntimeError("could not find an unused whitespace-only fallback binding")
                session.rollback()

            # Disable only the route's fast-path feature flag. The snapshot
            # fallback writes only its own derived cache rows; no business rows
            # or source tables are modified by this benchmark.
            route_settings["transparency_read_model_enabled"] = False
            _assert_database(engine, parsed_url.database)
            fallback_sample = _api_sample(client, headers, search=fallback_search)
            _assert_database(engine, parsed_url.database)
            fallback_sample.pop("_next_cursor", None)
            fallback_sample["snapshot_cache_hit_before_request"] = cached_snapshot is not None
            fallback_sample["snapshot_cache_state"] = "hit" if cached_snapshot is not None else "cold_miss"
            fallback_sample["fallback_cause"] = "read-model feature gate disabled for this controlled API sample"
            fallback_sample["search_binding_variant"] = {
                "whitespace_characters": len(fallback_search),
                "normalized_search": "",
                "reason": "A distinct cache binding preserves empty-search semantics for this cold fallback sample.",
            }
            measurements["snapshot_fallback_first_page"] = fallback_sample
            route_settings["transparency_read_model_enabled"] = True
        finally:
            scoring_route.get_settings = original_settings

    from app.services import transparency_read_model as read_model

    with db_session.session_scope() as session:
        current_generation = read_model.current_generation(
            session,
            source_generation=build["source_generation"],
            as_of=date.today(),
        )
        session.rollback()
    if current_generation is None:
        raise RuntimeError("model generation was not current after the API samples")
    if str(current_generation["id"]) != build["generation_id"]:
        raise RuntimeError("API measurements did not use the generation built by this benchmark")
    _assert_database(engine, parsed_url.database)
    plan = _query_plan(engine, UUID(build["generation_id"]))
    _assert_database(engine, parsed_url.database)
    measured_data = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "target": _details(engine),
        "dataset": counts,
        "parameters": {
            "endpoint": API_PATH,
            "page_size": PAGE_SIZE,
            "repetitions": repetitions,
            "warmups_per_api_operation": warmups,
            "actor_role": actor["role"],
            "concurrency": 1,
        },
        "measurements": {
            "model_build": build,
            **measurements,
        },
        "refresh_observation": {
            "controlled_fallback_requests": 1,
            "fallback_rate_in_live_traffic": None,
            "live_refresh_worker_build_lag": None,
            "model_age_at_measurement_ms": round(
                (datetime.now(UTC) - current_generation["published_at"]).total_seconds() * 1_000,
                3,
            ),
            "note": "The standalone runner has no production request-rate or worker telemetry source; only one forced fallback request and this model's publication age are observed.",
        },
        "query_plan": plan,
        "browser": {
            "status": "unavailable",
            "reason": "This runner captures authenticated API requests only; no browser automation was run.",
        },
        "limitations": [
            "In-process TestClient API timings include ASGI and serialization but do not measure browser rendering or page readiness.",
            "Only one administrator and one client were measured; there is no concurrent-load result.",
            "Model build is one direct rebuild sample; first-page and continuation each use the configured repeated samples.",
            "SQL cursor time excludes row fetching, ORM/Python work, and response serialization.",
            "The snapshot fallback may reuse a matching pre-existing snapshot; its measured cache state is recorded in the sample.",
        ],
    }
    # Keep private cursor-related values and any incidental server-only fields
    # out of the artifact. The helpers already omit cursor contents.
    validate_artifact_schema(measured_data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(measured_data, indent=2) + "\n", encoding="utf-8")
    engine.dispose()
    return measured_data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    artifact = run(repetitions=args.repetitions, warmups=args.warmups, output_path=args.output)
    print(f"artifact: {args.output}")
    for operation in ("current_model_first_page", "snapshot_fallback_first_page", "continuation"):
        entry = artifact["measurements"][operation]
        summary = entry["summary"] if "summary" in entry else {"wall_ms": entry["wall_ms"]}
        print(f"{operation}: {summary}")


if __name__ == "__main__":
    main()
