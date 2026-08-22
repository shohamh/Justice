"""Helpers for binding large id collections efficiently.

A ``column.in_(values)`` with tens of thousands of uuids produces a statement
with one bind parameter per value; PostgreSQL spends multiple seconds just
parsing and planning such statements. Passing a single array parameter and
matching with ``= ANY(..)`` is equivalent and stays fast.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from typing import Any

from sqlalchemy import text


def _any_clause(column_sql: str, values: Collection[str], pg_type: str) -> Any:
    if not values:
        return text("false")
    param = f"{column_sql.replace('.', '_')}_ids"
    return text(f"{column_sql} = ANY(CAST(:{param} AS {pg_type}))").bindparams(
        **{param: sorted(values)}
    )


def uuid_any(column_sql: str, values: Collection[uuid.UUID]) -> Any:
    """Match ``column_sql`` against a set of uuids via a single array parameter."""
    return _any_clause(column_sql, (str(v) for v in values), "uuid[]")


def date_any(column_sql: str, values: Collection[Any]) -> Any:
    """Match ``column_sql`` against a set of dates via a single array parameter."""
    return _any_clause(column_sql, (str(v) for v in values), "date[]")
