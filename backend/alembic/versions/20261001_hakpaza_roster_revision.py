"""Track Hakpaza roster assignment changes and index next-shift lookup.

Revision ID: 20261001_hakpaza_roster_revision
Revises: 20260930_soldier_roster_revision
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20261001_hakpaza_roster_revision"
down_revision = "20260930_soldier_roster_revision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Avoid blocking assignment writes while the scale dataset's index is built.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_duty_assignments_hakpaza_next "
            "ON duty_assignments (soldier_id, start_date, id) "
            "WHERE status = 'published'"
        )

    op.execute(
        """
        CREATE FUNCTION bump_soldier_roster_revision_for_assignments() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE soldier_roster_revision
            SET revision = revision + 1
            WHERE singleton;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER duty_assignments_roster_revision
        AFTER INSERT OR UPDATE OR DELETE ON duty_assignments
        FOR EACH STATEMENT
        EXECUTE FUNCTION bump_soldier_roster_revision_for_assignments()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER duty_assignments_roster_revision ON duty_assignments")
    op.execute("DROP FUNCTION bump_soldier_roster_revision_for_assignments()")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY ix_duty_assignments_hakpaza_next")
