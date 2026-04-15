import os
import re
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


def _normalize_webhook_keys(webhook_api_keys: list[str] | None) -> list[str]:
    keys: list[str] = []
    for raw in webhook_api_keys or []:
        key = str(raw).strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def _is_authorized_webhook_request(req: Request, webhook_api_keys: list[str], *, route_label: str) -> bool:
    auth_header = req.headers.get("Authorization")
    api_header = req.headers.get("x-api-key")
    provided = auth_header or api_header

    keys = _normalize_webhook_keys(webhook_api_keys)
    expected_values = set(keys)
    expected_values.update({f"Bearer {key}" for key in keys})

    is_authorized = bool(provided) and (provided in expected_values)
    if is_authorized:
        return True

    # Intentionally avoid logging secrets; only report source/header shape.
    source = "authorization" if auth_header else ("x-api-key" if api_header else "none")
    configured_key_count = len(keys)
    preview = ""
    if provided:
        preview = str(provided)[:16]
        if len(str(provided)) > 16:
            preview += "..."

    print(
        f"[WEBHOOK AUTH] Unauthorized {route_label}: source={source}, "
        f"configured_keys={configured_key_count}, header_preview={preview!r}, "
        f"client={(req.client.host if req.client else 'unknown')}"
    )
    return False


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


def _normalize_serial_value(value: Any) -> str:
    cleaned = _clean_placeholder(value)
    if cleaned is None:
        return ""
    text = str(cleaned).strip()
    if not text:
        return ""
    upper = text.upper()
    if upper.startswith("SERIAL:"):
        return text.split(":", 1)[1].strip()
    return text


def _normalize_key_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _extract_clean_from_obj(obj: Any, candidate_keys: list[str], *, allow_leaf_match: bool = True):
    """Best-effort deep extraction for values that may be nested or flattened with dotted keys."""
    wanted_paths = {_normalize_key_token(k) for k in (candidate_keys or []) if k}
    wanted_leafs = {_normalize_key_token(str(k).split(".")[-1]) for k in (candidate_keys or []) if k}

    def _walk(node: Any, path_parts: list[str]):
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k)
                key_parts = [p for p in key.split(".") if p]
                next_path = [*path_parts, *key_parts]

                path_norm = _normalize_key_token("".join(next_path))
                leaf_norm = _normalize_key_token(next_path[-1]) if next_path else ""

                if path_norm in wanted_paths or (allow_leaf_match and leaf_norm in wanted_leafs):
                    cleaned = _clean_placeholder(v)
                    if cleaned is not None:
                        return cleaned

                nested = _walk(v, next_path)
                if nested is not None:
                    return nested
        elif isinstance(node, list):
            for item in node:
                nested = _walk(item, path_parts)
                if nested is not None:
                    return nested
        return None

    return _walk(obj, [])


def _extract_stockid_from_obj(obj: Any):
    """Best-effort extraction of stock/asset ID from varied payload shapes."""
    candidate_keys = [
        "stockid",
        "stock_id",
        "stock id",
        "assetNumber",
        "assetnumber",
        "asset_number",
        "asset number",
        "assetNo",
        "asset_no",
        "asset no",
        "assetStockId",
        "assetstockid",
        "asset stock id",
        "assetstockidnumber",
        "asset_stock_id",
        "assetTag",
        "asset_tag",
        "asset tag",
        "assetid",
        "asset_id",
        "asset id",
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
                if "asset" in lk and "number" in lk:
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


def _collect_asset_like_keys(obj: Any) -> list[str]:
    """Collect key paths related to asset/stock identifiers for debug visibility."""
    hits: list[str] = []

    def _walk(node: Any, path: list[str]):
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k)
                next_path = [*path, key]
                lk = key.lower().replace("_", " ").replace("/", " ")
                if any(term in lk for term in ("asset", "stock", "tag", "id", "number")):
                    joined = ".".join(next_path)
                    if joined not in hits:
                        hits.append(joined)
                _walk(v, next_path)
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                _walk(item, [*path, str(idx)])

    _walk(obj, [])
    return hits[:50]


def create_webhooks_router(*, db_module, webhook_api_keys: list[str]) -> APIRouter:
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
        if not _is_authorized_webhook_request(req, webhook_api_keys, route_label="/hooks/erasure"):
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
        if not _is_authorized_webhook_request(req, webhook_api_keys, route_label="/hooks/erasure-detail"):
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
        try:
            asset_like_keys = _collect_asset_like_keys(payload)
            print(f"  Asset-like keys discovered: {asset_like_keys}")
        except Exception:
            pass

        event = (payload.get("event") or "success").strip().lower()
        job_id = payload.get("jobId") or payload.get("assetTag") or payload.get("id")
        device_type = (payload.get("deviceType") or payload.get("device_type") or payload.get("type") or "laptops_desktops").strip().lower()
        initials_raw = payload.get("initials") or payload.get("Engineer Initals") or payload.get("Engineer Initials") or ""
        initials = (initials_raw or "").strip().upper() or None

        duration_sec = _clean_placeholder(
            payload.get("durationSec")
            or payload.get("duration")
            or payload.get("durationSecAlt")
            or payload.get("duration_alt")
            or payload.get("durationAlt")
        )
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
        ts_in = (
            payload.get("timestamp")
            or payload.get("timestampAlt")
            or payload.get("timestamp_alt")
            or payload.get("completionTime")
            or payload.get("end_time")
        )
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

        manufacturer = _clean_placeholder(
            payload.get("manufacturer")
            or payload.get("manufacturerAlt")
            or payload.get("manufacturer_alt")
            or payload.get("systemManufacturer")
            or payload.get("system_manufacturer")
        ) or _extract_clean_from_obj(
            payload,
            [
                "manufacturer",
                "system.manufacturer",
                "blancco_data.blancco_hardware_report.system.manufacturer",
                "blancco_data.blancco_hardware_report.entries.system.manufacturer",
            ],
        )
        model = _clean_placeholder(
            payload.get("model")
            or payload.get("modelAlt")
            or payload.get("model_alt")
            or payload.get("systemModel")
            or payload.get("system_model")
            or payload.get("name")
            or payload.get("market_name")
        ) or _extract_clean_from_obj(
            payload,
            [
                "model",
                "name",
                "market_name",
                "system.model",
                "blancco_data.blancco_hardware_report.system.model",
                "blancco_data.blancco_hardware_report.entries.system.model",
                "blancco_data.blancco_hardware_report.entries.system.name",
                "blancco_data.blancco_hardware_report.entries.system.market_name",
            ],
        )
        system_serial = _normalize_serial_value(
            payload.get("system_serial")
            or payload.get("systemSerial")
            or payload.get("system-serial")
            or payload.get("systemSerialNumber")
            or payload.get("serialAlt")
            or payload.get("serial_alt")
            or payload.get("systemIdentifier")
            or payload.get("identifier")
            or payload.get("imei")
            or payload.get("serial")
        ) or _normalize_serial_value(_extract_clean_from_obj(
            payload,
            [
                "system_serial",
                "systemSerial",
                "system.serial",
                "identifier",
                "imei",
                "blancco_data.blancco_hardware_report.system.serial",
                "blancco_data.blancco_hardware_report.entries.system.serial",
                "blancco_data.blancco_hardware_report.entries.system.identifier",
                "serial",
            ],
            allow_leaf_match=False,
        )) or ""
        disk_serial = _clean_placeholder(
            payload.get("disk_serial")
            or payload.get("diskSerial")
            or payload.get("disk-serial")
            or payload.get("diskSerialNumber")
            or payload.get("diskSerialAlt")
            or payload.get("disk_serial_alt")
            or payload.get("erasureTargetSerial")
        ) or _extract_clean_from_obj(
            payload,
            [
                "disk_serial",
                "diskSerial",
                "disk.serial",
                "target.serial",
                "blancco_data.blancco_hardware_report.disks.disk.serial",
                "blancco_data.blancco_hardware_report.entries.disks.disk.serial",
                "blancco_data.blancco_erasure_report.erasures.erasure.target.serial",
            ],
            allow_leaf_match=False,
        ) or ""
        disk_capacity = _clean_placeholder(
            payload.get("disk_capacity")
            or payload.get("diskCapacity")
            or payload.get("drive_size")
            or payload.get("driveSize")
            or payload.get("diskCapacityAlt")
            or payload.get("disk_capacity_alt")
            or payload.get("erasureTargetCapacity")
        ) or _extract_clean_from_obj(
            payload,
            [
                "disk_capacity",
                "diskCapacity",
                "drive_size",
                "driveSize",
                "target.capacity",
                "disks.disk.capacity",
                "blancco_data.blancco_hardware_report.disks.disk.capacity",
                "blancco_data.blancco_hardware_report.entries.disks.disk.capacity",
                "blancco_data.blancco_erasure_report.erasures.erasure.target.capacity",
            ],
            allow_leaf_match=False,
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
                or payload.get("stock id")
                or payload.get("assetNumber")
                or payload.get("assetnumber")
                or payload.get("asset_number")
                or payload.get("asset number")
                or payload.get("assetTag")
            )
            if not stockid:
                stockid = _extract_stockid_from_obj(payload)
            if not stockid:
                print("[WEBHOOK DEBUG] No stock/asset ID resolved from payload (including alias scan).")
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
        if not _is_authorized_webhook_request(req, webhook_api_keys, route_label="/hooks/engineer-erasure"):
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
