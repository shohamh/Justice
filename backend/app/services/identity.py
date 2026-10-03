"""Canonical email and legacy AD sAMAccountName derivation for soldiers."""

from __future__ import annotations

import re


_EMAIL_LOCAL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", re.ASCII)
_DOMAIN_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", re.ASCII)
_SAM_FORBIDDEN = frozenset('"/\\[]:;|=,+*?<>')
_SAM_MAX_LENGTH = 20


def _canonical_identity(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None

    trimmed = value.strip()
    if not trimmed:
        return None, None
    if not trimmed.isascii():
        raise ValueError("email_invalid")

    email = trimmed.lower()
    if email.count("@") != 1:
        raise ValueError("email_invalid")
    local, domain = email.split("@")
    labels = domain.split(".")
    if (
        not local
        or len(local) > 64
        or not _EMAIL_LOCAL.fullmatch(local)
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or len(domain) > 253
        or len(labels) < 2
        or any(not _DOMAIN_LABEL.fullmatch(label) for label in labels)
    ):
        raise ValueError("email_invalid")
    if len(local) > _SAM_MAX_LENGTH:
        raise ValueError("ad_username_too_long")
    if any(character in _SAM_FORBIDDEN for character in local):
        raise ValueError("ad_username_invalid")
    return email, local


def normalize_email(value: str | None) -> str | None:
    """Trim and lowercase an address that can produce a supported AD name."""
    return _canonical_identity(value)[0]


def derive_ad_username(email: str | None) -> str | None:
    """Return the lowercased email local part without dropping punctuation."""
    return _canonical_identity(email)[1]


def canonical_identity(value: str | None) -> tuple[str | None, str | None]:
    """Return ``(normalized_email, ad_username)`` through one validation pass.

    Both are ``None`` for a blank value. Raises ``ValueError`` with one of the
    codes ``email_invalid``, ``ad_username_too_long`` or ``ad_username_invalid``.
    Write paths store the two values together; never store one without the other.
    """
    return _canonical_identity(value)


class IdentityCollisionError(ValueError):
    """A write would duplicate a unique soldier identity value.

    ``field`` is ``"email"``, ``"ad_username"`` or ``"personal_number"`` and names
    only the colliding field, never the other soldier. ``str(error)`` is the
    stable code ``"<field>_taken"``. Raised by the application-level pre-check
    and, for races, translated from the database unique-constraint error.
    """

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field}_taken")
