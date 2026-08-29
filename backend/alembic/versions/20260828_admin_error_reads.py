"""Create persistent per-admin error read markers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260828aer1"
down_revision = "27dc951bcc93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_error_reads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("record_key", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("admin_id", "source", "record_key", name="uq_admin_error_reads_admin_source_record_key"),
    )


def downgrade() -> None:
    op.drop_table("admin_error_reads")
