"""Index the published assignment end date used by transparency planning.

Revision ID: 20261002_transparency_max_end
Revises: 20261001_hakpaza_roster_revision
Create Date: 2026-10-02
"""

from alembic import op

revision = "20261002_transparency_max_end"
down_revision = "20261001_hakpaza_roster_revision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_duty_assignments_status_end_date "
            "ON duty_assignments (status, end_date DESC)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY ix_duty_assignments_status_end_date")
