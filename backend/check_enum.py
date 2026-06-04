from app.db.session import _engine
from sqlalchemy import text

result = [r[0] for r in _engine.connect().execute(text("SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_type.oid=enumtypid WHERE pg_type.typname IN ('notificationtype','notification_type') ORDER BY enumsortorder")).fetchall()]
print(result)
