"""Set personal_constraints.status default to pending_commander

Revision ID: c3e4f5a6b7d8
Revises: b2d3f4a5c6e7
Create Date: 2026-07-30
"""
from alembic import op

revision = "c3e4f5a6b7d8"
down_revision = "b2d3f4a5c6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Task 9 replaced the single "pending" PersonalConstraint.status value with
    # a two-step "pending_commander" / "pending_duty_manager" split. Every read
    # path (approval queues, remaining-days counting, admin routes, soldier
    # soft-delete, the approvals importer whitelist) was migrated off the bare
    # "pending" value, but the column default was left pointing at it — any
    # future insert that omitted status explicitly would silently produce an
    # invisible, uncounted, uncancellable row.
    op.execute(
        "ALTER TABLE personal_constraints ALTER COLUMN status SET DEFAULT 'pending_commander'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE personal_constraints ALTER COLUMN status SET DEFAULT 'pending'"
    )
