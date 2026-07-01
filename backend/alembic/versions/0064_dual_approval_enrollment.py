"""add is_career to soldiers and enrollment_request_id to exemption_requests

Revision ID: 0064
Revises: 0063
Create Date: 2026-07-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0064'
down_revision = '0063'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'soldiers',
        sa.Column('is_career', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'exemption_requests',
        sa.Column(
            'enrollment_request_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('soldier_enrollment_requests.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('exemption_requests_enrollment_request_id_fkey'),
        'exemption_requests',
        type_='foreignkey',
    )
    op.drop_column('exemption_requests', 'enrollment_request_id')
    op.drop_column('soldiers', 'is_career')
