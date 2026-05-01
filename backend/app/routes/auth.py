from datetime import UTC, datetime, timedelta
import hmac
from typing import Callable

from fastapi import APIRouter, HTTPException, Request


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _token_fingerprint(token: str) -> str | None:
    if ":" not in token:
        return None
    suffix = token.rsplit(":", 1)[-1].strip().lower()
    if len(suffix) >= 8 and all(ch in "0123456789abcdef" for ch in suffix):
        return suffix
    return None


def create_auth_router(
    *,
    admin_password: str,
    manager_password: str,
    viewer_password: str,
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
        strict_viewer_password = bool(str(viewer_password or "").strip())
        is_authenticated = is_local and not strict_viewer_password
        role = "viewer" if is_authenticated else None

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if hmac.compare_digest(token, admin_password):
                role = "admin"
                is_authenticated = True
            elif hmac.compare_digest(token, manager_password):
                role = "manager"
                is_authenticated = True
            elif strict_viewer_password and hmac.compare_digest(token, viewer_password):
                role = "viewer"
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

        return {
            "authenticated": is_authenticated,
            "role": role,
            "client_ip": client_ip,
            "is_tv_browser": is_tv_browser,
            "access_type": "local" if is_local else "external",
            "viewer_password_required": strict_viewer_password,
            "message": "Viewer password required" if strict_viewer_password else ("Local network access granted automatically" if is_local else "External access requires password"),
        }

    @router.post("/auth/login")
    async def login(request: Request):
        """Users can login with admin, manager, or configured viewer password."""
        try:
            body = await request.json()
            password = body.get("password", "")
            strict_viewer_password = bool(str(viewer_password or "").strip())

            forwarded_for = request.headers.get("X-Forwarded-For", "")
            if forwarded_for:
                client_ip = forwarded_for.split(",")[0].strip()
            else:
                client_ip = request.client.host if request.client else "0.0.0.0"

            if hmac.compare_digest(password, admin_password):
                user_agent = request.headers.get("User-Agent", "Unknown")
                device_token = generate_device_token(user_agent, client_ip)
                new_fp = _token_fingerprint(device_token)

                tokens = load_device_tokens()
                if new_fp:
                    for existing_token, existing_info in list(tokens.items()):
                        if existing_token == device_token:
                            continue
                        existing_role = str(existing_info.get("role") or "").strip().lower()
                        if existing_role != "admin":
                            continue
                        if _token_fingerprint(existing_token) == new_fp:
                            tokens.pop(existing_token, None)
                tokens[device_token] = {
                    "created": _utc_now_iso(),
                    "expiry": (datetime.now(UTC) + timedelta(days=device_token_expiry_days)).isoformat().replace("+00:00", "Z"),
                    "user_agent": user_agent,
                    "client_ip": client_ip,
                    "client_ips": [client_ip],
                    "last_client_ip": client_ip,
                    "last_seen": _utc_now_iso(),
                    "role": "admin",
                }
                save_device_tokens(tokens)

                print(f"Admin device token created for {client_ip} - expires in {device_token_expiry_days} days")
                return {
                    "authenticated": True,
                    "role": "admin",
                    "device_token": device_token,
                    "token": device_token,
                    "message": "Admin access granted",
                }

            if hmac.compare_digest(password, manager_password):
                user_agent = request.headers.get("User-Agent", "Unknown")
                device_token = generate_device_token(user_agent, client_ip)
                new_fp = _token_fingerprint(device_token)

                tokens = load_device_tokens()
                if new_fp:
                    for existing_token, existing_info in list(tokens.items()):
                        if existing_token == device_token:
                            continue
                        existing_role = str(existing_info.get("role") or "").strip().lower()
                        if existing_role != "manager":
                            continue
                        if _token_fingerprint(existing_token) == new_fp:
                            tokens.pop(existing_token, None)
                tokens[device_token] = {
                    "created": _utc_now_iso(),
                    "expiry": (datetime.now(UTC) + timedelta(days=device_token_expiry_days)).isoformat().replace("+00:00", "Z"),
                    "user_agent": user_agent,
                    "client_ip": client_ip,
                    "client_ips": [client_ip],
                    "last_client_ip": client_ip,
                    "last_seen": _utc_now_iso(),
                    "role": "manager",
                }
                save_device_tokens(tokens)

                print(f"Manager device token created for {client_ip} - expires in {device_token_expiry_days} days")
                return {
                    "authenticated": True,
                    "role": "manager",
                    "device_token": device_token,
                    "token": device_token,
                    "message": "Manager access granted",
                }

            if strict_viewer_password and hmac.compare_digest(password, viewer_password):
                user_agent = request.headers.get("User-Agent", "Unknown")
                device_token = generate_device_token(user_agent, client_ip)
                tokens = load_device_tokens()
                tokens[device_token] = {
                    "created": _utc_now_iso(),
                    "expiry": (datetime.now(UTC) + timedelta(days=device_token_expiry_days)).isoformat().replace("+00:00", "Z"),
                    "user_agent": user_agent,
                    "client_ip": client_ip,
                    "client_ips": [client_ip],
                    "last_client_ip": client_ip,
                    "last_seen": _utc_now_iso(),
                    "role": "viewer",
                }
                save_device_tokens(tokens)

                return {
                    "authenticated": True,
                    "role": "viewer",
                    "device_token": device_token,
                    "token": device_token,
                    "message": "Viewer access granted",
                }

            raise HTTPException(status_code=401, detail="Invalid password")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/auth/ephemeral-viewer")
    async def create_ephemeral_viewer(request: Request):
        """Create a short-lived viewer token for login modal dismiss flow."""
        try:
            if str(viewer_password or "").strip():
                raise HTTPException(status_code=403, detail="Viewer password is required")
            client_ip = get_client_ip(request)
            if not is_local_network(client_ip):
                raise HTTPException(status_code=403, detail="Viewer token issuance is restricted to trusted networks")
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
                "created": _utc_now_iso(),
                "expiry": (datetime.now(UTC) + timedelta(days=device_token_expiry_days)).isoformat().replace("+00:00", "Z"),
                "user_agent": ua,
                "client_ip": client_ip,
                "client_ips": get_client_ips(request),
                "last_client_ip": client_ip,
                "last_seen": _utc_now_iso(),
                "role": "viewer",
                "ephemeral": True,
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
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return router
