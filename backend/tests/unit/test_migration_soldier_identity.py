"""Soldier identity migration: preflight diagnostics, backfill and constraints."""

from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.services.identity_preflight import (
    IdentityPreflightError,
    collect_identity_conflicts,
)
from tests.support import database as db_support

pytestmark = pytest.mark.slow

DOWN_REVISION = "4858092e72e7"
REVISION = "20261002_soldier_identity"
_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = None


@contextmanager
def _db():
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = db_support.get_migrated_template(DOWN_REVISION, _ROOT)
    with db_support.cloned_migration_database(
        _TEMPLATE, upgrade_to_revision=REVISION, rootpath=_ROOT
    ) as (engine, run_migration):
        yield engine, run_migration


def _add(conn, personal_number, email=None):
    return conn.execute(
        text(
            "INSERT INTO soldiers (personal_number, full_name, password_hash, email) "
            "VALUES (:pn, 'n', 'x', :email) RETURNING id"
        ),
        {"pn": personal_number, "email": email},
    ).scalar_one()


def _kinds(report):
    return {(c.kind, frozenset(c.soldier_ids)) for c in report.conflicts}


def _has_ad_username_column(engine):
    with engine.begin() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'soldiers' AND column_name = 'ad_username'"
                )
            ).first()
        )


def test_preflight_reports_duplicate_normalized_emails_without_changing_data():
    with _db() as (engine, _run):
        with engine.begin() as conn:
            a = _add(conn, "1000001", "Dude@Gmail.com")
            b = _add(conn, "1000002", " dude@gmail.com ")
            _add(conn, "1000003", "other@example.com")
        with engine.begin() as conn:
            report = collect_identity_conflicts(conn)
            rows = conn.execute(
                text("SELECT email FROM soldiers ORDER BY personal_number")
            ).scalars().all()
        assert ("duplicate_email", frozenset({a, b})) in _kinds(report)
        assert rows == ["Dude@Gmail.com", " dude@gmail.com ", "other@example.com"]
        assert report.has_conflicts


def test_preflight_reports_duplicate_ad_username_from_different_domains():
    with _db() as (engine, _run):
        with engine.begin() as conn:
            a = _add(conn, "1000001", "dude@gmail.com")
            b = _add(conn, "1000002", "DUDE@corp.example")
        with engine.begin() as conn:
            report = collect_identity_conflicts(conn)
        kinds = _kinds(report)
        assert ("duplicate_ad_username", frozenset({a, b})) in kinds
        assert not any(kind == "duplicate_email" for kind, _ in kinds)


def test_preflight_reports_malformed_emails_and_unsupported_usernames():
    with _db() as (engine, _run):
        with engine.begin() as conn:
            bad = _add(conn, "1000001", "not-an-email")
            long_name = _add(conn, "1000002", "a" * 21 + "@example.com")
            plus = _add(conn, "1000003", "a+tag@example.com")
        with engine.begin() as conn:
            report = collect_identity_conflicts(conn)
        by_id = {tuple(c.soldier_ids): c.kind for c in report.conflicts}
        assert by_id[(bad,)] == "invalid_email"
        assert by_id[(long_name,)] == "ad_username_too_long"
        assert by_id[(plus,)] == "ad_username_invalid"
        # the report never echoes addresses
        assert "not-an-email" not in report.render()
        assert "example.com" not in report.render()


def test_preflight_reports_blank_untrimmed_and_colliding_personal_numbers():
    with _db() as (engine, _run):
        with engine.begin() as conn:
            blank = _add(conn, "   ")
            padded = _add(conn, " 2000001")
            plain = _add(conn, "2000001")
            padded_alone = _add(conn, "2000002 ")
        with engine.begin() as conn:
            report = collect_identity_conflicts(conn)
        kinds = _kinds(report)
        assert ("blank_personal_number", frozenset({blank})) in kinds
        assert ("duplicate_personal_number", frozenset({padded, plain})) in kinds
        assert ("untrimmed_personal_number", frozenset({padded})) in kinds
        assert ("untrimmed_personal_number", frozenset({padded_alone})) in kinds


def test_preflight_is_clean_for_blank_null_and_valid_rows():
    with _db() as (engine, _run):
        with engine.begin() as conn:
            _add(conn, "1000001", None)
            _add(conn, "1000002", "   ")
            _add(conn, "1000003", "First.Last@Example.com")
        with engine.begin() as conn:
            report = collect_identity_conflicts(conn)
        assert not report.has_conflicts
        assert report.render() == ""


def test_upgrade_aborts_on_conflicts_before_any_change():
    with _db() as (engine, run_migration):
        with engine.begin() as conn:
            _add(conn, "1000001", "Dude@Gmail.com")
            _add(conn, "1000002", "dude@gmail.com")
        with pytest.raises(IdentityPreflightError) as excinfo:
            run_migration()
        assert "duplicate_email" in str(excinfo.value)
        assert not _has_ad_username_column(engine)
        with engine.begin() as conn:
            emails = conn.execute(
                text("SELECT email FROM soldiers ORDER BY personal_number")
            ).scalars().all()
        assert emails == ["Dude@Gmail.com", "dude@gmail.com"]


def test_upgrade_backfills_and_enforces_constraints_and_downgrade_restores():
    with _db() as (engine, run_migration):
        with engine.begin() as conn:
            _add(conn, "1000001", " First.Last@Example.COM ")
            _add(conn, "1000002", "   ")
            _add(conn, "1000003", None)
            verified = _add(conn, "1000004", "ok@example.com")
            conn.execute(
                text("UPDATE soldiers SET email_verified = true WHERE id = :i"), {"i": verified}
            )
        run_migration()
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT personal_number, email, ad_username, email_verified "
                    "FROM soldiers ORDER BY personal_number"
                )
            ).all()
        assert rows == [
            ("1000001", "first.last@example.com", "first.last", False),
            ("1000002", None, None, False),
            ("1000003", None, None, False),
            ("1000004", "ok@example.com", "ok", True),
        ]

        def insert(pn, email, ad):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO soldiers "
                        "(personal_number, full_name, password_hash, email, ad_username) "
                        "VALUES (:pn, 'n', 'x', :e, :a)"
                    ),
                    {"pn": pn, "e": email, "a": ad},
                )

        with pytest.raises(IntegrityError):  # same email (verified or not)
            insert("1000009", "ok@example.com", "different")
        with pytest.raises(IntegrityError):  # same ad_username, other domain
            insert("1000009", "ok@other.example", "ok")
        with pytest.raises(IntegrityError):  # non-canonical email
            insert("1000009", "Mixed@example.com", "mixed")
        with pytest.raises(IntegrityError):  # non-canonical ad_username
            insert("1000009", "mixed@example.com", "Mixed")
        with pytest.raises(IntegrityError):  # duplicate personal number
            insert("1000001", None, None)
        with pytest.raises(IntegrityError):  # padded personal number
            insert("1000009 ", None, None)
        with pytest.raises(IntegrityError):  # blank personal number
            insert("  ", None, None)
        insert("1000010", None, None)  # NULLs never collide
        insert("1000011", None, None)

        from alembic.config import Config

        from alembic import command

        cfg = Config(str(_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(_ROOT / "alembic"))
        command.downgrade(cfg, DOWN_REVISION)
        assert not _has_ad_username_column(engine)
        with engine.begin() as conn:
            emails = conn.execute(
                text("SELECT email FROM soldiers WHERE personal_number = '1000001'")
            ).scalars().all()
        # canonical values are kept: the original raw text is not recoverable
        assert emails == ["first.last@example.com"]
