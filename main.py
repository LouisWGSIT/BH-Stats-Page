from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from starlette.background import BackgroundTask
import tempfile
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
import os
from typing import Any, Dict
from datetime import datetime, timedelta, date, UTC
import asyncio
import backend.database as db
import backend.excel_export as excel_export
import ipaddress
import json
import httpx  # For making API calls to Blancco
from time import time
import zipfile
import io
import backend.qa_export as qa_export
import routers.health as health_router
from backend.app import auth_utils
from backend.app import activity_logging
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
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
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
                    'ts': datetime.now(UTC).replace(tzinfo=None).isoformat(),
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
ACTIVITY_LOG = activity_logging.create_activity_log(maxlen=5000)


def get_process_rss_bytes() -> int | None:
    return activity_logging.get_process_rss_bytes(psutil_module=psutil)


def record_activity(entry: dict):
    return activity_logging.record_activity(
        entry,
        activity_log=ACTIVITY_LOG,
        get_activity_writer=lambda: getattr(app.state, 'activity_writer', None),
    )


def should_record_request(request: Request) -> bool:
    return activity_logging.should_record_request(request)


@app.on_event('startup')
def _start_activity_writer():
    activity_logging.start_activity_writer(
        app,
        db_path=os.getenv('ACTIVITY_DB_PATH', 'logs/activity.sqlite'),
    )


@app.on_event('shutdown')
def _stop_activity_writer():
    activity_logging.stop_activity_writer(app)

def load_device_tokens():
    return auth_utils.load_device_tokens(
        db_module=db,
        device_tokens_db=DEVICE_TOKENS_DB,
        device_tokens_file=DEVICE_TOKENS_FILE,
    )


def save_device_tokens(tokens):
    return auth_utils.save_device_tokens(
        tokens=tokens,
        db_module=db,
        device_tokens_db=DEVICE_TOKENS_DB,
        device_tokens_file=DEVICE_TOKENS_FILE,
    )

def generate_device_token(user_agent: str, client_ip: str) -> str:
    return auth_utils.generate_device_token(user_agent, client_ip)

def is_device_token_valid(token: str) -> bool:
    return auth_utils.is_device_token_valid(
        token=token,
        load_tokens=load_device_tokens,
        save_tokens=save_device_tokens,
    )

def touch_device_token(token: str, client_ips: list | None = None, user_agent: str | None = None):
    return auth_utils.touch_device_token(
        token=token,
        load_tokens=load_device_tokens,
        save_tokens=save_device_tokens,
        client_ips=client_ips,
        user_agent=user_agent,
    )

def is_local_network(client_ip: str) -> bool:
    return auth_utils.is_local_network(client_ip=client_ip, local_networks=LOCAL_NETWORKS)

def get_client_ip(request: Request) -> str:
    return auth_utils.get_client_ip(request)

def get_client_ips(request: Request) -> list:
    return auth_utils.get_client_ips(request)

def get_role_from_request(request: Request) -> str | None:
    return auth_utils.get_role_from_request(
        request=request,
        admin_password=ADMIN_PASSWORD,
        manager_password=MANAGER_PASSWORD,
        is_token_valid=is_device_token_valid,
        load_tokens=load_device_tokens,
    )

def require_manager_or_admin(request: Request):
    return auth_utils.require_manager_or_admin(request=request, get_role=get_role_from_request)

def require_admin(request: Request):
    return auth_utils.require_admin(request=request, get_role=get_role_from_request)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    return await auth_utils.auth_middleware(
        request=request,
        call_next=call_next,
        dashboard_public=DASHBOARD_PUBLIC,
        admin_password=ADMIN_PASSWORD,
        manager_password=MANAGER_PASSWORD,
        is_local_network_fn=is_local_network,
        is_token_valid_fn=is_device_token_valid,
        load_tokens_fn=load_device_tokens,
        touch_token_fn=touch_device_token,
        get_client_ip_fn=get_client_ip,
        get_client_ips_fn=get_client_ips,
    )
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

