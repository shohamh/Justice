"""create app role

Revision ID: 0001
Revises:
Create Date: 2026-05-27

This migration runs as db_admin. It creates the lower-privileged 'app' role
that the FastAPI process authenticates as. Permissions on individual tables
are granted by the migrations that create those tables.
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app') THEN
                CREATE ROLE app LOGIN PASSWORD 'app_pw';
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT CONNECT ON DATABASE cod2 TO app;")
    op.execute("GRANT USAGE ON SCHEMA public TO app;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app;")


def downgrade() -> None:
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM app;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM app;")
    op.execute("REVOKE USAGE ON SCHEMA public FROM app;")
    op.execute("REVOKE CONNECT ON DATABASE cod2 FROM app;")
    op.execute("DROP ROLE IF EXISTS app;")
