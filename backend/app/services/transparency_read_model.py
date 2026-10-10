"""Build and query the versioned relational transparency read model."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Soldier
from app.services import scoring
from app.services.authority import SoldierScopeVisibility

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500
_SOURCE_GENERATION_SQL = text(
    "SELECT CASE WHEN is_called THEN last_value ELSE 0 END "
    "FROM transparency_source_generation_seq"
)
_SOURCE_CHANGED_SQL = text("""
    SELECT EXISTS (
        SELECT 1 FROM transparency_source_change_journal AS source_changes
        WHERE source_changes.transaction_id >= pg_snapshot_xmin(CAST(:snapshot AS pg_snapshot))
          AND NOT pg_visible_in_snapshot(
              source_changes.transaction_id, CAST(:snapshot AS pg_snapshot)
          )
    )
""")
_INSERT_ROW_SQL = text("""
    INSERT INTO transparency_read_model_rows
      (generation_id, soldier_id, burden_share, cumulative_score, score_per_day,
       normalised_score, c_over_d, active_days, shift_count, burden_share_offset_raw,
       full_name, node_id, node_name, enrolled_at, rank, is_officer, service_type,
       is_globally_exempted)
    VALUES
      (:generation_id, :soldier_id, :burden_share, :cumulative_score, :score_per_day,
       :normalised_score, :c_over_d, :active_days, :shift_count,
       :burden_share_offset_raw, :full_name, :node_id, :node_name, :enrolled_at,
       :rank, :is_officer, :service_type, :is_globally_exempted)
""")


def _source_generation(session: Session) -> int:
    return int(session.execute(_SOURCE_GENERATION_SQL).scalar_one())


def capture_source_state(session: Session) -> tuple[int, str]:
    """Capture the sequence before the database's visibility snapshot."""
    generation = _source_generation(session)
    snapshot = session.execute(text("SELECT pg_current_snapshot()::text")).scalar_one()
    return generation, snapshot


def source_changed_since_snapshot(session: Session, snapshot: str) -> bool:
    return bool(session.execute(_SOURCE_CHANGED_SQL, {"snapshot": snapshot}).scalar_one())


def current_generation(
    session: Session, *, source_generation: int, as_of: date,
) -> dict | None:
    row = session.execute(text("""
        SELECT id, source_generation, source_snapshot, as_of,
               normalization_denominator, ready, created_at, published_at
        FROM transparency_read_model_generations
        WHERE ready AND source_generation = :source_generation AND as_of = :as_of
        ORDER BY published_at DESC NULLS LAST, created_at DESC, id DESC
        LIMIT 1
    """), {"source_generation": source_generation, "as_of": as_of}).mappings().one_or_none()
    if row is None or source_changed_since_snapshot(session, row["source_snapshot"]):
        return None
    return dict(row)


def rebuild_generation(session: Session) -> dict | None:
    """Publish a complete, source-fenced generation in one transaction."""
    # A caller may have read data already. Start at a fresh READ COMMITTED view.
    session.commit()
    source_generation, source_snapshot = capture_source_state(session)
    as_of = date.today()
    generation_id = uuid.uuid4()
    try:
        # transparency_rows returns this exact projected result when available.
        # A read model must not publish its legacy fallback as projection-ready.
        projected = scoring._try_projected_transparency_rows(session, viewer=None)
        if projected is None:
            session.rollback()
            return None
        rows = projected["rows"]
        denominator = (
            sum((Decimal(str(row["score_per_day"])) for row in rows), Decimal(0))
            / Decimal(len(rows)) if rows else Decimal(0)
        )
        session.execute(text("""
            INSERT INTO transparency_read_model_generations
              (id, source_generation, source_snapshot, as_of, normalization_denominator, ready)
            VALUES (:id, :source_generation, :source_snapshot, :as_of, :denominator, false)
        """), {"id": generation_id, "source_generation": source_generation,
               "source_snapshot": source_snapshot, "as_of": as_of,
               "denominator": denominator})
        for start in range(0, len(rows), _BATCH_SIZE):
            batch = rows[start:start + _BATCH_SIZE]
            session.execute(_INSERT_ROW_SQL, [
                {
                    "generation_id": generation_id,
                    "soldier_id": row["soldier_id"],
                    "burden_share": Decimal(str(row["burden_share"])),
                    "cumulative_score": Decimal(str(row["cumulative_score"])),
                    "score_per_day": Decimal(str(row["score_per_day"])),
                    "normalised_score": Decimal(str(row["normalised_score"])),
                    "c_over_d": Decimal(str(row["c_over_d"])),
                    "active_days": row["active_days"],
                    "shift_count": row["shift_count"],
                    "burden_share_offset_raw": row["burden_share_offset_raw"],
                    "full_name": row["full_name"],
                    "node_id": row["node_id"],
                    "node_name": row["node_name"],
                    "enrolled_at": row["enrolled_at"],
                    "rank": row["rank"],
                    "is_officer": row["is_officer"],
                    "service_type": row["service_type"],
                    "is_globally_exempted": row["is_globally_exempted"],
                }
                for row in batch
            ])
        ending_generation = _source_generation(session)
        source_changed = source_changed_since_snapshot(session, source_snapshot)
        if ending_generation != source_generation or source_changed or date.today() != as_of:
            logger.warning(
                "transparency read model source changed during build",
                extra={"generation_id": str(generation_id), "source_generation": source_generation,
                       "ending_generation": ending_generation, "journal_changed": source_changed},
            )
            session.rollback()
            return None
        session.execute(text("""
            UPDATE transparency_read_model_generations
            SET ready = true, published_at = now() WHERE id = :id
        """), {"id": generation_id})
        session.execute(text("""
            DELETE FROM transparency_read_model_generations
            WHERE ready AND id NOT IN (
                SELECT id FROM transparency_read_model_generations
                WHERE ready ORDER BY published_at DESC NULLS LAST, id DESC LIMIT 2
            )
        """))
        session.commit()
        return current_generation(session, source_generation=source_generation, as_of=as_of)
    except Exception:
        session.rollback()
        logger.exception("transparency read model build failed", extra={"generation_id": str(generation_id)})
        raise


def _visibility_sql(visibility: SoldierScopeVisibility) -> tuple[str, dict]:
    ancestors = [*visibility.commander_ancestor_ids, *visibility.dm_ancestor_ids]
    unrestricted = (
        visibility.is_admin or visibility.sees_every_soldier
        or (
            visibility.threshold_rank is not None
            and visibility.best_rank is not None
            and visibility.best_rank <= visibility.threshold_rank
        )
    )
    if unrestricted:
        return "TRUE", {}
    return """(
        rows.soldier_id = :viewer_id OR EXISTS (
            SELECT 1 FROM hierarchy_nodes AS node
            WHERE node.id = rows.node_id
              AND node.path_ids && CAST(:ancestor_ids AS uuid[])
        )
    )""", {"ancestor_ids": ancestors}


def _authorized_sql(
    *, viewer: Soldier, visibility: SoldierScopeVisibility,
) -> tuple[str, dict]:
    predicate, params = _visibility_sql(visibility)
    return predicate, {**params, "viewer_id": viewer.id}


def read_page(
    session: Session, *, generation_id: uuid.UUID, viewer: Soldier,
    visibility: SoldierScopeVisibility,
    after_score: Decimal | None, after_soldier_id: uuid.UUID | None, limit: int,
) -> list[dict]:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    if (after_score is None) != (after_soldier_id is None):
        raise ValueError("cursor score and soldier ID must be supplied together")
    predicate, params = _authorized_sql(viewer=viewer, visibility=visibility)
    cursor_predicate = (
        "TRUE" if after_score is None else
        "(rows.burden_share < :after_score OR "
        "(rows.burden_share = :after_score AND rows.soldier_id > :after_soldier_id))"
    )
    query = text(f"""
        SELECT rows.*
        FROM transparency_read_model_rows AS rows
        WHERE rows.generation_id = :generation_id
          AND {predicate}
          AND {cursor_predicate}
        ORDER BY rows.burden_share DESC, rows.soldier_id ASC
        LIMIT :limit
    """)
    result = session.execute(query, {
        **params, "generation_id": generation_id, "after_score": after_score,
        "after_soldier_id": after_soldier_id, "limit": limit,
    }).mappings().all()
    return [dict(row) for row in result]


def read_summary(
    session: Session, *, generation_id: uuid.UUID, viewer: Soldier,
    visibility: SoldierScopeVisibility,
) -> dict:
    predicate, params = _authorized_sql(viewer=viewer, visibility=visibility)
    aggregates = session.execute(text(f"""
        SELECT count(*) AS row_count,
               coalesce(avg(rows.cumulative_score), 0) AS average_cumulative,
               coalesce(floor(avg(rows.active_days) + 0.5), 0) AS average_active_days,
               coalesce(avg(rows.score_per_day), 0) AS average_score_per_day,
               coalesce(avg(rows.normalised_score), 0) AS average_normalised,
               avg(rows.burden_share) AS burden_share_mean,
               stddev_pop(rows.burden_share) AS burden_share_stddev,
               min(rows.burden_share) AS burden_share_min,
               max(rows.burden_share) AS burden_share_max,
               min(rows.burden_share_offset_raw) AS burden_share_offset_min,
               max(rows.burden_share_offset_raw) AS burden_share_offset_max
        FROM transparency_read_model_rows AS rows
        WHERE rows.generation_id = :generation_id AND {predicate}
    """), {**params, "generation_id": generation_id}).mappings().one()
    count = aggregates["row_count"]
    mean = aggregates["burden_share_mean"]
    stddev = aggregates["burden_share_stddev"]
    return {
        "row_count": count,
        "average_cumulative": float(aggregates["average_cumulative"]),
        "average_active_days": int(aggregates["average_active_days"]),
        "average_score_per_day": float(aggregates["average_score_per_day"]),
        "average_normalised": float(aggregates["average_normalised"]),
        "burden_share_mean": float(mean) if count >= 2 else None,
        "burden_share_stddev": float(stddev) if count >= 2 else None,
        "burden_share_cv": float(stddev / mean) if count >= 2 and mean else (0.0 if count >= 2 else None),
        "burden_share_min": float(aggregates["burden_share_min"]) if count >= 2 else None,
        "burden_share_max": float(aggregates["burden_share_max"]) if count >= 2 else None,
        "burden_share_offset_min": aggregates["burden_share_offset_min"],
        "burden_share_offset_max": aggregates["burden_share_offset_max"],
    }
