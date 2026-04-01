from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


def create_admin_diagnostics_router(
    *,
    require_admin: Callable[[Request], None],
    get_mariadb_connection: Callable[[], object | None],
    get_client_ip: Callable[[Request], str],
    get_client_ips: Callable[[Request], list[str]],
    is_local_network: Callable[[str], bool],
    is_device_token_valid: Callable[[str], bool],
    trusted_viewer_networks: list,
    activity_log,
) -> APIRouter:
    router = APIRouter()

    @router.get("/admin/db-processlist")
    def admin_db_processlist(request: Request, limit: int = 100):
        """Admin-only diagnostic: return SHOW FULL PROCESSLIST from MariaDB."""
        require_admin(request)
        conn = None
        try:
            conn = get_mariadb_connection()
            if not conn:
                return JSONResponse(status_code=503, content={"status": "fail", "detail": "MariaDB connection failed"})
            cur = conn.cursor()
            cur.execute("SHOW FULL PROCESSLIST")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            processlist = []
            for row in rows[:limit]:
                try:
                    processlist.append(
                        {
                            "Id": row[0],
                            "User": row[1],
                            "Host": row[2],
                            "db": row[3],
                            "Command": row[4],
                            "Time": row[5],
                            "State": row[6],
                            "Info": row[7],
                        }
                    )
                except Exception:
                    processlist.append({"raw": row})
            return {"processlist": processlist}
        except Exception as exc:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/admin/network-access")
    def admin_network_access_diagnostics(request: Request, token: str | None = None):
        """Admin-only diagnostic for client IP parsing and trusted viewer network matching."""
        require_admin(request)
        try:
            client_ip = get_client_ip(request)
            client_ips = get_client_ips(request)
            trusted_match = is_local_network(client_ip)
            auth_header = request.headers.get("Authorization", "")
            bearer_token = auth_header[7:] if auth_header.startswith("Bearer ") else None
            token_to_check = token or bearer_token

            token_valid = None
            if token_to_check:
                try:
                    token_valid = is_device_token_valid(token_to_check)
                except Exception:
                    token_valid = None

            return {
                "client_ip": client_ip,
                "client_ips": client_ips,
                "trusted_network_match": trusted_match,
                "trusted_viewer_networks": [str(n) for n in trusted_viewer_networks],
                "is_tv_browser": any(v in request.headers.get("User-Agent", "").lower() for v in ("silk", "firetv", "aftt")),
                "token_checked": bool(token_to_check),
                "token_valid": token_valid,
                "viewer_policy": {
                    "trusted_network_auto_allow": True,
                    "token_controls": "device tokens support revoke/rename; no lock behavior",
                },
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/admin/external-access-attempts")
    def admin_external_access_attempts(request: Request, limit: int = 100):
        """Admin-only diagnostic: summarize denied off-network access attempts."""
        require_admin(request)
        try:
            protected_prefixes = ("/metrics", "/analytics", "/competitions", "/export", "/api", "/admin")
            rows = []
            for ev in list(activity_log):
                try:
                    if int(ev.get("status_code") or 0) != 401:
                        continue
                    path = str(ev.get("path") or "")
                    if not path.startswith(protected_prefixes):
                        continue
                    client_ip = str(ev.get("client_ip") or "")
                    if not client_ip or is_local_network(client_ip):
                        continue
                    rows.append(
                        {
                            "ts": ev.get("ts"),
                            "path": path,
                            "method": ev.get("method"),
                            "client_ip": client_ip,
                            "user_agent": ev.get("user_agent") or "",
                        }
                    )
                except Exception:
                    continue

            grouped = {}
            for r in rows:
                key = (r["client_ip"], r["user_agent"])
                if key not in grouped:
                    grouped[key] = {
                        "client_ip": r["client_ip"],
                        "user_agent": r["user_agent"],
                        "attempts": 0,
                        "first_seen": r["ts"],
                        "last_seen": r["ts"],
                        "last_path": r["path"],
                        "last_method": r["method"],
                    }
                grouped[key]["attempts"] += 1
                grouped[key]["last_seen"] = r["ts"]
                grouped[key]["last_path"] = r["path"]
                grouped[key]["last_method"] = r["method"]

            items = sorted(grouped.values(), key=lambda x: (x.get("last_seen") or ""), reverse=True)[: max(1, min(limit, 500))]
            return {"attempts": items, "total": len(items)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return router
