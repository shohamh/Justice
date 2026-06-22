from app.main import app
from fastapi.testclient import TestClient
import traceback

client = TestClient(app, raise_server_exceptions=True)
try:
    resp = client.post("/api/auth/login", json={"personal_number": "admin", "password": "test"})
    print("Status:", resp.status_code, resp.text[:200])
except Exception:
    traceback.print_exc()
