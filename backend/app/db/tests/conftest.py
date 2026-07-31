import sys
import os

# Ensure the backend directory is on the path so `app` can be imported
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Re-export fixtures from the root test conftest so that tests in this
# subdirectory can use app_session, admin_session, client, etc.
pytest_plugins = ["tests.conftest"]
