"""create hierarchy_level_types; convert hierarchy_nodes.level to varchar

Revision ID: 0059
Revises: 0058
Create Date: 2026-06-23
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

_SEED_TYPES = [
    ("corps", "אגף", 1),
    ("division", "מערך", 2),
    ("unit", "יחידה", 3),
    ("department", "מרכז", 4),
    ("branch", "ענף", 5),
    ("group", "מדור", 6),
    ("team", "צוות", 7),
]


def upgrade() -> None:
    op.create_table(
        "hierarchy_level_types",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("key", sa.String(length=50), nullable=False, unique=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, unique=True),
    )

    rows = ", ".join(
        f"(gen_random_uuid(), '{key}', '{label}', {rank})" for key, label, rank in _SEED_TYPES
    )
    op.execute(
        f"INSERT INTO hierarchy_level_types (id, key, label, rank) VALUES {rows}"
    )

    # hierarchy_nodes.level was a Postgres ENUM (hierarchy_level); convert to a
    # plain varchar so admin-defined custom level keys can be stored.
    op.execute(
        "ALTER TABLE hierarchy_nodes ALTER COLUMN level TYPE varchar(50) USING level::text"
    )
    op.execute("DROP TYPE IF EXISTS hierarchy_level")


def downgrade() -> None:
    LEVEL_ENUM = sa.Enum(
        "corps", "division", "unit", "department", "branch", "group", "team",
        name="hierarchy_level",
    )
    LEVEL_ENUM.create(op.get_bind(), checkfirst=True)
    op.execute(
        "ALTER TABLE hierarchy_nodes ALTER COLUMN level TYPE hierarchy_level USING level::hierarchy_level"
    )
    op.drop_table("hierarchy_level_types")
