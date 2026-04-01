from pathlib import Path
from datetime import datetime, UTC


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

    r_category_cards = client.get("/erasure/category_cards.js")
    assert r_category_cards.status_code == 200
    assert "application/javascript" in r_category_cards.headers.get("content-type", "")

    r_qa_dashboard = client.get("/qa/qa_dashboard.js")
    assert r_qa_dashboard.status_code == 200
    assert "application/javascript" in r_qa_dashboard.headers.get("content-type", "")

    r_dashboard_switcher = client.get("/core/dashboard_switcher.js")
    assert r_dashboard_switcher.status_code == 200
    assert "application/javascript" in r_dashboard_switcher.headers.get("content-type", "")

    r_auth_ui = client.get("/core/auth_ui.js")
    assert r_auth_ui.status_code == 200
    assert "application/javascript" in r_auth_ui.headers.get("content-type", "")

    r_export_manager = client.get("/core/export_manager.js")
    assert r_export_manager.status_code == 200
    assert "application/javascript" in r_export_manager.headers.get("content-type", "")


def test_admin_activity_requires_admin(client):
    r = client.get("/admin/activity")
    assert r.status_code == 401


def test_admin_activity_returns_recent_events(client, app_module):
    app_module.ACTIVITY_LOG.append(
        {
            "ts": datetime.now(UTC).replace(tzinfo=None).isoformat(),
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
            "ts": datetime.now(UTC).replace(tzinfo=None).isoformat(),
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


def test_admin_initials_list_requires_admin(client):
    r = client.get("/admin/initials-list")
    assert r.status_code == 401


def test_admin_fix_and_undo_initials_flow(client, app_module):
    with app_module.db.sqlite_transaction() as (_, cur):
        cur.execute("DELETE FROM erasures")
        cur.execute("DELETE FROM admin_action_rows")
        cur.execute("DELETE FROM admin_actions")
        cur.execute(
            "INSERT INTO erasures (ts, initials, event, date, month) VALUES (?, ?, ?, ?, ?)",
            ("2026-01-01T00:00:00", "AA", "success", "2026-01-01", "2026-01"),
        )
        cur.execute(
            "INSERT INTO erasures (ts, initials, event, date, month) VALUES (?, ?, ?, ?, ?)",
            ("2026-01-01T00:01:00", "AA", "success", "2026-01-01", "2026-01"),
        )

    fix_resp = client.post(
        "/admin/fix-initials",
        headers={"Authorization": "Bearer test-admin-pass"},
        json={"from": "AA", "to": "BB", "limit": 1},
    )
    assert fix_resp.status_code == 200
    fix_body = fix_resp.json()
    assert fix_body["status"] == "ok"
    assert fix_body["affected_records"] == 1
    assert fix_body["available_records"] == 2

    undo_resp = client.post(
        "/admin/undo-last-initials",
        headers={"Authorization": "Bearer test-admin-pass"},
    )
    assert undo_resp.status_code == 200
    undo_body = undo_resp.json()
    assert undo_body["status"] == "ok"
    assert undo_body["undone"] == 1


def test_admin_delete_event_requires_job_id(client):
    r = client.post("/admin/delete-event", headers={"Authorization": "Bearer test-admin-pass"}, json={})
    assert r.status_code == 400


def test_admin_memory_snapshot_requires_admin(client):
    r = client.post("/admin/memory-snapshot", json={"reason": "test"})
    assert r.status_code == 401


def test_export_excel_requires_manager_or_admin(client):
    r = client.post("/export/excel", json={"sheetsData": {}})
    assert r.status_code == 401


def test_export_qa_stats_rejects_invalid_period_for_manager(client):
    r = client.get("/export/qa-stats?period=not_a_period", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 400


def test_powerbi_endpoints_removed(client):
    r = client.get("/api/powerbi/engineer-stats", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 404


def test_backfill_status_requires_manager_or_admin(client):
    r = client.get("/admin/backfill-status")
    assert r.status_code in (401, 403)


def test_erasure_insights_returns_expected_shape(client, app_module, monkeypatch):
    monkeypatch.setattr(
        app_module.db,
        "get_stats_range",
        lambda *_args, **_kwargs: [{"date": "2026-01-01", "erased": 5}],
    )
    monkeypatch.setattr(
        app_module.db,
        "get_engineer_stats_range",
        lambda *_args, **_kwargs: [{"date": "2026-01-01", "initials": "AA", "count": 5}],
    )
    r = client.get("/api/insights/erasure?period=today", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 200
    body = r.json()
    assert "total" in body
    assert "avgPerDay" in body


def test_qa_trends_endpoint_available(client):
    r = client.get("/api/qa-trends?period=today", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 200
    body = r.json()
    assert "period" in body or "error" in body


def test_qa_dashboard_endpoint_available(client):
    r = client.get("/api/qa-dashboard?period=today", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 200
    body = r.json()
    assert "period" in body or "error" in body


def test_metrics_summary_endpoint_available(client):
    r = client.get("/metrics/summary", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)


def test_analytics_hourly_totals_endpoint_available(client):
    r = client.get("/analytics/hourly-totals", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 200
    body = r.json()
    assert "hours" in body
