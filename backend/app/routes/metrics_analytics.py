from contextlib import closing
from datetime import date, datetime, timedelta
from typing import Dict

from fastapi import APIRouter, Request

import backend.qa_export as qa_export


def create_metrics_analytics_router(*, db_module, cache_get, cache_set) -> APIRouter:
    router = APIRouter()

    def _previous_business_day(target: date) -> date:
        weekday = target.weekday()
        if weekday == 0:  # Monday -> Friday
            return target - timedelta(days=3)
        if weekday == 6:  # Sunday -> Friday
            return target - timedelta(days=2)
        if weekday == 5:  # Saturday -> Friday
            return target - timedelta(days=1)
        return target - timedelta(days=1)

    def _safe_pct(today_value: int, prev_value: int) -> float | None:
        if prev_value <= 0:
            return None
        return round(((today_value - prev_value) / prev_value) * 100, 1)

    @router.get("/metrics/total-by-type")
    async def get_total_by_type(type: str = "laptops_desktops", scope: str = "today"):
        with closing(db_module.sqlite3.connect(db_module.DB_PATH)) as conn:
            cursor = conn.cursor()
            if scope == "month":
                today = date.today()
                year = today.year
                month = today.month
                first_day = f"{year:04d}-{month:02d}-01"
                last_day = f"{year:04d}-{month:02d}-{31 if month in [1,3,5,7,8,10,12] else 30 if month in [4,6,9,11] else (28 if year % 4 != 0 else 29):02d}"
                where = "date >= ? AND date <= ? AND event = 'success' AND device_type = ?"
                params = [first_day, last_day, type]
            elif scope == "all":
                where = "event = 'success' AND device_type = ?"
                params = [type]
            else:
                key_val = date.today().isoformat()
                where = "date = ? AND event = 'success' AND device_type = ?"
                params = [key_val, type]
            cursor.execute(f"SELECT COUNT(1) FROM erasures WHERE {where}", params)
            total = cursor.fetchone()[0]
        return {"total": total, "type": type, "scope": scope}

    @router.get("/metrics/all-time-totals")
    async def get_all_time_totals(group_by: str = None):
        result = db_module.get_all_time_totals(group_by=group_by)
        return {"allTimeTotal": result} if not group_by else result

    @router.get("/analytics/hourly-totals")
    async def analytics_hourly_totals():
        return {"hours": db_module.get_peak_hours()}

    @router.get("/analytics/daily-totals")
    async def analytics_daily_totals():
        return {"days": db_module.get_daily_totals()}

    @router.get("/metrics/monthly-momentum")
    async def get_monthly_momentum():
        return db_module.get_monthly_momentum()

    @router.get("/analytics/weekly-daily-totals")
    async def analytics_weekly_daily_totals():
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        days = [monday + timedelta(days=i) for i in range(5)]
        result = []
        for d in days:
            stats = db_module.get_daily_stats(d.isoformat())
            result.append({"date": d.isoformat(), "weekday": d.strftime("%a"), "count": stats.get("erased", 0)})
        return {"days": result}

    @router.get("/metrics/today")
    async def get_metrics(req: Request):
        cache_key = f"{req.url.path}" if not req.url.query else f"{req.url.path}?{req.url.query}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
        data = db_module.get_daily_stats()
        return cache_set(cache_key, data)

    @router.get("/metrics/yesterday")
    async def get_yesterday_metrics():
        return db_module.get_daily_stats(db_module.get_yesterday_str())

    @router.get("/metrics/flow-comparison")
    async def get_flow_comparison(req: Request):
        cache_key = f"{req.url.path}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

        today_date = date.today()
        compare_date = _previous_business_day(today_date)

        today_erasure = db_module.get_daily_stats(today_date.isoformat())
        prev_erasure = db_module.get_daily_stats(compare_date.isoformat())

        today_qa_rows = qa_export.get_qa_daily_totals_range(today_date, today_date) or []
        prev_qa_rows = qa_export.get_qa_daily_totals_range(compare_date, compare_date) or []
        today_qa = today_qa_rows[0] if today_qa_rows else {}
        prev_qa = prev_qa_rows[0] if prev_qa_rows else {}

        erased_today = int((today_erasure or {}).get("erased", 0) or 0)
        erased_prev = int((prev_erasure or {}).get("erased", 0) or 0)
        qa_today = int((today_qa or {}).get("qaTotal", 0) or 0)
        qa_prev = int((prev_qa or {}).get("qaTotal", 0) or 0)
        sorting_today = int((today_qa or {}).get("qaApp", 0) or 0)
        sorting_prev = int((prev_qa or {}).get("qaApp", 0) or 0)

        payload = {
            "currentDate": today_date.isoformat(),
            "compareDate": compare_date.isoformat(),
            "compareDayShort": compare_date.strftime("%a"),
            "erased": {
                "today": erased_today,
                "previous": erased_prev,
                "delta": erased_today - erased_prev,
                "deltaPct": _safe_pct(erased_today, erased_prev),
            },
            "qa": {
                "today": qa_today,
                "previous": qa_prev,
                "delta": qa_today - qa_prev,
                "deltaPct": _safe_pct(qa_today, qa_prev),
            },
            "sorting": {
                "today": sorting_today,
                "previous": sorting_prev,
                "delta": sorting_today - sorting_prev,
                "deltaPct": _safe_pct(sorting_today, sorting_prev),
            },
        }
        return cache_set(cache_key, payload)

    @router.get("/metrics/summary")
    async def metrics_summary(req: Request, date: str = None, startDate: str = None, endDate: str = None):
        if startDate and endDate:
            return db_module.get_summary_date_range(startDate, endDate)
        cache_key = f"{req.url.path}" if not req.url.query else f"{req.url.path}?{req.url.query}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
        data = db_module.get_summary_today_month(date)
        return cache_set(cache_key, data)

    @router.get("/metrics/qa-summary")
    async def metrics_qa_summary(req: Request):
        cache_key = f"{req.url.path}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

        result: Dict[str, object] = {}
        try:
            try:
                result["summary"] = db_module.get_summary_today_month()
            except Exception:
                result["summary"] = {}
            try:
                result["today"] = db_module.get_daily_stats()
            except Exception:
                result["today"] = {}
            try:
                result["monthlyMomentum"] = db_module.get_monthly_momentum()
            except Exception:
                result["monthlyMomentum"] = {}
            try:
                result["byType"] = db_module.get_counts_by_type_today()
            except Exception:
                result["byType"] = {}
            try:
                items = db_module.leaderboard(scope="today", limit=6)
                result["engineersLeaderboard"] = {"items": items}
            except Exception:
                result["engineersLeaderboard"] = {"items": []}
            try:
                end = datetime.now().date()
                start = end - timedelta(days=7)
                result["qaLast7"] = qa_export.get_qa_daily_totals_range(start, end)
            except Exception:
                result["qaLast7"] = []
        except Exception:
            result = {
                "summary": {},
                "today": {},
                "monthlyMomentum": {},
                "byType": {},
                "engineersLeaderboard": {"items": []},
                "qaLast7": [],
            }
        return cache_set(cache_key, result)

    @router.get("/metrics/by-type")
    async def metrics_by_type(req: Request):
        cache_key = f"{req.url.path}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
        data = db_module.get_counts_by_type_today()
        return cache_set(cache_key, data)

    @router.get("/metrics/errors")
    async def metrics_errors(req: Request):
        cache_key = f"{req.url.path}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
        data = db_module.get_error_distribution_today()
        return cache_set(cache_key, data)

    @router.get("/metrics/engineers/top2")
    async def metrics_engineers_top(req: Request, scope: str = "today", type: str | None = None, limit: int = 3):
        cache_key = f"{req.url.path}?scope={scope}&type={type}&limit={limit}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
        data = {"engineers": db_module.top_engineers(scope=scope, device_type=type, limit=limit)}
        return cache_set(cache_key, data)

    @router.get("/metrics/engineers/leaderboard")
    async def metrics_engineers_leaderboard(req: Request, scope: str = "today", limit: int = 6, date: str = None):
        cache_key = f"{req.url.path}?scope={scope}&limit={limit}&date={date}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
        data = {"items": db_module.leaderboard(scope=scope, limit=limit, date_str=date)}
        return cache_set(cache_key, data)

    @router.get("/metrics/engineers/weekly-stats")
    async def metrics_engineers_weekly_stats(req: Request, startDate: str, endDate: str):
        cache_key = f"{req.url.path}?start={startDate}&end={endDate}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
        data = {"engineers": db_module.get_engineer_weekly_stats(startDate, endDate)}
        return cache_set(cache_key, data)

    @router.get("/metrics/month-comparison")
    async def metrics_month_comparison(req: Request, currentStart: str, currentEnd: str, previousStart: str, previousEnd: str):
        cache_key = f"{req.url.path}?curStart={currentStart}&curEnd={currentEnd}&prevStart={previousStart}&prevEnd={previousEnd}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
        data = db_module.get_month_over_month_comparison(currentStart, currentEnd, previousStart, previousEnd)
        return cache_set(cache_key, data)

    @router.get("/metrics/top-engineers")
    async def get_top_engineers():
        engineers = db_module.get_top_engineers(limit=3)
        return {"engineers": engineers}

    @router.get("/metrics/engineers/top-by-type")
    async def get_top_engineers_by_type(type: str = "laptops_desktops", scope: str = "today", limit: int = 6):
        engineers = db_module.top_engineers(scope=scope, device_type=type, limit=limit)
        return {"engineers": engineers, "type": type}

    @router.get("/analytics/weekly-category-trends")
    async def get_weekly_category_trends():
        return {"trends": db_module.get_weekly_category_trends()}

    @router.get("/analytics/weekly-engineer-stats")
    async def get_weekly_engineer_stats():
        return {"stats": db_module.get_weekly_engineer_stats()}

    @router.get("/analytics/peak-hours")
    async def get_peak_hours():
        return {"hours": db_module.get_peak_hours()}

    @router.get("/analytics/day-of-week-patterns")
    async def get_day_of_week_patterns():
        return {"patterns": db_module.get_day_of_week_patterns()}

    @router.get("/competitions/speed-challenge")
    async def get_speed_challenge(window: str = "am"):
        return {
            "leaderboard": db_module.get_speed_challenge_stats(window),
            "status": db_module.get_speed_challenge_status(window),
        }

    @router.get("/competitions/category-specialists")
    async def get_category_specialists():
        return {"specialists": db_module.get_category_specialists()}

    @router.get("/competitions/consistency")
    async def get_consistency():
        return {"leaderboard": db_module.get_consistency_stats()}

    @router.get("/metrics/records")
    async def get_records():
        return db_module.get_records_and_milestones()

    @router.get("/metrics/weekly")
    async def get_weekly():
        return db_module.get_weekly_stats()

    @router.get("/metrics/performance-trends")
    async def get_performance_trends(target: int = 500):
        return db_module.get_performance_trends(target=target)

    @router.get("/metrics/target-achievement")
    async def get_target_achievement(target: int = 500):
        return db_module.get_target_achievement(target=target)

    @router.get("/metrics/engineers/{initials}/kpis")
    async def get_engineer_kpis(initials: str):
        return db_module.get_individual_engineer_kpis(initials)

    @router.get("/metrics/engineers/kpis/all")
    async def get_all_engineers_kpis():
        return {"engineers": db_module.get_all_engineers_kpis()}

    return router
