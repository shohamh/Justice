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
    op.execute("REVOKE ALL ON TABLE storage_delete_outbox FROM app;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE storage_delete_outbox TO app;")
    op.create_index(
        "ix_storage_delete_outbox_pending",
        "storage_delete_outbox",
        ["created_at"],
        postgresql_where=sa.text("completed_at IS NULL"),
    )


def _has_rows(bind, table: str, predicate: str) -> bool:
    # All identifiers and predicates are constants defined in this migration.
    statement = sa.text(
        f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {predicate})"
    )
    return bool(bind.execute(statement).scalar_one())


def downgrade() -> None:
    bind = op.get_bind()
    object_references = [
        (table, "storage_key IS NOT NULL")
        for table in _FILE_TABLES
    ]
    object_references.append(("bug_reports", "json_mirror_storage_key IS NOT NULL"))
    object_references.append(("storage_delete_outbox", "completed_at IS NULL"))
    if any(_has_rows(bind, table, predicate) for table, predicate in object_references):
        raise RuntimeError(
            "Cannot downgrade while storage objects or pending deletions are referenced."
        )

    legacy_payload_columns = [
        ("soldier_exemption_files", "data"),
        ("exemption_request_files", "data"),
        ("gimelim_attachments", "data"),
        ("bug_report_comment_attachments", "data"),
        ("import_sessions", "raw_excel"),
    ]
    if any(
        _has_rows(bind, table, f"{column} IS NULL")
        for table, column in legacy_payload_columns
    ):
        raise RuntimeError(
            "Cannot downgrade while legacy file payload columns contain NULL values."
        )

    for table, column in legacy_payload_columns:
        op.alter_column(table, column, nullable=False)

    op.drop_index("ix_storage_delete_outbox_pending", table_name="storage_delete_outbox")
    op.drop_table("storage_delete_outbox")

    for table in _FILE_TABLES:
        op.drop_column(table, "storage_key")
        op.drop_column(table, "storage_sha256")
        if table != "bug_reports":
            op.drop_column(table, "storage_size")
    op.drop_column("bug_reports", "storage_size")
    op.drop_column("bug_reports", "json_mirror_storage_key")
    op.drop_column("bug_reports", "json_mirror_sha256")
