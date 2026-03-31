from datetime import datetime
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

    @router.get("/admin/connected-devices")
    async def admin_connected_devices(request: Request):
        require_admin(request)
        tokens = load_device_tokens()
        devices = []
        for token, info in tokens.items():
            try:
                expiry = datetime.fromisoformat(info.get("expiry"))
            except Exception:
                continue
            if datetime.now() > expiry:
                continue
            devices.append(
                {
                    "token": token,
                    "role": info.get("role"),
                    "name": info.get("name") or info.get("device_name") or None,
                    "created": info.get("created"),
                    "expiry": info.get("expiry"),
                    "user_agent": info.get("user_agent"),
                    "client_ip": info.get("last_client_ip") or info.get("client_ip"),
                    "client_ips": info.get("client_ips") or [],
                    "last_seen": info.get("last_seen"),
                    "locked": info.get("locked", False),
                }
            )
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

    @router.post("/admin/lock-device")
    async def admin_lock_device(request: Request):
        require_admin(request)
        try:
            body = await request.json()
            token = body.get("token")
            lock = bool(body.get("lock", True))
            if not token:
                raise HTTPException(status_code=400, detail="token required")
            tokens = load_device_tokens()
            if token not in tokens:
                raise HTTPException(status_code=404, detail="token not found")
            tokens[token]["locked"] = lock
            save_device_tokens(tokens)
            return {"token": token, "locked": lock}
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
