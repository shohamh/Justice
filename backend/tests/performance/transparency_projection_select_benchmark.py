"""Compare Transparency projection entity hydration with its three-column read."""

from __future__ import annotations

import argparse
import json
import platform
import random
import sys
import time
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from statistics import mean, median
from typing import Any
from uuid import UUID, uuid5

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import insert, select, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.models import SoldierScoreProjection  # noqa: E402
from tests.support import database  # noqa: E402

ROW_COUNT = 20_270
VARIANTS = ("orm_entity", "selected_columns")
NAMESPACE = UUID("3f5a7c91-62de-4e13-8d02-3d61b2dc5e74")


def _version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"


def _make_rows(count: int) -> list[dict[str, Any]]:
    return [
        {
            "soldier_id": uuid5(NAMESPACE, f"soldier-{index}"),
            "projection_version": "benchmark-v1",
            "duty_score": Decimal(index % 4_000) / Decimal("13"),
            "adjustment_score": Decimal(index % 200) / Decimal("17"),
            "cumulative_score": Decimal(index % 8_000) / Decimal("19"),
            "shift_count": index % 250,
        }
        for index in range(count)
    ]


def _create_dataset(engine: Engine, rows: list[dict[str, Any]]) -> None:
    # The real mapped projection table only depends on soldiers.id. Keep that
    # parent minimal; the Testcontainers database is disposable and isolated.
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE soldiers (id uuid PRIMARY KEY)"))
        SoldierScoreProjection.__table__.create(connection)
        connection.execute(
            text("INSERT INTO soldiers (id) VALUES (:id)"),
            [{"id": row["soldier_id"]} for row in rows],
        )
        connection.execute(insert(SoldierScoreProjection), rows)


def _read_once(session: Session, variant: str) -> tuple[float, dict[UUID, tuple[Decimal, int]]]:
    started = time.perf_counter()
    if variant == "orm_entity":
        result = session.execute(
            select(SoldierScoreProjection).order_by(SoldierScoreProjection.soldier_id)
        ).scalars().all()
        output = {
            row.soldier_id: (row.cumulative_score, row.shift_count)
            for row in result
        }
    elif variant == "selected_columns":
        result = session.execute(
            select(
                SoldierScoreProjection.soldier_id,
                SoldierScoreProjection.cumulative_score,
                SoldierScoreProjection.shift_count,
            ).order_by(SoldierScoreProjection.soldier_id)
        ).all()
        output = {
            soldier_id: (cumulative_score, shift_count)
            for soldier_id, cumulative_score, shift_count in result
        }
    else:
        raise ValueError(f"unknown variant: {variant}")
    return time.perf_counter() - started, output


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, int((percentile / 100) * len(ordered) + 0.999999))
    return ordered[rank - 1]


def _summarize(samples: list[dict[str, Any]]) -> dict[str, float]:
    values = [float(sample["wall_ms"]) for sample in samples]
    return {
        "min_ms": round(min(values), 3),
        "median_ms": round(median(values), 3),
        "mean_ms": round(mean(values), 3),
        "p95_ms_nearest_rank": round(_percentile(values, 95), 3),
        "max_ms": round(max(values), 3),
    }


def _server_details(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        server_version, work_mem = connection.execute(
            text("SELECT current_setting('server_version'), current_setting('work_mem')")
        ).one()
        connection.rollback()
    return {
        "postgres_version": server_version,
        "work_mem": work_mem,
        "sqlalchemy_version": _version("sqlalchemy"),
        "testcontainers_version": _version("testcontainers"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


def run(repetitions: int, warmups: int, output_path: Path) -> dict[str, Any]:
    if repetitions < 1 or warmups < 1:
        raise ValueError("repetitions and warmups must both be positive")

    rows = _make_rows(ROW_COUNT)
    expected = {
        row["soldier_id"]: (
            row["cumulative_score"].quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
            row["shift_count"],
        )
        for row in rows
    }
    with database.new_postgres_container() as container:
        from sqlalchemy import create_engine

        engine = create_engine(database.render_psycopg_url(container.get_connection_url()))
        try:
            _create_dataset(engine, rows)
            details = _server_details(engine)
            rng = random.Random(20_270)
            warmup_samples: dict[str, list[float]] = {variant: [] for variant in VARIANTS}
            for _ in range(warmups):
                order = list(VARIANTS)
                rng.shuffle(order)
                with Session(engine) as session:
                    for variant in order:
                        elapsed, output = _read_once(session, variant)
                        if output != expected:
                            raise AssertionError(f"{variant} warm-up output differs from source data")
                        warmup_samples[variant].append(round(elapsed * 1_000, 3))

            measured: dict[str, list[dict[str, Any]]] = {variant: [] for variant in VARIANTS}
            measured_order: list[list[str]] = []
            for round_number in range(repetitions):
                order = list(VARIANTS)
                rng.shuffle(order)
                measured_order.append(order)
                with Session(engine) as session:
                    for variant in order:
                        elapsed, output = _read_once(session, variant)
                        if output != expected:
                            raise AssertionError(f"{variant} round {round_number + 1} output differs")
                        measured[variant].append({
                            "round": round_number + 1,
                            "wall_ms": round(elapsed * 1_000, 3),
                            "rows": len(output),
                            "query_count": 1,
                            "output_matches_source": True,
                        })

            projection_columns = list(SoldierScoreProjection.__table__.columns.keys())
            artifact = {
                "captured_at_utc": datetime.now(UTC).isoformat(),
                "profile_type": "synthetic isolated PostgreSQL ORM hydration microbenchmark",
                "not_route_or_page_latency": True,
                "database": {
                    **details,
                    "container_image": "postgres:16-alpine",
                    "lifecycle": "created by repository Testcontainers helper and removed on exit",
                    "container_settings": (
                        "repository helper sets fsync=off, full_page_writes=off, "
                        "synchronous_commit=off"
                    ),
                    "schema": (
                        "production SoldierScoreProjection SQLAlchemy mapping and its "
                        "foreign key, with a minimal disposable soldiers(id) parent table; "
                        "no application migrations or external database"
                    ),
                },
                "dataset": {
                    "rows": ROW_COUNT,
                    "source": "deterministic synthetic projection rows, inserted once and shared by both variants",
                    "orm_mapped_columns": projection_columns,
                    "selected_columns": ["soldier_id", "cumulative_score", "shift_count"],
                    "all_variants_return_same_mapping": True,
                },
                "method": {
                    "warmups_per_variant": warmups,
                    "measured_rounds_per_variant": repetitions,
                    "measured_order_by_round": measured_order,
                    "session_policy": "one fresh SQLAlchemy Session and transaction per paired round; both variants run once in the same transaction",
                    "cache_policy": "warm database/table cache; variants share one unchanged table and alternate order",
                    "timed_boundary": (
                        "one SELECT, result fetching, ORM/Row materialization, and construction "
                        "of soldier_id -> (cumulative_score, shift_count); excludes dataset setup"
                    ),
                    "reported_wall_times_are_not_server_only": True,
                },
                "variants": {
                    variant: {
                        "selected_column_count": len(projection_columns) if variant == "orm_entity" else 3,
                        "warmup_ms": warmup_samples[variant],
                        "samples": measured[variant],
                        "summary": _summarize(measured[variant]),
                    }
                    for variant in VARIANTS
                },
                "limitations": [
                    "Synthetic projection values and disposable table; not the transparency service, endpoint, browser, or full route workload.",
                    "Excludes active soldier loading, readiness checks, repairs, burden calculation, hierarchy and exemption reads, sorting, snapshot writes, JSON serialization, and network HTTP overhead.",
                    "The repository test container disables PostgreSQL durability settings; read-path timings do not model production configuration or load.",
                    "Seven measured rounds on one local container are directional microbenchmark evidence, not a production latency guarantee.",
                ],
            }
        finally:
            engine.dispose()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            REPO_DIR
            / "docs"
            / "benchmarks"
            / "data"
            / "transparency-projection-select-comparison-20261004.json"
        ),
    )
    args = parser.parse_args()
    artifact = run(args.repetitions, args.warmups, args.output)
    for variant, result in artifact["variants"].items():
        print(f"{variant}: {result['summary']}")
    print(f"artifact: {args.output}")


if __name__ == "__main__":
    main()
