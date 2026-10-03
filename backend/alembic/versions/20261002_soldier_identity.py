"""soldier canonical email, ad_username and identity uniqueness

Revision ID: 20261002_soldier_identity
Revises: 4858092e72e7
Create Date: 2026-10-02

Order matters: (1) read-only preflight aborts on any conflict, before any
change; (2) add ``ad_username``; (3) backfill canonical email and derived
username; (4) add CHECKs and unique partial indexes. Nothing is merged,
renamed or arbitrarily selected. Downgrade drops the column, indexes and
checks; canonical email values stay (the original raw text is not recoverable).
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.services.identity import derive_ad_username, normalize_email
from app.services.identity_preflight import IdentityPreflightError, collect_identity_conflicts

revision: str = "20261002_soldier_identity"
down_revision: str | Sequence[str] | None = "4858092e72e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WS = "E' \t\r\n\f\v'"


def upgrade() -> None:
    bind = op.get_bind()

    report = collect_identity_conflicts(bind)
    if report.has_conflicts:
        raise IdentityPreflightError(report)

    op.add_column("soldiers", sa.Column("ad_username", sa.Text(), nullable=True))

    rows = bind.execute(
        sa.text("SELECT id, email FROM soldiers WHERE email IS NOT NULL")
    ).all()
    updates = []
    for soldier_id, raw in rows:
        email = normalize_email(raw)
        username = derive_ad_username(raw)
        if email != raw or username is not None:
            updates.append({"i": soldier_id, "e": email, "a": username})
    if updates:
        bind.execute(
            sa.text("UPDATE soldiers SET email = :e, ad_username = :a WHERE id = :i"),
            updates,
        )

    op.create_check_constraint(
        "ck_soldiers_personal_number_trimmed",
        "soldiers",
        f"personal_number <> '' AND personal_number = btrim(personal_number, {_WS})",
    )
    op.create_check_constraint(
        "ck_soldiers_email_canonical",
        "soldiers",
        f"email IS NULL OR (email <> '' AND email = lower(btrim(email, {_WS})))",
    )
    op.create_check_constraint(
        "ck_soldiers_ad_username_canonical",
        "soldiers",
        f"ad_username IS NULL OR (ad_username <> '' AND ad_username = lower(btrim(ad_username, {_WS})))",
    )
    op.create_index(
        "uq_soldiers_email", "soldiers", ["email"],
        unique=True, postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "uq_soldiers_ad_username", "soldiers", ["ad_username"],
        unique=True, postgresql_where=sa.text("ad_username IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_soldiers_ad_username", table_name="soldiers")
    op.drop_index("uq_soldiers_email", table_name="soldiers")
    op.drop_constraint("ck_soldiers_ad_username_canonical", "soldiers", type_="check")
    op.drop_constraint("ck_soldiers_email_canonical", "soldiers", type_="check")
    op.drop_constraint("ck_soldiers_personal_number_trimmed", "soldiers", type_="check")
    op.drop_column("soldiers", "ad_username")
