import logging
import os
import tempfile
import zipfile
import hashlib
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

import backend.engineer_export as engineer_export
import backend.qa_export as qa_export


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _parse_int_env(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _qa_export_cache_dir() -> str:
    configured = str(os.getenv("QA_EXPORT_CACHE_DIR", "")).strip()
    if configured:
        return configured
    return os.path.join(tempfile.gettempdir(), "bh_qa_export_cache")


def _qa_export_cache_key(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _qa_cache_meta_path(cache_dir: str, cache_key: str) -> str:
    return os.path.join(cache_dir, f"{cache_key}.json")


def _qa_cache_payload_path(cache_dir: str, cache_key: str, ext: str) -> str:
    return os.path.join(cache_dir, f"{cache_key}{ext}")


def _cleanup_qa_cache(cache_dir: str, *, now_ts: float, max_age_seconds: int, max_entries: int) -> None:
    try:
        entries: list[tuple[float, str, str]] = []
        for name in os.listdir(cache_dir):
            if not name.endswith(".json"):
                continue
            meta_path = os.path.join(cache_dir, name)
            try:
                with open(meta_path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
                created_ts = float(meta.get("created_ts", 0.0) or 0.0)
                payload_path = str(meta.get("payload_path") or "")
            except Exception:
                created_ts = 0.0
                payload_path = ""

            is_stale = (now_ts - created_ts) > max_age_seconds
            if (not payload_path) or (not os.path.exists(payload_path)) or is_stale:
                try:
                    os.remove(meta_path)
                except Exception:
                    pass
                if payload_path:
                    try:
                        os.remove(payload_path)
                    except Exception:
                        pass
                continue

            entries.append((created_ts, meta_path, payload_path))

        if len(entries) <= max_entries:
            return

        entries.sort(key=lambda item: item[0], reverse=True)
        for _created_ts, meta_path, payload_path in entries[max_entries:]:
            try:
                os.remove(meta_path)
            except Exception:
                pass
            try:
                os.remove(payload_path)
            except Exception:
                pass
    except Exception:
        pass


def _load_cached_qa_export(cache_dir: str, cache_key: str, max_age_seconds: int) -> dict | None:
    meta_path = _qa_cache_meta_path(cache_dir, cache_key)
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        payload_path = str(meta.get("payload_path") or "")
        created_ts = float(meta.get("created_ts", 0.0) or 0.0)
        if (not payload_path) or (not os.path.exists(payload_path)):
            return None
        if (datetime.utcnow().timestamp() - created_ts) > max_age_seconds:
            return None
        return {
            "payload_path": payload_path,
            "filename": str(meta.get("filename") or "qa-export.xlsx"),
            "media_type": str(meta.get("media_type") or "application/octet-stream"),
        }
    except Exception:
        return None


def _store_cached_qa_export(
    cache_dir: str,
    cache_key: str,
    source_path: str,
    *,
    filename: str,
    media_type: str,
) -> str | None:
    try:
        os.makedirs(cache_dir, exist_ok=True)
        ext = os.path.splitext(filename)[1] or ".bin"
        payload_path = _qa_cache_payload_path(cache_dir, cache_key, ext)
        tmp_payload_path = f"{payload_path}.tmp"
        with open(source_path, "rb") as src, open(tmp_payload_path, "wb") as dst:
            dst.write(src.read())
        os.replace(tmp_payload_path, payload_path)

        meta = {
            "payload_path": payload_path,
            "filename": filename,
            "media_type": media_type,
            "created_ts": datetime.utcnow().timestamp(),
        }
        meta_path = _qa_cache_meta_path(cache_dir, cache_key)
        tmp_meta_path = f"{meta_path}.tmp"
        with open(tmp_meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        os.replace(tmp_meta_path, meta_path)
        return payload_path
    except Exception:
        return None


def _parse_boolish(value: str | None) -> bool | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def _get_process_rss_bytes(psutil_module) -> int | None:
    try:
        if psutil_module:
            return psutil_module.Process().memory_info().rss
    except Exception:
        pass
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    except Exception:
        return None


def create_admin_exports_router(
    *,
    require_manager_or_admin: Callable[[Request], None],
    db_module,
    excel_export_module,
    psutil_module,
    trace_snapshot_threshold_mb: int,
    take_tracemalloc_snapshot: Callable[[str, dict | None], str | None],
    set_last_server_error: Callable[[dict], None],
) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("export")
    qa_export_cache_enabled = _parse_bool_env("QA_EXPORT_CACHE_ENABLED", True)
    qa_export_cache_ttl_seconds = _parse_int_env("QA_EXPORT_CACHE_TTL_SECONDS", 300, minimum=30, maximum=3600)
    qa_export_cache_max_entries = _parse_int_env("QA_EXPORT_CACHE_MAX_ENTRIES", 30, minimum=5, maximum=500)
    qa_export_cache_dir = _qa_export_cache_dir()
    qa_export_async_enabled = _parse_bool_env("QA_EXPORT_ASYNC_ENABLED", True)
    qa_export_async_workers = _parse_int_env("QA_EXPORT_ASYNC_WORKERS", 1, minimum=1, maximum=4)
    qa_export_async_job_ttl_seconds = _parse_int_env("QA_EXPORT_ASYNC_JOB_TTL_SECONDS", 3600, minimum=300, maximum=86400)
    qa_export_async_download_ttl_seconds = _parse_int_env("QA_EXPORT_ASYNC_DOWNLOAD_TTL_SECONDS", 900, minimum=120, maximum=86400)

    qa_export_executor = ThreadPoolExecutor(max_workers=qa_export_async_workers, thread_name_prefix="qa-export")
    qa_export_jobs_lock = threading.Lock()
    qa_export_jobs: dict[str, dict] = {}

    def _safe_remove(path: str | None) -> None:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _cleanup_async_jobs() -> None:
        now_ts = time.time()
        with qa_export_jobs_lock:
            stale_ids = []
            for job_id, job in qa_export_jobs.items():
                status = str(job.get("status") or "")
                updated_ts = float(job.get("updated_ts") or job.get("created_ts") or now_ts)
                ttl = qa_export_async_download_ttl_seconds if status == "completed" else qa_export_async_job_ttl_seconds
                if (now_ts - updated_ts) > ttl:
                    stale_ids.append(job_id)

            for job_id in stale_ids:
                job = qa_export_jobs.pop(job_id, None)
                if not job:
                    continue
                if not bool(job.get("cached")):
                    _safe_remove(job.get("payload_path"))

    def _validate_qa_export_request(
        *,
        period: str,
        include_device_sheets: str,
        start_year: int | None,
        start_month: int | None,
        end_year: int | None,
        end_month: int | None,
    ) -> dict:
        normalized_period = str(period or "this_week").replace("-", "_")
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
        if normalized_period not in valid_periods:
            raise HTTPException(status_code=400, detail=f"Invalid period. Must be one of: {', '.join(valid_periods)}")

        if normalized_period == "custom_range":
            if not all([start_year, start_month, end_year, end_month]):
                raise HTTPException(
                    status_code=400,
                    detail="Custom range requires start_year, start_month, end_year, end_month",
                )
            if start_month < 1 or start_month > 12 or end_month < 1 or end_month > 12:
                raise HTTPException(status_code=400, detail="Month must be between 1 and 12")

        include_device_opt = _parse_boolish(include_device_sheets)
        if include_device_opt is None:
            include_device_opt = normalized_period in ("this_week", "last_week")

        long_periods = {
            "this_month",
            "last_month",
            "this_year",
            "last_year",
            "last_year_h1",
            "last_year_h2",
            "custom_range",
        }

        cache_key_payload = {
            "route": "export/qa-stats",
            "period": normalized_period,
            "include_device_sheets": bool(include_device_opt),
            "start_year": start_year,
            "start_month": start_month,
            "end_year": end_year,
            "end_month": end_month,
        }

        return {
            "period": normalized_period,
            "include_device_opt": bool(include_device_opt),
            "start_year": start_year,
            "start_month": start_month,
            "end_year": end_year,
            "end_month": end_month,
            "is_long_period": normalized_period in long_periods,
            "cache_key": _qa_export_cache_key(cache_key_payload),
        }

    def _generate_qa_export_artifact(args: dict) -> dict:
        period = args["period"]
        include_device_opt = args["include_device_opt"]
        start_year = args.get("start_year")
        start_month = args.get("start_month")
        end_year = args.get("end_year")
        end_month = args.get("end_month")
        is_long_period = bool(args.get("is_long_period"))
        cache_key = str(args["cache_key"])

        if qa_export_cache_enabled:
            cached = _load_cached_qa_export(qa_export_cache_dir, cache_key, qa_export_cache_ttl_seconds)
            if cached and os.path.exists(cached["payload_path"]):
                return {
                    "payload_path": cached["payload_path"],
                    "filename": cached["filename"],
                    "media_type": cached["media_type"],
                    "cached": True,
                }

        period_label = period.replace("_", "-")

        if is_long_period:
            chunks = qa_export.generate_qa_engineer_export_chunked(
                period,
                start_year=start_year,
                start_month=start_month,
                end_year=end_year,
                end_month=end_month,
                include_device_sheets=include_device_opt,
            )

            if len(chunks) == 1:
                _suffix, sheets_data = chunks[0]
                fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
                os.close(fd)
                excel_export_module.create_excel_report(sheets_data, output_path=tmp_path)
                filename = f"qa-engineer-stats-{period_label}.xlsx"
                media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            else:
                fd_zip, tmp_path = tempfile.mkstemp(suffix=".zip")
                os.close(fd_zip)
                with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    for suffix, sheets_data in chunks:
                        fd, tmp_xlsx = tempfile.mkstemp(suffix=".xlsx")
                        os.close(fd)
                        try:
                            excel_export_module.create_excel_report(sheets_data, output_path=tmp_xlsx)
                            excel_filename = f"qa-engineer-stats-{period_label}{suffix}.xlsx"
                            zip_file.write(tmp_xlsx, arcname=excel_filename)
                        finally:
                            _safe_remove(tmp_xlsx)
                filename = f"qa-engineer-stats-{period_label}-weekly.zip"
                media_type = "application/zip"
        else:
            sheets_data = qa_export.generate_qa_engineer_export(
                period,
                start_year=start_year,
                start_month=start_month,
                end_year=end_year,
                end_month=end_month,
                include_device_sheets=include_device_opt,
            )
            fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
            os.close(fd)
            excel_export_module.create_excel_report(sheets_data, output_path=tmp_path)
            filename = f"qa-engineer-stats-{period_label}.xlsx"
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        if qa_export_cache_enabled:
            cached_path = _store_cached_qa_export(
                qa_export_cache_dir,
                cache_key,
                tmp_path,
                filename=filename,
                media_type=media_type,
            )
            if cached_path and os.path.exists(cached_path):
                _safe_remove(tmp_path)
                _cleanup_qa_cache(
                    qa_export_cache_dir,
                    now_ts=datetime.utcnow().timestamp(),
                    max_age_seconds=qa_export_cache_ttl_seconds,
                    max_entries=qa_export_cache_max_entries,
                )
                return {
                    "payload_path": cached_path,
                    "filename": filename,
                    "media_type": media_type,
                    "cached": True,
                }

        return {
            "payload_path": tmp_path,
            "filename": filename,
            "media_type": media_type,
            "cached": False,
        }

    def _run_async_qa_export_job(job_id: str, args: dict) -> None:
        with qa_export_jobs_lock:
            job = qa_export_jobs.get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["progress_pct"] = 10
            job["message"] = "Preparing export"
            job["updated_ts"] = time.time()

        try:
            with qa_export_jobs_lock:
                job = qa_export_jobs.get(job_id)
                if job:
                    job["progress_pct"] = 45
                    job["message"] = "Generating workbook"
                    job["updated_ts"] = time.time()

            artifact = _generate_qa_export_artifact(args)

            with qa_export_jobs_lock:
                job = qa_export_jobs.get(job_id)
                if not job:
                    if not bool(artifact.get("cached")):
                        _safe_remove(artifact.get("payload_path"))
                    return
                job["status"] = "completed"
                job["progress_pct"] = 100
                job["message"] = "Export ready"
                job["payload_path"] = artifact["payload_path"]
                job["filename"] = artifact["filename"]
                job["media_type"] = artifact["media_type"]
                job["cached"] = bool(artifact.get("cached"))
                job["updated_ts"] = time.time()
        except Exception as exc:
            logger.exception("Async QA export job failed: %s", exc)
            with qa_export_jobs_lock:
                job = qa_export_jobs.get(job_id)
                if job:
                    job["status"] = "failed"
                    job["progress_pct"] = 100
                    job["message"] = "Export failed"
                    job["error"] = str(exc)
                    job["updated_ts"] = time.time()

    @router.post("/export/qa-stats/jobs")
    async def start_qa_export_job(
        request: Request,
        period: str = "this_week",
        include_device_sheets: str = "auto",
        start_year: int = None,
        start_month: int = None,
        end_year: int = None,
        end_month: int = None,
    ):
        require_manager_or_admin(request)
        if not qa_export_async_enabled:
            raise HTTPException(status_code=503, detail="Async QA export is disabled")
        _cleanup_async_jobs()
        db_module.init_db()

        args = _validate_qa_export_request(
            period=period,
            include_device_sheets=include_device_sheets,
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
        )

        job_id = uuid.uuid4().hex
        now_ts = time.time()
        with qa_export_jobs_lock:
            qa_export_jobs[job_id] = {
                "id": job_id,
                "status": "queued",
                "progress_pct": 0,
                "message": "Queued",
                "created_ts": now_ts,
                "updated_ts": now_ts,
                "error": None,
                "payload_path": None,
                "filename": None,
                "media_type": None,
                "cached": False,
            }

        qa_export_executor.submit(_run_async_qa_export_job, job_id, args)
        return {"job_id": job_id, "status": "queued"}

    @router.get("/export/qa-stats/jobs/{job_id}")
    async def get_qa_export_job_status(request: Request, job_id: str):
        require_manager_or_admin(request)
        _cleanup_async_jobs()
        with qa_export_jobs_lock:
            job = qa_export_jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Export job not found")
            return {
                "job_id": job["id"],
                "status": job["status"],
                "progress_pct": int(job.get("progress_pct") or 0),
                "message": job.get("message") or "",
                "error": job.get("error"),
                "ready": job.get("status") == "completed",
            }

    @router.get("/export/qa-stats/jobs/{job_id}/download")
    async def download_qa_export_job_result(request: Request, job_id: str):
        require_manager_or_admin(request)
        _cleanup_async_jobs()
        with qa_export_jobs_lock:
            job = qa_export_jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Export job not found")
            if job.get("status") != "completed":
                raise HTTPException(status_code=409, detail="Export job is not ready")
            payload_path = str(job.get("payload_path") or "")
            filename = str(job.get("filename") or "qa-export.xlsx")
            media_type = str(job.get("media_type") or "application/octet-stream")
            is_cached = bool(job.get("cached"))
            job["updated_ts"] = time.time()

        if (not payload_path) or (not os.path.exists(payload_path)):
            raise HTTPException(status_code=410, detail="Export file expired; please generate a new one")

        background = None
        if not is_cached:
            background = BackgroundTask(lambda: _safe_remove(payload_path))

        return FileResponse(
            payload_path,
            media_type=media_type,
            filename=filename,
            background=background,
        )

    @router.post("/export/excel")
    async def export_excel(req: Request):
        """Generate multi-sheet Excel export of warehouse stats (manager only)."""
        require_manager_or_admin(req)
        try:
            body = await req.json()
            sheets_data = body.get("sheetsData", {})
            logger = logging.getLogger("export")

            try:
                rss_before = _get_process_rss_bytes(psutil_module)
                logger.info("Excel export start: sheets=%d rss_before=%s", len(sheets_data), str(rss_before))
            except Exception:
                pass

            fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
            os.close(fd)
            try:
                excel_export_module.create_excel_report(sheets_data, output_path=tmp_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise

            try:
                rss_after = _get_process_rss_bytes(psutil_module)
                logger.info("Excel export written to %s rss_after=%s", tmp_path, str(rss_after))
                try:
                    if (
                        rss_after
                        and trace_snapshot_threshold_mb
                        and (rss_after > trace_snapshot_threshold_mb * 1024 * 1024)
                    ):
                        snap_path = take_tracemalloc_snapshot(
                            "export_threshold",
                            {"sheets": len(sheets_data), "rss_after": rss_after},
                        )
                        if snap_path:
                            logger.warning(
                                "Tracemalloc snapshot written to %s due to export RSS %s",
                                snap_path,
                                rss_after,
                            )
                except Exception:
                    pass
            except Exception:
                pass

            filename = "warehouse-stats.xlsx"
            return FileResponse(
                tmp_path,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=filename,
                background=BackgroundTask(lambda: os.remove(tmp_path)),
            )
        except HTTPException:
            raise
        except Exception as exc:
            import traceback as _tb

            set_last_server_error(
                {
                    "ts": datetime.utcnow().isoformat(),
                    "path": "/export/excel",
                    "error": str(exc),
                    "trace": _tb.format_exc(),
                }
            )
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/export/engineer-deepdive")
    async def export_engineer_deepdive(request: Request, period: str = "this_week"):
        """Generate engineer deep-dive Excel export for a specific period (manager only)."""
        require_manager_or_admin(request)
        try:
            period = period.replace("-", "_")
            db_module.init_db()

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

            sheets_data = engineer_export.generate_engineer_deepdive_export(period)

            fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
            os.close(fd)
            try:
                excel_export_module.create_excel_report(sheets_data, output_path=tmp_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise

            period_label = period.replace("_", "-")
            filename = f"engineer-deepdive-{period_label}.xlsx"
            return FileResponse(
                tmp_path,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=filename,
                background=BackgroundTask(lambda: os.remove(tmp_path)),
            )
        except HTTPException:
            raise
        except Exception as exc:
            import traceback as _tb

            set_last_server_error(
                {
                    "ts": datetime.utcnow().isoformat(),
                    "path": "/export/engineer-deepdive",
                    "error": str(exc),
                    "trace": _tb.format_exc(),
                }
            )
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/export/qa-stats")
    async def export_qa_stats(
        request: Request,
        period: str = "this_week",
        include_device_sheets: str = "auto",
        start_year: int = None,
        start_month: int = None,
        end_year: int = None,
        end_month: int = None,
    ):
        """Generate QA stats Excel export for a specific period from MariaDB (manager only)."""
        require_manager_or_admin(request)
        try:
            period = period.replace("-", "_")
            db_module.init_db()

            def _build_cached_or_temp_response(tmp_path: str, *, filename: str, media_type: str, cache_key: str):
                if not qa_export_cache_enabled:
                    return FileResponse(
                        tmp_path,
                        media_type=media_type,
                        filename=filename,
                        background=BackgroundTask(lambda: os.remove(tmp_path)),
                    )

                cached_path = _store_cached_qa_export(
                    qa_export_cache_dir,
                    cache_key,
                    tmp_path,
                    filename=filename,
                    media_type=media_type,
                )

                if cached_path and os.path.exists(cached_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    logger.info("QA export cache store: key=%s file=%s", cache_key[:12], filename)
                    now_ts = datetime.utcnow().timestamp()
                    _cleanup_qa_cache(
                        qa_export_cache_dir,
                        now_ts=now_ts,
                        max_age_seconds=qa_export_cache_ttl_seconds,
                        max_entries=qa_export_cache_max_entries,
                    )
                    return FileResponse(
                        cached_path,
                        media_type=media_type,
                        filename=filename,
                    )

                return FileResponse(
                    tmp_path,
                    media_type=media_type,
                    filename=filename,
                    background=BackgroundTask(lambda: os.remove(tmp_path)),
                )

            def _parse_boolish(value: str | None) -> bool | None:
                if value is None:
                    return None
                raw = str(value).strip().lower()
                if raw in ("1", "true", "yes", "on"):
                    return True
                if raw in ("0", "false", "no", "off"):
                    return False
                return None

            async def _raise_if_disconnected() -> None:
                try:
                    if await request.is_disconnected():
                        raise HTTPException(status_code=499, detail="Client disconnected during QA export")
                except RuntimeError:
                    # Some test harnesses/request contexts do not support disconnection checks.
                    return

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
                raise HTTPException(status_code=400, detail=f"Invalid period. Must be one of: {', '.join(valid_periods)}")

            if period == "custom_range":
                if not all([start_year, start_month, end_year, end_month]):
                    raise HTTPException(
                        status_code=400,
                        detail="Custom range requires start_year, start_month, end_year, end_month",
                    )
                if start_month < 1 or start_month > 12 or end_month < 1 or end_month > 12:
                    raise HTTPException(status_code=400, detail="Month must be between 1 and 12")

            long_periods = [
                "this_month",
                "last_month",
                "this_year",
                "last_year",
                "last_year_h1",
                "last_year_h2",
                "custom_range",
            ]

            include_device_opt = _parse_boolish(include_device_sheets)
            if include_device_opt is None:
                include_device_opt = period in ("this_week", "last_week")

            cache_key_payload = {
                "route": "export/qa-stats",
                "period": period,
                "include_device_sheets": bool(include_device_opt),
                "start_year": start_year,
                "start_month": start_month,
                "end_year": end_year,
                "end_month": end_month,
            }
            cache_key = _qa_export_cache_key(cache_key_payload)
            if qa_export_cache_enabled:
                cached = _load_cached_qa_export(
                    qa_export_cache_dir,
                    cache_key,
                    qa_export_cache_ttl_seconds,
                )
                if cached and os.path.exists(cached["payload_path"]):
                    logger.info("QA export cache hit: key=%s file=%s", cache_key[:12], cached["filename"])
                    return FileResponse(
                        cached["payload_path"],
                        media_type=cached["media_type"],
                        filename=cached["filename"],
                    )
                logger.info("QA export cache miss: key=%s", cache_key[:12])

            await _raise_if_disconnected()

            if period in long_periods:
                chunks = qa_export.generate_qa_engineer_export_chunked(
                    period,
                    start_year=start_year,
                    start_month=start_month,
                    end_year=end_year,
                    end_month=end_month,
                    include_device_sheets=include_device_opt,
                )

                if len(chunks) == 1:
                    await _raise_if_disconnected()
                    suffix, sheets_data = chunks[0]
                    _ = suffix
                    fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
                    os.close(fd)
                    try:
                        excel_export_module.create_excel_report(sheets_data, output_path=tmp_path)
                    except Exception:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass
                        raise
                    period_label = period.replace("_", "-")
                    filename = f"qa-engineer-stats-{period_label}.xlsx"
                    return _build_cached_or_temp_response(
                        tmp_path,
                        filename=filename,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        cache_key=cache_key,
                    )

                period_label = period.replace("_", "-")
                fd_zip, tmp_zip_path = tempfile.mkstemp(suffix=".zip")
                os.close(fd_zip)
                try:
                    with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
                        for suffix, sheets_data in chunks:
                            await _raise_if_disconnected()
                            fd, tmp_xlsx = tempfile.mkstemp(suffix=".xlsx")
                            os.close(fd)
                            try:
                                excel_export_module.create_excel_report(sheets_data, output_path=tmp_xlsx)
                                excel_filename = f"qa-engineer-stats-{period_label}{suffix}.xlsx"
                                zip_file.write(tmp_xlsx, arcname=excel_filename)
                            finally:
                                try:
                                    os.remove(tmp_xlsx)
                                except Exception:
                                    pass
                    zip_filename = f"qa-engineer-stats-{period_label}-weekly.zip"
                    return _build_cached_or_temp_response(
                        tmp_zip_path,
                        filename=zip_filename,
                        media_type="application/zip",
                        cache_key=cache_key,
                    )
                except Exception:
                    try:
                        os.remove(tmp_zip_path)
                    except Exception:
                        pass
                    raise

            await _raise_if_disconnected()
            sheets_data = qa_export.generate_qa_engineer_export(
                period,
                start_year=start_year,
                start_month=start_month,
                end_year=end_year,
                end_month=end_month,
                include_device_sheets=include_device_opt,
            )

            fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
            os.close(fd)
            try:
                excel_export_module.create_excel_report(sheets_data, output_path=tmp_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise

            period_label = period.replace("_", "-")
            filename = f"qa-engineer-stats-{period_label}.xlsx"
            return _build_cached_or_temp_response(
                tmp_path,
                filename=filename,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                cache_key=cache_key,
            )
        except HTTPException:
            raise
        except Exception as exc:
            import traceback as _tb

            set_last_server_error(
                {
                    "ts": datetime.utcnow().isoformat(),
                    "path": "/export/qa-stats",
                    "error": str(exc),
                    "trace": _tb.format_exc(),
                }
            )
            raise HTTPException(status_code=500, detail=str(exc))

    return router
