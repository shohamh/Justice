"""grant shift_templates table to app role

Revision ID: 0051
Revises: fcac936c2558
Create Date: 2026-06-18
"""

from alembic import op

revision = "0051"
down_revision = "fcac936c2558"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE shift_templates TO app;")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE shift_templates FROM app;")
