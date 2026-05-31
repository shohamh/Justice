"""shift_templates table + duty_shifts generation columns

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shift_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("duty_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("duty_location_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weekdays", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("start_time", sa.Text(), server_default=sa.text("'00:00'"), nullable=False),
        sa.Column("end_time", sa.Text(), server_default=sa.text("'23:59'"), nullable=False),
        sa.Column("required_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("auto_roll", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["duty_type_id"], ["duty_types.id"], ondelete="RESTRICT", name="fk_shift_templates_duty_type_id"),
        sa.ForeignKeyConstraint(["duty_location_id"], ["duty_locations.id"], ondelete="RESTRICT", name="fk_shift_templates_duty_location_id"),
        sa.ForeignKeyConstraint(["created_by"], ["soldiers.id"], ondelete="SET NULL", name="fk_shift_templates_created_by"),
    )
    op.add_column(
        "duty_shifts",
        sa.Column("generated_from_template_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_duty_shifts_generated_from_template_id",
        "duty_shifts", "shift_templates",
        ["generated_from_template_id"], ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "duty_shifts",
        sa.Column("dm_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("duty_shifts", "dm_locked")
    op.drop_constraint("fk_duty_shifts_generated_from_template_id", "duty_shifts", type_="foreignkey")
    op.drop_column("duty_shifts", "generated_from_template_id")
    op.drop_table("shift_templates")
