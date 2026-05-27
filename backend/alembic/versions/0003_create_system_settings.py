"""create system_settings

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-27
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


DEFAULTS: dict[str, object] = {
    "auth.session_minutes": 15,
    "auth.refresh_days": 30,
    "auth.login_rate_limit_per_5m": 5,
}


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    # Seed auth-relevant defaults; later slices seed their own keys in their migrations.
    rows = [{"key": k, "value": json.dumps(v)} for k, v in DEFAULTS.items()]
    if rows:
        op.execute(sa.text("INSERT INTO system_settings (key, value) VALUES " + ", ".join(f"('{r['key']}', '{r['value']}'::jsonb)" for r in rows)))


def downgrade() -> None:
    op.drop_table("system_settings")
