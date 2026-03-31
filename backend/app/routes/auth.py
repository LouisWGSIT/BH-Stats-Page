from datetime import datetime, timedelta
import hashlib
import secrets
from typing import Callable

from fastapi import APIRouter, HTTPException, Request


def create_auth_router(
    *,
    admin_password: str,
    manager_password: str,
    device_token_expiry_days: int,
    get_client_ip: Callable[[Request], str],
    get_client_ips: Callable[[Request], list[str]],
    is_local_network: Callable[[str], bool],
    is_device_token_valid: Callable[[str], bool],
    load_device_tokens: Callable[[], dict],
    save_device_tokens: Callable[[dict], None],
    touch_device_token: Callable[[str, list[str], str], None],
    generate_device_token: Callable[[str, str], str],
) -> APIRouter:
    router = APIRouter()

    @router.get("/auth/status")
    async def auth_status(request: Request):
        """Check auth status for current client."""
        client_ip = get_client_ip(request)

        user_agent = request.headers.get("User-Agent", "").lower()
        is_tv_browser = "silk" in user_agent or "firetv" in user_agent or "aftt" in user_agent

        is_local = is_local_network(client_ip)
        is_authenticated = is_local or is_tv_browser
        role = "viewer" if (is_local or is_tv_browser) else None

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token == admin_password:
                role = "admin"
                is_authenticated = True
            elif token == manager_password:
                role = "manager"
                is_authenticated = True
            elif is_device_token_valid(token):
                tokens = load_device_tokens()
                role = tokens.get(token, {}).get("role") or role
                try:
                    ua = request.headers.get("User-Agent", "")
                    touch_device_token(token, get_client_ips(request), ua)
                except Exception:
                    pass
                is_authenticated = True

        forwarded_for = request.headers.get("X-Forwarded-For", "")
        print(
            f"Auth check - Client IP: {client_ip}, Is Local: {is_local}, "
            f"Is TV: {is_tv_browser}, Role: {role}, X-Forwarded-For: {forwarded_for}"
        )

        try:
            auth_header = request.headers.get("Authorization", "")
            if (is_local or is_tv_browser) and not auth_header.startswith("Bearer "):
                ua = request.headers.get("User-Agent", "")[:512]
                fingerprint = hashlib.sha256(f"{ua}:{client_ip}".encode()).hexdigest()
                tokens = load_device_tokens()
                found = None
                for t, info in tokens.items():
                    if info.get("fingerprint") == fingerprint and info.get("ephemeral"):
                        found = t
                        break
                if found:
                    touch_device_token(found, get_client_ips(request), ua)
                else:
                    anon_token = "ephemeral-" + secrets.token_urlsafe(12)
                    tokens[anon_token] = {
                        "created": datetime.now().isoformat(),
                        "expiry": (datetime.now() + timedelta(hours=24)).isoformat(),
                        "user_agent": ua,
                        "client_ip": client_ip,
                        "client_ips": get_client_ips(request),
                        "last_client_ip": client_ip,
                        "last_seen": datetime.now().isoformat(),
                        "role": "viewer",
                        "ephemeral": True,
                        "fingerprint": fingerprint,
                        "locked": False,
                    }
                    save_device_tokens(tokens)
        except Exception:
            pass

        return {
            "authenticated": is_authenticated,
            "role": role,
            "client_ip": client_ip,
            "is_tv_browser": is_tv_browser,
            "access_type": "tv-browser" if is_tv_browser else ("local" if is_local else "external"),
            "message": "TV browser auto-allowed"
            if is_tv_browser
            else ("Local network access granted automatically" if is_local else "External access requires password"),
        }

    @router.post("/auth/login")
    async def login(request: Request):
        """Users can login with manager/admin password."""
        try:
            body = await request.json()
            password = body.get("password", "")

            forwarded_for = request.headers.get("X-Forwarded-For", "")
            if forwarded_for:
                client_ip = forwarded_for.split(",")[0].strip()
            else:
                client_ip = request.client.host if request.client else "0.0.0.0"

            if password == admin_password:
                user_agent = request.headers.get("User-Agent", "Unknown")
                device_token = generate_device_token(user_agent, client_ip)

                tokens = load_device_tokens()
                tokens[device_token] = {
                    "created": datetime.now().isoformat(),
                    "expiry": (datetime.now() + timedelta(days=device_token_expiry_days)).isoformat(),
                    "user_agent": user_agent,
                    "client_ip": client_ip,
                    "client_ips": [client_ip],
                    "last_client_ip": client_ip,
                    "last_seen": datetime.now().isoformat(),
                    "locked": False,
                    "role": "admin",
                }
                save_device_tokens(tokens)

                print(f"Admin device token created for {client_ip} - expires in {device_token_expiry_days} days")
                return {
                    "authenticated": True,
                    "role": "admin",
                    "device_token": device_token,
                    "token": admin_password,
                    "message": "Admin access granted",
                }

            if password == manager_password:
                user_agent = request.headers.get("User-Agent", "Unknown")
                device_token = generate_device_token(user_agent, client_ip)

                tokens = load_device_tokens()
                tokens[device_token] = {
                    "created": datetime.now().isoformat(),
                    "expiry": (datetime.now() + timedelta(days=device_token_expiry_days)).isoformat(),
                    "user_agent": user_agent,
                    "client_ip": client_ip,
                    "client_ips": [client_ip],
                    "last_client_ip": client_ip,
                    "last_seen": datetime.now().isoformat(),
                    "locked": False,
                    "role": "manager",
                }
                save_device_tokens(tokens)

                print(f"Manager device token created for {client_ip} - expires in {device_token_expiry_days} days")
                return {
                    "authenticated": True,
                    "role": "manager",
                    "device_token": device_token,
                    "token": manager_password,
                    "message": "Manager access granted",
                }

            if is_local_network(client_ip):
                return {"authenticated": True, "role": "viewer", "message": "Local network view-only access"}

            raise HTTPException(status_code=401, detail="Invalid password")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/auth/ephemeral-viewer")
    async def create_ephemeral_viewer(request: Request):
        """Create a short-lived viewer token for login modal dismiss flow."""
        try:
            client_ip = get_client_ip(request)
            ua = request.headers.get("User-Agent", "Unknown")[:512]
            name = None
            try:
                body = await request.json()
                if isinstance(body, dict):
                    name = body.get("name") or body.get("device_name") or None
            except Exception:
                name = None

            token = generate_device_token(ua, client_ip)
            tokens = load_device_tokens()
            tokens[token] = {
                "created": datetime.now().isoformat(),
                "expiry": (datetime.now() + timedelta(days=device_token_expiry_days)).isoformat(),
                "user_agent": ua,
                "client_ip": client_ip,
                "client_ips": get_client_ips(request),
                "last_client_ip": client_ip,
                "last_seen": datetime.now().isoformat(),
                "role": "viewer",
                "ephemeral": True,
                "locked": False,
                "name": name,
            }
            save_device_tokens(tokens)
            return {
                "device_token": token,
                "token": token,
                "role": "viewer",
                "name": name,
                "message": "Viewer token issued",
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return router
