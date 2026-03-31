from datetime import date, datetime, timedelta

from fastapi import APIRouter


def _get_period_range(period: str):
    """Return (start_date, end_date, label) for a period string."""
    today = datetime.now().date()

    if period == "today":
        return today, today, "Today"
    if period == "this_week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=4) if today.weekday() >= 5 else today
        return start, end, "This Week"
    if period == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=4)
        return start, end, "Last Week"
    if period == "this_month":
        start = today.replace(day=1)
        end = today
        return start, end, "This Month"
    if period == "last_month":
        last_month_end = today.replace(day=1) - timedelta(days=1)
        start = last_month_end.replace(day=1)
        end = last_month_end
        return start, end, "Last Month"
    if period == "this_year":
        start = date(today.year, 1, 1)
        end = today
        return start, end, "This Year"
    if period == "last_year":
        last_year = today.year - 1
        start = date(last_year, 1, 1)
        end = date(last_year, 12, 31)
        return start, end, "Last Year"
    if period == "all_time":
        return None, None, "All Time"
    return None, None, "Custom"


def create_erasure_insights_router(*, db_module) -> APIRouter:
    router = APIRouter()

    @router.get("/api/insights/erasure")
    async def erasure_insights(period: str = "this_week"):
        start_date, end_date, label = _get_period_range(period)
        if not start_date or not end_date:
            return {"period": label, "error": "Unsupported period"}

        stats = db_module.get_stats_range(start_date.isoformat(), end_date.isoformat())
        engineer_stats = db_module.get_engineer_stats_range(start_date.isoformat(), end_date.isoformat())

        total_erased = sum(row.get("erased", 0) for row in stats)
        day_count = max(1, (end_date - start_date).days + 1)
        avg_per_day = round(total_erased / day_count, 1)

        active_engineers = {
            row.get("initials")
            for row in engineer_stats
            if row.get("initials") and (row.get("count") or 0) > 0
        }
        active_count = len(active_engineers)
        avg_per_engineer = round(total_erased / active_count, 1) if active_count else 0

        projection = None
        today = datetime.now().date()
        if period == "this_month":
            total_days = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            total_days = total_days.day
            days_elapsed = max(1, today.day)
            pace = total_erased / days_elapsed
            projection = round(pace * total_days)

        rolling_7 = 0
        rolling_30 = 0
        trend_pct = 0
        try:
            end_rolling = datetime.now().date()
            start_rolling = end_rolling - timedelta(days=29)
            rolling_stats = db_module.get_stats_range(start_rolling.isoformat(), end_rolling.isoformat())
            daily_map = {row["date"]: row.get("erased", 0) for row in rolling_stats}
            daily_values = []
            cursor_date = start_rolling
            while cursor_date <= end_rolling:
                daily_values.append(daily_map.get(cursor_date.isoformat(), 0))
                cursor_date += timedelta(days=1)
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

        return {
            "period": label,
            "dateRange": f"{start_date} to {end_date}",
            "total": total_erased,
            "avgPerDay": avg_per_day,
            "rolling7DayAvg": rolling_7,
            "rolling30DayAvg": rolling_30,
            "trend7DayPct": trend_pct,
            "activeEngineers": active_count,
            "avgPerEngineer": avg_per_engineer,
            "projection": projection,
        }

    @router.get("/api/insights/erasure-engineers")
    async def erasure_engineer_insights(period: str = "this_week", limit: int = 10):
        start_date, end_date, label = _get_period_range(period)
        if not start_date or not end_date:
            return {"period": label, "error": "Unsupported period"}

        day_count = max(1, (end_date - start_date).days + 1)
        stats = db_module.get_engineer_stats_range(start_date.isoformat(), end_date.isoformat())

        totals = {}
        active_days = {}
        for row in stats:
            initials = row.get("initials")
            if not initials:
                continue
            totals[initials] = totals.get(initials, 0) + (row.get("count") or 0)
            active_days.setdefault(initials, set()).add(row.get("date"))

        prev_start = start_date - timedelta(days=day_count)
        prev_end = start_date - timedelta(days=1)
        prev_stats = db_module.get_engineer_stats_range(prev_start.isoformat(), prev_end.isoformat())
        prev_totals = {}
        for row in prev_stats:
            initials = row.get("initials")
            if not initials:
                continue
            prev_totals[initials] = prev_totals.get(initials, 0) + (row.get("count") or 0)

        results = []
        for initials, total in totals.items():
            avg_per_day = round(total / day_count, 1)
            active_count = len(active_days.get(initials, []))
            avg_per_active_day = round(total / active_count, 1) if active_count else 0
            prev_avg = round((prev_totals.get(initials, 0) / day_count), 1)
            trend_pct = 0
            if prev_avg > 0:
                trend_pct = round(((avg_per_day - prev_avg) / prev_avg) * 100, 1)
            results.append(
                {
                    "initials": initials,
                    "total": total,
                    "avgPerDay": avg_per_day,
                    "avgPerActiveDay": avg_per_active_day,
                    "trendPct": trend_pct,
                }
            )

        results.sort(key=lambda x: x["total"], reverse=True)
        return {"period": label, "data": results[: max(1, limit)]}

    return router
