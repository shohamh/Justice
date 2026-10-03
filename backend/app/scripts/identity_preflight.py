"""Operator command: report soldier identity conflicts without changing data.

Run before upgrading to the soldier-identity migration:

    python -m app.scripts.identity_preflight

Exit status is 0 when clean and 1 when conflicts exist. It only reads, and it
is never invoked implicitly by deployment tooling.
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine

from app.services.identity_preflight import collect_identity_conflicts
from app.settings import get_settings


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.db_admin_url)
    try:
        with engine.connect() as conn:
            report = collect_identity_conflicts(conn)
    finally:
        engine.dispose()
    if not report.has_conflicts:
        print("identity preflight: no conflicts.")
        return 0
    print(report.render())
    return 1


if __name__ == "__main__":
    sys.exit(main())
