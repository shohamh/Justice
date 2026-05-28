"""First-boot script: create the initial admin from env vars, then refuse to run again.

Idempotent: if any soldier with role='admin' already exists, this script exits with
code 0 and prints a no-op message. Otherwise it inserts one admin row using
BOOTSTRAP_ADMIN_PERSONAL_NUMBER / BOOTSTRAP_ADMIN_FULL_NAME / BOOTSTRAP_ADMIN_PASSWORD.

Set must_change_password=True so the soldier is forced to set a new password on
first login.
"""
from __future__ import annotations

import sys

from sqlalchemy import select

from app.auth.password import hash_password
from app.db.models import Soldier
from app.db.session import session_scope
from app.settings import get_settings


def main() -> int:
    settings = get_settings()
    pn = settings.bootstrap_admin_personal_number
    fn = settings.bootstrap_admin_full_name
    pw = settings.bootstrap_admin_password
    if not (pn and fn and pw):
        print("bootstrap: BOOTSTRAP_ADMIN_* env vars not all set; skipping.")
        return 0

    with session_scope() as session:
        existing = session.execute(select(Soldier).where(Soldier.role == "admin").limit(1)).scalar_one_or_none()
        if existing is not None:
            print("bootstrap: an admin already exists; skipping.")
            return 0
        admin = Soldier(
            personal_number=pn,
            full_name=fn,
            password_hash=hash_password(pw),
            role="admin",
            must_change_password=True,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        print(f"bootstrap: created admin id={admin.id} personal_number={pn}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
