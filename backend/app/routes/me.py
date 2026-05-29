from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.db.models import Soldier

router = APIRouter(prefix="/me", tags=["me"])


class MeResponse(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    must_change_password: bool
    hierarchy_node_id: uuid.UUID | None


@router.get("", response_model=MeResponse)
def me(user: Soldier = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=user.id,
        personal_number=user.personal_number,
        full_name=user.full_name,
        role=user.role,
        must_change_password=user.must_change_password,
        hierarchy_node_id=user.hierarchy_node_id,
    )
