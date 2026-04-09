import hashlib
from datetime import UTC, datetime
from typing import Callable

from fastapi import APIRouter, HTTPException, Request


def create_admin_devices_router(
    *,
    require_admin: Callable[[Request], None],
    require_manager_or_admin: Callable[[Request], None],
    load_device_tokens: Callable[[], dict],
    save_device_tokens: Callable[[dict], None],
    get_last_server_error: Callable[[], object | None],
) -> APIRouter:
    router = APIRouter()

    def _parse_iso_utc(value: object | None) -> datetime | None:
        if value is None:
            return None
        try:
            raw = str(value).strip()
            if not raw:
                return None
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except Exception:
            return None

    def _device_fingerprint(token: str, info: dict) -> str:
        explicit = str(info.get("fingerprint") or "").strip().lower()
        if explicit:
            return explicit

        token_part = ""
        if ":" in token:
            candidate = token.rsplit(":", 1)[-1].strip().lower()
            if len(candidate) >= 8 and all(ch in "0123456789abcdef" for ch in candidate):
                token_part = candidate
        if token_part:
            return token_part

        # Fallback heuristic when legacy tokens have no explicit fingerprint segment.
        ua = str(info.get("user_agent") or "")
        ip = str(info.get("last_client_ip") or info.get("client_ip") or "")
        return hashlib.sha256(f"{ua}:{ip}".encode("utf-8")).hexdigest()[:16]

    @router.get("/admin/connected-devices")
    async def admin_connected_devices(request: Request):
        require_admin(request)
        tokens = load_device_tokens()
        devices = []
        now_utc = datetime.now(UTC)
        to_prune: set[str] = set()
        kept_by_key: dict[str, tuple[datetime, datetime, str]] = {}

        for token, info in tokens.items():
            try:
                raw_expiry = str(info.get("expiry", "")).strip()
                if raw_expiry.endswith("Z"):
                    raw_expiry = raw_expiry[:-1] + "+00:00"
                expiry = datetime.fromisoformat(raw_expiry)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)
                expiry = expiry.astimezone(UTC)
            except Exception:
                to_prune.add(token)
                continue

            if now_utc > expiry:
                to_prune.add(token)
                continue

            role = str(info.get("role") or "viewer").strip().lower() or "viewer"
            fingerprint = _device_fingerprint(token, info)
            dedupe_key = f"{role}:{fingerprint}"
            last_seen_dt = _parse_iso_utc(info.get("last_seen")) or _parse_iso_utc(info.get("created")) or now_utc
            created_dt = _parse_iso_utc(info.get("created")) or last_seen_dt

            existing = kept_by_key.get(dedupe_key)
            if existing is not None:
                existing_last_seen, existing_created, existing_token = existing
                if (last_seen_dt, created_dt) <= (existing_last_seen, existing_created):
                    to_prune.add(token)
                    continue
                to_prune.add(existing_token)

            kept_by_key[dedupe_key] = (last_seen_dt, created_dt, token)
            devices.append(
                {
                    "token": token,
                    "role": role,
                    "name": info.get("name") or info.get("device_name") or None,
                    "created": info.get("created"),
                    "expiry": info.get("expiry"),
                    "user_agent": info.get("user_agent"),
                    "client_ip": info.get("last_client_ip") or info.get("client_ip"),
                    "client_ips": info.get("client_ips") or [],
                    "last_seen": info.get("last_seen"),
                    "device_id": fingerprint[:8],
                }
            )

        if to_prune:
            for token in to_prune:
                tokens.pop(token, None)
            try:
                save_device_tokens(tokens)
            except Exception:
                pass

            devices = [d for d in devices if d.get("token") not in to_prune]

        devices.sort(key=lambda d: d.get("last_seen") or "", reverse=True)
        return {"devices": devices}

    @router.get("/admin/last-error")
    def admin_last_error(request: Request):
        require_admin(request)
        try:
            last_error = get_last_server_error()
            if last_error is None:
                return {"found": False, "message": "No recent server error recorded"}
            return {"found": True, "error": last_error}
        except Exception as exc:
            return {"found": True, "error": {"error": str(exc)}}

    @router.get("/manager/last-error")
    def manager_last_error(request: Request):
        require_manager_or_admin(request)
        try:
            last_error = get_last_server_error()
            if last_error is None:
                return {"found": False, "message": "No recent server error recorded"}
            return {"found": True, "error": last_error}
        except Exception as exc:
            return {"found": True, "error": {"error": str(exc)}}

    @router.post("/admin/revoke-device")
    async def admin_revoke_device(request: Request):
        require_admin(request)
        try:
            body = await request.json()
            token = body.get("token")
            if not token:
                raise HTTPException(status_code=400, detail="token required")
            tokens = load_device_tokens()
            if token in tokens:
                del tokens[token]
                save_device_tokens(tokens)
            return {"revoked": True}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/admin/set-device-name")
    async def admin_set_device_name(request: Request):
        require_admin(request)
        try:
            body = {}
            try:
                body = await request.json()
            except Exception:
                body = {}
            token = body.get("token")
            name = body.get("name")
            if not token:
                raise HTTPException(status_code=400, detail="token required")
            tokens = load_device_tokens()
            if token not in tokens:
                raise HTTPException(status_code=404, detail="token not found")
            tokens[token]["name"] = name or None
            save_device_tokens(tokens)
            return {"token": token, "name": tokens[token].get("name")}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return router
