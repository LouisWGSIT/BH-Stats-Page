import os
import sqlite3
from datetime import datetime, timedelta
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


def create_admin_backfill_router(
    *,
    require_admin: Callable[[Request], None],
    require_manager_or_admin: Callable[[Request], None],
    db_module,
    progress_state: dict,
) -> APIRouter:
    router = APIRouter()

    @router.post("/admin/backfill-local-erasures")
    async def admin_backfill_local_erasures(request: Request):
        """Admin-only backfill from erasures -> local_erasures."""
        require_admin(request)
        params = dict(request.query_params)
        try:
            days = int(params.get("days", 7))
        except Exception:
            days = 7
        try:
            limit = int(params.get("limit", 5000))
        except Exception:
            limit = 5000
        dry_run = str(params.get("dry_run", "false")).lower() in ("1", "true", "yes")

        db_path = db_module.DB_PATH
        add_local_erasure = db_module.add_local_erasure
        if not os.path.exists(db_path):
            return JSONResponse(status_code=500, content={"detail": f"DB not found at {db_path}"})

        if progress_state.get("running"):
            return JSONResponse(status_code=409, content={"detail": "Backfill already running"})

        now = datetime.utcnow()
        start = (now - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        q = (
            "SELECT id, job_id, system_serial, ts, device_type, initials FROM erasures "
            "WHERE event = 'success' AND ts >= ? ORDER BY ts ASC LIMIT ?"
        )
        try:
            cur.execute(q, (start, limit))
            rows = cur.fetchall()
        except Exception as exc:
            cur.close()
            conn.close()
            return JSONResponse(status_code=500, content={"detail": f"query failed: {exc}"})

        inserted = 0
        errors = []

        try:
            progress_state["running"] = True
            progress_state["total"] = len(rows)
            progress_state["processed"] = 0
            progress_state["percent"] = 0
            progress_state["last_updated"] = datetime.utcnow().isoformat()
            progress_state["errors"] = []
        except Exception:
            pass

        for idx, row in enumerate(rows):
            eid, job_id, system_serial, ts, device_type, initials = row
            jid = job_id if job_id else f"erasures-backfill-{eid}"
            payload = {"source": "erasures-backfill", "device_type": device_type, "initials": initials}
            if dry_run:
                try:
                    progress_state["processed"] = idx + 1
                    progress_state["percent"] = int((progress_state["processed"] / (progress_state["total"] or 1)) * 100)
                    progress_state["last_updated"] = datetime.utcnow().isoformat()
                except Exception:
                    pass
                continue
            try:
                add_local_erasure(
                    stockid=None,
                    system_serial=system_serial,
                    job_id=jid,
                    ts=ts,
                    warehouse=None,
                    source="erasures-backfill",
                    payload=payload,
                )
                inserted += 1
            except Exception as exc:
                errors.append(str(exc))
                try:
                    progress_state["errors"].append(str(exc))
                except Exception:
                    pass
            finally:
                try:
                    progress_state["processed"] = idx + 1
                    progress_state["percent"] = int((progress_state["processed"] / (progress_state["total"] or 1)) * 100)
                    progress_state["last_updated"] = datetime.utcnow().isoformat()
                except Exception:
                    pass

        cur.close()
        conn.close()
        try:
            progress_state["running"] = False
            progress_state["last_updated"] = datetime.utcnow().isoformat()
        except Exception:
            pass

        return JSONResponse(
            status_code=200,
            content={"rows_considered": len(rows), "inserted": inserted, "errors": errors, "dry_run": dry_run},
        )

    @router.get("/admin/backfill-status")
    def admin_backfill_status(request: Request):
        """Return current backfill status."""
        require_manager_or_admin(request)
        try:
            return dict(progress_state)
        except Exception:
            return progress_state

    return router
