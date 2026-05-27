"""create audit_log

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("actor_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("after", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("context", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    # Append-only: app can only INSERT and SELECT.
    op.execute("REVOKE ALL ON TABLE audit_log FROM app;")
    op.execute("GRANT SELECT, INSERT ON TABLE audit_log TO app;")


def downgrade() -> None:
    op.drop_table("audit_log")
