from typing import Callable
from datetime import UTC, datetime

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

        def _parse_dt(v):
            if v is None:
                return None
            if isinstance(v, datetime):
                return v if v.tzinfo else v.replace(tzinfo=UTC)
            raw = str(v).strip()
            if not raw:
                return None
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
            ):
                try:
                    return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
                except Exception:
                    continue
            try:
                dt = datetime.fromisoformat(raw)
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            except Exception:
                return None

        start_iso = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        summary = {
            "windowDays": days,
            "erasuresSuccessCount": 0,
            "erasuresWithSerialCount": 0,
            "localErasuresCount": 0,
            "mariaAssetMatchesInSample": 0,
            "mariaQaMatchesInSample": 0,
            "sampleAwaitingQaByRule": 0,
            "sampleDeductedByQaAfterErasure": 0,
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
        qa_meta_by_stockid = {}
        if key_norms:
            mariadb_conn = get_mariadb_connection()
            if mariadb_conn:
                mcur = mariadb_conn.cursor()
                try:
                    vals = list(key_norms.values())
                    placeholders = ",".join(["%s"] * len(vals))
                    q_asset_primary = (
                        f"SELECT stockid, serialnumber FROM ITAD_asset_info "
                        f"WHERE stockid IN ({placeholders}) OR serialnumber IN ({placeholders})"
                    )
                    q_asset_fallback = (
                        f"SELECT stockid, system_serial FROM ITAD_asset_info "
                        f"WHERE stockid IN ({placeholders}) OR system_serial IN ({placeholders})"
                    )
                    try:
                        mcur.execute(q_asset_primary, tuple(vals) + tuple(vals))
                    except Exception:
                        mcur.execute(q_asset_fallback, tuple(vals) + tuple(vals))
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

                        mcur.execute(
                            f"""
                            SELECT stockid, de_completed_by, de_completed_date
                            FROM ITAD_asset_info
                            WHERE stockid IN ({ph})
                            """,
                            tuple(sids),
                        )
                        for ar in mcur.fetchall() or []:
                            sid = str(ar[0]) if ar and ar[0] is not None else None
                            if not sid:
                                continue
                            qa_meta_by_stockid.setdefault(sid, {})
                            qa_meta_by_stockid[sid]["qaByDeCompletedBy"] = str(ar[1]) if len(ar) > 1 and ar[1] is not None else None
                            qa_meta_by_stockid[sid]["qaCompletedDate"] = _to_iso(ar[2] if len(ar) > 2 else None)

                        mcur.execute(
                            f"""
                            SELECT
                                stockid,
                                MAX(added_date) AS last_qa_date,
                                SUBSTRING_INDEX(
                                    GROUP_CONCAT(COALESCE(username, '') ORDER BY added_date DESC SEPARATOR '||'),
                                    '||',
                                    1
                                ) AS last_qa_username
                            FROM ITAD_QA_App
                            WHERE stockid IN ({ph})
                            GROUP BY stockid
                            """,
                            tuple(sids),
                        )
                        for qr in mcur.fetchall() or []:
                            sid = str(qr[0]) if qr and qr[0] is not None else None
                            if not sid:
                                continue
                            qa_meta_by_stockid.setdefault(sid, {})
                            qa_meta_by_stockid[sid]["lastQaDate"] = _to_iso(qr[1] if len(qr) > 1 else None)
                            qa_meta_by_stockid[sid]["lastQaUsername"] = str(qr[2]) if len(qr) > 2 and qr[2] is not None else None
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
            meta = qa_meta_by_stockid.get(stockid or "", {})
            last_qa_date = meta.get("lastQaDate")
            has_qa = bool(stockid and (stockid in qa_stockids or last_qa_date))
            if has_asset:
                summary["mariaAssetMatchesInSample"] += 1
            if has_qa:
                summary["mariaQaMatchesInSample"] += 1

            erasure_dt = _parse_dt(ts)
            qa_dt = _parse_dt(last_qa_date)
            awaiting_by_rule = None
            qa_status_reason = "no_asset_match"
            qa_lag_hours = None
            if has_asset:
                if erasure_dt and qa_dt:
                    qa_lag_hours = round((qa_dt - erasure_dt).total_seconds() / 3600.0, 2)
                    if qa_dt >= erasure_dt:
                        awaiting_by_rule = False
                        qa_status_reason = "deducted_qa_on_or_after_erasure"
                    else:
                        awaiting_by_rule = True
                        qa_status_reason = "awaiting_qa_last_qa_before_erasure"
                elif qa_dt:
                    awaiting_by_rule = False
                    qa_status_reason = "deducted_has_qa_no_erasure_ts"
                else:
                    awaiting_by_rule = True
                    qa_status_reason = "awaiting_no_qa_found"

            if awaiting_by_rule is True:
                summary["sampleAwaitingQaByRule"] += 1
            elif awaiting_by_rule is False:
                summary["sampleDeductedByQaAfterErasure"] += 1

            samples.append({
                "ts": _to_iso(ts),
                "job_id": job_id,
                "key": key_id,
                "initials": initials,
                "device_type": device_type,
                "asset_match": has_asset,
                "stockid": stockid,
                "qa_match": has_qa,
                "last_qa_date": last_qa_date,
                "qa_by_de_completed_by": meta.get("qaByDeCompletedBy"),
                "last_qa_username": meta.get("lastQaUsername"),
                "awaiting_qa_by_rule": awaiting_by_rule,
                "qa_status_reason": qa_status_reason,
                "qa_lag_hours": qa_lag_hours,
            })

        return {
            "summary": summary,
            "samples": samples,
        }

    @router.get("/admin/sorting-evidence")
    def admin_sorting_evidence(request: Request, days: int = 30, limit: int = 50):
        """Admin-only diagnostic: sampled proof for Awaiting Sorting calculation."""
        require_admin(request)
        days = max(1, min(int(days or 30), 180))
        limit = max(10, min(int(limit or 50), 200))

        conn = None
        try:
            conn = get_mariadb_connection()
            if not conn:
                return JSONResponse(status_code=503, content={"status": "fail", "detail": "MariaDB connection failed"})

            cur = conn.cursor()
            try:
                # Candidate stockids: recently DE-completed assets that could be in sorting flow.
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT a.stockid)
                    FROM ITAD_asset_info a
                    WHERE a.stockid IS NOT NULL
                      AND TRIM(COALESCE(a.stockid, '')) <> ''
                      AND a.de_completed_date IS NOT NULL
                      AND a.de_completed_date >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    """,
                    (days,),
                )
                row = cur.fetchone()
                candidate_total = int(row[0]) if row and row[0] is not None else 0

                # Awaiting sorting by current rule:
                # DE complete exists, and latest QA row with username is missing or older than DE completion.
                # Exclusion rule: any pallet_id starting with A100 is considered already assigned and should be deducted.
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT a.stockid)
                    FROM ITAD_asset_info a
                    LEFT JOIN (
                        SELECT stockid, MAX(added_date) AS last_qa_with_user
                        FROM ITAD_QA_App
                        WHERE stockid IS NOT NULL
                          AND TRIM(COALESCE(stockid, '')) <> ''
                          AND TRIM(COALESCE(username, '')) <> ''
                        GROUP BY stockid
                    ) q ON q.stockid = a.stockid
                    WHERE a.stockid IS NOT NULL
                      AND TRIM(COALESCE(a.stockid, '')) <> ''
                      AND a.de_completed_date IS NOT NULL
                      AND a.de_completed_date >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                            AND LEFT(UPPER(TRIM(COALESCE(a.pallet_id, ''))), 4) <> 'A100'
                      AND (
                            q.last_qa_with_user IS NULL
                            OR a.de_completed_date > q.last_qa_with_user
                          )
                    """,
                    (days,),
                )
                row = cur.fetchone()
                awaiting_total = int(row[0]) if row and row[0] is not None else 0

                # Rows that have a valid decrement signal (Sorting row with username newer than QA completion).
                # Includes A100 pallet assignment as a decrement signal.
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT a.stockid)
                    FROM ITAD_asset_info a
                    LEFT JOIN (
                        SELECT stockid, MAX(added_date) AS last_qa_with_user
                        FROM ITAD_QA_App
                        WHERE stockid IS NOT NULL
                          AND TRIM(COALESCE(stockid, '')) <> ''
                          AND TRIM(COALESCE(username, '')) <> ''
                        GROUP BY stockid
                    ) q ON q.stockid = a.stockid
                    WHERE a.stockid IS NOT NULL
                      AND TRIM(COALESCE(a.stockid, '')) <> ''
                      AND a.de_completed_date IS NOT NULL
                      AND a.de_completed_date >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                            AND (
                                                        q.last_qa_with_user >= a.de_completed_date
                                                        OR LEFT(UPPER(TRIM(COALESCE(a.pallet_id, ''))), 4) = 'A100'
                                                    )
                    """,
                    (days,),
                )
                row = cur.fetchone()
                decremented_total = int(row[0]) if row and row[0] is not None else 0

                # Reassurance metrics:
                # - split awaiting stockids by reason
                # - measure potential undercount caused by blank usernames in Sorting scans
                # - verify QA completion metadata coverage in ITAD_asset_info (de_* fields)
                cur.execute(
                    """
                    SELECT
                        COUNT(DISTINCT CASE WHEN q.last_qa_with_user IS NULL THEN a.stockid END) AS missing_sorting_with_username,
                        COUNT(DISTINCT CASE WHEN q.last_qa_with_user IS NOT NULL AND a.de_completed_date > q.last_qa_with_user THEN a.stockid END) AS sorting_older_than_qa_completed
                    FROM ITAD_asset_info a
                    LEFT JOIN (
                        SELECT stockid, MAX(added_date) AS last_qa_with_user
                        FROM ITAD_QA_App
                        WHERE stockid IS NOT NULL
                          AND TRIM(COALESCE(stockid, '')) <> ''
                          AND TRIM(COALESCE(username, '')) <> ''
                        GROUP BY stockid
                    ) q ON q.stockid = a.stockid
                    WHERE a.stockid IS NOT NULL
                      AND TRIM(COALESCE(a.stockid, '')) <> ''
                      AND a.de_completed_date IS NOT NULL
                      AND a.de_completed_date >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                            AND LEFT(UPPER(TRIM(COALESCE(a.pallet_id, ''))), 4) <> 'A100'
                    """,
                    (days,),
                )
                row = cur.fetchone()
                missing_sorting_with_username = int(row[0]) if row and row[0] is not None else 0
                sorting_older_than_qa_completed = int(row[1]) if row and len(row) > 1 and row[1] is not None else 0

                cur.execute(
                    """
                    SELECT COUNT(DISTINCT q.stockid)
                    FROM ITAD_QA_App q
                    INNER JOIN ITAD_asset_info a ON a.stockid = q.stockid
                    WHERE a.stockid IS NOT NULL
                      AND TRIM(COALESCE(a.stockid, '')) <> ''
                      AND a.de_completed_date IS NOT NULL
                      AND a.de_completed_date >= DATE_SUB(NOW(), INTERVAL %s DAY)
                      AND q.added_date >= a.de_completed_date
                      AND TRIM(COALESCE(q.username, '')) = ''
                    """,
                    (days,),
                )
                row = cur.fetchone()
                blank_username_after_de = int(row[0]) if row and row[0] is not None else 0

                cur.execute(
                    """
                    SELECT COUNT(DISTINCT a.stockid)
                    FROM ITAD_asset_info a
                    WHERE a.stockid IS NOT NULL
                      AND TRIM(COALESCE(a.stockid, '')) <> ''
                      AND a.de_completed_date IS NOT NULL
                      AND a.de_completed_date >= DATE_SUB(NOW(), INTERVAL %s DAY)
                      AND LEFT(UPPER(TRIM(COALESCE(a.pallet_id, ''))), 4) = 'A100'
                    """,
                    (days,),
                )
                row = cur.fetchone()
                excluded_by_a100 = int(row[0]) if row and row[0] is not None else 0

                cur.execute(
                    """
                    SELECT COUNT(DISTINCT a.stockid)
                    FROM ITAD_asset_info a
                    WHERE a.stockid IS NOT NULL
                      AND TRIM(COALESCE(a.stockid, '')) <> ''
                      AND a.de_completed_date IS NOT NULL
                      AND a.de_completed_date >= DATE_SUB(NOW(), INTERVAL %s DAY)
                      AND TRIM(COALESCE(a.de_completed_by, '')) <> ''
                    """,
                    (days,),
                )
                row = cur.fetchone()
                de_completed_by_present = int(row[0]) if row and row[0] is not None else 0

                # Sample awaiting rows for quick manual validation in admin UI.
                cur.execute(
                    """
                    SELECT
                        a.stockid,
                        a.de_completed_date,
                        q.last_qa_with_user,
                        a.pallet_id,
                        CASE
                            WHEN LEFT(UPPER(TRIM(COALESCE(a.pallet_id, ''))), 4) = 'A100' THEN 'decremented_by_a100_pallet'
                            WHEN q.last_qa_with_user IS NULL THEN 'missing_sorting_with_username'
                            WHEN a.de_completed_date > q.last_qa_with_user THEN 'sorting_older_than_qa_completed'
                            ELSE 'unknown'
                        END AS reason
                    FROM ITAD_asset_info a
                    LEFT JOIN (
                        SELECT stockid, MAX(added_date) AS last_qa_with_user
                        FROM ITAD_QA_App
                        WHERE stockid IS NOT NULL
                          AND TRIM(COALESCE(stockid, '')) <> ''
                          AND TRIM(COALESCE(username, '')) <> ''
                        GROUP BY stockid
                    ) q ON q.stockid = a.stockid
                    WHERE a.stockid IS NOT NULL
                      AND TRIM(COALESCE(a.stockid, '')) <> ''
                      AND a.de_completed_date IS NOT NULL
                      AND a.de_completed_date >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                            AND LEFT(UPPER(TRIM(COALESCE(a.pallet_id, ''))), 4) <> 'A100'
                      AND (
                            q.last_qa_with_user IS NULL
                            OR a.de_completed_date > q.last_qa_with_user
                          )
                    ORDER BY a.de_completed_date DESC
                    LIMIT %s
                    """,
                    (days, limit),
                )
                awaiting_rows = cur.fetchall() or []

                # Sample decremented rows to compare what "good" looks like.
                cur.execute(
                    """
                    SELECT
                        a.stockid,
                        a.de_completed_date,
                        q.last_qa_with_user,
                        a.pallet_id,
                        CASE
                            WHEN LEFT(UPPER(TRIM(COALESCE(a.pallet_id, ''))), 4) = 'A100' THEN 'decremented_by_a100_pallet'
                            ELSE 'decremented_by_sorting_scan'
                        END AS reason
                    FROM ITAD_asset_info a
                    LEFT JOIN (
                        SELECT stockid, MAX(added_date) AS last_qa_with_user
                        FROM ITAD_QA_App
                        WHERE stockid IS NOT NULL
                          AND TRIM(COALESCE(stockid, '')) <> ''
                          AND TRIM(COALESCE(username, '')) <> ''
                        GROUP BY stockid
                    ) q ON q.stockid = a.stockid
                    WHERE a.stockid IS NOT NULL
                      AND TRIM(COALESCE(a.stockid, '')) <> ''
                      AND a.de_completed_date IS NOT NULL
                      AND a.de_completed_date >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                            AND (
                                                        q.last_qa_with_user >= a.de_completed_date
                                                        OR LEFT(UPPER(TRIM(COALESCE(a.pallet_id, ''))), 4) = 'A100'
                                                    )
                                        ORDER BY
                                                CASE WHEN LEFT(UPPER(TRIM(COALESCE(a.pallet_id, ''))), 4) = 'A100' THEN 1 ELSE 0 END DESC,
                                                q.last_qa_with_user DESC
                    LIMIT %s
                    """,
                    (days, max(10, limit // 2)),
                )
                decremented_rows = cur.fetchall() or []
            finally:
                cur.close()
                conn.close()

            def _to_iso(value):
                if value is None:
                    return None
                if isinstance(value, datetime):
                    dt = value if value.tzinfo else value.replace(tzinfo=UTC)
                    return dt.isoformat()
                return str(value)

            def _parse_dt(value):
                if value is None:
                    return None
                if isinstance(value, datetime):
                    return value if value.tzinfo else value.replace(tzinfo=UTC)
                raw = str(value).strip()
                if not raw:
                    return None
                if raw.endswith("Z"):
                    raw = raw[:-1] + "+00:00"
                try:
                    dt = datetime.fromisoformat(raw)
                    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
                except Exception:
                    return None

            now_utc = datetime.now(UTC)

            # Enrich sampled stockids with DE owner and latest QA metadata.
            sampled_stockids = []
            for row in awaiting_rows + decremented_rows:
                if row and row[0] is not None:
                    sid = str(row[0]).strip()
                    if sid:
                        sampled_stockids.append(sid)
            sampled_stockids = sorted(set(sampled_stockids))

            sample_meta = {}
            if sampled_stockids:
                meta_conn = get_mariadb_connection()
                if meta_conn:
                    mcur = meta_conn.cursor()
                    try:
                        def _pick_existing_column(table_name: str, candidates: list[str]) -> str | None:
                            try:
                                mcur.execute(
                                    """
                                    SELECT LOWER(COLUMN_NAME)
                                    FROM information_schema.columns
                                    WHERE table_schema = DATABASE() AND table_name = %s
                                    """,
                                    (table_name,),
                                )
                                cols = {str(r[0]).lower() for r in (mcur.fetchall() or []) if r and r[0]}
                                for c in candidates:
                                    if c.lower() in cols:
                                        return c
                            except Exception:
                                return None
                            return None

                        asset_location_col = _pick_existing_column(
                            "ITAD_asset_info",
                            ["location", "destination", "site", "de_destination", "final_destination"],
                        )
                        asset_pallet_col = _pick_existing_column(
                            "ITAD_asset_info",
                            ["pallet_id", "pallet", "palletid"],
                        )
                        qa_location_col = _pick_existing_column(
                            "ITAD_QA_App",
                            ["scanned_location", "location", "destination", "scan_location", "warehouse_location"],
                        )

                        asset_location_expr = (
                            f"a.`{asset_location_col}`" if asset_location_col else "NULL"
                        )
                        asset_pallet_expr = (
                            f"a.`{asset_pallet_col}`" if asset_pallet_col else "NULL"
                        )
                        qa_location_group_expr = (
                            f"COALESCE(q.`{qa_location_col}`, '')" if qa_location_col else "''"
                        )

                        ph = ",".join(["%s"] * len(sampled_stockids))
                        q = (
                            f"SELECT a.stockid, a.de_completed_by, {asset_location_expr} AS asset_location, {asset_pallet_expr} AS asset_pallet_id, "
                            "u.last_sorting_with_user, u.last_sorting_user, "
                            "x.last_sorting_any, x.last_sorting_any_user, x.last_sorting_any_location "
                            "FROM ITAD_asset_info a "
                            "LEFT JOIN ("
                            "  SELECT q.stockid, "
                            "         MAX(q.added_date) AS last_sorting_with_user, "
                            "         SUBSTRING_INDEX(GROUP_CONCAT(q.username ORDER BY q.added_date DESC SEPARATOR '||'), '||', 1) AS last_sorting_user "
                            "  FROM ITAD_QA_App q "
                            f"  WHERE q.stockid IN ({ph}) "
                            "    AND TRIM(COALESCE(q.stockid, '')) <> '' "
                            "    AND TRIM(COALESCE(q.username, '')) <> '' "
                            "  GROUP BY q.stockid"
                            ") u ON u.stockid = a.stockid "
                            "LEFT JOIN ("
                            "  SELECT q.stockid, "
                            "         MAX(q.added_date) AS last_sorting_any, "
                            "         SUBSTRING_INDEX(GROUP_CONCAT(COALESCE(q.username, '') ORDER BY q.added_date DESC SEPARATOR '||'), '||', 1) AS last_sorting_any_user, "
                            f"         SUBSTRING_INDEX(GROUP_CONCAT({qa_location_group_expr} ORDER BY q.added_date DESC SEPARATOR '||'), '||', 1) AS last_sorting_any_location "
                            "  FROM ITAD_QA_App q "
                            f"  WHERE q.stockid IN ({ph}) "
                            "    AND TRIM(COALESCE(q.stockid, '')) <> '' "
                            "  GROUP BY q.stockid"
                            ") x ON x.stockid = a.stockid "
                            f"WHERE a.stockid IN ({ph})"
                        )
                        params = tuple(sampled_stockids) + tuple(sampled_stockids) + tuple(sampled_stockids)
                        mcur.execute(q, params)
                        for r in mcur.fetchall() or []:
                            sid = str(r[0]) if r and r[0] is not None else None
                            if not sid:
                                continue
                            sample_meta[sid] = {
                                "qaCompletedBy": str(r[1]) if len(r) > 1 and r[1] is not None else None,
                                "assetLocation": str(r[2]) if len(r) > 2 and r[2] is not None else None,
                                "assetPalletId": str(r[3]) if len(r) > 3 and r[3] is not None else None,
                                "lastSortingWithUser": _to_iso(r[4] if len(r) > 4 else None),
                                "lastSortingUsername": str(r[5]) if len(r) > 5 and r[5] is not None else None,
                                "lastSortingAny": _to_iso(r[6] if len(r) > 6 else None),
                                "lastSortingAnyUsername": str(r[7]) if len(r) > 7 and r[7] is not None else None,
                                "lastSortingAnyLocation": str(r[8]) if len(r) > 8 and r[8] is not None else None,
                            }
                    finally:
                        try:
                            mcur.close()
                            meta_conn.close()
                        except Exception:
                            pass

            def _enrich_sample(row, default_reason: str):
                stockid = str(row[0]) if row and row[0] is not None else None
                qa_completed = _to_iso(row[1] if len(row) > 1 else None)
                last_sorting_added = _to_iso(row[2] if len(row) > 2 else None)
                reason = str(row[4]) if len(row) > 4 and row[4] is not None else default_reason

                meta = sample_meta.get(stockid or "", {})
                qa_dt = _parse_dt(qa_completed)
                sorting_with_user_dt = _parse_dt(last_sorting_added or meta.get("lastSortingWithUser"))
                lag_hours = None
                hours_since_qa_completed = None
                if qa_dt:
                    hours_since_qa_completed = round((now_utc - qa_dt).total_seconds() / 3600.0, 2)
                if qa_dt and sorting_with_user_dt:
                    lag_hours = round((sorting_with_user_dt - qa_dt).total_seconds() / 3600.0, 2)

                return {
                    "stockid": stockid,
                    "qaCompletedDate": qa_completed,
                    "qaCompletedBy": meta.get("qaCompletedBy"),
                    "lastSortingAddedDate": last_sorting_added or meta.get("lastSortingWithUser"),
                    "lastSortingUsername": meta.get("lastSortingUsername"),
                    "latestSortingAnyDate": meta.get("lastSortingAny"),
                    "latestSortingAnyUsername": meta.get("lastSortingAnyUsername"),
                    "location": meta.get("lastSortingAnyLocation") or meta.get("assetLocation"),
                    "assetPalletId": (str(row[3]) if len(row) > 3 and row[3] is not None else None) or meta.get("assetPalletId"),
                    "hoursSinceQaCompleted": hours_since_qa_completed,
                    "lagHours": lag_hours,
                    "reason": reason,
                }

            awaiting_samples = [_enrich_sample(r, "unknown") for r in awaiting_rows]
            decremented_samples = [_enrich_sample(r, "decremented_by_sorting_scan") for r in decremented_rows]

            return {
                "summary": {
                    "windowDays": days,
                    "candidateStockids": candidate_total,
                    "awaitingSorting": awaiting_total,
                    "decrementedBySorting": decremented_total,
                    "missingSortingWithUsername": missing_sorting_with_username,
                    "sortingOlderThanQaCompleted": sorting_older_than_qa_completed,
                    "blankUsernameAfterQaCompleted": blank_username_after_de,
                    "excludedByA100Pallet": excluded_by_a100,
                    "qaCompletedByPresent": de_completed_by_present,
                    # Backward-compat aliases for existing UI consumers.
                    "decrementedByQa": decremented_total,
                    "missingQaWithUsername": missing_sorting_with_username,
                    "qaOlderThanDeCompleted": sorting_older_than_qa_completed,
                    "blankUsernameAfterDe": blank_username_after_de,
                    "deCompletedByPresent": de_completed_by_present,
                    "reconciliationGap": int(candidate_total - (awaiting_total + decremented_total)),
                    "qaFieldNamingNote": "ITAD_asset_info de_* fields currently represent QA completion; ITAD_QA_App rows represent Sorting scans.",
                    "sampleAwaitingCount": len(awaiting_samples),
                    "sampleDecrementedCount": len(decremented_samples),
                    "generatedAt": datetime.now(UTC).isoformat(),
                },
                "awaitingSamples": awaiting_samples,
                "decrementedSamples": decremented_samples,
            }
        except Exception as exc:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(exc))

    return router
