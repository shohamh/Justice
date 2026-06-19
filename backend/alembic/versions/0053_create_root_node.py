"""create כלל המסגרת root node

Revision ID: 0053
Revises: 0052
Create Date: 2026-06-19
"""

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 'corps' was added in 0052 and is now committed, so it's safe to use here.
    op.execute("""
        DO $$
        DECLARE
            root_id uuid;
        BEGIN
            IF EXISTS (SELECT 1 FROM system_settings WHERE key = 'system.root_node_id') THEN
                RETURN;
            END IF;

            INSERT INTO hierarchy_nodes (level, name, parent_id, path_ids)
            VALUES ('corps', 'כלל המסגרת', NULL, ARRAY[]::uuid[])
            RETURNING id INTO root_id;

            UPDATE hierarchy_nodes SET path_ids = ARRAY[root_id] WHERE id = root_id;

            UPDATE hierarchy_nodes
            SET parent_id = root_id
            WHERE parent_id IS NULL AND id != root_id;

            UPDATE hierarchy_nodes
            SET path_ids = ARRAY[root_id] || path_ids
            WHERE id != root_id;

            INSERT INTO system_settings (key, value, updated_by)
            VALUES ('system.root_node_id', to_jsonb(root_id::text), NULL);
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            root_id uuid;
        BEGIN
            SELECT (value #>> '{}')::uuid INTO root_id
            FROM system_settings WHERE key = 'system.root_node_id';

            IF root_id IS NULL THEN RETURN; END IF;

            UPDATE hierarchy_nodes
            SET path_ids = path_ids[2:]
            WHERE id != root_id AND path_ids[1] = root_id;

            UPDATE hierarchy_nodes SET parent_id = NULL WHERE parent_id = root_id;

            DELETE FROM hierarchy_nodes WHERE id = root_id;
            DELETE FROM system_settings WHERE key = 'system.root_node_id';
        END $$;
    """)
