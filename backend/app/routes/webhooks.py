import os
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


def _to_initials(value: Any) -> str | None:
    cleaned = _clean_placeholder(value)
    if cleaned is None:
        return None

    text = str(cleaned).strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered in {"no user", "unknown", "unassigned", "none", "n/a", "na"}:
        return None

    # Already-initialized tokens like "SS", "BP", "JD".
    alpha_only = "".join(ch for ch in text if ch.isalpha())
    if 2 <= len(alpha_only) <= 4 and text.replace(" ", "").replace("-", "").replace("_", "").replace(".", "").isalpha():
        return alpha_only.upper()

    # Derive initials from names/usernames when full names are supplied.
    tokenized = text
    if "@" in tokenized:
        tokenized = tokenized.split("@", 1)[0]
    for sep in (".", "_", "-", "(", ")", "/", "\\"):
        tokenized = tokenized.replace(sep, " ")
    parts = [p for p in tokenized.split() if p]
    if len(parts) >= 2:
        initials = "".join(p[0] for p in parts if p and p[0].isalpha())
        if len(initials) >= 2:
            return initials[:4].upper()

    if len(alpha_only) >= 2:
        return alpha_only[:2].upper()
    return None


def _extract_initials_from_obj(obj: Any):
    if isinstance(obj, dict):
        for key in [
            "initials",
            "engineerInitials",
            "engineer_initials",
            "Engineer Initals",
            "Engineer Initials",
            "engineerInitals",
            "engineer",
            "username",
            "user",
            "operator",
            "technician",
            "startedBy",
            "createdBy",
        ]:
            derived = _to_initials(obj.get(key))
            if derived:
                return derived

    def deep(o: Any):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str):
                    lk = k.lower()
                    if any(term in lk for term in ("initial", "engineer", "operator", "technician", "username", "user")):
                        derived = _to_initials(v)
                        if derived:
                            return derived
                res = deep(v)
                if res:
                    return res
        elif isinstance(o, list):
            for item in o:
                res = deep(item)
                if res:
                    return res
        return None

    return deep(obj)


def _clean_placeholder(value):
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        upper = cleaned.upper()
        if cleaned.startswith("<REPORTPATH") or "<REPORTPATH" in cleaned:
            return None
        if "<SYSTEM_" in upper or "SYSTEM MANUFACTURER" in upper:
            return None
        return cleaned
    return value


def _extract_stockid_from_obj(obj: Any):
    """Best-effort extraction of stock/asset ID from varied payload shapes."""
    candidate_keys = [
        "stockid",
        "stock_id",
        "assetNumber",
        "assetStockId",
        "asset_stock_id",
        "assetTag",
        "asset_tag",
        "assetid",
        "asset_id",
        "Asset/Stock ID Number",
        "Asset/Stock ID",
    ]

    def _is_valid(v: Any) -> str | None:
        cleaned = _clean_placeholder(v)
        if cleaned is None:
            return None
        s = str(cleaned).strip()
        if not s:
            return None
        return s

    def _walk(o: Any):
        if isinstance(o, dict):
            for key in candidate_keys:
                if key in o:
                    found = _is_valid(o.get(key))
                    if found:
                        return found
            # Fallback: fuzzy key detection for variants like "asset stock id number".
            for k, v in o.items():
                lk = str(k).lower().replace("_", " ").replace("/", " ")
                if "stock" in lk and "id" in lk:
                    found = _is_valid(v)
                    if found:
                        return found
                if "asset" in lk and "id" in lk:
                    found = _is_valid(v)
                    if found:
                        return found
            for _, v in o.items():
                found = _walk(v)
                if found:
                    return found
        elif isinstance(o, list):
            for item in o:
                found = _walk(item)
                if found:
                    return found
        return None

    return _walk(obj)


def create_webhooks_router(*, db_module, webhook_api_key: str) -> APIRouter:
    router = APIRouter()

    @router.post("/api/ingest/local-erasure")
    async def ingest_local_erasure(request: Request):
        try:
            raw_body = await request.body()
            body = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid JSON"})

        ingestion_secret = os.getenv("INGESTION_SECRET")
        if ingestion_secret:
            import hashlib
            import hmac

            sig_header = (
                request.headers.get("X-Signature")
                or request.headers.get("X-Hub-Signature-256")
                or request.headers.get("X-Hub-Signature")
                or request.headers.get("x-signature")
                or request.headers.get("x-hub-signature-256")
                or request.headers.get("x-hub-signature")
            )
            if not sig_header:
                return JSONResponse(status_code=401, content={"detail": "Missing signature header"})
            recv_hex = sig_header.split("=", 1)[1] if sig_header.startswith("sha256=") else sig_header
            try:
                expected = hmac.new(ingestion_secret.encode("utf-8"), raw_body or b"", hashlib.sha256).hexdigest()
            except Exception:
                return JSONResponse(status_code=500, content={"detail": "HMAC computation failed"})
            if not hmac.compare_digest(expected, recv_hex):
                return JSONResponse(status_code=401, content={"detail": "Invalid signature"})
        else:
            ingestion_key = os.getenv("INGESTION_KEY")
            if not ingestion_key:
                return JSONResponse(status_code=403, content={"detail": "Ingestion not configured on server"})
            auth_header = request.headers.get("Authorization", "")
            bearer = auth_header[7:] if auth_header.startswith("Bearer ") else None
            header_key = request.headers.get("X-INGESTION-KEY") or request.headers.get("x-ingestion-key")
            if (bearer != ingestion_key) and (header_key != ingestion_key):
                return JSONResponse(status_code=401, content={"detail": "Invalid ingestion key"})

        stockid = body.get("stockid") or body.get("stock_id") or body.get("assetNumber") or body.get("assetTag")
        if not stockid:
            stockid = _extract_stockid_from_obj(body)
        system_serial = body.get("system_serial") or body.get("systemSerial")
        job_id = body.get("job_id") or body.get("jobId")
        ts = body.get("ts") or body.get("timestamp")
        warehouse = body.get("warehouse")
        source = body.get("source") or "ingest"
        payload = body.get("payload") or body

        try:
            db_module.add_local_erasure(
                stockid=stockid,
                system_serial=system_serial,
                job_id=job_id,
                ts=ts,
                warehouse=warehouse,
                source=source,
                payload=payload,
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            return JSONResponse(status_code=500, content={"detail": f"failed to insert: {e}"})

        return JSONResponse(status_code=200, content={"ok": True, "inserted": True})

    @router.post("/hooks/erasure")
    async def erasure_hook(req: Request):
        hdr = req.headers.get("Authorization") or req.headers.get("x-api-key")
        if not hdr or (hdr != f"Bearer {webhook_api_key}" and hdr != webhook_api_key):
            raise HTTPException(status_code=401, detail="Unauthorized")

        payload = await req.json()
        event = payload.get("event", "success")
        job_id = payload.get("jobId") or payload.get("assetTag") or payload.get("id") or "unknown"
        print(f"Received webhook: event={event}, jobId={job_id}, payload={payload}")

        if job_id != "unknown" and db_module.is_job_seen(job_id):
            return JSONResponse({"status": "ignored", "reason": "duplicate"})

        if event in ["success", "connected"]:
            db_module.increment_stat("erased", 1)
            if job_id != "unknown":
                db_module.mark_job_seen(job_id)
            stats = db_module.get_daily_stats()
            return {"status": "ok", "count": stats["erased"]}
        if event == "failure":
            return {"status": "ok"}
        db_module.increment_stat("erased", 1)
        if job_id != "unknown":
            db_module.mark_job_seen(job_id)
        stats = db_module.get_daily_stats()
        return {"status": "ok", "event_accepted": event, "count": stats["erased"]}

    @router.api_route("/hooks/erasure-detail", methods=["GET", "POST"])
    async def erasure_detail(req: Request):
        hdr = req.headers.get("Authorization") or req.headers.get("x-api-key")
        if not hdr or (hdr != f"Bearer {webhook_api_key}" and hdr != webhook_api_key):
            raise HTTPException(status_code=401, detail="Unauthorized")

        payload: Dict[str, Any] = {}
        try:
            payload = await req.json()
            if not isinstance(payload, dict):
                payload = {"_body": payload}
        except Exception:
            try:
                raw = await req.body()
                text = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
                import json as _json
                from urllib.parse import parse_qs

                try:
                    payload = _json.loads(text)
                except Exception:
                    qs = parse_qs(text)
                    payload = {k: v[0] for k, v in qs.items()} if qs else {"_raw": text}
            except Exception:
                payload = {}

        if req.query_params:
            payload = {**payload, **dict(req.query_params)}

        print("[WEBHOOK DEBUG] Full payload received:")
        print(f"  Headers: Content-Type={req.headers.get('content-type', '')}")
        print(f"  Payload keys: {list(payload.keys())}")
        print(f"  Full payload: {payload}")

        event = (payload.get("event") or "success").strip().lower()
        job_id = payload.get("jobId") or payload.get("assetTag") or payload.get("id")
        device_type = (payload.get("deviceType") or payload.get("device_type") or payload.get("type") or "laptops_desktops").strip().lower()
        initials_raw = payload.get("initials") or payload.get("Engineer Initals") or payload.get("Engineer Initials") or ""
        initials = (initials_raw or "").strip().upper() or None

        duration_sec = _clean_placeholder(payload.get("durationSec") or payload.get("duration"))
        try:
            if isinstance(duration_sec, str) and ":" in duration_sec:
                parts = duration_sec.split(":")
                if len(parts) == 3:
                    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                    duration_sec = h * 3600 + m * 60 + s
                else:
                    duration_sec = None
            else:
                duration_sec = int(duration_sec) if duration_sec is not None else None
        except Exception:
            duration_sec = None

        error_type = payload.get("errorType") or payload.get("error")
        ts_in = payload.get("timestamp")
        ts = None
        if isinstance(ts_in, (int, float)):
            try:
                ts = datetime.fromtimestamp(float(ts_in), tz=timezone.utc).isoformat()
            except Exception:
                ts = None
        elif isinstance(ts_in, str) and ts_in.strip():
            s = ts_in.strip()
            try:
                if s.endswith("Z"):
                    s = s.replace("Z", "+00:00")
                try:
                    ts = datetime.fromisoformat(s).isoformat()
                except Exception:
                    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                        try:
                            ts = datetime.strptime(s, fmt).isoformat()
                            break
                        except Exception:
                            continue
            except Exception:
                ts = None

        if job_id and db_module.is_job_seen(job_id):
            return {"status": "ignored", "reason": "duplicate"}

        manufacturer = _clean_placeholder(payload.get("manufacturer"))
        model = _clean_placeholder(payload.get("model"))
        system_serial = _clean_placeholder(
            payload.get("system_serial")
            or payload.get("systemSerial")
            or payload.get("system-serial")
            or payload.get("systemSerialNumber")
            or payload.get("serial")
        ) or ""
        disk_serial = _clean_placeholder(
            payload.get("disk_serial")
            or payload.get("diskSerial")
            or payload.get("disk-serial")
            or payload.get("diskSerialNumber")
        ) or ""
        disk_capacity = _clean_placeholder(
            payload.get("disk_capacity")
            or payload.get("diskCapacity")
            or payload.get("drive_size")
            or payload.get("driveSize")
        ) or ""

        if isinstance(disk_capacity, str):
            try:
                disk_capacity = int(float(disk_capacity))
            except Exception:
                pass

        if manufacturer or model:
            print(f"[DEVICE DETAILS] Captured from payload: manufacturer={manufacturer}, model={model}")

        db_module.add_erasure_event(
            event=event,
            device_type=device_type,
            initials=initials,
            duration_sec=duration_sec,
            error_type=error_type,
            job_id=job_id,
            ts=ts,
            manufacturer=manufacturer,
            model=model,
            system_serial=system_serial,
            disk_serial=disk_serial,
            disk_capacity=disk_capacity,
        )
        # Keep local erasure feed in sync with detailed erasure hook so downstream
        # "awaiting QA" comparators always have a recent erasure timestamp to compare.
        try:
            stockid = _clean_placeholder(
                payload.get("stockid")
                or payload.get("stock_id")
                or payload.get("assetNumber")
                or payload.get("assetTag")
            )
            if not stockid:
                stockid = _extract_stockid_from_obj(payload)
            db_module.add_local_erasure(
                stockid=stockid,
                system_serial=system_serial,
                job_id=job_id,
                ts=ts,
                warehouse=_clean_placeholder(payload.get("warehouse")),
                source="erasure-detail",
                payload={
                    "event": event,
                    "device_type": device_type,
                    "initials": initials,
                    "job_id": job_id,
                    "stockid": stockid,
                    "assetNumber": _clean_placeholder(payload.get("assetNumber")),
                    "system_serial": system_serial,
                },
            )
        except Exception:
            pass
        try:
            dbg = db_module.get_summary_today_month()
            print(
                f"erasure-detail wrote event={event} type={device_type} jobId={job_id} -> "
                f"todayTotal={dbg.get('todayTotal')} avg={dbg.get('avgDurationSec')}"
            )
        except Exception as _e:
            print(f"erasure-detail post-insert check failed: {_e}")

        if event in ["success", "connected"]:
            db_module.increment_stat("erased", 1)
            if initials:
                try:
                    # Keep engineer-level rollups live in step with detailed ingest.
                    db_module.increment_engineer_count(initials, 1)
                    db_module.increment_engineer_type_count(device_type, initials, 1)
                except Exception as _e:
                    print(f"erasure-detail engineer counter update failed: {_e}")
        if job_id:
            db_module.mark_job_seen(job_id)

        return {"status": "ok"}

    @router.api_route("/hooks/engineer-erasure", methods=["GET", "POST"])
    async def engineer_erasure_hook(req: Request):
        hdr = req.headers.get("Authorization") or req.headers.get("x-api-key")
        if not hdr or (hdr != f"Bearer {webhook_api_key}" and hdr != webhook_api_key):
            raise HTTPException(status_code=401, detail="Unauthorized")

        payload: Dict[str, Any] = {}
        try:
            payload = await req.json()
            if not isinstance(payload, dict):
                payload = {"_body": payload}
        except Exception:
            payload = {}
        if req.query_params:
            payload = {**payload, **dict(req.query_params)}

        initials = _extract_initials_from_obj(payload) or ""
        device_type = (payload.get("deviceType") or payload.get("device_type") or payload.get("type") or "laptops_desktops").strip().lower()
        print(f"Received engineer erasure: initials={initials}, payload={payload}")

        if not initials:
            return JSONResponse({"status": "error", "reason": "missing initials"}, status_code=400)

        try:
            job_id = payload.get("jobId") or payload.get("assetTag") or payload.get("id") or None
            duration = payload.get("durationSec") or payload.get("duration") or None
            ts_in = payload.get("timestamp") or payload.get("ts") or None
            ts = None
            if isinstance(ts_in, (int, float)):
                try:
                    ts = datetime.fromtimestamp(float(ts_in), tz=timezone.utc).isoformat()
                except Exception:
                    ts = None
            elif isinstance(ts_in, str) and ts_in.strip():
                ts = ts_in
            try:
                db_module.add_erasure_event(
                    event="success",
                    device_type=device_type,
                    initials=initials,
                    duration_sec=(int(duration) if duration is not None and str(duration).isdigit() else None),
                    job_id=job_id,
                    ts=ts,
                )
            except Exception as _e:
                print(f"[engineer_erasure] failed to add detailed erasure event: {_e}")

            db_module.increment_stat("erased", 1)
            if job_id:
                try:
                    db_module.mark_job_seen(job_id)
                except Exception:
                    pass
            db_module.increment_engineer_count(initials, 1)
            db_module.increment_engineer_type_count(device_type, initials, 1)
        except Exception as e:
            print(f"[engineer_erasure] error updating counts: {e}")
        engineers = db_module.get_top_engineers(limit=10)
        engineer_count = next((e["count"] for e in engineers if e["initials"] == initials), 0)

        return {"status": "ok", "engineer": initials, "count": engineer_count}

    return router
