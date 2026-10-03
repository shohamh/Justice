"""oidc login transactions

Revision ID: 20261003_oidc_transactions
Revises: 20261002_identity_conflicts
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261003_oidc_transactions"
down_revision: Union[str, Sequence[str], None] = "20261002_identity_conflicts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oidc_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("state_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("browser_hash", sa.Text(), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_oidc_transactions_expires_at", "oidc_transactions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_oidc_transactions_expires_at", table_name="oidc_transactions")
    op.drop_table("oidc_transactions")
