import logging
import os
import tempfile
import zipfile
from datetime import datetime
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

import backend.engineer_export as engineer_export
import backend.qa_export as qa_export


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

            if period in long_periods:
                chunks = qa_export.generate_qa_engineer_export_chunked(
                    period,
                    start_year=start_year,
                    start_month=start_month,
                    end_year=end_year,
                    end_month=end_month,
                )

                if len(chunks) == 1:
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
                    return FileResponse(
                        tmp_path,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        filename=filename,
                        background=BackgroundTask(lambda: os.remove(tmp_path)),
                    )

                period_label = period.replace("_", "-")
                fd_zip, tmp_zip_path = tempfile.mkstemp(suffix=".zip")
                os.close(fd_zip)
                try:
                    with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
                        for suffix, sheets_data in chunks:
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
                    return FileResponse(
                        tmp_zip_path,
                        media_type="application/zip",
                        filename=zip_filename,
                        background=BackgroundTask(lambda: os.remove(tmp_zip_path)),
                    )
                except Exception:
                    try:
                        os.remove(tmp_zip_path)
                    except Exception:
                        pass
                    raise

            sheets_data = qa_export.generate_qa_engineer_export(
                period,
                start_year=start_year,
                start_month=start_month,
                end_year=end_year,
                end_month=end_month,
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
                    "path": "/export/qa-stats",
                    "error": str(exc),
                    "trace": _tb.format_exc(),
                }
            )
            raise HTTPException(status_code=500, detail=str(exc))

    return router
