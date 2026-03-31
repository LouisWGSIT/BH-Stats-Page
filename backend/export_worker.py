"""Worker wrapper for export jobs (RQ worker compatible).

This module exposes `worker_create_report` which can be enqueued by an RQ
worker. It uses `qa_export.generate_qa_export()` to build sheets and
`excel_export.create_excel_report()` to render a workbook. If S3
environment variables are present the worker will upload the file to S3 and
return a presigned URL; otherwise it returns a local `/tmp` path.
"""
import os
import uuid
import tempfile
import logging
from typing import Optional
from rq import get_current_job

logger = logging.getLogger("export_worker")

try:
    import boto3
    boto3_available = True
except Exception:
    boto3_available = False

import backend.qa_export as qa_export
import backend.excel_export as excel_export


def _upload_to_s3(local_path: str, key: str, expires: int = 3600) -> Optional[str]:
    bucket = os.getenv("S3_BUCKET") or os.getenv("AWS_S3_BUCKET")
    if not bucket or not boto3_available:
        return None
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION") or None,
    )
    try:
        s3.upload_file(local_path, bucket, key)
        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires,
        )
        return url
    except Exception as e:
        logger.exception("S3 upload failed: %s", e)
        return None


def worker_create_report(period: str = "this_week", write_mode: Optional[str] = None, batch_size: Optional[int] = None) -> dict:
    """RQ worker entry point.

    Returns a dict with `status` and either `url` (S3) or `path` (local).
    """
    job = get_current_job()

    def _progress(pct: int, msg: str | None = None):
        if job:
            meta = job.meta or {}
            meta['progress'] = {'pct': pct, 'msg': msg}
            job.meta = meta
            try:
                job.save_meta()
            except Exception:
                pass

    logger.info("worker_create_report start: period=%s write_mode=%s batch_size=%s", period, write_mode, batch_size)

    try:
        sheets = qa_export.generate_qa_export(period)

        # Choose a temporary filename
        uid = uuid.uuid4().hex[:8]
        fname = f"qa-engineer-stats-{period}-{uid}.xlsx"
        tmpdir = tempfile.gettempdir()
        out_path = os.path.join(tmpdir, fname)

        # Render workbook to file (create_excel_report supports output_path)
        excel_export.create_excel_report(sheets, output_path=out_path)

        # Try S3 upload if configured
        s3_key = f"exports/{fname}"
        s3_url = _upload_to_s3(out_path, s3_key) if boto3_available else None

        result = {
            'status': 'finished',
            'file_path': out_path,
            'bytes': os.path.getsize(out_path) if os.path.exists(out_path) else None,
        }
        if s3_url:
            result['url'] = s3_url

        logger.info("worker_create_report complete: %s", result)
        return result
    except Exception as e:
        logger.exception("worker_create_report failed: %s", e)
        return {'status': 'failed', 'error': str(e)}
