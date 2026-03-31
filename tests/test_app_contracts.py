from pathlib import Path
from datetime import datetime


def test_health_liveness(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_db_returns_503_when_connection_unavailable(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module.health_router.qa_export, "get_mariadb_connection", lambda: None)
    r = client.get("/health/db")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "fail"


def test_health_db_returns_200_when_query_succeeds(client, app_module, monkeypatch):
    class _Cursor:
        def execute(self, _q):
            return None

        def fetchone(self):
            return (1,)

        def close(self):
            return None

    class _Conn:
        def cursor(self):
            return _Cursor()

        def close(self):
            return None

    monkeypatch.setattr(app_module.health_router.qa_export, "get_mariadb_connection", lambda: _Conn())
    r = client.get("/health/db")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}


def test_admin_devices_requires_admin(client):
    r = client.get("/admin/connected-devices")
    assert r.status_code == 401


def test_admin_devices_with_admin_token(client):
    r = client.get("/admin/connected-devices", headers={"Authorization": "Bearer test-admin-pass"})
    assert r.status_code == 200
    body = r.json()
    assert "devices" in body
    assert isinstance(body["devices"], list)


def test_hwid_requires_api_key(client):
    r = client.post("/hwid", json={"hashid": "abc"})
    assert r.status_code == 401


def test_hwid_accepts_key_and_writes_log(client, app_module, workspace_temp_dir, monkeypatch):
    log_path = workspace_temp_dir / "hwid_log.jsonl"
    monkeypatch.setattr(app_module, "HWID_LOG_PATH", str(log_path))
    monkeypatch.setattr(app_module, "WEBHOOK_API_KEY", "test-webhook-key")

    r = client.post(
        "/hwid",
        headers={"x-api-key": "test-webhook-key"},
        json={"hashid": "abc123", "serial": "SER-1"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert Path(log_path).exists()


def test_auth_login_admin_returns_admin_role(client, app_module, workspace_temp_dir, monkeypatch):
    tokens_path = workspace_temp_dir / "device_tokens_test.json"
    monkeypatch.setattr(app_module, "DEVICE_TOKENS_FILE", str(tokens_path))

    r = client.post("/auth/login", json={"password": "test-admin-pass"})
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["role"] == "admin"
    assert "device_token" in body


def test_auth_status_with_manager_bearer(client):
    r = client.get("/auth/status", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["role"] == "manager"


def test_static_routes_still_serve_assets(client):
    r_index = client.get("/")
    assert r_index.status_code == 200
    assert "text/html" in r_index.headers.get("content-type", "")

    r_config = client.get("/config.json")
    assert r_config.status_code == 200
    assert "application/json" in r_config.headers.get("content-type", "")


def test_admin_activity_requires_admin(client):
    r = client.get("/admin/activity")
    assert r.status_code == 401


def test_admin_activity_returns_recent_events(client, app_module):
    app_module.ACTIVITY_LOG.append(
        {
            "ts": datetime.utcnow().isoformat(),
            "path": "/hooks/erasure-detail",
            "method": "POST",
            "client_ip": "127.0.0.1",
            "duration_ms": 12,
            "rss": 123456,
        }
    )
    r = client.get("/admin/activity", headers={"Authorization": "Bearer test-admin-pass"})
    assert r.status_code == 200
    body = r.json()
    assert "counts" in body
    assert "recent" in body
    assert isinstance(body["recent"], list)


def test_admin_activity_memory_series_shape(client, app_module):
    app_module.ACTIVITY_LOG.append(
        {
            "ts": datetime.utcnow().isoformat(),
            "path": "/app.js",
            "method": "GET",
            "client_ip": "127.0.0.1",
            "rss": 222222,
        }
    )
    r = client.get(
        "/admin/activity/memory-series?minutes=10&bucket_seconds=60",
        headers={"Authorization": "Bearer test-admin-pass"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "series" in body
    assert body["bucket_seconds"] == 60


def test_admin_last_error_requires_admin(client):
    r = client.get("/admin/last-error")
    assert r.status_code == 401


def test_admin_revoke_device_round_trip(client, app_module, workspace_temp_dir, monkeypatch):
    tokens_path = workspace_temp_dir / "device_tokens_roundtrip.json"
    monkeypatch.setattr(app_module, "DEVICE_TOKENS_FILE", str(tokens_path))

    app_module.save_device_tokens(
        {
            "tok-1": {
                "expiry": "2099-01-01T00:00:00",
                "role": "viewer",
                "user_agent": "pytest",
            }
        }
    )

    r = client.post(
        "/admin/revoke-device",
        headers={"Authorization": "Bearer test-admin-pass"},
        json={"token": "tok-1"},
    )
    assert r.status_code == 200
    assert r.json()["revoked"] is True

    tokens = app_module.load_device_tokens()
    assert "tok-1" not in tokens


def test_admin_db_processlist_handles_db_unavailable(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module.qa_export, "get_mariadb_connection", lambda: None)
    r = client.get("/admin/db-processlist", headers={"Authorization": "Bearer test-admin-pass"})
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "fail"
