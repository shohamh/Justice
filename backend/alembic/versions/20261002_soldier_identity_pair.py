"""soldier email and ad_username must be written as a pair

Revision ID: 20261002_soldier_identity_pair
Revises: 20261002_soldier_identity
Create Date: 2026-10-02

Every write path now stores the canonical email and the AD username derived
from it together (app.services.identity_write). This CHECK makes the database
the last line of defence: both NULL, or ad_username equal to the email local
part.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261002_soldier_identity_pair"
down_revision: Union[str, Sequence[str], None] = "20261002_soldier_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_soldiers_email_ad_username_pair",
        "soldiers",
        "(email IS NULL AND ad_username IS NULL) "
        "OR (email IS NOT NULL AND ad_username IS NOT NULL AND ad_username = split_part(email, '@', 1))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_soldiers_email_ad_username_pair", "soldiers", type_="check")
