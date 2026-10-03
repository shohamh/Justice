"""Add a deterministic synthetic dataset to an isolated PostgreSQL database.

The command intentionally does not use the normal ``DATABASE_URL`` setting.
It only inserts or reuses rows in the reserved SCALE20 namespace and never
updates or deletes existing data.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil
from typing import Any

from sqlalchemy import Engine, create_engine, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError

from app.auth.password import hash_password
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyType,
    HierarchyLevelType,
    HierarchyNode,
    HrRankConflict,
    Soldier,
    SoldierHrProfile,
)

SCALE_DATABASE_URL_ENV = "JUSTICE_SCALE_DATABASE_URL"
SYNTHETIC_PREFIX = "SCALE20-"
MAX_BATCH_SIZE = 10_000
SEED_NAMESPACE = uuid.UUID("9a6ca943-a898-4e74-9022-9700a5dbfd2d")
HISTORY_END_DATE = date(2026, 9, 29)
REVIEW_EXCEPTION_KINDS = ("held", "divergent", "vanished", "conflict")
_TEST_ONLY_PASSWORD = "scale-seed-test-only-password"

@dataclass(frozen=True)
class ScaleSeedConfig:
    soldiers: int = 20_000
    team_size: int = 50
    history_years: int = 2
    assignments_per_year: int = 25
    hr_exception_ratio: float = 0.01

    def __post_init__(self) -> None:
        if self.soldiers < 1:
            raise ValueError("--soldiers must be at least 1")
        if self.team_size < 1:
            raise ValueError("--team-size must be at least 1")
        if self.history_years < 1:
            raise ValueError("--history-years must be at least 1")
        if not 1 <= self.assignments_per_year <= 365:
            raise ValueError("--assignments-per-year must be between 1 and 365")
        if not 0 <= self.hr_exception_ratio <= 1:
            raise ValueError("--hr-exception-ratio must be between 0 and 1")

    @property
    def team_count(self) -> int:
        return ceil(self.soldiers / self.team_size)

    @property
    def assignment_count(self) -> int:
        return self.soldiers * self.history_years * self.assignments_per_year

    @property
    def history_days(self) -> int:
        return self.history_years * 365

    @property
    def history_start_date(self) -> date:
        return HISTORY_END_DATE - timedelta(days=self.history_days - 1)

    @property
    def hr_profile_count(self) -> int:
        return self.soldiers

    @property
    def hr_exception_count(self) -> int:
        return int(self.soldiers * self.hr_exception_ratio + 0.5)


class ScaleSeedCollisionError(RuntimeError):
    """An existing reserved-namespace row differs from the deterministic seed."""


def synthetic_uuid(kind: str, identity: str) -> uuid.UUID:
    """Return a stable UUID for one record in the SCALE20 namespace."""
    return uuid.uuid5(SEED_NAMESPACE, f"{kind}:{identity}")


def validate_target_database_url(database_url: str | None) -> URL:
    """Parse and validate the explicit, isolated PostgreSQL target URL."""
    if not database_url or not database_url.strip():
        raise ValueError(
            f"Set {SCALE_DATABASE_URL_ENV} to a dedicated PostgreSQL scale database."
        )

    try:
        parsed = make_url(database_url)
    except Exception as exc:
        raise ValueError(f"{SCALE_DATABASE_URL_ENV} is not a valid SQLAlchemy URL.") from exc

    database_name = (parsed.database or "").casefold()
    safe_name = "_scale" in database_name or "_perf" in database_name
    if (
        parsed.get_backend_name() != "postgresql"
        or database_name in {"justice", "postgres"}
        or not safe_name
    ):
        raise ValueError(
            f"{SCALE_DATABASE_URL_ENV} must target PostgreSQL with a database name "
            "containing _scale or _perf; the default justice and postgres databases "
            "are not allowed."
        )
    return parsed


def target_database_url(environ: Mapping[str, str] | None = None) -> URL:
    """Read only the dedicated scale URL, with no DATABASE_URL fallback."""
    source = os.environ if environ is None else environ
    return validate_target_database_url(source.get(SCALE_DATABASE_URL_ENV))


def create_scale_engine(environ: Mapping[str, str] | None = None) -> Engine:
    """Validate the target fully before asking SQLAlchemy to create an engine."""
    return create_engine(target_database_url(environ), pool_pre_ping=True)


def personal_number(index: int) -> str:
    return f"{SYNTHETIC_PREFIX}{index + 1:05d}"


def team_node_id(index: int) -> uuid.UUID:
    return synthetic_uuid("team", f"{index + 1:04d}")


def iter_team_rows(
    config: ScaleSeedConfig,
    *,
    root_id: uuid.UUID,
    root_path: Sequence[uuid.UUID],
) -> Iterator[dict[str, Any]]:
    for index in range(config.team_count):
        node_id = team_node_id(index)
        yield {
            "id": node_id,
            "level": "team",
            "name": f"SCALE20 Team {index + 1:04d}",
            "parent_id": root_id,
            "commander_id": None,
            "path_ids": [*root_path, node_id],
        }


def iter_soldier_rows(
    config: ScaleSeedConfig,
    *,
    password_hash: str,
) -> Iterator[dict[str, Any]]:
    for index in range(config.soldiers):
        pn = personal_number(index)
        team_index = index // config.team_size
        yield {
            "id": synthetic_uuid("soldier", f"{index + 1:05d}"),
            "personal_number": pn,
            "full_name": f"Scale Test Soldier {index + 1:05d}",
            "password_hash": password_hash,
            "role": "soldier",
            "hierarchy_node_id": team_node_id(team_index),
            "email": f"{pn.lower()}@example.invalid",
            "gender": "male" if index % 2 == 0 else "female",
        }


def hr_exception_kind(config: ScaleSeedConfig, soldier_index: int) -> str | None:
    """Evenly split the configured leading exception slice across review cases."""
    exceptions = config.hr_exception_count
    if soldier_index < 0 or soldier_index >= config.soldiers:
        raise IndexError("soldier index is outside the configured seed")
    if exceptions == 0 or soldier_index >= exceptions:
        return None
    bucket = min(len(REVIEW_EXCEPTION_KINDS) - 1, soldier_index * 4 // exceptions)
    return REVIEW_EXCEPTION_KINDS[bucket]


def iter_hr_profile_rows(config: ScaleSeedConfig) -> Iterator[dict[str, Any]]:
    for index in range(config.soldiers):
        pn = personal_number(index)
        kind = hr_exception_kind(config, index)
        if kind in ("held", "divergent"):
            sync_status = "held_for_review"
            review_reason = (
                "synthetic_missing_field" if kind == "held" else "synthetic_rank_divergence"
            )
        elif kind == "vanished":
            sync_status = "vanished"
            review_reason = None
        else:
            sync_status = "synced"
            review_reason = None

        yield {
            "id": synthetic_uuid("hr-profile", f"{index + 1:05d}"),
            "personal_number": pn,
            "raw_dto": {
                "personalNumber": pn,
                "fullName": f"Scale Test Soldier {index + 1:05d}",
                "synthetic": True,
            },
            "soldier_id": synthetic_uuid("soldier", f"{index + 1:05d}"),
            "sync_status": sync_status,
            "review_reason": review_reason,
        }


def iter_rank_conflict_rows(config: ScaleSeedConfig) -> Iterator[dict[str, Any]]:
    for index in range(config.soldiers):
        if hr_exception_kind(config, index) != "conflict":
            continue
        yield {
            "id": synthetic_uuid("hr-rank-conflict", f"{index + 1:05d}"),
            "soldier_id": synthetic_uuid("soldier", f"{index + 1:05d}"),
            "old_rank": "Scale Test Rank 1",
            "new_rank": "Scale Test Rank 2",
            "triggered_by_worker_decision": False,
            "non_sequential_jump": False,
            "hr_person_sync_id": None,
        }


def iter_assignment_specs(config: ScaleSeedConfig) -> Iterator[dict[str, Any]]:
    total = config.assignment_count
    last_day_offset = config.history_days - 1
    for index in range(total):
        offset = 0 if total == 1 else index * last_day_offset // (total - 1)
        start_date = config.history_start_date + timedelta(days=offset)
        soldier_index = index % config.soldiers
        yield {
            "id": synthetic_uuid("duty-assignment", f"{index + 1:07d}"),
            "soldier_id": synthetic_uuid("soldier", f"{soldier_index + 1:05d}"),
            "start_date": start_date,
            # DutyAssignment intervals use an exclusive end date.
            "end_date": start_date + timedelta(days=1),
            "status": "published",
            "is_reserve": False,
            "notes": "SCALE20 synthetic duty history",
            "duty_type_index": index,
            "duty_location_index": index,
        }


def iter_assignment_rows(
    config: ScaleSeedConfig,
    *,
    duty_type_ids: Sequence[uuid.UUID],
    duty_location_ids: Sequence[uuid.UUID],
) -> Iterator[dict[str, Any]]:
    if not duty_type_ids or not duty_location_ids:
        raise ValueError("The scale seed requires active duty type and location fixtures.")
    for spec in iter_assignment_specs(config):
        yield {
            key: value
            for key, value in spec.items()
            if key not in {"duty_type_index", "duty_location_index"}
        } | {
            "duty_type_id": duty_type_ids[spec["duty_type_index"] % len(duty_type_ids)],
            "duty_location_id": duty_location_ids[
                spec["duty_location_index"] % len(duty_location_ids)
            ],
        }


def iter_batches[T](
    items: Iterable[T], batch_size: int = MAX_BATCH_SIZE
) -> Iterator[list[T]]:
    if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE:,}.")
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _assert_existing_rows_compatible(
    connection: Any,
    *,
    model: Any,
    rows: Iterable[dict[str, Any]],
    identity_columns: Sequence[str],
    compare_columns: Sequence[str],
) -> None:
    """Reject any generated identity collision whose existing shape differs."""
    lookup_columns = tuple(dict.fromkeys((*identity_columns, "id")))
    for batch in iter_batches(rows):
        clauses = [
            getattr(model, column).in_([row[column] for row in batch])
            for column in identity_columns
        ]
        selected = [getattr(model, column) for column in compare_columns]
        existing = connection.execute(
            select(*selected).where(or_(*clauses))
        ).mappings()
        expected_by_identity = {
            (column, row[column]): row
            for row in batch
            for column in lookup_columns
        }
        for current in existing:
            expected = next(
                (
                    expected_by_identity[(column, current[column])]
                    for column in lookup_columns
                    if (column, current[column]) in expected_by_identity
                ),
                None,
            )
            if expected is None or any(
                current[column] != expected[column] for column in compare_columns
            ):
                raise ScaleSeedCollisionError(
                    "Existing SCALE20 seed data has an incompatible identity or field shape."
                )


def _insert_missing_rows(
    connection: Any,
    *,
    model: Any,
    rows: Iterable[dict[str, Any]],
    identity_column: str,
) -> tuple[int, int]:
    inserted = 0
    present = 0
    identity = getattr(model, identity_column)
    insert_statement = pg_insert(model.__table__).on_conflict_do_nothing(
        index_elements=[model.__table__.c.id]
    )

    for batch in iter_batches(rows):
        identities = [row[identity_column] for row in batch]
        existing = set(
            connection.execute(select(identity).where(identity.in_(identities))).scalars()
        )
        connection.commit()
        missing = [row for row in batch if row[identity_column] not in existing]
        if missing:
            connection.execute(insert_statement, missing)
            connection.commit()
            inserted += len(missing)
        present += len(existing)
    return inserted, present


def _preflight(
    connection: Any,
    config: ScaleSeedConfig,
    *,
    root_id: uuid.UUID,
    root_path: Sequence[uuid.UUID],
    duty_type_ids: Sequence[uuid.UUID],
    duty_location_ids: Sequence[uuid.UUID],
) -> None:
    _assert_existing_rows_compatible(
        connection,
        model=HierarchyNode,
        rows=iter_team_rows(config, root_id=root_id, root_path=root_path),
        identity_columns=("id", "name"),
        compare_columns=("id", "level", "name", "parent_id", "commander_id", "path_ids"),
    )
    _assert_existing_rows_compatible(
        connection,
        model=Soldier,
        rows=iter_soldier_rows(config, password_hash="<shared-test-hash>"),
        identity_columns=("id", "personal_number", "email"),
        compare_columns=(
            "id",
            "personal_number",
            "full_name",
            "role",
            "hierarchy_node_id",
            "email",
            "gender",
        ),
    )
    _preflight_profiles(connection, config)
    _assert_existing_rows_compatible(
        connection,
        model=HrRankConflict,
        rows=iter_rank_conflict_rows(config),
        identity_columns=("id", "soldier_id"),
        compare_columns=(
            "id",
            "soldier_id",
            "old_rank",
            "new_rank",
            "triggered_by_worker_decision",
            "non_sequential_jump",
            "hr_person_sync_id",
        ),
    )
    _assert_existing_rows_compatible(
        connection,
        model=DutyAssignment,
        rows=iter_assignment_rows(
            config,
            duty_type_ids=duty_type_ids,
            duty_location_ids=duty_location_ids,
        ),
        identity_columns=("id",),
        compare_columns=(
            "id",
            "soldier_id",
            "duty_type_id",
            "duty_location_id",
            "start_date",
            "end_date",
            "status",
            "is_reserve",
            "notes",
        ),
    )
    connection.rollback()


def _preflight_profiles(connection: Any, config: ScaleSeedConfig) -> None:
    _assert_existing_rows_compatible(
        connection,
        model=SoldierHrProfile,
        rows=iter_hr_profile_rows(config),
        identity_columns=("id", "personal_number"),
        compare_columns=(
            "id",
            "personal_number",
            "raw_dto",
            "soldier_id",
            "sync_status",
            "review_reason",
        ),
    )


def validate_team_hierarchy_level(
    root_level: str, configured_level_ranks: Mapping[str, int]
) -> None:
    """Require a configured team level ranked below the initialized root."""
    root_rank = configured_level_ranks.get(root_level)
    if root_rank is None:
        raise ValueError("The target root hierarchy level is not configured.")

    team_rank = configured_level_ranks.get("team")
    if team_rank is None:
        raise ValueError("The target has no configured team hierarchy level.")
    if team_rank <= root_rank:
        raise ValueError("The configured team hierarchy level must be below the root level.")


def _read_base_fixtures(connection: Any) -> tuple[
    uuid.UUID,
    list[uuid.UUID],
    list[uuid.UUID],
    list[uuid.UUID],
]:
    roots = connection.execute(
        select(HierarchyNode.id, HierarchyNode.level, HierarchyNode.path_ids).where(
            HierarchyNode.parent_id.is_(None)
        )
    ).mappings().all()
    if len(roots) != 1:
        raise ValueError("The target must have exactly one initialized hierarchy root.")
    root = roots[0]
    root_id = root["id"]
    root_level = root["level"]
    root_path = list(root["path_ids"] or [])
    if not root_path or root_path[-1] != root_id:
        raise ValueError("The target hierarchy root is not initialized.")

    configured_level_ranks = dict(
        connection.execute(
            select(HierarchyLevelType.key, HierarchyLevelType.rank).where(
                HierarchyLevelType.key.in_((root_level, "team"))
            )
        ).all()
    )
    validate_team_hierarchy_level(root_level, configured_level_ranks)

    duty_type_ids = list(
        connection.execute(
            select(DutyType.id)
            .where(DutyType.active.is_(True))
            .order_by(DutyType.id)
        ).scalars()
    )
    duty_location_ids = list(
        connection.execute(
            select(DutyLocation.id)
            .where(DutyLocation.active.is_(True))
            .order_by(DutyLocation.id)
        ).scalars()
    )
    if not duty_type_ids or not duty_location_ids:
        raise ValueError("The target must contain active duty types and locations.")
    return root_id, root_path, duty_type_ids, duty_location_ids


def seed_database(
    engine: Engine,
    config: ScaleSeedConfig,
) -> tuple[dict[str, tuple[int, int]], dict[str, float]]:
    """Preflight all deterministic rows, then insert missing rows in safe batches."""
    password_hash = hash_password(_TEST_ONLY_PASSWORD)
    phase_seconds: dict[str, float] = {}
    with engine.connect() as connection:
        phase_started = time.perf_counter()
        root_id, root_path, duty_type_ids, duty_location_ids = _read_base_fixtures(connection)
        phase_seconds["read_fixtures"] = time.perf_counter() - phase_started

        phase_started = time.perf_counter()
        _preflight(
            connection,
            config,
            root_id=root_id,
            root_path=root_path,
            duty_type_ids=duty_type_ids,
            duty_location_ids=duty_location_ids,
        )
        phase_seconds["preflight"] = time.perf_counter() - phase_started

        counts: dict[str, tuple[int, int]] = {}
        phase_started = time.perf_counter()
        counts["teams"] = _insert_missing_rows(
            connection,
            model=HierarchyNode,
            rows=iter_team_rows(config, root_id=root_id, root_path=root_path),
            identity_column="id",
        )
        phase_seconds["teams"] = time.perf_counter() - phase_started

        phase_started = time.perf_counter()
        counts["soldiers"] = _insert_missing_rows(
            connection,
            model=Soldier,
            rows=iter_soldier_rows(config, password_hash=password_hash),
            identity_column="personal_number",
        )
        phase_seconds["soldiers"] = time.perf_counter() - phase_started

        phase_started = time.perf_counter()
        counts["hr_profiles"] = _insert_missing_rows(
            connection,
            model=SoldierHrProfile,
            rows=iter_hr_profile_rows(config),
            identity_column="personal_number",
        )
        phase_seconds["hr_profiles"] = time.perf_counter() - phase_started

        phase_started = time.perf_counter()
        counts["hr_rank_conflicts"] = _insert_missing_rows(
            connection,
            model=HrRankConflict,
            rows=iter_rank_conflict_rows(config),
            identity_column="id",
        )
        phase_seconds["hr_rank_conflicts"] = time.perf_counter() - phase_started

        phase_started = time.perf_counter()
        counts["duty_assignments"] = _insert_missing_rows(
            connection,
            model=DutyAssignment,
            rows=iter_assignment_rows(
                config,
                duty_type_ids=duty_type_ids,
                duty_location_ids=duty_location_ids,
            ),
            identity_column="id",
        )
        phase_seconds["duty_assignments"] = time.perf_counter() - phase_started
        return counts, phase_seconds


def _parse_args(argv: Sequence[str] | None = None) -> ScaleSeedConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--soldiers", type=int, default=20_000)
    parser.add_argument("--team-size", type=int, default=50)
    parser.add_argument("--history-years", type=int, default=2)
    parser.add_argument("--assignments-per-year", type=int, default=25)
    parser.add_argument("--hr-exception-ratio", type=float, default=0.01)
    args = parser.parse_args(argv)
    return ScaleSeedConfig(
        soldiers=args.soldiers,
        team_size=args.team_size,
        history_years=args.history_years,
        assignments_per_year=args.assignments_per_year,
        hr_exception_ratio=args.hr_exception_ratio,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        config = _parse_args(argv)
        started = time.perf_counter()
        engine = create_scale_engine()
        try:
            counts, phase_seconds = seed_database(engine, config)
        finally:
            engine.dispose()
    except (ValueError, ScaleSeedCollisionError) as exc:
        print(f"Scale seed aborted: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print(
            "Scale seed aborted during a database operation. Completed batches contain "
            "only SCALE20 synthetic rows and are safe to rerun.",
            file=sys.stderr,
        )
        return 2

    for table_name, (inserted, present) in counts.items():
        print(f"{table_name}: inserted={inserted} already_present={present}")
    exception_counts = {
        kind: sum(hr_exception_kind(config, index) == kind for index in range(config.soldiers))
        for kind in REVIEW_EXCEPTION_KINDS
    }
    print(f"history_days={config.history_days} assignments={config.assignment_count}")
    print(
        "hr_review_exceptions: "
        f"total={config.hr_exception_count} "
        + " ".join(f"{kind}={count}" for kind, count in exception_counts.items())
    )
    for phase_name, seconds in phase_seconds.items():
        print(f"phase={phase_name} seconds={seconds:.2f}")
    print(f"elapsed_seconds={time.perf_counter() - started:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
