"""API endpoints to enqueue and check export jobs using RQ/Redis."""
import os
import logging
from fastapi import APIRouter, HTTPException

router = APIRouter()
logger = logging.getLogger("export_jobs")

REDIS_URL = os.getenv("REDIS_URL")
if REDIS_URL:
    try:
        import redis
        from rq import Queue
        redis_conn = redis.from_url(REDIS_URL)
        q = Queue("exports", connection=redis_conn)
    except Exception:
        redis_conn = None
        q = None
else:
    redis_conn = None
    q = None


@router.post("/export/qa-stats/start")
def start_export(period: str = "this_week"):
    """Enqueue an export job. Returns a job id to poll."""
    if not REDIS_URL or q is None:
        raise HTTPException(status_code=503, detail="REDIS_URL not configured. Set REDIS_URL to enable queued exports.")

    # Enqueue the worker_create_report function from export_worker
    try:
        job = q.enqueue("export_worker.worker_create_report", period, result_ttl=3600)
        return {"job_id": job.id}
    except Exception as e:
        logger.exception("Failed to enqueue job: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/qa-stats/status/{job_id}")
def export_status(job_id: str):
    """Return job status and any result/meta available."""
    if not REDIS_URL or redis_conn is None:
        raise HTTPException(status_code=503, detail="REDIS_URL not configured. Set REDIS_URL to enable queued exports.")

    try:
        from rq.job import Job
        job = Job.fetch(job_id, connection=redis_conn)
        resp = {"id": job.id, "status": job.get_status(), "meta": job.meta}
        if job.is_finished:
            resp["result"] = job.result
        if job.is_failed:
            resp["exc_info"] = str(job.exc_info)
        return resp
    except Exception as e:
        logger.exception("Failed to fetch job %s: %s", job_id, e)
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
