from datetime import UTC, datetime, timedelta
import os

from fastapi import APIRouter

import backend.database as db
import backend.qa_export as qa_export


QA_DASHBOARD_SNAPSHOT_TTL_SECONDS = max(15, int(os.getenv("QA_DASHBOARD_SNAPSHOT_TTL_SECONDS", "120")))
QA_ALL_TIME_RECORD_TTL_SECONDS = max(60, int(os.getenv("QA_ALL_TIME_RECORD_TTL_SECONDS", "600")))
QA_SNAPSHOT_MAX_STALE_SECONDS = max(300, int(os.getenv("QA_SNAPSHOT_MAX_STALE_SECONDS", "3600")))
QA_ALL_TIME_SQLITE_REFRESH_SECONDS = max(30, int(os.getenv("QA_ALL_TIME_SQLITE_REFRESH_SECONDS", "120")))

_qa_all_time_refresh_state = {
    "lastRefresh": datetime.min.replace(tzinfo=UTC),
}


def _parse_snapshot_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _snapshot_payload_if_usable(snapshot_key: str, max_stale_seconds: int) -> tuple[dict | None, float | None]:
    snap = db.get_dashboard_snapshot(snapshot_key)
    if not snap:
        return None, None
    payload = snap.get("payload") if isinstance(snap, dict) else None
    if not isinstance(payload, dict):
        return None, None
    ts = _parse_snapshot_ts(snap.get("updatedAt") if isinstance(snap, dict) else None)
    if ts is None:
        return None, None
    age_seconds = max(0.0, (datetime.now(UTC) - ts).total_seconds())
    if age_seconds > float(max_stale_seconds):
        return None, age_seconds
    return payload, age_seconds


def _get_all_time_daily_record_snapshot(*, force_refresh: bool = False) -> dict:
    snapshot_key = "qa_all_time_daily_record"
    if not force_refresh:
        payload, age = _snapshot_payload_if_usable(snapshot_key, QA_SNAPSHOT_MAX_STALE_SECONDS)
        if isinstance(payload, dict) and age is not None and age <= QA_ALL_TIME_RECORD_TTL_SECONDS:
            return payload
    value = qa_export.get_all_time_daily_record() or {
        "data_bearing_records": [],
        "non_data_bearing_records": [],
    }
    try:
        db.upsert_dashboard_snapshot(snapshot_key, value, source_version="qa_export.get_all_time_daily_record")
    except Exception:
        pass
    return value


def _should_refresh_all_time_sqlite(*, force_refresh: bool = False) -> bool:
    if force_refresh:
        _qa_all_time_refresh_state["lastRefresh"] = datetime.now(UTC)
        return True
    now = datetime.now(UTC)
    last = _qa_all_time_refresh_state.get("lastRefresh")
    if not isinstance(last, datetime):
        _qa_all_time_refresh_state["lastRefresh"] = now
        return True
    if (now - last).total_seconds() >= float(QA_ALL_TIME_SQLITE_REFRESH_SECONDS):
        _qa_all_time_refresh_state["lastRefresh"] = now
        return True
    return False


async def compute_qa_dashboard_data(period: str, cache_get, cache_set, force_refresh: bool = False):
    """Shared QA dashboard payload builder used by endpoint and internal callers."""
    cache_key = f"qa_dashboard:{period}"
    snapshot_key = f"qa_dashboard:{period}"
    snapshot_fallback = None
    try:
        if not force_refresh:
            cached = cache_get(cache_key)
            if cached is not None:
                return cached

            snapshot_payload, snapshot_age = _snapshot_payload_if_usable(snapshot_key, QA_SNAPSHOT_MAX_STALE_SECONDS)
            if isinstance(snapshot_payload, dict):
                snapshot_fallback = snapshot_payload
                if snapshot_age is not None and snapshot_age <= QA_DASHBOARD_SNAPSHOT_TTL_SECONDS:
                    return cache_set(cache_key, snapshot_payload)

        start_date, end_date, period_label = qa_export.get_week_dates(period)

        if period == "all_time":
            if _should_refresh_all_time_sqlite(force_refresh=force_refresh):
                try:
                    qa_export.refresh_all_time_sqlite_aggregates()
                except Exception:
                    pass
            qa_data, de_qa_data, non_de_qa_data = qa_export.get_all_time_aggregates_from_sqlite()
            if not qa_data and not de_qa_data and not non_de_qa_data:
                qa_data = qa_export.get_weekly_qa_comparison(start_date, end_date)
                de_qa_data = qa_export.get_de_qa_comparison(start_date, end_date)
                non_de_qa_data = qa_export.get_non_de_qa_comparison(start_date, end_date)
        else:
            qa_data = qa_export.get_weekly_qa_comparison(start_date, end_date)
            de_qa_data = qa_export.get_de_qa_comparison(start_date, end_date)
            non_de_qa_data = qa_export.get_non_de_qa_comparison(start_date, end_date)

        if not qa_data and not de_qa_data and not non_de_qa_data:
            min_date, max_date = qa_export.get_qa_data_bounds()
            result = {
                "period": period_label,
                "dateRange": f"{start_date} to {end_date}",
                "technicians": [],
                "summary": {
                    "totalScans": 0,
                    "deQaScans": 0,
                    "nonDeQaScans": 0,
                    "combinedScans": 0,
                    "passRate": 0,
                    "avgConsistency": 0,
                    "topTechnician": "N/A",
                },
                "topPerformers": [],
                "locations": [],
                "dataBounds": {
                    "minDate": str(min_date) if min_date else None,
                    "maxDate": str(max_date) if max_date else None,
                },
            }
            try:
                db.upsert_dashboard_snapshot(snapshot_key, result, source_version=f"period:{period_label}")
            except Exception:
                pass
            return cache_set(cache_key, result)

        total_scans = sum(stats["total"] for name, stats in qa_data.items() if name.lower() != "(unassigned)") if qa_data else 0
        total_passed = sum(stats["successful"] for name, stats in qa_data.items() if name.lower() != "(unassigned)") if qa_data else 0
        total_de_scans = sum(stats["total"] for name, stats in de_qa_data.items() if name.lower() != "(unassigned)") if de_qa_data else 0
        total_non_de_scans = (
            sum(stats["total"] for name, stats in non_de_qa_data.items() if name.lower() != "(unassigned)")
            if non_de_qa_data
            else 0
        )
        combined_scans = total_scans + total_de_scans + total_non_de_scans
        overall_pass_rate = (total_passed / total_scans * 100) if total_scans > 0 else 0

        technicians = []
        consistency_scores = []
        all_names = sorted(
            set(qa_data.keys() if qa_data else [])
            | set(de_qa_data.keys() if de_qa_data else [])
            | set(non_de_qa_data.keys() if non_de_qa_data else [])
        )

        for tech_name in all_names:
            stats = qa_data.get(tech_name, {"total": 0, "successful": 0, "daily": {}, "pass_rate": 0.0})
            de_stats = de_qa_data.get(tech_name, {"total": 0, "daily": {}})
            non_de_stats = non_de_qa_data.get(tech_name, {"total": 0, "daily": {}})

            qa_total = stats["total"]
            de_total = de_stats["total"]
            non_de_total = non_de_stats["total"]
            tech_combined_total = qa_total + de_total + non_de_total

            combined_daily = {}
            for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
                qa_scans = stats["daily"].get(day, {}).get("scans", 0)
                de_scans = de_stats["daily"].get(day, {}).get("scans", 0)
                non_de_scans = non_de_stats["daily"].get(day, {}).get("scans", 0)
                combined_scans_day = qa_scans + de_scans + non_de_scans
                if combined_scans_day > 0:
                    combined_daily[day] = {"scans": combined_scans_day, "passed": stats["daily"].get(day, {}).get("passed", 0)}

            days_active = len([d for d in combined_daily if combined_daily[d]["scans"] > 0])
            avg_per_day = tech_combined_total / max(1, days_active) if days_active > 0 else 0

            daily_counts = [float(combined_daily[day]["scans"]) for day in combined_daily if combined_daily[day]["scans"] > 0]
            consistency = 100
            if daily_counts and len(daily_counts) > 1:
                avg = sum(daily_counts) / len(daily_counts)
                if avg > 0:
                    variance = sum((x - avg) ** 2 for x in daily_counts) / len(daily_counts)
                    consistency = max(0, min(100, 100 - (variance / (avg + 1) * 10)))
            consistency_scores.append(consistency)

            reliability = (stats["pass_rate"] * 0.6) + (consistency * 0.4) if qa_total > 0 else 0
            tech_data = {
                "name": tech_name,
                "qaScans": qa_total,
                "deQaScans": de_total,
                "nonDeQaScans": non_de_total,
                "combinedScans": tech_combined_total,
                "passRate": round(stats["pass_rate"], 1),
                "avgPerDay": round(avg_per_day, 1),
                "consistency": round(consistency, 1),
                "reliability": round(reliability, 1),
                "daysActive": days_active,
                "daily": {},
            }
            for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
                if day in combined_daily:
                    daily = combined_daily[day]
                    pass_pct = (daily["passed"] / daily["scans"] * 100) if daily["scans"] > 0 else 0
                    tech_data["daily"][day] = {"scans": daily["scans"], "passed": daily["passed"], "passRate": round(pass_pct, 1)}
            technicians.append(tech_data)

        top_performers = sorted(technicians, key=lambda x: x["combinedScans"], reverse=True)[:5]
        avg_consistency = sum(consistency_scores) / len(consistency_scores) if consistency_scores else 0
        daily_record = _get_all_time_daily_record_snapshot(force_refresh=False)

        result = {
            "period": period_label,
            "dateRange": f"{start_date.isoformat()} to {end_date.isoformat()}",
            "technicians": technicians,
            "summary": {
                "totalScans": total_scans,
                "deQaScans": total_de_scans,
                "nonDeQaScans": total_non_de_scans,
                "combinedScans": combined_scans,
                "passRate": round(overall_pass_rate, 1),
                "avgConsistency": round(avg_consistency, 1),
                "topTechnician": top_performers[0]["name"] if top_performers else "N/A",
                "techniciansCount": len(technicians),
                "dailyRecord": daily_record,
            },
            "topPerformers": top_performers,
        }
        try:
            db.upsert_dashboard_snapshot(snapshot_key, result, source_version=f"period:{period_label}")
        except Exception:
            pass
        return cache_set(cache_key, result)
    except Exception as exc:
        if isinstance(snapshot_fallback, dict):
            return cache_set(cache_key, snapshot_fallback)
        return {"error": str(exc), "period": period}


async def refresh_qa_snapshot_tables(periods: list[str] | None = None):
    """Refresh persisted QA snapshots in the background to reduce request-time DB load."""
    target_periods = periods or ["today", "this_week", "this_month", "all_time"]

    # Refresh all-time records first so period payloads can reuse this snapshot.
    _get_all_time_daily_record_snapshot(force_refresh=True)

    def _no_cache_get(_cache_key):
        return None

    def _no_cache_set(_cache_key, value):
        return value

    for period in target_periods:
        try:
            await compute_qa_dashboard_data(period, _no_cache_get, _no_cache_set, force_refresh=True)
        except Exception:
            continue


def create_qa_insights_router(*, cache_get, cache_set) -> APIRouter:
    router = APIRouter()

    async def _get_qa_insights_payload(period: str = "this_week") -> dict:
        cache_key = f"qa_insights:{period}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

        start_date, end_date, label = qa_export.get_week_dates(period)
        qa_data = qa_export.get_weekly_qa_comparison(start_date, end_date)
        de_qa_data = qa_export.get_de_qa_comparison(start_date, end_date)
        non_de_qa_data = qa_export.get_non_de_qa_comparison(start_date, end_date)

        total_qa_app = sum(stats["total"] for name, stats in qa_data.items() if name.lower() != "(unassigned)") if qa_data else 0
        total_de = sum(stats["total"] for name, stats in de_qa_data.items() if name.lower() != "(unassigned)") if de_qa_data else 0
        total_non_de = sum(stats["total"] for name, stats in non_de_qa_data.items() if name.lower() != "(unassigned)") if non_de_qa_data else 0
        combined_total = total_qa_app + total_de + total_non_de

        day_count = max(1, (end_date - start_date).days + 1)
        active_engineers = set()
        for name, stats in (qa_data or {}).items():
            if name.lower() != "(unassigned)" and stats.get("total", 0) > 0:
                active_engineers.add(name)
        for name, stats in (de_qa_data or {}).items():
            if name.lower() != "(unassigned)" and stats.get("total", 0) > 0:
                active_engineers.add(name)
        for name, stats in (non_de_qa_data or {}).items():
            if name.lower() != "(unassigned)" and stats.get("total", 0) > 0:
                active_engineers.add(name)
        active_count = len(active_engineers)

        projection = None
        today = datetime.now().date()
        if period == "this_month":
            total_days = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            total_days = total_days.day
            days_elapsed = max(1, today.day)
            projection = round((combined_total / days_elapsed) * total_days)

        rolling_7 = 0
        rolling_30 = 0
        trend_pct = 0
        try:
            end_rolling = datetime.now().date()
            start_rolling = end_rolling - timedelta(days=29)
            daily_totals = qa_export.get_qa_daily_totals_range(start_rolling, end_rolling)
            daily_values = [row.get("qaTotal", row.get("deQa", 0) + row.get("nonDeQa", 0)) for row in daily_totals]
            if daily_values:
                rolling_30 = round(sum(daily_values) / len(daily_values), 1)
                last_7 = daily_values[-7:]
                prev_7 = daily_values[-14:-7] if len(daily_values) >= 14 else []
                rolling_7 = round(sum(last_7) / max(1, len(last_7)), 1)
                if prev_7 and sum(prev_7) > 0:
                    prev_avg = sum(prev_7) / len(prev_7)
                    trend_pct = round(((rolling_7 - prev_avg) / prev_avg) * 100, 1)
        except Exception:
            pass

        qa_only_total = total_de + total_non_de
        result = {
            "period": label,
            "dateRange": f"{start_date} to {end_date}",
            "total": qa_only_total,
            "combinedTotal": combined_total,
            "breakdown": {"qaApp": total_qa_app, "deQa": total_de, "nonDeQa": total_non_de},
            "avgPerDay": round(qa_only_total / day_count, 1),
            "rolling7DayAvg": rolling_7,
            "rolling30DayAvg": rolling_30,
            "trend7DayPct": trend_pct,
            "activeEngineers": active_count,
            "avgPerEngineer": round(qa_only_total / active_count, 1) if active_count else 0,
            "projection": projection,
        }
        return cache_set(cache_key, result)

    async def _get_qa_trends_payload(period: str = "this_week") -> dict:
        today = datetime.now().date()
        cache_key = f"qa_trends:{period}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

        if period == "today":
            result = {"period": "Today", "granularity": "hour", "series": qa_export.get_qa_hourly_totals(today)}
            return cache_set(cache_key, result)

        if period == "all_time":
            min_date, max_date = qa_export.get_qa_data_bounds()
            if max_date:
                end_date = max_date
                start_date = max_date - timedelta(days=29)
            else:
                start_date = today - timedelta(days=29)
                end_date = today
            label = "All Time (Last 30 Days)"
        else:
            start_date, end_date, label = qa_export.get_week_dates(period)

        result = {"period": label, "granularity": "day", "series": qa_export.get_qa_daily_totals_range(start_date, end_date)}
        return cache_set(cache_key, result)

    @router.get("/api/insights/qa")
    async def qa_insights(period: str = "this_week"):
        try:
            return await _get_qa_insights_payload(period)
        except Exception:
            return {"error": "Failed to compute QA insights"}

    @router.get("/api/qa-trends")
    async def qa_trends(period: str = "this_week"):
        try:
            return await _get_qa_trends_payload(period)
        except Exception:
            return {"error": "Failed to compute QA trends"}

    @router.get("/api/qa-bootstrap")
    async def qa_bootstrap():
        """Single-call QA payload to reduce client request fanout and warm endpoint caches."""
        try:
            cache_key = "qa_bootstrap_payload"
            cached = cache_get(cache_key)
            if cached is not None:
                return cached

            periods = ["today", "this_week", "all_time"]
            dashboard = {}
            trends = {}
            insights = {}

            for period in periods:
                dashboard[period] = await compute_qa_dashboard_data(period, cache_get, cache_set)
                trends[period] = await _get_qa_trends_payload(period)
                insights[period] = await _get_qa_insights_payload(period)

            payload = {
                "dashboard": dashboard,
                "trends": trends,
                "insights": insights,
                "generatedAt": datetime.now(UTC).isoformat(),
            }
            return cache_set(cache_key, payload)
        except Exception:
            return {"error": "Failed to build QA bootstrap payload"}

    @router.get("/api/insights/qa-engineers")
    async def qa_engineer_insights(period: str = "this_week", limit: int = 10):
        try:
            cache_key = f"qa_engineers:{period}:{limit}"
            cached = cache_get(cache_key)
            if cached is not None:
                return cached
            start_date, end_date, label = qa_export.get_week_dates(period)
            day_count = max(1, (end_date - start_date).days + 1)

            data = qa_export.get_qa_engineer_daily_totals_range(start_date, end_date)
            prev_start = start_date - timedelta(days=day_count)
            prev_end = start_date - timedelta(days=1)
            prev_data = qa_export.get_qa_engineer_daily_totals_range(prev_start, prev_end)

            results = []
            for name, daily in data.items():
                if name.lower() == "(unassigned)":
                    continue
                total = sum(daily.values())
                active_days = len([v for v in daily.values() if v > 0])
                avg_per_day = round(total / day_count, 1)
                prev_total = sum(prev_data.get(name, {}).values())
                prev_avg = round(prev_total / day_count, 1)
                trend_pct = round(((avg_per_day - prev_avg) / prev_avg) * 100, 1) if prev_avg > 0 else 0
                results.append(
                    {
                        "name": name,
                        "total": total,
                        "avgPerDay": avg_per_day,
                        "avgPerActiveDay": round(total / active_days, 1) if active_days else 0,
                        "trendPct": trend_pct,
                    }
                )
            results.sort(key=lambda x: x["total"], reverse=True)
            return cache_set(cache_key, {"period": label, "data": results[: max(1, limit)]})
        except Exception:
            return {"error": "Failed to compute QA engineer insights"}

    @router.get("/api/qa-dashboard")
    async def qa_dashboard(period: str = "this_week"):
        return await compute_qa_dashboard_data(period, cache_get, cache_set)

    return router
