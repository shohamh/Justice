"""preserve range qualification event history"""
from alembic import op
import sqlalchemy as sa

revision = "20260802rq01"
down_revision = "20260802rn01"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("soldier_range_qualifications", sa.Column("source_range_event_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_soldier_range_qualifications_source_range_event_id",
        "soldier_range_qualifications",
        "range_events",
        ["source_range_event_id"],
        ["id"],
        ondelete="SET NULL",
    )

def downgrade() -> None:
    op.drop_constraint(
        "fk_soldier_range_qualifications_source_range_event_id",
        "soldier_range_qualifications",
        type_="foreignkey",
    )
    op.drop_column("soldier_range_qualifications", "source_range_event_id")
