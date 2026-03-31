from typing import Callable

from fastapi import APIRouter, HTTPException, Request


def create_admin_maintenance_router(
    *,
    require_admin: Callable[[Request], None],
    db_module,
    take_tracemalloc_snapshot: Callable[[str, dict | None], str | None],
) -> APIRouter:
    router = APIRouter()

    @router.post("/admin/delete-event")
    async def admin_delete_event(req: Request):
        """Delete an ingested event by jobId (admin only)."""
        require_admin(req)

        body = {}
        try:
            body = await req.json()
        except Exception:
            pass
        job_id = (body.get("jobId") if isinstance(body, dict) else None) or req.query_params.get("jobId")
        if not job_id:
            raise HTTPException(status_code=400, detail="jobId is required")

        deleted = db_module.delete_event_by_job(job_id)
        summary = db_module.get_summary_today_month()
        return {"deleted": deleted, "jobId": job_id, "summary": summary}

    @router.post("/admin/memory-snapshot")
    async def admin_memory_snapshot(req: Request):
        """Trigger a tracemalloc snapshot and return path (admin only)."""
        require_admin(req)
        body = {}
        try:
            body = await req.json()
        except Exception:
            body = {}
        reason = (body.get("reason") if isinstance(body, dict) else None) or req.query_params.get("reason") or "manual"
        meta = {}
        try:
            meta = body.get("meta") if isinstance(body, dict) else {}
        except Exception:
            meta = {}
        path = take_tracemalloc_snapshot(reason, meta)
        if path:
            return {"status": "ok", "path": path}
        raise HTTPException(status_code=500, detail="tracemalloc not available or snapshot failed")

    return router
