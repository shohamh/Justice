"""merge hr identity conflicts and oidc

Revision ID: 20261003_merge_identity_heads
Revises: 20261002_hr_identity_conflicts, 20261003_oidc_registration
Create Date: 2026-10-02 20:53:35.230935

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20261003_merge_identity_heads'
down_revision: Union[str, Sequence[str], None] = ('20261002_hr_identity_conflicts', '20261003_oidc_registration')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
