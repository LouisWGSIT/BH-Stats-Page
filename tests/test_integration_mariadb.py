import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_health_db_with_real_mariadb(mariadb_creds_present):
    if not mariadb_creds_present:
        pytest.skip("MariaDB credentials not set in environment")

    import main

    client = TestClient(main.app)
    r = client.get("/health/db", headers={"Authorization": f"Bearer {main.ADMIN_PASSWORD}"})
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}
