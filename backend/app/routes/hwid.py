import json
import os
import logging
from datetime import datetime, UTC

import backend.request_context as request_context
from fastapi import APIRouter, HTTPException, Request


logger = logging.getLogger(__name__)


def _request_id(req: Request) -> str:
    try:
        rid = request_context.request_id.get()
        if rid:
            return str(rid)
    except Exception:
        pass
    return req.headers.get("x-request-id") or "n/a"


def _normalize_webhook_keys(webhook_api_keys: list[str] | None) -> list[str]:
    keys: list[str] = []
    for raw in webhook_api_keys or []:
        key = str(raw).strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def _is_authorized_hwid_request(req: Request, webhook_api_keys: list[str]) -> bool:
    api_header = req.headers.get("x-api-key")
    auth_header = req.headers.get("Authorization")
    provided = api_header or auth_header

    keys = _normalize_webhook_keys(webhook_api_keys)
    expected_values = set(keys)
    expected_values.update({f"Bearer {key}" for key in keys})

    is_authorized = bool(provided) and (provided in expected_values)
    if is_authorized:
        return True

    source = "x-api-key" if api_header else ("authorization" if auth_header else "none")
    configured_key_count = len(keys)
    preview = ""
    if provided:
        preview = str(provided)[:16]
        if len(str(provided)) > 16:
            preview += "..."

    logger.warning(
        "[HWID AUTH] Unauthorized /hwid rid=%s source=%s configured_keys=%s header_preview=%r client=%s",
        _request_id(req),
        source,
        configured_key_count,
        preview,
        (req.client.host if req.client else "unknown"),
    )
    return False


def create_hwid_router(*, webhook_api_keys: list[str], hwid_log_path: str) -> APIRouter:
    router = APIRouter()

    @router.get("/hwid")
    async def hwid_status():
        """Simple health check so a browser GET confirms the endpoint is alive."""
        return {
            "status": "ok",
            "endpoint": "/hwid",
            "method": "POST",
            "description": "HashID capture endpoint. Send POST with JSON body and x-api-key header.",
        }

    @router.post("/hwid")
    async def capture_hwid(req: Request):
        """
        Receives HWID data posted from a USB boot script.
        Validates x-api-key header, then appends the payload to a JSONL log file.
        """
        if not _is_authorized_hwid_request(req, webhook_api_keys):
            raise HTTPException(status_code=401, detail="Unauthorized")

        try:
            payload = await req.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        record = {
            "received_at": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
            "source_ip": req.client.host if req.client else "unknown",
            **payload,
        }

        logger.info(
            "HWID capture accepted rid=%s keys=%s source_ip=%s",
            _request_id(req),
            sorted(list(payload.keys())) if isinstance(payload, dict) else [],
            (req.client.host if req.client else "unknown"),
        )

        try:
            os.makedirs(os.path.dirname(hwid_log_path), exist_ok=True)
            with open(hwid_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to write log: {e}")

        return {"status": "ok", "saved_to": hwid_log_path}

    return router
