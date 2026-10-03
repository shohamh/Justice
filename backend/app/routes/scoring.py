from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, HierarchyNode, Soldier
from app.db.session import get_session
from app.services import scoring as svc
from app.services.authority import can_view_soldier_scope, has_any_visibility
from app.settings import get_settings

router = APIRouter(prefix="/scoring", tags=["scoring"])


class ExemptionSummaryItem(BaseModel):
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool
    start_date: date
    end_date: date | None


class TransparencyRow(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    node_id: uuid.UUID | None
    node_name: str | None
    enrolled_at: date
    active_days: int
    shift_count: int
    rank: str | None
    is_officer: bool | None
    service_type: str | None
    cumulative_score: Decimal
    score_per_day: Decimal
    normalised_score: Decimal
    is_globally_exempted: bool = False
    burden_share: float = 0.0
    c_over_d: float = 0.0
    burden_share_offset_raw: int = 0
    exemptions_display: str = ""
    exemptions_visible: bool = False
    exemptions: list[ExemptionSummaryItem] = []
    has_global_exemption: bool | None = None
    has_partial_exemption: bool | None = None
    has_temporary_exemption: bool | None = None


class TransparencyOut(BaseModel):
    rows: list[TransparencyRow]
    can_see_exemption_aggregates: bool


class TransparencyPageItem(TransparencyRow):
    row_num: int


class TransparencyPageSummary(BaseModel):
    row_count: int
    average_cumulative: float
    average_active_days: int
    average_score_per_day: float
    average_normalised: float
    burden_share_mean: float | None
    burden_share_stddev: float | None
    burden_share_cv: float | None
    burden_share_min: float | None
    burden_share_max: float | None
    burden_share_offset_min: int | None
    burden_share_offset_max: int | None


class TransparencyPageOut(BaseModel):
    items: list[TransparencyPageItem]
    next_cursor: str | None
    has_more: bool
    summary: TransparencyPageSummary
    can_see_exemption_aggregates: bool


class PerTypeRow(BaseModel):
    duty_type_id: uuid.UUID
    duty_type_name: str | None
    days: int
    days_past: int
    days_future: int
    score: Decimal


class AdjustmentRow(BaseModel):
    id: uuid.UUID
    delta: Decimal
    reason: str
    created_at: datetime


class BreakdownOut(BaseModel):
    per_type: list[PerTypeRow]
    adjustments: list[AdjustmentRow]


class BurdenShareContributionOut(BaseModel):
    kind: str                 # "duty" | "adjustment"
    label: str
    detail: str = ""
    score: Decimal
    start_date: date | None = None   # inclusive, duty spans only
    end_date: date | None = None     # inclusive, duty spans only
    days: int = 0
    multiplier: Decimal = Decimal("1")


class BurdenShareQuarterRow(BaseModel):
    quarter_start: date
    quarter_end: date
    quarter_label: str
    soldier_score: Decimal
    unit_score: Decimal
    active_frac: Decimal
    share: Decimal
    weighted_share: Decimal
    is_partial: bool
    adjustment_delta: Decimal = Decimal("0")
    contributions: list[BurdenShareContributionOut] = []


class BurdenShareBreakdownOut(BaseModel):
    quarters: list[BurdenShareQuarterRow]
    burden_share: Decimal
    A_i: Decimal   # Σ(s_q × active_frac_q) — personal weighted score
    W_i: Decimal   # Σ(U_q × active_frac_q) — unit weighted score


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


@router.get("/transparency", response_model=TransparencyOut)
def transparency(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransparencyOut:
    if not has_any_visibility(session, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="transparency_hidden")
    result = svc.transparency_rows(session, viewer=user)
    return TransparencyOut(
        rows=[TransparencyRow(**row) for row in result["rows"]],
        can_see_exemption_aggregates=result["can_see_exemption_aggregates"],
    )


def _transparency_source_generation(session: Session) -> int:
    """Read the non-transactional generation for canonical transparency inputs."""
    return int(
        session.execute(
            text(
                "SELECT CASE WHEN is_called THEN last_value ELSE 0 END "
                "FROM transparency_source_generation_seq"
            )
        ).scalar_one()
    )


def _transparency_source_snapshot(session: Session) -> str:
    """Capture the database visibility snapshot after reading the source sequence."""
    return session.execute(text("SELECT pg_current_snapshot()::text")).scalar_one()


def _transparency_source_changed_since_snapshot(session: Session, snapshot: str) -> bool:
    """Find source transactions that committed after the cursor snapshot.

    Sequence values advance before their source transactions commit, so the
    journal must also catch transactions that were not yet assigned an xid in
    the captured snapshot. Committed journal rows invisible to that snapshot
    indicate a canonical write after the page's source view.
    """
    return bool(
        session.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM transparency_source_change_journal AS source_changes
                    WHERE source_changes.transaction_id >= pg_snapshot_xmin(
                        CAST(:snapshot AS pg_snapshot)
                    )
                      AND NOT pg_visible_in_snapshot(
                          source_changes.transaction_id,
                          CAST(:snapshot AS pg_snapshot)
                      )
                )
                """
            ),
            {"snapshot": snapshot},
        ).scalar_one()
    )


def _transparency_page_revision(
    rows: list[dict], *, source_generation: int, as_of: date
) -> str:
    """Fingerprint row values plus the generation of all canonical inputs."""
    content = json.dumps(
        {
            "rows": rows,
            "source_generation": source_generation,
            "as_of": as_of.isoformat(),
        },
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _number_transparency_rows_in_place(rows: list[dict]) -> list[dict]:
    """Add display row numbers without copying every projected row dictionary."""
    for index, row in enumerate(rows, start=1):
        row["row_num"] = index
    return rows


def _transparency_page_binding(
    *,
    session: Session,
    user: Soldier,
    node_id: uuid.UUID | None,
    officer_filter: str,
    service_type: str | None,
    group_keys: list[str],
    rank_filter: str | None,
    search: str,
    sort: str,
    descending: bool,
    page_size: int,
    rank_order: list[str],
) -> str:
    roots = sorted(str(value) for value in scope_root_ids(session, user))
    value = {
        "user": str(user.id),
        "role": str(user.role),
        "scope_roots": roots,
        "node_id": str(node_id) if node_id else None,
        "officer_filter": officer_filter,
        "service_type": service_type,
        "group_keys": sorted(set(group_keys)),
        "rank_filter": rank_filter,
        "search": search.casefold(),
        "sort": sort,
        "descending": descending,
        "page_size": page_size,
        "rank_order": rank_order,
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _transparency_page_cursor(
    *, binding: str, revision: str, offset: int, source_snapshot: str
) -> str:
    settings = get_settings()
    return jwt.encode(
        {
            "purpose": "transparency-page-v1",
            "binding": binding,
            "revision": revision,
            "offset": offset,
            "source_snapshot": source_snapshot,
            "exp": int((datetime.now(UTC) + timedelta(minutes=20)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


@router.get("/transparency/page", response_model=TransparencyPageOut)
def transparency_page(
    cursor: str | None = None,
    search: str = Query("", max_length=200),
    sort: str = Query("burden_share", max_length=40),
    descending: bool = True,
    page_size: int = Query(100, ge=1, le=100),
    node_id: uuid.UUID | None = None,
    officer_filter: str = Query("all", pattern="^(all|officer|enlisted)$"),
    service_type: str | None = Query(None, max_length=40),
    group_key: list[str] = Query(default=[]),
    rank_filter: str | None = Query(None, max_length=40),
    rank_order: list[str] = Query(default=[]),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransparencyPageOut:
    """Bound the response and DOM while preserving the global scoring projection.

    The score projection still materializes all caller-visible rows to retain its
    global normalization and burden-share ordering semantics. The legacy route
    remains the complete export and sub-unit contract.
    """
    if not has_any_visibility(session, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="transparency_hidden")

    source_generation = _transparency_source_generation(session)
    source_snapshot = _transparency_source_snapshot(session)
    result = svc.transparency_rows(session, viewer=user)
    source_rows: list[dict] = result["rows"]
    revision_as_of = date.today()
    revision = _transparency_page_revision(
        source_rows, source_generation=source_generation, as_of=revision_as_of
    )
    if officer_filter not in {"all", "officer", "enlisted"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_officer_filter")

    binding = _transparency_page_binding(
        session=session,
        user=user,
        node_id=node_id,
        officer_filter=officer_filter,
        service_type=service_type,
        group_keys=group_key,
        rank_filter=rank_filter,
        search=search,
        sort=sort,
        descending=descending,
        page_size=page_size,
        rank_order=rank_order,
    )
    offset = 0
    if cursor:
        try:
            payload = jwt.decode(
                cursor,
                get_settings().jwt_secret,
                algorithms=[get_settings().jwt_algorithm],
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_cursor") from exc
        if payload.get("purpose") != "transparency-page-v1" or payload.get("binding") != binding:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_cursor")
        cursor_snapshot = payload.get("source_snapshot")
        snapshot_is_valid = isinstance(cursor_snapshot, str) and session.execute(
            text("SELECT pg_input_is_valid(:snapshot, 'pg_snapshot')"),
            {"snapshot": cursor_snapshot},
        ).scalar_one()
        if not snapshot_is_valid:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stale_cursor")
        source_snapshot = cursor_snapshot
        if payload.get("revision") != revision:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stale_cursor")
        try:
            offset = int(payload["offset"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_cursor") from exc
        if offset < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_cursor")

    node_ids: set[uuid.UUID] | None = None
    if node_id:
        node_ids = {
            node.id
            for node in session.execute(select(HierarchyNode)).scalars().all()
            if node_id in (node.path_ids or [])
        }
        node_ids.add(node_id)

    group_soldier_ids: set[uuid.UUID] | None = None
    fairness_by_id: dict[uuid.UUID, tuple[int, float | None]] = {}
    if group_key or sort in {"group_rank", "group_dev"}:
        fairness = svc.fairness_components(session, viewer=user, node_id=node_id)
        group_soldier_ids = set() if group_key else None
        for index, component in enumerate(fairness.get("components", [])):
            members = sorted(component.get("soldiers", []), key=lambda item: float(item.get("burden_share") or 0))
            mean_value = component.get("burden_share")
            group_mean = float(mean_value["mean"]) if isinstance(mean_value, dict) and mean_value.get("mean") is not None else None
            for rank_index, item in enumerate(members, start=1):
                soldier_id = uuid.UUID(str(item["soldier_id"]))
                fairness_by_id[soldier_id] = (rank_index, group_mean)
        for item in fairness.get("exempt_from_all", {}).get("soldiers", []):
            fairness_by_id[uuid.UUID(str(item["soldier_id"]))] = (0, None)
        if group_key:
            assert group_soldier_ids is not None
            for key in set(group_key):
                if key == "exempt":
                    group_soldier_ids.update(
                        uuid.UUID(str(item["soldier_id"]))
                        for item in fairness.get("exempt_from_all", {}).get("soldiers", [])
                    )
                elif key.startswith("comp_"):
                    try:
                        index = int(key[5:])
                        component = fairness.get("components", [])[index]
                    except (ValueError, IndexError):
                        continue
                    group_soldier_ids.update(
                        uuid.UUID(str(item["soldier_id"])) for item in component.get("soldiers", [])
                    )

    filtered_rows = []
    for row in source_rows:
        if node_ids is not None and row.get("node_id") not in node_ids:
            continue
        if officer_filter == "officer" and not row.get("is_officer"):
            continue
        if officer_filter == "enlisted" and row.get("is_officer"):
            continue
        if service_type is not None and row.get("service_type") != service_type:
            continue
        if group_soldier_ids is not None and row.get("soldier_id") not in group_soldier_ids:
            continue
        filtered_rows.append(row)

    burden_shares = [float(row.get("burden_share") or 0) for row in filtered_rows]
    mean = sum(burden_shares) / len(burden_shares) if burden_shares else 0.0
    stddev = (
        math.sqrt(sum((value - mean) ** 2 for value in burden_shares) / len(burden_shares))
        if len(burden_shares) >= 2
        else None
    )
    summary = TransparencyPageSummary(
        row_count=len(filtered_rows),
        average_cumulative=(
            sum(float(row.get("cumulative_score") or 0) for row in filtered_rows) / len(filtered_rows)
            if filtered_rows
            else 0.0
        ),
        average_active_days=(
            math.floor(sum(int(row.get("active_days") or 0) for row in filtered_rows) / len(filtered_rows) + 0.5)
            if filtered_rows
            else 0
        ),
        average_score_per_day=(
            sum(float(row.get("score_per_day") or 0) for row in filtered_rows) / len(filtered_rows)
            if filtered_rows
            else 0.0
        ),
        average_normalised=(
            sum(float(row.get("normalised_score") or 0) for row in filtered_rows) / len(filtered_rows)
            if filtered_rows
            else 0.0
        ),
        burden_share_mean=mean if len(burden_shares) >= 2 else None,
        burden_share_stddev=stddev,
        burden_share_cv=(stddev / mean if stddev is not None and mean else 0.0)
        if stddev is not None
        else None,
        burden_share_min=min(burden_shares) if len(burden_shares) >= 2 else None,
        burden_share_max=max(burden_shares) if len(burden_shares) >= 2 else None,
        burden_share_offset_min=min(
            (int(row.get("burden_share_offset_raw") or 0) for row in source_rows), default=None
        ),
        burden_share_offset_max=max(
            (int(row.get("burden_share_offset_raw") or 0) for row in source_rows), default=None
        ),
    )

    numbered_rows = _number_transparency_rows_in_place(filtered_rows)
    if rank_filter is not None:
        numbered_rows = [row for row in numbered_rows if row.get("rank") == rank_filter]
    query_text = search.casefold().strip()
    if query_text:
        numbered_rows = [
            row
            for row in numbered_rows
            if any(
                query_text in str(row.get(field) or "").casefold()
                for field in ("full_name", "node_name", "exemptions_display", "rank")
            )
        ]

    allowed_sort_fields = {
        "num": "row_num",
        "name": "full_name",
        "full_name": "full_name",
        "unit": "node_name",
        "exemptions": "exemptions_display",
        "enrolled_at": "enrolled_at",
        "active_days": "active_days",
        "rank": "rank",
        "shift_count": "shift_count",
        "cumulative": "cumulative_score",
        "cumulative_score": "cumulative_score",
        "score_per_day": "score_per_day",
        "normalised": "normalised_score",
        "burden_share": "burden_share",
        "burden_share_offset_raw": "burden_share_offset_raw",
        "c_over_d": "c_over_d",
        "group_rank": "group_rank",
        "group_dev": "group_dev",
        "count_offset": "burden_share_offset_raw",
    }
    if sort not in allowed_sort_fields:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_sort")
    field = allowed_sort_fields[sort]

    def sort_value(row: dict) -> Any:
        if sort in {"group_rank", "group_dev"}:
            group_rank, group_mean = fairness_by_id.get(uuid.UUID(str(row["soldier_id"])), (999, None))
            return group_rank if sort == "group_rank" else (
                float(row.get("burden_share") or 0) - group_mean if group_mean is not None else 9999.0
            )
        value = row.get(field)
        if field in {"active_days", "shift_count", "row_num", "burden_share_offset_raw"}:
            return int(value or 0)
        if field in {"cumulative_score", "score_per_day", "normalised_score", "burden_share", "c_over_d"}:
            return Decimal(str(value or 0))
        if sort == "rank":
            order = {value: index for index, value in enumerate(rank_order)}
            return order.get(str(value or ""), len(order) + 1)
        return str(value or "").casefold()

    # Stable secondary key is always the soldier UUID, regardless of direction.
    numbered_rows.sort(key=lambda row: str(row["soldier_id"]))
    numbered_rows.sort(key=sort_value, reverse=descending)
    page_rows = numbered_rows[offset : offset + page_size]
    has_more = offset + page_size < len(numbered_rows)
    next_cursor = (
        _transparency_page_cursor(
            binding=binding,
            revision=revision,
            offset=offset + page_size,
            source_snapshot=source_snapshot,
        )
        if has_more
        else None
    )
    if (
        _transparency_source_generation(session) != source_generation
        or _transparency_source_changed_since_snapshot(session, source_snapshot)
        or date.today() != revision_as_of
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="stale_cursor" if cursor else "data_changed",
        )
    return TransparencyPageOut(
        items=[TransparencyPageItem(**row) for row in page_rows],
        next_cursor=next_cursor,
        has_more=has_more,
        summary=summary,
        can_see_exemption_aggregates=result["can_see_exemption_aggregates"],
    )


@router.get("/fairness-components")
def fairness_components(
    node_id: uuid.UUID | None = Query(None, description="Scope to this node's subtree"),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    """Burden-share spread (פיזור) split per connected component of soldiers who share
    duty-type eligibility, plus the count of soldiers exempt from every duty."""
    if not has_any_visibility(session, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="transparency_hidden")
    return svc.fairness_components(session, viewer=user, node_id=node_id)


@router.get("/eligibility-groups")
def eligibility_groups(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[dict]:
    """Lightweight view of fairness_components() for scoping auto-assign selection —
    same connected components, without the per-soldier detail."""
    full = svc.fairness_components(session)
    return [
        {
            "duty_type_ids": c["duty_type_ids"],
            "duty_type_names": c["duty_type_names"],
            "soldier_count": c["soldier_count"],
        }
        for c in full["components"]
    ]


@router.get("/soldiers/{soldier_id}/burden-share-breakdown", response_model=BurdenShareBreakdownOut)
def burden_share_breakdown(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> BurdenShareBreakdownOut:
    from app.services.effort_score import compute_burden_share_breakdown

    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if s.id != user.id:
        if not can_view_soldier_scope(session, user, _node_of(session, s)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    today = date.today()

    latest_published_end = session.execute(
        select(func.max(DutyAssignment.end_date)).where(DutyAssignment.status == "published")
    ).scalar()
    if latest_published_end is not None and latest_published_end >= today:
        planning_start = latest_published_end + timedelta(days=1)
    else:
        planning_start = today

    bd = compute_burden_share_breakdown(
        session,
        soldier=s,
        planning_start=planning_start,
        planning_end=planning_start,
    )
    return BurdenShareBreakdownOut(
        quarters=[
            BurdenShareQuarterRow(
                quarter_start=q.quarter_start,
                quarter_end=q.quarter_end,
                quarter_label=q.quarter_label,
                soldier_score=q.soldier_score,
                unit_score=q.unit_score,
                active_frac=q.active_frac,
                share=q.share,
                weighted_share=q.weighted_share,
                is_partial=q.is_partial,
                adjustment_delta=q.adjustment_delta,
                contributions=[
                    BurdenShareContributionOut(
                        kind=c.kind,
                        label=c.label,
                        detail=c.detail,
                        score=c.score,
                        start_date=c.start_date,
                        end_date=c.end_date,
                        days=c.days,
                        multiplier=c.multiplier,
                    )
                    for c in q.contributions
                ],
            )
            for q in bd.quarters
        ],
        burden_share=bd.burden_share,
        A_i=bd.A_i,
        W_i=bd.W_i,
    )


class BurdenShareOut(BaseModel):
    has_group: bool
    burden_share: Decimal | None = None
    rank: int | None = None
    group_size: int | None = None
    duty_type_names: list[str] = []
    peer_scores: list[Decimal] = []
    mean: Decimal | None = None
    stddev: Decimal | None = None
    cv: Decimal | None = None
    low_sample: bool = False


@router.get("/soldiers/{soldier_id}/burden-share", response_model=BurdenShareOut)
def burden_share(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> BurdenShareOut:
    """A soldier's own rank + anonymized peer distribution within their duty-type
    eligibility group. Never exposes other soldiers' names or ids — see
    scoring.soldier_burden_share / _soldier_burden_share."""
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if s.id != user.id:
        if not can_view_soldier_scope(session, user, _node_of(session, s)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    result = svc.soldier_burden_share(session, soldier_id)
    if result is None:
        return BurdenShareOut(has_group=False)
    return BurdenShareOut(has_group=True, **result)


@router.get("/soldiers/{soldier_id}", response_model=BreakdownOut)
def breakdown(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> BreakdownOut:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    data = svc.soldier_score_breakdown(session, soldier_id=soldier_id)
    return BreakdownOut(
        per_type=[PerTypeRow(**pt) for pt in data["per_type"]],
        adjustments=[
            AdjustmentRow(id=a.id, delta=a.delta, reason=a.reason, created_at=a.created_at)
            for a in data["adjustments"]
        ],
    )
