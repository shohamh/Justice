"""add object storage metadata

Revision ID: 4858092e72e7
Revises: 20260928_admin_error_clears
Create Date: 2026-09-27 13:02:08.676050

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4858092e72e7'
down_revision: Union[str, Sequence[str], None] = '20260928_admin_error_clears'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FILE_TABLES = (
    "soldier_exemption_files",
    "exemption_request_files",
    "gimelim_attachments",
    "bug_report_comment_attachments",
    "bug_reports",
    "import_sessions",
)


def upgrade() -> None:
    for table in _FILE_TABLES:
        op.add_column(table, sa.Column("storage_key", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("storage_sha256", sa.Text(), nullable=True))
        if table != "bug_reports":
            op.add_column(table, sa.Column("storage_size", sa.Integer(), nullable=True))
    op.add_column("bug_reports", sa.Column("storage_size", sa.Integer(), nullable=True))
    op.add_column("bug_reports", sa.Column("json_mirror_storage_key", sa.Text(), nullable=True))
    op.add_column("bug_reports", sa.Column("json_mirror_sha256", sa.Text(), nullable=True))
    for table in (
        "soldier_exemption_files",
        "exemption_request_files",
        "gimelim_attachments",
        "bug_report_comment_attachments",
        "import_sessions",
    ):
        op.alter_column(table, "data" if table != "import_sessions" else "raw_excel", nullable=True)
    op.create_table(
        "storage_delete_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("object_key", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_storage_delete_outbox_pending",
        "storage_delete_outbox",
        ["created_at"],
        postgresql_where=sa.text("completed_at IS NULL"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Object storage metadata cannot be downgraded safely after any object-only write. "
        "Restore a database backup from before this migration instead."
    )
