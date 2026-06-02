"""merge heads: 0026 (notifications) + 36d8af34a3d6 (eligible_node_ids)

Revision ID: 0027
Revises: 0026, 36d8af34a3d6
Create Date: 2026-06-02

"""
from typing import Sequence, Union

revision: str = "0027"
down_revision: Union[str, Sequence[str], None] = ("0026", "36d8af34a3d6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
