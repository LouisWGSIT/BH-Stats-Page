import importlib
import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _load_main_with_test_env(tmp_db: Path):
    os.environ["STATS_DB_PATH"] = str(tmp_db)
    os.environ["INGESTION_KEY"] = "test-ingestion-key"
    os.environ["WEBHOOK_API_KEY"] = "test-webhook-key"
    os.environ["DASHBOARD_ADMIN_PASSWORD"] = "test-admin-pass"
    os.environ["DASHBOARD_MANAGER_PASSWORD"] = "test-manager-pass"

    if "database" in sys.modules:
        del sys.modules["database"]
    if "main" in sys.modules:
        del sys.modules["main"]

    import database as database_mod

    database_mod.DB_PATH = str(tmp_db)
    import main as main_mod

    return importlib.reload(main_mod)


@pytest.fixture()
def workspace_temp_dir():
    root = Path.cwd() / "outputs" / "pytest-runtime"
    root.mkdir(parents=True, exist_ok=True)
    yield root


@pytest.fixture()
def app_module(workspace_temp_dir):
    tmp_db = workspace_temp_dir / f"app_test_{uuid.uuid4().hex}.db"
    return _load_main_with_test_env(tmp_db)


@pytest.fixture()
def client(app_module):
    return TestClient(app_module.app)


@pytest.fixture()
def mariadb_creds_present():
    keys = ["MARIADB_HOST", "MARIADB_USER", "MARIADB_PASSWORD", "MARIADB_DB"]
    return all(bool(os.getenv(k)) for k in keys)
