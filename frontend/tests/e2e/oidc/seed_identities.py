"""Give two seeded soldiers e-mail identities for the OIDC browser journeys.

Run from backend/ after `python -m app.scripts.seed` against the disposable e2e
database (DATABASE_URL must point at it). Synthetic example.test data only.
"""
from sqlalchemy import select

from app.db.models import Soldier
from app.db.session import SessionLocal
from app.services.identity_write import assign_soldier_email

ASSIGNMENTS = {
    "1000003": "sso.existing@example.test",  # matches Keycloak user sso.existing
    "1000004": "sso.ambig@corp.example.test",  # same AD username as sso.ambig, other domain
}

with SessionLocal() as session:
    for personal_number, email in ASSIGNMENTS.items():
        soldier = session.execute(
            select(Soldier).where(Soldier.personal_number == personal_number)
        ).scalar_one()
        assign_soldier_email(session, soldier, email, verified=True)
    session.commit()
print("seeded", len(ASSIGNMENTS), "identities")
