"""Measure the legacy (non-projection) read path against a benchmark dataset.

Run from any checkout against a database prepared by
``score_projection_benchmark.py``. On branches before the projection feature,
this exercises the pure legacy computation; on this branch it reports what the
fallback path would cost. Mirrors the harness methodology: wall time, db time
and statement count per operation.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import DutyAssignment, DutyLocation, DutyType, HierarchyNode, Soldier


def measure(engine, fn):
    total = 0.0
    count = 0
    state = {"t": None}

    def before(conn, cursor, statement, parameters, context, executemany):
        state["t"] = time.perf_counter()

    def after(conn, cursor, statement, parameters, context, executemany):
        nonlocal total, count
        if state["t"] is not None:
            total += time.perf_counter() - state["t"]
        count += 1

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    start = time.perf_counter()
    try:
        result = fn()
        status = "ok"
        detail = ""
    except Exception as exc:
        result = None
        status = f"CRASH: {type(exc).__name__}"
        detail = str(exc)[:200]
        wall = time.perf_counter() - start
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
        return {"status": status, "detail": detail, "wall_seconds": round(wall, 2)}
    wall = time.perf_counter() - start
    event.remove(engine, "before_cursor_execute", before)
    event.remove(engine, "after_cursor_execute", after)
    return {
        "status": status,
        "wall_seconds": round(wall, 3),
        "db_seconds": round(total, 3),
        "query_count": count,
    }


def main() -> None:
    database_name = sys.argv[1] if len(sys.argv) > 1 else "justice_bench"
    engine = create_engine(
        f"postgresql+psycopg://app:app_pw@localhost:5432/{database_name}",
        future=True,
        pool_pre_ping=True,
    )
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    results: dict = {}
    with SessionLocal() as session:
        admin = session.execute(
            select(Soldier).where(Soldier.personal_number == "1000001")
        ).scalar_one_or_none()
        assert admin is not None, "admin soldier missing - run the branch harness first"
        subtree_ids = [nid for (nid,) in session.execute(select(HierarchyNode.id)).all()]

        from app.services import commander_dashboard, scoring

        results["transparency"] = measure(
            engine, lambda: scoring.transparency_rows(session, viewer=admin)
        )
        results["fairness"] = measure(
            engine, lambda: scoring.fairness_components(session, viewer=admin)
        )
        results["dashboard_summary"] = measure(
            engine, lambda: commander_dashboard.summary_cards(session, subtree_ids=subtree_ids)
        )

        # Raw write probe (no projection maintenance on pre-projection code).
        soldier_id = session.execute(
            select(Soldier.id).order_by(Soldier.personal_number).limit(1)
        ).scalar_one()
        duty_type_id = session.execute(select(DutyType.id).limit(1)).scalar_one()
        location_id = session.execute(select(DutyLocation.id).limit(1)).scalar_one()

        def insert_assignment():
            session.add(
                DutyAssignment(
                    soldier_id=soldier_id,
                    duty_type_id=duty_type_id,
                    duty_location_id=location_id,
                    start_date=date.today() + timedelta(days=60),
                    end_date=date.today() + timedelta(days=61),
                    status="published",
                )
            )
            session.flush()

        results["mutation_insert_only"] = measure(engine, insert_assignment)
        session.rollback()

    engine.dispose()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
