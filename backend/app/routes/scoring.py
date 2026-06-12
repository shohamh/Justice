from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, HierarchyNode, Soldier
from app.db.session import get_session
from app.services import scoring as svc

router = APIRouter(prefix="/scoring", tags=["scoring"])


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
    effort_score: float = 0.0


class PerTypeRow(BaseModel):
    duty_type_id: uuid.UUID
    duty_type_name: str | None
    days: int
    score: Decimal


class AdjustmentRow(BaseModel):
    id: uuid.UUID
    delta: Decimal
    reason: str
    created_at: datetime


class BreakdownOut(BaseModel):
    per_type: list[PerTypeRow]
    adjustments: list[AdjustmentRow]


class EffortQuarterRow(BaseModel):
    quarter_start: date
    quarter_end: date
    quarter_label: str
    soldier_score: Decimal
    unit_score: Decimal
    active_frac: Decimal
    share: Decimal
    weighted_share: Decimal
    is_partial: bool = False


class EffortBreakdownOut(BaseModel):
    quarters: list[EffortQuarterRow]
    effort_score: Decimal
    A_i: Decimal   # Σ(share_q × active_frac_q)
    W_i: Decimal   # Σ(active_frac_q) — historical weight


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _xlsx_response(wb: openpyxl.Workbook, filename: str) -> StreamingResponse:
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/transparency", response_model=list[TransparencyRow])
def transparency(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[TransparencyRow]:
    return [TransparencyRow(**row) for row in svc.transparency_rows(session)]


def _dfs_order(nodes_by_parent: dict[uuid.UUID | None, list[HierarchyNode]], parent_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    for node in nodes_by_parent.get(parent_id, []):
        result.append(node.id)
        result.extend(_dfs_order(nodes_by_parent, node.id))
    return result


def _node_path(node_id: uuid.UUID | None, nodes_by_id: dict[uuid.UUID, HierarchyNode], sep: str = " / ") -> str:
    parts: list[str] = []
    nid = node_id
    while nid:
        node = nodes_by_id.get(nid)
        if not node:
            break
        parts.append(node.name)
        nid = node.parent_id
    return sep.join(reversed(parts))


@router.get("/transparency/export")
def transparency_export(
    node_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> StreamingResponse:
    rows = svc.transparency_rows(session)
    all_nodes = session.execute(select(HierarchyNode)).scalars().all()

    if node_id is not None:
        node_ids_in_db = {n.id for n in all_nodes}
        if node_id not in node_ids_in_db:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
        subtree_node_ids = {n.id for n in all_nodes if node_id in n.path_ids}
        rows = [r for r in rows if r["node_id"] in subtree_node_ids]

    # Build DFS-ordered node list
    nodes_by_parent: dict[uuid.UUID | None, list[HierarchyNode]] = {}
    for n in all_nodes:
        nodes_by_parent.setdefault(n.parent_id, []).append(n)
    # Sort children alphabetically for deterministic output
    for children in nodes_by_parent.values():
        children.sort(key=lambda n: n.name)

    ordered_node_ids = _dfs_order(nodes_by_parent)
    node_order = {nid: i for i, nid in enumerate(ordered_node_ids)}

    # Sort rows by node DFS order, then by soldier name within each node
    rows.sort(key=lambda r: (node_order.get(r["node_id"], 9999), r["full_name"]))

    # Build nodes_by_id for path lookup
    nodes_by_id: dict[uuid.UUID, HierarchyNode] = {n.id: n for n in all_nodes}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "חיילים"
    ws.append([
        "יחידה / תת-יחידה", "שם", "יחידה", "תאריך הצטרפות", "ימים פעילים", "דרגה",
        "כמות משמרות", "ניקוד מצטבר", "ניקוד ליום", "ניקוד מנורמל",
    ])
    for r in rows:
        ws.append([
            _node_path(r["node_id"], nodes_by_id),
            r["full_name"],
            r["node_name"],
            str(r["enrolled_at"]),
            r["active_days"],
            r["rank"],
            r["shift_count"],
            float(r["cumulative_score"]),
            float(r["score_per_day"]),
            float(r["normalised_score"]),
        ])

    return _xlsx_response(wb, "transparency.xlsx")


@router.get("/transparency/sub-units/export")
def transparency_sub_units_export(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> StreamingResponse:
    rows = svc.transparency_rows(session)
    all_nodes = session.execute(select(HierarchyNode)).scalars().all()

    # Map each node id to its path_ids for quick lookup
    node_path_map: dict[uuid.UUID, list[uuid.UUID]] = {n.id: n.path_ids for n in all_nodes}

    # Sort nodes: shallowest first, then alphabetically
    sorted_nodes = sorted(all_nodes, key=lambda n: (len(n.path_ids), n.name))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "תתי יחידות"
    ws.append([
        "יחידה", "כמות חיילים", "חיילים פעילים (%)",
        "ממוצע ימים פעילים", "ממוצע ניקוד לחייל",
        "ממוצע ניקוד לחייל פעיל", "ניקוד ליום (מסגרת)", "ניקוד מנורמל ממוצע",
    ])

    for node in sorted_nodes:
        node_rows = [
            r for r in rows
            if r["node_id"] is not None and node.id in node_path_map.get(r["node_id"], [])
        ]
        if not node_rows:
            continue

        count = len(node_rows)
        active_rows = [r for r in node_rows if not r.get("is_globally_exempted")]
        active_count = len(active_rows)
        active_pct = round(active_count / count * 100)
        avg_cumulative = float(sum(r["cumulative_score"] for r in node_rows) / count)
        avg_cumulative_active = (
            float(sum(r["cumulative_score"] for r in active_rows) / len(active_rows))
            if active_rows else 0.0
        )
        total_score_per_day = float(sum(r["score_per_day"] for r in node_rows))
        avg_active_days = round(sum(r["active_days"] for r in node_rows) / count)
        avg_normalised = float(sum(r["normalised_score"] for r in node_rows) / count)

        ws.append([
            node.name,
            count,
            active_pct,
            avg_active_days,
            avg_cumulative,
            avg_cumulative_active,
            total_score_per_day,
            avg_normalised,
        ])

    return _xlsx_response(wb, "sub-units.xlsx")


@router.get("/soldiers/{soldier_id}/effort-breakdown", response_model=EffortBreakdownOut)
def effort_breakdown(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> EffortBreakdownOut:
    from app.services.effort_score import compute_effort_breakdown, quarter_start
    from app.services.settings_loader import SettingNotFound, get_setting

    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))

    today = date.today()
    try:
        reset_raw = get_setting(session, "fairness.reset_date")
        reset_date = date.fromisoformat(str(reset_raw))
    except Exception:
        reset_date = quarter_start(date(today.year - 2, today.month, 1))

    latest_published_end = session.execute(
        select(func.max(DutyAssignment.end_date)).where(DutyAssignment.status == "published")
    ).scalar()
    if latest_published_end is not None and latest_published_end >= today:
        planning_start = latest_published_end + timedelta(days=1)
    else:
        planning_start = today

    bd = compute_effort_breakdown(
        session,
        soldier=s,
        planning_start=planning_start,
        planning_end=planning_start,
        reset_date=reset_date,
    )
    return EffortBreakdownOut(
        quarters=[
            EffortQuarterRow(
                quarter_start=q.quarter_start,
                quarter_end=q.quarter_end,
                quarter_label=q.quarter_label,
                soldier_score=q.soldier_score,
                unit_score=q.unit_score,
                active_frac=q.active_frac,
                share=q.share,
                weighted_share=q.weighted_share,
                is_partial=q.is_partial,
            )
            for q in bd.quarters
        ],
        effort_score=bd.effort_score,
        A_i=bd.A_i,
        W_i=bd.W_i,
    )


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
