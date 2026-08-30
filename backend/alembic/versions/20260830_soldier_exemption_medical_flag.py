"""persist medical classification on soldier exemptions"""

import sqlalchemy as sa

from alembic import op


revision = "20260830_exemption_medical"
down_revision = "20260830_soldier_exemption_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "soldier_exemptions",
        sa.Column("is_medical", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("soldier_exemptions", "is_medical")
