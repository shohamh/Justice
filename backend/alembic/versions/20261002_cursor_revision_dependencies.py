"""Track the remaining inputs to paged roster and transparency cursors.

Revision ID: 20261002_cursor_revision_deps
Revises: 20261002_transparency_max_end
Create Date: 2026-10-02
"""

import sqlalchemy as sa

from alembic import op

revision = "20261002_cursor_revision_deps"
down_revision = "20261002_transparency_max_end"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Soldier roster cursors also serve the hierarchy tree and Hakpaza picker.
    # Extend the existing statement-level change detector to the fields those
    # projections actually return.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION bump_soldier_roster_revision_on_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'soldiers' THEN
                IF NOT EXISTS (
                    SELECT id, personal_number, full_name, role, hierarchy_node_id, left_at, rank
                    FROM old_rows
                    EXCEPT ALL
                    SELECT id, personal_number, full_name, role, hierarchy_node_id, left_at, rank
                    FROM new_rows
                ) THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME = 'hierarchy_nodes' THEN
                IF NOT EXISTS (
                    SELECT id, name, level, parent_id, commander_id, path_ids FROM old_rows
                    EXCEPT ALL
                    SELECT id, name, level, parent_id, commander_id, path_ids FROM new_rows
                ) THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME = 'telegram_links' THEN
                IF NOT EXISTS (
                    SELECT soldier_id FROM old_rows WHERE is_verified
                    EXCEPT ALL
                    SELECT soldier_id FROM new_rows WHERE is_verified
                ) AND NOT EXISTS (
                    SELECT soldier_id FROM new_rows WHERE is_verified
                    EXCEPT ALL
                    SELECT soldier_id FROM old_rows WHERE is_verified
                ) THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME = 'duty_types' THEN
                IF NOT EXISTS (
                    SELECT id, name FROM old_rows
                    EXCEPT ALL
                    SELECT id, name FROM new_rows
                ) THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME = 'duty_manager_scope' THEN
                IF NOT EXISTS (
                    SELECT duty_manager_id, hierarchy_node_id FROM old_rows
                    EXCEPT ALL
                    SELECT duty_manager_id, hierarchy_node_id FROM new_rows
                ) THEN RETURN NULL; END IF;
            END IF;
            UPDATE soldier_roster_revision SET revision = revision + 1 WHERE singleton;
            RETURN NULL;
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION bump_soldier_roster_revision_for_scope_and_duty_type() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'duty_manager_scope' THEN
                IF TG_OP = 'INSERT' THEN
                    IF NOT EXISTS (SELECT 1 FROM new_rows) THEN RETURN NULL; END IF;
                ELSIF TG_OP = 'DELETE' THEN
                    IF NOT EXISTS (SELECT 1 FROM old_rows) THEN RETURN NULL; END IF;
                END IF;
            ELSIF TG_TABLE_NAME = 'duty_types' THEN
                IF TG_OP = 'INSERT' THEN
                    IF NOT EXISTS (SELECT 1 FROM new_rows) THEN RETURN NULL; END IF;
                ELSIF TG_OP = 'DELETE' THEN
                    IF NOT EXISTS (SELECT 1 FROM old_rows) THEN RETURN NULL; END IF;
                END IF;
            END IF;
            UPDATE soldier_roster_revision SET revision = revision + 1 WHERE singleton;
            RETURN NULL;
        END;
        $$
        """
    )
    for table in ("duty_manager_scope", "duty_types"):
        for operation in ("INSERT", "DELETE"):
            transition = "NEW TABLE AS new_rows" if operation == "INSERT" else "OLD TABLE AS old_rows"
            op.execute(
                f"""
                CREATE TRIGGER {table}_roster_{operation.lower()}
                AFTER {operation} ON {table}
                REFERENCING {transition}
                FOR EACH STATEMENT EXECUTE FUNCTION bump_soldier_roster_revision_for_scope_and_duty_type()
                """
            )
        op.execute(
            f"""
            CREATE TRIGGER {table}_roster_update
            AFTER UPDATE ON {table}
            REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
            FOR EACH STATEMENT EXECUTE FUNCTION bump_soldier_roster_revision_on_update()
            """
        )

    # Fairness groups depend on active duty types, eligibility requirements,
    # and dated exemption coverage. Keep one O(1) generation row so a cursor
    # can detect those changes without hashing these source tables per page.
    op.create_table(
        "transparency_fairness_revision",
        sa.Column("singleton", sa.Boolean(), primary_key=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("singleton", name="ck_transparency_fairness_revision_singleton"),
    )
    op.execute(
        "INSERT INTO transparency_fairness_revision (singleton, revision) VALUES (TRUE, 0)"
    )
    op.execute(
        """
        CREATE FUNCTION bump_transparency_fairness_revision() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF TG_TABLE_NAME = 'system_settings' THEN
                    IF NOT EXISTS (
                        SELECT 1 FROM new_rows
                        WHERE key IN (
                            'eligibility.mitvahim_months', 'eligibility.alal_months',
                            'transparency.commander_levels_above',
                            'transparency.duty_manager_levels_above',
                            'transparency.min_visible_level'
                        )
                    ) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'duty_types' THEN
                    IF NOT EXISTS (SELECT 1 FROM new_rows WHERE active) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'exemption_types' THEN
                    IF NOT EXISTS (SELECT 1 FROM new_rows WHERE is_global) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'soldiers' THEN
                    IF NOT EXISTS (SELECT 1 FROM new_rows WHERE left_at IS NULL) THEN RETURN NULL; END IF;
                ELSIF NOT EXISTS (SELECT 1 FROM new_rows) THEN
                    RETURN NULL;
                END IF;
            ELSIF TG_OP = 'DELETE' THEN
                IF TG_TABLE_NAME = 'system_settings' THEN
                    IF NOT EXISTS (
                        SELECT 1 FROM old_rows
                        WHERE key IN (
                            'eligibility.mitvahim_months', 'eligibility.alal_months',
                            'transparency.commander_levels_above',
                            'transparency.duty_manager_levels_above',
                            'transparency.min_visible_level'
                        )
                    ) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'duty_types' THEN
                    IF NOT EXISTS (SELECT 1 FROM old_rows WHERE active) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'exemption_types' THEN
                    IF NOT EXISTS (SELECT 1 FROM old_rows WHERE is_global) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'soldiers' THEN
                    IF NOT EXISTS (SELECT 1 FROM old_rows WHERE left_at IS NULL) THEN RETURN NULL; END IF;
                ELSIF NOT EXISTS (SELECT 1 FROM old_rows) THEN
                    RETURN NULL;
                END IF;
            ELSIF TG_OP = 'UPDATE' THEN
                IF TG_TABLE_NAME = 'system_settings' THEN
                    IF NOT EXISTS (
                        SELECT key, value FROM old_rows
                        WHERE key IN (
                            'eligibility.mitvahim_months', 'eligibility.alal_months',
                            'transparency.commander_levels_above',
                            'transparency.duty_manager_levels_above',
                            'transparency.min_visible_level'
                        )
                        EXCEPT ALL
                        SELECT key, value FROM new_rows
                        WHERE key IN (
                            'eligibility.mitvahim_months', 'eligibility.alal_months',
                            'transparency.commander_levels_above',
                            'transparency.duty_manager_levels_above',
                            'transparency.min_visible_level'
                        )
                    ) AND NOT EXISTS (
                        SELECT key, value FROM new_rows
                        WHERE key IN (
                            'eligibility.mitvahim_months', 'eligibility.alal_months',
                            'transparency.commander_levels_above',
                            'transparency.duty_manager_levels_above',
                            'transparency.min_visible_level'
                        )
                        EXCEPT ALL
                        SELECT key, value FROM old_rows
                        WHERE key IN (
                            'eligibility.mitvahim_months', 'eligibility.alal_months',
                            'transparency.commander_levels_above',
                            'transparency.duty_manager_levels_above',
                            'transparency.min_visible_level'
                        )
                    ) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'duty_types' THEN
                    IF NOT EXISTS (
                        SELECT id, active, requirements FROM old_rows
                        EXCEPT ALL
                        SELECT id, active, requirements FROM new_rows
                    ) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'exemption_types' THEN
                    IF NOT EXISTS (
                        SELECT id, is_global FROM old_rows
                        EXCEPT ALL
                        SELECT id, is_global FROM new_rows
                    ) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'exemption_duty_type_map' THEN
                    IF NOT EXISTS (
                        SELECT exemption_type_id, duty_type_id FROM old_rows
                        EXCEPT ALL
                        SELECT exemption_type_id, duty_type_id FROM new_rows
                    ) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'soldier_exemptions' THEN
                    IF NOT EXISTS (
                        SELECT id, soldier_id, exemption_type_id, start_date, end_date FROM old_rows
                        EXCEPT ALL
                        SELECT id, soldier_id, exemption_type_id, start_date, end_date FROM new_rows
                    ) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'soldiers' THEN
                    IF NOT EXISTS (
                        SELECT id, left_at, gender, is_officer, rank, bahad1_graduate,
                               has_military_driving_license, military_driving_license_expiry,
                               mandatory_end_date, last_mitvahim_date, last_alal_date,
                               hierarchy_node_id
                        FROM old_rows
                        EXCEPT ALL
                        SELECT id, left_at, gender, is_officer, rank, bahad1_graduate,
                               has_military_driving_license, military_driving_license_expiry,
                               mandatory_end_date, last_mitvahim_date, last_alal_date,
                               hierarchy_node_id
                        FROM new_rows
                    ) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'hierarchy_nodes' THEN
                    IF NOT EXISTS (
                        SELECT id, level, parent_id, commander_id, path_ids FROM old_rows
                        EXCEPT ALL
                        SELECT id, level, parent_id, commander_id, path_ids FROM new_rows
                    ) THEN RETURN NULL; END IF;
                ELSIF TG_TABLE_NAME = 'duty_manager_scope' THEN
                    IF NOT EXISTS (
                        SELECT id, duty_manager_id, hierarchy_node_id FROM old_rows
                        EXCEPT ALL
                        SELECT id, duty_manager_id, hierarchy_node_id FROM new_rows
                    ) THEN RETURN NULL; END IF;
                END IF;
            END IF;
            UPDATE transparency_fairness_revision
            SET revision = revision + 1
            WHERE singleton;
            RETURN NULL;
        END;
        $$
        """
    )

    for table in (
        "system_settings",
        "duty_types",
        "exemption_types",
        "exemption_duty_type_map",
        "soldier_exemptions",
        "soldiers",
        "hierarchy_nodes",
        "duty_manager_scope",
    ):
        for operation in ("INSERT", "DELETE"):
            transition = "NEW TABLE AS new_rows" if operation == "INSERT" else "OLD TABLE AS old_rows"
            op.execute(
                f"""
                CREATE TRIGGER {table}_transparency_fairness_{operation.lower()}
                AFTER {operation} ON {table}
                REFERENCING {transition}
                FOR EACH STATEMENT EXECUTE FUNCTION bump_transparency_fairness_revision()
                """
            )
        op.execute(
            f"""
            CREATE TRIGGER {table}_transparency_fairness_update
            AFTER UPDATE ON {table}
            REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
            FOR EACH STATEMENT EXECUTE FUNCTION bump_transparency_fairness_revision()
            """
        )


def downgrade() -> None:
    for table in (
        "system_settings",
        "duty_types",
        "exemption_types",
        "exemption_duty_type_map",
        "soldier_exemptions",
        "soldiers",
        "hierarchy_nodes",
        "duty_manager_scope",
    ):
        for operation in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER {table}_transparency_fairness_{operation} ON {table}")
    op.execute("DROP FUNCTION bump_transparency_fairness_revision()")
    op.drop_table("transparency_fairness_revision")

    for table in ("duty_manager_scope", "duty_types"):
        for operation in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER {table}_roster_{operation} ON {table}")
    op.execute("DROP FUNCTION bump_soldier_roster_revision_for_scope_and_duty_type()")

    # Restore the revision function shape that was active before this migration.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION bump_soldier_roster_revision_on_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'soldiers' THEN
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
        """
    )
