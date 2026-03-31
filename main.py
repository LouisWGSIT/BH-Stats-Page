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
from backend.app.routes.erasure_insights import create_erasure_insights_router
from backend.app.routes.hwid import create_hwid_router
from backend.app.routes.metrics_analytics import create_metrics_analytics_router
from backend.app.routes.qa_insights import compute_qa_dashboard_data, create_qa_insights_router
from backend.app.routes.static_pages import create_static_pages_router
import logging
from backend.logging_config import configure_logging
from collections import OrderedDict
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


# Simple thread-safe TTL + max-size cache to avoid unbounded growth in-process
class TTLCache:
    def __init__(self, maxsize: int = 256, ttl: float = 60.0):
        self.maxsize = maxsize
        self.ttl = ttl
        self._store = OrderedDict()  # key -> (value, ts)
        self._lock = threading.Lock()

    def get(self, key, default=None):
        now = time()
        with self._lock:
            item = self._store.get(key)
            if not item:
                return default
            value, ts = item
            if now - ts > self.ttl:
                try:
                    del self._store[key]
                except Exception:
                    pass
                return default
            # move to end as recently used
            try:
                self._store.move_to_end(key)
            except Exception:
                pass
            return value

    def set(self, key, value):
        now = time()
        with self._lock:
            if key in self._store:
                try:
                    del self._store[key]
                except Exception:
                    pass
            self._store[key] = (value, now)
            # Evict oldest if over capacity
            try:
                while len(self._store) > self.maxsize:
                    self._store.popitem(last=False)
            except Exception:
                pass

    def clear(self):
        with self._lock:
            self._store.clear()


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
MANAGER_PASSWORD = os.getenv("DASHBOARD_MANAGER_PASSWORD", "Gr33n5af3!")
ADMIN_PASSWORD = os.getenv("DASHBOARD_ADMIN_PASSWORD", "P!nkarrow")

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


# Warm common dashboard caches on startup to avoid cold-start slowness
async def warm_cache_on_startup():
    try:
        # brief delay to allow startup syncs to complete
        await asyncio.sleep(1)
        # daily metrics
        try:
            data = db.get_daily_stats()
            _set_cached_response('/metrics/today', data)
        except Exception:
            pass

        # monthly / momentum data
        try:
            data = db.get_monthly_momentum()
            _set_cached_response('/metrics/monthly-momentum', data)
        except Exception:
            pass

        # summary (if available via db helper)
        try:
            if hasattr(db, 'get_summary'):
                data = db.get_summary()
                _set_cached_response('/metrics/summary', data)
        except Exception:
            pass

        # QA insights window (last 7 days) - use qa_export helper if present
        try:
            if hasattr(qa_export, 'get_qa_daily_totals_range'):
                end = datetime.now().date()
                start = end - timedelta(days=7)
                qa_data = qa_export.get_qa_daily_totals_range(start, end)
                _set_cached_response('/api/insights/qa', {'data': qa_data})
        except Exception:
            pass

    except Exception:
        # never fail startup because of warm cache
        pass


# Memory watchdog: clear QA_CACHE when process RSS grows above a threshold
async def memory_watchdog():
    try:
        if psutil is None:
            return
        # Determine memory limit (bytes) from env or default 512MB
        try:
            limit = int(os.getenv('MEMORY_LIMIT_BYTES', str(512 * 1024 * 1024)))
        except Exception:
            limit = 512 * 1024 * 1024
        threshold = int(limit * 0.85)
        while True:
            try:
                rss = psutil.Process().memory_info().rss
                if rss and rss >= threshold:
                    try:
                        QA_CACHE.clear()
                    except Exception:
                        pass
                    # take an optional memory snapshot if tracemalloc enabled
                    try:
                        take_tracemalloc_snapshot(reason='memory_watchdog', meta={'rss': rss})
                    except Exception:
                        pass
                await asyncio.sleep(30)
            except Exception:
                await asyncio.sleep(30)
    except Exception:
        return


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

# Ingestion endpoint for external erasure producers (secure)
@app.post("/api/ingest/local-erasure")
async def ingest_local_erasure(request: Request):
    """Accept a JSON erasure event and insert into local_erasures via database.add_local_erasure.

    Authentication: supply the ingestion API key via `Authorization: Bearer <INGESTION_KEY>`
    or `X-INGESTION-KEY` header. The key should be set in env `INGESTION_KEY` on the server.
    """
    import os
    try:
        # Read raw body for HMAC verification, then parse JSON
        raw_body = await request.body()
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON"})

    # Prefer HMAC verification if a secret is configured
    ingestion_secret = os.getenv('INGESTION_SECRET')
    if ingestion_secret:
        import hmac, hashlib
        # Accept common header names
        sig_header = (request.headers.get('X-Signature') or
                      request.headers.get('X-Hub-Signature-256') or
                      request.headers.get('X-Hub-Signature') or
                      request.headers.get('x-signature') or
                      request.headers.get('x-hub-signature-256') or
                      request.headers.get('x-hub-signature'))
        if not sig_header:
            return JSONResponse(status_code=401, content={"detail": "Missing signature header"})

        # Normalize header value (allow formats like 'sha256=<hex>' or raw hex)
        if sig_header.startswith('sha256='):
            recv_hex = sig_header.split('=', 1)[1]
        else:
            recv_hex = sig_header

        try:
            expected = hmac.new(ingestion_secret.encode('utf-8'), raw_body or b'', hashlib.sha256).hexdigest()
        except Exception:
            return JSONResponse(status_code=500, content={"detail": "HMAC computation failed"})

        # Use timing-safe comparison
        if not hmac.compare_digest(expected, recv_hex):
            return JSONResponse(status_code=401, content={"detail": "Invalid signature"})
    else:
        # Fallback: legacy ingestion key behavior
        ingestion_key = os.getenv('INGESTION_KEY')
        if not ingestion_key:
            return JSONResponse(status_code=403, content={"detail": "Ingestion not configured on server"})

        auth_header = request.headers.get('Authorization', '')
        bearer = auth_header[7:] if auth_header.startswith('Bearer ') else None
        header_key = request.headers.get('X-INGESTION-KEY') or request.headers.get('x-ingestion-key')
        if (bearer != ingestion_key) and (header_key != ingestion_key):
            return JSONResponse(status_code=401, content={"detail": "Invalid ingestion key"})

    # Extract fields from payload
    stockid = body.get('stockid')
    system_serial = body.get('system_serial') or body.get('systemSerial')
    job_id = body.get('job_id') or body.get('jobId')
    ts = body.get('ts') or body.get('timestamp')
    warehouse = body.get('warehouse')
    source = body.get('source') or 'ingest'
    payload = body.get('payload') or body

    try:
        # Import here to avoid top-level cycles
        from database import add_local_erasure
        add_local_erasure(stockid=stockid, system_serial=system_serial, job_id=job_id, ts=ts, warehouse=warehouse, source=source, payload=payload)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": f"failed to insert: {e}"})

    return JSONResponse(status_code=200, content={"ok": True, "inserted": True})


# Enable CORS for TV access from network (more restricted now with auth middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Still allow all origins, but auth middleware controls actual access
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
    # Warm commonly used dashboard caches to avoid slow cold-start requests
    try:
        asyncio.create_task(warm_cache_on_startup())
    except Exception:
        pass

    # Start memory watchdog to clear cache if RSS grows too large
    try:
        asyncio.create_task(memory_watchdog())
    except Exception:
        pass

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

    # Ensure a canonical detailed erasure row is written so all aggregates use the same source of truth.
    try:
        job_id = payload.get('jobId') or payload.get('assetTag') or payload.get('id') or None
        # duration if present
        duration = payload.get('durationSec') or payload.get('duration') or None
        # timestamp if present (try to normalize simple epoch or ISO strings)
        ts_in = payload.get('timestamp') or payload.get('ts') or None
        ts = None
        if isinstance(ts_in, (int, float)):
            try:
                from datetime import datetime, timezone
                ts = datetime.fromtimestamp(float(ts_in), tz=timezone.utc).isoformat()
            except Exception:
                ts = None
        elif isinstance(ts_in, str) and ts_in.strip():
            ts = ts_in
        # Write minimal detailed event into `erasures` so downstream syncs read it.
        try:
            db.add_erasure_event(event='success', device_type=device_type, initials=initials, duration_sec=(int(duration) if duration is not None and str(duration).isdigit() else None), job_id=job_id, ts=ts)
        except Exception as _e:
            print(f"[engineer_erasure] failed to add detailed erasure event: {_e}")

        # Also keep lightweight summary counters in sync (daily counters and per-engineer totals)
        db.increment_stat('erased', 1)
        if job_id:
            try:
                db.mark_job_seen(job_id)
            except Exception:
                pass

        # Increment count for this engineer (overall and per device type)
        db.increment_engineer_count(initials, 1)
        db.increment_engineer_type_count(device_type, initials, 1)
    except Exception as e:
        print(f"[engineer_erasure] error updating counts: {e}")
    engineers = db.get_top_engineers(limit=10)
    engineer_count = next((e["count"] for e in engineers if e["initials"] == initials), 0)

    return {"status": "ok", "engineer": initials, "count": engineer_count}

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
    
    import time, logging
    logger = logging.getLogger('device_lookup')
    try:
        # quick guard: ensure connection runs read-only where possible
        try:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
        except Exception:
            pass
        start_all = time.time()
        # honor per-request audit lookback (default 30 days, deep lookup 120 days)
        try:
            audit_days = int(request.query_params.get('audit_days', '30'))
        except Exception:
            audit_days = 30
        import qa_export
        conn = qa_export.get_mariadb_connection()
        if not conn:
            raise HTTPException(status_code=500, detail="Database connection failed")
        # ensure read-only intent to avoid accidental write locks where supported
        try:
            conn.autocommit = True
        except Exception:
            pass
        try:
            cur_tmp = conn.cursor()
            try:
                cur_tmp.execute("SET SESSION TRANSACTION READ ONLY")
            except Exception:
                pass
            try:
                cur_tmp.close()
            except Exception:
                pass
        except Exception:
            pass

        cursor = conn.cursor()
        
        # 1. Check ITAD_asset_info for asset details
        asset_row = None
        # Some deployments have newer optional columns (quarantine, etc.).
        # Probe INFORMATION_SCHEMA for the presence of the `quarantine` column
        # to avoid issuing a SELECT that references missing columns (which
        # caused the "Unknown column 'quarantine'" error previously).
        try:
            try:
                cursor.execute(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s AND TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = %s",
                    ("ITAD_asset_info", "quarantine")
                )
                has_quarantine = cursor.fetchone() is not None
            except Exception:
                # If the probe fails (lack of privilege), default to safe path
                has_quarantine = False

            if has_quarantine:
                cursor.execute("""
                    SELECT stockid, serialnumber, manufacturer, description, `condition`, 
                           COALESCE(pallet_id, palletID) as pallet_id, last_update, location,
                           roller_location, stage_current, stage_next, received_date,
                           quarantine, quarantine_reason, process_complete,
                           de_complete, de_completed_by, de_completed_date
                    FROM ITAD_asset_info 
                    WHERE stockid = %s OR serialnumber = %s
                """, (stock_id, stock_id))
            else:
                cursor.execute("""
                    SELECT stockid, serialnumber, manufacturer, description, `condition`, 
                           COALESCE(pallet_id, palletID) as pallet_id, last_update, location
                    FROM ITAD_asset_info 
                    WHERE stockid = %s OR serialnumber = %s
                """, (stock_id, stock_id))
            asset_row = cursor.fetchone()
        except Exception:
            # As a final fallback, try the minimal projection to avoid hard failures
            try:
                cursor.execute("""
                    SELECT stockid, serialnumber, manufacturer, description, `condition`, 
                           COALESCE(pallet_id, palletID) as pallet_id, last_update, location
                    FROM ITAD_asset_info 
                    WHERE stockid = %s OR serialnumber = %s
                """, (stock_id, stock_id))
                asset_row = cursor.fetchone()
            except Exception:
                asset_row = None
        row = asset_row
        if row:
            results["found_in"].append("ITAD_asset_info")
            results["asset_info"] = {
                "stock_id": row[0],
                "serial": row[1],
                "manufacturer": row[2],
                "model": row[3],
                "condition": row[4],
                "pallet_id": row[5],
                "last_update": str(row[6]) if row[6] else None,
                "location": row[7],
            }
            if len(row) > 8:
                results["asset_info"].update({
                    "roller_location": row[8],
                    "stage_current": row[9],
                    "stage_next": row[10],
                    "received_date": str(row[11]) if row[11] else None,
                    "quarantine": row[12],
                    "quarantine_reason": row[13],
                    "process_complete": row[14],
                    "de_complete": row[15] if len(row) > 15 else None,
                    "de_completed_by": row[16] if len(row) > 16 else None,
                    "de_completed_date": str(row[17]) if len(row) > 17 and row[17] else None,
                })
            if row[5]:  # pallet_id
                results["pallet_info"] = {"pallet_id": row[5]}
            if row[7]:  # location
                results["last_known_location"] = row[7]
            # Asset info is recorded in `results["asset_info"]` but we avoid
            # emitting a separate generic timeline row here since it often
            # contains no human-friendly location. Timeline rows are built from
            # richer, action-oriented sources (QA, audit, erasure, pallet).
        
        # 2. Check Stockbypallet for pallet assignment
        t0 = time.time()
        cursor.execute("""
            SELECT stockid, pallet_id
            FROM Stockbypallet
            WHERE stockid = %s
        """, (stock_id,))
        row = cursor.fetchone()
        logger.info("Stockbypallet lookup: %.3fs", time.time()-t0)
        if row:
            results["found_in"].append("Stockbypallet")
            if not results["pallet_info"]:
                results["pallet_info"] = {}
            results["pallet_info"]["pallet_id"] = row[1]
        
        # 3. Get pallet details if we have a pallet_id
        # Guard against unexpected None for `results` or `pallet_info`.
        pallet_id = None
        pallet_info = (results or {}).get("pallet_info") if isinstance(results, dict) else None
        if pallet_info and pallet_info.get("pallet_id"):
            pallet_id = pallet_info.get("pallet_id")
            cursor.execute("""
                SELECT pallet_id, destination, pallet_location, pallet_status, create_date
                FROM ITAD_pallet
                WHERE pallet_id = %s
            """, (pallet_id,))
            row = cursor.fetchone()
            if row:
                results["pallet_info"].update({
                    "destination": row[1],
                    "location": row[2],
                    "status": row[3],
                    "create_date": str(row[4]) if row[4] else None,
                })
                # Add a dedicated pallet creation/assignment event to the timeline
                try:
                    results.setdefault("timeline", [])
                    pallet_ts = str(row[4]) if row[4] else None
                    results["timeline"].append({
                        "timestamp": pallet_ts,
                        "stage": f"Pallet {pallet_id}",
                        "user": None,
                        "location": row[2],
                        "source": "ITAD_pallet",
                        "pallet_id": pallet_id,
                        "pallet_destination": row[1],
                        "pallet_location": row[2],
                        "details": "pallet record",
                    })
                except Exception:
                    pass
        
        # 4. Check ITAD_QA_App for sorting scans (include richer metadata when available)
        # Decide whether extended QA projection is safe by probing INFORMATION_SCHEMA
        t0 = time.time()
        try:
            try:
                cursor.execute(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s AND TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = %s",
                    ("ITAD_QA_App", "sales_order")
                )
                has_sales_order = cursor.fetchone() is not None
            except Exception:
                has_sales_order = False

            # Respect audit_days to limit QA scan lookback and avoid long-running queries
            if has_sales_order:
                cursor.execute("""
                    SELECT added_date, username, scanned_location, stockid, photo_location, sales_order
                    FROM ITAD_QA_App
                    WHERE stockid = %s
                      AND DATE(added_date) >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    ORDER BY added_date ASC
                """, (stock_id, audit_days))
            else:
                cursor.execute("""
                    SELECT added_date, username, scanned_location, stockid
                    FROM ITAD_QA_App
                    WHERE stockid = %s
                      AND DATE(added_date) >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    ORDER BY added_date ASC
                """, (stock_id, audit_days))
            rows = cursor.fetchall()
        except Exception as _ex:
            # If anything goes wrong, avoid raising DB error to caller; log and continue
            logger.exception("[device_lookup] QA projection probe/execute failed: %s", _ex)
            rows = []
        logger.info("ITAD_QA_App lookup: %.3fs", time.time()-t0)

        # start background confirmed_locations read to overlap IO
        import sqlite3
        from concurrent.futures import ThreadPoolExecutor
        def _fetch_confirmed():
            try:
                sqlite_conn = sqlite3.connect(db.DB_PATH)
                sqlite_cur = sqlite_conn.cursor()
                sqlite_cur.execute("SELECT location, user, ts FROM confirmed_locations WHERE stockid = ? ORDER BY ts DESC LIMIT 1", (stock_id,))
                conf = sqlite_cur.fetchone()
                sqlite_cur.close()
                sqlite_conn.close()
                return conf
            except Exception:
                return None
        try:
            _executor = ThreadPoolExecutor(max_workers=1)
            conf_future = _executor.submit(_fetch_confirmed)
        except Exception:
            conf_future = None

        for row in rows:
            try:
                # Unpack defensively depending on which projection succeeded
                if len(row) >= 6:
                    added_date, username, scanned_location, q_stockid, photo_location, sales_order = row
                elif len(row) >= 4:
                    added_date, username, scanned_location, q_stockid = row[0], row[1], row[2], row[3]
                    photo_location = None
                    sales_order = None
                else:
                    added_date, username, scanned_location = (row[0], row[1], row[2])
                    q_stockid = None
                    photo_location = None
                    sales_order = None
            except Exception:
                added_date, username, scanned_location = (None, None, None)
                q_stockid = None
                photo_location = None
                sales_order = None
            results.setdefault("found_in", [])
            if "ITAD_QA_App" not in results["found_in"]:
                results["found_in"].append("ITAD_QA_App")
            results["timeline"].append({
                "timestamp": str(added_date) if added_date is not None else None,
                "stage": "Sorting",
                "user": username,
                "location": scanned_location,
                "source": "ITAD_QA_App",
                "stockid": q_stockid or stock_id,
                "serial": None,
                "device_type": None,
                "manufacturer": (results.get("asset_info") or {}).get("manufacturer"),
                "model": (results.get("asset_info") or {}).get("model"),
                "pallet_id": (results.get("pallet_info") or {}).get("pallet_id"),
                "pallet_destination": (results.get("pallet_info") or {}).get("destination"),
                "pallet_location": (results.get("pallet_info") or {}).get("location"),
                "sales_order": sales_order,
                "photo_location": photo_location,
            })
            results["last_known_user"] = username
            results["last_known_location"] = scanned_location
        
        # 5. Check audit_master for QA submissions (include descriptions)
        cursor.execute("""
            SELECT date_time, audit_type, user_id, log_description, log_description2
            FROM audit_master
            WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload', 
                     'Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload')
              AND (log_description LIKE %s OR log_description2 LIKE %s)
              AND date_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
            ORDER BY date_time ASC
        """, (f'%{stock_id}%', f'%{stock_id}%', audit_days))
        for row in cursor.fetchall():
            try:
                date_time, audit_type, user_id, log_description, log_description2 = row
            except Exception:
                date_time, audit_type, user_id = row[0], row[1], row[2]
                log_description = None
                log_description2 = None
            results.setdefault("found_in", [])
            results["found_in"].append("audit_master") if "audit_master" not in results["found_in"] else None
            stage = "QA Data Bearing" if str(audit_type or '').startswith("DEAPP_") else "QA Non-Data Bearing"
            results["timeline"].append({
                "timestamp": str(date_time),
                "stage": stage,
                "user": user_id,
                "location": None,
                "source": "audit_master",
                "stockid": stock_id,
                "log_description": log_description,
                "log_description2": log_description2,
            })
            results["last_known_user"] = user_id
        
        # 6. Check ITAD_asset_info_blancco for erasure records (include serial/manufacturer/model)
        # Probe INFORMATION_SCHEMA to choose safe blancco projection
        try:
            try:
                cursor.execute(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s AND TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = %s",
                    ("ITAD_asset_info_blancco", "added_date")
                )
                has_added_date = cursor.fetchone() is not None
            except Exception:
                has_added_date = False

            if has_added_date:
                cursor.execute("""
                    SELECT stockid, serial, manufacturer, model, erasure_status, added_date, username
                    FROM ITAD_asset_info_blancco
                    WHERE stockid = %s OR serial = %s
                """, (stock_id, stock_id))
            else:
                cursor.execute("""
                    SELECT stockid, serial, manufacturer, model, erasure_status
                    FROM ITAD_asset_info_blancco
                    WHERE stockid = %s OR serial = %s
                """, (stock_id, stock_id))
            b_rows = cursor.fetchall()
        except Exception as _ex_b:
            print(f"[device_lookup] Blancco projection probe/execute failed: {_ex_b}")
            b_rows = []

        for row in b_rows:
            try:
                if len(row) >= 7:
                    b_stockid, b_serial, b_manufacturer, b_model, b_status, b_added, b_user = row
                elif len(row) >= 5:
                    b_stockid, b_serial, b_manufacturer, b_model, b_status = row[0], row[1], row[2], row[3], row[4]
                    b_added = None
                    b_user = None
                else:
                    # Unexpected shape
                    continue
            except Exception:
                b_stockid = b_serial = b_manufacturer = b_model = b_status = None
                b_added = None
                b_user = None
            results.setdefault("found_in", [])
            if "ITAD_asset_info_blancco" not in results["found_in"]:
                results["found_in"].append("ITAD_asset_info_blancco")
            # Represent Blancco rows as a canonical 'Erasure station' timeline event
            # (previously surfaced as 'Erasure (Successful)' or similar). The
            # database naming is inconsistent: Blancco reports may appear to be
            # labelled as 'erasure' or even show operator names that are actually
            # QA actions. We surface the canonical stage name 'Erasure station'
            # and include the raw blancco status and operator so the UI can
            # display the authoritative Blancco evidence without creating a
            # separate 'Erasure (Blancco)' location to look in.
            # Try to merge Blancco evidence into an existing nearby QA/audit event
                # If we already have a local_erasures provenance for this stock/serial,
                # skip adding the MariaDB Blancco copy to avoid duplicate/confusing entries.
                try:
                    suppressed = False
                    existing = results.get('timeline', []) or []
                    for ev in existing:
                        try:
                            if ev.get('source') == 'local_erasures':
                                # match by serial or stockid/job
                                if b_serial and (str(ev.get('system_serial') or ev.get('serial') or '').strip() == str(b_serial).strip()):
                                    suppressed = True
                                    break
                                if b_stockid and (str(ev.get('job_id') or ev.get('stockid') or '') == str(b_stockid)):
                                    suppressed = True
                                    break
                        except Exception:
                            continue
                    if not suppressed:
                        # Represent Blancco rows as a canonical 'Erasure station' timeline event
                        # (previously surfaced as 'Erasure (Successful)' or similar). The
                        # database naming is inconsistent: Blancco reports may appear to be
                        # labelled as 'erasure' or even show operator names that are actually
                        # QA actions. We surface the canonical stage name 'Erasure station'
                        # and include the raw blancco status and operator so the UI can
                        # display the authoritative Blancco evidence without creating a
                        # separate 'Erasure (Blancco)' location to look in.
                        # Try to merge Blancco evidence into an existing nearby QA/audit event
                        from datetime import datetime as _dt
                        MERGE_WINDOW = int(os.getenv('MERGE_TIMELINE_WINDOW_SECONDS', '60'))

                        def _parse_ts_local(ts):
                            if not ts:
                                return None
                            try:
                                if isinstance(ts, str):
                                    try:
                                        return _dt.fromisoformat(ts.replace('Z', '+00:00'))
                                    except Exception:
                                        pass
                                    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                                        try:
                                            return _dt.strptime(ts, fmt)
                                        except Exception:
                                            continue
                                elif hasattr(ts, 'timetuple'):
                                    return ts
                            except Exception:
                                return None

                        def _try_attach_blancco():
                            if not b_added:
                                return False
                            try:
                                b_dt = _parse_ts_local(b_added)
                            except Exception:
                                b_dt = None
                            for ev in results.get('timeline', []):
                                try:
                                    if not ev.get('timestamp'):
                                        continue
                                    ev_dt = _parse_ts_local(ev.get('timestamp'))
                                    if not ev_dt or not b_dt:
                                        continue
                                    if abs((ev_dt - b_dt).total_seconds()) <= MERGE_WINDOW:
                                        ev.setdefault('sources', [])
                                        ev['sources'].append({
                                            'type': 'blancco',
                                            'source': 'ITAD_asset_info_blancco',
                                            'ts': b_added,
                                            'initials': b_user,
                                            'status': b_status,
                                            'manufacturer': b_manufacturer,
                                            'model': b_model,
                                            'serial': b_serial,
                                        })
                                        ev['is_blancco_record'] = True
                                        return True
                                except Exception:
                                    continue
                            return False

                        attached = _try_attach_blancco()
                        if not attached:
                            results["timeline"].append({
                                "timestamp": str(b_added) if b_added else None,
                                "stage": "Blancco record",
                                "user": b_user,
                                "location": None,
                                "source": "ITAD_asset_info_blancco",
                                "serial": b_serial,
                                "stockid": b_stockid,
                                "manufacturer": b_manufacturer,
                                "model": b_model,
                                "details": f"{b_manufacturer} {b_model}" if b_manufacturer or b_model else None,
                                "blancco_status": b_status,
                                "is_blancco_record": True,
                            })
                except Exception:
                    # fallback to appending as before
                    # fallback: append as a Blancco record (see note above)
                    results["timeline"].append({
                        "timestamp": str(b_added) if b_added else None,
                        "stage": "Blancco record",
                        "user": b_user,
                        "location": None,
                        "source": "ITAD_asset_info_blancco",
                        "serial": b_serial,
                        "stockid": b_stockid,
                        "manufacturer": b_manufacturer,
                        "model": b_model,
                        "details": f"{b_manufacturer} {b_model}" if b_manufacturer or b_model else None,
                        "blancco_status": b_status,
                        "is_blancco_record": True,
                    })
            try:
                from datetime import datetime as _dt
                MERGE_WINDOW = int(os.getenv('MERGE_TIMELINE_WINDOW_SECONDS', '60'))

                def _parse_ts_local(ts):
                    if not ts:
                        return None
                    try:
                        if isinstance(ts, str):
                            try:
                                return _dt.fromisoformat(ts.replace('Z', '+00:00'))
                            except Exception:
                                pass
                            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                                try:
                                    return _dt.strptime(ts, fmt)
                                except Exception:
                                    continue
                        elif hasattr(ts, 'timetuple'):
                            return ts
                    except Exception:
                        return None
                    return None

                merged_into_existing = False
                b_dt = _parse_ts_local(str(b_added)) if b_added else None
                for ev in results.get('timeline', []):
                    try:
                        ev_ts = _parse_ts_local(ev.get('timestamp'))
                        if not ev_ts or not b_dt:
                            # also allow exact string match as fallback
                            if ev.get('timestamp') and b_added and str(ev.get('timestamp')) == str(b_added):
                                ev.setdefault('sources', [ev.get('source')])
                                if 'ITAD_asset_info_blancco' not in ev['sources']:
                                    ev['sources'].append('ITAD_asset_info_blancco')
                                ev['blancco_status'] = b_status
                                ev['is_blancco_record'] = True
                                merged_into_existing = True
                                break
                            continue
                        diff = abs((ev_ts - b_dt).total_seconds())
                        if diff <= MERGE_WINDOW and (str(ev.get('source') or '').lower().startswith('audit_master') or 'qa' in str(ev.get('stage') or '').lower()):
                            # attach blancco provenance to this existing QA/audit event
                            ev.setdefault('sources', [ev.get('source')])
                            if 'ITAD_asset_info_blancco' not in ev['sources']:
                                ev['sources'].append('ITAD_asset_info_blancco')
                            ev['blancco_status'] = b_status
                            ev['is_blancco_record'] = True
                            merged_into_existing = True
                            break
                    except Exception:
                        continue
                if not merged_into_existing:
                    # Do NOT create a separate 'Erasure station' search location
                    # from MariaDB Blancco rows. In this deployment Blancco rows
                    # in MariaDB are a downstream copy of server messages and
                    # should only act as provenance. If they don't merge into an
                    # existing QA/audit event, append a lightweight 'Blancco
                    # record' timeline entry for visibility but it will not be
                    # treated as a separate plausible search location.
                    results["timeline"].append({
                        "timestamp": str(b_added) if b_added else None,
                        "stage": "Blancco record",
                        "user": b_user,
                        "location": None,
                        "source": "ITAD_asset_info_blancco",
                        "serial": b_serial,
                        "stockid": b_stockid,
                        "manufacturer": b_manufacturer,
                        "model": b_model,
                        "details": f"{b_manufacturer} {b_model}" if b_manufacturer or b_model else None,
                        "blancco_status": b_status,
                        "is_blancco_record": True,
                    })
            except Exception:
                # fallback to appending as before
                # fallback: append as a Blancco record (see note above)
                results["timeline"].append({
                    "timestamp": str(b_added) if b_added else None,
                    "stage": "Blancco record",
                    "user": b_user,
                    "location": None,
                    "source": "ITAD_asset_info_blancco",
                    "serial": b_serial,
                    "stockid": b_stockid,
                    "manufacturer": b_manufacturer,
                    "model": b_model,
                    "details": f"{b_manufacturer} {b_model}" if b_manufacturer or b_model else None,
                    "blancco_status": b_status,
                    "is_blancco_record": True,
                })
        
        cursor.close()
        conn.close()
        
        # 7. Check local SQLite erasures table
        try:
            import sqlite3
            sqlite_conn = sqlite3.connect(db.DB_PATH)
            sqlite_cursor = sqlite_conn.cursor()
            # Build candidate identifiers: include the requested stock_id plus
            # any serial known from asset_info so that lookups by stock id
            # also match erasure rows recorded by serial number.
            candidates = [str(stock_id)]
            try:
                ai = results.get('asset_info') or {}
                asset_serial = (ai.get('serial') or '').strip()
                if asset_serial and asset_serial not in candidates:
                    candidates.append(asset_serial)
            except Exception:
                asset_serial = None

            # Prepare placeholders and parameters for IN (...) clauses
            placeholders = ','.join(['?'] * len(candidates))
            params = tuple(candidates)

            sqlite_cursor.execute(f"""
                SELECT ts, date, initials, device_type, event, manufacturer, model, system_serial, disk_serial, job_id, drive_size, drive_type, drive_count
                FROM erasures
                WHERE system_serial IN ({placeholders}) OR disk_serial IN ({placeholders}) OR job_id IN ({placeholders})
                ORDER BY date ASC, ts ASC
            """, params * 3)
            for row in sqlite_cursor.fetchall():
                try:
                    ts, date_str, initials, device_type, event, manufacturer, model, system_serial, disk_serial, job_id, drive_size, drive_type, drive_count = row
                except Exception:
                    ts, date_str, initials, device_type, event = row[0], row[1], row[2], row[3], row[4]
                    manufacturer = model = system_serial = disk_serial = job_id = drive_size = drive_type = drive_count = None
                results.setdefault("found_in", [])
                results["found_in"].append("local_erasures") if "local_erasures" not in results["found_in"] else None

                # Build a provenance object for this erasure record
                erasure_prov = {
                    "type": "erasure",
                    "source": "local_erasures",
                    "ts": ts or date_str,
                    "initials": initials,
                    "job_id": job_id,
                    "device_type": device_type,
                    "manufacturer": manufacturer,
                    "model": model,
                    "system_serial": system_serial,
                    "disk_serial": disk_serial,
                    "drive_size": drive_size,
                    "drive_type": drive_type,
                    "drive_count": drive_count,
                }

                # Try to attach this erasure provenance to a nearby QA/audit/asset event
                attached = False
                try:
                    from datetime import datetime as _dt
                    MERGE_WINDOW = int(os.getenv('MERGE_TIMELINE_WINDOW_SECONDS', '60'))

                    def _to_dt(val):
                        if not val:
                            return None
                        if isinstance(val, _dt):
                            return val
                        try:
                            if isinstance(val, str):
                                return _dt.fromisoformat(val.replace('Z', '+00:00'))
                        except Exception:
                            try:
                                # fallback common format
                                return _dt.strptime(val, '%Y-%m-%d %H:%M:%S')
                            except Exception:
                                return None
                        return None

                    e_ts = _to_dt(ts or date_str)
                    # prefer attaching to QA/audit/history/asset events
                    for ev in results.get('timeline', []):
                        try:
                            src = (ev.get('source') or '')
                            stage = (ev.get('stage') or '').lower()
                            # candidate sources/stages indicating QA/audit/asset
                            if not any(k in (src or '').lower() for k in ('audit_master', 'qa', 'qa_export', 'asset_info', 'qa_export.history')) and not ('qa' in stage or 'audit' in stage or 'history' in stage):
                                continue
                            ev_ts = _to_dt(ev.get('timestamp'))
                            if not ev_ts or not e_ts:
                                continue
                            delta = abs((ev_ts - e_ts).total_seconds())
                            if delta <= MERGE_WINDOW:
                                # attach provenance
                                ev.setdefault('sources', [])
                                ev['sources'].append(erasure_prov)
                                # mark that this event has blancco provenance for UI
                                ev['is_blancco_record'] = True
                                attached = True
                                try:
                                    logging.info("[device_lookup] attached erasure prov job=%s initials=%s stock=%s to event source=%s stage=%s ts=%s", job_id, initials, stock_id, ev.get('source'), ev.get('stage'), ev.get('timestamp'))
                                except Exception:
                                    pass
                                break
                        except Exception:
                            continue
                except Exception:
                    attached = False

                if not attached:
                    # Fallback: add a provenance-only timeline event
                    results["timeline"].append({
                        "timestamp": ts or date_str,
                        "stage": "Blancco record",
                        "user": initials,
                        "location": None,
                        "source": "local_erasures",
                        "device_type": device_type,
                        "manufacturer": manufacturer,
                        "model": model,
                        "system_serial": system_serial,
                        "disk_serial": disk_serial,
                        "job_id": job_id,
                        "drive_size": drive_size,
                        "drive_type": drive_type,
                        "drive_count": drive_count,
                        "is_blancco_record": True,
                        "sources": [erasure_prov],
                    })
                    try:
                        logging.info("[device_lookup] added blancco provenance-only event job=%s initials=%s stock=%s ts=%s", job_id, initials, stock_id, ts or date_str)
                    except Exception:
                        pass
                else:
                    # If attached, ensure last_known_user is captured
                    pass

                # Prefer last_known_user from QA/audit sources. Only set from
                # erasure initials if no last_known_user is already present.
                try:
                    if initials and not results.get("last_known_user"):
                        results["last_known_user"] = initials
                except Exception:
                    pass

                # Cleanup: find any MariaDB-copied Blancco timeline events that
                # refer to the same serial/job and merge them into the local
                # erasure provenance we just attached/added, then remove the
                # duplicate MariaDB event so the timeline is not confusing.
                try:
                    to_remove_idxs = []
                    # find the timeline event that contains our local_erasures provenance
                    target_ev = None
                    for tev in results.get('timeline', []):
                        try:
                            for s in tev.get('sources', []) or []:
                                if s and s.get('source') == 'local_erasures' and (s.get('job_id') == job_id or (s.get('system_serial') and system_serial and str(s.get('system_serial')) == str(system_serial))):
                                    target_ev = tev
                                    break
                            if target_ev:
                                break
                        except Exception:
                            continue

                    # If we didn't find a target event, try to locate a provenance-only
                    # local_erasures event we just appended (match by job_id and ts)
                    if not target_ev:
                        for tev in reversed(results.get('timeline', [])):
                            try:
                                if tev.get('source') == 'local_erasures' and (tev.get('job_id') == job_id or (system_serial and str(tev.get('system_serial') or '') == str(system_serial))):
                                    target_ev = tev
                                    break
                            except Exception:
                                continue

                    # Now find any ITAD_asset_info_blancco events that match and merge
                    for idx, ev in enumerate(list(results.get('timeline', []))):
                        try:
                            if (ev.get('source') or '').lower() == 'itad_asset_info_blancco' or 'blancco' in str(ev.get('source') or '').lower():
                                # match by serial or stockid/job
                                ev_serial = ev.get('serial') or ev.get('stockid') or ev.get('stockid')
                                ev_job = ev.get('stockid') or ev.get('job_id') or None
                                if (system_serial and ev_serial and str(ev_serial).strip() == str(system_serial).strip()) or (job_id and ev_job and str(ev_job).strip() == str(job_id).strip()):
                                    # attach this blancco event as provenance to target_ev if present
                                    if target_ev is not None:
                                        target_ev.setdefault('sources', [])
                                        blobj = {
                                            'type': 'blancco',
                                            'source': 'ITAD_asset_info_blancco',
                                            'ts': ev.get('timestamp'),
                                            'initials': ev.get('user'),
                                            'job_id': ev.get('stockid') or ev.get('job_id'),
                                            'manufacturer': ev.get('manufacturer'),
                                            'model': ev.get('model'),
                                            'serial': ev.get('serial') or ev.get('stockid'),
                                            'blancco_status': ev.get('blancco_status') or ev.get('status')
                                        }
                                        # avoid duplicates
                                        if not any((s.get('type') == 'blancco' and str(s.get('serial')) == str(blobj.get('serial'))) for s in target_ev.get('sources', [])):
                                            target_ev['sources'].append(blobj)
                                            target_ev['is_blancco_record'] = True
                                    # mark this blancco event for removal
                                    to_remove_idxs.append(idx)
                        except Exception:
                            continue

                    # remove in reverse order to keep indices valid
                    for ridx in sorted(set(to_remove_idxs), reverse=True):
                        try:
                            del results['timeline'][ridx]
                        except Exception:
                            continue
                    if to_remove_idxs:
                        try:
                            logging.info("[device_lookup] removed %d duplicate ITAD_asset_info_blancco events for job=%s serial=%s stock=%s", len(to_remove_idxs), job_id, system_serial, stock_id)
                        except Exception:
                            pass
                except Exception:
                    pass
            # Additionally, if a spreadsheet-style erasure table exists (imported manually),
            # query it by the same candidate serials and attach those rows as provenance.
            try:
                sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ('erasure_spreadsheet',))
                if sqlite_cursor.fetchone():
                    sqlite_cursor.execute(f"SELECT ts, initials, manufacturer, model, serial, job_id, drive_size FROM erasure_spreadsheet WHERE serial IN ({placeholders}) OR job_id IN ({placeholders}) ORDER BY ts ASC", params * 2)
                    for r in sqlite_cursor.fetchall():
                        try:
                            ets, einits, emfg, emod, eserial, ejob, edrive = r
                        except Exception:
                            continue
                        prov = {
                            'type': 'erasure_sheet',
                            'source': 'erasure_spreadsheet',
                            'ts': ets,
                            'initials': einits,
                            'job_id': ejob,
                            'manufacturer': emfg,
                            'model': emod,
                            'serial': eserial,
                            'drive_size': edrive,
                        }
                        # Attach as provenance-only event (will be merged if timestamps align)
                        results.setdefault('found_in', [])
                        if 'erasure_spreadsheet' not in results['found_in']:
                            results['found_in'].append('erasure_spreadsheet')
                        results['timeline'].append({
                            'timestamp': ets,
                            'stage': 'Erasure (spreadsheet)',
                            'user': einits,
                            'location': None,
                            'source': 'erasure_spreadsheet',
                            'manufacturer': emfg,
                            'model': emod,
                            'system_serial': eserial,
                            'job_id': ejob,
                            'drive_size': edrive,
                            'is_blancco_record': True,
                            'sources': [prov],
                        })
                        try:
                            logging.info("[device_lookup] attached erasure_spreadsheet prov job=%s initials=%s stock=%s", ejob, einits, stock_id)
                        except Exception:
                            pass
            except Exception:
                pass
            sqlite_cursor.close()
            sqlite_conn.close()
        except Exception as e:
            print(f"SQLite lookup error: {e}")

        # 7b. Enrich timeline with device history from QA export (broad range, best-effort)
        try:
            from datetime import date, timedelta
            # request a history window limited by audit_days to avoid fetching huge datasets
            start = date.today() - timedelta(days=audit_days)
            end = date.today()
            try:
                history = qa_export.get_device_history_range(start, end)
            except Exception:
                history = []
            # Debug: report how many history rows we received from qa_export
            try:
                hist_len = len(history) if isinstance(history, (list, tuple)) else 0
            except Exception:
                hist_len = 0
            logging.info("[device_lookup] qa_export.get_device_history_range returned %d rows for %s", hist_len, stock_id)

            for h in history:
                try:
                    # Normalize identifiers for flexible matching
                    h_stock = str(h.get('stockid') or '').strip()
                    h_serial = str(h.get('serial') or '').strip()
                    if not h_stock and not h_serial:
                        continue

                    norm_req = str(stock_id or '').strip().lower()
                    match = False
                    if h_stock and h_stock.strip().lower() == norm_req:
                        match = True
                    if h_serial and h_serial.strip().lower() == norm_req:
                        match = True
                    # Allow substring matches to catch slight formatting differences
                    if not match:
                        if h_stock and norm_req and norm_req in h_stock.lower():
                            match = True
                        if h_serial and norm_req and norm_req in h_serial.lower():
                            match = True
                    if not match:
                        continue

                    # Surface full history fields (manufacturer/model/pallet/device_type)
                    results.setdefault("found_in", [])
                    if "qa_export.history" not in results.get("found_in", []):
                        results["found_in"].append("qa_export.history")

                    ev = {
                        "timestamp": h.get('timestamp'),
                        "stage": h.get('stage') or 'History',
                        "user": h.get('user'),
                        "location": h.get('location'),
                        "source": h.get('source') or 'qa_export.history',
                        "stockid": h_stock or None,
                        "serial": h_serial or None,
                        "manufacturer": h.get('manufacturer'),
                        "model": h.get('model'),
                        "device_type": h.get('device_type'),
                        "pallet_id": h.get('pallet_id'),
                        "pallet_destination": h.get('pallet_destination'),
                        "pallet_location": h.get('pallet_location'),
                        "details": json.dumps({k: v for k, v in h.items() if k in ('drive_size', 'drive_type', 'drive_count')}) if h else None,
                    }

                    results["timeline"].append(ev)

                    # If this history row includes a pallet assignment, add a dedicated Pallet event
                    try:
                        pid = ev.get('pallet_id')
                        if pid:
                            results["timeline"].append({
                                "timestamp": h.get('timestamp'),
                                "stage": f"Pallet {pid}",
                                "user": h.get('user'),
                                "location": ev.get('pallet_location'),
                                "source": "qa_export.pallet",
                                "pallet_id": pid,
                                "pallet_destination": ev.get('pallet_destination'),
                                "pallet_location": ev.get('pallet_location'),
                            })
                    except Exception:
                        pass

                except Exception:
                    continue
        except Exception:
            pass

        # 7c. Include admin action history tied to erasures rows (undo/fix-initials etc.)
        try:
            import sqlite3 as _sqlite
            sconn = _sqlite.connect(db.DB_PATH)
            scur = sconn.cursor()
            scur.execute("SELECT rowid FROM erasures WHERE system_serial = ? OR disk_serial = ? OR job_id = ?", (stock_id, stock_id, stock_id))
            affected_rowids = [r[0] for r in scur.fetchall() if r and r[0]]
            if affected_rowids:
                placeholders = ','.join(['?'] * len(affected_rowids))
                q = f"SELECT a.created_at, a.action, a.from_initials, a.to_initials, ar.rowid FROM admin_actions a JOIN admin_action_rows ar ON a.id = ar.action_id WHERE ar.rowid IN ({placeholders}) ORDER BY a.created_at ASC"
                scur.execute(q, affected_rowids)
                for created_at, action, from_i, to_i, rowid in scur.fetchall():
                    results.setdefault("found_in", []).append("admin_actions") if "admin_actions" not in results.get("found_in", []) else None
                    results["timeline"].append({
                        "timestamp": created_at,
                        "stage": f"Admin: {action}",
                        "user": from_i or to_i,
                        "location": None,
                        "source": "admin_actions",
                        "details": f"rowid={rowid} from={from_i} to={to_i}",
                    })
            scur.close()
            sconn.close()
        except Exception:
            pass

        # 7d. Include manager confirmations history from confirmed_locations
        try:
            # Prefer the background confirmed_locations read if available
            conf_rows = None
            try:
                if 'conf_future' in locals() and conf_future:
                    single = conf_future.result(timeout=0.05)
                    if single:
                        # we only have the latest in the future; for history fall back
                        conf_rows = [ (single[2], single[0], single[1], None) ]
            except Exception:
                conf_rows = None

            if conf_rows is None:
                import sqlite3 as _sqlite2
                sc = _sqlite2.connect(db.DB_PATH)
                curc = sc.cursor()
                curc.execute("SELECT ts, location, user, note FROM confirmed_locations WHERE stockid = ? ORDER BY ts ASC", (stock_id,))
                conf_rows = curc.fetchall()
                curc.close()
                sc.close()

            for ts, loc, user, note in conf_rows:
                results.setdefault("found_in", []).append("confirmed_locations") if "confirmed_locations" not in results.get("found_in", []) else None
                results["timeline"].append({
                    "timestamp": ts,
                    "stage": "Manager Confirmation",
                    "user": user,
                    "location": loc,
                    "source": "confirmed_locations",
                    "details": note,
                })
        except Exception:
            pass

        # 7e. Hypothesis-derived events intentionally omitted from timeline
        # Reason: hypotheses are represented separately in `results.hypotheses` and
        # including them here caused duplicate timestamps (same occurrence shown
        # twice). We keep hypotheses in the hypotheses list but do not append them
        # as separate timeline events to avoid duplication.
        
        # De-dupe timeline events that are identical across sources/rows
        deduped_timeline = []
        seen_events = set()
        for event in results["timeline"]:
            key = (
                event.get("timestamp"),
                event.get("stage"),
                event.get("user"),
                event.get("location"),
                event.get("source"),
                event.get("details"),
            )
            if key in seen_events:
                continue
            seen_events.add(key)
            deduped_timeline.append(event)

        # Sort timeline most-recent-first (newest at the top)
        deduped_timeline.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
        results["timeline"] = deduped_timeline

        # Debug: report final timeline size and a small sample for inspection
        try:
            logging.info("[device_lookup] timeline events after dedupe/sort: %d for %s", len(deduped_timeline), stock_id)
            for ev in deduped_timeline[:6]:
                logging.info("[device_lookup] sample event: source=%s stage=%s ts=%s loc=%s", ev.get('source'), ev.get('stage'), ev.get('timestamp'), ev.get('location'))
        except Exception:
            pass

        # Backfill missing metadata on timeline events (pallet/destination/manufacturer/model)
        try:
            pallet_info = results.get('pallet_info') or {}
            for ev in results.get('timeline', []):
                try:
                    if not ev.get('pallet_id') and pallet_info.get('pallet_id'):
                        ev['pallet_id'] = pallet_info.get('pallet_id')
                    if not ev.get('pallet_destination') and pallet_info.get('destination'):
                        ev['pallet_destination'] = pallet_info.get('destination')
                    if not ev.get('pallet_location') and pallet_info.get('location'):
                        ev['pallet_location'] = pallet_info.get('location')
                    # Fill manufacturer/model from asset_info when missing
                    asset_info = results.get('asset_info') or {}
                    if not ev.get('manufacturer') and asset_info.get('manufacturer'):
                        ev['manufacturer'] = asset_info.get('manufacturer')
                    if not ev.get('model') and asset_info.get('model'):
                        ev['model'] = asset_info.get('model')
                    # Normalize timestamp strings where possible
                    if ev.get('timestamp'):
                        try:
                            # keep as string but try to ensure ISO-like form
                            _t = ev.get('timestamp')
                            if isinstance(_t, (int, float)):
                                # epoch -> iso
                                from datetime import datetime as _dt
                                ev['timestamp'] = _dt.utcfromtimestamp(float(_t)).isoformat()
                        except Exception:
                            pass
                except Exception:
                    continue
        except Exception:
            pass

        # Add likely-location hypotheses (top N) from DB heuristics
        try:
            hypotheses = qa_export.get_device_location_hypotheses(stock_id, top_n=3)
            results["hypotheses"] = hypotheses or []
        except Exception as e:
            # Hypothesis generation is optional; log exception for debugging and return empty list
            logging.exception("Hypothesis generation failed for %s: %s", stock_id, e)
            results["hypotheses"] = []

        # If we know the last user (from QA/audit) and there's no pallet assignment,
        # surface a QA-confirmed hypothesis indicating the device was QA'd by that
        # user and is likely awaiting Sorting. This makes it easy to search for
        # devices handled by a technician and not yet assigned to a pallet.
        try:
            last_user = results.get('last_known_user')
            pallet_info = results.get('pallet_info') or {}
            asset_info = results.get('asset_info') or {}
            # Always surface a QA-confirmed hypothesis when we know the last user
            # (from audit_master), even if a pallet assignment exists. This keeps
            # the QA action visible in the UI between Sorting and later-stage
            # events like Erasure.
            if last_user:
                # Find last seen timestamp for this user in the timeline
                last_seen = None
                for ev in reversed(results.get('timeline', [])):
                    try:
                        if ev.get('user') and str(ev.get('user')).lower() == str(last_user).lower():
                            last_seen = ev.get('timestamp') or last_seen
                            break
                    except Exception:
                        continue

                qa_label = f"QA Data Bearing (by {last_user})"
                qa_evidence = [{'source': 'audit_master', 'username': last_user}]
                # Determine latest timeline timestamp so we can mark whether
                # this QA hypothesis corresponds to the most-recent event.
                latest_ts = None
                try:
                    for tev in results.get('timeline', []) or []:
                        t = tev.get('timestamp')
                        if not t:
                            continue
                        try:
                            if isinstance(t, str):
                                from datetime import datetime as _dt
                                tdt = _dt.fromisoformat(t.replace('Z', '+00:00'))
                            else:
                                tdt = t
                        except Exception:
                            continue
                        if not latest_ts or (tdt and tdt > latest_ts):
                            latest_ts = tdt
                except Exception:
                    latest_ts = None
                # prepend so it shows prominently; score 85 to be competitive but still
                # allow true recency to reorder if other signals are fresher.
                # mark `is_most_recent` True when the user's last_seen equals the
                # most recent timeline timestamp (within 60 seconds) so the UI
                # can highlight this as the freshest signal.
                is_most_recent_flag = False
                try:
                    if last_seen and latest_ts:
                        try:
                            from datetime import datetime as _dt
                            if isinstance(last_seen, str):
                                last_dt = _dt.fromisoformat(last_seen.replace('Z', '+00:00'))
                            else:
                                last_dt = last_seen
                            if last_dt and abs((latest_ts - last_dt).total_seconds()) <= 60:
                                is_most_recent_flag = True
                        except Exception:
                            is_most_recent_flag = False
                except Exception:
                    is_most_recent_flag = False

                qa_hyp = {
                    'location': qa_label,
                    # Compute QA score relative to existing top hypothesis so
                    # QA does not accidentally outrank a more-recent Sorting
                    # candidate. If a top hypothesis exists and its score is
                    # lower than the configured QA_CONFIRMED_SCORE, give QA a
                    # slightly lower score so it appears second.
                    'score': None,
                    'raw_score': None,
                    'evidence': qa_evidence,
                    'last_seen': last_seen,
                    'type': 'stage',
                    'explanation': f"Device was recorded in audit_master by {last_user} and likely passed QA.",
                    'ai_explanation': f"Recorded as QA Data Bearing by {last_user}; likely awaiting Sorting.",
                    'rank': 1,
                    'is_qa_confirmed': True,
                    'awaiting_sorting': True,
                    'is_most_recent': is_most_recent_flag,
                }
                # Ensure the QA-confirmed hypothesis is present and prominent.
                # Even when a pallet assignment exists, operators want to see
                # the QA confirmation alongside pallet/inferred candidates.
                results.setdefault('hypotheses', [])
                # avoid duplicate QA hypotheses
                found_qa = False
                try:
                    for h in results.get('hypotheses', []):
                        try:
                            if h.get('is_qa_confirmed') or (isinstance(h.get('location'), str) and h.get('location').lower().startswith('qa data bearing')):
                                found_qa = True
                                break
                        except Exception:
                            continue
                except Exception:
                    found_qa = False
                if not found_qa:
                    # Determine an appropriate numeric score for the QA
                    # hypothesis so ordering is driven by numeric sort when
                    # possible. Prefer to keep QA slightly below the current
                    # top hypothesis if that hypothesis exists.
                    try:
                        top_score = None
                        if results.get('hypotheses'):
                            top_score = max((int(h.get('score') or 0) for h in results.get('hypotheses')))
                    except Exception:
                        top_score = None
                    try:
                        if top_score is not None and top_score < int(QA_CONFIRMED_SCORE):
                            qa_score = max(0, int(top_score) - 1)
                        else:
                            qa_score = int(QA_CONFIRMED_SCORE)
                    except Exception:
                        qa_score = int(QA_CONFIRMED_SCORE)
                    qa_hyp['score'] = qa_score
                    qa_hyp['raw_score'] = float(qa_score)

                    # Insert QA just after the top hypothesis when possible.
                    if results.get('hypotheses') and len(results.get('hypotheses')) >= 1:
                        try:
                            results['hypotheses'].insert(1, qa_hyp)
                        except Exception:
                            results['hypotheses'].insert(0, qa_hyp)
                    else:
                        results['hypotheses'].insert(0, qa_hyp)
        except Exception:
            pass

        # Build a compact smart advisory from the top hypothesis (if available)
        try:
            smart_advisory = None
            # --- Enrich hypotheses with any erasure provenance found in the timeline ---
            try:
                if results.get('hypotheses') and results.get('timeline'):
                    # Collect erasure provenance objects from timeline
                    erasures_found = []
                    for ev in results.get('timeline', []):
                        for s in ev.get('sources', []) or []:
                            try:
                                if s and (s.get('type') == 'erasure' or (s.get('source') and 'local_erasures' in str(s.get('source')))):
                                    erasures_found.append(s)
                            except Exception:
                                continue

                    # Also collect Blancco timeline events (MariaDB copies) as provenance
                    blancco_found = []
                    for ev in results.get('timeline', []):
                        try:
                            src = (ev.get('source') or '')
                            if ev.get('is_blancco_record') or ('blancco' in str(src).lower()):
                                blancco_found.append({
                                    'type': 'blancco',
                                    'source': src,
                                    'ts': ev.get('timestamp'),
                                    'initials': ev.get('user'),
                                    'blancco_status': ev.get('blancco_status') or ev.get('status'),
                                    'manufacturer': ev.get('manufacturer'),
                                    'model': ev.get('model'),
                                    'serial': ev.get('serial') or ev.get('stockid'),
                                })
                        except Exception:
                            continue

                    if erasures_found or blancco_found:
                        for h in results.get('hypotheses', []):
                            try:
                                h.setdefault('evidence', h.get('evidence') or [])
                                # attach shallow copies (avoid mutating DB rows)
                                for e in erasures_found:
                                    # Build a concise evidence object for UI
                                    ev_obj = {
                                        'source': 'local_erasures',
                                        'type': 'erasure',
                                        'initials': e.get('initials'),
                                        'job_id': e.get('job_id'),
                                        'ts': e.get('ts'),
                                        'manufacturer': e.get('manufacturer'),
                                        'model': e.get('model'),
                                        'disk_serial': e.get('disk_serial'),
                                        'drive_size': e.get('drive_size')
                                    }
                                    # Avoid duplicate evidence entries
                                    if not any((ev.get('job_id') and ev.get('job_id') == ev_obj['job_id']) for ev in h['evidence'] if isinstance(ev, dict)):
                                        h['evidence'].append(ev_obj)
                                # Add Blancco evidence too
                                for b in blancco_found:
                                    bobj = {
                                        'source': 'ITAD_asset_info_blancco',
                                        'type': 'blancco',
                                        'initials': b.get('initials'),
                                        'ts': b.get('ts'),
                                        'status': b.get('blancco_status'),
                                        'manufacturer': b.get('manufacturer'),
                                        'model': b.get('model'),
                                        'serial': b.get('serial')
                                    }
                                    if not any((ev.get('type') == 'blancco' and ev.get('serial') == bobj.get('serial')) for ev in h['evidence'] if isinstance(ev, dict)):
                                        h['evidence'].append(bobj)
                                # Mark hypothesis as having Blancco evidence (UI can show badge)
                                if blancco_found:
                                    h['is_blancco'] = True
                                    if 'blancco' not in h:
                                        h['blancco'] = blancco_found[0]
                            except Exception:
                                continue
                    # If we found erasure provenance, also add an explicit
                    # 'Data Erasure' hypothesis (lower score than QA) so the UI
                    # lists both QA confirmation and Data Erasure as top items.
                    try:
                        if erasures_found:
                            # prefer the most-recent erasure provenance
                            e = erasures_found[-1]
                            er_initials = e.get('initials') or 'Unknown'
                            er_ts = e.get('ts')
                            er_evidence = [{
                                'source': 'local_erasures',
                                'type': 'erasure',
                                'initials': e.get('initials'),
                                'job_id': e.get('job_id'),
                                'ts': e.get('ts'),
                                'manufacturer': e.get('manufacturer'),
                                'model': e.get('model'),
                                'disk_serial': e.get('disk_serial'),
                                'drive_size': e.get('drive_size')
                            }]
                            er_hyp = {
                                'location': f"Data Erasure (by {er_initials})",
                                'score': max(0, int(QA_CONFIRMED_SCORE) - 10),
                                'raw_score': float(max(0, int(QA_CONFIRMED_SCORE) - 10)),
                                'evidence': er_evidence,
                                'last_seen': er_ts,
                                'type': 'stage',
                                'explanation': f"Device erasure recorded by {er_initials}.",
                                'ai_explanation': f"Erasure recorded by {er_initials} on {er_ts}.",
                                'rank': 2,
                                'is_blancco': True,
                            }
                            # Ensure hypotheses list exists and append if not duplicate
                            results.setdefault('hypotheses', [])
                            # avoid adding duplicate erasure hyp
                            if not any(h.get('location', '').lower().startswith('data erasure') for h in results['hypotheses']):
                                results['hypotheses'].append(er_hyp)
                    except Exception:
                        pass
            except Exception:
                pass
            if results.get("hypotheses"):
                top = results["hypotheses"][0]
                # confidence: use normalized score if present, else raw_score
                try:
                    conf_pct = int(top.get('score', top.get('raw_score', 0)))
                except Exception:
                    conf_pct = int(top.get('raw_score', 0) or 0)

                # last activity
                last_act = top.get('last_seen')
                last_dt = None
                try:
                    if last_act:
                        # last_seen might already be iso string or datetime
                        if isinstance(last_act, str):
                            from datetime import datetime as _dt
                            try:
                                last_dt = _dt.fromisoformat(last_act.replace('Z', '+00:00'))
                            except Exception:
                                last_dt = None
                        else:
                            last_dt = last_act
                except Exception:
                    last_dt = None

                hours_since = None
                from datetime import datetime as _dt
                try:
                    if last_dt:
                        hours_since = round((datetime.now(last_dt.tzinfo) - last_dt).total_seconds() / 3600.0, 1)
                except Exception:
                    hours_since = None

                # simple predicted next step based on candidate type or keywords
                predicted_next = None
                locname = (top.get('location') or '').lower()
                if 'erasure' in locname or 'blancco' in locname:
                    predicted_next = 'QA Review'
                elif 'pallet' in locname:
                    predicted_next = 'Pallet Move / Shipping'
                elif 'roller' in locname or 'ia' in locname:
                    predicted_next = 'Erasure'
                else:
                    predicted_next = results.get('insights', {}).get('predicted_next_step') or None

                # reason: use first sentence of ai_explanation if available
                reason = None
                try:
                    aiex = top.get('ai_explanation') or top.get('explanation') or ''
                    if aiex:
                        reason = str(aiex).split('.')[:1][0].strip()
                except Exception:
                    reason = None

                recommended = None
                # derive recommended action from ai_explanation trailing phrases if possible
                try:
                    if aiex and 'recommended action' in aiex.lower():
                        rec = aiex.lower().split('recommended action:')[-1].strip()
                        recommended = rec[0:200].strip()
                except Exception:
                    recommended = None

                smart_advisory = {
                    'predicted_next': predicted_next,
                    'confidence_pct': conf_pct,
                    'last_activity': last_act if isinstance(last_act, str) else (last_dt.isoformat() if last_dt else None),
                    'time_since_hours': hours_since,
                    'reason': reason,
                    'recommended_action': recommended,
                    'source_candidate': top.get('location'),
                }
                # also attach advisory to the hypothesis object for UI convenience
                results['hypotheses'][0]['smart_advisory'] = smart_advisory
            results['smart_advisory'] = smart_advisory
            # Provide a short timeline advisory note (human-friendly) derived from top hypothesis
            try:
                if results.get('hypotheses') and results['hypotheses'][0].get('ai_explanation'):
                    note = results['hypotheses'][0].get('ai_explanation')
                    # keep it short (first two sentences)
                    sn = '.'.join(str(note).split('.')[:2]).strip()
                    results['timeline_advisory_note'] = sn
                else:
                    results['timeline_advisory_note'] = None
            except Exception:
                results['timeline_advisory_note'] = None
        except Exception:
            results['smart_advisory'] = None

        # Build smart insights (simple prediction + risk signals)
        from datetime import datetime

        def parse_timestamp(value):
            if not value:
                return None
            if isinstance(value, datetime):
                return value
            raw = str(value).strip()
            if not raw:
                return None
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                pass
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    return datetime.strptime(raw, fmt)
                except Exception:
                    continue
            return None

        last_activity_dt = None
        last_activity_label = None
        for event in reversed(results["timeline"]):
            ts = parse_timestamp(event.get("timestamp"))
            if ts:
                last_activity_dt = ts
                last_activity_label = event.get("timestamp")
                break
        if not last_activity_dt and results.get("asset_info"):
            asset_last = parse_timestamp(results["asset_info"].get("last_update"))
            if asset_last:
                last_activity_dt = asset_last
                last_activity_label = results["asset_info"].get("last_update")

        hours_since = None
        if last_activity_dt:
            try:
                delta = datetime.now(last_activity_dt.tzinfo) - last_activity_dt
                hours_since = round(delta.total_seconds() / 3600, 1)
            except Exception:
                hours_since = None

        asset_info = results.get("asset_info") or {}
        stage_next = asset_info.get("stage_next")
        stage_current = asset_info.get("stage_current")
        pallet_id = (results.get("pallet_info") or {}).get("pallet_id")
        has_qa = any((evt.get("stage") or "").lower().startswith("qa") for evt in results["timeline"])
        has_erasure = any("erasure" in (evt.get("stage") or "").lower() for evt in results["timeline"])
        last_stage = None
        if results["timeline"]:
            last_stage = results["timeline"][-1].get("stage")

        predicted_next = None
        confidence = 0.35
        if stage_next:
            predicted_next = stage_next
            confidence = 0.78
        elif last_stage:
            stage_lower = last_stage.lower()
            if "erasure" in stage_lower:
                predicted_next = "QA Review"
                confidence = 0.6
            elif stage_lower.startswith("qa"):
                predicted_next = "Pallet Assignment" if not pallet_id else "Pallet Move / Shipping"
                confidence = 0.65
            elif "sorting" in stage_lower:
                predicted_next = "QA Review"
                confidence = 0.55
        elif stage_current:
            predicted_next = "Continue workflow"
            confidence = 0.4

        signals = []
        recommendations = []
        risk_score = 10
        risk_level = "low"

        if hours_since is not None and hours_since >= 48:
            signals.append(f"No activity for {hours_since} hours")
            recommendations.append("Investigate current location and assign owner")
            risk_score += 35
        if has_qa and not pallet_id:
            signals.append("QA complete but no pallet assignment")
            recommendations.append("Assign pallet or confirm destination")
            risk_score += 30
        if asset_info.get("quarantine"):
            signals.append("Device is in quarantine")
            if asset_info.get("quarantine_reason"):
                signals.append(f"Quarantine reason: {asset_info.get('quarantine_reason')}")
            recommendations.append("Resolve quarantine before next stage")
            risk_score += 40

        roller_location = (asset_info.get("roller_location") or "").strip()
        if roller_location and "roller" in roller_location.lower():
            de_complete = str(asset_info.get("de_complete") or "").lower() in ("yes", "true", "1")
            if de_complete or has_erasure:
                signals.append(f"Roller status: {roller_location} (erased, waiting QA)")
                recommendations.append("Prioritize QA scan to clear roller queue")
                risk_score += 15
            else:
                signals.append(f"Roller status: {roller_location} (waiting erasure)")
                recommendations.append("Route to erasure queue or verify intake")
                risk_score += 20

        if risk_score >= 70:
            risk_level = "high"
        elif risk_score >= 35:
            risk_level = "medium"

        results["insights"] = {
            "predicted_next_step": predicted_next,
            "confidence": confidence,
            "risk_score": min(risk_score, 100),
            "risk_level": risk_level,
            "last_activity": last_activity_label,
            "hours_since_activity": hours_since,
            "signals": signals,
            "recommendations": recommendations,
        }

        # Destination-specific bottleneck snapshot removed from device lookup

        # Summary
        # Merge near-duplicate timeline events (events within a short window)
        try:
            from datetime import datetime as _dt

            MERGE_WINDOW = int(os.getenv('MERGE_TIMELINE_WINDOW_SECONDS', '60'))

            def _parse_ts(ts):
                if not ts:
                    return None
                try:
                    if isinstance(ts, str):
                        # Handle ISO and common SQL formats
                        try:
                            return _dt.fromisoformat(ts.replace('Z', '+00:00'))
                        except Exception:
                            pass
                        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                            try:
                                return _dt.strptime(ts, fmt)
                            except Exception:
                                continue
                    elif hasattr(ts, 'timetuple'):
                        return ts
                except Exception:
                    return None
                return None

            # Build a list of (dt, event) and sort by dt desc, keep None timestamps at end
            evs = results.get('timeline', []) or []
            evs_with_dt = []
            evs_none = []
            for e in evs:
                try:
                    d = _parse_ts(e.get('timestamp'))
                except Exception:
                    d = None
                if d:
                    evs_with_dt.append((d, e))
                else:
                    evs_none.append((None, e))

            evs_with_dt.sort(key=lambda x: x[0], reverse=True)

            merged = []
            i = 0
            while i < len(evs_with_dt):
                base_dt, base_ev = evs_with_dt[i]
                group = [(base_dt, base_ev)]
                j = i + 1
                while j < len(evs_with_dt):
                    nxt_dt, nxt_ev = evs_with_dt[j]
                    try:
                        diff = abs((base_dt - nxt_dt).total_seconds())
                    except Exception:
                        diff = None
                    if diff is not None and diff <= MERGE_WINDOW:
                        group.append((nxt_dt, nxt_ev))
                        # extend base_dt to the most recent in group for subsequent comparisons
                        if nxt_dt and nxt_dt > base_dt:
                            base_dt = nxt_dt
                        j += 1
                    else:
                        break
                # Produce merged event: prefer the event with the latest timestamp as primary
                primary = max(group, key=lambda x: x[0] or _dt.min)[1]
                merged_event = dict(primary)
                # attach provenance of merged events
                merged_event['merged'] = True if len(group) > 1 else False
                merged_event['merged_from'] = []
                for d, ev in group:
                    merged_event['merged_from'].append({
                        'timestamp': ev.get('timestamp'),
                        'stage': ev.get('stage'),
                        'source': ev.get('source'),
                        'user': ev.get('user')
                    })
                merged.append(merged_event)
                i = j

            # Append events with no timestamps after the merged ones (preserve order)
            for _, e in evs_none:
                merged.append(e)

            results['timeline'] = merged
        except Exception:
            # If merge fails for any reason, fall back to raw timeline
            pass

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


_SUMMARY_TTL = float(os.getenv("SUMMARY_TTL", "60"))
# Short-lived cache for device summary
_summary_cache = TTLCache(maxsize=int(os.getenv("SUMMARY_MAXSIZE", "512")), ttl=_SUMMARY_TTL)

@app.get("/api/device-lookup/{stock_id}/summary")
async def device_lookup_summary(stock_id: str, request: Request):
    """Return a lightweight top suggestion for a device. Cached for short TTL."""
    require_manager_or_admin(request)
    cached = _summary_cache.get(stock_id)
    if cached is not None:
        return {"stock_id": stock_id, "summary": cached, "cached": True}
    try:
        import device_lookup as dl
        # request a single top hypothesis; device_lookup's SIMPLE_MODE will keep this light
        hyps = dl.get_device_location_hypotheses(stock_id, top_n=1)
        top = hyps[0] if hyps else None
        _summary_cache.set(stock_id, top)
        return {"stock_id": stock_id, "summary": top, "cached": False}
    except Exception as e:
        return {"stock_id": stock_id, "summary": None, "error": str(e)}


@app.post("/api/device-lookup/{stock_id}/confirm")
async def confirm_device_location(stock_id: str, request: Request):
    """Record a user-confirmed device location to improve future hypotheses (manager/admin only)."""
    require_manager_or_admin(request)
    payload = await request.json()
    location = payload.get('location')
    note = payload.get('note')
    role = get_role_from_request(request) or 'manager'
    if not location:
        raise HTTPException(status_code=400, detail='location required')

    import sqlite3
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS confirmed_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stockid TEXT,
                location TEXT,
                user TEXT,
                note TEXT,
                ts TEXT
            )
        """)
        ts = __import__('datetime').datetime.utcnow().isoformat()
        cur.execute("INSERT INTO confirmed_locations (stockid, location, user, note, ts) VALUES (?, ?, ?, ?, ?)",
                    (stock_id, location, role, note, ts))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Confirm location error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return { 'ok': True, 'stockid': stock_id, 'location': location, 'ts': ts }


def _build_bottleneck_snapshot(destination: str = None, limit_engineers: int = 5, days_threshold: int = 7) -> Dict[str, object]:
    """Summarize CURRENT bottleneck patterns - shows warehouse state for THIS WEEK.
    
    Shows:
    - Current unpalleted devices active this week
    - Current roller queue status (devices awaiting erasure/QA/pallet)
    - Roller station breakdown by workflow stage
    - Engineers with unpalleted devices assigned to them
    """
    import qa_export

    def normalize_destination(value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    destination_norm = normalize_destination(destination).lower() if destination else None
    try:
        summary = qa_export.get_unpalleted_summary(
            destination=destination_norm,
            days_threshold=7  # This is now ignored, uses "this week" filtering
        )
    except Exception as ex:
        print(f"[Bottleneck] get_unpalleted_summary failed: {ex}")
        import traceback as _tb
        _tb.print_exc()
        summary = {"total_unpalleted": 0, "destination_counts": {}, "engineer_counts": {}}

    total_unpalleted = summary.get("total_unpalleted", 0)
    awaiting_erasure = summary.get("awaiting_erasure", 0)
    awaiting_qa = summary.get("awaiting_qa", 0)
    awaiting_pallet = summary.get("awaiting_pallet", 0)
    destination_counts = summary.get("destination_counts", {})
    engineer_counts = summary.get("engineer_counts", {})

    top_destinations = sorted(
        [{"destination": k, "count": v} for k, v in destination_counts.items()],
        key=lambda x: x["count"],
        reverse=True
    )

    top_engineers = sorted(
        [{"engineer": k, "missing_pallet_count": v} for k, v in engineer_counts.items()],
        key=lambda x: x["missing_pallet_count"],
        reverse=True
    )

    # Only flag REAL engineers (not unassigned/system entries) with high share
    flagged_engineers = []
    for item in top_engineers[:limit_engineers]:
        share = (item["missing_pallet_count"] / total_unpalleted) if total_unpalleted else 0
        item["share"] = round(share, 2)
        
        engineer_name = item["engineer"].lower()
        # Skip flagging unassigned, NO USER, system entries
        is_system_entry = any(x in engineer_name for x in ["unassigned", "no user", "system", "unknown"])
        
        if not is_system_entry and item["missing_pallet_count"] >= 10 and share >= 0.25:
            flagged_engineers.append({
                "engineer": item["engineer"],
                "missing_pallet_count": item["missing_pallet_count"],
                "share": item["share"],
                "reason": f"High volume of unpalleted devices ({item['missing_pallet_count']} devices, {int(share*100)}% of total)",
            })

    # Get accurate roller queue status (shows CURRENT state of all rollers this week)
    try:
        roller_status = qa_export.get_roller_queue_status(days_threshold=7)  # This is now ignored, uses "this week" filtering
        # Ensure totals/rollers structure exists
        if not isinstance(roller_status, dict):
            roller_status = {"totals": {}, "rollers": []}
        roller_totals = roller_status.get("totals", {})
        roller_rollers = roller_status.get("rollers", [])
    except Exception as ex:
        print(f"[Bottleneck] get_roller_queue_status failed: {ex}")
        import traceback as _tb
        _tb.print_exc()
        roller_totals = {"total": 0, "awaiting_erasure": 0, "awaiting_qa": 0, "awaiting_pallet": 0}
        roller_rollers = []
    
    return {
        "timestamp": datetime.now().isoformat(),
        "filter_period": "this_week",  # Changed from lookback_days
        "total_unpalleted": total_unpalleted,
        "awaiting_erasure": awaiting_erasure,
        "awaiting_qa": awaiting_qa,
        "awaiting_pallet": awaiting_pallet,
        "destination_counts": top_destinations,
        "engineer_missing_pallets": top_engineers[:limit_engineers],
        "flagged_engineers": flagged_engineers,
        "roller_queue": roller_totals,
        "roller_breakdown": roller_rollers,
    }


@app.get("/api/bottlenecks")
async def get_bottleneck_snapshot(request: Request, days: int = 7, debug: bool = False):
    """Return CURRENT bottleneck snapshot - warehouse state NOW (manager only)."""
    require_manager_or_admin(request)
    # Lightweight bottleneck implementation using recent-window counts.
    # Uses MariaDB via services.db_utils and local SQLite erasure feed for early erasure signals.
    try:
        from services import db_utils
        import sqlite3
        import os

        # Simple cache to avoid repeated heavy calls
        global _bottleneck_cache
        try:
            _bottleneck_cache
        except NameError:
            _bottleneck_cache = TTLCache(maxsize=128, ttl=int(os.getenv('BOTTLENECK_CACHE_TTL', '60')))

        now = datetime.utcnow()
        days = max(1, min(int(days or 7), 90))
        start = (now - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        end = now.strftime('%Y-%m-%d %H:%M:%S')
        cache_key = f"bottleneck|{start}|{end}"
        cached = _bottleneck_cache.get(cache_key)
        if cached is not None:
            return JSONResponse(status_code=200, content=cached)

        # 1) Goods In (Stockbypallet) - best-effort
        q_goods = "SELECT COUNT(DISTINCT pallet_id) FROM Stockbypallet WHERE received_date >= %s AND received_date < %s"
        goods_res = db_utils.safe_read(q_goods, (start, end))
        goods_in = int(goods_res[0][0]) if goods_res and isinstance(goods_res, list) and goods_res[0] and goods_res[0][0] is not None else 0

        # 2) Awaiting Erasure (stage_current='IA' and no blancco)
        q_awaiting = (
            "SELECT COUNT(*) FROM ITAD_asset_info a "
            "WHERE (a.warehouse IS NULL OR a.warehouse = 'Berry Hill') "
            "AND a.stage_current = 'IA' "
            "AND NOT EXISTS (SELECT 1 FROM ITAD_asset_info_blancco b WHERE b.stockid = a.stockid) "
            "AND a.sla_complete_date >= %s AND a.sla_complete_date < %s"
        )
        awaiting_res = db_utils.safe_read(q_awaiting, (start, end))
        awaiting_erasure = int(awaiting_res[0][0]) if awaiting_res and awaiting_res[0] and awaiting_res[0][0] is not None else 0

        # 3) Awaiting QA: infer from local SQLite erasure feed vs MariaDB
        stats_db = os.getenv('STATS_DB_PATH', 'warehouse_stats.db')
        erased_awaiting_qa = 0
        diagnostics = {"sqlite_found": False, "sqlite_rows": 0, "batches": 0, "errors": []}
        try:
            if os.path.exists(stats_db):
                diagnostics["sqlite_found"] = True
                conn = sqlite3.connect(stats_db)
                cur = conn.cursor()
                # Pull distinct stockids with their latest erasure ts in the window
                cur.execute("SELECT stockid, MAX(ts) as last_ts FROM local_erasures WHERE ts >= ? AND ts < ? GROUP BY stockid", (start, end))
                rows = cur.fetchall()
                cur.close()
                conn.close()
                # If local_erasures is empty and AUTO_BACKFILL enabled, try to seed from erasures table
                if not rows:
                    try:
                        from os import getenv
                        if str(getenv('AUTO_BACKFILL', '')).lower() in ('1', 'true', 'yes'):
                            # backfill from erasures (recent events)
                            from database import DB_PATH, add_local_erasure
                            conn2 = sqlite3.connect(DB_PATH)
                            cur2 = conn2.cursor()
                            days_back = int(getenv('AUTO_BACKFILL_DAYS', '7'))
                            limit = int(getenv('AUTO_BACKFILL_LIMIT', '2000'))
                            from datetime import timedelta as _td
                            start_back = (datetime.utcnow() - _td(days=days_back)).isoformat()
                            q_back = ("SELECT id, job_id, system_serial, ts, device_type, initials FROM erasures "
                                      "WHERE event = 'success' AND ts >= ? ORDER BY ts ASC LIMIT ?")
                            cur2.execute(q_back, (start_back, limit))
                            back_rows = cur2.fetchall()
                            inserted = 0
                            # Initialize auto-backfill progress so UI can poll
                            try:
                                BACKFILL_PROGRESS['running'] = True
                                BACKFILL_PROGRESS['total'] = len(back_rows)
                                BACKFILL_PROGRESS['processed'] = 0
                                BACKFILL_PROGRESS['percent'] = 0
                                BACKFILL_PROGRESS['last_updated'] = datetime.utcnow().isoformat()
                                BACKFILL_PROGRESS['errors'] = []
                            except Exception:
                                pass
                            for r in back_rows:
                                eid, job_id, system_serial, ts_val, device_type, initials = r
                                jid = job_id if job_id else f"erasures-backfill-{eid}"
                                try:
                                    add_local_erasure(stockid=None, system_serial=system_serial, job_id=jid, ts=ts_val, warehouse=None, source='erasures-backfill', payload={'device_type': device_type, 'initials': initials})
                                    inserted += 1
                                except Exception as _e:
                                    diagnostics.setdefault('errors', []).append(str(_e))
                                    try:
                                        BACKFILL_PROGRESS['errors'].append(str(_e))
                                    except Exception:
                                        pass
                                finally:
                                    try:
                                        BACKFILL_PROGRESS['processed'] = BACKFILL_PROGRESS.get('processed', 0) + 1
                                        BACKFILL_PROGRESS['percent'] = int((BACKFILL_PROGRESS.get('processed', 0) / (BACKFILL_PROGRESS.get('total') or 1)) * 100)
                                        BACKFILL_PROGRESS['last_updated'] = datetime.utcnow().isoformat()
                                    except Exception:
                                        pass
                            cur2.close()
                            conn2.close()
                            # re-open the local_erasures query to pick up inserted rows
                            if inserted > 0:
                                conn = sqlite3.connect(stats_db)
                                cur = conn.cursor()
                                cur.execute("SELECT stockid, MAX(ts) as last_ts FROM local_erasures WHERE ts >= ? AND ts < ? GROUP BY stockid", (start, end))
                                rows = cur.fetchall()
                                cur.close()
                                conn.close()
                                diagnostics['auto_backfilled'] = inserted
                            # Mark auto-backfill finished
                            try:
                                BACKFILL_PROGRESS['running'] = False
                                BACKFILL_PROGRESS['last_updated'] = datetime.utcnow().isoformat()
                            except Exception:
                                pass
                    except Exception as _e:
                        diagnostics.setdefault('errors', []).append(str(_e))

                if rows:
                    diagnostics["sqlite_rows"] = len(rows)
                    # Build map key -> last erasure ts where key is COALESCE(stockid, system_serial)
                    stock_ts = {}
                    for r in rows:
                        # r may be (stockid, last_ts) or (stockid, last_ts, system_serial) depending on query
                        s = r[0]
                        sys = None
                        try:
                            # if the row has a second column that's the ts, keep it as ts
                            ts_val = r[1]
                            # attempt to pick system_serial if stockid is falsy
                            if len(r) > 2:
                                sys = r[2]
                        except Exception:
                            continue
                        key = None
                        if s is not None and str(s).strip() != '':
                            key = str(s)
                        elif sys is not None and str(sys).strip() != '':
                            key = str(sys)
                        if key:
                            stock_ts[key] = ts_val
                    stockids = list(stock_ts.keys())
                    batch_size = 200
                    awaiting = 0

                    # Helper to parse timestamps robustly
                    from datetime import datetime as _dt
                    def _parse_ts(v):
                        if not v:
                            return None
                        if isinstance(v, _dt):
                            return v
                        s = str(v).strip()
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                            try:
                                return _dt.strptime(s, fmt)
                            except Exception:
                                continue
                        try:
                            return _dt.fromisoformat(s.replace('Z', '+00:00'))
                        except Exception:
                            return None

                    for i in range(0, len(stockids), batch_size):
                        batch = stockids[i:i+batch_size]
                        diagnostics["batches"] += 1
                        placeholders = ",".join(["%s"] * len(batch))

                        # 1) Check ITAD_asset_info for matches by stockid OR system_serial and get last_update
                        q_asset = f"SELECT stockid, last_update, system_serial FROM ITAD_asset_info WHERE stockid IN ({placeholders}) OR system_serial IN ({placeholders})"
                        asset_rows = db_utils.safe_read(q_asset, tuple(batch) + tuple(batch)) or []
                        # asset_map holds last_update keyed by canonical stockid
                        asset_map = {}
                        # key_to_stockid maps the incoming key (stockid or system_serial) -> canonical stockid
                        key_to_stockid = {}
                        for ar in asset_rows:
                            try:
                                a_stockid = str(ar[0]) if ar[0] is not None else None
                                a_last = ar[1]
                                a_sys = str(ar[2]) if len(ar) > 2 and ar[2] is not None else None
                            except Exception:
                                continue
                            if a_stockid:
                                asset_map[a_stockid] = a_last
                                # map by stockid
                                if a_stockid in batch:
                                    key_to_stockid[a_stockid] = a_stockid
                            if a_sys:
                                # map system_serial back to canonical stockid when available
                                key_to_stockid[a_sys] = a_stockid or a_sys

                        # 2) Check for any QA/audit rows after erasure ts (ITAD_QA_App + audit_master)
                        # Use UNION ALL to combine sources and get the max added_date per stockid
                        q_qa = (
                            f"SELECT stockid, MAX(added_date) as last_qa FROM ("
                            f"SELECT stockid, added_date FROM ITAD_QA_App WHERE stockid IN ({placeholders}) UNION ALL "
                            f"SELECT stockid, added_date FROM audit_master WHERE stockid IN ({placeholders})"
                            f") x GROUP BY stockid"
                        )
                        # For QA lookup, prefer canonical stockids mapped from the asset query
                        canonical_ids = list({key_to_stockid[k] for k in batch if k in key_to_stockid and key_to_stockid[k]})
                        qa_map = {}
                        if canonical_ids:
                            q_place = ",".join(["%s"] * len(canonical_ids))
                            q_qa_specific = (
                                f"SELECT stockid, MAX(added_date) as last_qa FROM ("
                                f"SELECT stockid, added_date FROM ITAD_QA_App WHERE stockid IN ({q_place}) UNION ALL "
                                f"SELECT stockid, added_date FROM audit_master WHERE stockid IN ({q_place})"
                                f") x GROUP BY stockid"
                            )
                            qa_params = tuple(canonical_ids) + tuple(canonical_ids)
                            qa_rows = db_utils.safe_read(q_qa_specific, qa_params) or []
                            qa_map = {str(r[0]): r[1] for r in qa_rows if r and r[0]}
                        else:
                            qa_rows = []

                        # Evaluate each stockid in the batch
                        for sid in batch:
                            er_ts_raw = stock_ts.get(sid)
                            er_ts_dt = _parse_ts(er_ts_raw)

                            # Resolve asset mapping: try to find a canonical stockid for this key
                            a_last_raw = None
                            q_last_raw = None
                            canonical = key_to_stockid.get(sid)
                            if canonical:
                                a_last_raw = asset_map.get(canonical)
                                q_last_raw = qa_map.get(canonical)
                            else:
                                # No matching asset found by stockid/system_serial -> treat as awaiting
                                awaiting += 1
                                continue

                            a_last_dt = _parse_ts(a_last_raw)
                            q_last_dt = _parse_ts(q_last_raw)

                            # If no QA/audit seen after the erasure ts -> awaiting QA
                            if not q_last_dt:
                                awaiting += 1
                                continue

                            if er_ts_dt and q_last_dt and q_last_dt < er_ts_dt:
                                # QA happened before the latest erasure -> awaiting again
                                awaiting += 1

                    erased_awaiting_qa = int(awaiting)
                else:
                    erased_awaiting_qa = 0
            else:
                erased_awaiting_qa = 0
        except Exception as _e:
            diagnostics["errors"].append(str(_e))
            print(f"[Bottleneck] sqlite local_erasures read failed: {_e}")

        # 4) QA'd awaiting Sorting (ITAD_QA_App left join Stockbypallet)
        # NOTE: ITAD_QA_App does not include a `warehouse` column in some schemas.
        # Join through ITAD_asset_info to apply the warehouse filter safely.
        q_qa_sort = (
            "SELECT COUNT(DISTINCT q.stockid) FROM ITAD_QA_App q "
            "LEFT JOIN Stockbypallet s ON s.stockid = q.stockid "
            "LEFT JOIN ITAD_asset_info a ON a.stockid = q.stockid "
            "WHERE (a.warehouse IS NULL OR a.warehouse = 'Berry Hill') "
            "AND s.stockid IS NULL "
            "AND q.added_date >= %s AND q.added_date < %s"
        )
        qa_sort_res = db_utils.safe_read(q_qa_sort, (start, end))
        qa_awaiting_sorting = int(qa_sort_res[0][0]) if qa_sort_res and qa_sort_res[0] and qa_sort_res[0][0] is not None else 0

        # 5) Sorted count
        q_sorted = "SELECT COUNT(DISTINCT stockid) FROM Stockbypallet WHERE received_date >= %s AND received_date < %s"
        sorted_res = db_utils.safe_read(q_sorted, (start, end))
        sorted_count = int(sorted_res[0][0]) if sorted_res and sorted_res[0] and sorted_res[0][0] is not None else 0

        # 6) Disposition breakout from ITAD_asset_info
        q_disp = (
            "SELECT "
            "SUM(CASE WHEN a.condition = 'Dest:Refurbishment' THEN 1 ELSE 0 END) AS awaiting_refurb, "
            "SUM(CASE WHEN a.condition = 'Dest:Breakfix' THEN 1 ELSE 0 END) AS awaiting_breakfix "
            "FROM ITAD_asset_info a WHERE (a.warehouse IS NULL OR a.warehouse = 'Berry Hill') "
            "AND a.sla_complete_date >= %s AND a.sla_complete_date < %s"
        )
        disp_res = db_utils.safe_read(q_disp, (start, end))
        awaiting_refurb = int(disp_res[0][0] or 0) if disp_res and disp_res[0] else 0
        awaiting_breakfix = int(disp_res[0][1] or 0) if disp_res and disp_res[0] else 0

        # 7) SLA overdue
        q_sla = (
            "SELECT COUNT(*) FROM ITAD_asset_info a WHERE (a.warehouse IS NULL OR a.warehouse = 'Berry Hill') "
            "AND a.sla_complete_date < NOW() - INTERVAL 5 DAY "
            "AND (a.de_completed_date IS NULL OR a.de_completed_date = '')"
        )
        sla_res = db_utils.safe_read(q_sla)
        sla_overdue = int(sla_res[0][0]) if sla_res and sla_res[0] and sla_res[0][0] is not None else 0

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "filter_period": f"last_{days}_days",
            "goods_in_totes": goods_in,
            "awaiting_erasure": awaiting_erasure,
            "erased_awaiting_qa": erased_awaiting_qa,
            "qa_awaiting_sorting": qa_awaiting_sorting,
            "sorted": sorted_count,
            "dispositions": {"awaiting_refurb": awaiting_refurb, "awaiting_breakfix": awaiting_breakfix},
            "sla_overdue": sla_overdue,
        }

        # Attach diagnostics when requested (admin/manager only)
        try:
            if debug:
                result["diagnostics"] = diagnostics
        except Exception:
            pass

        try:
            _bottleneck_cache.set(cache_key, result)
        except Exception:
            pass

        return JSONResponse(status_code=200, content=result)
    except Exception as e:
        import traceback as _tb
        print("Bottleneck snapshot error:")
        _tb.print_exc()
        return JSONResponse(status_code=500, content={"detail": "Bottleneck snapshot failed (server error). Check server logs."})


@app.get("/api/bottlenecks/from-dashboard")
async def get_bottleneck_from_dashboard(date: str = None, qa_user: str = None):
    """Lightweight bottleneck snapshot built from existing dashboard endpoints (today-only by default).

    Returns simple counts: awaiting_qa and awaiting_sorting plus small QA/erasure samples.
    """
    from datetime import date as _date, datetime as _dt
    import time

    # Use a short-lived TTL cache for identical dashboard queries
    global _bottleneck_dashboard_cache
    try:
        _bottleneck_dashboard_cache
    except NameError:
        _bottleneck_dashboard_cache = TTLCache(maxsize=256, ttl=60)

    CACHE_TTL = 60  # seconds (kept for compatibility)

    target_date = date if date else _date.today().isoformat()
    cache_key = f"{target_date}|{(qa_user or '').lower()}|default"
    print(f"[Bottleneck-From-Dashboard] request date={target_date} qa_user={(qa_user or '')} cache_key={cache_key}")
    cache_entry = _bottleneck_dashboard_cache.get(cache_key)
    if cache_entry is not None:
        print(f"[Bottleneck-From-Dashboard] cache hit for {cache_key}")
        return JSONResponse(status_code=200, content=cache_entry)
    print(f"[Bottleneck-From-Dashboard] cache miss for {cache_key}; calling dashboard endpoints")

    try:

        # Get merged daily stats (includes erased, qaApp, deQa, nonDeQa, qaTotal)
        print("[Bottleneck-From-Dashboard] loading daily stats directly")
        daily_rows = db.get_stats_range(target_date, target_date)
        try:
            _d = _date.fromisoformat(target_date)
            qa_daily = qa_export.get_qa_daily_totals_range(_d, _d)
            qa_by_date = {row.get("date"): row for row in (qa_daily or [])}
            for row in daily_rows:
                qa_row = qa_by_date.get(row.get("date"), {})
                row["qaApp"] = qa_row.get("qaApp", 0)
                row["deQa"] = qa_row.get("deQa", 0)
                row["nonDeQa"] = qa_row.get("nonDeQa", 0)
                row["qaTotal"] = qa_row.get("qaTotal", 0)
        except Exception:
            pass
        daily = daily_rows[0] if daily_rows else {}
        print(f"[Bottleneck-From-Dashboard] daily rows={len(daily_rows)}")

        # Get QA dashboard today to fetch per-engineer counts
        print("[Bottleneck-From-Dashboard] calling QA dashboard helper")
        qa_dash = await compute_qa_dashboard_data("today", _get_cached_response, _set_cached_response)
        if isinstance(qa_dash, dict) and qa_dash.get('technicians'):
            print(f"[Bottleneck-From-Dashboard] qa_dash technicians={len(qa_dash.get('technicians', []))}")

        # Compute combined QA totals
        qa_total = daily.get("qaTotal") or qa_dash.get("summary", {}).get("combinedScans") or 0
        qa_app = daily.get("qaApp") or qa_dash.get("summary", {}).get("totalScans") or 0
        erased = daily.get("erased") or 0

        # Default lightweight calculation (bounded to dashboard totals)
        awaiting_qa = max(0, int(erased) - int(qa_total))
        awaiting_sorting = max(0, int(qa_total) - int(qa_app))

        # Attempt a more precise, device-level awaiting QA count by mapping
        # today's erasures (local SQLite) to stockids (MariaDB) and checking
        # for a QA/audit timestamp >= erasure timestamp. This is read-only
        # and grouped; if it fails we fall back to dashboard totals above.
        try:
            from datetime import date as _date
            precise = qa_export.get_awaiting_qa_counts_for_date(_date.fromisoformat(target_date))
            if precise and isinstance(precise, dict):
                # Use the precise awaiting_qa where available (keeps value bounded by erased)
                awaiting_qa = int(precise.get("awaiting_qa", awaiting_qa))
                # Attach diagnostic fields to the result later
                precise_meta = precise
            else:
                precise_meta = None
        except Exception as _e:
            print(f"[Bottleneck-From-Dashboard] precise awaiting_qa check failed: {_e}")
            precise_meta = None

        # Use dashboard-derived counts only (erased - qa_total) to keep bottleneck
        # bounded by today's data captured on the Erasure/QA dashboards.

        # Find QA counts for requested qa_user (e.g., 'solomon')
        user_count = None
        if qa_user and qa_dash and qa_dash.get("technicians"):
            for tech in qa_dash["technicians"]:
                if qa_user.lower() in str(tech.get("name", "")).lower():
                    user_count = tech.get("combinedScans")
                    break

        # Get erasure events for the day and aggregate by initials
        print("[Bottleneck-From-Dashboard] loading erasure events directly")
        erasures = db.get_erasure_events_range(target_date, target_date, None)
        print(f"[Bottleneck-From-Dashboard] erasures rows={len(erasures)}")
        erasure_by_initials = {}
        for ev in erasures:
            init = ev.get("initials") or ""
            if not init:
                continue
            erasure_by_initials[init] = erasure_by_initials.get(init, 0) + 1

        # Find a sample pallet-scan by Owen in device history (stage == 'Sorting')
        print("[Bottleneck-From-Dashboard] loading device history directly")
        _d = _date.fromisoformat(target_date)
        hist_rows = qa_export.get_device_history_range(_d, _d)
        print(f"[Bottleneck-From-Dashboard] device_history rows={len(hist_rows)}")
        owen_pallet_sample = None
        for row in hist_rows:
            user = str(row.get("user") or "")
            stage = str(row.get("stage") or "")
            if "owen" in user.lower() and stage.lower() == "sorting":
                owen_pallet_sample = {
                    "timestamp": row.get("timestamp"),
                    "stockid": row.get("stockid"),
                    "user": user,
                    "stage": stage,
                    "location": row.get("location")
                }
                break

        result = {
            "timestamp": _dt.now().isoformat(),
            "date": target_date,
            "awaiting_qa": awaiting_qa,
            "awaiting_sorting": awaiting_sorting,
            "erased": int(erased),
            "qa_total": int(qa_total),
            "qa_app": int(qa_app),
            "user_combined_scans": user_count,
            "erasure_by_initials": erasure_by_initials,
            "owen_pallet_sample": owen_pallet_sample,
            "note": "Data sourced from dashboard PowerBI and QA endpoints (today-only)."
        }

        # Include precise matching diagnostics when available
        if 'precise_meta' in locals() and precise_meta:
            result.update({
                "precise_total_erasures": int(precise_meta.get("total_erasures", 0)),
                "precise_matched_qas": int(precise_meta.get("matched", 0)),
                "precise_awaiting_qa": int(precise_meta.get("awaiting_qa", 0)),
            })

        print(f"[Bottleneck-From-Dashboard] computed awaiting_qa={awaiting_qa} awaiting_sorting={awaiting_sorting}")
        try:
            _bottleneck_dashboard_cache.set(cache_key, result)
            print(f"[Bottleneck-From-Dashboard] cached result for {cache_key}")
        except Exception:
            print("[Bottleneck-From-Dashboard] cache write failed")
        return JSONResponse(status_code=200, content=result)
    except Exception as e:
        print(f"[Bottleneck-From-Dashboard] error: {e}")
        import traceback as _tb
        _tb.print_exc()
        return JSONResponse(status_code=500, content={"detail": "Failed to build bottleneck from dashboard."})


@app.get("/api/bottlenecks/details")
async def get_bottleneck_details(
    request: Request,
    category: str,
    value: str = None,
    limit: int = 100,
    days: int = 7,
    page: int = 1,
    page_size: int = 20
):
    """
    Get detailed device list for a specific bottleneck category - CURRENT state (no lookback).
    
    Categories:
    - unassigned: Devices without a QA user recorded
    - unpalleted: All unpalleted devices (current)
    - destination: Filter by destination/condition (value = destination name)
    - engineer: Filter by QA user (value = engineer email/name)
    - roller_pending: Data-bearing devices on rollers awaiting erasure
    - roller_awaiting_qa: Devices on rollers awaiting QA scan
    - roller_awaiting_pallet: Devices on rollers awaiting pallet ID
    - roller_station: Specific roller (value = roller name like "IA-ROLLER1")
    - quarantine: Devices in quarantine status
    """
    require_manager_or_admin(request)
    # pagination: normalize page and page_size; keep legacy `limit` as fallback
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or limit or 20), 500))
    days = max(1, min(int(days or 7), 90))
    
    import qa_export
    from datetime import datetime
    
    try:
        result = {
            "category": category,
            "value": value,
            "snapshot_timestamp": datetime.now().isoformat(),
            "devices": [],
            "total_count": 0,
            "showing": 0,
        }
        
        # Data-bearing device types (updated to match qa_export.py)
        DATA_BEARING_TYPES = [
            # Laptops
            'laptop', 'notebook', 'elitebook', 'probook', 'latitude', 'precision', 'xps', 'thinkpad', 'macbook', 'surface',
            # Desktops
            'desktop', 'optiplex', 'prodesk', 'precision', 'thinkcentre', 'imac', 'mac mini', 'mac pro',
            # Servers
            'server', 'blade', 'rackmount',
            # Network devices
            'switch', 'router', 'firewall', 'access point', 'network', 'hub',
            # Mobile devices
            'tablet', 'phone', 'mobile', 'smartphone', 'ipad', 'iphone', 'android', 'galaxy', 'handset', 'dect',
            # Storage devices
            'hard drive', 'ssd', 'hdd', 'nas', 'san',
            # Other computing devices
            'workstation', 'thin client', 'all-in-one'
        ]
        
        if category in ("roller_pending", "roller_awaiting_qa", "roller_awaiting_pallet", "roller_station"):
            # Query roller devices directly with recent activity window
            conn = qa_export.get_mariadb_connection()
            if not conn:
                raise HTTPException(status_code=500, detail="Database connection failed")
            
            cursor = conn.cursor()
            
            # Base query for devices on rollers without pallet ID
            base_select = """
                SELECT 
                    a.stockid, a.serialnumber, a.manufacturer, a.description,
                    a.condition, a.received_date, a.roller_location,
                    a.de_complete, a.de_completed_by, a.de_completed_date,
                    COALESCE(a.pallet_id, a.palletID) as pallet_id,
                    a.stage_current, a.last_update,
                    (SELECT MAX(q.added_date) FROM ITAD_QA_App q WHERE q.stockid = a.stockid) as last_qa_date
                FROM ITAD_asset_info a
            """
            recent_clause = "AND a.last_update IS NOT NULL AND a.last_update >= DATE_SUB(NOW(), INTERVAL %s DAY)"
            
            if category == "roller_station" and value:
                # Specific roller station - show all devices without pallet
                offset = (page - 1) * page_size
                cursor.execute(f"""
                        {base_select}
                        WHERE (a.roller_location = %s OR a.roller_location LIKE %s)
                            AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                            AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                            {recent_clause}
                        ORDER BY a.received_date DESC
                        LIMIT %s OFFSET %s
                                                """, (value, f"%:{value}", days, page_size, offset))
            elif category == "roller_pending":
                # Data-bearing devices awaiting erasure (not erased, no pallet)
                # Build parameterized OR condition for data-bearing types to avoid
                # passing raw '%' characters into pymysql's mogrify formatting.
                types = DATA_BEARING_TYPES
                type_clause = " OR ".join(["LOWER(a.description) LIKE %s" for _ in types])
                type_params = tuple([f"%{t}%" for t in types])
                offset = (page - 1) * page_size
                cursor.execute(f"""
                        {base_select}
                        WHERE a.roller_location IS NOT NULL 
                            AND a.roller_location != ''
                            AND LOWER(a.roller_location) LIKE '%%roller%%'
                            AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                            AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                            AND (a.de_complete IS NULL OR LOWER(a.de_complete) NOT IN ('yes', 'true', '1'))
                            AND ({type_clause})
                            {recent_clause}
                        ORDER BY a.received_date DESC
                        LIMIT %s OFFSET %s
                                                """, (*type_params, days, page_size, offset))
            elif category == "roller_awaiting_qa":
                # Devices that are erased (or non-data-bearing) but haven't had QA scan
                # On roller, no pallet, and either:
                #   - Data-bearing: erased but no QA after erasure
                #   - Non-data-bearing: no QA scan at all
                                # Only include devices that are erased (de_complete) OR have Blancco records;
                                # exclude devices whose destination/condition indicates Quarantine because
                                # those are effectively awaiting sorting rather than QA.
                                cursor.execute(f"""
                                        {base_select}
                                        WHERE a.roller_location IS NOT NULL 
                                            AND a.roller_location != ''
                                            AND LOWER(a.roller_location) LIKE '%%roller%%'
                                            AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                                              AND LOWER(COALESCE(a.`condition`, '')) NOT LIKE '%%quarantine%%'
                                            AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                                            AND (
                                                (LOWER(COALESCE(a.de_complete, '')) IN ('yes', 'true', '1')
                                                 AND NOT EXISTS (SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid AND q.added_date > a.de_completed_date))
                                                OR
                                                (EXISTS (SELECT 1 FROM ITAD_asset_info_blancco b WHERE b.stockid = a.stockid)
                                                 AND NOT EXISTS (SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid))
                                            )
                                                                                        {recent_clause}
                                                                                ORDER BY a.received_date DESC
                                                                                LIMIT %s OFFSET %s
                                                                                                                                """, (days, page_size, (page-1)*page_size))
            else:  # roller_awaiting_pallet
                # Devices that have been QA'd but don't have a pallet yet
                                cursor.execute(f"""
                    {base_select}
                    WHERE a.roller_location IS NOT NULL 
                      AND a.roller_location != ''
                      AND LOWER(a.roller_location) LIKE '%%roller%%'
                      AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                      AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                      AND EXISTS (
                        SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid 
                        AND (a.de_completed_date IS NULL OR q.added_date > a.de_completed_date)
                      )
                                            {recent_clause}
                                        ORDER BY a.received_date DESC
                                        LIMIT %s OFFSET %s
                                                                """, (days, page_size, (page-1)*page_size))
            
            devices = []
            for row in cursor.fetchall():
                desc = row[3] or ""
                is_data_bearing = any(t in desc.lower() for t in DATA_BEARING_TYPES)
                is_erased = str(row[7] or "").lower() in ("yes", "true", "1")
                last_qa = row[13]
                de_completed = row[9]
                
                # Determine workflow stage
                if is_data_bearing and not is_erased:
                    stage = "Awaiting Erasure"
                elif last_qa and (not de_completed or last_qa > de_completed):
                    stage = "Awaiting Pallet"
                else:
                    stage = "Awaiting QA"
                
                devices.append({
                    "stockid": row[0],
                    "serial": row[1],
                    "manufacturer": row[2],
                    "model": row[3],
                    "condition": row[4],
                    "received_date": str(row[5]) if row[5] else None,
                    "roller_location": row[6],
                    "de_complete": row[7],
                    "de_completed_by": row[8],
                    "de_completed_date": str(row[9]) if row[9] else None,
                    "pallet_id": row[10],
                    "stage_current": row[11],
                    "last_update": str(row[12]) if row[12] else None,
                    "workflow_stage": stage,
                    "is_data_bearing": is_data_bearing,
                })
            
            # Get total count based on category
            if category == "roller_station" and value:
                cursor.execute("""
                    SELECT COUNT(*) FROM ITAD_asset_info 
                    WHERE (roller_location = %s OR roller_location LIKE %s)
                      AND `condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                      AND (COALESCE(pallet_id, palletID, '') = '' OR COALESCE(pallet_id, palletID) IS NULL OR COALESCE(pallet_id, palletID) LIKE 'NOPOST%%')
                                            AND last_update IS NOT NULL
                                            AND last_update >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                """, (value, f"%:{value}", days))
            elif category == "roller_pending":
                # Count data-bearing devices awaiting erasure
                                types = DATA_BEARING_TYPES
                                type_clause = " OR ".join(["LOWER(description) LIKE %s" for _ in types])
                                type_params = tuple([f"%{t}%" for t in types])
                                cursor.execute(f"""
                                        SELECT COUNT(*) FROM ITAD_asset_info 
                                        WHERE roller_location IS NOT NULL AND roller_location != ''
                                            AND LOWER(roller_location) LIKE '%%roller%%'
                                            AND `condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                                            AND (COALESCE(pallet_id, palletID, '') = '' OR COALESCE(pallet_id, palletID) IS NULL OR COALESCE(pallet_id, palletID) LIKE 'NOPOST%%')
                                            AND (de_complete IS NULL OR LOWER(de_complete) NOT IN ('yes', 'true', '1'))
                                            AND ({type_clause})
                                                                                        AND last_update IS NOT NULL
                                                                                        AND last_update >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                                                """, (*type_params, days,))
            elif category == "roller_awaiting_qa":
                # Count devices awaiting QA
                cursor.execute("""
                    SELECT COUNT(*) FROM ITAD_asset_info a
                    WHERE a.roller_location IS NOT NULL AND a.roller_location != ''
                      AND LOWER(a.roller_location) LIKE '%%roller%%'
                      AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                      AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                      AND (
                        (LOWER(COALESCE(a.de_complete, '')) IN ('yes', 'true', '1')
                         AND NOT EXISTS (SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid AND q.added_date > a.de_completed_date))
                        OR
                        (LOWER(COALESCE(a.de_complete, '')) NOT IN ('yes', 'true', '1')
                         AND NOT EXISTS (SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid))
                      )
                                            AND a.last_update IS NOT NULL
                                            AND a.last_update >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                """, (days,))
            else:  # roller_awaiting_pallet
                # Count devices with QA but no pallet
                cursor.execute("""
                    SELECT COUNT(*) FROM ITAD_asset_info a
                    WHERE a.roller_location IS NOT NULL AND a.roller_location != ''
                      AND LOWER(a.roller_location) LIKE '%%roller%%'
                      AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                      AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL)
                      AND EXISTS (
                        SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid 
                        AND (a.de_completed_date IS NULL OR q.added_date > a.de_completed_date)
                      )
                                            AND a.last_update IS NOT NULL
                                            AND a.last_update >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                """, (days,))
            
            total = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            
            result["devices"] = devices
            result["total_count"] = total
            result["showing"] = len(devices)
            
        else:
            # Use recent unpalleted devices query with filters
            all_devices = qa_export.get_unpalleted_devices_recent(days_threshold=days)
            
            filtered = []
            for d in all_devices:
                qa_user = (d.get("qa_user") or "").strip()
                condition = (d.get("condition") or "").strip()
                
                if category == "unassigned":
                    if not qa_user:
                        filtered.append(d)
                elif category == "unpalleted":
                    filtered.append(d)
                elif category == "destination" and value:
                    if condition.lower() == value.lower():
                        filtered.append(d)
                elif category == "engineer" and value:
                    if qa_user.lower() == value.lower():
                        filtered.append(d)
                elif category == "quarantine":
                    if "quarantine" in condition.lower():
                        filtered.append(d)
            
            result["total_count"] = len(filtered)
            result["devices"] = filtered[:limit]
            result["showing"] = len(result["devices"])
        
        # Add summary stats for the category
        if result["devices"]:
            # Count by manufacturer
            mfg_counts = {}
            condition_counts = {}
            for d in result["devices"]:
                mfg = d.get("manufacturer") or "Unknown"
                mfg_counts[mfg] = mfg_counts.get(mfg, 0) + 1
                cond = d.get("condition") or "Unknown"
                condition_counts[cond] = condition_counts.get(cond, 0) + 1
            
            result["breakdown"] = {
                "by_manufacturer": sorted(
                    [{"name": k, "count": v} for k, v in mfg_counts.items()],
                    key=lambda x: x["count"], reverse=True
                )[:10],
                "by_condition": sorted(
                    [{"name": k, "count": v} for k, v in condition_counts.items()],
                    key=lambda x: x["count"], reverse=True
                )[:10],
            }
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Bottleneck details error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


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
