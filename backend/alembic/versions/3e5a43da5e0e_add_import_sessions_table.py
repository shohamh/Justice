"""add import_sessions table

Revision ID: 3e5a43da5e0e
Revises: 7bef29786e25
Create Date: 2026-07-01 07:31:59.393833

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3e5a43da5e0e'
down_revision: Union[str, Sequence[str], None] = '7bef29786e25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE TYPE import_session_status AS ENUM ('draft', 'confirmed', 'cancelled', 'done')")
    op.create_table(
        "import_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status", postgresql.ENUM("draft", "confirmed", "cancelled", "done", name="import_session_status", create_type=False), server_default="draft", nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("raw_excel", sa.LargeBinary(), nullable=False),
        sa.Column("parsed_state", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("user_selections", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_links", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("import_sessions")
    op.execute("DROP TYPE import_session_status")
