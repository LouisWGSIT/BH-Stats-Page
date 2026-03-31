from pathlib import Path


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
