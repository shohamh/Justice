"""Compare transparency JSONB chunk write paths on an ephemeral PostgreSQL."""

from __future__ import annotations

import argparse
import json
import platform
import random
import sys
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from statistics import mean, median
from typing import Any
from uuid import UUID, uuid5

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import psycopg  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Connection, Engine  # noqa: E402

from tests.support import database  # noqa: E402

ROW_COUNT = 20_270
ROWS_PER_CHUNK = 100
NAMESPACE = UUID("11223344-5566-7788-9900-aabbccddeeff")
VARIANTS = ("jsonb_array", "executemany", "copy")

CURRENT_INSERT = text("""
    INSERT INTO transparency_page_snapshot_rows (snapshot_id, ordinal, payload)
    SELECT :id, :chunk_start + value.ordinal - 1, value.payload
    FROM jsonb_array_elements(CAST(:chunks AS jsonb))
         WITH ORDINALITY AS value(payload, ordinal)
""")
EXECUTEMANY_INSERT = text("""
    INSERT INTO transparency_page_snapshot_rows (snapshot_id, ordinal, payload)
    VALUES (:id, :ordinal, CAST(:payload AS jsonb))
""")
COPY_INSERT = (
    "COPY transparency_page_snapshot_rows (snapshot_id, ordinal, payload) FROM STDIN"
)


def _version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"


def make_rows(count: int) -> list[dict[str, Any]]:
    """Build full TransparencyPageItem-shaped rows with production-like types."""
    start = date(2020, 1, 1)
    rows: list[dict[str, Any]] = []
    for index in range(count):
        soldier_id = uuid5(NAMESPACE, f"soldier-{index}")
        has_exemption = index % 47 == 0
        rows.append({
            "row_num": index + 1,
            "soldier_id": soldier_id,
            "full_name": f"Synthetic Soldier {index + 1:05d}",
            "node_id": uuid5(NAMESPACE, f"node-{index // 100}"),
            "node_name": f"Synthetic Unit {index // 100:03d}",
            "enrolled_at": start + timedelta(days=index % 2_400),
            "active_days": 500 + index % 4_000,
            "shift_count": index % 250,
            "rank": ("private", "corporal", "sergeant", "officer")[index % 4],
            "is_officer": index % 4 == 3,
            "service_type": ("combat", "support", "staff")[index % 3],
            "cumulative_score": Decimal(index % 8_000) / Decimal("17"),
            "score_per_day": Decimal(index % 250) / Decimal("31"),
            "normalised_score": Decimal(index % 1_000) / Decimal("113"),
            "is_globally_exempted": has_exemption and index % 2 == 0,
            "burden_share": (index % 2_000) / 10_000,
            "c_over_d": (index % 500) / 1_000,
            "burden_share_offset_raw": (index % 2_000) - 1_000,
            "exemptions_display": "Medical" if has_exemption else "",
            "exemptions_visible": True,
            "exemptions": ([{
                "id": uuid5(NAMESPACE, f"exemption-{index}"),
                "exemption_type_name": "Medical",
                "is_global": index % 2 == 0,
                "start_date": start + timedelta(days=index % 2_400),
                "end_date": None,
            }] if has_exemption else []),
            "has_global_exemption": index % 2 == 0 if has_exemption else None,
            "has_partial_exemption": index % 2 == 1 if has_exemption else None,
            "has_temporary_exemption": False if has_exemption else None,
        })
    return rows


def chunk_rows(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [rows[offset:offset + ROWS_PER_CHUNK] for offset in range(0, len(rows), ROWS_PER_CHUNK)]


def _prepare(variant: str, snapshot_id: UUID, rows: list[dict[str, Any]]) -> tuple[Any, int]:
    chunks = chunk_rows(rows)
    if variant == "jsonb_array":
        encoded = json.dumps(chunks, default=str)
        return {
            "id": snapshot_id,
            "chunk_start": 0,
            "chunks": encoded,
        }, len(encoded.encode("utf-8"))
    parameters = [
        {
            "id": snapshot_id,
            "ordinal": ordinal,
            "payload": json.dumps(chunk, default=str),
        }
        for ordinal, chunk in enumerate(chunks)
    ]
    serialized_bytes = sum(len(item["payload"].encode("utf-8")) for item in parameters)
    return parameters, serialized_bytes


def _write(connection: Connection, variant: str, prepared: Any) -> float:
    started = time.perf_counter()
    if variant == "jsonb_array":
        connection.execute(CURRENT_INSERT, prepared)
    elif variant == "executemany":
        connection.execute(EXECUTEMANY_INSERT, prepared)
    elif variant == "copy":
        # COPY uses the exact DBAPI connection owned by this SQLAlchemy Connection,
        # so the inserts participate in its currently open PostgreSQL transaction.
        raw_connection = connection.connection.driver_connection
        with raw_connection.cursor().copy(COPY_INSERT) as copy:
            for item in prepared:
                copy.write_row((item["id"], item["ordinal"], item["payload"]))
    else:
        raise ValueError(f"unknown write variant: {variant}")
    return time.perf_counter() - started


def _begin(connection: Connection) -> None:
    connection.begin()
    # Force the DBAPI transaction to start before a candidate can use raw COPY.
    connection.execute(text("SELECT 1"))


def _create_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA transparency_write_bench"))
        connection.execute(text("SET search_path TO transparency_write_bench, public"))
        connection.execute(text("""
            CREATE TABLE transparency_page_snapshots (
                id uuid PRIMARY KEY
            )
        """))
        connection.execute(text("""
            CREATE TABLE transparency_page_snapshot_rows (
                snapshot_id uuid NOT NULL REFERENCES transparency_page_snapshots(id)
                    ON DELETE CASCADE,
                ordinal integer NOT NULL,
                payload jsonb NOT NULL,
                PRIMARY KEY (snapshot_id, ordinal)
            )
        """))


def _configure_search_path(connection: Connection) -> None:
    connection.execute(text("SET search_path TO transparency_write_bench, public"))
    connection.commit()


def _reset(connection: Connection) -> None:
    connection.execute(text("""
        TRUNCATE transparency_page_snapshot_rows, transparency_page_snapshots
    """))
    connection.commit()


def _insert_parent(connection: Connection, snapshot_id: UUID) -> None:
    connection.execute(
        text("INSERT INTO transparency_page_snapshots (id) VALUES (:id)"),
        {"id": snapshot_id},
    )


def _rollback_check(engine: Engine, rows: list[dict[str, Any]], variant: str) -> None:
    snapshot_id = uuid5(NAMESPACE, f"rollback-{variant}")
    with engine.connect() as connection:
        _configure_search_path(connection)
        _begin(connection)
        _insert_parent(connection, snapshot_id)
        prepared, _serialized_bytes = _prepare(variant, snapshot_id, rows)
        _write(connection, variant, prepared)
        connection.rollback()
    with engine.connect() as connection:
        _configure_search_path(connection)
        count = connection.execute(text("""
            SELECT count(*) FROM transparency_page_snapshot_rows
        """)).scalar_one()
        connection.rollback()
    if count != 0:
        raise AssertionError(f"{variant} did not roll back atomically; {count} chunks remain")


def _verify(connection: Connection, rows: list[dict[str, Any]]) -> float:
    started = time.perf_counter()
    chunks = chunk_rows(rows)
    actual = connection.execute(text("""
        SELECT ordinal, payload
        FROM transparency_page_snapshot_rows
        ORDER BY ordinal
    """)).all()
    expected = [json.loads(json.dumps(chunk, default=str)) for chunk in chunks]
    if [ordinal for ordinal, _payload in actual] != list(range(len(chunks))):
        raise AssertionError("chunk ordinals differ from the expected zero-based sequence")
    if [payload for _ordinal, payload in actual] != expected:
        raise AssertionError("stored JSONB chunks differ from the expected response rows")
    count, total_rows = connection.execute(text("""
        SELECT count(*), coalesce(sum(jsonb_array_length(payload)), 0)
        FROM transparency_page_snapshot_rows
    """)).one()
    if count != len(chunks) or total_rows != len(rows):
        raise AssertionError(f"stored {total_rows} rows in {count} chunks; expected {len(rows)} in {len(chunks)}")
    return time.perf_counter() - started


def measure_once(
    engine: Engine, rows: list[dict[str, Any]], variant: str, payload_bytes: int,
) -> dict[str, float | int | str]:
    snapshot_id = uuid5(NAMESPACE, f"measure-{variant}-{time.time_ns()}")
    with engine.connect() as connection:
        _configure_search_path(connection)
        _reset(connection)
        _begin(connection)
        _insert_parent(connection, snapshot_id)

        preparation_started = time.perf_counter()
        prepared, serialized_bytes = _prepare(variant, snapshot_id, rows)
        preparation_seconds = time.perf_counter() - preparation_started
        write_seconds = _write(connection, variant, prepared)
        verification_seconds = _verify(connection, rows)
        commit_started = time.perf_counter()
        connection.commit()
        commit_seconds = time.perf_counter() - commit_started

    return {
        "variant": variant,
        "python_prepare_ms": round(preparation_seconds * 1000, 3),
        "client_write_ms": round(write_seconds * 1000, 3),
        "verification_ms": round(verification_seconds * 1000, 3),
        "commit_ms": round(commit_seconds * 1000, 3),
        "prepare_plus_write_ms": round((preparation_seconds + write_seconds) * 1000, 3),
        "transaction_total_ms": round((preparation_seconds + write_seconds + commit_seconds) * 1000, 3),
        "serialized_input_bytes": serialized_bytes,
        "json_chunk_payload_bytes": payload_bytes,
    }


def summarize(samples: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for field in (
        "python_prepare_ms", "client_write_ms", "verification_ms", "commit_ms",
        "prepare_plus_write_ms", "transaction_total_ms",
    ):
        values = [float(sample[field]) for sample in samples]
        summary[field] = {
            "min": round(min(values), 3),
            "median": round(median(values), 3),
            "mean": round(mean(values), 3),
        }
    return summary


def _server_details(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        version_string, server_version = connection.execute(text(
            "SELECT version(), current_setting('server_version')"
        )).one()
        connection.rollback()
    return {
        "postgres_version": server_version,
        "postgres_version_string": version_string,
        "psycopg_version": psycopg.__version__,
        "sqlalchemy_version": _version("sqlalchemy"),
        "testcontainers_version": _version("testcontainers"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


def run(repetitions: int, output_path: Path) -> dict[str, Any]:
    rows = make_rows(ROW_COUNT)
    # Compute the common stored-payload byte count once, outside each candidate's
    # timed Python preparation path.
    payload_bytes = sum(
        len(json.dumps(chunk, default=str).encode("utf-8"))
        for chunk in chunk_rows(rows)
    )
    with database.new_postgres_container() as container:
        engine = create_engine(database.render_psycopg_url(container.get_connection_url()))
        try:
            _create_schema(engine)
            details = _server_details(engine)
            for variant in VARIANTS:
                _rollback_check(engine, rows, variant)

            # One unrecorded warm-up for each candidate; randomize measured order
            # by round so a fixed order does not favor one method.
            warmups = {
                variant: measure_once(engine, rows, variant, payload_bytes)
                for variant in VARIANTS
            }
            samples: dict[str, list[dict[str, Any]]] = {variant: [] for variant in VARIANTS}
            rng = random.Random(20_270)
            for _ in range(repetitions):
                order = list(VARIANTS)
                rng.shuffle(order)
                for variant in order:
                    samples[variant].append(
                        measure_once(engine, rows, variant, payload_bytes)
                    )

            chunk_sizes = [len(chunk) for chunk in chunk_rows(rows)]
            artifact = {
                "captured_at_utc": datetime.now(UTC).isoformat(),
                "profile_type": "synthetic isolated PostgreSQL chunk-write comparison",
                "not_an_end_to_end_or_browser_profile": True,
                "database": {
                    **details,
                    "container_image": "postgres:16-alpine",
                    "lifecycle": "created by the repository testcontainers helper and removed on exit",
                    "container_settings": "repository helper options: fsync=off, full_page_writes=off, synchronous_commit=off",
                    "schema": "ephemeral transparency_write_bench schema with the production chunk table columns, foreign key, and composite primary key",
                },
                "shape": {
                    "response_rows": ROW_COUNT,
                    "chunk_rows": ROWS_PER_CHUNK,
                    "chunk_count": len(chunk_sizes),
                    "chunk_sizes": chunk_sizes,
                    "payload_model": "full TransparencyPageItem field shape with UUID, date, Decimal, nullable, and nested exemption values",
                    "json_chunk_payload_bytes": payload_bytes,
                },
                "method": {
                    "warmups_per_variant": 1,
                    "measured_repetitions_per_variant": repetitions,
                    "measured_order": "seeded randomized order by round",
                    "same_empty_table_and_primary_key_index": True,
                    "time_boundary": "Python chunk/JSON preparation, client execute/COPY span, verification, and COMMIT reported separately; client write includes driver adaptation, network, and PostgreSQL work, not server-only execution time",
                    "atomicity": "all three methods inserted through one open SQLAlchemy-owned connection transaction; each variant passed explicit rollback verification; measured runs committed before the next TRUNCATE",
                },
                "variants": {
                    variant: {
                        "implementation": {
                            "jsonb_array": "Current production SQL: one JSON array bind expanded with jsonb_array_elements and WITH ORDINALITY.",
                            "executemany": "SQLAlchemy Core execute with a list of 203 per-chunk JSONB bind parameter dictionaries.",
                            "copy": "psycopg 3 cursor.copy/write_row on the same DBAPI connection and open SQLAlchemy transaction.",
                        }[variant],
                        "warmup": warmups[variant],
                        "samples": samples[variant],
                        "summary": summarize(samples[variant]),
                        "rollback_verified": True,
                        "payload_and_ordinal_parity_verified": True,
                        "limitation": (
                            "Uses psycopg-specific access to SQLAlchemy's underlying driver connection."
                            if variant == "copy"
                            else "Synthetic rows and isolated write workload; excludes transparency projection construction and route serialization."
                        ),
                    }
                    for variant in VARIANTS
                },
                "decision_threshold": "No production change unless a candidate has a repeatable material improvement and preserves the existing one-transaction semantics with maintainable integration.",
            }
        finally:
            engine.dispose()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_DIR / "docs" / "benchmarks" / "data" / "transparency-chunk-write-comparison-20261004.json",
    )
    args = parser.parse_args()
    if args.repetitions < 3:
        parser.error("at least three measured repetitions are required")
    artifact = run(args.repetitions, args.output)
    print(json.dumps({
        "output": str(args.output),
        "database": artifact["database"]["postgres_version"],
        "samples": {
            variant: artifact["variants"][variant]["summary"]
            for variant in VARIANTS
        },
    }, indent=2))


if __name__ == "__main__":
    main()
