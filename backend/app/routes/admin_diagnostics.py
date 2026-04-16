from typing import Callable
from datetime import UTC, datetime
import os
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

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

        def _is_seven_digit_stockid(v):
            return bool(re.fullmatch(r"\d{7}", str(v or "").strip()))

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
            "sampleExcludedBy7DigitStockid": 0,
            "sampleWithPayloadStockid": 0,
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
                SELECT
                    e.ts,
                    e.job_id,
                    COALESCE(NULLIF(TRIM(le.stockid), ''), NULLIF(TRIM(e.system_serial), ''), NULLIF(TRIM(e.job_id), '')) AS key_id,
                    e.initials,
                    e.device_type,
                    NULLIF(TRIM(le.stockid), '') AS payload_stockid
                FROM erasures e
                LEFT JOIN local_erasures le ON le.job_id = e.job_id
                WHERE e.event = 'success' AND e.ts >= ?
                ORDER BY e.ts DESC
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
                    # Schema-safe serial mapping for ITAD_asset_info_blancco.
                    blancco_serial_col = None
                    try:
                        mcur.execute(
                            """
                            SELECT LOWER(COLUMN_NAME)
                            FROM information_schema.columns
                            WHERE table_schema = DATABASE() AND table_name = 'ITAD_asset_info_blancco'
                            """
                        )
                        blancco_cols = {str(r[0]).lower() for r in (mcur.fetchall() or []) if r and r[0]}
                        for candidate in ("serial", "serialnumber", "system_serial"):
                            if candidate in blancco_cols:
                                blancco_serial_col = candidate
                                break
                    except Exception:
                        blancco_serial_col = None

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

                    unresolved_vals = [v for v in vals if _norm(v) and _norm(v) not in key_to_stockid]
                    if unresolved_vals and blancco_serial_col:
                        ph_un = ",".join(["%s"] * len(unresolved_vals))
                        q_bl = (
                            f"SELECT stockid, `{blancco_serial_col}` FROM ITAD_asset_info_blancco "
                            f"WHERE stockid IN ({ph_un}) OR `{blancco_serial_col}` IN ({ph_un})"
                        )
                        try:
                            mcur.execute(q_bl, tuple(unresolved_vals) + tuple(unresolved_vals))
                            bl_rows = mcur.fetchall() or []
                            for br in bl_rows:
                                bsid = str(br[0]) if br and br[0] is not None else None
                                bserial = str(br[1]) if br and len(br) > 1 and br[1] is not None else None
                                if bsid:
                                    key_to_stockid[_norm(bsid)] = bsid
                                if bserial and bsid:
                                    key_to_stockid[_norm(bserial)] = bsid
                        except Exception:
                            pass

                    sids = list({v for v in key_to_stockid.values() if v})
                    if sids:
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
                        asset_last_update_col = _pick_existing_column(
                            "ITAD_asset_info",
                            ["last_update", "updated_at", "last_modified", "modified_at"],
                        )

                        asset_location_expr = f"`{asset_location_col}`" if asset_location_col else "NULL"
                        asset_pallet_expr = f"`{asset_pallet_col}`" if asset_pallet_col else "NULL"
                        asset_last_update_expr = f"`{asset_last_update_col}`" if asset_last_update_col else "NULL"

                        ph = ",".join(["%s"] * len(sids))
                        mcur.execute(
                            f"SELECT DISTINCT stockid FROM ITAD_QA_App WHERE stockid IN ({ph})",
                            tuple(sids),
                        )
                        qa_stockids = {str(r[0]) for r in (mcur.fetchall() or []) if r and r[0]}

                        mcur.execute(
                            f"""
                            SELECT
                                stockid,
                                de_completed_by,
                                de_completed_date,
                                {asset_location_expr} AS asset_location,
                                {asset_pallet_expr} AS asset_pallet_id,
                                {asset_last_update_expr} AS asset_last_update
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
                            qa_meta_by_stockid[sid]["assetLocation"] = str(ar[3]) if len(ar) > 3 and ar[3] is not None else None
                            qa_meta_by_stockid[sid]["assetPalletId"] = str(ar[4]) if len(ar) > 4 and ar[4] is not None else None
                            qa_meta_by_stockid[sid]["assetLastUpdate"] = _to_iso(ar[5] if len(ar) > 5 else None)

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
            ts, job_id, key_id, initials, device_type, payload_stockid = row
            nkey = _norm(key_id)
            stockid = key_to_stockid.get(nkey)
            has_asset = bool(stockid)
            meta = qa_meta_by_stockid.get(stockid or "", {})
            last_qa_date = meta.get("qaCompletedDate") or meta.get("lastQaDate")
            has_qa = bool(stockid and (stockid in qa_stockids or last_qa_date or meta.get("qaByDeCompletedBy")))
            if has_asset:
                summary["mariaAssetMatchesInSample"] += 1
            if has_qa:
                summary["mariaQaMatchesInSample"] += 1

            erasure_dt = _parse_dt(ts)
            qa_dt = _parse_dt(last_qa_date)
            last_update_dt = _parse_dt(meta.get("assetLastUpdate"))
            qa_by = (meta.get("qaByDeCompletedBy") or "").strip()
            awaiting_by_rule = None
            qa_status_reason = "no_asset_match"
            qa_lag_hours = None
            if _is_seven_digit_stockid(payload_stockid) or _is_seven_digit_stockid(key_id):
                awaiting_by_rule = False
                qa_status_reason = "deducted_itad_7_digit_input_key"
                summary["sampleExcludedBy7DigitStockid"] += 1
            elif has_asset:
                if _is_seven_digit_stockid(stockid):
                    awaiting_by_rule = False
                    qa_status_reason = "deducted_itad_7_digit_stockid"
                    summary["sampleExcludedBy7DigitStockid"] += 1
                elif erasure_dt and qa_dt:
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
                elif qa_by and last_update_dt and (not erasure_dt or last_update_dt >= erasure_dt):
                    awaiting_by_rule = False
                    qa_status_reason = "deducted_by_de_completed_by_last_update_proxy"
                    if erasure_dt:
                        qa_lag_hours = round((last_update_dt - erasure_dt).total_seconds() / 3600.0, 2)
                else:
                    awaiting_by_rule = True
                    qa_status_reason = "awaiting_no_qa_found"

            if awaiting_by_rule is True:
                summary["sampleAwaitingQaByRule"] += 1
            elif awaiting_by_rule is False:
                summary["sampleDeductedByQaAfterErasure"] += 1
            if payload_stockid:
                summary["sampleWithPayloadStockid"] += 1

            samples.append({
                "ts": _to_iso(ts),
                "job_id": job_id,
                "key": key_id,
                "payload_stockid": payload_stockid,
                "initials": initials,
                "device_type": device_type,
                "asset_match": has_asset,
                "stockid": stockid,
                "qa_match": has_qa,
                "last_qa_date": last_qa_date,
                "qa_by_de_completed_by": meta.get("qaByDeCompletedBy"),
                "last_qa_username": meta.get("lastQaUsername"),
                "last_update": meta.get("assetLastUpdate") or last_qa_date,
                "location": meta.get("assetLocation"),
                "pallet_id": meta.get("assetPalletId"),
                "awaiting_qa_by_rule": awaiting_by_rule,
                "qa_status_reason": qa_status_reason,
                "qa_lag_hours": qa_lag_hours,
            })

        return {
            "summary": summary,
            "samples": samples,
        }

    @router.get("/admin/erasure-reconciliation")
    def admin_erasure_reconciliation(request: Request, date: str | None = None, limit: int = 50):
        """Admin-only diagnostic: reconcile top total vs engineer/category cards for a specific day."""
        require_admin(request)
        sample_limit = max(10, min(int(limit or 50), 200))
        target_date = (str(date).strip() if date else "") or datetime.now(UTC).date().isoformat()

        visible_types = ("laptops_desktops", "servers", "macs", "mobiles")
        type_placeholders = ",".join(["?"] * len(visible_types))

        import sqlite3

        conn = sqlite3.connect(db_module.DB_PATH)
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(1) FROM erasures WHERE date = ?", (target_date,))
            day_total_all_events = int((cur.fetchone() or [0])[0] or 0)

            cur.execute("SELECT COUNT(1) FROM erasures WHERE date = ? AND event = 'success'", (target_date,))
            day_success_total = int((cur.fetchone() or [0])[0] or 0)

            cur.execute("SELECT COUNT(1) FROM erasures WHERE date = ? AND event = 'failure'", (target_date,))
            day_failure_total = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                """
                SELECT COUNT(1)
                FROM erasures
                WHERE date = ?
                  AND event = 'success'
                  AND TRIM(COALESCE(initials, '')) <> ''
                """,
                (target_date,),
            )
            day_success_with_initials = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                """
                SELECT COUNT(1)
                FROM erasures
                WHERE date = ?
                  AND event = 'success'
                  AND TRIM(COALESCE(initials, '')) = ''
                """,
                (target_date,),
            )
            day_success_missing_initials = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                f"""
                SELECT COUNT(1)
                FROM erasures
                WHERE date = ?
                  AND event = 'success'
                  AND LOWER(TRIM(COALESCE(device_type, ''))) IN ({type_placeholders})
                """,
                (target_date, *visible_types),
            )
            day_success_visible_types = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                f"""
                SELECT COUNT(1)
                FROM erasures
                WHERE date = ?
                  AND event = 'success'
                  AND LOWER(TRIM(COALESCE(device_type, ''))) IN ({type_placeholders})
                  AND TRIM(COALESCE(initials, '')) <> ''
                """,
                (target_date, *visible_types),
            )
            day_success_visible_with_initials = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                f"""
                SELECT COUNT(1)
                FROM erasures
                WHERE date = ?
                  AND event = 'success'
                  AND LOWER(TRIM(COALESCE(device_type, ''))) NOT IN ({type_placeholders})
                """,
                (target_date, *visible_types),
            )
            day_success_outside_visible_types = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                """
                SELECT COUNT(1)
                FROM erasures
                WHERE date = ?
                  AND event = 'success'
                  AND CAST(SUBSTR(COALESCE(ts, ''), 12, 2) AS INTEGER) BETWEEN 8 AND 15
                """,
                (target_date,),
            )
            day_success_workday_8_to_16 = int((cur.fetchone() or [0])[0] or 0)
            day_success_outside_workday = max(0, day_success_total - day_success_workday_8_to_16)

            cur.execute(
                f"""
                SELECT COALESCE(NULLIF(LOWER(TRIM(device_type)), ''), '(blank)') AS device_type_key, COUNT(1) AS total
                FROM erasures
                WHERE date = ?
                  AND event = 'success'
                  AND LOWER(TRIM(COALESCE(device_type, ''))) NOT IN ({type_placeholders})
                GROUP BY device_type_key
                ORDER BY total DESC
                LIMIT ?
                """,
                (target_date, *visible_types, sample_limit),
            )
            outside_type_breakdown = [
                {"deviceType": row[0], "count": int(row[1] or 0)}
                for row in (cur.fetchall() or [])
            ]

            cur.execute(
                """
                SELECT ts, job_id, initials, device_type
                FROM erasures
                WHERE date = ?
                  AND event = 'success'
                  AND TRIM(COALESCE(initials, '')) = ''
                ORDER BY ts DESC
                LIMIT ?
                """,
                (target_date, sample_limit),
            )
            missing_initials_samples = [
                {
                    "ts": row[0],
                    "job_id": row[1],
                    "initials": row[2],
                    "device_type": row[3],
                }
                for row in (cur.fetchall() or [])
            ]

            cur.execute(
                f"""
                SELECT ts, job_id, initials, device_type
                FROM erasures
                WHERE date = ?
                  AND event = 'success'
                  AND LOWER(TRIM(COALESCE(device_type, ''))) NOT IN ({type_placeholders})
                ORDER BY ts DESC
                LIMIT ?
                """,
                (target_date, *visible_types, sample_limit),
            )
            outside_visible_type_samples = [
                {
                    "ts": row[0],
                    "job_id": row[1],
                    "initials": row[2],
                    "device_type": row[3],
                }
                for row in (cur.fetchall() or [])
            ]

            cur.execute(
                """
                SELECT
                    serial_norm,
                    COUNT(1) AS failure_count
                FROM (
                    SELECT UPPER(
                        REPLACE(REPLACE(REPLACE(TRIM(COALESCE(NULLIF(system_serial, ''), NULLIF(disk_serial, ''))), '-', ''), ' ', ''), ':', '')
                    ) AS serial_norm
                    FROM erasures
                    WHERE date = ?
                      AND event = 'failure'
                      AND TRIM(COALESCE(NULLIF(system_serial, ''), NULLIF(disk_serial, ''))) <> ''
                ) f
                WHERE serial_norm <> ''
                GROUP BY serial_norm
                HAVING failure_count > 1
                ORDER BY failure_count DESC, serial_norm
                LIMIT ?
                """,
                (target_date, sample_limit),
            )
            failed_duplicate_serials = [
                {"serial": row[0], "failureCount": int(row[1] or 0)}
                for row in (cur.fetchall() or [])
            ]

            cur.execute(
                """
                SELECT
                    f.serial_norm,
                    f.failure_count,
                    COALESCE(s.success_count, 0) AS success_count
                FROM (
                    SELECT
                        UPPER(REPLACE(REPLACE(REPLACE(TRIM(COALESCE(NULLIF(system_serial, ''), NULLIF(disk_serial, ''))), '-', ''), ' ', ''), ':', '')) AS serial_norm,
                        COUNT(1) AS failure_count
                    FROM erasures
                    WHERE date = ?
                      AND event = 'failure'
                      AND TRIM(COALESCE(NULLIF(system_serial, ''), NULLIF(disk_serial, ''))) <> ''
                    GROUP BY serial_norm
                ) f
                INNER JOIN (
                    SELECT
                        UPPER(REPLACE(REPLACE(REPLACE(TRIM(COALESCE(NULLIF(system_serial, ''), NULLIF(disk_serial, ''))), '-', ''), ' ', ''), ':', '')) AS serial_norm,
                        COUNT(1) AS success_count
                    FROM erasures
                    WHERE date = ?
                      AND event = 'success'
                      AND TRIM(COALESCE(NULLIF(system_serial, ''), NULLIF(disk_serial, ''))) <> ''
                    GROUP BY serial_norm
                ) s ON s.serial_norm = f.serial_norm
                WHERE f.serial_norm <> ''
                ORDER BY f.failure_count DESC, s.success_count DESC, f.serial_norm
                LIMIT ?
                """,
                (target_date, target_date, sample_limit),
            )
            failure_then_success_serials = [
                {
                    "serial": row[0],
                    "failureCount": int(row[1] or 0),
                    "successCount": int(row[2] or 0),
                }
                for row in (cur.fetchall() or [])
            ]
        finally:
            cur.close()
            conn.close()

        reconciliation = {
            "totalMinusSuccess": max(0, day_total_all_events - day_success_total),
            "successMinusVisibleWithInitials": max(0, day_success_total - day_success_visible_with_initials),
            "missingInitialsGap": day_success_missing_initials,
            "outsideVisibleTypeGap": day_success_outside_visible_types,
            "overlapGap": max(
                0,
                day_success_missing_initials + day_success_outside_visible_types - (day_success_total - day_success_visible_with_initials),
            ),
        }

        return {
            "summary": {
                "date": target_date,
                "visibleTypes": list(visible_types),
                "dayTotalAllEvents": day_total_all_events,
                "daySuccessTotal": day_success_total,
                "dayFailureTotal": day_failure_total,
                "daySuccessWithInitials": day_success_with_initials,
                "daySuccessMissingInitials": day_success_missing_initials,
                "daySuccessVisibleTypes": day_success_visible_types,
                "daySuccessVisibleWithInitials": day_success_visible_with_initials,
                "daySuccessOutsideVisibleTypes": day_success_outside_visible_types,
                "daySuccessWorkday8To16": day_success_workday_8_to_16,
                "daySuccessOutsideWorkday": day_success_outside_workday,
                "failedDuplicateSerialCount": len(failed_duplicate_serials),
                "failureThenSuccessSerialCount": len(failure_then_success_serials),
                "reconciliation": reconciliation,
                "generatedAt": datetime.now(UTC).isoformat(),
            },
            "outsideTypeBreakdown": outside_type_breakdown,
            "missingInitialsSamples": missing_initials_samples,
            "outsideVisibleTypeSamples": outside_visible_type_samples,
            "failedDuplicateSerials": failed_duplicate_serials,
            "failureThenSuccessSerials": failure_then_success_serials,
        }

    @router.get("/admin/goods-in-evidence")
    def admin_goods_in_evidence(request: Request, days: int = 90, limit: int = 50):
        """Admin-only diagnostic: prove Goods In queue and received-today matching logic."""
        require_admin(request)
        days = max(1, min(int(days or 90), 180))
        limit = max(10, min(int(limit or 50), 200))

        goods_in_enabled = str(os.getenv("GOODS_IN_ENABLED", "false")).strip().lower() in ("1", "true", "yes", "on")
        goods_in_api_url = str(os.getenv("GOODS_IN_API_BASE_URL", "")).strip()
        goods_in_api_token = str(os.getenv("GOODS_IN_API_TOKEN", "")).strip()
        goods_in_auth_header = str(os.getenv("GOODS_IN_API_AUTH_HEADER", "Authorization")).strip() or "Authorization"
        goods_in_auth_scheme_raw = str(os.getenv("GOODS_IN_API_AUTH_SCHEME", "bearer")).strip().lower() or "bearer"
        goods_in_auth_scheme_key = goods_in_auth_scheme_raw.replace(" ", "").replace("_", "").replace("-", "")

        if goods_in_auth_scheme_key in ("secrettoken", "token"):
            goods_in_auth_scheme = "token"
        elif goods_in_auth_scheme_key in ("apikey", "api", "api_key"):
            goods_in_auth_scheme = "apikey"
        elif goods_in_auth_scheme_key in ("raw", "none"):
            goods_in_auth_scheme = "raw"
        else:
            goods_in_auth_scheme = "bearer"
        api_fallback_error = None

        def _parse_goods_in_dt(raw_value: str | None):
            if raw_value is None:
                return None
            value = str(raw_value).strip()
            if not value:
                return None

            normalized = value.replace("T", " ").replace("Z", "").strip()
            for fmt in (
                "%d-%m-%Y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%d/%m/%Y",
            ):
                try:
                    return datetime.strptime(normalized, fmt).replace(tzinfo=UTC)
                except Exception:
                    continue
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            except Exception:
                return None

        def _iso(dt):
            if dt is None:
                return None
            return dt.astimezone(UTC).isoformat()

        if goods_in_enabled and goods_in_api_url and goods_in_api_token:
            try:
                req = urllib.request.Request(goods_in_api_url, method="GET")
                if goods_in_auth_scheme in ("raw",):
                    auth_value = goods_in_api_token
                elif goods_in_auth_scheme in ("token",):
                    auth_value = f"Token {goods_in_api_token}"
                elif goods_in_auth_scheme in ("apikey", "api_key"):
                    auth_value = goods_in_api_token
                elif goods_in_api_token.lower().startswith("bearer "):
                    auth_value = goods_in_api_token
                else:
                    auth_value = f"Bearer {goods_in_api_token}"
                req.add_header(goods_in_auth_header, auth_value)
                req.add_header("Accept", "application/xml, text/xml")

                with urllib.request.urlopen(req, timeout=15) as resp:
                    payload = resp.read()

                root = ET.fromstring(payload)
                all_rows = []
                for grn in root.findall(".//grn"):
                    order_number = (grn.findtext("order_number") or "").strip()
                    order_type = (grn.findtext("order_type") or "").strip()
                    operator = (grn.findtext("operator") or "").strip()
                    total_items_raw = (grn.findtext("total_items") or "").strip()
                    arrival_raw = (grn.findtext("arrival_date") or "").strip()
                    start_raw = (grn.findtext("start_time") or "").strip()
                    finish_raw = (grn.findtext("finish_time") or "").strip()

                    arrival_dt = _parse_goods_in_dt(arrival_raw)
                    start_dt = _parse_goods_in_dt(start_raw)
                    finish_dt = _parse_goods_in_dt(finish_raw)
                    event_dt = finish_dt or start_dt or arrival_dt

                    all_rows.append(
                        {
                            "orderNumber": order_number,
                            "orderType": order_type,
                            "operator": operator,
                            "totalItems": int(total_items_raw) if total_items_raw.isdigit() else None,
                            "arrivalRaw": arrival_raw,
                            "startRaw": start_raw,
                            "finishRaw": finish_raw,
                            "arrivalDt": arrival_dt,
                            "startDt": start_dt,
                            "finishDt": finish_dt,
                            "eventDt": event_dt,
                        }
                    )

                cutoff = datetime.now(UTC).timestamp() - (days * 86400)
                filtered_rows = []
                for row in all_rows:
                    dt = row.get("eventDt")
                    if dt is None:
                        filtered_rows.append(row)
                        continue
                    if dt.timestamp() >= cutoff:
                        filtered_rows.append(row)

                latest_by_order = {}
                for row in filtered_rows:
                    key = row.get("orderNumber") or ""
                    if not key:
                        key = f"__row__{id(row)}"
                    prev = latest_by_order.get(key)
                    prev_dt = prev.get("eventDt") if isinstance(prev, dict) else None
                    row_dt = row.get("eventDt")
                    if prev is None:
                        latest_by_order[key] = row
                        continue
                    if row_dt and (not prev_dt or row_dt > prev_dt):
                        latest_by_order[key] = row

                latest_rows = list(latest_by_order.values())
                latest_rows.sort(key=lambda r: (r.get("eventDt") or datetime.min.replace(tzinfo=UTC)), reverse=True)

                today_date = datetime.now(UTC).date()
                awaiting_rows = [r for r in latest_rows if not r.get("finishDt")]
                received_today_rows = [r for r in latest_rows if r.get("finishDt") and r.get("finishDt").date() == today_date]

                awaiting_samples = []
                for row in awaiting_rows[:limit]:
                    awaiting_samples.append(
                        {
                            "grnOrderNumber": row.get("orderNumber") or "",
                            "automationOrderNumber": row.get("orderNumber") or "",
                            "lastGrnDate": _iso(row.get("arrivalDt") or row.get("startDt")),
                            "receiptStatus": "PENDING",
                            "orderStatus": row.get("orderType") or None,
                            "dateAdded": _iso(row.get("startDt")),
                            "dateRequired": _iso(row.get("arrivalDt")),
                            "shipDate": _iso(row.get("finishDt")),
                            "addedDate": _iso(row.get("startDt")),
                            "matchState": "awaiting_receipt_match",
                        }
                    )

                received_today_samples = []
                for row in received_today_rows[:limit]:
                    received_today_samples.append(
                        {
                            "grnOrderNumber": row.get("orderNumber") or "",
                            "automationOrderNumber": row.get("orderNumber") or "",
                            "lastGrnDate": _iso(row.get("arrivalDt") or row.get("startDt")),
                            "lastReceivedDate": _iso(row.get("finishDt")),
                            "receiptStatus": "RECEIVED",
                            "orderStatus": row.get("orderType") or None,
                            "dateAdded": _iso(row.get("startDt")),
                            "dateRequired": _iso(row.get("arrivalDt")),
                            "shipDate": _iso(row.get("finishDt")),
                            "addedDate": _iso(row.get("startDt")),
                            "matchState": "matched_received_today",
                        }
                    )

                total_orders = len(latest_rows)
                awaiting_count = len(awaiting_rows)
                matched_count = max(0, total_orders - awaiting_count)

                return {
                    "summary": {
                        "windowDays": days,
                        "totalBookedOrders": total_orders,
                        "awaitingReceiptMatch": awaiting_count,
                        "matchedReceivedAnyDay": matched_count,
                        "bookedAndReceivedToday": len(received_today_rows),
                        "source": "goods-in-api",
                        "apiAuthHeader": goods_in_auth_header,
                        "apiAuthScheme": goods_in_auth_scheme,
                        "statusField": "finish_time",
                        "grnDateField": "arrival_date",
                        "ordersDateField": "start_time/finish_time",
                        "apiAuthHeader": goods_in_auth_header,
                        "apiAuthScheme": goods_in_auth_scheme,
                        "sampleAwaitingCount": len(awaiting_samples),
                        "sampleReceivedTodayCount": len(received_today_samples),
                        "generatedAt": datetime.now(UTC).isoformat(),
                    },
                    "awaitingSamples": awaiting_samples,
                    "receivedTodaySamples": received_today_samples,
                }
            except urllib.error.HTTPError as exc:
                err_snippet = ""
                try:
                    body = exc.read()
                    if body:
                        err_snippet = body.decode("utf-8", errors="ignore").strip().replace("\n", " ")[:180]
                except Exception:
                    err_snippet = ""
                if err_snippet:
                    api_fallback_error = f"Goods In API HTTP {exc.code}: {err_snippet}"
                else:
                    api_fallback_error = f"Goods In API HTTP {exc.code}"
            except urllib.error.URLError:
                api_fallback_error = "Goods In API unavailable"
            except Exception:
                api_fallback_error = "Goods In API parse failure"

        conn = None
        try:
            conn = get_mariadb_connection()
            if not conn:
                return JSONResponse(status_code=503, content={"status": "fail", "detail": "MariaDB connection failed"})

            cur = conn.cursor()
            try:
                grn_table = "ITAD_GRN"
                orders_table = "Automation_AllOrders"

                cur.execute(
                    """
                    SELECT LOWER(column_name)
                    FROM information_schema.columns
                    WHERE table_schema = DATABASE()
                      AND table_name = %s
                    """,
                    (grn_table,),
                )
                grn_cols = {str(r[0]).lower() for r in (cur.fetchall() or []) if r and r[0]}

                cur.execute(
                    """
                    SELECT LOWER(column_name)
                    FROM information_schema.columns
                    WHERE table_schema = DATABASE()
                      AND table_name = %s
                    """,
                    (orders_table,),
                )
                orders_cols = {str(r[0]).lower() for r in (cur.fetchall() or []) if r and r[0]}

                if "order_number" not in grn_cols or "order_number" not in orders_cols:
                    raise HTTPException(
                        status_code=500,
                        detail="Goods In evidence requires order_number in both ITAD_GRN and Automation_AllOrders",
                    )

                status_col = "receipt_status" if "receipt_status" in orders_cols else None
                if not status_col:
                    raise HTTPException(
                        status_code=500,
                        detail="Goods In evidence requires receipt_status in Automation_AllOrders",
                    )

                grn_date_col = next((c for c in ("date_received", "date_added", "added_date") if c in grn_cols), None)
                orders_date_col = next((c for c in ("added_date", "date_added", "date_received") if c in orders_cols), None)

                lookback_clause = ""
                if grn_date_col:
                    lookback_clause = f" AND DATE(g.{grn_date_col}) >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)"

                q_total_grn = (
                    "SELECT COUNT(DISTINCT TRIM(COALESCE(g.order_number, ''))) "
                    f"FROM {grn_table} g "
                    "WHERE TRIM(COALESCE(g.order_number, '')) <> ''"
                    f"{lookback_clause}"
                )
                cur.execute(q_total_grn)
                row = cur.fetchone()
                total_grn_orders = int(row[0]) if row and row[0] is not None else 0

                q_unmatched = (
                    "SELECT COUNT(DISTINCT TRIM(COALESCE(g.order_number, ''))) "
                    f"FROM {grn_table} g "
                    "LEFT JOIN ("
                    "    SELECT DISTINCT TRIM(COALESCE(order_number, '')) AS order_number "
                    f"    FROM {orders_table} "
                    "    WHERE TRIM(COALESCE(order_number, '')) <> '' "
                    f"      AND UPPER(TRIM(COALESCE({status_col}, ''))) IN ('RECIEVED', 'RECEIVED')"
                    ") r ON r.order_number = TRIM(COALESCE(g.order_number, '')) "
                    "WHERE TRIM(COALESCE(g.order_number, '')) <> ''"
                    f"{lookback_clause} "
                    "AND r.order_number IS NULL"
                )
                cur.execute(q_unmatched)
                row = cur.fetchone()
                queue_unmatched = int(row[0]) if row and row[0] is not None else 0

                received_today_matched = 0
                if orders_date_col:
                    q_received_today = (
                        "SELECT COUNT(DISTINCT TRIM(COALESCE(g.order_number, ''))) "
                        f"FROM {grn_table} g "
                        "INNER JOIN ("
                        "    SELECT DISTINCT TRIM(COALESCE(order_number, '')) AS order_number "
                        f"    FROM {orders_table} "
                        "    WHERE TRIM(COALESCE(order_number, '')) <> '' "
                        f"      AND UPPER(TRIM(COALESCE({status_col}, ''))) IN ('RECIEVED', 'RECEIVED') "
                        f"      AND DATE({orders_date_col}) = CURDATE()"
                        ") rt ON rt.order_number = TRIM(COALESCE(g.order_number, '')) "
                        "WHERE TRIM(COALESCE(g.order_number, '')) <> ''"
                        f"{lookback_clause}"
                    )
                    cur.execute(q_received_today)
                    row = cur.fetchone()
                    received_today_matched = int(row[0]) if row and row[0] is not None else 0

                grn_date_select = f"MAX(g.{grn_date_col})" if grn_date_col else "NULL"
                order_status_col = "order_status" if "order_status" in orders_cols else None
                date_added_col = "date_added" if "date_added" in orders_cols else None
                date_required_col = "date_required" if "date_required" in orders_cols else None
                ship_date_col = "ship_date" if "ship_date" in orders_cols else None
                added_date_col = "added_date" if "added_date" in orders_cols else None

                sort_candidates = [c for c in (added_date_col, date_added_col, ship_date_col, date_required_col) if c]
                sort_expr = (", ".join([f"COALESCE(o.{c}, '')" for c in sort_candidates]) if sort_candidates else "TRIM(COALESCE(o.order_number, ''))")

                def _latest_field_expr(column_name: str | None, alias: str) -> str:
                    if not column_name:
                        return f"NULL AS {alias}"
                    return (
                        "SUBSTRING_INDEX("
                        f"GROUP_CONCAT(COALESCE(o.{column_name}, '') ORDER BY {sort_expr} DESC SEPARATOR '||'), "
                        "'||', "
                        "1"
                        f") AS {alias}"
                    )

                q_automation_latest = (
                    "SELECT "
                    "    TRIM(COALESCE(o.order_number, '')) AS order_number, "
                    f"    {_latest_field_expr(status_col, 'receipt_status')}, "
                    f"    {_latest_field_expr(order_status_col, 'order_status')}, "
                    f"    {_latest_field_expr(date_added_col, 'date_added')}, "
                    f"    {_latest_field_expr(date_required_col, 'date_required')}, "
                    f"    {_latest_field_expr(ship_date_col, 'ship_date')}, "
                    f"    {_latest_field_expr(added_date_col, 'added_date')} "
                    f"FROM {orders_table} o "
                    "WHERE TRIM(COALESCE(o.order_number, '')) <> '' "
                    "GROUP BY TRIM(COALESCE(o.order_number, ''))"
                )

                q_unmatched_samples = (
                    "SELECT "
                    "    TRIM(COALESCE(g.order_number, '')) AS grn_order_number, "
                    "    ao.order_number AS automation_order_number, "
                    f"    {grn_date_select} AS last_grn_date, "
                    "    ao.receipt_status, "
                    "    ao.order_status, "
                    "    ao.date_added, "
                    "    ao.date_required, "
                    "    ao.ship_date, "
                    "    ao.added_date "
                    f"FROM {grn_table} g "
                    "LEFT JOIN ("
                    "    SELECT DISTINCT TRIM(COALESCE(order_number, '')) AS order_number "
                    f"    FROM {orders_table} "
                    "    WHERE TRIM(COALESCE(order_number, '')) <> '' "
                    f"      AND UPPER(TRIM(COALESCE({status_col}, ''))) IN ('RECIEVED', 'RECEIVED')"
                    ") r ON r.order_number = TRIM(COALESCE(g.order_number, '')) "
                    f"LEFT JOIN ({q_automation_latest}) ao ON ao.order_number = TRIM(COALESCE(g.order_number, '')) "
                    "WHERE TRIM(COALESCE(g.order_number, '')) <> '' "
                    f"{lookback_clause} "
                    "AND r.order_number IS NULL "
                    "GROUP BY TRIM(COALESCE(g.order_number, '')) "
                    "ORDER BY last_grn_date DESC "
                    "LIMIT %s"
                )
                cur.execute(q_unmatched_samples, (limit,))
                unmatched_rows = cur.fetchall() or []

                received_today_rows = []
                if orders_date_col:
                    today_clause = f"AND DATE(o.{orders_date_col}) = CURDATE()"
                    received_date_select = f"MAX(o.{orders_date_col})"
                    q_received_today_samples = (
                        "SELECT "
                        "    TRIM(COALESCE(g.order_number, '')) AS grn_order_number, "
                        "    ao.order_number AS automation_order_number, "
                        f"    {grn_date_select} AS last_grn_date, "
                        f"    {received_date_select} AS last_received_date, "
                        "    ao.receipt_status, "
                        "    ao.order_status, "
                        "    ao.date_added, "
                        "    ao.date_required, "
                        "    ao.ship_date, "
                        "    ao.added_date "
                        f"FROM {grn_table} g "
                        f"INNER JOIN {orders_table} o "
                        "    ON TRIM(COALESCE(o.order_number, '')) = TRIM(COALESCE(g.order_number, '')) "
                        f"LEFT JOIN ({q_automation_latest}) ao ON ao.order_number = TRIM(COALESCE(g.order_number, '')) "
                        "WHERE TRIM(COALESCE(g.order_number, '')) <> '' "
                        "AND TRIM(COALESCE(o.order_number, '')) <> '' "
                        f"AND UPPER(TRIM(COALESCE(o.{status_col}, ''))) IN ('RECIEVED', 'RECEIVED') "
                        f"{today_clause} "
                        f"{lookback_clause} "
                        "GROUP BY TRIM(COALESCE(g.order_number, '')) "
                        "ORDER BY last_received_date DESC "
                        "LIMIT %s"
                    )
                    cur.execute(q_received_today_samples, (limit,))
                    received_today_rows = cur.fetchall() or []
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

            unmatched_samples = []
            for row in unmatched_rows:
                unmatched_samples.append(
                    {
                        "grnOrderNumber": str(row[0]) if row and row[0] is not None else "",
                        "automationOrderNumber": str(row[1]) if row and len(row) > 1 and row[1] is not None else None,
                        "lastGrnDate": _to_iso(row[2] if len(row) > 2 else None),
                        "receiptStatus": str(row[3]) if row and len(row) > 3 and row[3] is not None else None,
                        "orderStatus": str(row[4]) if row and len(row) > 4 and row[4] is not None else None,
                        "dateAdded": _to_iso(row[5] if len(row) > 5 else None),
                        "dateRequired": _to_iso(row[6] if len(row) > 6 else None),
                        "shipDate": _to_iso(row[7] if len(row) > 7 else None),
                        "addedDate": _to_iso(row[8] if len(row) > 8 else None),
                        "matchState": "awaiting_receipt_match",
                    }
                )

            received_today_samples = []
            for row in received_today_rows:
                received_today_samples.append(
                    {
                        "grnOrderNumber": str(row[0]) if row and row[0] is not None else "",
                        "automationOrderNumber": str(row[1]) if row and len(row) > 1 and row[1] is not None else None,
                        "lastGrnDate": _to_iso(row[2] if len(row) > 2 else None),
                        "lastReceivedDate": _to_iso(row[3] if len(row) > 3 else None),
                        "receiptStatus": str(row[4]) if row and len(row) > 4 and row[4] is not None else None,
                        "orderStatus": str(row[5]) if row and len(row) > 5 and row[5] is not None else None,
                        "dateAdded": _to_iso(row[6] if len(row) > 6 else None),
                        "dateRequired": _to_iso(row[7] if len(row) > 7 else None),
                        "shipDate": _to_iso(row[8] if len(row) > 8 else None),
                        "addedDate": _to_iso(row[9] if len(row) > 9 else None),
                        "matchState": "matched_received_today",
                    }
                )

            matched_orders = max(0, total_grn_orders - queue_unmatched)

            return {
                "summary": {
                    "windowDays": days,
                    "totalBookedOrders": total_grn_orders,
                    "awaitingReceiptMatch": queue_unmatched,
                    "matchedReceivedAnyDay": matched_orders,
                    "bookedAndReceivedToday": received_today_matched,
                    "source": "mariadb:ITAD_GRN+Automation_AllOrders",
                    "apiFallbackError": api_fallback_error,
                    "apiAuthHeader": goods_in_auth_header,
                    "apiAuthScheme": goods_in_auth_scheme,
                    "statusField": status_col,
                    "grnDateField": grn_date_col,
                    "ordersDateField": orders_date_col,
                    "sampleAwaitingCount": len(unmatched_samples),
                    "sampleReceivedTodayCount": len(received_today_samples),
                    "generatedAt": datetime.now(UTC).isoformat(),
                },
                "awaitingSamples": unmatched_samples,
                "receivedTodaySamples": received_today_samples,
            }
        except HTTPException:
            raise
        except Exception as exc:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(exc))

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
