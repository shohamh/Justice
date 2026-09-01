"""add active-days reference persistence fields

Revision ID: 20260901_active_days_ref
Revises: 20260830_exemption_medical
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901_active_days_ref"
down_revision = "20260830_exemption_medical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("soldiers", sa.Column("unit_join_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("soldiers", "unit_join_date")
