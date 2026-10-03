"""oidc registration contexts

Revision ID: 20261003_oidc_registration
Revises: 20261003_oidc_identities
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261003_oidc_registration"
down_revision: Union[str, Sequence[str], None] = "20261003_oidc_identities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oidc_registration_contexts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("ad_username", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_oidc_registration_contexts_live_subject", "oidc_registration_contexts",
        ["issuer", "subject"], unique=True, postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_oidc_registration_contexts_live_subject", table_name="oidc_registration_contexts")
    op.drop_table("oidc_registration_contexts")
