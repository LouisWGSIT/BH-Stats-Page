from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from starlette.background import BackgroundTask
import tempfile
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
import os
from typing import Any, Dict
from datetime import datetime, timedelta, date
import asyncio
import backend.database as db
import backend.excel_export as excel_export
import ipaddress
import json
import hashlib
import secrets
import httpx  # For making API calls to Blancco
from time import time
import zipfile
import io
import sqlite3
import backend.qa_export as qa_export
import routers.health as health_router
from backend.app.routes.admin_activity import create_admin_activity_router
from backend.app.routes.admin_backfill import create_admin_backfill_router
from backend.app.routes.admin_devices import create_admin_devices_router
from backend.app.routes.admin_diagnostics import create_admin_diagnostics_router
from backend.app.routes.admin_exports import create_admin_exports_router
from backend.app.routes.admin_initials import create_admin_initials_router
from backend.app.routes.admin_maintenance import create_admin_maintenance_router
from backend.app.routes.auth import create_auth_router
from backend.app.routes.bottlenecks import create_bottleneck_router
from backend.app.routes.device_lookup import create_device_lookup_router
from backend.app.routes.erasure_insights import create_erasure_insights_router
from backend.app.routes.hwid import create_hwid_router
from backend.app.routes.metrics_analytics import create_metrics_analytics_router
from backend.app.routes.qa_insights import compute_qa_dashboard_data, create_qa_insights_router
from backend.app.routes.static_pages import create_static_pages_router
from backend.app.routes.webhooks import create_webhooks_router
from backend.app.runtime_tasks import (
    TTLCache,
    check_daily_reset,
    memory_watchdog,
    sync_engineer_stats_on_startup,
    warm_cache_on_startup,
)
import logging
from backend.logging_config import configure_logging
import threading
from collections import deque
import queue

# Optional psutil import (not required at runtime)
try:
    import psutil  # type: ignore
except Exception:
    psutil = None

# Tracemalloc / snapshot settings
ENABLE_TRACEMALLOC = os.getenv("ENABLE_TRACEMALLOC", "false").lower() in ("1", "true", "yes")
TRACE_SNAPSHOT_THRESHOLD_MB = int(os.getenv("TRACE_SNAPSHOT_THRESHOLD_MB", "450"))
TRACE_SNAPSHOT_DIR = os.getenv("TRACE_SNAPSHOT_DIR", "logs/memory")
if ENABLE_TRACEMALLOC:
    try:
        import tracemalloc
        tracemalloc.start(25)
    except Exception:
        tracemalloc = None

        # Store last server error details for admin debugging (in-memory)
        LAST_SERVER_ERROR = None
else:
    tracemalloc = None

def take_tracemalloc_snapshot(reason: str = "threshold", meta: dict | None = None) -> str | None:
    """Take a tracemalloc snapshot and write a human-readable top-list to TRACE_SNAPSHOT_DIR.

    Returns path to written file or None on failure.
    """
    try:
        if tracemalloc is None:
            return None
        os.makedirs(TRACE_SNAPSHOT_DIR, exist_ok=True)
        snap = tracemalloc.take_snapshot()
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        fname = f"memsnap-{ts}-{reason}.txt"
        path = os.path.join(TRACE_SNAPSHOT_DIR, fname)
        top_stats = snap.statistics('lineno')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"Tracemalloc snapshot: {ts}\nReason: {reason}\n")
            if meta:
                f.write(f"Meta: {json.dumps(meta)}\n")
            try:
                rss = get_process_rss_bytes()
                f.write(f"Process RSS: {rss}\n\n")
            except Exception:
                pass
            f.write("Top 100 memory blocks (filename:lineno: size bytes)\n")
            for i, stat in enumerate(top_stats[:100], 1):
                try:
                    frame = stat.traceback[0]
                    f.write(f"{i}: {frame.filename}:{frame.lineno}: {stat.size} bytes ({stat.count} blocks)\n")
                except Exception:
                    f.write(f"{i}: {stat}\n")
        return path
    except Exception:
        return None


# Configure root logger to emit structured JSON logs (includes request_id)
configure_logging(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")))
app = FastAPI(title="Warehouse Stats Service")
app.include_router(health_router.router)
# Enable GZip compression for responses over a threshold to reduce payload sizes
app.add_middleware(GZipMiddleware, minimum_size=500)

# Export job routes (enqueue / status) - optional Redis/RQ integration
try:
    import export_jobs
    app.include_router(export_jobs.router)
except Exception:
    # If the module or dependencies aren't available at runtime, skip router
    pass

from uuid import uuid4
import backend.request_context as request_context

# Middleware: add a request-id to each incoming HTTP request for log correlation
@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    rid = uuid4().hex
    # store in contextvar for other modules (e.g., DB logging) to read
    request_context.request_id.set(rid)
    start_ts = time()
    try:
        response = await call_next(request)
        response.headers['X-Request-ID'] = rid
        return response
    finally:
        # clear contextvar to avoid leaking across requests in long-lived tasks
        request_context.request_id.set(None)
        # Record activity for diagnostic purposes (keep lightweight)
        try:
            # Only record requests that pass the should_record_request filter
            do_record = True
            try:
                if not should_record_request(request):
                    do_record = False
            except Exception:
                do_record = True

            if do_record:
                dur = int((time() - start_ts) * 1000)
                client_ip = get_client_ip(request) if 'get_client_ip' in globals() else (request.client.host if request.client else '0.0.0.0')
                rss = get_process_rss_bytes()
                record_activity({
                    'ts': datetime.utcnow().isoformat(),
                    'request_id': rid,
                    'path': request.url.path,
                    'method': request.method,
                    'client_ip': client_ip,
                    'status_code': getattr(response, 'status_code', None),
                    'duration_ms': dur,
                    'rss': rss
                })
        except Exception:
            pass

# ============= BLANCCO API CONFIG =============
BLANCCO_API_URL = os.getenv("BLANCCO_API_URL", "")  # Set this if Blancco has an API
BLANCCO_API_KEY = os.getenv("BLANCCO_API_KEY", "")
QA_CONFIRMED_SCORE = int(os.getenv("QA_CONFIRMED_SCORE", "95"))

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
MANAGER_PASSWORD = os.getenv("DASHBOARD_MANAGER_PASSWORD", "")
ADMIN_PASSWORD = os.getenv("DASHBOARD_ADMIN_PASSWORD", "")

# If set to a truthy value, allow read-only public GET access to dashboard metrics
# Use only for short-lived public tests (e.g., Lighthouse). Defaults to false.
DASHBOARD_PUBLIC = os.getenv("DASHBOARD_PUBLIC", "false").lower() in ("1", "true", "yes")

# Device token storage (persistent across redeployments)
DEVICE_TOKENS_FILE = "device_tokens.json"
DEVICE_TOKENS_DB = os.getenv("DEVICE_TOKENS_DB", "").strip()
DEVICE_TOKEN_EXPIRY_DAYS = 7  # Remember device for 7 days

QA_CACHE_TTL_SECONDS = float(os.getenv("QA_CACHE_TTL_SECONDS", "60"))
# Bounded TTL cache for QA/dashboard responses
QA_CACHE = TTLCache(maxsize=int(os.getenv("QA_CACHE_MAXSIZE", "256")), ttl=QA_CACHE_TTL_SECONDS)

def _get_cached_response(cache_key: str):
    return QA_CACHE.get(cache_key)

def _set_cached_response(cache_key: str, data: Dict[str, object]):
    QA_CACHE.set(cache_key, data)
    return data


# Activity log (in-memory ring buffer). Each entry: {ts, path, method, role, client_ip, note, rss}
ACTIVITY_LOG = deque(maxlen=5000)

def get_process_rss_bytes() -> int | None:
    """Best-effort process RSS in bytes, even when psutil is unavailable."""
    try:
        if psutil:
            return psutil.Process().memory_info().rss
    except Exception:
        pass

    # Linux /proc fallback (current RSS)
    try:
        with open('/proc/self/status', 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except Exception:
        pass

    # Linux/macOS fallback via resource (often high-water mark)
    try:
        import resource
        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Heuristic: Linux values are typically in KiB range
        return rss * 1024 if rss < (10**10) else rss
    except Exception:
        pass

    return None

def record_activity(entry: dict):
    try:
        # Ensure timestamp in ISO
        entry.setdefault('ts', datetime.utcnow().isoformat())
        ACTIVITY_LOG.append(entry)
        # Enqueue to persistent writer if available (non-blocking)
        try:
            writer = getattr(app.state, 'activity_writer', None)
            if writer:
                writer.enqueue(entry)
        except Exception:
            pass
    except Exception:
        pass


# Paths/prefixes to exclude from activity logging (noisy dashboard GETs)
ACTIVITY_EXCLUDE_PREFIXES = [
    '/analytics',
    '/metrics',
    '/competitions',
    '/vendor',
    '/assets',
    '/styles.css',
    '/favicon.ico',
    '/auth/status',
    '/auth',
    '/health',
    '/static'
]
ACTIVITY_EXCLUDE_EXACT = {
    '/admin/activity',
    '/admin/activity/memory-series',
}

def should_record_request(request: Request) -> bool:
    """Return True if the request should be recorded in activity log.

    Rules:
    - Always record explicit exports, device-lookup, and admin actions.
    - Record non-GET methods by default.
    - Skip common noisy GET prefixes defined in ACTIVITY_EXCLUDE_PREFIXES.
    """
    try:
        path = request.url.path or ''
        method = request.method or 'GET'

        # Skip noisy admin self-observability refresh endpoints.
        # These are user-triggered diagnostics and can flood the table.
        if path in ACTIVITY_EXCLUDE_EXACT:
            return False

        # Always record exports and important admin/device actions
        if '/export' in path or '/api/device-lookup' in path or path.startswith('/admin'):
            return True

        # Record non-GET requests
        if method != 'GET':
            return True

        # Skip common noisy GETs
        for p in ACTIVITY_EXCLUDE_PREFIXES:
            if path.startswith(p):
                return False

        return True
    except Exception:
        return True


# SQLite-backed async writer to persist activity entries without blocking requests
class ActivityWriter:
    def __init__(self, db_path: str = 'logs/activity.sqlite', retention_days: int = 7, max_queue: int = 10000):
        self.db_path = db_path
        self.retention_days = retention_days
        self.queue = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        self._ensure_schema()
        self._thread.start()

    def _get_conn(self):
        # allow cross-thread use
        conn = sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)
        return conn

    def _ensure_schema(self):
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT,
                    request_id TEXT,
                    path TEXT,
                    method TEXT,
                    client_ip TEXT,
                    role TEXT,
                    note TEXT,
                    duration_ms INTEGER,
                    rss INTEGER
                )
            ''')
            cur.execute('CREATE INDEX IF NOT EXISTS ix_activity_ts ON activity(ts)')
            cur.execute('CREATE INDEX IF NOT EXISTS ix_activity_path ON activity(path)')
            conn.commit()
        finally:
            conn.close()

    def enqueue(self, entry: dict):
        try:
            # Non-blocking; drop if queue full to avoid backpressure
            self.queue.put_nowait(entry)
        except queue.Full:
            # Silently drop
            pass

    def _run(self):
        conn = self._get_conn()
        cur = conn.cursor()
        batch = []
        try:
            while not self._stop.is_set():
                try:
                    item = self.queue.get(timeout=1.0)
                except Exception:
                    item = None
                if item is None:
                    # flush any pending
                    if batch:
                        for row in batch:
                            try:
                                cur.execute('INSERT INTO activity(ts, request_id, path, method, client_ip, role, note, duration_ms, rss) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (
                                    row.get('ts'), row.get('request_id'), row.get('path'), row.get('method'), row.get('client_ip'), row.get('role'), row.get('note'), row.get('duration_ms'), row.get('rss')
                                ))
                            except Exception:
                                continue
                        conn.commit()
                        batch = []
                    continue

                batch.append(item)
                # commit in chunks to reduce I/O
                if len(batch) >= 20:
                    for row in batch:
                        try:
                            cur.execute('INSERT INTO activity(ts, request_id, path, method, client_ip, role, note, duration_ms, rss) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (
                                row.get('ts'), row.get('request_id'), row.get('path'), row.get('method'), row.get('client_ip'), row.get('role'), row.get('note'), row.get('duration_ms'), row.get('rss')
                            ))
                        except Exception:
                            continue
                    conn.commit()
                    batch = []

        finally:
            try:
                if batch:
                    for row in batch:
                        try:
                            cur.execute('INSERT INTO activity(ts, request_id, path, method, client_ip, role, note, duration_ms, rss) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (
                                row.get('ts'), row.get('request_id'), row.get('path'), row.get('method'), row.get('client_ip'), row.get('role'), row.get('note'), row.get('duration_ms'), row.get('rss')
                            ))
                        except Exception:
                            continue
                    conn.commit()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2.0)

    def prune_older_than_days(self, days: int):
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            cur.execute('DELETE FROM activity WHERE ts < ?', (cutoff,))
            conn.commit()
            conn.close()
        except Exception:
            pass


# Initialize persistent activity writer on startup
@app.on_event('startup')
def _start_activity_writer():
    try:
        writer = ActivityWriter(db_path=os.getenv('ACTIVITY_DB_PATH', 'logs/activity.sqlite'))
        app.state.activity_writer = writer
    except Exception:
        app.state.activity_writer = None


@app.on_event('shutdown')
def _stop_activity_writer():
    try:
        writer = getattr(app.state, 'activity_writer', None)
        if writer:
            writer.stop()
    except Exception:
        pass

def load_device_tokens():
    """Load device tokens from persistent storage."""
    # Prefer SQLite-backed storage if configured (set DEVICE_TOKENS_DB env var)
    if DEVICE_TOKENS_DB:
        try:
            result = {}
            with db.sqlite_transaction(DEVICE_TOKENS_DB, timeout=2) as (conn, cur):
                cur.execute("CREATE TABLE IF NOT EXISTS device_tokens (token TEXT PRIMARY KEY, data TEXT)")
                cur.execute("SELECT data FROM device_tokens")
                rows = cur.fetchall()
                for (d,) in rows:
                    try:
                        parsed = json.loads(d)
                        token_key = parsed.get('token') or parsed.get('device_token')
                        if token_key:
                            # remove embedded token key to avoid duplication
                            parsed.pop('token', None)
                            parsed.pop('device_token', None)
                            result[token_key] = parsed
                    except Exception:
                        continue
            return result
        except Exception as e:
            print(f"Error loading device tokens from DB ({DEVICE_TOKENS_DB}): {e}")

    # Fallback to JSON file
    try:
        if os.path.exists(DEVICE_TOKENS_FILE):
            with open(DEVICE_TOKENS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_device_tokens(tokens):
    """Save device tokens to persistent storage."""
    # If configured, save to SQLite DB for persistence across deploys (set DEVICE_TOKENS_DB env var)
    if DEVICE_TOKENS_DB:
        try:
            with db.sqlite_transaction(DEVICE_TOKENS_DB, timeout=2) as (conn, cur):
                cur.execute("CREATE TABLE IF NOT EXISTS device_tokens (token TEXT PRIMARY KEY, data TEXT)")
                # Upsert each token as JSON blob
                for token, info in tokens.items():
                    try:
                        payload = json.dumps({**info, 'token': token})
                        cur.execute("INSERT OR REPLACE INTO device_tokens(token, data) VALUES (?, ?)", (token, payload))
                    except Exception:
                        continue
                # Remove rows not present in tokens dict
                try:
                    cur.execute("SELECT token FROM device_tokens")
                    existing = [r[0] for r in cur.fetchall()]
                    for e in existing:
                        if e not in tokens:
                            cur.execute("DELETE FROM device_tokens WHERE token = ?", (e,))
                except Exception:
                    pass
            return
        except Exception as e:
            print(f"Error saving device tokens to DB ({DEVICE_TOKENS_DB}): {e}")

    # Fallback to JSON file
    try:


        # Admin: trigger sync to populate engineer_stats_type (category trends)
        @app.post("/admin/sync-engineer-stats-type")
        async def admin_sync_engineer_stats_type(req: Request):
            """Trigger a DB sync to populate `engineer_stats_type` from `erasures`.
            Optional JSON body or query param `date` (YYYY-MM-DD) to sync a single date.
            Requires admin access.
            """
            require_admin(req)

            body = {}
            try:
                body = await req.json()
            except Exception:
                body = {}

            date_param = None
            if isinstance(body, dict):
                date_param = body.get('date')
            if not date_param:
                date_param = req.query_params.get('date')

            try:
                synced = db.sync_engineer_stats_type_from_erasures(date_param) if date_param else db.sync_engineer_stats_type_from_erasures()
                return {"status": "ok", "synced_records": synced, "date": date_param}
            except Exception as e:
                print(f"[ADMIN] sync error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        with open(DEVICE_TOKENS_FILE, 'w') as f:
            json.dump(tokens, f)
    except Exception as e:
        print(f"Error saving device tokens: {e}")

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
        entry = tokens[token]
        # Respect explicit lock flag: locked tokens are invalid for automatic login
        if entry.get('locked'):
            return False
        try:
            expiry = datetime.fromisoformat(entry['expiry'])
        except Exception:
            # Malformed expiry, treat as invalid
            try:
                del tokens[token]
                save_device_tokens(tokens)
            except Exception:
                pass
            return False
        if datetime.now() < expiry:
            return True
        else:
            # Token expired, remove it
            try:
                del tokens[token]
                save_device_tokens(tokens)
            except Exception:
                pass
    return False

def touch_device_token(token: str, client_ips: list | None = None, user_agent: str | None = None):
    """Update metadata for a device token when it is used (last_seen, last_client_ip, client_ips).

    This helps the admin panel display current connections and allows locking/revoking.
    """
    if not token:
        return
    tokens = load_device_tokens()
    if token not in tokens:
        return
    entry = tokens[token]
    entry['last_seen'] = datetime.now().isoformat()
    if user_agent:
        entry['user_agent'] = user_agent
    if client_ips:
        # store last_client_ip and accumulate a small history
        try:
            # preserve existing client_ips list
            existing = entry.get('client_ips') or []
            for ip in client_ips:
                if ip not in existing:
                    existing.append(ip)
            entry['client_ips'] = existing[-10:]
            entry['last_client_ip'] = client_ips[-1]
        except Exception:
            pass
    try:
        tokens[token] = entry
        save_device_tokens(tokens)
    except Exception:
        pass

def is_local_network(client_ip: str) -> bool:
    """Check if client IP is on local network (no auth needed)."""
    try:
        # Accept either a single IP string or an iterable of IPs
        ips = client_ip if isinstance(client_ip, (list, tuple)) else [client_ip]
        for ip_str in ips:
            try:
                ip = ipaddress.ip_address(ip_str)
                if any(ip in network for network in LOCAL_NETWORKS):
                    return True
            except ValueError:
                continue
    except Exception:
        pass
    return False

def get_client_ip(request: Request) -> str:
    """Get real client IP from X-Forwarded-For header or request client."""
    # Keep for compatibility: return the first IP in X-Forwarded-For (original behaviour)
    forwarded_for = request.headers.get("X-Forwarded-For", "") or request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        # Return the full list (comma-separated) as a list when needed elsewhere
        # Historically callers expected a single IP string; keep returning the first for backwards compatibility
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"

def get_client_ips(request: Request) -> list:
    """Return a list of client IPs from X-Forwarded-For or request.client.host.

    Some reverse proxies append multiple IPs; check all entries to detect a private/local client IP.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "") or request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return [p.strip() for p in forwarded_for.split(",") if p.strip()]
    if request.client and getattr(request.client, 'host', None):
        return [request.client.host]
    return ["0.0.0.0"]

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

    # Check for valid device token (remembered device)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if is_device_token_valid(token):
            tokens = load_device_tokens()
            role = tokens.get(token, {}).get("role")
            # update last_seen and client_ips for admin visibility
            try:
                ua = request.headers.get('User-Agent', '')
                touch_device_token(token, get_client_ips(request), ua)
            except Exception:
                pass
            if request.url.path.startswith("/admin") and role != "admin":
                return JSONResponse(status_code=403, content={"detail": "Admin access required."})
            return await call_next(request)

    # Public read-only toggle: allow GETs to metrics/analytics when DASHBOARD_PUBLIC is enabled
    try:
        if DASHBOARD_PUBLIC and request.method == "GET" and request.url.path.startswith(("/metrics", "/analytics")):
            return await call_next(request)
    except Exception:
        pass

    # Allow ingestion key to authenticate ingestion endpoints before the final API block
    try:
        from os import getenv
        ingest_key = getenv('INGESTION_KEY')
        if ingest_key and request.url.path.startswith('/api/ingest'):
            auth_header = request.headers.get('Authorization', '')
            bearer_key = auth_header[7:] if auth_header.startswith('Bearer ') else None
            header_key = request.headers.get('X-INGESTION-KEY') or request.headers.get('x-ingestion-key')
            if bearer_key == ingest_key or header_key == ingest_key:
                return await call_next(request)
    except Exception:
        pass
    
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
        return FileResponse("frontend/pages/index.html")  # Will add login UI to index.html
    
    return await call_next(request)
# Initialize database tables on startup
db.init_db()

# Backfill progress status (shared in-memory)
BACKFILL_PROGRESS = {
    'running': False,
    'total': 0,
    'processed': 0,
    'percent': 0,
    'last_updated': None,
    'errors': []
}

# Enable CORS for TV access from network (more restricted now with auth middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Still allow all origins, but auth middleware controls actual access
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEBHOOK_API_KEY = os.getenv("WEBHOOK_API_KEY", "")

@app.on_event("startup")
async def startup_event():
    """Start the background reset task and sync engineer stats"""
    sync_engineer_stats_on_startup(db_module=db)
    asyncio.create_task(check_daily_reset())
    # Warm commonly used dashboard caches to avoid slow cold-start requests
    try:
        asyncio.create_task(
            warm_cache_on_startup(
                db_module=db,
                qa_export_module=qa_export,
                cache_set=_set_cached_response,
            )
        )
    except Exception:
        pass

    # Start memory watchdog to clear cache if RSS grows too large
    try:
        asyncio.create_task(
            memory_watchdog(
                psutil_module=psutil,
                cache_clear=QA_CACHE.clear,
                take_tracemalloc_snapshot=take_tracemalloc_snapshot,
            )
        )
    except Exception:
        pass

# ============= AUTH ENDPOINTS =============
app.include_router(
    create_auth_router(
        admin_password=ADMIN_PASSWORD,
        manager_password=MANAGER_PASSWORD,
        device_token_expiry_days=DEVICE_TOKEN_EXPIRY_DAYS,
        get_client_ip=get_client_ip,
        get_client_ips=get_client_ips,
        is_local_network=is_local_network,
        is_device_token_valid=is_device_token_valid,
        load_device_tokens=load_device_tokens,
        save_device_tokens=save_device_tokens,
        touch_device_token=touch_device_token,
        generate_device_token=generate_device_token,
    )
)
app.include_router(
    create_admin_activity_router(
        require_admin=require_admin,
        load_device_tokens=load_device_tokens,
        activity_log=ACTIVITY_LOG,
        get_activity_writer=lambda: getattr(app.state, "activity_writer", None),
    )
)
app.include_router(
    create_admin_devices_router(
        require_admin=require_admin,
        require_manager_or_admin=require_manager_or_admin,
        load_device_tokens=load_device_tokens,
        save_device_tokens=save_device_tokens,
        get_last_server_error=lambda: LAST_SERVER_ERROR,
    )
)
app.include_router(
    create_admin_diagnostics_router(
        require_admin=require_admin,
        get_mariadb_connection=qa_export.get_mariadb_connection,
    )
)
app.include_router(
    create_admin_initials_router(
        require_admin=require_admin,
        db_module=db,
    )
)
app.include_router(
    create_admin_maintenance_router(
        require_admin=require_admin,
        db_module=db,
        take_tracemalloc_snapshot=take_tracemalloc_snapshot,
    )
)
app.include_router(
    create_admin_backfill_router(
        require_admin=require_admin,
        require_manager_or_admin=require_manager_or_admin,
        db_module=db,
        progress_state=BACKFILL_PROGRESS,
    )
)
app.include_router(
    create_admin_exports_router(
        require_manager_or_admin=require_manager_or_admin,
        db_module=db,
        excel_export_module=excel_export,
        psutil_module=psutil,
        trace_snapshot_threshold_mb=TRACE_SNAPSHOT_THRESHOLD_MB,
        take_tracemalloc_snapshot=take_tracemalloc_snapshot,
        set_last_server_error=lambda payload: globals().__setitem__("LAST_SERVER_ERROR", payload),
    )
)
app.include_router(
    create_erasure_insights_router(
        db_module=db,
    )
)
app.include_router(
    create_qa_insights_router(
        cache_get=_get_cached_response,
        cache_set=_set_cached_response,
    )
)
app.include_router(
    create_metrics_analytics_router(
        db_module=db,
        cache_get=_get_cached_response,
        cache_set=_set_cached_response,
    )
)
app.include_router(
    create_webhooks_router(
        db_module=db,
        webhook_api_key=WEBHOOK_API_KEY,
    )
)
app.include_router(
    create_device_lookup_router(
        db_module=db,
        qa_export_module=qa_export,
        require_manager_or_admin=require_manager_or_admin,
        get_role_from_request=get_role_from_request,
        ttl_cache_cls=TTLCache,
    )
)
app.include_router(
    create_bottleneck_router(
        db_module=db,
        qa_export_module=qa_export,
        require_manager_or_admin=require_manager_or_admin,
        compute_qa_dashboard_data=compute_qa_dashboard_data,
        cache_get=_get_cached_response,
        cache_set=_set_cached_response,
        ttl_cache_cls=TTLCache,
        backfill_progress=BACKFILL_PROGRESS,
    )
)

# ===== HWID Capture Endpoint =====

HWID_LOG_PATH = os.getenv("HWID_LOG_PATH", "logs/hwid_log.jsonl")

FRONTEND_PAGES_DIR = os.path.join("frontend", "pages")
FRONTEND_JS_DIR = os.path.join("frontend", "js")
FRONTEND_CSS_DIR = os.path.join("frontend", "css")

app.include_router(
    create_static_pages_router(
        frontend_pages_dir=FRONTEND_PAGES_DIR,
        frontend_js_dir=FRONTEND_JS_DIR,
        frontend_css_dir=FRONTEND_CSS_DIR,
        config_json_path=os.path.join("config", "config.json"),
    )
)

app.include_router(
    create_hwid_router(
        webhook_api_key=WEBHOOK_API_KEY,
        hwid_log_path=HWID_LOG_PATH,
    )
)


# Serve static files (HTML, CSS, JS)
app.mount("/", StaticFiles(directory=".", html=True), name="static")

