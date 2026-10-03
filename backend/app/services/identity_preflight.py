"""Read-only diagnostics for soldier identity data.

The soldier identity migration enforces unique canonical ``email``, derived
``ad_username`` and trimmed non-blank ``personal_number``. Before it changes
anything it calls :func:`collect_identity_conflicts`; any conflict aborts the
migration with :class:`IdentityPreflightError`. Operators resolve conflicts by
hand (this module never merges, renames or selects a soldier) and re-run.

Reports identify soldiers by id and conflict kind only. Email addresses are not
echoed; the id is enough to find the row.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.services.identity import derive_ad_username, normalize_email

#: Characters treated as whitespace by both Python code and the database CHECK
#: on ``personal_number`` (``btrim(personal_number, E' \t\r\n\f\v')``).
PERSONAL_NUMBER_WHITESPACE = " \t\r\n\f\v"

_EMAIL_ERROR_KINDS = {
    "email_invalid": "invalid_email",
    "ad_username_too_long": "ad_username_too_long",
    "ad_username_invalid": "ad_username_invalid",
}


@dataclass(frozen=True)
class IdentityConflict:
    """One conflict: ``kind`` plus the ids of every soldier involved."""

    kind: str
    soldier_ids: tuple[Any, ...]

    def render(self) -> str:
        ids = ", ".join(str(i) for i in self.soldier_ids)
        return f"{self.kind}: soldier ids [{ids}]"


@dataclass
class IdentityPreflightReport:
    conflicts: list[IdentityConflict] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    def render(self) -> str:
        """Human-readable report, one line per conflict; ``""`` when clean."""
        return "\n".join(conflict.render() for conflict in self.conflicts)


class IdentityPreflightError(RuntimeError):
    """Raised by the migration when existing data would violate the new rules."""

    def __init__(self, report: IdentityPreflightReport) -> None:
        self.report = report
        super().__init__(
            "Soldier identity preflight found conflicts. Nothing was changed. "
            "Fix these soldiers by hand (no automatic merge or rename), then re-run:\n"
            + report.render()
        )


def _sorted_ids(ids) -> tuple[Any, ...]:
    return tuple(sorted(ids, key=str))


def collect_identity_conflicts(connection) -> IdentityPreflightReport:
    """Scan ``soldiers`` and report everything the new constraints would reject.

    Kinds: ``invalid_email``, ``ad_username_too_long``, ``ad_username_invalid``,
    ``duplicate_email`` (same normalized email), ``duplicate_ad_username``
    (same derived username from different normalized emails),
    ``blank_personal_number``, ``untrimmed_personal_number`` and
    ``duplicate_personal_number`` (equal after trimming). Blank or NULL email is
    never a conflict. ``email_verified`` is ignored. Never writes.
    """
    rows = connection.execute(
        text("SELECT id, personal_number, email FROM soldiers")
    ).all()
    conflicts: list[IdentityConflict] = []

    by_email: dict[str, list[Any]] = defaultdict(list)
    by_username: dict[str, list[Any]] = defaultdict(list)
    emails_by_username: dict[str, set[str]] = defaultdict(set)
    by_trimmed_number: dict[str, list[Any]] = defaultdict(list)

    for soldier_id, personal_number, raw_email in rows:
        trimmed_number = personal_number.strip(PERSONAL_NUMBER_WHITESPACE)
        if not trimmed_number:
            conflicts.append(IdentityConflict("blank_personal_number", (soldier_id,)))
        else:
            by_trimmed_number[trimmed_number].append(soldier_id)
            if trimmed_number != personal_number:
                conflicts.append(IdentityConflict("untrimmed_personal_number", (soldier_id,)))

        try:
            email = normalize_email(raw_email)
            username = derive_ad_username(raw_email)
        except ValueError as exc:
            kind = _EMAIL_ERROR_KINDS.get(str(exc), "invalid_email")
            conflicts.append(IdentityConflict(kind, (soldier_id,)))
            continue
        if email is None or username is None:
            continue
        by_email[email].append(soldier_id)
        by_username[username].append(soldier_id)
        emails_by_username[username].add(email)

    for ids in by_email.values():
        if len(ids) > 1:
            conflicts.append(IdentityConflict("duplicate_email", _sorted_ids(ids)))
    for username, ids in by_username.items():
        if len(emails_by_username[username]) > 1:
            conflicts.append(IdentityConflict("duplicate_ad_username", _sorted_ids(ids)))
    for ids in by_trimmed_number.values():
        if len(ids) > 1:
            conflicts.append(IdentityConflict("duplicate_personal_number", _sorted_ids(ids)))

    return IdentityPreflightReport(conflicts)
