"""Persist deterministic event-date order for Exchange backfill.

Revision ID: 20261002_exchange_event_date
Revises: 20260928_exchange_outbox
"""

import sqlalchemy as sa

from alembic import op

revision = "20261002_exchange_event_date"
down_revision = "20260928_exchange_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("exchange_calendar_outbox", sa.Column("event_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("exchange_calendar_outbox", "event_date")
