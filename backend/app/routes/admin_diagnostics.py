from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


def create_admin_diagnostics_router(
    *,
    require_admin: Callable[[Request], None],
    db_module,
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

    @router.get("/admin/erasure-evidence")
    def admin_erasure_evidence(request: Request, days: int = 30, limit: int = 50):
        """Admin-only diagnostic: prove erasure records exist and show mapping hints to MariaDB."""
        require_admin(request)
        days = max(1, min(int(days or 30), 180))
        limit = max(1, min(int(limit or 50), 200))

        import sqlite3
        import re
        from datetime import datetime, timedelta, UTC

        def _norm(v):
            if v is None:
                return ""
            return re.sub(r"[^A-Za-z0-9]", "", str(v)).upper()

        def _to_iso(v):
            if not v:
                return ""
            s = str(v).strip()
            if not s:
                return ""
            return s.replace(" ", "T")

        start_iso = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        summary = {
            "windowDays": days,
            "erasuresSuccessCount": 0,
            "erasuresWithSerialCount": 0,
            "localErasuresCount": 0,
            "mariaAssetMatchesInSample": 0,
            "mariaQaMatchesInSample": 0,
        }
        samples = []

        conn = sqlite3.connect(db_module.DB_PATH)
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(1) FROM erasures WHERE event = 'success' AND ts >= ?", (start_iso,))
            row = cur.fetchone()
            summary["erasuresSuccessCount"] = int(row[0]) if row and row[0] is not None else 0

            cur.execute(
                "SELECT COUNT(1) FROM erasures WHERE event = 'success' AND ts >= ? AND TRIM(COALESCE(system_serial,'')) <> ''",
                (start_iso,),
            )
            row = cur.fetchone()
            summary["erasuresWithSerialCount"] = int(row[0]) if row and row[0] is not None else 0

            cur.execute("SELECT COUNT(1) FROM local_erasures WHERE ts >= ?", (start_iso,))
            row = cur.fetchone()
            summary["localErasuresCount"] = int(row[0]) if row and row[0] is not None else 0

            cur.execute(
                """
                SELECT ts, job_id, COALESCE(NULLIF(TRIM(system_serial), ''), NULLIF(TRIM(job_id), '')) AS key_id, initials, device_type
                FROM erasures
                WHERE event = 'success' AND ts >= ?
                ORDER BY ts DESC
                LIMIT ?
                """,
                (start_iso, limit),
            )
            er_rows = cur.fetchall() or []
        finally:
            cur.close()
            conn.close()

        keys = [str(r[2]) for r in er_rows if r and r[2]]
        key_norms = {_norm(k): k for k in keys if _norm(k)}

        key_to_stockid = {}
        qa_stockids = set()
        if key_norms:
            mariadb_conn = get_mariadb_connection()
            if mariadb_conn:
                mcur = mariadb_conn.cursor()
                try:
                    vals = list(key_norms.values())
                    placeholders = ",".join(["%s"] * len(vals))
                    mcur.execute(
                        f"SELECT stockid, system_serial FROM ITAD_asset_info WHERE stockid IN ({placeholders}) OR system_serial IN ({placeholders})",
                        tuple(vals) + tuple(vals),
                    )
                    for ar in mcur.fetchall() or []:
                        sid = str(ar[0]) if ar and ar[0] is not None else None
                        serial = str(ar[1]) if ar and len(ar) > 1 and ar[1] is not None else None
                        if sid:
                            key_to_stockid[_norm(sid)] = sid
                        if serial and sid:
                            key_to_stockid[_norm(serial)] = sid

                    sids = list({v for v in key_to_stockid.values() if v})
                    if sids:
                        ph = ",".join(["%s"] * len(sids))
                        mcur.execute(
                            f"SELECT DISTINCT stockid FROM ITAD_QA_App WHERE stockid IN ({ph})",
                            tuple(sids),
                        )
                        qa_stockids = {str(r[0]) for r in (mcur.fetchall() or []) if r and r[0]}
                except Exception:
                    pass
                finally:
                    try:
                        mcur.close()
                        mariadb_conn.close()
                    except Exception:
                        pass

        for row in er_rows:
            ts, job_id, key_id, initials, device_type = row
            nkey = _norm(key_id)
            stockid = key_to_stockid.get(nkey)
            has_asset = bool(stockid)
            has_qa = bool(stockid and stockid in qa_stockids)
            if has_asset:
                summary["mariaAssetMatchesInSample"] += 1
            if has_qa:
                summary["mariaQaMatchesInSample"] += 1
            samples.append({
                "ts": _to_iso(ts),
                "job_id": job_id,
                "key": key_id,
                "initials": initials,
                "device_type": device_type,
                "asset_match": has_asset,
                "stockid": stockid,
                "qa_match": has_qa,
            })

        return {
            "summary": summary,
            "samples": samples,
        }

    return router
