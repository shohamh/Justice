"""Track changes to fields used by the paged soldier roster.

Revision ID: 20260930_soldier_roster_revision
Revises: 20260928_admin_error_clears
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "20260930_soldier_roster_revision"
down_revision = "20260928_admin_error_clears"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soldier_roster_revision",
        sa.Column("singleton", sa.Boolean(), primary_key=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("singleton", name="ck_soldier_roster_revision_singleton"),
    )
    op.execute("INSERT INTO soldier_roster_revision (singleton, revision) VALUES (TRUE, 0)")
    op.execute("""
        CREATE FUNCTION bump_soldier_roster_revision() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NOT EXISTS (SELECT 1 FROM new_rows) THEN RETURN NULL; END IF;
            ELSIF TG_OP = 'DELETE' THEN
                IF NOT EXISTS (SELECT 1 FROM old_rows) THEN RETURN NULL; END IF;
            END IF;
            IF TG_TABLE_NAME = 'telegram_links' THEN
                IF TG_OP = 'INSERT' THEN
                    IF NOT EXISTS (SELECT 1 FROM new_rows WHERE is_verified) THEN RETURN NULL; END IF;
                ELSIF TG_OP = 'DELETE' THEN
                    IF NOT EXISTS (SELECT 1 FROM old_rows WHERE is_verified) THEN RETURN NULL; END IF;
                END IF;
            END IF;
            UPDATE soldier_roster_revision SET revision = revision + 1 WHERE singleton;
            RETURN NULL;
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION bump_soldier_roster_revision_on_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'soldiers' THEN
                -- Transition tables contain only this statement's updated rows.
                -- Comparing projections as multisets also catches changed IDs.
                IF NOT EXISTS (
                    SELECT id, personal_number, full_name, role, hierarchy_node_id, left_at FROM old_rows
                    EXCEPT ALL
                    SELECT id, personal_number, full_name, role, hierarchy_node_id, left_at FROM new_rows
                ) THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME = 'hierarchy_nodes' THEN
                IF NOT EXISTS (
                    SELECT id, name, path_ids FROM old_rows
                    EXCEPT ALL
                    SELECT id, name, path_ids FROM new_rows
                ) THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME = 'telegram_links' THEN
                -- Only verified link membership affects the roster. Check both
                -- directions because the filtered row counts can differ.
                IF NOT EXISTS (
                    SELECT soldier_id FROM old_rows WHERE is_verified
                    EXCEPT ALL
                    SELECT soldier_id FROM new_rows WHERE is_verified
                ) AND NOT EXISTS (
                    SELECT soldier_id FROM new_rows WHERE is_verified
                    EXCEPT ALL
                    SELECT soldier_id FROM old_rows WHERE is_verified
                ) THEN RETURN NULL; END IF;
            END IF;
            UPDATE soldier_roster_revision SET revision = revision + 1 WHERE singleton;
            RETURN NULL;
        END;
        $$
    """)
    for table in ("soldiers", "hierarchy_nodes", "telegram_links"):
        for operation in ("INSERT", "DELETE"):
            transition = "NEW TABLE AS new_rows" if operation == "INSERT" else "OLD TABLE AS old_rows"
            op.execute(f"""
                CREATE TRIGGER {table}_roster_{operation.lower()}
                AFTER {operation} ON {table}
                REFERENCING {transition}
                FOR EACH STATEMENT EXECUTE FUNCTION bump_soldier_roster_revision()
            """)
        op.execute(f"""
            CREATE TRIGGER {table}_roster_update
            AFTER UPDATE ON {table}
            REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
            FOR EACH STATEMENT EXECUTE FUNCTION bump_soldier_roster_revision_on_update()
        """)


def downgrade() -> None:
    for table in ("soldiers", "hierarchy_nodes", "telegram_links"):
        for operation in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER {table}_roster_{operation} ON {table}")
    op.execute("DROP FUNCTION bump_soldier_roster_revision_on_update()")
    op.execute("DROP FUNCTION bump_soldier_roster_revision()")
    op.drop_table("soldier_roster_revision")
