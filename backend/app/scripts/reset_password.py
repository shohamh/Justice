"""Reset a soldier's password by personal number.

Usage: uv run python -m app.scripts.reset_password <personal_number> [<password>]

If password is omitted, a random one is generated and printed to stdout.
Sets must_change_password=True so the soldier is forced to set a new password
on next login.
"""

from __future__ import annotations

import secrets
import string
import sys

from sqlalchemy import select

from app.auth.password import hash_password
from app.db.models import Soldier
from app.db.session import session_scope


def main() -> int:
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <personal_number> [<password>]", file=sys.stderr)
        return 1

    pn = sys.argv[1]
    if len(sys.argv) >= 3:
        pw = sys.argv[2]
    else:
        pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))

    with session_scope() as session:
        soldier = session.execute(
            select(Soldier).where(Soldier.personal_number == pn)
        ).scalar_one_or_none()

        if soldier is None:
            print(f"error: no soldier found with personal_number={pn}", file=sys.stderr)
            return 1

        soldier.password_hash = hash_password(pw)
        soldier.must_change_password = True
        session.commit()
        print(f"reset password for {soldier.full_name} ({soldier.personal_number})")
        print(f"new password: {pw}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
