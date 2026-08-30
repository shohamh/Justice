"""add files to granted soldier exemptions"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260830_soldier_exemption_files"
down_revision = "20260829_transfer_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soldier_exemption_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "soldier_exemption_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldier_exemptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("soldier_exemption_files")
