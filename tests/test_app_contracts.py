from pathlib import Path
from datetime import datetime, UTC
from datetime import date
import time


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


def test_admin_page_collapsible_sections_lazy_init_smoke(client):
    r = client.get("/admin.html", headers={"Authorization": "Bearer test-admin-pass"})
    assert r.status_code == 200
    html = r.text

    for section_id in [
        "section-fix-initials",
        "section-connected-devices",
        "section-goods-in-evidence",
        "section-erasure-evidence",
        "section-erasure-reconciliation",
        "section-sorting-evidence",
        "section-dashboard-activity",
    ]:
        assert f'id="{section_id}"' in html

    assert "registerSectionLoaders();" in html
    assert "toggleBtn.innerHTML = '<span class=\"chevron\" aria-hidden=\"true\"></span>'" in html

    load_idx = html.find("window.addEventListener('load', async () => {")
    assert load_idx != -1
    load_snippet = html[load_idx: load_idx + 600]
    assert "registerSectionLoaders();" in load_snippet
    assert "initCollapsibleSections();" in load_snippet
    assert "loadErasureEvidence();" not in load_snippet
    assert "loadSortingEvidence();" not in load_snippet
    assert "fetchAdminActivity();" not in load_snippet


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


def test_erasure_detail_falls_back_to_nested_hardware_fields(client, app_module):
    with app_module.db.sqlite_transaction() as (_, cur):
        cur.execute("DELETE FROM erasures")

    payload = {
        "event": "success",
        "deviceType": "macs",
        "initials": "BP",
        "manufacturer": "<REPORTPATH blancco_data.blancco_hardware_report.system.manufacturer>",
        "model": "<REPORTPATH blancco_data.blancco_hardware_report.system.model>",
        "serial": "<REPORTPATH blancco_data.blancco_hardware_report.system.serial>",
        "diskSerial": "<REPORTPATH blancco_data.blancco_hardware_report.disks.disk.serial>",
        "durationSec": "<REPORTPATH blancco_data.blancco_erasure_report.erasures.erasure.elapsed_time>",
        "timestamp": "<Completion Time>",
        "blancco_data": {
            "blancco_hardware_report": {
                "system": {
                    "manufacturer": "Apple, Inc.",
                    "model": "MacBook Pro 16",
                    "serial": "MACSYS-123",
                },
                "disks": {
                    "disk": {
                        "serial": "MACDISK-456",
                        "capacity": "500107862016",
                    }
                },
            }
        },
    }

    r = client.post(
        "/hooks/erasure-detail",
        headers={"x-api-key": "test-webhook-key"},
        json=payload,
    )
    assert r.status_code == 200
    assert r.json().get("status") == "ok"

    with app_module.db.sqlite_transaction() as (_, cur):
        cur.execute(
            """
            SELECT device_type, initials, manufacturer, model, system_serial, disk_serial, drive_size
            FROM erasures
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == "macs"
    assert row[1] == "BP"
    assert row[2] == "Apple, Inc."
    assert row[3] == "MacBook Pro 16"
    assert row[4] == "MACSYS-123"
    assert row[5] == "MACDISK-456"
    assert row[6] == 500107862016


def test_erasure_detail_accepts_assetnumber_alias_for_stockid(client, app_module):
    with app_module.db.sqlite_transaction() as (_, cur):
        cur.execute("DELETE FROM local_erasures")

    payload = {
        "event": "success",
        "deviceType": "macs",
        "initials": "BP",
        "assetnumber": "A1234567",
        "serial": "MACSYS-ALIAS",
        "diskSerial": "MACDISK-ALIAS",
    }

    r = client.post(
        "/hooks/erasure-detail",
        headers={"x-api-key": "test-webhook-key"},
        json=payload,
    )
    assert r.status_code == 200
    assert r.json().get("status") == "ok"

    with app_module.db.sqlite_transaction() as (_, cur):
        cur.execute(
            "SELECT stockid, system_serial FROM local_erasures ORDER BY ts DESC LIMIT 1"
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == "A1234567"
    assert row[1] == "MACSYS-ALIAS"


def test_auth_login_admin_returns_admin_role(client, app_module, workspace_temp_dir, monkeypatch):
    tokens_path = workspace_temp_dir / "device_tokens_test.json"
    monkeypatch.setattr(app_module, "DEVICE_TOKENS_FILE", str(tokens_path))

    r = client.post("/auth/login", json={"password": "test-admin-pass"})
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["role"] == "admin"
    assert "device_token" in body


def test_auth_login_invalid_password_rejected_even_on_local_network(client):
    r = client.post("/auth/login", json={"password": "definitely-wrong"})
    assert r.status_code == 401
    assert r.json().get("detail") == "Invalid password"


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


def test_overall_sections_unique_keys_and_expected_set(client):
    r = client.get('/overall/sections')
    assert r.status_code == 200
    body = r.json()
    sections = body.get('sections') or []
    keys = [s.get('sectionKey') for s in sections if isinstance(s, dict)]

    assert len(keys) == len(set(keys)), 'sectionKey values must be unique'
    expected = {'goods_in', 'ia', 'erasure', 'qa', 'sorting'}
    assert set(keys) == expected


def test_overall_sections_optional_diagnostics_shape(client):
    r = client.get('/overall/sections')
    assert r.status_code == 200
    body = r.json()
    sections = body.get('sections') or []

    for section in sections:
        if not isinstance(section, dict):
            continue
        if 'queryMs' in section and section['queryMs'] is not None:
            assert isinstance(section['queryMs'], int)
            assert section['queryMs'] >= 0
        if 'sourceReason' in section and section['sourceReason'] is not None:
            assert isinstance(section['sourceReason'], str)


def test_overall_spotlight_endpoint_returns_contract_shape(client):
    r = client.get('/overall/spotlight')
    assert r.status_code == 200
    body = r.json()
    assert 'goodsIn' in body
    assert 'ia' in body
    assert 'erasure' in body
    assert 'qa' in body
    assert 'sorting' in body


def test_qa_bootstrap_endpoint_returns_expected_sections(client):
    r = client.get('/api/qa-bootstrap', headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 200
    body = r.json()
    assert 'dashboard' in body
    assert 'trends' in body
    assert 'insights' in body
    assert 'today' in body['dashboard']
    assert 'this_week' in body['dashboard']
    assert 'all_time' in body['dashboard']


def test_static_assets_have_cache_control_headers(client):
    r_js = client.get('/core/dashboard_switcher.js')
    assert r_js.status_code == 200
    cache_control = r_js.headers.get('cache-control', '')
    assert 'public' in cache_control
    assert 'max-age=' in cache_control

    r_html = client.get('/')
    assert r_html.status_code == 200
    html_cache_control = r_html.headers.get('cache-control', '')
    assert 'no-cache' in html_cache_control


def test_overall_sections_falls_back_when_refresh_times_out(client, app_module, monkeypatch):
    monkeypatch.setenv('OVERALL_REFRESH_TIMEOUT_SECONDS', '0.05')

    def _slow_conn():
        time.sleep(0.2)
        return None

    monkeypatch.setattr(app_module.qa_export, 'get_mariadb_connection', _slow_conn)

    r = client.get('/overall/sections')
    assert r.status_code == 200
    body = r.json()
    assert 'sections' in body
    assert isinstance(body['sections'], list)
    assert len(body['sections']) >= 1
    assert body.get('degraded') in (True, None)


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


def test_qa_dashboard_all_time_can_serve_from_sqlite_aggregates(client, monkeypatch):
    import backend.app.routes.qa_insights as qa_insights_module

    monkeypatch.setattr(
        qa_insights_module.qa_export,
        "refresh_all_time_sqlite_aggregates",
        lambda: {"ok": True, "rows": 3},
    )
    monkeypatch.setattr(
        qa_insights_module.qa_export,
        "get_all_time_aggregates_from_sqlite",
        lambda: (
            {
                "Louise L": {
                    "total": 120,
                    "successful": 110,
                    "daily": {"Monday": {"date": "2026-04-07", "scans": 30, "passed": 28}},
                    "pass_rate": 91.7,
                }
            },
            {
                "Louise L": {
                    "total": 60,
                    "daily": {"Monday": {"date": "2026-04-07", "scans": 60}},
                }
            },
            {
                "Louise L": {
                    "total": 15,
                    "daily": {"Monday": {"date": "2026-04-07", "scans": 15}},
                }
            },
        ),
    )

    r = client.get("/api/qa-dashboard?period=all_time", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 200
    body = r.json()
    assert body["period"] == "All Time"
    assert "summary" in body
    assert body["summary"]["combinedScans"] == 195
    assert body["summary"]["topTechnician"] == "Louise L"


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
    assert "sqlite_storage" in body
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


def test_admin_goods_in_evidence_requires_admin(client):
    r = client.get("/admin/goods-in-evidence")
    assert r.status_code == 401


def test_admin_erasure_reconciliation_requires_admin(client):
    r = client.get("/admin/erasure-reconciliation")
    assert r.status_code == 401


def test_admin_erasure_reconciliation_contract_shape_and_counts(client, app_module):
    target_date = "2026-02-03"
    with app_module.db.sqlite_transaction() as (_, cur):
        cur.execute("DELETE FROM erasures")
        rows = [
            ("2026-02-03T09:00:00", target_date, "2026-02", "success", "laptops_desktops", "AA", "job-1", "S1", None),
            ("2026-02-03T10:00:00", target_date, "2026-02", "success", "servers", "", "job-2", "S2", None),
            ("2026-02-03T11:00:00", target_date, "2026-02", "success", "loose_drives", "BB", "job-3", "S3", None),
            ("2026-02-03T17:30:00", target_date, "2026-02", "success", "macs", "", "job-4", "S4", None),
            ("2026-02-03T09:10:00", target_date, "2026-02", "failure", "laptops_desktops", "AA", "job-5", "DUP1", None),
            ("2026-02-03T09:11:00", target_date, "2026-02", "failure", "laptops_desktops", "AA", "job-6", "DUP1", None),
            ("2026-02-03T09:12:00", target_date, "2026-02", "success", "laptops_desktops", "AA", "job-7", "DUP1", None),
        ]
        cur.executemany(
            """
            INSERT INTO erasures (ts, date, month, event, device_type, initials, job_id, system_serial, disk_serial)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    r = client.get(
        f"/admin/erasure-reconciliation?date={target_date}&limit=50",
        headers={"Authorization": "Bearer test-admin-pass"},
    )
    assert r.status_code == 200
    body = r.json()

    assert "summary" in body
    assert "outsideTypeBreakdown" in body
    assert "missingInitialsSamples" in body
    assert "outsideVisibleTypeSamples" in body
    assert "failedDuplicateSerials" in body
    assert "failureThenSuccessSerials" in body

    summary = body["summary"]
    assert summary["date"] == target_date
    assert summary["dayTotalAllEvents"] == 7
    assert summary["daySuccessTotal"] == 5
    assert summary["dayFailureTotal"] == 2
    assert summary["daySuccessWithInitials"] == 3
    assert summary["daySuccessMissingInitials"] == 2
    assert summary["daySuccessVisibleTypes"] == 4
    assert summary["daySuccessVisibleWithInitials"] == 2
    assert summary["daySuccessOutsideVisibleTypes"] == 1
    assert summary["daySuccessWorkday8To16"] == 4
    assert summary["daySuccessOutsideWorkday"] == 1
    assert summary["failedDuplicateSerialCount"] == 1
    assert summary["failureThenSuccessSerialCount"] == 1

    recon = summary.get("reconciliation") or {}
    assert recon["successMinusVisibleWithInitials"] == 3
    assert recon["missingInitialsGap"] == 2
    assert recon["outsideVisibleTypeGap"] == 1


def test_admin_goods_in_evidence_handles_db_unavailable(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module.qa_export, "get_mariadb_connection", lambda: None)
    r = client.get("/admin/goods-in-evidence", headers={"Authorization": "Bearer test-admin-pass"})
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "fail"


def test_admin_sorting_evidence_handles_db_unavailable(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module.qa_export, "get_mariadb_connection", lambda: None)
    r = client.get("/admin/sorting-evidence", headers={"Authorization": "Bearer test-admin-pass"})
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "fail"


def test_admin_connected_devices_deduplicates_same_device_role(client, app_module):
    # Two admin tokens with the same fingerprint suffix should collapse to one
    # most-recent device record.
    app_module.save_device_tokens(
        {
            "old-token:09a0cea3abcdef12": {
                "expiry": "2099-01-01T00:00:00Z",
                "role": "admin",
                "user_agent": "pytest-agent",
                "client_ip": "127.0.0.1",
                "last_seen": "2026-01-01T00:00:00Z",
            },
            "new-token:09a0cea3abcdef12": {
                "expiry": "2099-01-01T00:00:00Z",
                "role": "admin",
                "user_agent": "pytest-agent",
                "client_ip": "127.0.0.1",
                "last_seen": "2026-01-02T00:00:00Z",
            },
        }
    )

    r = client.get("/admin/connected-devices", headers={"Authorization": "Bearer test-admin-pass"})
    assert r.status_code == 200
    body = r.json()
    devices = body.get("devices") or []
    assert len(devices) == 1
    assert devices[0].get("device_id") == "09a0cea3"


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


def test_local_network_can_read_dashboard_api_without_auth(client):
    # Trusted local-network viewers should be able to read dashboard APIs
    # without a manager/admin token.
    r = client.get(
        "/api/qa-dashboard?period=today",
        headers={"X-Forwarded-For": "192.168.1.10"},
    )
    assert r.status_code == 200


def test_local_network_still_cannot_access_admin_without_auth(client):
    # Local-network trust must not bypass /admin protections.
    r = client.get(
        "/admin/connected-devices",
        headers={"X-Forwarded-For": "192.168.1.10"},
    )
    assert r.status_code == 401


def test_overall_sections_overrides_stale_daily_done_counts(client, app_module, monkeypatch):
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    stale_payload = {
        "sections": [
            {
                "sectionKey": "qa",
                "sectionName": "QA",
                "currentQueue": 2775,
                "subMetrics": [
                    {"label": "DB Awaiting QA", "value": 2775},
                    {"label": "Non-DB Awaiting QA", "value": 0},
                    {"label": "Completed QA Today", "value": 588},
                ],
                "updatedAt": now_iso,
                "isLive": True,
                "source": "snapshot",
            },
            {
                "sectionKey": "sorting",
                "sectionName": "Sorting",
                "currentQueue": 8708,
                "subMetrics": [
                    {"label": "Awaiting Sorting", "value": 8708},
                    {"label": "Sorted Today", "value": 123},
                    {"label": "Sorting Output Last Hour", "value": 10},
                ],
                "updatedAt": now_iso,
                "isLive": True,
                "source": "snapshot",
            },
        ]
    }

    def _fake_get_snapshot(key):
        if key == "overall_sections":
            return {"payload": stale_payload, "updatedAt": now_iso}
        return None

    monkeypatch.setattr(app_module.db, "get_dashboard_snapshot", _fake_get_snapshot)
    monkeypatch.setattr(app_module.qa_export, "get_weekly_qa_comparison", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(app_module.qa_export, "get_de_qa_comparison", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(app_module.qa_export, "get_non_de_qa_comparison", lambda *_args, **_kwargs: {})

    r = client.get("/overall/sections")
    assert r.status_code == 200
    body = r.json()
    sections = body.get("sections") or []
    qa = next((s for s in sections if s.get("sectionKey") == "qa"), None)
    sorting = next((s for s in sections if s.get("sectionKey") == "sorting"), None)
    assert qa is not None
    assert sorting is not None

    qa_done = next((m.get("value") for m in qa.get("subMetrics", []) if str(m.get("label", "")).lower() == "completed qa today"), None)
    sorting_done = next((m.get("value") for m in sorting.get("subMetrics", []) if str(m.get("label", "")).lower() == "sorted today"), None)
    assert qa_done == 0
    assert sorting_done == 0


def test_analytics_hourly_totals_endpoint_available(client):
    r = client.get("/analytics/hourly-totals", headers={"Authorization": "Bearer test-manager-pass"})
    assert r.status_code == 200
    body = r.json()
    assert "hours" in body
