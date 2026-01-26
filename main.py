from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
from typing import Any, Dict
from datetime import datetime
import asyncio
import database as db
import excel_export

app = FastAPI(title="Warehouse Stats Service")

# Initialize database tables on startup
db.init_db()

@app.get("/analytics/daily-totals")
async def analytics_daily_totals():
    return {"days": db.get_daily_totals()}
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
from typing import Any, Dict
from datetime import datetime
import asyncio
import database as db
import excel_export

app = FastAPI(title="Warehouse Stats Service")

# Initialize database tables on startup
db.init_db()

@app.get("/metrics/monthly-momentum")
async def get_monthly_momentum():
    """Get weekly totals for the current month for monthly momentum chart"""
    return db.get_monthly_momentum()

# Enable CORS for TV access from network
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEBHOOK_API_KEY = os.getenv("WEBHOOK_API_KEY", "6LVepDbZkbMwA66Gpl9bWherzT5wKfOl")

# Background task for daily reset
async def check_daily_reset():
    """Check at 18:00 each day and reset daily stats"""
    while True:
        now = datetime.now()
        # If it's 18:00 (6 PM), reset the stats
        if now.hour == 18 and now.minute == 0:
            print(f"[{now}] Daily reset triggered at 18:00")
            try:
                # This clears today's stats for tomorrow's fresh start
                # Stats are cumulative per day, so at 18:00 we let them accumulate tomorrow
                pass  # Stats persist by date, so no action needed - next day starts fresh automatically
            except Exception as e:
                print(f"Error during daily reset: {e}")
            # Wait until next day to avoid multiple resets
            await asyncio.sleep(3600)  # Sleep for 1 hour
        else:
            await asyncio.sleep(60)  # Check every minute

@app.on_event("startup")
async def startup_event():
    """Start the background reset task and sync engineer stats"""
    print("[Startup] Syncing engineer stats from erasures table...")
    try:
        synced = db.sync_engineer_stats_from_erasures()
        print(f"[Startup] Engineer stats sync complete: {synced} records")
    except Exception as e:
        print(f"[Startup] Error syncing engineer stats: {e}")

    try:
        synced_type = db.sync_engineer_stats_type_from_erasures()
        print(f"[Startup] Engineer stats by device type sync complete: {synced_type} records")
    except Exception as e:
        print(f"[Startup] Error syncing engineer stats by device type: {e}")

    asyncio.create_task(check_daily_reset())

@app.post("/hooks/erasure")
async def erasure_hook(req: Request):
    hdr = req.headers.get("Authorization") or req.headers.get("x-api-key")
    if not hdr or (hdr != f"Bearer {WEBHOOK_API_KEY}" and hdr != WEBHOOK_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await req.json()
    event = payload.get("event", "success")  # Default to success if missing
    job_id = payload.get("jobId") or payload.get("assetTag") or payload.get("id") or "unknown"
    
    # Always accept and log for debugging
    print(f"Received webhook: event={event}, jobId={job_id}, payload={payload}")

    # Only deduplicate if we have a real jobId (not "unknown")
    if job_id != "unknown" and db.is_job_seen(job_id):
        return JSONResponse({"status": "ignored", "reason": "duplicate"})

    if event in ["success", "connected"]:  # Accept both success and connected
        db.increment_stat("erased", 1)
        # Only track if we have a real ID
        if job_id != "unknown":
            db.mark_job_seen(job_id)
        stats = db.get_daily_stats()
        return {"status": "ok", "count": stats["erased"]}
    elif event == "failure":
        return {"status": "ok"}
    else:
        # Still accept it and increment counter
        db.increment_stat("erased", 1)
        if job_id != "unknown":
            db.mark_job_seen(job_id)
        stats = db.get_daily_stats()
        return {"status": "ok", "event_accepted": event, "count": stats["erased"]}

@app.get("/metrics/today")
async def get_metrics():
    return db.get_daily_stats()

@app.get("/metrics/yesterday")
async def get_yesterday_metrics():
    return db.get_daily_stats(db.get_yesterday_str())

# ===== Power BI Integration Endpoints =====
@app.get("/api/powerbi/daily-stats")
async def powerbi_daily_stats(start_date: str = None, end_date: str = None):
    """
    Power BI endpoint: Returns daily stats in a table format
    Parameters:
    - start_date: YYYY-MM-DD (optional, defaults to 30 days ago)
    - end_date: YYYY-MM-DD (optional, defaults to today)
    """
    from datetime import datetime, timedelta
    
    if not end_date:
        end_date = datetime.now().date().isoformat()
    if not start_date:
        start_date = (datetime.now().date() - timedelta(days=30)).isoformat()
    
    data = db.get_stats_range(start_date, end_date)
    return {"data": data}

@app.get("/api/powerbi/erasure-events")
async def powerbi_erasure_events(start_date: str = None, end_date: str = None, device_type: str = None):
    """
    Power BI endpoint: Returns detailed erasure events
    Parameters:
    - start_date: YYYY-MM-DD (optional)
    - end_date: YYYY-MM-DD (optional)
    - device_type: filter by device type (optional)
    """
    from datetime import datetime, timedelta
    
    if not end_date:
        end_date = datetime.now().date().isoformat()
    if not start_date:
        start_date = (datetime.now().date() - timedelta(days=30)).isoformat()
    
    events = db.get_erasure_events_range(start_date, end_date, device_type)
    return {"data": events}

@app.get("/api/powerbi/engineer-stats")
async def powerbi_engineer_stats(start_date: str = None, end_date: str = None):
    """
    Power BI endpoint: Returns engineer statistics
    Parameters:
    - start_date: YYYY-MM-DD (optional)
    - end_date: YYYY-MM-DD (optional)
    """
    from datetime import datetime, timedelta
    
    if not end_date:
        end_date = datetime.now().date().isoformat()
    if not start_date:
        start_date = (datetime.now().date() - timedelta(days=30)).isoformat()
    
    stats = db.get_engineer_stats_range(start_date, end_date)
    return {"data": stats}

# New: detailed erasure webhook for richer dashboard (accept GET/POST, robust parsing)
@app.api_route("/hooks/erasure-detail", methods=["GET", "POST"])
async def erasure_detail(req: Request):
    hdr = req.headers.get("Authorization") or req.headers.get("x-api-key")
    if not hdr or (hdr != f"Bearer {WEBHOOK_API_KEY}" and hdr != WEBHOOK_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Robust payload parsing: try JSON, fall back to form/query/raw text
    payload: Dict[str, Any] = {}
    try:
        payload = await req.json()
        if not isinstance(payload, dict):
            payload = {"_body": payload}
    except Exception:
        try:
            raw = await req.body()
            text = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
            import json as _json
            try:
                payload = _json.loads(text)
            except Exception:
                # Try form-encoded
                from urllib.parse import parse_qs
                qs = parse_qs(text)
                payload = {k: v[0] for k, v in qs.items()} if qs else {"_raw": text}
        except Exception:
            payload = {}

    # Merge query params for GET or as fallback
    if req.query_params:
        payload = {**payload, **dict(req.query_params)}

    # Minimal debug print (sanitized)
    print(f"erasure-detail headers={{'Content-Type': '{req.headers.get('content-type', '')}'}} payload_keys={list(payload.keys())}")

    event = (payload.get("event") or "success").strip().lower()
    job_id = payload.get("jobId") or payload.get("assetTag") or payload.get("id")
    device_type = (payload.get("deviceType") or payload.get("device_type") or payload.get("type") or "laptops_desktops").strip().lower()
    initials_raw = payload.get("initials") or payload.get("Engineer Initals") or payload.get("Engineer Initials") or ""
    initials = (initials_raw or "").strip().upper() or None
    duration_sec = payload.get("durationSec") or payload.get("duration")
    try:
        duration_sec = int(duration_sec) if duration_sec is not None else None
    except Exception:
        duration_sec = None
    error_type = payload.get("errorType") or payload.get("error")
    ts_in = payload.get("timestamp")
    # Normalize timestamp to ISO or drop to use UTC now
    ts = None
    if isinstance(ts_in, (int, float)):
        try:
            from datetime import datetime, timezone
            ts = datetime.fromtimestamp(float(ts_in), tz=timezone.utc).isoformat()
        except Exception:
            ts = None
    elif isinstance(ts_in, str) and ts_in.strip():
        s = ts_in.strip()
        try:
            # ISO 8601 with possible 'Z'
            from datetime import datetime
            if s.endswith('Z'):
                s = s.replace('Z', '+00:00')
            try:
                ts = datetime.fromisoformat(s).isoformat()
            except Exception:
                # Try common UK/EU formats
                for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                    try:
                        ts = datetime.strptime(s, fmt).isoformat()
                        break
                    except Exception:
                        continue
        except Exception:
            ts = None

    # Dedup if a real job_id is present
    if job_id and db.is_job_seen(job_id):
        return {"status": "ignored", "reason": "duplicate"}

    db.add_erasure_event(event=event, device_type=device_type, initials=initials,
                         duration_sec=duration_sec, error_type=error_type, job_id=job_id, ts=ts)
    try:
        dbg = db.get_summary_today_month()
        print(f"erasure-detail wrote event={event} type={device_type} jobId={job_id} -> todayTotal={dbg.get('todayTotal')} avg={dbg.get('avgDurationSec')}")
    except Exception as _e:
        print(f"erasure-detail post-insert check failed: {_e}")

    # Keep simple daily erased counter in sync for compatibility when success
    if event in ["success", "connected"]:
        db.increment_stat("erased", 1)
    if job_id:
        db.mark_job_seen(job_id)

    return {"status": "ok"}

# Summary metrics powering the new dashboard
@app.get("/metrics/summary")
async def metrics_summary(date: str = None):
    """Get summary for a specific date (YYYY-MM-DD) or today if not provided"""
    return db.get_summary_today_month(date)

@app.get("/metrics/by-type")
async def metrics_by_type():
    return db.get_counts_by_type_today()

@app.get("/metrics/errors")
async def metrics_errors():
    return db.get_error_distribution_today()

@app.get("/metrics/engineers/top2")
async def metrics_engineers_top(scope: str = "today", type: str | None = None, limit: int = 3):
    return {"engineers": db.top_engineers(scope=scope, device_type=type, limit=limit)}

@app.get("/metrics/engineers/leaderboard")
async def metrics_engineers_leaderboard(scope: str = "today", limit: int = 6, date: str = None):
    return {"items": db.leaderboard(scope=scope, limit=limit, date_str=date)}

# Admin: delete an ingested event by jobId (secured by API key)
@app.post("/admin/delete-event")
async def admin_delete_event(req: Request):
    hdr = req.headers.get("Authorization") or req.headers.get("x-api-key")
    if not hdr or (hdr != f"Bearer {WEBHOOK_API_KEY}" and hdr != WEBHOOK_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = {}
    try:
        body = await req.json()
    except Exception:
        pass
    job_id = (body.get("jobId") if isinstance(body, dict) else None) or req.query_params.get("jobId")
    if not job_id:
        raise HTTPException(status_code=400, detail="jobId is required")

    deleted = db.delete_event_by_job(job_id)
    summary = db.get_summary_today_month()
    return {"deleted": deleted, "jobId": job_id, "summary": summary}

def _extract_initials_from_obj(obj: Any):
    # Try common explicit keys first
    if isinstance(obj, dict):
        for key in [
            "initials",
            "engineerInitials",
            "engineer_initials",
            "Engineer Initals",
            "Engineer Initials",
            "engineerInitals",
        ]:
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().upper()

    # Deep search for any key containing 'initial'
    def deep(o: Any):
        if isinstance(o, dict):
            for k, v in o.items():
                # Prefer direct initial-like keys
                if isinstance(k, str) and "initial" in k.lower():
                    if isinstance(v, str) and v.strip():
                        return v.strip().upper()
                res = deep(v)
                if res:
                    return res
        elif isinstance(o, list):
            for item in o:
                res = deep(item)
                if res:
                    return res
        return None

    return deep(obj)


@app.api_route("/hooks/engineer-erasure", methods=["GET", "POST"])
async def engineer_erasure_hook(req: Request):
    hdr = req.headers.get("Authorization") or req.headers.get("x-api-key")
    if not hdr or (hdr != f"Bearer {WEBHOOK_API_KEY}" and hdr != WEBHOOK_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Merge JSON body (if any) and query params to a single payload
    payload: Dict[str, Any] = {}
    try:
        payload = await req.json()
        if not isinstance(payload, dict):
            payload = {"_body": payload}
    except Exception:
        payload = {}

    # Include query params as fallback
    if req.query_params:
        payload = {**payload, **dict(req.query_params)}

    initials = _extract_initials_from_obj(payload) or ""
    device_type = (
        payload.get("deviceType") or
        payload.get("device_type") or
        payload.get("type") or
        "laptops_desktops"
    ).strip().lower()

    print(f"Received engineer erasure: initials={initials}, payload={payload}")

    if not initials:
        return JSONResponse({"status": "error", "reason": "missing initials"}, status_code=400)

    # Increment count for this engineer (overall and per device type)
    db.increment_engineer_count(initials, 1)
    db.increment_engineer_type_count(device_type, initials, 1)
    engineers = db.get_top_engineers(limit=10)
    engineer_count = next((e["count"] for e in engineers if e["initials"] == initials), 0)

    return {"status": "ok", "engineer": initials, "count": engineer_count}

@app.get("/metrics/top-engineers")
async def get_top_engineers():
    # Return top 3 engineers by erasure count
    engineers = db.get_top_engineers(limit=3)
    return {"engineers": engineers}

@app.get("/metrics/engineers/top-by-type")
async def get_top_engineers_by_type(type: str = "laptops_desktops", scope: str = "today", limit: int = 6):
    engineers = db.top_engineers(scope=scope, device_type=type, limit=limit)
    return {"engineers": engineers, "type": type}

@app.get("/analytics/weekly-category-trends")
async def get_weekly_category_trends():
    """Get last 7 days of category trends for flip cards"""
    trends = db.get_weekly_category_trends()
    return {"trends": trends}

@app.get("/analytics/weekly-engineer-stats")
async def get_weekly_engineer_stats():
    """Get weekly totals and consistency scores for engineers"""
    stats = db.get_weekly_engineer_stats()
    return {"stats": stats}

@app.get("/analytics/peak-hours")
async def get_peak_hours():
    """Get hourly breakdown for today"""
    hours = db.get_peak_hours()
    return {"hours": hours}

@app.get("/analytics/day-of-week-patterns")
async def get_day_of_week_patterns():
    """Get average erasures by day of week"""
    patterns = db.get_day_of_week_patterns()
    return {"patterns": patterns}

@app.get("/competitions/speed-challenge")
async def get_speed_challenge(window: str = "am"):
    """Get speed challenge leaderboard and status for AM or PM"""
    stats = db.get_speed_challenge_stats(window)
    status = db.get_speed_challenge_status(window)
    return {
        "leaderboard": stats,
        "status": status
    }

@app.get("/competitions/category-specialists")
async def get_category_specialists():
    """Get top 3 specialists for each equipment category"""
    specialists = db.get_category_specialists()
    return {"specialists": specialists}

@app.get("/competitions/consistency")
async def get_consistency():
    """Get consistency rankings - engineers with steadiest pace"""
    stats = db.get_consistency_stats()
    return {"leaderboard": stats}

@app.get("/metrics/records")
async def get_records():
    """Get historical records and milestones"""
    records = db.get_records_and_milestones()
    return records

@app.get("/metrics/weekly")
async def get_weekly():
    """Get weekly statistics (past 7 days)"""
    weekly = db.get_weekly_stats()
    return weekly

@app.get("/metrics/performance-trends")
async def get_performance_trends(target: int = 500):
    """Get performance trends: WoW, MoM, rolling averages"""
    trends = db.get_performance_trends(target=target)
    return trends

@app.get("/metrics/target-achievement")
async def get_target_achievement(target: int = 500):
    """Get target achievement metrics: days hitting target, streaks, projections"""
    achievement = db.get_target_achievement(target=target)
    return achievement

@app.get("/metrics/engineers/{initials}/kpis")
async def get_engineer_kpis(initials: str):
    """Get comprehensive KPI metrics for a specific engineer"""
    kpis = db.get_individual_engineer_kpis(initials)
    return kpis

@app.get("/metrics/engineers/kpis/all")
async def get_all_engineers_kpis():
    """Get KPI metrics for all engineers"""
    kpis = db.get_all_engineers_kpis()
    return {"engineers": kpis}

@app.post("/export/excel")
async def export_excel(req: Request):
    """Generate multi-sheet Excel export of warehouse stats"""
    try:
        body = await req.json()
        sheets_data = body.get("sheetsData", {})
        
        excel_file = excel_export.create_excel_report(sheets_data)
        
        return StreamingResponse(
            iter([excel_file.getvalue()]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=warehouse-stats.xlsx"}
        )
    except Exception as e:
        print(f"Excel export error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Serve static files (HTML, CSS, JS)
app.mount("/", StaticFiles(directory=".", html=True), name="static")
