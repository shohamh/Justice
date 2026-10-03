"""oidc identities (issuer + subject linked to one soldier)

Revision ID: 20261003_oidc_identities
Revises: 20261003_oidc_transactions
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261003_oidc_identities"
down_revision: Union[str, Sequence[str], None] = "20261003_oidc_transactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oidc_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("issuer", "subject", name="uq_oidc_identities_issuer_subject"),
        sa.CheckConstraint("length(btrim(issuer)) > 0 AND length(btrim(subject)) > 0",
                           name="ck_oidc_identities_non_blank"),
    )


def downgrade() -> None:
    op.drop_table("oidc_identities")
