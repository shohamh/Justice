"""add_ranges_tables

Revision ID: de2742d45fa3
Revises: 651a0642281d
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'de2742d45fa3'
down_revision: Union[str, Sequence[str], None] = '651a0642281d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    range_type_enum = postgresql.ENUM("laser", "live", "alal", name="range_type")
    range_type_enum.create(op.get_bind(), checkfirst=True)
    range_event_status_enum = postgresql.ENUM("planned", "completed", "cancelled", name="range_event_status")
    range_event_status_enum.create(op.get_bind(), checkfirst=True)
    range_attendance_status_enum = postgresql.ENUM("pending", "present", "no_show", name="range_attendance_status")
    range_attendance_status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "duty_types",
        sa.Column("requires_weapon", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "exemption_types",
        sa.Column("forbids_weapons", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "range_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("hierarchy_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("range_type", postgresql.ENUM("laser", "live", "alal", name="range_type", create_type=False), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Text(), nullable=True),
        sa.Column("end_time", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("arrival_instructions", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.Text(), nullable=True),
        sa.Column("contact_phone", sa.Text(), nullable=True),
        sa.Column("required_count", sa.Integer(), nullable=False),
        sa.Column("reserve_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "status",
            postgresql.ENUM("planned", "completed", "cancelled", name="range_event_status", create_type=False),
            nullable=False,
            server_default=sa.text("'planned'"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "range_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("range_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("range_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_reserve", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "attendance_status",
            postgresql.ENUM("pending", "present", "no_show", name="range_attendance_status", create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("marked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("score_adjustment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("score_adjustments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("range_event_id", "soldier_id", name="uq_range_assignment_event_soldier"),
    )

    op.create_table(
        "soldier_range_qualifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("range_type", postgresql.ENUM("laser", "live", "alal", name="range_type", create_type=False), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("source_range_assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("range_assignments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("soldier_id", "range_type", name="uq_soldier_range_qualification"),
    )

    op.execute(
        """
        INSERT INTO system_settings (key, value) VALUES
            ('mitvachim.enabled', 'false'),
            ('mitvachim.laser_validity_days', '180'),
            ('mitvachim.live_validity_days', '365'),
            ('mitvachim.alal_validity_days', '365'),
            ('mitvachim.attendance_edit_min_level', '"ענף"')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM system_settings WHERE key IN ("
        "'mitvachim.enabled', 'mitvachim.laser_validity_days', 'mitvachim.live_validity_days', "
        "'mitvachim.alal_validity_days', 'mitvachim.attendance_edit_min_level')"
    )
    op.drop_table("soldier_range_qualifications")
    op.drop_table("range_assignments")
    op.drop_table("range_events")
    op.drop_column("exemption_types", "forbids_weapons")
    op.drop_column("duty_types", "requires_weapon")
    postgresql.ENUM(name="range_attendance_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="range_event_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="range_type").drop(op.get_bind(), checkfirst=True)
