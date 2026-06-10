"""Add forced_call_up_multiplier to duty_assignments

Revision ID: 0044
Revises: 0043
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "duty_assignments",
        sa.Column("forced_call_up_multiplier", sa.Numeric(6, 2), nullable=True),
    )

    # Backfill: copy callup_multiplier from approved forced_callups to their
    # replacement assignments (these were previously represented as ScoreAdjustments)
    op.execute(text("""
        UPDATE duty_assignments da
        SET forced_call_up_multiplier = fc.callup_multiplier
        FROM forced_callups fc
        WHERE fc.replacement_assignment_id = da.id
          AND fc.status = 'approved'
    """))

    # Remove the old ScoreAdjustment rows that the hakpaza approve code created.
    # These are now fully represented by the forced_call_up_multiplier field.
    op.execute(text("""
        DELETE FROM score_adjustments
        WHERE reason LIKE 'הקפצה פיקודית — %'
    """))


def downgrade() -> None:
    # Restore ScoreAdjustments for approved forced callups before dropping column.
    # Join through replacement_assignment (not original) because approve() sets
    # orig.end_date = pull_date - 1, which would make the delta zero.
    op.execute(text("""
        INSERT INTO score_adjustments (id, soldier_id, delta, reason, created_by)
        SELECT
            gen_random_uuid(),
            fc.replacement_soldier_id,
            dt.score_per_day
                * ((repl.end_date - fc.pull_date + 1))
                * fc.callup_multiplier,
            'הקפצה פיקודית (restored)',
            fc.approver_id
        FROM forced_callups fc
        JOIN duty_assignments repl ON repl.id = fc.replacement_assignment_id
        JOIN duty_types dt ON dt.id = repl.duty_type_id
        WHERE fc.status = 'approved'
          AND fc.replacement_assignment_id IS NOT NULL
    """))

    op.drop_column("duty_assignments", "forced_call_up_multiplier")
