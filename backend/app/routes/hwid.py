import json
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request


def create_hwid_router(*, webhook_api_key: str, hwid_log_path: str) -> APIRouter:
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
        hdr = req.headers.get("x-api-key") or req.headers.get("Authorization")
        if not hdr or (hdr != webhook_api_key and hdr != f"Bearer {webhook_api_key}"):
            raise HTTPException(status_code=401, detail="Unauthorized")

        try:
            payload = await req.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        record = {
            "received_at": datetime.utcnow().isoformat() + "Z",
            "source_ip": req.client.host if req.client else "unknown",
            **payload,
        }

        try:
            os.makedirs(os.path.dirname(hwid_log_path), exist_ok=True)
            with open(hwid_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to write log: {e}")

        return {"status": "ok", "saved_to": hwid_log_path}

    return router
