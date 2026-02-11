from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
from typing import Any, Dict
from datetime import datetime, timedelta, date
import asyncio
import database as db
import excel_export
import ipaddress
import json
import hashlib
import secrets
import httpx  # For making API calls to Blancco
from time import time

app = FastAPI(title="Warehouse Stats Service")

# ============= BLANCCO API CONFIG =============
BLANCCO_API_URL = os.getenv("BLANCCO_API_URL", "")  # Set this if Blancco has an API
BLANCCO_API_KEY = os.getenv("BLANCCO_API_KEY", "")

async def fetch_blancco_device_details(job_id: str):
    """
    Fetch device details from Blancco API using job ID.
    Returns dict with manufacturer, model, drive info, or None if unavailable.
    """
    if not BLANCCO_API_URL or not job_id:
        return None
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            headers = {}
            if BLANCCO_API_KEY:
                headers["Authorization"] = f"Bearer {BLANCCO_API_KEY}"
            
            # Adjust this endpoint to match Blancco's actual API
            response = await client.get(
                f"{BLANCCO_API_URL}/reports/{job_id}",
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                # Extract hardware details from Blancco response
                # Adjust field names based on actual Blancco API response
                return {
                    "manufacturer": data.get("hardware", {}).get("manufacturer"),
                    "model": data.get("hardware", {}).get("model"),
                    "drive_size": data.get("storage", {}).get("totalCapacity"),
                    "drive_count": data.get("storage", {}).get("driveCount"),
                    "drive_type": data.get("storage", {}).get("type")
                }
    except Exception as e:
        print(f"[BLANCCO API] Failed to fetch device details for job {job_id}: {e}")
    
    return None

# ============= SECURITY CONFIG =============
# Local network subnet(s) that don't require auth (e.g., 192.168.x.x, 10.x.x.x)
LOCAL_NETWORKS = [
    ipaddress.ip_network("192.168.0.0/16"),   # 192.168.x.x
    ipaddress.ip_network("10.0.0.0/8"),       # 10.x.x.x
    ipaddress.ip_network("172.16.0.0/12"),    # 172.16.x.x
]

# Manager and admin passwords for external access (set via environment or use defaults)
MANAGER_PASSWORD = os.getenv("DASHBOARD_MANAGER_PASSWORD", "Gr33n5af3!")
ADMIN_PASSWORD = os.getenv("DASHBOARD_ADMIN_PASSWORD", "P!nkarrow")

# Device token storage (persistent across redeployments)
DEVICE_TOKENS_FILE = "device_tokens.json"
POWERBI_API_KEY_FILE = "powerbi_api_key.txt"
DEVICE_TOKEN_EXPIRY_DAYS = 7  # Remember device for 7 days

QA_CACHE_TTL_SECONDS = 60
QA_CACHE: Dict[str, Dict[str, object]] = {}

def _get_cached_response(cache_key: str):
    entry = QA_CACHE.get(cache_key)
    if not entry:
        return None
    if time() - entry.get("ts", 0) > QA_CACHE_TTL_SECONDS:
        return None
    return entry.get("data")

def _set_cached_response(cache_key: str, data: Dict[str, object]):
    QA_CACHE[cache_key] = {"ts": time(), "data": data}
    return data

def load_device_tokens():
    """Load device tokens from persistent storage."""
    try:
        if os.path.exists(DEVICE_TOKENS_FILE):
            with open(DEVICE_TOKENS_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_device_tokens(tokens):
    """Save device tokens to persistent storage."""
    try:
        with open(DEVICE_TOKENS_FILE, 'w') as f:
            json.dump(tokens, f)
    except Exception as e:
        print(f"Error saving device tokens: {e}")

def get_powerbi_api_key() -> str:
    """Load or create a Power BI API key for service refreshes."""
    env_key = os.getenv("POWERBI_API_KEY", "").strip()
    if env_key:
        return env_key

    try:
        if os.path.exists(POWERBI_API_KEY_FILE):
            with open(POWERBI_API_KEY_FILE, "r") as f:
                file_key = f.read().strip()
            if file_key:
                return file_key
    except Exception as e:
        print(f"Error reading Power BI API key file: {e}")

    new_key = secrets.token_urlsafe(32)
    try:
        with open(POWERBI_API_KEY_FILE, "w") as f:
            f.write(new_key)
    except Exception as e:
        print(f"Error saving Power BI API key file: {e}")
    print("Power BI API key generated. Set POWERBI_API_KEY to override.")
    return new_key

def generate_device_token(user_agent: str, client_ip: str) -> str:
    """Generate a unique device token based on device fingerprint."""
    # Create fingerprint from user agent + IP
    fingerprint = f"{user_agent}:{client_ip}"
    # Add randomness to make it more secure
    token = secrets.token_urlsafe(32) + ":" + hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
    return token

def is_device_token_valid(token: str) -> bool:
    """Check if a device token is valid and not expired."""
    tokens = load_device_tokens()
    if token in tokens:
        expiry = datetime.fromisoformat(tokens[token]['expiry'])
        if datetime.now() < expiry:
            return True
        else:
            # Token expired, remove it
            del tokens[token]
            save_device_tokens(tokens)
    return False

def is_local_network(client_ip: str) -> bool:
    """Check if client IP is on local network (no auth needed)."""
    try:
        ip = ipaddress.ip_address(client_ip)
        return any(ip in network for network in LOCAL_NETWORKS)
    except ValueError:
        return False

def get_client_ip(request: Request) -> str:
    """Get real client IP from X-Forwarded-For header or request client."""
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"

def get_role_from_request(request: Request) -> str | None:
    """Resolve role from request auth header or device token."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == ADMIN_PASSWORD:
            return "admin"
        if token == MANAGER_PASSWORD:
            return "manager"
        if is_device_token_valid(token):
            tokens = load_device_tokens()
            return tokens.get(token, {}).get("role")
    return None

def require_manager_or_admin(request: Request):
    role = get_role_from_request(request)
    if role not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="Manager access required for exports")

def require_admin(request: Request):
    role = get_role_from_request(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """
    Middleware to check authentication on API calls and page access.
    Local network = automatic access.
    External = requires password.
    """
    # Get real client IP from X-Forwarded-For header (set by reverse proxies like Render)
    client_ip = get_client_ip(request)
    
    # Get user agent to detect TV browsers (FireStick Silk)
    user_agent = request.headers.get("User-Agent", "").lower()
    is_tv_browser = "silk" in user_agent or "firetv" in user_agent or "aftt" in user_agent
    
    # Allow static assets without auth
    if request.url.path.startswith(("/styles.css", "/assets/", "/vendor/")):
        return await call_next(request)

    # Allow admin page to load (it will prompt for admin password)
    if request.url.path == "/admin.html":
        return await call_next(request)
    
    # Allow auth endpoints without prior auth
    if request.url.path.startswith("/auth/"):
        return await call_next(request)
    
    # Auto-allow TV browsers (FireStick Silk) - they're physically in the office
    if is_tv_browser:
        print(f"TV browser detected (User-Agent: {user_agent[:50]}...) - auto-allowing access")
        return await call_next(request)
    
    # Check if local network (viewer access)
    if is_local_network(client_ip):
        # Admin paths still require admin password/token
        if request.url.path.startswith("/admin"):
            pass
        else:
            return await call_next(request)

    # Allow Power BI API access via static API key
    if request.url.path.startswith("/api/powerbi") and POWERBI_API_KEY:
        auth_header = request.headers.get("Authorization", "")
        header_key = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
        query_key = request.query_params.get("api_key")
        bearer_key = auth_header[7:] if auth_header.startswith("Bearer ") else ""
        if header_key == POWERBI_API_KEY or query_key == POWERBI_API_KEY or bearer_key == POWERBI_API_KEY:
            return await call_next(request)
    
    # Check for valid device token (remembered device)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if is_device_token_valid(token):
            tokens = load_device_tokens()
            role = tokens.get(token, {}).get("role")
            if request.url.path.startswith("/admin") and role != "admin":
                return JSONResponse(status_code=403, content={"detail": "Admin access required."})
            return await call_next(request)
    
    # External access: check for password
    # Check Authorization header with password
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == ADMIN_PASSWORD:
            return await call_next(request)
        if token == MANAGER_PASSWORD:
            if request.url.path.startswith("/admin"):
                return JSONResponse(status_code=403, content={"detail": "Admin access required."})
            return await call_next(request)
    
    # Check query parameter (for page loads)
    if request.query_params.get("auth") in (ADMIN_PASSWORD, MANAGER_PASSWORD):
        if request.query_params.get("auth") == MANAGER_PASSWORD and request.url.path.startswith("/admin"):
            return JSONResponse(status_code=403, content={"detail": "Admin access required."})
        return await call_next(request)
    
    # Check Basic Auth format
    if auth_header.startswith("Basic "):
        import base64
        try:
            decoded = base64.b64decode(auth_header[6:]).decode()
            if ":" in decoded:
                _, password = decoded.split(":", 1)
                if password == ADMIN_PASSWORD:
                    return await call_next(request)
                if password == MANAGER_PASSWORD and not request.url.path.startswith("/admin"):
                    return await call_next(request)
        except:
            pass
    
    # For API requests, return 401
    if request.url.path.startswith("/metrics") or request.url.path.startswith("/analytics") or request.url.path.startswith("/competitions") or request.url.path.startswith("/export") or request.url.path.startswith("/api") or request.url.path.startswith("/admin"):
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized. External access requires password."}
        )
    
    # For page load, redirect to login
    if request.url.path == "/" or request.url.path == "/index.html":
        return FileResponse("index.html")  # Will add login UI to index.html
    
    return await call_next(request)
# New endpoint: Get total erasures for a device type and period
@app.get("/metrics/total-by-type")
async def get_total_by_type(type: str = "laptops_desktops", scope: str = "today"):
    """Return the total erasures for a given device type and period (today, month, all)."""
    from datetime import date
    conn = db.sqlite3.connect(db.DB_PATH)
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
        key_col = "date"
        key_val = date.today().isoformat()
        where = f"{key_col} = ? AND event = 'success' AND device_type = ?"
        params = [key_val, type]
    cursor.execute(f"SELECT COUNT(1) FROM erasures WHERE {where}", params)
    total = cursor.fetchone()[0]
    conn.close()
    return {"total": total, "type": type, "scope": scope}

# --- ALL TIME TOTALS ENDPOINT ---
@app.get("/metrics/all-time-totals")
async def get_all_time_totals(group_by: str = None):
    """Get all-time erasure totals. Optionally group by device_type or initials."""
    result = db.get_all_time_totals(group_by=group_by)
    return {"allTimeTotal": result} if not group_by else result

# Initialize database tables on startup
db.init_db()

# For sparkline compatibility: hourly-totals endpoint
@app.get("/analytics/hourly-totals")
async def analytics_hourly_totals():
    """Get hourly erasure totals for today (shift hours)"""
    return {"hours": db.get_peak_hours()}

# Place the endpoint here, after app is defined
@app.get("/analytics/daily-totals")
async def analytics_daily_totals():
    return {"days": db.get_daily_totals()}

@app.get("/metrics/monthly-momentum")
async def get_monthly_momentum():
    """Get weekly totals for the current month for monthly momentum chart"""
    return db.get_monthly_momentum()


# Endpoint: Mon-Fri daily erasure totals for current week
@app.get("/analytics/weekly-daily-totals")
async def analytics_weekly_daily_totals():
    """Return Mon-Fri daily erasure totals for the current week (Monday to Friday)."""
    from datetime import date, timedelta
    import calendar
    today = date.today()
    # Find this week's Monday
    monday = today - timedelta(days=today.weekday())
    days = []
    for i in range(5):  # Mon-Fri
        d = monday + timedelta(days=i)
        days.append(d)
    # Query DB for each day
    import database as db
    result = []
    for d in days:
        stats = db.get_daily_stats(d.isoformat())
        result.append({
            "date": d.isoformat(),
            "weekday": calendar.day_abbr[d.weekday()],
            "count": stats.get("erased", 0)
        })
    return {"days": result}

# Enable CORS for TV access from network (more restricted now with auth middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Still allow all origins, but auth middleware controls actual access
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEBHOOK_API_KEY = os.getenv("WEBHOOK_API_KEY", "6LVepDbZkbMwA66Gpl9bWherzT5wKfOl")
POWERBI_API_KEY = get_powerbi_api_key()

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
    qa_data = []
    try:
        import qa_export
        qa_data = qa_export.get_qa_daily_totals_range(
            datetime.fromisoformat(start_date).date(),
            datetime.fromisoformat(end_date).date()
        )
    except Exception as e:
        print(f"Power BI QA daily merge error: {e}")

    qa_by_date = {row.get("date"): row for row in qa_data}
    for row in data:
        qa_row = qa_by_date.get(row.get("date"), {})
        row["qaApp"] = qa_row.get("qaApp", 0)  # Sorting scans
        row["deQa"] = qa_row.get("deQa", 0)
        row["nonDeQa"] = qa_row.get("nonDeQa", 0)
        row["qaTotal"] = qa_row.get("qaTotal", 0)  # QA only (DE + Non-DE, no sorting)

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

@app.get("/api/powerbi/qa-daily")
async def powerbi_qa_daily(start_date: str = None, end_date: str = None):
    """
    Power BI endpoint: Returns QA daily totals
    Parameters:
    - start_date: YYYY-MM-DD (optional, defaults to 30 days ago)
    - end_date: YYYY-MM-DD (optional, defaults to today)
    """
    from datetime import datetime, timedelta
    import qa_export

    end = datetime.now().date() if not end_date else datetime.fromisoformat(end_date).date()
    start = (end - timedelta(days=30)) if not start_date else datetime.fromisoformat(start_date).date()
    daily = qa_export.get_qa_daily_totals_range(start, end)
    return {"data": daily}

@app.get("/api/powerbi/device-history")
async def powerbi_device_history(start_date: str = None, end_date: str = None):
    """
    Power BI endpoint: Returns device history (erasure + sorting)
    Parameters:
    - start_date: YYYY-MM-DD (optional, defaults to 30 days ago)
    - end_date: YYYY-MM-DD (optional, defaults to today)
    """
    from datetime import datetime, timedelta
    import qa_export

    end = datetime.now().date() if not end_date else datetime.fromisoformat(end_date).date()
    start = (end - timedelta(days=30)) if not start_date else datetime.fromisoformat(start_date).date()
    history = qa_export.get_device_history_range(start, end)
    return {"data": history}

@app.get("/api/powerbi/qa-engineer")
async def powerbi_qa_engineer(start_date: str = None, end_date: str = None):
    """
    Power BI endpoint: Returns per-engineer QA daily breakdown
    Parameters:
    - start_date: YYYY-MM-DD (optional, defaults to 30 days ago)
    - end_date: YYYY-MM-DD (optional, defaults to today)
    """
    from datetime import datetime, timedelta
    import qa_export

    end = datetime.now().date() if not end_date else datetime.fromisoformat(end_date).date()
    start = (end - timedelta(days=30)) if not start_date else datetime.fromisoformat(start_date).date()
    data = qa_export.get_qa_engineer_daily_breakdown_range(start, end)
    return {"data": data}

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

@app.get("/api/insights/erasure")
async def erasure_insights(period: str = "this_week"):
    """Return averages and trajectory data for erasures."""
    start_date, end_date, label = _get_period_range(period)
    if not start_date or not end_date:
        return {
            "period": label,
            "error": "Unsupported period"
        }

    stats = db.get_stats_range(start_date.isoformat(), end_date.isoformat())
    engineer_stats = db.get_engineer_stats_range(start_date.isoformat(), end_date.isoformat())

    total_erased = sum(row.get("erased", 0) for row in stats)
    day_count = max(1, (end_date - start_date).days + 1)
    avg_per_day = round(total_erased / day_count, 1)

    active_engineers = {
        row.get("initials") for row in engineer_stats
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

    # Rolling averages for last 30 days
    rolling_7 = 0
    rolling_30 = 0
    trend_pct = 0
    try:
        end_rolling = datetime.now().date()
        start_rolling = end_rolling - timedelta(days=29)
        rolling_stats = db.get_stats_range(start_rolling.isoformat(), end_rolling.isoformat())
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
    except Exception as e:
        print(f"Erasure rolling avg error: {e}")

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

@app.get("/api/insights/qa")
async def qa_insights(period: str = "this_week"):
    """Return averages and trajectory data for QA totals (QA App + DE + Non-DE)."""
    try:
        import qa_export
        cache_key = f"qa_insights:{period}"
        cached = _get_cached_response(cache_key)
        if cached is not None:
            return cached
        start_date, end_date, label = qa_export.get_week_dates(period)

        qa_data = qa_export.get_weekly_qa_comparison(start_date, end_date)
        de_qa_data = qa_export.get_de_qa_comparison(start_date, end_date)
        non_de_qa_data = qa_export.get_non_de_qa_comparison(start_date, end_date)

        total_qa_app = sum(stats["total"] for name, stats in qa_data.items() if name.lower() != '(unassigned)') if qa_data else 0
        total_de = sum(stats["total"] for name, stats in de_qa_data.items() if name.lower() != '(unassigned)') if de_qa_data else 0
        total_non_de = sum(stats["total"] for name, stats in non_de_qa_data.items() if name.lower() != '(unassigned)') if non_de_qa_data else 0
        combined_total = total_qa_app + total_de + total_non_de

        day_count = max(1, (end_date - start_date).days + 1)
        avg_per_day = round(combined_total / day_count, 1)

        active_engineers = set()
        for name, stats in (qa_data or {}).items():
            if name.lower() != '(unassigned)' and stats.get("total", 0) > 0:
                active_engineers.add(name)
        for name, stats in (de_qa_data or {}).items():
            if name.lower() != '(unassigned)' and stats.get("total", 0) > 0:
                active_engineers.add(name)
        for name, stats in (non_de_qa_data or {}).items():
            if name.lower() != '(unassigned)' and stats.get("total", 0) > 0:
                active_engineers.add(name)
        active_count = len(active_engineers)
        avg_per_engineer = round(combined_total / active_count, 1) if active_count else 0

        projection = None
        today = datetime.now().date()
        if period == "this_month":
            total_days = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            total_days = total_days.day
            days_elapsed = max(1, today.day)
            pace = combined_total / days_elapsed
            projection = round(pace * total_days)

        # Rolling averages for last 30 days (QA only, no sorting)
        rolling_7 = 0
        rolling_30 = 0
        trend_pct = 0
        try:
            end_rolling = datetime.now().date()
            start_rolling = end_rolling - timedelta(days=29)
            daily_totals = qa_export.get_qa_daily_totals_range(start_rolling, end_rolling)
            # Use qaTotal (DE + Non-DE only, excludes sorting)
            daily_values = [row.get("qaTotal", row.get("deQa", 0) + row.get("nonDeQa", 0)) for row in daily_totals]
            if daily_values:
                rolling_30 = round(sum(daily_values) / len(daily_values), 1)
                last_7 = daily_values[-7:]
                prev_7 = daily_values[-14:-7] if len(daily_values) >= 14 else []
                rolling_7 = round(sum(last_7) / max(1, len(last_7)), 1)
                if prev_7 and sum(prev_7) > 0:
                    prev_avg = sum(prev_7) / len(prev_7)
                    trend_pct = round(((rolling_7 - prev_avg) / prev_avg) * 100, 1)
        except Exception as e:
            print(f"QA rolling avg error: {e}")

        # QA-only totals (DE + Non-DE, excludes sorting)
        qa_only_total = total_de + total_non_de
        qa_only_avg_per_day = round(qa_only_total / day_count, 1)
        qa_only_avg_per_engineer = round(qa_only_total / active_count, 1) if active_count else 0

        result = {
            "period": label,
            "dateRange": f"{start_date} to {end_date}",
            "total": qa_only_total,  # QA only (DE + Non-DE, no sorting)
            "combinedTotal": combined_total,  # Everything including sorting
            "breakdown": {
                "qaApp": total_qa_app,  # Sorting
                "deQa": total_de,
                "nonDeQa": total_non_de
            },
            "avgPerDay": qa_only_avg_per_day,
            "rolling7DayAvg": rolling_7,
            "rolling30DayAvg": rolling_30,
            "trend7DayPct": trend_pct,
            "activeEngineers": active_count,
            "avgPerEngineer": qa_only_avg_per_engineer,
            "projection": projection,
        }
        return _set_cached_response(cache_key, result)
    except Exception as e:
        print(f"QA insights error: {e}")
        return {"error": "Failed to compute QA insights"}

@app.get("/api/qa-trends")
async def qa_trends(period: str = "this_week"):
    """Return QA trend series for sparklines."""
    try:
        import qa_export
        today = datetime.now().date()

        cache_key = f"qa_trends:{period}"
        cached = _get_cached_response(cache_key)
        if cached is not None:
            return cached

        if period == "today":
            hourly = qa_export.get_qa_hourly_totals(today)
            result = {
                "period": "Today",
                "granularity": "hour",
                "series": hourly
            }
            return _set_cached_response(cache_key, result)

        if period == "all_time":
            min_date, max_date = qa_export.get_qa_data_bounds()
            if max_date:
                end_date = max_date
                start_date = max_date - timedelta(days=29)
                label = "All Time (Last 30 Days)"
            else:
                start_date = today - timedelta(days=29)
                end_date = today
                label = "All Time (Last 30 Days)"
        else:
            start_date, end_date, label = qa_export.get_week_dates(period)

        daily = qa_export.get_qa_daily_totals_range(start_date, end_date)
        result = {
            "period": label,
            "granularity": "day",
            "series": daily
        }
        return _set_cached_response(cache_key, result)
    except Exception as e:
        print(f"QA trends error: {e}")
        return {"error": "Failed to compute QA trends"}

@app.get("/api/insights/erasure-engineers")
async def erasure_engineer_insights(period: str = "this_week", limit: int = 10):
    """Return per-engineer averages and trends for erasures."""
    start_date, end_date, label = _get_period_range(period)
    if not start_date or not end_date:
        return {"period": label, "error": "Unsupported period"}

    day_count = max(1, (end_date - start_date).days + 1)
    stats = db.get_engineer_stats_range(start_date.isoformat(), end_date.isoformat())

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
    prev_stats = db.get_engineer_stats_range(prev_start.isoformat(), prev_end.isoformat())
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
        results.append({
            "initials": initials,
            "total": total,
            "avgPerDay": avg_per_day,
            "avgPerActiveDay": avg_per_active_day,
            "trendPct": trend_pct
        })

    results.sort(key=lambda x: x["total"], reverse=True)
    return {"period": label, "data": results[:max(1, limit)]}

@app.get("/api/insights/qa-engineers")
async def qa_engineer_insights(period: str = "this_week", limit: int = 10):
    """Return per-engineer averages and trends for QA totals."""
    try:
        import qa_export
        cache_key = f"qa_engineers:{period}:{limit}"
        cached = _get_cached_response(cache_key)
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
            if name.lower() == '(unassigned)':
                continue
            total = sum(daily.values())
            active_days = len([v for v in daily.values() if v > 0])
            avg_per_day = round(total / day_count, 1)
            avg_per_active_day = round(total / active_days, 1) if active_days else 0
            prev_total = sum(prev_data.get(name, {}).values())
            prev_avg = round(prev_total / day_count, 1)
            trend_pct = 0
            if prev_avg > 0:
                trend_pct = round(((avg_per_day - prev_avg) / prev_avg) * 100, 1)
            results.append({
                "name": name,
                "total": total,
                "avgPerDay": avg_per_day,
                "avgPerActiveDay": avg_per_active_day,
                "trendPct": trend_pct
            })

        results.sort(key=lambda x: x["total"], reverse=True)
        result = {"period": label, "data": results[:max(1, limit)]}
        return _set_cached_response(cache_key, result)
    except Exception as e:
        print(f"QA engineer insights error: {e}")
        return {"error": "Failed to compute QA engineer insights"}

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

    # Debug: Log full payload to see what Blancco is sending
    print(f"[WEBHOOK DEBUG] Full payload received:")
    print(f"  Headers: Content-Type={req.headers.get('content-type', '')}")
    print(f"  Payload keys: {list(payload.keys())}")
    print(f"  Full payload: {payload}")

    event = (payload.get("event") or "success").strip().lower()
    job_id = payload.get("jobId") or payload.get("assetTag") or payload.get("id")
    device_type = (payload.get("deviceType") or payload.get("device_type") or payload.get("type") or "laptops_desktops").strip().lower()
    initials_raw = payload.get("initials") or payload.get("Engineer Initals") or payload.get("Engineer Initials") or ""
    initials = (initials_raw or "").strip().upper() or None
    def _clean_placeholder(value):
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            upper = cleaned.upper()
            if cleaned.startswith("<REPORTPATH") or "<REPORTPATH" in cleaned:
                return None
            if "<SYSTEM_" in upper or "SYSTEM MANUFACTURER" in upper:
                return None
            return cleaned
        return value

    duration_sec = _clean_placeholder(payload.get("durationSec") or payload.get("duration"))
    try:
        if isinstance(duration_sec, str) and ':' in duration_sec:
            # Parse HH:MM:SS format
            parts = duration_sec.split(':')
            if len(parts) == 3:
                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                duration_sec = h * 3600 + m * 60 + s
            else:
                duration_sec = None
        else:
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

    # Extract device details from payload (Blancco built-in variables)
    # Using built-in Blancco variables: <MANUFACTURER> and <MODEL>
    # Note: <SYSTEM SERIAL>, <DISK SERIAL>, <DISK CAPACITY> are not available as built-in variables
    manufacturer = _clean_placeholder(payload.get("manufacturer"))
    model = _clean_placeholder(payload.get("model"))
    system_serial = _clean_placeholder(
        payload.get("system_serial")
        or payload.get("systemSerial")
        or payload.get("system-serial")
        or payload.get("systemSerialNumber")
        or payload.get("serial")
    ) or ""
    disk_serial = _clean_placeholder(
        payload.get("disk_serial")
        or payload.get("diskSerial")
        or payload.get("disk-serial")
        or payload.get("diskSerialNumber")
    ) or ""
    disk_capacity = _clean_placeholder(
        payload.get("disk_capacity")
        or payload.get("diskCapacity")
        or payload.get("drive_size")
        or payload.get("driveSize")
    ) or ""

    if isinstance(disk_capacity, str):
        try:
            disk_capacity = int(float(disk_capacity))
        except:
            pass
    
    # Log what we found
    if manufacturer or model:
        print(f"[DEVICE DETAILS] Captured from payload: manufacturer={manufacturer}, model={model}")

    db.add_erasure_event(event=event, device_type=device_type, initials=initials,
                         duration_sec=duration_sec, error_type=error_type, job_id=job_id, ts=ts,
                         manufacturer=manufacturer, model=model, system_serial=system_serial,
                         disk_serial=disk_serial, disk_capacity=disk_capacity)
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
async def metrics_summary(date: str = None, startDate: str = None, endDate: str = None):
    """Get summary for a specific date (YYYY-MM-DD), date range, or today if not provided"""
    if startDate and endDate:
        return db.get_summary_date_range(startDate, endDate)
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

@app.get("/metrics/engineers/weekly-stats")
async def metrics_engineers_weekly_stats(startDate: str, endDate: str):
    """Get weekly breakdown of erasures by engineer for a date range"""
    return {"engineers": db.get_engineer_weekly_stats(startDate, endDate)}

@app.get("/metrics/month-comparison")
async def metrics_month_comparison(currentStart: str, currentEnd: str, previousStart: str, previousEnd: str):
    """Get month-over-month comparison"""
    return db.get_month_over_month_comparison(currentStart, currentEnd, previousStart, previousEnd)

@app.get("/admin/initials-list")
async def admin_get_initials_list(req: Request):
    """Get all unique initials in the database with their counts"""
    require_admin(req)

    conn = db.sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            COALESCE(NULLIF(TRIM(initials), ''), '(unassigned)') as initials_group,
            COUNT(*) as count
        FROM erasures 
        GROUP BY COALESCE(NULLIF(TRIM(initials), ''), '(unassigned)')
        ORDER BY count DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    result = [{"initials": row[0], "count": row[1]} for row in rows]
    
    return {
        "status": "ok",
        "total_records": sum(r["count"] for r in result),
        "initials": result
    }

# Admin: delete an ingested event by jobId (secured by API key)
@app.post("/admin/delete-event")
async def admin_delete_event(req: Request):
    require_admin(req)

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

# Admin: assign unassigned initials to a specific engineer
@app.post("/admin/assign-unassigned")
async def admin_assign_unassigned(req: Request):
    """Assign all erasures with NULL or empty initials to a specific engineer"""
    require_admin(req)

    body = {}
    try:
        body = await req.json()
    except Exception:
        pass
    
    to_initials = (body.get("to") if isinstance(body, dict) else None) or req.query_params.get("to")
    if not to_initials or not isinstance(to_initials, str) or len(to_initials.strip()) == 0:
        raise HTTPException(status_code=400, detail="'to' parameter required with engineer initials")
    
    to_initials = to_initials.strip().upper()
    
    # Execute the update - catch NULL, empty string, and whitespace-only
    conn = db.sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE erasures 
        SET initials = ? 
        WHERE initials IS NULL OR TRIM(COALESCE(initials, '')) = ''
    """, (to_initials,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"[ADMIN] Assigned {affected} unassigned erasures to engineer {to_initials}")
    
    return {
        "status": "ok",
        "action": "assign_unassigned",
        "to_initials": to_initials,
        "affected_records": affected
    }

# Admin: fix specific initials (rename/correct typos)
@app.post("/admin/fix-initials")
async def admin_fix_initials(req: Request):
    """Change all erasures with old initials to new initials (useful for fixing typos/mistakes)"""
    require_admin(req)

    body = {}
    try:
        body = await req.json()
    except Exception:
        pass
    
    from_initials = body.get("from") if isinstance(body, dict) else None
    to_initials = (body.get("to") if isinstance(body, dict) else None) or req.query_params.get("to")
    limit = body.get("limit") if isinstance(body, dict) else None
    if limit is None or limit == "":
        limit = None
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = None
    
    # from_initials can be empty string (for blank records), but to_initials must have a value
    if from_initials is None:
        raise HTTPException(status_code=400, detail="'from' parameter required")
    if not to_initials or not isinstance(to_initials, str) or len(to_initials.strip()) == 0:
        raise HTTPException(status_code=400, detail="'to' parameter required with engineer initials")
    
    to_initials = to_initials.strip().upper()
    
    # Handle empty string "from" - means we're targeting blank/null records
    if isinstance(from_initials, str):
        from_initials = from_initials.strip().upper()
    
    conn = db.sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()

    cursor.execute("BEGIN")
    if from_initials == '' or from_initials is None:
        cursor.execute("""
            SELECT rowid, initials
            FROM erasures
            WHERE initials IS NULL OR TRIM(COALESCE(initials, '')) = ''
            ORDER BY rowid ASC
        """)
        rows = cursor.fetchall()
        available_count = len(rows)
        if limit is not None:
            limit = max(0, min(int(limit), available_count))
            rows = rows[:limit]
        from_display = "(blank/unassigned)"
    else:
        if from_initials == to_initials:
            conn.close()
            return {"status": "error", "message": "from and to initials must be different"}
        cursor.execute("""
            SELECT rowid, initials
            FROM erasures
            WHERE initials = ?
            ORDER BY rowid ASC
        """, (from_initials,))
        rows = cursor.fetchall()
        available_count = len(rows)
        if limit is not None:
            limit = max(0, min(int(limit), available_count))
            rows = rows[:limit]
        from_display = from_initials

    if not rows:
        conn.rollback()
        conn.close()
        return {
            "status": "ok",
            "action": "fix_initials",
            "from_initials": from_display,
            "to_initials": to_initials,
            "affected_records": 0,
            "available_records": available_count
        }

    cursor.execute(
        "INSERT INTO admin_actions (action, from_initials, to_initials, created_at, affected) VALUES (?, ?, ?, ?, ?)",
        ("fix_initials", from_display, to_initials, datetime.now().isoformat(), len(rows))
    )
    action_id = cursor.lastrowid
    cursor.executemany(
        "INSERT INTO admin_action_rows (action_id, rowid, old_initials) VALUES (?, ?, ?)",
        [(action_id, row_id, old_initials) for row_id, old_initials in rows]
    )

    cursor.executemany(
        "UPDATE erasures SET initials = ? WHERE rowid = ?",
        [(to_initials, row_id) for row_id, _ in rows]
    )

    affected = len(rows)
    conn.commit()
    conn.close()
    
    print(f"[ADMIN] Fixed initials: {from_display} -> {to_initials} ({affected} records)")
    
    return {
        "status": "ok",
        "action": "fix_initials",
        "from_initials": from_display,
        "to_initials": to_initials,
        "affected_records": affected,
        "available_records": available_count
    }

@app.post("/admin/undo-last-initials")
async def admin_undo_last_initials(req: Request):
    """Undo the most recent initials change."""
    require_admin(req)
    conn = db.sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, action, from_initials, to_initials, affected
        FROM admin_actions
        WHERE action = 'fix_initials'
        ORDER BY id DESC
        LIMIT 1
    """)
    action = cursor.fetchone()
    if not action:
        conn.close()
        return {"status": "ok", "undone": 0, "message": "No undo history"}

    action_id, action_name, from_initials, to_initials, affected = action
    cursor.execute("SELECT rowid, old_initials FROM admin_action_rows WHERE action_id = ?", (action_id,))
    rows = cursor.fetchall()

    cursor.execute("BEGIN")
    cursor.executemany(
        "UPDATE erasures SET initials = ? WHERE rowid = ?",
        [(old_initials, row_id) for row_id, old_initials in rows]
    )
    cursor.execute("DELETE FROM admin_action_rows WHERE action_id = ?", (action_id,))
    cursor.execute("DELETE FROM admin_actions WHERE id = ?", (action_id,))
    conn.commit()
    conn.close()

    return {
        "status": "ok",
        "undone": len(rows),
        "from_initials": from_initials,
        "to_initials": to_initials
    }

@app.get("/admin/connected-devices")
async def admin_connected_devices(req: Request):
    """List active device tokens with roles and expiry."""
    require_admin(req)
    tokens = load_device_tokens()
    devices = []
    for token, info in tokens.items():
        devices.append({
            "token": token,
            "role": info.get("role"),
            "client_ip": info.get("client_ip"),
            "user_agent": info.get("user_agent"),
            "created": info.get("created"),
            "expiry": info.get("expiry")
        })
    return {"status": "ok", "devices": devices}

@app.post("/admin/revoke-device")
async def admin_revoke_device(req: Request):
    """Revoke a device token."""
    require_admin(req)
    body = {}
    try:
        body = await req.json()
    except Exception:
        body = {}
    token = (body.get("token") if isinstance(body, dict) else None) or req.query_params.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="token is required")
    tokens = load_device_tokens()
    if token in tokens:
        del tokens[token]
        save_device_tokens(tokens)
        return {"status": "ok", "revoked": True}
    return {"status": "ok", "revoked": False}

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

# ============= AUTH ENDPOINTS =============
@app.get("/auth/status")
async def auth_status(request: Request):
    """Check auth status for current client"""
    client_ip = get_client_ip(request)
    
    # Check for TV browser
    user_agent = request.headers.get("User-Agent", "").lower()
    is_tv_browser = "silk" in user_agent or "firetv" in user_agent or "aftt" in user_agent
    
    is_local = is_local_network(client_ip)
    is_authenticated = is_local or is_tv_browser
    role = "viewer" if (is_local or is_tv_browser) else None

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == ADMIN_PASSWORD:
            role = "admin"
            is_authenticated = True
        elif token == MANAGER_PASSWORD:
            role = "manager"
            is_authenticated = True
        elif is_device_token_valid(token):
            tokens = load_device_tokens()
            role = tokens.get(token, {}).get("role") or role
            is_authenticated = True
    
    # Log for debugging
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    print(f"Auth check - Client IP: {client_ip}, Is Local: {is_local}, Is TV: {is_tv_browser}, Role: {role}, X-Forwarded-For: {forwarded_for}")
    
    return {
        "authenticated": is_authenticated,
        "role": role,
        "client_ip": client_ip,
        "is_tv_browser": is_tv_browser,
        "access_type": "tv-browser" if is_tv_browser else ("local" if is_local else "external"),
        "message": "TV browser auto-allowed" if is_tv_browser else ("Local network access granted automatically" if is_local else "External access requires password")
    }

@app.post("/auth/login")
async def login(request: Request):
    """Users can login with manager/admin password"""
    try:
        body = await request.json()
        password = body.get("password", "")
        
        # Get real client IP
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "0.0.0.0"
        
        # Admin password accepted anywhere
        if password == ADMIN_PASSWORD:
            # Generate device token for future auto-login
            user_agent = request.headers.get("User-Agent", "Unknown")
            device_token = generate_device_token(user_agent, client_ip)
            
            # Store token with expiry
            tokens = load_device_tokens()
            tokens[device_token] = {
                "created": datetime.now().isoformat(),
                "expiry": (datetime.now() + timedelta(days=DEVICE_TOKEN_EXPIRY_DAYS)).isoformat(),
                "user_agent": user_agent,
                "client_ip": client_ip,
                "role": "admin"
            }
            save_device_tokens(tokens)
            
            print(f"Admin device token created for {client_ip} - expires in {DEVICE_TOKEN_EXPIRY_DAYS} days")
            
            return {
                "authenticated": True,
                "role": "admin",
                "device_token": device_token,
                "token": ADMIN_PASSWORD,
                "message": "Admin access granted"
            }

        # Manager password accepted anywhere
        if password == MANAGER_PASSWORD:
            user_agent = request.headers.get("User-Agent", "Unknown")
            device_token = generate_device_token(user_agent, client_ip)

            tokens = load_device_tokens()
            tokens[device_token] = {
                "created": datetime.now().isoformat(),
                "expiry": (datetime.now() + timedelta(days=DEVICE_TOKEN_EXPIRY_DAYS)).isoformat(),
                "user_agent": user_agent,
                "client_ip": client_ip,
                "role": "manager"
            }
            save_device_tokens(tokens)

            print(f"Manager device token created for {client_ip} - expires in {DEVICE_TOKEN_EXPIRY_DAYS} days")

            return {
                "authenticated": True,
                "role": "manager",
                "device_token": device_token,
                "token": MANAGER_PASSWORD,
                "message": "Manager access granted"
            }
        
        # Local network users can continue as viewer without password
        if is_local_network(client_ip):
            return {"authenticated": True, "role": "viewer", "message": "Local network view-only access"}
        
        raise HTTPException(status_code=401, detail="Invalid password")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/export/excel")
async def export_excel(req: Request):
    """Generate multi-sheet Excel export of warehouse stats (manager only)"""
    require_manager_or_admin(req)
    
    try:
        body = await req.json()
        sheets_data = body.get("sheetsData", {})
        
        excel_file = excel_export.create_excel_report(sheets_data)
        
        return StreamingResponse(
            iter([excel_file.getvalue()]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=warehouse-stats.xlsx"}
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Excel export error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/export/engineer-deepdive")
async def export_engineer_deepdive(request: Request, period: str = "this_week"):
    """Generate engineer deep-dive Excel export for a specific period (manager only)"""
    require_manager_or_admin(request)
    
    try:
        import engineer_export
        period = period.replace("-", "_")
        
        # Ensure database schema is up-to-date
        db.init_db()
        
        # Validate period
        valid_periods = [
            "this_week",
            "last_week",
            "this_month",
            "last_month",
            "this_year",
            "last_year",
            "last_year_h1",
            "last_year_h2",
            "last_available",
        ]
        if period not in valid_periods:
            raise HTTPException(status_code=400, detail=f"Invalid period. Must be one of: {', '.join(valid_periods)}")
        
        # Generate the analysis
        sheets_data = engineer_export.generate_engineer_deepdive_export(period)
        
        # Create Excel file
        excel_file = excel_export.create_excel_report(sheets_data)
        
        # Format filename with period
        period_label = period.replace("_", "-")
        filename = f"engineer-deepdive-{period_label}.xlsx"
        
        return StreamingResponse(
            iter([excel_file.getvalue()]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Engineer deep-dive export error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/device-lookup/{stock_id}")
async def device_lookup(stock_id: str, request: Request):
    """Search for a device across all data sources to trace its journey (manager only)"""
    require_manager_or_admin(request)
    
    results = {
        "stock_id": stock_id,
        "found_in": [],
        "timeline": [],
        "asset_info": None,
        "pallet_info": None,
        "last_known_user": None,
        "last_known_location": None,
    }
    
    try:
        import qa_export
        conn = qa_export.get_mariadb_connection()
        if not conn:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        cursor = conn.cursor()
        
        # 1. Check ITAD_asset_info for asset details
        cursor.execute("""
            SELECT stockid, serialnumber, manufacturer, description, `condition`, 
                   COALESCE(pallet_id, palletID) as pallet_id, added_date, status
            FROM ITAD_asset_info 
            WHERE stockid = %s OR serialnumber = %s
        """, (stock_id, stock_id))
        row = cursor.fetchone()
        if row:
            results["found_in"].append("ITAD_asset_info")
            results["asset_info"] = {
                "stock_id": row[0],
                "serial": row[1],
                "manufacturer": row[2],
                "model": row[3],
                "condition": row[4],
                "pallet_id": row[5],
                "added_date": str(row[6]) if row[6] else None,
                "status": row[7],
            }
            if row[5]:  # pallet_id
                results["pallet_info"] = {"pallet_id": row[5]}
        
        # 2. Check Stockbypallet for pallet assignment
        cursor.execute("""
            SELECT stockid, pallet_id, date_added
            FROM Stockbypallet
            WHERE stockid = %s
        """, (stock_id,))
        row = cursor.fetchone()
        if row:
            results["found_in"].append("Stockbypallet")
            if not results["pallet_info"]:
                results["pallet_info"] = {}
            results["pallet_info"]["pallet_id"] = row[1]
            results["pallet_info"]["date_added"] = str(row[2]) if row[2] else None
        
        # 3. Get pallet details if we have a pallet_id
        if results.get("pallet_info", {}).get("pallet_id"):
            pallet_id = results["pallet_info"]["pallet_id"]
            cursor.execute("""
                SELECT pallet_id, destination, pallet_location, pallet_status, date_created
                FROM ITAD_pallet
                WHERE pallet_id = %s
            """, (pallet_id,))
            row = cursor.fetchone()
            if row:
                results["pallet_info"].update({
                    "destination": row[1],
                    "location": row[2],
                    "status": row[3],
                    "date_created": str(row[4]) if row[4] else None,
                })
        
        # 4. Check ITAD_QA_App for sorting scans
        cursor.execute("""
            SELECT added_date, username, scanned_location
            FROM ITAD_QA_App
            WHERE stockid = %s
            ORDER BY added_date ASC
        """, (stock_id,))
        for row in cursor.fetchall():
            results["found_in"].append("ITAD_QA_App") if "ITAD_QA_App" not in results["found_in"] else None
            results["timeline"].append({
                "timestamp": str(row[0]),
                "stage": "Sorting",
                "user": row[1],
                "location": row[2],
                "source": "ITAD_QA_App",
            })
            results["last_known_user"] = row[1]
            results["last_known_location"] = row[2]
        
        # 5. Check audit_master for QA submissions
        cursor.execute("""
            SELECT date_time, audit_type, user_id, log_description, log_description2
            FROM audit_master
            WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload', 
                                 'Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload')
              AND (log_description LIKE %s OR log_description2 LIKE %s)
            ORDER BY date_time ASC
        """, (f'%{stock_id}%', f'%{stock_id}%'))
        for row in cursor.fetchall():
            results["found_in"].append("audit_master") if "audit_master" not in results["found_in"] else None
            stage = "QA Data Bearing" if row[1].startswith("DEAPP_") else "QA Non-Data Bearing"
            results["timeline"].append({
                "timestamp": str(row[0]),
                "stage": stage,
                "user": row[2],
                "location": None,
                "source": "audit_master",
            })
            results["last_known_user"] = row[2]
        
        # 6. Check ITAD_asset_info_blancco for erasure records
        cursor.execute("""
            SELECT job_date, stockid, serial, manufacturer, model, job_status
            FROM ITAD_asset_info_blancco
            WHERE stockid = %s OR serial = %s
            ORDER BY job_date ASC
        """, (stock_id, stock_id))
        for row in cursor.fetchall():
            results["found_in"].append("ITAD_asset_info_blancco") if "ITAD_asset_info_blancco" not in results["found_in"] else None
            results["timeline"].append({
                "timestamp": str(row[0]) if row[0] else None,
                "stage": f"Erasure ({row[5]})" if row[5] else "Erasure",
                "user": None,
                "location": None,
                "source": "ITAD_asset_info_blancco",
            })
        
        cursor.close()
        conn.close()
        
        # 7. Check local SQLite erasures table
        try:
            import sqlite3
            sqlite_conn = sqlite3.connect(db.DB_PATH)
            sqlite_cursor = sqlite_conn.cursor()
            sqlite_cursor.execute("""
                SELECT ts, date, initials, device_type, event
                FROM erasures
                WHERE system_serial = ? OR disk_serial = ? OR job_id = ?
                ORDER BY date ASC, ts ASC
            """, (stock_id, stock_id, stock_id))
            for row in sqlite_cursor.fetchall():
                results["found_in"].append("local_erasures") if "local_erasures" not in results["found_in"] else None
                results["timeline"].append({
                    "timestamp": row[0] or row[1],
                    "stage": f"Erasure ({row[4]})",
                    "user": row[2],
                    "location": None,
                    "source": "local_erasures",
                })
                results["last_known_user"] = row[2]
            sqlite_cursor.close()
            sqlite_conn.close()
        except Exception as e:
            print(f"SQLite lookup error: {e}")
        
        # Sort timeline chronologically
        results["timeline"].sort(key=lambda x: x.get("timestamp") or "")
        
        # Summary
        results["total_events"] = len(results["timeline"])
        results["data_sources_checked"] = [
            "ITAD_asset_info", "Stockbypallet", "ITAD_pallet", 
            "ITAD_QA_App", "audit_master", "ITAD_asset_info_blancco", "local_erasures"
        ]
        
        return results
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Device lookup error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/export/qa-stats")
async def export_qa_stats(
    request: Request, 
    period: str = "this_week",
    start_year: int = None,
    start_month: int = None,
    end_year: int = None,
    end_month: int = None
):
    """Generate QA stats Excel export for a specific period from MariaDB (manager only)"""
    require_manager_or_admin(request)
    
    try:
        import qa_export
        period = period.replace("-", "_")
        
        # Ensure database schema is up-to-date
        db.init_db()
        
        # Validate period
        valid_periods = [
            "this_week",
            "last_week",
            "this_month",
            "last_month",
            "this_year",
            "last_year",
            "last_year_h1",
            "last_year_h2",
            "last_available",
            "custom_range",
        ]
        if period not in valid_periods:
            print(f"QA export invalid period: {period}")
            raise HTTPException(status_code=400, detail=f"Invalid period. Must be one of: {', '.join(valid_periods)}")
        
        # Validate custom range parameters if specified
        if period == "custom_range":
            if not all([start_year, start_month, end_year, end_month]):
                raise HTTPException(status_code=400, detail="Custom range requires start_year, start_month, end_year, end_month")
            if start_month < 1 or start_month > 12 or end_month < 1 or end_month > 12:
                raise HTTPException(status_code=400, detail="Month must be between 1 and 12")
        
        # Generate the QA engineer breakdown export (new comprehensive version)
        sheets_data = qa_export.generate_qa_engineer_export(
            period, 
            start_year=start_year, 
            start_month=start_month, 
            end_year=end_year, 
            end_month=end_month
        )
        
        # Create Excel file
        excel_file = excel_export.create_excel_report(sheets_data)
        
        # Format filename with period
        period_label = period.replace("_", "-")
        filename = f"qa-engineer-stats-{period_label}.xlsx"
        
        return StreamingResponse(
            iter([excel_file.getvalue()]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"QA stats export error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/qa-dashboard")
async def get_qa_dashboard_data(period: str = "this_week"):
    """Get QA dashboard data for display (not export)"""
    try:
        import qa_export
        from datetime import date, timedelta

        cache_key = f"qa_dashboard:{period}"
        cached = _get_cached_response(cache_key)
        if cached is not None:
            return cached
        
        # Get date range
        start_date, end_date, period_label = qa_export.get_week_dates(period)
        
        # Get QA data (ITAD_QA_App), DE QA data, and Non-DE QA data
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
                    "topTechnician": "N/A"
                },
                "topPerformers": [],
                "locations": [],
                "dataBounds": {
                    "minDate": str(min_date) if min_date else None,
                    "maxDate": str(max_date) if max_date else None
                }
            }
            return _set_cached_response(cache_key, result)
        
        # Calculate summary metrics (excluding unassigned)
        total_scans = sum(stats['total'] for name, stats in qa_data.items() if name.lower() != '(unassigned)') if qa_data else 0
        total_passed = sum(stats['successful'] for name, stats in qa_data.items() if name.lower() != '(unassigned)') if qa_data else 0
        total_de_scans = sum(stats['total'] for name, stats in de_qa_data.items() if name.lower() != '(unassigned)') if de_qa_data else 0
        total_non_de_scans = sum(stats['total'] for name, stats in non_de_qa_data.items() if name.lower() != '(unassigned)') if non_de_qa_data else 0
        combined_scans = total_scans + total_de_scans + total_non_de_scans
        overall_pass_rate = (total_passed / total_scans * 100) if total_scans > 0 else 0
        
        # Calculate consistency scores and build technician list
        technicians = []
        consistency_scores = []
        
        all_names = sorted(
            set(qa_data.keys() if qa_data else [])
            | set(de_qa_data.keys() if de_qa_data else [])
            | set(non_de_qa_data.keys() if non_de_qa_data else [])
        )

        for tech_name in all_names:
            stats = qa_data.get(tech_name, {'total': 0, 'successful': 0, 'daily': {}, 'pass_rate': 0.0})
            de_stats = de_qa_data.get(tech_name, {'total': 0, 'daily': {}})
            non_de_stats = non_de_qa_data.get(tech_name, {'total': 0, 'daily': {}})

            qa_total = stats['total']
            de_total = de_stats['total']
            non_de_total = non_de_stats['total']
            tech_combined_total = qa_total + de_total + non_de_total

            # Calculate combined daily counts (QA app + DE QA + Non-DE QA)
            combined_daily = {}
            for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
                qa_scans = stats['daily'].get(day, {}).get('scans', 0)
                de_scans = de_stats['daily'].get(day, {}).get('scans', 0)
                non_de_scans = non_de_stats['daily'].get(day, {}).get('scans', 0)
                combined_scans_day = qa_scans + de_scans + non_de_scans
                if combined_scans_day > 0:
                    combined_daily[day] = {
                        'scans': combined_scans_day,
                        'passed': stats['daily'].get(day, {}).get('passed', 0)
                    }

            days_active = len([d for d in combined_daily if combined_daily[d]['scans'] > 0])
            avg_per_day = tech_combined_total / max(1, days_active) if days_active > 0 else 0
            
            # Calculate consistency from combined daily totals
            daily_counts = [float(combined_daily[day]['scans'])
                           for day in combined_daily if combined_daily[day]['scans'] > 0]
            
            consistency = 100
            if daily_counts and len(daily_counts) > 1:
                avg = sum(daily_counts) / len(daily_counts)
                if avg > 0:
                    variance = sum((x - avg) ** 2 for x in daily_counts) / len(daily_counts)
                    consistency = max(0, min(100, 100 - (variance / (avg + 1) * 10)))
            
            consistency_scores.append(consistency)
            
            # Reliability score
            reliability = (stats['pass_rate'] * 0.6) + (consistency * 0.4) if qa_total > 0 else 0
            
            tech_data = {
                "name": tech_name,
                "qaScans": qa_total,
                "deQaScans": de_total,
                "nonDeQaScans": non_de_total,
                "combinedScans": tech_combined_total,
                "passRate": round(stats['pass_rate'], 1),
                "avgPerDay": round(avg_per_day, 1),
                "consistency": round(consistency, 1),
                "reliability": round(reliability, 1),
                "daysActive": days_active,
                "daily": {}
            }
            
            # Add daily breakdown
            for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
                if day in combined_daily:
                    daily = combined_daily[day]
                    pass_pct = (daily['passed'] / daily['scans'] * 100) if daily['scans'] > 0 else 0
                    tech_data['daily'][day] = {
                        "scans": daily['scans'],
                        "passed": daily['passed'],
                        "passRate": round(pass_pct, 1)
                    }
            
            technicians.append(tech_data)
        
        # Get top performers
        top_performers = sorted(technicians, key=lambda x: x['combinedScans'], reverse=True)[:5]
        
        avg_consistency = sum(consistency_scores) / len(consistency_scores) if consistency_scores else 0
        
        # Get all-time daily record
        daily_record = qa_export.get_all_time_daily_record()
        
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
                "topTechnician": top_performers[0]['name'] if top_performers else "N/A",
                "techniciansCount": len(technicians),
                "dailyRecord": daily_record
            },
            "topPerformers": top_performers
        }
        return _set_cached_response(cache_key, result)
    
    except Exception as e:
        print(f"QA dashboard data error: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e), "period": period}

# Serve static files (HTML, CSS, JS)
app.mount("/", StaticFiles(directory=".", html=True), name="static")
