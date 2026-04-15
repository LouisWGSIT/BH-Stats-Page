from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from starlette.background import BackgroundTask
import tempfile
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager
import os
from typing import Any, Dict
from datetime import datetime, timedelta, date, UTC
import asyncio
import backend.database as db
import backend.excel_export as excel_export
import json
import zipfile
import io
import backend.qa_export as qa_export
import routers.health as health_router
from backend.app import auth_utils
from backend.app import activity_logging
from backend.app import runtime_state
from backend.app import router_wiring
from backend.app import blancco_client
from backend.app import auth_bindings as auth_bindings_module
from backend.app import request_middleware
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
from backend.app.routes.overall_stats import create_overall_stats_router
from backend.app.routes.qa_insights import (
    compute_qa_dashboard_data,
    create_qa_insights_router,
    refresh_qa_snapshot_tables,
)
from backend.app.routes.static_pages import create_static_pages_router
from backend.app.routes.webhooks import create_webhooks_router
from backend.app.runtime_tasks import (
    TTLCache,
    check_daily_reset,
    memory_watchdog,
    refresh_qa_snapshots_periodically,
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
startup_logger = logging.getLogger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_logger.info(
        "Startup storage paths: stats_db=%s device_tokens_db=%s",
        db.DB_PATH,
        DEVICE_TOKENS_DB,
    )

    activity_logging.start_activity_writer(
        app,
        db_path=os.getenv('ACTIVITY_DB_PATH', 'logs/activity.sqlite'),
    )

    background_tasks = []
    # Avoid blocking cold start on sync work; run it in a worker thread instead.
    try:
        background_tasks.append(
            asyncio.create_task(
                asyncio.to_thread(lambda: sync_engineer_stats_on_startup(db_module=db))
            )
        )
    except Exception:
        pass

    background_tasks.append(asyncio.create_task(check_daily_reset()))

    try:
        background_tasks.append(
            asyncio.create_task(
                warm_cache_on_startup(
                    db_module=db,
                    qa_export_module=qa_export,
                    cache_set=_set_cached_response,
                )
            )
        )
    except Exception:
        pass

    try:
        background_tasks.append(
            asyncio.create_task(
                memory_watchdog(
                    psutil_module=psutil,
                    cache_clear=QA_CACHE.clear,
                    take_tracemalloc_snapshot=take_tracemalloc_snapshot,
                )
            )
        )
    except Exception:
        pass

    try:
        background_tasks.append(
            asyncio.create_task(
                refresh_qa_snapshots_periodically(
                    refresh_snapshots_func=refresh_qa_snapshot_tables,
                    interval_seconds=int(os.getenv("QA_SNAPSHOT_REFRESH_SECONDS", "120")),
                )
            )
        )
    except Exception:
        pass

    app.state.background_tasks = background_tasks
    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        activity_logging.stop_activity_writer(app)


app = FastAPI(title="Warehouse Stats Service", lifespan=lifespan)
app.include_router(health_router.router)
# Enable GZip compression for responses over a threshold to reduce payload sizes
app.add_middleware(GZipMiddleware, minimum_size=500)

# Export job routes (enqueue / status) - optional Redis/RQ integration
try:
    import backend.export_jobs as export_jobs
    app.include_router(export_jobs.router)
except Exception:
    # If the module or dependencies aren't available at runtime, skip router
    pass

import backend.request_context as request_context

# ============= BLANCCO API CONFIG =============
BLANCCO_API_URL, BLANCCO_API_KEY, QA_CONFIRMED_SCORE = blancco_client.get_config()

async def fetch_blancco_device_details(job_id: str):
    return await blancco_client.fetch_device_details(
        job_id,
        api_url=BLANCCO_API_URL,
        api_key=BLANCCO_API_KEY,
    )

# ============= SECURITY CONFIG =============
LOCAL_NETWORKS = runtime_state.build_local_networks()
MANAGER_PASSWORD = runtime_state.get_manager_password()
ADMIN_PASSWORD = runtime_state.get_admin_password()
DASHBOARD_PUBLIC = runtime_state.get_dashboard_public_flag()

# Device token storage (persistent across redeployments)
DEVICE_TOKENS_FILE, DEVICE_TOKENS_DB, DEVICE_TOKEN_EXPIRY_DAYS = runtime_state.get_device_token_settings()

# Bounded TTL cache for QA/dashboard responses
QA_CACHE = runtime_state.create_qa_cache(TTLCache)

def _get_cached_response(cache_key: str):
    return runtime_state.cache_get(QA_CACHE, cache_key)

def _set_cached_response(cache_key: str, data: Dict[str, object]):
    return runtime_state.cache_set(QA_CACHE, cache_key, data)


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
auth_binding_funcs = auth_bindings_module.create_auth_bindings(
    auth_utils=auth_utils,
    db_module=db,
    device_tokens_db=DEVICE_TOKENS_DB,
    device_tokens_file=DEVICE_TOKENS_FILE,
    local_networks=LOCAL_NETWORKS,
    admin_password=ADMIN_PASSWORD,
    manager_password=MANAGER_PASSWORD,
    dashboard_public=DASHBOARD_PUBLIC,
    legacy_query_auth_enabled=runtime_state.is_legacy_query_auth_enabled(),
    legacy_basic_auth_enabled=runtime_state.is_legacy_basic_auth_enabled(),
)

load_device_tokens = auth_binding_funcs["load_device_tokens"]
save_device_tokens = auth_binding_funcs["save_device_tokens"]
generate_device_token = auth_binding_funcs["generate_device_token"]
is_device_token_valid = auth_binding_funcs["is_device_token_valid"]
touch_device_token = auth_binding_funcs["touch_device_token"]
is_local_network = auth_binding_funcs["is_local_network"]
get_client_ip = auth_binding_funcs["get_client_ip"]
get_client_ips = auth_binding_funcs["get_client_ips"]
get_role_from_request = auth_binding_funcs["get_role_from_request"]
require_manager_or_admin = auth_binding_funcs["require_manager_or_admin"]
require_admin = auth_binding_funcs["require_admin"]

add_request_id_middleware = request_middleware.create_request_id_middleware(
    request_context_module=request_context,
    should_record_request=should_record_request,
    get_client_ip=get_client_ip,
    get_process_rss_bytes=get_process_rss_bytes,
    record_activity=record_activity,
)

app.middleware("http")(add_request_id_middleware)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    return await auth_binding_funcs["auth_middleware"](request, call_next)


@app.middleware("http")
async def static_cache_headers_middleware(request: Request, call_next):
    response = await call_next(request)

    if request.method != "GET":
        return response

    if response.headers.get("Cache-Control"):
        return response

    path = request.url.path.lower()
    static_exts = (
        ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".woff", ".woff2"
    )

    if path.endswith(static_exts):
        response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=600"
    elif path in ("/", "/index.html", "/admin.html", "/manager.html"):
        response.headers["Cache-Control"] = "no-cache"
    elif path.endswith(".json"):
        response.headers["Cache-Control"] = "no-cache"

    return response
# Initialize database tables on startup
db.init_db()

# Backfill progress status (shared in-memory)
BACKFILL_PROGRESS = runtime_state.initial_backfill_progress()

# Enable CORS for TV access from network (more restricted now with auth middleware)
CORS_ALLOW_ORIGINS = runtime_state.get_cors_allow_origins()
CORS_ALLOW_CREDENTIALS = "*" not in CORS_ALLOW_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEBHOOK_API_KEYS = runtime_state.get_webhook_api_keys()
# Backward-compat alias for older tests/modules that still reference a single key name.
WEBHOOK_API_KEY = WEBHOOK_API_KEYS[0] if WEBHOOK_API_KEYS else ""

HWID_LOG_PATH = runtime_state.get_hwid_log_path()
FRONTEND_PAGES_DIR, FRONTEND_JS_DIR, FRONTEND_CSS_DIR = runtime_state.get_frontend_paths()

router_wiring.register_routes(
    app,
    create_auth_router=create_auth_router,
    create_admin_activity_router=create_admin_activity_router,
    create_admin_devices_router=create_admin_devices_router,
    create_admin_diagnostics_router=create_admin_diagnostics_router,
    create_admin_initials_router=create_admin_initials_router,
    create_admin_maintenance_router=create_admin_maintenance_router,
    create_admin_backfill_router=create_admin_backfill_router,
    create_admin_exports_router=create_admin_exports_router,
    create_erasure_insights_router=create_erasure_insights_router,
    create_qa_insights_router=create_qa_insights_router,
    create_metrics_analytics_router=create_metrics_analytics_router,
    create_overall_stats_router=create_overall_stats_router,
    create_webhooks_router=create_webhooks_router,
    create_device_lookup_router=create_device_lookup_router,
    create_bottleneck_router=create_bottleneck_router,
    create_static_pages_router=create_static_pages_router,
    create_hwid_router=create_hwid_router,
    admin_password=ADMIN_PASSWORD,
    manager_password=MANAGER_PASSWORD,
    device_token_expiry_days=DEVICE_TOKEN_EXPIRY_DAYS,
    get_client_ip=get_client_ip,
    get_client_ips=get_client_ips,
    is_local_network=is_local_network,
    local_networks=LOCAL_NETWORKS,
    is_device_token_valid=is_device_token_valid,
    load_device_tokens=load_device_tokens,
    save_device_tokens=save_device_tokens,
    get_last_server_error=lambda: LAST_SERVER_ERROR,
    touch_device_token=touch_device_token,
    generate_device_token=generate_device_token,
    require_admin=require_admin,
    require_manager_or_admin=require_manager_or_admin,
    activity_log=ACTIVITY_LOG,
    db_module=db,
    qa_export_module=qa_export,
    excel_export_module=excel_export,
    psutil_module=psutil,
    trace_snapshot_threshold_mb=TRACE_SNAPSHOT_THRESHOLD_MB,
    take_tracemalloc_snapshot=take_tracemalloc_snapshot,
    set_last_server_error=lambda payload: globals().__setitem__("LAST_SERVER_ERROR", payload),
    cache_get=_get_cached_response,
    cache_set=_set_cached_response,
    webhook_api_keys=WEBHOOK_API_KEYS,
    hwid_log_path=HWID_LOG_PATH,
    get_role_from_request=get_role_from_request,
    ttl_cache_cls=TTLCache,
    compute_qa_dashboard_data=compute_qa_dashboard_data,
    backfill_progress=BACKFILL_PROGRESS,
    frontend_pages_dir=FRONTEND_PAGES_DIR,
    frontend_js_dir=FRONTEND_JS_DIR,
    frontend_css_dir=FRONTEND_CSS_DIR,
)

