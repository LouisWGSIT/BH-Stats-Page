from pathlib import Path
from datetime import datetime, UTC
from datetime import date


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


def test_auth_status_external_tv_user_agent_not_auto_authenticated(client):
    r = client.get(
        "/auth/status",
        headers={
            "X-Forwarded-For": "82.163.130.162",
            "User-Agent": "Mozilla/5.0 (Linux; Android 9; AFTSS) AppleWebKit/537.36 (KHTML, like Gecko) Silk/138.13.4",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is False
    assert body["role"] is None
    assert body["access_type"] == "external"


def test_external_tv_user_agent_without_token_cannot_read_metrics(client):
    r = client.get(
        "/metrics/summary",
        headers={
            "X-Forwarded-For": "82.163.130.162",
            "User-Agent": "Mozilla/5.0 (Linux; Android 9; AFTSS) AppleWebKit/537.36 (KHTML, like Gecko) Silk/138.13.4",
        },
    )
    assert r.status_code == 401


def test_external_tv_user_agent_with_saved_viewer_token_can_refresh(client, app_module):
    token = "tv-saved-token"
    app_module.save_device_tokens(
        {
            token: {
                "expiry": "2099-01-01T00:00:00",
                "role": "viewer",
                "user_agent": "silk",
                "client_ip": "82.163.130.162",
            }
        }
    )

    r = client.get(
        "/metrics/summary",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Forwarded-For": "82.163.130.162",
            "User-Agent": "Mozilla/5.0 (Linux; Android 9; AFTSS) AppleWebKit/537.36 (KHTML, like Gecko) Silk/138.13.4",
        },
    )
    assert r.status_code == 200


def test_legacy_locked_field_does_not_block_token_auth(client, app_module):
    token = "tv-legacy-locked-token"
    app_module.save_device_tokens(
        {
            token: {
                "expiry": "2099-01-01T00:00:00",
                "role": "viewer",
                "locked": True,
                "user_agent": "silk",
                "client_ip": "82.163.130.162",
            }
        }
    )

    r = client.get(
        "/metrics/summary",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Forwarded-For": "82.163.130.162",
            "User-Agent": "Mozilla/5.0 (Linux; Android 9; AFTSS) AppleWebKit/537.36 (KHTML, like Gecko) Silk/138.13.4",
        },
    )
    assert r.status_code == 200


def test_admin_lock_device_route_removed(client):
    r = client.post(
        "/admin/lock-device",
        headers={"Authorization": "Bearer test-admin-pass"},
        json={"token": "abc", "lock": True},
    )
    assert r.status_code in (404, 405)


def test_ephemeral_viewer_token_rejected_for_external_ip(client):
    r = client.post(
        "/auth/ephemeral-viewer",
        headers={"X-Forwarded-For": "82.163.130.162"},
        json={"name": "TV"},
    )
    assert r.status_code == 403


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

    r_qa_adapter = client.get("/core/qa_adapter.js")
    assert r_qa_adapter.status_code == 200
    assert "application/javascript" in r_qa_adapter.headers.get("content-type", "")

    r_display_keepalive = client.get("/core/display_keepalive.js")
    assert r_display_keepalive.status_code == 200
    assert "application/javascript" in r_display_keepalive.headers.get("content-type", "")

    r_adaptive_poll = client.get("/core/adaptive_poll.js")
    assert r_adaptive_poll.status_code == 200
    assert "application/javascript" in r_adaptive_poll.headers.get("content-type", "")

    r_aggregated_refresh = client.get("/core/aggregated_refresh.js")
    assert r_aggregated_refresh.status_code == 200
    assert "application/javascript" in r_aggregated_refresh.headers.get("content-type", "")

    r_flip_cards_updater = client.get("/core/flip_cards_updater.js")
    assert r_flip_cards_updater.status_code == 200
    assert "application/javascript" in r_flip_cards_updater.headers.get("content-type", "")

    r_analytics_charts = client.get("/core/analytics_charts.js")
    assert r_analytics_charts.status_code == 200
    assert "application/javascript" in r_analytics_charts.headers.get("content-type", "")

    r_monthly_momentum_chart = client.get("/core/monthly_momentum_chart.js")
    assert r_monthly_momentum_chart.status_code == 200
    assert "window.MonthlyMomentumChart" in r_monthly_momentum_chart.text

    r_competition_announcements = client.get("/core/competition_announcements.js")
    assert r_competition_announcements.status_code == 200
    assert "window.CompetitionAnnouncements" in r_competition_announcements.text

    r_all_time_totals = client.get("/core/all_time_totals.js")
    assert r_all_time_totals.status_code == 200
    assert "window.AllTimeTotals" in r_all_time_totals.text

    r_race_leaderboard = client.get("/core/race_leaderboard.js")
    assert r_race_leaderboard.status_code == 200
    assert "window.RaceLeaderboard" in r_race_leaderboard.text

    r_overall_stats_dashboard = client.get("/core/overall_stats_dashboard.js")
    assert r_overall_stats_dashboard.status_code == 200
    assert "window.OverallStatsDashboard" in r_overall_stats_dashboard.text

    r_qa_trend_panel = client.get("/core/qa_trend_panel.js")
    assert r_qa_trend_panel.status_code == 200
    assert "window.QATrendPanel" in r_qa_trend_panel.text

    r_qa_metrics_rotator = client.get("/core/qa_metrics_rotator.js")
    assert r_qa_metrics_rotator.status_code == 200
    assert "window.QAMetricsRotator" in r_qa_metrics_rotator.text

    r_qa_cards_renderer = client.get("/core/qa_cards_renderer.js")
    assert r_qa_cards_renderer.status_code == 200
    assert "window.QACardsRenderer" in r_qa_cards_renderer.text

    r_qa_card_rotator = client.get("/core/qa_card_rotator.js")
    assert r_qa_card_rotator.status_code == 200
    assert "window.QACardRotator" in r_qa_card_rotator.text

    r_qa_dashboard_ui = client.get("/core/qa_dashboard_ui.js")
    assert r_qa_dashboard_ui.status_code == 200
    assert "window.QADashboardUI" in r_qa_dashboard_ui.text

    r_qa_data_loader = client.get("/core/qa_data_loader.js")
    assert r_qa_data_loader.status_code == 200
    assert "window.QADataLoader" in r_qa_data_loader.text

    r_export_manager = client.get("/core/export_manager.js")
    assert r_export_manager.status_code == 200
    assert "application/javascript" in r_export_manager.headers.get("content-type", "")

    r_export_csv_helpers = client.get("/core/export_csv_helpers.js")
    assert r_export_csv_helpers.status_code == 200
    assert "application/javascript" in r_export_csv_helpers.headers.get("content-type", "")

    r_flip_rotator_lifecycle = client.get("/core/flip_rotator_lifecycle.js")
    assert r_flip_rotator_lifecycle.status_code == 200
    assert "window.FlipRotatorLifecycle" in r_flip_rotator_lifecycle.text

def test_export_manager_contains_explicit_missing_helper_error(client):
    r = client.get("/core/export_manager.js")
    assert r.status_code == 200
    text = r.text
    assert "CSV export unavailable: ExportCsvHelpers.buildCsvRows is not loaded" in text


def test_export_csv_helpers_race_analysis_is_zero_safe(client):
    r = client.get("/core/export_csv_helpers.js")
    assert r.status_code == 200
    text = r.text
    assert "const gapPercent = second > 0 ? Math.round((gap / second) * 100) : 100;" in text


def test_core_routed_endpoints_still_resolve(client):
    r_auth_status = client.get("/auth/status")
    assert r_auth_status.status_code == 200

    r_analytics_overview = client.get("/analytics/overview")
    assert r_analytics_overview.status_code in (200, 401)


def test_overall_goods_in_endpoint_returns_contract_shape(client):
    r = client.get('/overall/goods-in')
    assert r.status_code == 200
    body = r.json()
    assert body['sectionKey'] == 'goods_in'
    assert 'targetQueue' in body
    assert 'currentQueue' in body
    assert 'subMetrics' in body
    assert isinstance(body['subMetrics'], list)


def test_overall_sections_endpoint_returns_list(client):
    r = client.get('/overall/sections')
    assert r.status_code == 200
    body = r.json()
    assert 'sections' in body
    assert isinstance(body['sections'], list)
    assert len(body['sections']) >= 1

    r_metrics_today = client.get("/metrics/today")
    assert r_metrics_today.status_code in (200, 401)

    r_export_excel = client.post("/export/excel", json={"sheetsData": {}})
    assert r_export_excel.status_code in (400, 401)


def test_overall_spotlight_endpoint_returns_contract_shape(client):
    r = client.get('/overall/spotlight')
    assert r.status_code == 200
    body = r.json()
    assert 'goodsIn' in body
    assert 'ia' in body
    assert 'erasure' in body
    assert 'qa' in body
    assert 'sorting' in body


def test_erasure_metrics_qa_summary_contract_shape(client):
    r = client.get("/metrics/qa-summary", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body
    assert "today" in body
    assert "monthlyMomentum" in body
    assert "byType" in body
    assert "engineersLeaderboard" in body
    assert isinstance(body["engineersLeaderboard"], dict)
    assert "items" in body["engineersLeaderboard"]
    assert isinstance(body["engineersLeaderboard"]["items"], list)


def test_qa_dashboard_contract_shape_with_stubbed_source_data(client, monkeypatch):
    import backend.app.routes.qa_insights as qa_insights_module

    monkeypatch.setattr(
        qa_insights_module.qa_export,
        "get_week_dates",
        lambda period: (date(2026, 4, 6), date(2026, 4, 10), "This Week"),
    )
    monkeypatch.setattr(
        qa_insights_module.qa_export,
        "get_weekly_qa_comparison",
        lambda start, end: {
            "Louise L": {
                "total": 50,
                "successful": 45,
                "pass_rate": 90.0,
                "daily": {"Monday": {"scans": 20, "passed": 18}},
            }
        },
    )
    monkeypatch.setattr(
        qa_insights_module.qa_export,
        "get_de_qa_comparison",
        lambda start, end: {"Louise L": {"total": 30, "daily": {"Monday": {"scans": 12}}}},
    )
    monkeypatch.setattr(
        qa_insights_module.qa_export,
        "get_non_de_qa_comparison",
        lambda start, end: {"Louise L": {"total": 20, "daily": {"Monday": {"scans": 8}}}},
    )
    monkeypatch.setattr(qa_insights_module.qa_export, "get_all_time_daily_record", lambda: 351)

    r = client.get("/api/qa-dashboard?period=this_week", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 200
    body = r.json()

    assert body["period"] == "This Week"
    assert "technicians" in body
    assert isinstance(body["technicians"], list)
    assert len(body["technicians"]) >= 1

    assert "summary" in body
    summary = body["summary"]
    for key in ("totalScans", "deQaScans", "nonDeQaScans", "combinedScans", "passRate", "topTechnician"):
        assert key in summary


def test_dashboard_view_isolation_contracts(client):
    r_switcher = client.get("/core/dashboard_switcher.js")
    assert r_switcher.status_code == 200
    switcher_js = r_switcher.text
    assert "view.hidden = !isActive;" in switcher_js
    assert "view.setAttribute('aria-hidden', isActive ? 'false' : 'true');" in switcher_js
    assert "view.style.display = isActive ? displayMode : 'none';" in switcher_js

    r_styles = client.get("/styles.css")
    assert r_styles.status_code == 200
    css = r_styles.text
    assert "main.layout {" in css
    assert "display: none !important;" in css
    assert "#erasureStatsView.is-active," in css
    assert "#qaStatsView.is-active," in css
    assert "#overallStatsView.is-active {" in css


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


def test_admin_network_access_requires_admin(client):
    r = client.get("/admin/network-access")
    assert r.status_code == 401


def test_admin_network_access_returns_trust_and_policy_details(client):
    r = client.get(
        "/admin/network-access",
        headers={
            "Authorization": "Bearer test-admin-pass",
            "X-Forwarded-For": "82.163.130.162",
            "User-Agent": "Mozilla/5.0 (Linux; Android 9; AFTSS) AppleWebKit/537.36 (KHTML, like Gecko) Silk/138.13.4",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "client_ip" in body
    assert "client_ips" in body
    assert "trusted_network_match" in body
    assert "trusted_viewer_networks" in body
    assert "viewer_policy" in body
    assert body["viewer_policy"]["trusted_network_auto_allow"] is True


def test_admin_external_access_attempts_requires_admin(client):
    r = client.get("/admin/external-access-attempts")
    assert r.status_code == 401


def test_admin_external_access_attempts_returns_shape(client):
    r = client.get("/admin/external-access-attempts", headers={"Authorization": "Bearer test-admin-pass"})
    assert r.status_code == 200
    body = r.json()
    assert "attempts" in body
    assert "total" in body


def test_admin_sorting_evidence_requires_admin(client):
    r = client.get("/admin/sorting-evidence")
    assert r.status_code == 401


def test_admin_sorting_evidence_handles_db_unavailable(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module.qa_export, "get_mariadb_connection", lambda: None)
    r = client.get("/admin/sorting-evidence", headers={"Authorization": "Bearer test-admin-pass"})
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
