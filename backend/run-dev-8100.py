import os

os.environ["DATABASE_URL"] = "postgresql+psycopg://app:app_pw@localhost:5432/justice"
os.environ["DB_ADMIN_URL"] = "postgresql+psycopg://db_admin:db_admin_pw@localhost:5432/justice"

import uvicorn

uvicorn.run("app.main:app", host="0.0.0.0", port=8100)
