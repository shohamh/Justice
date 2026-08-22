from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, event, func, insert, select, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyType,
    HierarchyNode,
    ScoreProjectionQuarterTotal,
    ScoreProjectionState,
    Soldier,
    SoldierQuarterScoreProjection,
    SoldierScoreProjection,
)
from app.services import commander_dashboard, scoring, score_projection
from app.services.settings_loader import set_setting

DEFAULT_SOURCE_DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://app:app_pw@localhost:5432/justice"
)
DEFAULT_SOURCE_DB_ADMIN_URL = os.environ.get(
    "DB_ADMIN_URL", "postgresql+psycopg://db_admin:db_admin_pw@localhost:5432/justice"
)


@dataclass
class Measurement:
    wall_seconds: float
    db_seconds: float
    python_seconds: float
    query_count: int


@dataclass
class DatasetStats:
    soldiers: int
    assignments: int
    hierarchy_nodes: int
    soldier_score_projection_rows: int
    soldier_quarter_score_projection_rows: int
    quarter_total_rows: int


class QueryTimer:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.query_count = 0
        self.db_seconds = 0.0

    def _before(
        self, _conn, _cursor, _statement, _parameters, context, _executemany
    ) -> None:
        context._score_projection_benchmark_started_at = time.perf_counter()

    def _after(
        self, _conn, _cursor, _statement, _parameters, context, _executemany
    ) -> None:
        started_at = getattr(context, "_score_projection_benchmark_started_at", None)
        if started_at is None:
            return
        self.query_count += 1
        self.db_seconds += time.perf_counter() - started_at

    def __enter__(self) -> "QueryTimer":
        event.listen(self.engine, "before_cursor_execute", self._before)
        event.listen(self.engine, "after_cursor_execute", self._after)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        event.remove(self.engine, "before_cursor_execute", self._before)
        event.remove(self.engine, "after_cursor_execute", self._after)


def _measure(engine: Engine, fn: Callable[[], Any]) -> tuple[Any, Measurement]:
    with QueryTimer(engine) as timer:
        started_at = time.perf_counter()
        result = fn()
        wall_seconds = time.perf_counter() - started_at
    measurement = Measurement(
        wall_seconds=wall_seconds,
        db_seconds=timer.db_seconds,
        python_seconds=max(0.0, wall_seconds - timer.db_seconds),
        query_count=timer.query_count,
    )
    return result, measurement


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _url_with_database(raw_url: str, database_name: str) -> str:
    url = make_url(raw_url)
    return url.set(database=database_name).render_as_string(hide_password=False)


def _prepare_database(admin_url: str, database_name: str) -> None:
    admin = make_url(admin_url)
    maintenance_url = admin.set(database="postgres")
    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT", future=True)
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :database_name
                  AND pid <> pg_backend_pid()
                """
            ),
            {"database_name": database_name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        conn.execute(text(f'CREATE DATABASE "{database_name}"'))
    engine.dispose()


def _run_subprocess(args: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "subprocess failed\n"
            f"command: {' '.join(args)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def _migrate_database(backend_dir: Path, database_url: str, db_admin_url: str) -> str:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["DB_ADMIN_URL"] = db_admin_url
    completed = _run_subprocess(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=env,
    )
    return completed.stdout.strip()


def _seed_database(backend_dir: Path, database_url: str, db_admin_url: str) -> str:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["DB_ADMIN_URL"] = db_admin_url
    completed = _run_subprocess(
        [sys.executable, "-m", "app.scripts.seed", "--clear", "--db-url", database_url],
        cwd=backend_dir,
        env=env,
    )
    return completed.stdout.strip()


def _chunked[T](items: list[T], size: int) -> Iterator[list[T]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def _ensure_perf_shape(
    session: Session,
    *,
    target_soldier_count: int,
    target_assignment_count: int,
    team_count: int,
) -> dict[str, Any]:
    today = date.today()
    now = datetime.now(timezone.utc)
    existing_soldiers = session.execute(select(func.count(Soldier.id))).scalar_one()
    existing_assignments = session.execute(select(func.count(DutyAssignment.id))).scalar_one()
    if existing_soldiers > target_soldier_count:
        raise RuntimeError(
            f"justice_perf already has {existing_soldiers} soldiers, above requested {target_soldier_count}"
        )
    if existing_assignments > target_assignment_count:
        raise RuntimeError(
            f"justice_perf already has {existing_assignments} assignments, above requested {target_assignment_count}"
        )

    parent = session.execute(
        select(HierarchyNode).where(HierarchyNode.level == "group").order_by(HierarchyNode.name)
    ).scalars().first()
    if parent is None:
        raise RuntimeError("No group node exists after seed; cannot attach perf teams")

    existing_team_names = set(
        session.execute(
            select(HierarchyNode.name).where(HierarchyNode.name.like("Perf Team %"))
        ).scalars().all()
    )
    team_rows: list[dict[str, Any]] = []
    team_ids: list[uuid.UUID] = []
    for index in range(team_count):
        name = f"Perf Team {index + 1:03d}"
        if name in existing_team_names:
            team_id = session.execute(
                select(HierarchyNode.id).where(HierarchyNode.name == name)
            ).scalar_one()
        else:
            team_id = uuid.uuid4()
            team_rows.append(
                {
                    "id": team_id,
                    "parent_id": parent.id,
                    "level": "team",
                    "name": name,
                    "commander_id": None,
                    "path_ids": list(parent.path_ids) + [team_id],
                    "created_at": now,
                    "updated_at": now,
                }
            )
        team_ids.append(team_id)
    if team_rows:
        session.execute(insert(HierarchyNode), team_rows)
        session.commit()

    password_hash = session.execute(
        select(Soldier.password_hash).where(Soldier.personal_number == "1000001")
    ).scalar_one()
    soldiers_to_add = target_soldier_count - existing_soldiers
    synthetic_soldier_ids: list[uuid.UUID] = []
    if soldiers_to_add > 0:
        _log(f"Creating {soldiers_to_add} synthetic soldiers")
        soldier_rows: list[dict[str, Any]] = []
        for index in range(soldiers_to_add):
            soldier_id = uuid.uuid4()
            team_id = team_ids[index % len(team_ids)]
            personal_number = f"perf-{index + 1:05d}"
            soldier_rows.append(
                {
                    "id": soldier_id,
                    "personal_number": personal_number,
                    "full_name": f"Perf Soldier {index + 1:05d}",
                    "password_hash": password_hash,
                    "role": "soldier",
                    "hierarchy_node_id": team_id,
                    "enrolled_at": today - timedelta(days=(index % 730) + 1),
                    "must_change_password": False,
                    "created_at": now,
                    "updated_at": now,
                    "bahad1_graduate": False,
                    "email_verified": False,
                    "token_version": 0,
                    "failed_login_count": 0,
                    "is_career": False,
                    "theme_preference": "light",
                    "next_rank_date_overridden": False,
                }
            )
            synthetic_soldier_ids.append(soldier_id)
        for chunk in _chunked(soldier_rows, 2_000):
            session.execute(insert(Soldier), chunk)
            session.commit()
    else:
        synthetic_soldier_ids = session.execute(
            select(Soldier.id)
            .where(Soldier.personal_number.like("perf-%"))
            .order_by(Soldier.personal_number)
        ).scalars().all()

    if not synthetic_soldier_ids:
        raise RuntimeError("No synthetic soldiers available for assignment generation")

    duty_type_ids = session.execute(
        select(DutyType.id).where(DutyType.active.is_(True)).order_by(DutyType.name)
    ).scalars().all()
    duty_location_ids = session.execute(select(DutyLocation.id).order_by(DutyLocation.name)).scalars().all()
    if not duty_type_ids or not duty_location_ids:
        raise RuntimeError("Seed did not produce active duty types and locations")

    assignments_to_add = target_assignment_count - existing_assignments
    if assignments_to_add > 0:
        _log(f"Creating {assignments_to_add} synthetic assignments")
        assignment_rows: list[dict[str, Any]] = []
        for index in range(assignments_to_add):
            start_date = today - timedelta(days=(index % 730) + 1)
            assignment_rows.append(
                {
                    "id": uuid.uuid4(),
                    "soldier_id": synthetic_soldier_ids[index % len(synthetic_soldier_ids)],
                    "duty_type_id": duty_type_ids[index % len(duty_type_ids)],
                    "duty_location_id": duty_location_ids[(index // len(duty_type_ids)) % len(duty_location_ids)],
                    "start_date": start_date,
                    "end_date": start_date + timedelta(days=1),
                    "status": "published",
                    "created_by": None,
                    "notes": None,
                    "created_at": now,
                    "duty_shift_id": None,
                    "is_reserve": False,
                    "called_up_from": None,
                    "called_up_to": None,
                    "forced_call_up_multiplier": None,
                    "batch_index": None,
                    "start_time": "08:00",
                    "end_time": "17:00",
                    "algorithm_job_id": None,
                    "norm_score_before": None,
                    "norm_score_after": None,
                    "candidate_rank": None,
                    "candidate_pool_size": None,
                    "weapon_ineligible": False,
                    "weapon_ineligible_reason": None,
                    "weapon_ineligible_detected_at": None,
                    "range_info_active": False,
                    "range_info_covered_by_date": None,
                    "range_info_covering_range_type": None,
                    "range_info_detected_at": None,
                }
            )
            if len(assignment_rows) >= 5_000:
                session.execute(insert(DutyAssignment), assignment_rows)
                session.commit()
                assignment_rows.clear()
        if assignment_rows:
            session.execute(insert(DutyAssignment), assignment_rows)
            session.commit()

    return {
        "synthetic_soldier_count": len(synthetic_soldier_ids),
        "team_count": len(team_ids),
    }


def _dataset_stats(session: Session) -> DatasetStats:
    return DatasetStats(
        soldiers=session.execute(select(func.count(Soldier.id))).scalar_one(),
        assignments=session.execute(select(func.count(DutyAssignment.id))).scalar_one(),
        hierarchy_nodes=session.execute(select(func.count(HierarchyNode.id))).scalar_one(),
        soldier_score_projection_rows=session.execute(
            select(func.count(SoldierScoreProjection.soldier_id))
        ).scalar_one(),
        soldier_quarter_score_projection_rows=session.execute(
            select(func.count()).select_from(SoldierQuarterScoreProjection)
        ).scalar_one(),
        quarter_total_rows=session.execute(
            select(func.count(ScoreProjectionQuarterTotal.quarter_start))
        ).scalar_one(),
    )


@contextlib.contextmanager
def _forbid_normal_history_expansion() -> Iterator[None]:
    original_effective_rows = score_projection._effective_duty_day_rows
    original_project_all_buckets = score_projection.project_all_buckets

    def fail_unbounded_projection_expansion(*args, **kwargs):
        if "assignment_ids" in kwargs:
            return original_effective_rows(*args, **kwargs)
        raise AssertionError("normal projected scoring read expanded duty history")

    def fail_project_all_buckets(*_args, **_kwargs):
        raise AssertionError("normal projected scoring read enumerated canonical buckets")

    score_projection._effective_duty_day_rows = fail_unbounded_projection_expansion
    score_projection.project_all_buckets = fail_project_all_buckets
    try:
        yield
    finally:
        score_projection._effective_duty_day_rows = original_effective_rows
        score_projection.project_all_buckets = original_project_all_buckets


def _all_hierarchy_ids(session: Session) -> list[uuid.UUID]:
    return session.execute(select(HierarchyNode.id)).scalars().all()


def _root_admin(session: Session) -> Soldier:
    admin = session.execute(select(Soldier).where(Soldier.personal_number == "1000001")).scalar_one_or_none()
    if admin is None:
        raise RuntimeError("Seeded admin 1000001 not found")
    return admin


def _benchmark_reads(
    session: Session,
    engine: Engine,
    *,
    subtree_ids: list[uuid.UUID],
    viewer: Soldier,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    with _forbid_normal_history_expansion():
        _, transparency = _measure(engine, lambda: scoring.transparency_rows(session, viewer=viewer))
        _, fairness = _measure(engine, lambda: scoring.fairness_components(session, viewer=viewer))
        _, dashboard = _measure(
            engine, lambda: commander_dashboard.summary_cards(session, subtree_ids=subtree_ids)
        )
    results["transparency"] = asdict(transparency)
    results["fairness"] = asdict(fairness)
    results["dashboard_summary"] = asdict(dashboard)
    return results


def _benchmark_mutation_refresh(session: Session, engine: Engine) -> dict[str, Any]:
    soldier_id = session.execute(
        select(Soldier.id)
        .where(Soldier.personal_number.like("perf-%"))
        .order_by(Soldier.personal_number)
        .limit(1)
    ).scalar_one()
    duty_type_id = session.execute(select(DutyType.id).where(DutyType.active.is_(True)).order_by(DutyType.name).limit(1)).scalar_one()
    duty_location_id = session.execute(select(DutyLocation.id).order_by(DutyLocation.name).limit(1)).scalar_one()
    probe_assignment = DutyAssignment(
        soldier_id=soldier_id,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        start_date=date.today() + timedelta(days=30),
        end_date=date.today() + timedelta(days=31),
        status="published",
        start_time="08:00",
        end_time="17:00",
    )
    session.add(probe_assignment)
    session.flush()
    _, measurement = _measure(
        engine,
        lambda: score_projection.refresh_projection_for_assignment_change(
            session, assignment=probe_assignment
        ),
    )
    session.commit()
    return asdict(measurement)


def _run_backfill(session: Session, engine: Engine, *, batch_size: int) -> dict[str, Any]:
    resume_probe: dict[str, Any] | None = None

    def backfill_all() -> ScoreProjectionState:
        nonlocal resume_probe
        while True:
            state = score_projection.backfill_score_projection(session, batch_size=batch_size)
            session.commit()
            if resume_probe is None and not state.backfill_complete:
                resume_probe = {
                    "resume_after_soldier_id": str(state.resume_after_soldier_id),
                    "resume_after_quarter_start": (
                        state.resume_after_quarter_start.isoformat()
                        if state.resume_after_quarter_start is not None
                        else None
                    ),
                }
            if state.backfill_complete:
                return state

    state, measurement = _measure(engine, backfill_all)
    return {
        "measurement": asdict(measurement),
        "state": {
            "canonical_version": state.canonical_version,
            "backfill_complete": state.backfill_complete,
            "completed_at": state.completed_at.isoformat() if state.completed_at else None,
            "resume_after_soldier_id": (
                str(state.resume_after_soldier_id) if state.resume_after_soldier_id else None
            ),
            "resume_after_quarter_start": (
                state.resume_after_quarter_start.isoformat()
                if state.resume_after_quarter_start is not None
                else None
            ),
        },
        "resume_probe_after_first_partial_batch": resume_probe,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Justice score projections on justice_perf")
    parser.add_argument("--source-database-url", default=DEFAULT_SOURCE_DB_URL)
    parser.add_argument("--source-db-admin-url", default=DEFAULT_SOURCE_DB_ADMIN_URL)
    parser.add_argument("--database-name", default="justice_perf")
    parser.add_argument("--soldier-count", type=int, default=10_000)
    parser.add_argument("--assignment-count", type=int, default=500_000)
    parser.add_argument("--team-count", type=int, default=200)
    parser.add_argument("--backfill-batch-size", type=int, default=10_000)
    parser.add_argument("--skip-prepare", action="store_true")
    parser.add_argument("--skip-seed", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    backend_dir = BACKEND_DIR
    perf_db_url = _url_with_database(args.source_database_url, args.database_name)
    perf_admin_url = _url_with_database(args.source_db_admin_url, args.database_name)

    if not args.skip_prepare:
        _log(f"Preparing disposable database {args.database_name}")
        _prepare_database(perf_admin_url, args.database_name)
        _log("Running migrations")
        migrate_stdout = _migrate_database(backend_dir, perf_db_url, perf_admin_url)
    else:
        migrate_stdout = ""

    if not args.skip_seed:
        _log("Seeding base fixtures")
        seed_stdout = _seed_database(backend_dir, perf_db_url, perf_admin_url)
    else:
        seed_stdout = ""

    engine = create_engine(perf_db_url, future=True, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    with SessionLocal() as session:
        shape = _ensure_perf_shape(
            session,
            target_soldier_count=args.soldier_count,
            target_assignment_count=args.assignment_count,
            team_count=args.team_count,
        )
        dataset_before = asdict(_dataset_stats(session))
        backfill = _run_backfill(session, engine, batch_size=args.backfill_batch_size)
        set_setting(
            session,
            score_projection.SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
            True,
            actor_id=None,
        )
        session.commit()
        viewer = _root_admin(session)
        subtree_ids = _all_hierarchy_ids(session)
        reads = _benchmark_reads(session, engine, subtree_ids=subtree_ids, viewer=viewer)
        mutation_refresh = _benchmark_mutation_refresh(session, engine)
        dataset_after = asdict(_dataset_stats(session))

    engine.dispose()

    result = {
        "database_name": args.database_name,
        "database_url": perf_db_url,
        "migrate_stdout": migrate_stdout,
        "seed_stdout": seed_stdout,
        "requested_shape": {
            "soldiers": args.soldier_count,
            "assignments": args.assignment_count,
            "teams": args.team_count,
        },
        "generated_shape": shape,
        "dataset_before_reads": dataset_before,
        "dataset_after_mutation": dataset_after,
        "backfill": backfill,
        "reads": reads,
        "mutation_refresh": mutation_refresh,
    }
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
