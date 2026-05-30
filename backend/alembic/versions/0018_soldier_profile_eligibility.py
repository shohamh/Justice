"""soldier profile fields, field updates table, duty type requirements

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Soldier profile fields ---
    op.add_column("soldiers", sa.Column("gender", sa.Text(), nullable=True))
    op.add_column("soldiers", sa.Column("is_officer", sa.Boolean(), nullable=True))
    op.add_column("soldiers", sa.Column("rank", sa.Text(), nullable=True))
    op.add_column("soldiers", sa.Column("bahad1_graduate", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("soldiers", sa.Column("enlistment_date", sa.Date(), nullable=True))
    op.add_column("soldiers", sa.Column("mandatory_end_date", sa.Date(), nullable=True))
    op.add_column("soldiers", sa.Column("discharge_date", sa.Date(), nullable=True))
    op.add_column("soldiers", sa.Column("last_mitvahim_date", sa.Date(), nullable=True))
    op.add_column("soldiers", sa.Column("last_alal_date", sa.Date(), nullable=True))

    # --- Soldier field update requests ---
    op.create_table(
        "soldier_field_updates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_name", sa.Text(), nullable=False),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("idx_sfu_soldier", "soldier_field_updates", ["soldier_id"])
    op.create_index("idx_sfu_status", "soldier_field_updates", ["status"])

    # --- DutyType eligibility requirements ---
    op.add_column(
        "duty_types",
        sa.Column("requirements", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
    )

    # --- System settings defaults ---
    op.execute(
        "INSERT INTO system_settings (key, value) VALUES "
        "('eligibility.mitvahim_months', '6') ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "INSERT INTO system_settings (key, value) VALUES "
        "('eligibility.alal_months', '3') ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM system_settings WHERE key IN ('eligibility.mitvahim_months', 'eligibility.alal_months')")
    op.drop_column("duty_types", "requirements")
    op.drop_index("idx_sfu_status", table_name="soldier_field_updates")
    op.drop_index("idx_sfu_soldier", table_name="soldier_field_updates")
    op.drop_table("soldier_field_updates")
    for col in ["last_alal_date", "last_mitvahim_date", "discharge_date",
                "mandatory_end_date", "enlistment_date", "bahad1_graduate",
                "rank", "is_officer", "gender"]:
        op.drop_column("soldiers", col)
