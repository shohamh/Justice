"""Use a sequence plus xid journal to track transparency source mutations.

Revision ID: 20261004_src_gen
Revises: 825b49ff9b2c
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261004_src_gen"
down_revision: str | Sequence[str] | None = "825b49ff9b2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SOURCE_TABLES = (
    "soldiers",
    "duty_assignments",
    "duty_day_overrides",
    "duty_dismissals",
    "score_adjustments",
    "duty_types",
    "soldier_exemptions",
    "exemption_types",
    "exemption_duty_type_map",
    "hierarchy_nodes",
    "hierarchy_level_types",
    "duty_manager_scope",
    "role_deputies",
    "system_settings",
)


def upgrade() -> None:
    # Remove the old selected-field singleton revision. Its row UPDATE serialized
    # otherwise-independent source writers and participated in projection-lock
    # deadlocks. The sequence below has no row lock and intentionally is not
    # transactional: rollback can conservatively invalidate a transparency cursor.
    # The xid journal is transactional and lets a cursor detect a source writer
    # that had advanced the sequence but committed after that cursor's snapshot.
    # Rows remain unpruned until cursor snapshots can be registered server-side;
    # pruning by insert time alone is unsafe for long-running source transactions.
    op.execute(
        """
        DO $$
        DECLARE old_trigger record;
        BEGIN
            FOR old_trigger IN
                SELECT namespace.nspname, relation.relname, trigger.tgname
                FROM pg_trigger AS trigger
                JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE NOT trigger.tgisinternal
                  AND trigger.tgfoid = to_regprocedure(
                      'bump_transparency_fairness_revision()'
                  )
            LOOP
                EXECUTE format(
                    'DROP TRIGGER %I ON %I.%I',
                    old_trigger.tgname,
                    old_trigger.nspname,
                    old_trigger.relname
                );
            END LOOP;
        END;
        $$;
        """
    )
    op.execute("DROP FUNCTION IF EXISTS bump_transparency_fairness_revision()")
    op.drop_table("transparency_fairness_revision")

    op.execute(
        """
        CREATE SEQUENCE transparency_source_generation_seq
            AS BIGINT
            START WITH 1
            INCREMENT BY 1
            CACHE 1
        """
    )
    op.execute(
        """
        CREATE TABLE transparency_source_change_journal (
            transaction_id xid8 PRIMARY KEY
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION bump_transparency_source_generation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM nextval('transparency_source_generation_seq'::regclass);
            INSERT INTO transparency_source_change_journal (transaction_id)
            VALUES (pg_current_xact_id())
            ON CONFLICT (transaction_id) DO NOTHING;
            RETURN NULL;
        END;
        $$
        """
    )

    for table in _SOURCE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_transparency_source_dml
            AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION bump_transparency_source_generation()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_transparency_source_truncate
            AFTER TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION bump_transparency_source_generation()
            """
        )


def downgrade() -> None:
    for table in _SOURCE_TABLES:
        op.execute(f"DROP TRIGGER {table}_transparency_source_dml ON {table}")
        op.execute(f"DROP TRIGGER {table}_transparency_source_truncate ON {table}")
    op.execute("DROP FUNCTION bump_transparency_source_generation()")
    op.execute("DROP TABLE transparency_source_change_journal")
    op.execute("DROP SEQUENCE transparency_source_generation_seq")

    # Restore the table expected by the prior route. A broad statement trigger
    # keeps downgraded cursors conservative for the same canonical inputs.
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
            UPDATE transparency_fairness_revision
            SET revision = revision + 1
            WHERE singleton;
            RETURN NULL;
        END;
        $$
        """
    )
    for table in _SOURCE_TABLES:
        for operation in ("INSERT OR UPDATE OR DELETE", "TRUNCATE"):
            suffix = "dml" if operation != "TRUNCATE" else "truncate"
            op.execute(
                f"""
                CREATE TRIGGER {table}_transparency_fairness_{suffix}
                AFTER {operation} ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION bump_transparency_fairness_revision()
                """
            )
