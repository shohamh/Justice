"""add keva to enlisted duty type allowed_service_types

Revision ID: 6b45caf468c2
Revises: 63cff804e3e4
Create Date: 2026-07-30 14:08:19.163703

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6b45caf468c2'
down_revision: Union[str, Sequence[str], None] = '63cff804e3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


duty_types_t = sa.table(
    "duty_types",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("requirements", postgresql.JSONB()),
)


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(duty_types_t.c.id, duty_types_t.c.requirements).where(
            duty_types_t.c.requirements.isnot(None)
        )
    ).mappings().all()
    for row in rows:
        requirements = dict(row["requirements"])
        allowed = requirements.get("allowed_service_types")
        if allowed == ["חובה"] and requirements.get("enlisted_allowed", True) is not False:
            requirements["allowed_service_types"] = ["חובה", "קבע"]
            conn.execute(
                sa.update(duty_types_t)
                .where(duty_types_t.c.id == row["id"])
                .values(requirements=requirements)
            )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(duty_types_t.c.id, duty_types_t.c.requirements).where(
            duty_types_t.c.requirements.isnot(None)
        )
    ).mappings().all()
    for row in rows:
        requirements = dict(row["requirements"])
        if requirements.get("allowed_service_types") == ["חובה", "קבע"]:
            requirements["allowed_service_types"] = ["חובה"]
            conn.execute(
                sa.update(duty_types_t)
                .where(duty_types_t.c.id == row["id"])
                .values(requirements=requirements)
            )
