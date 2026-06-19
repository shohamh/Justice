"""add corps level and כלל המסגרת root node

Revision ID: 0052
Revises: 0051
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Extend the enum with a new top-level 'corps' value.
    op.execute("ALTER TYPE hierarchy_level ADD VALUE IF NOT EXISTS 'corps' BEFORE 'division'")

    # 2. Create the root node and propagate it through the existing tree atomically.
    #    - Root node path_ids starts empty, then gets patched to [root.id].
    #    - All existing parentless nodes become children of the root.
    #    - All existing nodes get root.id prepended to their path_ids.
    #    - Root node ID is stored in system_settings for fast lookup.
    op.execute("""
        DO $$
        DECLARE
            root_id uuid;
        BEGIN
            -- Bail out if we already ran (idempotent).
            IF EXISTS (SELECT 1 FROM system_settings WHERE key = 'system.root_node_id') THEN
                RETURN;
            END IF;

            -- Create the root node.
            INSERT INTO hierarchy_nodes (level, name, parent_id, path_ids)
            VALUES ('corps', 'כלל המסגרת', NULL, ARRAY[]::uuid[])
            RETURNING id INTO root_id;

            -- Self-referential path.
            UPDATE hierarchy_nodes SET path_ids = ARRAY[root_id] WHERE id = root_id;

            -- Reparent all current root nodes (parent_id IS NULL, excluding the new root).
            UPDATE hierarchy_nodes
            SET parent_id = root_id
            WHERE parent_id IS NULL AND id != root_id;

            -- Prepend root_id to every existing node's path_ids (excluding the root itself).
            UPDATE hierarchy_nodes
            SET path_ids = ARRAY[root_id] || path_ids
            WHERE id != root_id;

            -- Persist the root node ID.
            INSERT INTO system_settings (key, value, updated_by)
            VALUES ('system.root_node_id', root_id::text, NULL);
        END $$;
    """)


def downgrade() -> None:
    # Remove root node and restore original state.
    op.execute("""
        DO $$
        DECLARE
            root_id uuid;
        BEGIN
            SELECT value::uuid INTO root_id
            FROM system_settings WHERE key = 'system.root_node_id';

            IF root_id IS NULL THEN RETURN; END IF;

            -- Strip root_id from all path_ids.
            UPDATE hierarchy_nodes
            SET path_ids = path_ids[2:]
            WHERE id != root_id AND path_ids[1] = root_id;

            -- Restore parent_id = NULL for direct children of root.
            UPDATE hierarchy_nodes SET parent_id = NULL WHERE parent_id = root_id;

            DELETE FROM hierarchy_nodes WHERE id = root_id;
            DELETE FROM system_settings WHERE key = 'system.root_node_id';
        END $$;
    """)
    # Note: enum value 'corps' cannot be removed from PostgreSQL without recreating the type.
