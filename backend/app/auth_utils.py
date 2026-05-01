import base64
import hmac
import hashlib
import ipaddress
import json
import os
import secrets
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_iso_to_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def load_device_tokens(*, db_module, device_tokens_db: str, device_tokens_file: str):
    """Load device tokens from persistent storage."""
    if device_tokens_db:
        try:
            result = {}
            with db_module.sqlite_transaction(device_tokens_db, timeout=2) as (_, cur):
                cur.execute("CREATE TABLE IF NOT EXISTS device_tokens (token TEXT PRIMARY KEY, data TEXT)")
                cur.execute("SELECT data FROM device_tokens")
                rows = cur.fetchall()
                for (blob,) in rows:
                    try:
                        parsed = json.loads(blob)
                        token_key = parsed.get('token') or parsed.get('device_token')
                        if token_key:
                            parsed.pop('token', None)
                            parsed.pop('device_token', None)
                            result[token_key] = parsed
                    except Exception:
                        continue
            return result
        except Exception as e:
            print(f"Error loading device tokens from DB ({device_tokens_db}): {e}")

    try:
        if os.path.exists(device_tokens_file):
            with open(device_tokens_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_device_tokens(*, tokens: dict, db_module, device_tokens_db: str, device_tokens_file: str):
    """Save device tokens to persistent storage."""
    if device_tokens_db:
        try:
            with db_module.sqlite_transaction(device_tokens_db, timeout=2) as (_, cur):
                cur.execute("CREATE TABLE IF NOT EXISTS device_tokens (token TEXT PRIMARY KEY, data TEXT)")
                for token, info in tokens.items():
                    try:
                        payload = json.dumps({**info, 'token': token})
                        cur.execute("INSERT OR REPLACE INTO device_tokens(token, data) VALUES (?, ?)", (token, payload))
                    except Exception:
                        continue
                try:
                    cur.execute("SELECT token FROM device_tokens")
                    existing = [r[0] for r in cur.fetchall()]
                    for token in existing:
                        if token not in tokens:
                            cur.execute("DELETE FROM device_tokens WHERE token = ?", (token,))
                except Exception:
                    pass
            return
        except Exception as e:
            print(f"Error saving device tokens to DB ({device_tokens_db}): {e}")

    try:
        with open(device_tokens_file, 'w', encoding='utf-8') as f:
            json.dump(tokens, f)
    except Exception as e:
        print(f"Error saving device tokens: {e}")


def generate_device_token(user_agent: str, client_ip: str) -> str:
    fingerprint = f"{user_agent}:{client_ip}"
    return secrets.token_urlsafe(32) + ":" + hashlib.sha256(fingerprint.encode()).hexdigest()[:16]


def is_device_token_valid(*, token: str, load_tokens, save_tokens) -> bool:
    tokens = load_tokens()
    if token in tokens:
        entry = tokens[token]
        expiry = _parse_iso_to_utc(entry.get('expiry'))
        if expiry is None:
            try:
                del tokens[token]
                save_tokens(tokens)
            except Exception:
                pass
            return False
        if _utc_now() < expiry:
            return True
        try:
            del tokens[token]
            save_tokens(tokens)
        except Exception:
            pass
    return False


def touch_device_token(*, token: str, load_tokens, save_tokens, client_ips: list | None = None, user_agent: str | None = None):
    if not token:
        return
    tokens = load_tokens()
    if token not in tokens:
        return
    entry = tokens[token]
    entry['last_seen'] = _utc_now_iso()
    if user_agent:
        entry['user_agent'] = user_agent
    if client_ips:
        try:
            existing = entry.get('client_ips') or []
            for ip in client_ips:
                if ip not in existing:
                    existing.append(ip)
            entry['client_ips'] = existing[-10:]
            entry['last_client_ip'] = client_ips[-1]
        except Exception:
            pass
    try:
        tokens[token] = entry
        save_tokens(tokens)
    except Exception:
        pass


def is_local_network(*, client_ip, local_networks) -> bool:
    try:
        ips = client_ip if isinstance(client_ip, (list, tuple)) else [client_ip]
        for ip_str in ips:
            try:
                ip = ipaddress.ip_address(ip_str)
                if any(ip in network for network in local_networks):
                    return True
            except ValueError:
                continue
    except Exception:
        pass
    return False


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "") or request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


def get_client_ips(request: Request) -> list:
    forwarded_for = request.headers.get("X-Forwarded-For", "") or request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return [p.strip() for p in forwarded_for.split(",") if p.strip()]
    if request.client and getattr(request.client, 'host', None):
        return [request.client.host]
    return ["0.0.0.0"]


def get_role_from_request(*, request: Request, admin_password: str, manager_password: str, viewer_password: str = "", is_token_valid=None, load_tokens=None) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if hmac.compare_digest(token, admin_password):
            return "admin"
        if hmac.compare_digest(token, manager_password):
            return "manager"
        if viewer_password and hmac.compare_digest(token, viewer_password):
            return "viewer"
        if is_token_valid and load_tokens and is_token_valid(token):
            tokens = load_tokens()
            return tokens.get(token, {}).get("role")
    return None


def require_manager_or_admin(*, request: Request, get_role):
    role = get_role(request)
    if role not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="Manager access required for exports")


def require_admin(*, request: Request, get_role):
    role = get_role(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


async def auth_middleware(
    *,
    request: Request,
    call_next,
    dashboard_public: bool,
    admin_password: str,
    manager_password: str,
    viewer_password: str = "",
    is_local_network_fn,
    is_token_valid_fn,
    load_tokens_fn,
    touch_token_fn,
    get_client_ip_fn,
    get_client_ips_fn,
    legacy_query_auth_enabled: bool = False,
    legacy_basic_auth_enabled: bool = False,
):
    client_ip = get_client_ip_fn(request)
    strict_viewer_password = bool(str(viewer_password or "").strip())

    if request.url.path.startswith(("/styles.css", "/assets/", "/vendor/")):
        return await call_next(request)

    if request.url.path == "/admin.html":
        return await call_next(request)

    if request.url.path.startswith("/auth/"):
        return await call_next(request)

    if is_local_network_fn(client_ip) and not strict_viewer_password:
        # Intentional policy: trusted network viewers can access non-admin routes
        # even if a remembered device token is missing.
        if not request.url.path.startswith("/admin"):
            return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if is_token_valid_fn(token):
            tokens = load_tokens_fn()
            role = tokens.get(token, {}).get("role")
            try:
                ua = request.headers.get('User-Agent', '')
                touch_token_fn(token, get_client_ips_fn(request), ua)
            except Exception:
                pass
            if request.url.path.startswith("/admin") and role != "admin":
                return JSONResponse(status_code=403, content={"detail": "Admin access required."})
            return await call_next(request)

    if not strict_viewer_password:
        try:
            if dashboard_public and request.method == "GET" and request.url.path.startswith(("/metrics", "/analytics")):
                return await call_next(request)
        except Exception:
            pass

    try:
        ingest_key = os.getenv('INGESTION_KEY')
        if ingest_key and request.url.path.startswith('/api/ingest'):
            auth_header = request.headers.get('Authorization', '')
            bearer_key = auth_header[7:] if auth_header.startswith('Bearer ') else None
            header_key = request.headers.get('X-INGESTION-KEY') or request.headers.get('x-ingestion-key')
            if bearer_key == ingest_key or header_key == ingest_key:
                return await call_next(request)
    except Exception:
        pass

    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if hmac.compare_digest(token, admin_password):
            return await call_next(request)
        if hmac.compare_digest(token, manager_password):
            if request.url.path.startswith("/admin"):
                return JSONResponse(status_code=403, content={"detail": "Admin access required."})
            return await call_next(request)
        if strict_viewer_password and hmac.compare_digest(token, viewer_password):
            if request.url.path.startswith("/admin"):
                return JSONResponse(status_code=403, content={"detail": "Admin access required."})
            return await call_next(request)

    if legacy_query_auth_enabled:
        query_auth = request.query_params.get("auth")
        if query_auth and (hmac.compare_digest(query_auth, admin_password) or hmac.compare_digest(query_auth, manager_password)):
            if hmac.compare_digest(query_auth, manager_password) and request.url.path.startswith("/admin"):
                return JSONResponse(status_code=403, content={"detail": "Admin access required."})
            return await call_next(request)

    if legacy_basic_auth_enabled and auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode()
            if ":" in decoded:
                _, password = decoded.split(":", 1)
                if hmac.compare_digest(password, admin_password):
                    return await call_next(request)
                if hmac.compare_digest(password, manager_password) and not request.url.path.startswith("/admin"):
                    return await call_next(request)
        except Exception:
            pass

    if request.url.path.startswith("/metrics") or request.url.path.startswith("/analytics") or request.url.path.startswith("/competitions") or request.url.path.startswith("/export") or request.url.path.startswith("/api") or request.url.path.startswith("/admin"):
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized. External access requires password."}
        )

    if request.url.path == "/" or request.url.path == "/index.html":
        return FileResponse("frontend/pages/index.html")

    return await call_next(request)
