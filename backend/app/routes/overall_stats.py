from datetime import UTC, datetime, timedelta
import os
import re
import sqlite3

from fastapi import APIRouter, Request


def create_overall_stats_router(*, qa_export_module, db_module, require_manager_or_admin):
    router = APIRouter()
    qa_export = qa_export_module

    goods_in_queries = {
        "delivered": os.getenv("OVERALL_GOODS_IN_DELIVERED_QUERY", "").strip(),
        "checked_in": os.getenv("OVERALL_GOODS_IN_CHECKED_IN_QUERY", "").strip(),
        "awaiting_ia": os.getenv("OVERALL_GOODS_IN_AWAITING_IA_QUERY", "").strip(),
    }
    goods_in_table_raw = os.getenv("OVERALL_GOODS_IN_TABLE", "ITAD_GRN").strip() or "ITAD_GRN"
    goods_in_table = goods_in_table_raw if re.fullmatch(r"[A-Za-z0-9_]+", goods_in_table_raw) else "ITAD_GRN"
    try:
        goods_in_lookback_days = max(1, int(os.getenv("OVERALL_GOODS_IN_LOOKBACK_DAYS", "90")))
    except Exception:
        goods_in_lookback_days = 90
    try:
        qa_compare_lookback_days = max(1, int(os.getenv("OVERALL_QA_COMPARE_LOOKBACK_DAYS", "30")))
    except Exception:
        qa_compare_lookback_days = 30
    qa_include_audit_master = os.getenv("OVERALL_QA_INCLUDE_AUDIT_MASTER", "false").lower() in ("1", "true", "yes")

    def _run_query_variants(cur, queries: list[str]) -> int:
        last_error = None
        for query in queries:
            try:
                return _run_scalar_query(cur, query)
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        return 0

    def _run_scalar_query(cur, query: str) -> int:
        cur.execute(query)
        row = cur.fetchone()
        if not row or row[0] is None:
            return 0
        return int(row[0])

    def _parse_ts(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        s = str(value).strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    def _compute_db_awaiting_qa(*, include_samples: bool = False, sample_limit: int = 25) -> dict:
        result = {
            "dbAwaitingQa": 0,
            "completedAfterErasure": 0,
            "considered": 0,
            "samples": [],
            "source": "mock",
            "lookbackDays": qa_compare_lookback_days,
        }
        try:
            def _norm_key(v):
                if v is None:
                    return ""
                return re.sub(r"[^A-Za-z0-9]", "", str(v)).upper()

            start_dt = datetime.now(UTC) - timedelta(days=qa_compare_lookback_days)
            start_iso = start_dt.isoformat()

            conn_sqlite = sqlite3.connect(db_module.DB_PATH)
            cur_sqlite = conn_sqlite.cursor()
            try:
                # Source 1: local live erasure feed
                cur_sqlite.execute(
                    """
                    SELECT
                        COALESCE(NULLIF(TRIM(stockid), ''), NULLIF(TRIM(system_serial), '')) AS key_id,
                        MAX(ts) AS last_erasure_ts
                    FROM local_erasures
                    WHERE ts >= ?
                    GROUP BY COALESCE(NULLIF(TRIM(stockid), ''), NULLIF(TRIM(system_serial), ''))
                    """,
                    (start_iso,),
                )
                erasure_rows = cur_sqlite.fetchall() or []

                # Source 2: detailed erasure hook table (where most Blancco payloads land)
                cur_sqlite.execute(
                    """
                    SELECT
                        NULLIF(TRIM(system_serial), '') AS key_id,
                        MAX(ts) AS last_erasure_ts
                    FROM erasures
                    WHERE ts >= ?
                      AND event = 'success'
                      AND NULLIF(TRIM(system_serial), '') IS NOT NULL
                    GROUP BY NULLIF(TRIM(system_serial), '')
                    """,
                    (start_iso,),
                )
                erasure_rows.extend(cur_sqlite.fetchall() or [])
            finally:
                cur_sqlite.close()
                conn_sqlite.close()

            if not erasure_rows:
                return result

            key_to_erasure = {}
            key_to_erasure_norm = {}
            for row in erasure_rows:
                if not row or not row[0]:
                    continue
                key = str(row[0])
                ts_val = _parse_ts(row[1])
                if key not in key_to_erasure or (ts_val and key_to_erasure.get(key) and ts_val > key_to_erasure.get(key)):
                    key_to_erasure[key] = ts_val
                nkey = _norm_key(key)
                if nkey and (nkey not in key_to_erasure_norm or (ts_val and key_to_erasure_norm.get(nkey) and ts_val > key_to_erasure_norm.get(nkey))):
                    key_to_erasure_norm[nkey] = ts_val

            keys = list(key_to_erasure.keys())
            if not keys:
                return result

            conn = qa_export.get_mariadb_connection()
            if not conn:
                return result
            cur = conn.cursor()
            try:
                awaiting = 0
                completed = 0
                considered = 0
                samples = []
                batch_size = 500

                for i in range(0, len(keys), batch_size):
                    batch = keys[i:i + batch_size]
                    placeholders = ",".join(["%s"] * len(batch))

                    q_asset = (
                        f"SELECT stockid, system_serial FROM ITAD_asset_info "
                        f"WHERE stockid IN ({placeholders}) OR system_serial IN ({placeholders})"
                    )
                    asset_rows = cur.execute(q_asset, tuple(batch) + tuple(batch)) or None
                    # mysql cursor execute returns None; fetch afterward
                    asset_rows = cur.fetchall() or []

                    key_to_stockid = {}
                    key_to_stockid_norm = {}
                    for ar in asset_rows:
                        stockid = str(ar[0]) if ar and ar[0] is not None else None
                        serial = str(ar[1]) if ar and len(ar) > 1 and ar[1] is not None else None
                        if stockid:
                            key_to_stockid[stockid] = stockid
                            n_stock = _norm_key(stockid)
                            if n_stock:
                                key_to_stockid_norm[n_stock] = stockid
                        if serial:
                            key_to_stockid[serial] = stockid or serial
                            n_ser = _norm_key(serial)
                            if n_ser:
                                key_to_stockid_norm[n_ser] = stockid or serial

                    canonical = list({key_to_stockid[k] for k in batch if k in key_to_stockid and key_to_stockid[k]})
                    qa_map = {}
                    if canonical:
                        q_place = ",".join(["%s"] * len(canonical))
                        if qa_include_audit_master:
                            q_qa = (
                                f"SELECT stockid, MAX(added_date) as last_qa FROM ("
                                f"SELECT stockid, added_date FROM ITAD_QA_App WHERE stockid IN ({q_place}) UNION ALL "
                                f"SELECT stockid, added_date FROM audit_master WHERE stockid IN ({q_place})"
                                f") x GROUP BY stockid"
                            )
                            params = tuple(canonical) + tuple(canonical)
                        else:
                            q_qa = (
                                f"SELECT stockid, MAX(added_date) as last_qa "
                                f"FROM ITAD_QA_App WHERE stockid IN ({q_place}) GROUP BY stockid"
                            )
                            params = tuple(canonical)
                        cur.execute(q_qa, params)
                        qa_rows = cur.fetchall() or []
                        qa_map = {str(r[0]): _parse_ts(r[1]) for r in qa_rows if r and r[0]}

                    for key in batch:
                        er_ts = key_to_erasure.get(key) or key_to_erasure_norm.get(_norm_key(key))
                        sid = key_to_stockid.get(key) or key_to_stockid_norm.get(_norm_key(key))
                        considered += 1
                        if not sid:
                            awaiting += 1
                            if include_samples and len(samples) < sample_limit:
                                samples.append({"key": key, "stockid": None, "reason": "missing_in_asset_info", "erasureTs": str(er_ts) if er_ts else None, "qaTs": None})
                            continue

                        qa_ts = qa_map.get(sid)
                        if not qa_ts:
                            awaiting += 1
                            if include_samples and len(samples) < sample_limit:
                                samples.append({"key": key, "stockid": sid, "reason": "no_qa_or_audit_after_erasure", "erasureTs": str(er_ts) if er_ts else None, "qaTs": None})
                            continue

                        if er_ts and qa_ts < er_ts:
                            awaiting += 1
                            if include_samples and len(samples) < sample_limit:
                                samples.append({"key": key, "stockid": sid, "reason": "qa_before_latest_erasure", "erasureTs": str(er_ts), "qaTs": str(qa_ts)})
                            continue

                        completed += 1

                result.update({
                    "dbAwaitingQa": int(awaiting),
                    "completedAfterErasure": int(completed),
                    "considered": int(considered),
                    "samples": samples if include_samples else [],
                    "source": "local_erasures_vs_mariadb",
                    "includeAuditMaster": qa_include_audit_master,
                })
                return result
            finally:
                cur.close()
                conn.close()
        except Exception:
            return result

    def _mock_goods_in_payload(now_iso: str) -> dict:
        return {
            "sectionKey": "goods_in",
            "sectionName": "Goods In",
            "targetQueue": 90,
            "currentQueue": 412,
            "trendPctHour": 14,
            "owner": "Inbound Team",
            "queueLabel": "GRNs (Last 3 Months)",
            "subMetrics": [
                {"label": "Total Received (Not Booked In)", "value": 412},
                {"label": "Booked In Today", "value": 61},
                {"label": "Awaiting IA (All Booked In)", "value": 1743},
            ],
            "updatedAt": now_iso,
            "isLive": False,
            "source": "mock",
        }

    def _build_goods_in_payload() -> dict:
        now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        mock = _mock_goods_in_payload(now_iso)

        try:
            conn = qa_export.get_mariadb_connection()
            if not conn:
                return mock
            cur = conn.cursor()
            try:
                try:
                    default_received_today = _run_query_variants(cur, [
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) = CURDATE()
                          AND UPPER(COALESCE(recieved, '')) = 'Y'
                        """,
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) = CURDATE()
                          AND UPPER(COALESCE(received, '')) = 'Y'
                        """,
                    ])
                    default_checked_in = _run_query_variants(cur, [
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(bookedin_date) = CURDATE()
                          AND UPPER(COALESCE(bookedin, '')) = 'Y'
                        """,
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) = CURDATE()
                          AND UPPER(COALESCE(bookedin, '')) = 'Y'
                        """,
                    ])
                    default_awaiting_ia = _run_query_variants(cur, [
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) = CURDATE()
                          AND UPPER(COALESCE(recieved, '')) = 'Y'
                          AND UPPER(COALESCE(bookedin, 'N')) <> 'Y'
                        """,
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) = CURDATE()
                          AND UPPER(COALESCE(received, '')) = 'Y'
                          AND UPPER(COALESCE(bookedin, 'N')) <> 'Y'
                        """,
                    ])

                    received_total = _run_query_variants(cur, [
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) >= DATE_SUB(CURDATE(), INTERVAL {goods_in_lookback_days} DAY)
                          AND UPPER(COALESCE(recieved, '')) = 'Y'
                        """,
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) >= DATE_SUB(CURDATE(), INTERVAL {goods_in_lookback_days} DAY)
                          AND UPPER(COALESCE(received, '')) = 'Y'
                        """,
                    ])
                    booked_total = _run_query_variants(cur, [
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) >= DATE_SUB(CURDATE(), INTERVAL {goods_in_lookback_days} DAY)
                          AND UPPER(COALESCE(bookedin, '')) = 'Y'
                        """,
                    ])
                    source = f"mariadb:{goods_in_table}"
                except Exception:
                    default_received_today = _run_scalar_query(
                        cur,
                        """
                        SELECT COUNT(DISTINCT pallet_id)
                        FROM Stockbypallet
                        WHERE received_date >= CURDATE()
                        """,
                    )
                    default_checked_in = max(0, int(round(default_received_today * 0.72)))
                    default_awaiting_ia = max(0, default_received_today - default_checked_in)
                    received_total = default_received_today
                    booked_total = default_checked_in
                    source = "mariadb:Stockbypallet"

                if goods_in_queries["delivered"] or goods_in_queries["checked_in"] or goods_in_queries["awaiting_ia"]:
                    delivered = _run_scalar_query(cur, goods_in_queries["delivered"]) if goods_in_queries["delivered"] else max(0, received_total - booked_total)
                    checked_in = _run_scalar_query(cur, goods_in_queries["checked_in"]) if goods_in_queries["checked_in"] else default_checked_in
                    awaiting_ia = _run_scalar_query(cur, goods_in_queries["awaiting_ia"]) if goods_in_queries["awaiting_ia"] else default_awaiting_ia
                    source = "mariadb:custom-overall-goods-in-queries"
                else:
                    delivered = max(0, received_total - booked_total)
                    checked_in = default_checked_in
                    awaiting_ia = booked_total
            finally:
                cur.close()
                conn.close()

            trend = 0
            if delivered > 0:
                trend = int(round((checked_in / max(1, delivered)) * 100))

            return {
                "sectionKey": "goods_in",
                "sectionName": "Goods In",
                "targetQueue": 90,
                "currentQueue": delivered,
                "trendPctHour": trend,
                "owner": "Inbound Team",
                "queueLabel": f"GRNs (Last {goods_in_lookback_days} Days)",
                "subMetrics": [
                    {"label": "Total Received (Not Booked In)", "value": delivered},
                    {"label": "Booked In Today", "value": checked_in},
                    {"label": "Awaiting IA (All Booked In)", "value": awaiting_ia},
                ],
                "updatedAt": now_iso,
                "isLive": True,
                "source": source,
            }
        except Exception:
            return mock

    def _build_non_goods_mock(section_key: str) -> dict:
        now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        base = {
            "updatedAt": now_iso,
            "isLive": False,
            "source": "mock",
        }
        if section_key == "ia":
            return {
                **base,
                "sectionKey": "ia",
                "sectionName": "IA",
                "targetQueue": 72,
                "currentQueue": 81,
                "trendPctHour": 6,
                "owner": "Assessment Team",
                "queueLabel": "Totes Awaiting IA",
                "subMetrics": [
                    {"label": "Awaiting IA", "value": 81},
                    {"label": "Completed IA", "value": 59},
                    {"label": "Ready for Erasure", "value": 43},
                ],
            }
        if section_key == "erasure":
            return {
                **base,
                "sectionKey": "erasure",
                "sectionName": "Erasure",
                "targetQueue": 140,
                "currentQueue": 136,
                "trendPctHour": -4,
                "owner": "Erasure Team",
                "queueLabel": "Data-Bearing Awaiting Erasure",
                "subMetrics": [
                    {"label": "Roller 1 Queue", "value": 46},
                    {"label": "Roller 2 Queue", "value": 39},
                    {"label": "Roller 3 Queue", "value": 51},
                ],
            }
        if section_key == "qa":
            qa_live = _compute_db_awaiting_qa(include_samples=False)
            db_awaiting = int(qa_live.get("dbAwaitingQa", 44))
            completed_today = 0
            non_db_awaiting = 23
            source = qa_live.get("source", "mock")
            is_live = source != "mock"
            try:
                conn = qa_export.get_mariadb_connection()
                if conn:
                    cur = conn.cursor()
                    try:
                        cur.execute(
                            """
                            SELECT COUNT(DISTINCT stockid)
                            FROM ITAD_QA_App
                            WHERE DATE(added_date) = CURDATE()
                            """
                        )
                        row = cur.fetchone()
                        completed_today = int(row[0]) if row and row[0] is not None else 0
                    finally:
                        cur.close()
                        conn.close()
            except Exception:
                completed_today = 71

            return {
                **base,
                "sectionKey": "qa",
                "sectionName": "QA",
                "targetQueue": 95,
                "currentQueue": db_awaiting + non_db_awaiting,
                "trendPctHour": -8,
                "owner": "QA Team",
                "queueLabel": "Items Awaiting QA",
                "subMetrics": [
                    {"label": "DB Awaiting QA", "value": db_awaiting},
                    {"label": "Non-DB Awaiting QA", "value": non_db_awaiting},
                    {"label": "Completed QA Today", "value": completed_today},
                ],
                "isLive": is_live,
                "source": source,
            }
        return {
            **base,
            "sectionKey": "sorting",
            "sectionName": "Sorting",
            "targetQueue": 110,
            "currentQueue": 118,
            "trendPctHour": 5,
            "owner": "Sorting Team",
            "queueLabel": "Items Awaiting Sorting",
            "subMetrics": [
                {"label": "Awaiting Sorting", "value": 118},
                {"label": "Sorted This Morning", "value": 74},
                {"label": "QA Output Last Hour", "value": 29},
            ],
        }

    @router.get("/overall/goods-in")
    async def overall_goods_in() -> dict:
        return _build_goods_in_payload()

    @router.get("/overall/sections")
    async def overall_sections() -> dict:
        sections = [
            _build_goods_in_payload(),
            _build_non_goods_mock("ia"),
            _build_non_goods_mock("erasure"),
            _build_non_goods_mock("qa"),
            _build_non_goods_mock("sorting"),
        ]
        return {"sections": sections}

    @router.get("/overall/qa-awaiting-diagnostics")
    async def overall_qa_awaiting_diagnostics(request: Request):
        require_manager_or_admin(request)
        return _compute_db_awaiting_qa(include_samples=True, sample_limit=50)

    return router
