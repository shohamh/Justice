"""Phase timer for ``count_ineligible_soldiers`` against the scale database.

Run from ``backend`` with ``JUSTICE_SCALE_DATABASE_URL`` pointing at a seeded
scale database (the seed script's guard enforces a loopback host and a
``_scale``/``_perf`` database name)::

    python -m app.scripts.profile_ineligible_count [--repeat 5]

For admin scope (roots=None) and for a scoped group and team node it prints the
median milliseconds of each phase of the count, the end-to-end median of
``count_ineligible_soldiers`` itself, and a parity check that the count equals
``len(list_ineligible_soldiers(...))``. Read-only: every session runs inside a
``READ ONLY`` transaction that is rolled back.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from time import perf_counter
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, aliased, sessionmaker

from app.db.models import HierarchyNode, Soldier
from app.scripts.seed_scale_test import create_scale_engine
from app.services import ineligible_soldiers as svc
from app.services.range_eligibility_projection import project_duty_eligibility


@contextmanager
def _read_only_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        yield session
    finally:
        session.rollback()
        session.close()


def _phases(session: Session, roots: set[uuid.UUID] | None, as_of: date) -> dict[str, Any]:
    """Mirror ``count_ineligible_soldiers`` step by step, timing each phase."""
    timings: dict[str, float] = {}
    rows: dict[str, int] = {}

    def timed(name: str, call: Callable[[], Any]) -> Any:
        start = perf_counter()
        result = call()
        timings[name] = (perf_counter() - start) * 1000
        return result

    statement = select(Soldier).join(HierarchyNode, Soldier.hierarchy_node_id == HierarchyNode.id)
    scope_clause = svc._scope_clause(roots)
    if scope_clause is not None:
        statement = statement.where(scope_clause)
    soldiers = timed("1 load soldiers", lambda: session.execute(statement).scalars().all())
    rows["soldiers"] = len(soldiers)
    weapon_ids = timed(
        "2 structural eligibility",
        lambda: svc._weapon_eligible_soldier_ids(session, soldiers=soldiers, as_of=as_of),
    )
    eligible = [soldier for soldier in soldiers if soldier.id in weapon_ids]
    rows["weapon eligible"] = len(eligible)
    quals = timed(
        "3 qualifications",
        lambda: svc._valid_qualifications_by_soldier(session, soldiers=eligible, as_of=as_of),
    )
    qualified = {soldier.id for soldier in eligible if soldier.id in quals}
    rows["qualified"] = len(qualified)
    duties = timed(
        "4 future weapon duties",
        lambda: svc._upcoming_weapon_duties_by_soldier(
            session, soldier_ids=qualified, as_of=as_of
        ),
    )
    duty_ids = [duty.assignment_id for soldier_duties in duties.values() for duty in soldier_duties]
    rows["future duties"] = len(duty_ids)
    timed(
        "5 duty eligibility",
        lambda: project_duty_eligibility(
            session, soldier_ids=list(qualified), duty_ids=duty_ids, as_of=as_of
        ),
    )
    return {"timings": timings, "rows": rows}


def _scoped_roots(session: Session) -> dict[str, set[uuid.UUID] | None]:
    scopes: dict[str, set[uuid.UUID] | None] = {"admin (roots=None)": None}
    member_node = aliased(HierarchyNode)
    for level in ("branch", "group", "team"):
        # The node at this level with the most soldiers in its subtree.
        node = session.execute(
            select(HierarchyNode.id, HierarchyNode.name)
            .join(member_node, member_node.path_ids.any(HierarchyNode.id))
            .join(Soldier, Soldier.hierarchy_node_id == member_node.id)
            .where(HierarchyNode.level == level)
            .group_by(HierarchyNode.id, HierarchyNode.name)
            .order_by(func.count(Soldier.id).desc(), HierarchyNode.name)
            .limit(1)
        ).first()
        if node is not None:
            scopes[f"{level} {node.name}"] = {node.id}
    return scopes


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # node names are Hebrew

    engine = create_scale_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    as_of = date.today()
    with _read_only_session(factory) as session:
        scopes = _scoped_roots(session)

    for label, roots in scopes.items():
        samples: dict[str, list[float]] = {}
        totals: list[float] = []
        row_counts: dict[str, int] = {}
        for _ in range(args.repeat):
            with _read_only_session(factory) as session:
                result = _phases(session, roots, as_of)
            for name, value in result["timings"].items():
                samples.setdefault(name, []).append(value)
            row_counts = result["rows"]
            with _read_only_session(factory) as session:
                start = perf_counter()
                svc.count_ineligible_soldiers(session, roots=roots, as_of=as_of)
                totals.append((perf_counter() - start) * 1000)

        phase_sum = sum(statistics.median(values) for values in samples.values())
        print(f"\n== {label}: rows {row_counts}")
        for name, values in samples.items():
            median = statistics.median(values)
            print(f"  {name:<26} {median:9.1f} ms  {median / phase_sum:6.1%}")
        print(f"  {'sum of phase medians':<26} {phase_sum:9.1f} ms")
        print(f"  {'count_ineligible_soldiers':<26} {statistics.median(totals):9.1f} ms (median)")

        with _read_only_session(factory) as session:
            count = svc.count_ineligible_soldiers(session, roots=roots, as_of=as_of)
            listed = len(svc.list_ineligible_soldiers(session, roots=roots, as_of=as_of))
        print(f"  parity: count={count} list={listed} {'OK' if count == listed else 'MISMATCH'}")

    engine.dispose()


if __name__ == "__main__":
    main()
