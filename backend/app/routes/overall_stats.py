from datetime import UTC, datetime, timedelta
from datetime import date
import asyncio
import os
import re
import sqlite3
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request


def create_overall_stats_router(*, qa_export_module, db_module, require_manager_or_admin):
    router = APIRouter()
    qa_export = qa_export_module
    snapshot_ttl_seconds = max(30, int(os.getenv("OVERALL_SNAPSHOT_TTL_SECONDS", "120")))
    snapshot_max_stale_seconds = max(300, int(os.getenv("OVERALL_SNAPSHOT_MAX_STALE_SECONDS", "3600")))
    overall_business_tz_name = os.getenv("OVERALL_BUSINESS_TZ", "Europe/London")
    refresh_throttle_state = {
        "sections": datetime.min.replace(tzinfo=UTC),
        "spotlight": datetime.min.replace(tzinfo=UTC),
    }

    def _parse_snapshot_ts(value: str | None) -> datetime | None:
        if not value:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except Exception:
            return None

    def _business_today() -> date:
        try:
            return datetime.now(ZoneInfo(overall_business_tz_name)).date()
        except Exception:
            return datetime.now(UTC).date()

    def _get_refresh_timeout_seconds() -> float:
        try:
            return max(0.2, float(os.getenv("OVERALL_REFRESH_TIMEOUT_SECONDS", "6.0")))
        except Exception:
            return 6.0

    def _get_snapshot_payload(snapshot_key: str) -> tuple[dict | None, float | None]:
        try:
            snap = db_module.get_dashboard_snapshot(snapshot_key)
        except Exception:
            snap = None
        if not isinstance(snap, dict):
            return None, None
        payload = snap.get("payload")
        if not isinstance(payload, dict):
            return None, None
        ts = _parse_snapshot_ts(snap.get("updatedAt"))
        if ts is None:
            return None, None
        age = max(0.0, (datetime.now(UTC) - ts).total_seconds())
        return payload, age

    def _store_snapshot_payload(snapshot_key: str, payload: dict, source_version: str) -> None:
        try:
            db_module.upsert_dashboard_snapshot(snapshot_key, payload, source_version=source_version)
        except Exception:
            pass

    def _should_attempt_refresh(kind: str) -> bool:
        now = datetime.now(UTC)
        last = refresh_throttle_state.get(kind)
        if not isinstance(last, datetime):
            refresh_throttle_state[kind] = now
            return True
        if (now - last).total_seconds() < float(snapshot_ttl_seconds):
            return False
        refresh_throttle_state[kind] = now
        return True

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
    try:
        sorting_lookback_days = max(1, int(os.getenv("OVERALL_SORTING_LOOKBACK_DAYS", "90")))
    except Exception:
        sorting_lookback_days = 90
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
            "excludedBy7DigitStockid": 0,
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

            def _is_seven_digit_stockid(v):
                return bool(re.fullmatch(r"\d{7}", str(v or "").strip()))

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
                excluded_seven_digit = 0
                considered = 0
                samples = []
                batch_size = 500

                # Some environments expose different serial column names on
                # ITAD_asset_info_blancco. Detect once to avoid noisy SQL errors.
                blancco_serial_col = None
                try:
                    cur.execute(
                        """
                        SELECT LOWER(COLUMN_NAME)
                        FROM information_schema.columns
                        WHERE table_schema = DATABASE() AND table_name = 'ITAD_asset_info_blancco'
                        """
                    )
                    blancco_cols = {
                        str(r[0]).lower() for r in (cur.fetchall() or []) if r and r[0]
                    }
                    for candidate in ("serial", "serialnumber", "system_serial"):
                        if candidate in blancco_cols:
                            blancco_serial_col = candidate
                            break
                except Exception:
                    blancco_serial_col = None

                for i in range(0, len(keys), batch_size):
                    batch = keys[i:i + batch_size]
                    placeholders = ",".join(["%s"] * len(batch))

                    # Most environments store asset serials in `serialnumber`.
                    # Keep a fallback for legacy schemas using `system_serial`.
                    q_asset_primary = (
                        f"SELECT stockid, serialnumber FROM ITAD_asset_info "
                        f"WHERE stockid IN ({placeholders}) OR serialnumber IN ({placeholders})"
                    )
                    q_asset_fallback = (
                        f"SELECT stockid, system_serial FROM ITAD_asset_info "
                        f"WHERE stockid IN ({placeholders}) OR system_serial IN ({placeholders})"
                    )
                    try:
                        cur.execute(q_asset_primary, tuple(batch) + tuple(batch))
                        asset_rows = cur.fetchall() or []
                    except Exception:
                        cur.execute(q_asset_fallback, tuple(batch) + tuple(batch))
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

                    # Fallback path: some ITAD devices may only be discoverable via
                    # ITAD_asset_info_blancco serial mappings.
                    unresolved = [k for k in batch if _norm_key(k) and _norm_key(k) not in key_to_stockid_norm]
                    if unresolved and blancco_serial_col:
                        ph_un = ",".join(["%s"] * len(unresolved))
                        q_bl = (
                            f"SELECT stockid, `{blancco_serial_col}` FROM ITAD_asset_info_blancco "
                            f"WHERE stockid IN ({ph_un}) OR `{blancco_serial_col}` IN ({ph_un})"
                        )
                        try:
                            cur.execute(q_bl, tuple(unresolved) + tuple(unresolved))
                            bl_rows = cur.fetchall() or []
                            for br in bl_rows:
                                bsid = str(br[0]) if br and br[0] is not None else None
                                bserial = str(br[1]) if br and len(br) > 1 and br[1] is not None else None
                                if bsid:
                                    key_to_stockid[bsid] = bsid
                                    n_bsid = _norm_key(bsid)
                                    if n_bsid:
                                        key_to_stockid_norm[n_bsid] = bsid
                                if bserial and bsid:
                                    key_to_stockid[bserial] = bsid
                                    n_bserial = _norm_key(bserial)
                                    if n_bserial:
                                        key_to_stockid_norm[n_bserial] = bsid
                        except Exception:
                            pass

                    canonical = list({key_to_stockid[k] for k in batch if k in key_to_stockid and key_to_stockid[k]})
                    qa_map = {}
                    asset_de_ts_map = {}
                    asset_de_by_map = {}
                    asset_last_update_map = {}
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

                        q_meta_variants = [
                            (
                                f"SELECT stockid, de_completed_date, de_completed_by, last_update "
                                f"FROM ITAD_asset_info WHERE stockid IN ({q_place})",
                                tuple(canonical),
                            ),
                            (
                                f"SELECT stockid, de_completed_date, de_completed_by, updated_at "
                                f"FROM ITAD_asset_info WHERE stockid IN ({q_place})",
                                tuple(canonical),
                            ),
                            (
                                f"SELECT stockid, de_completed_date, de_completed_by, NULL "
                                f"FROM ITAD_asset_info WHERE stockid IN ({q_place})",
                                tuple(canonical),
                            ),
                        ]
                        for q_meta, p_meta in q_meta_variants:
                            try:
                                cur.execute(q_meta, p_meta)
                                meta_rows = cur.fetchall() or []
                                for mr in meta_rows:
                                    msid = str(mr[0]) if mr and mr[0] is not None else None
                                    if not msid:
                                        continue
                                    asset_de_ts_map[msid] = _parse_ts(mr[1] if len(mr) > 1 else None)
                                    raw_by = mr[2] if len(mr) > 2 else None
                                    asset_de_by_map[msid] = str(raw_by).strip() if raw_by is not None and str(raw_by).strip() else None
                                    asset_last_update_map[msid] = _parse_ts(mr[3] if len(mr) > 3 else None)
                                break
                            except Exception:
                                continue

                    for key in batch:
                        er_ts = key_to_erasure.get(key) or key_to_erasure_norm.get(_norm_key(key))
                        sid = key_to_stockid.get(key) or key_to_stockid_norm.get(_norm_key(key))
                        considered += 1

                        # Exclude ITAD lane early when incoming key itself is a 7-digit asset number,
                        # even if the asset is not yet present in MariaDB.
                        if _is_seven_digit_stockid(key):
                            excluded_seven_digit += 1
                            if include_samples and len(samples) < sample_limit:
                                samples.append({"key": key, "stockid": None, "reason": "excluded_itad_7_digit_input_key", "erasureTs": str(er_ts) if er_ts else None, "qaTs": None})
                            continue

                        if not sid:
                            awaiting += 1
                            if include_samples and len(samples) < sample_limit:
                                samples.append({"key": key, "stockid": None, "reason": "missing_in_asset_info", "erasureTs": str(er_ts) if er_ts else None, "qaTs": None})
                            continue

                        if _is_seven_digit_stockid(sid):
                            excluded_seven_digit += 1
                            if include_samples and len(samples) < sample_limit:
                                samples.append({"key": key, "stockid": sid, "reason": "excluded_itad_7_digit_stockid", "erasureTs": str(er_ts) if er_ts else None, "qaTs": None})
                            continue

                        qa_ts = qa_map.get(sid)
                        de_ts = asset_de_ts_map.get(sid)
                        de_by = asset_de_by_map.get(sid)
                        last_update_ts = asset_last_update_map.get(sid)

                        effective_qa_ts = qa_ts
                        if de_ts and (not effective_qa_ts or de_ts > effective_qa_ts):
                            effective_qa_ts = de_ts

                        if not effective_qa_ts and de_by and last_update_ts and (not er_ts or last_update_ts >= er_ts):
                            completed += 1
                            if include_samples and len(samples) < sample_limit:
                                samples.append({"key": key, "stockid": sid, "reason": "deducted_by_de_completed_by_last_update_proxy", "erasureTs": str(er_ts) if er_ts else None, "qaTs": str(last_update_ts)})
                            continue

                        if not effective_qa_ts:
                            awaiting += 1
                            if include_samples and len(samples) < sample_limit:
                                samples.append({"key": key, "stockid": sid, "reason": "no_qa_or_audit_after_erasure", "erasureTs": str(er_ts) if er_ts else None, "qaTs": None})
                            continue

                        if er_ts and effective_qa_ts < er_ts:
                            awaiting += 1
                            if include_samples and len(samples) < sample_limit:
                                samples.append({"key": key, "stockid": sid, "reason": "qa_before_latest_erasure", "erasureTs": str(er_ts), "qaTs": str(effective_qa_ts)})
                            continue

                        completed += 1

                result.update({
                    "dbAwaitingQa": int(awaiting),
                    "completedAfterErasure": int(completed),
                    "excludedBy7DigitStockid": int(excluded_seven_digit),
                    "considered": int(considered),
                    "samples": samples if include_samples else [],
                    "source": "local_erasures_vs_mariadb(exclude_7_digit_stockid)",
                    "includeAuditMaster": qa_include_audit_master,
                })
                return result
            finally:
                cur.close()
                conn.close()
        except Exception:
            return result

    def _get_qa_today_totals() -> dict:
        """Return QA dashboard-compatible daily totals.

        - qaAppScans: ITAD_QA_App daily scans excluding unassigned usernames.
        - deQaScans/nonDeQaScans: audit_master daily QA events.
        - combinedScans: qaAppScans + deQaScans + nonDeQaScans.
        """
        out = {
            "qaAppScans": 0,
            "deQaScans": 0,
            "nonDeQaScans": 0,
            "combinedScans": 0,
            "source": "mock",
        }
        try:
            snap = db_module.get_dashboard_snapshot("qa_dashboard:today")
            payload = snap.get("payload") if isinstance(snap, dict) else None
            summary = payload.get("summary") if isinstance(payload, dict) else None
            snap_updated_at = _parse_snapshot_ts(snap.get("updatedAt") if isinstance(snap, dict) else None)
            # Guard against previous-day cached "today" values carrying over after midnight
            # in the business timezone.
            snap_business_day = None
            if snap_updated_at:
                try:
                    snap_business_day = snap_updated_at.astimezone(ZoneInfo(overall_business_tz_name)).date()
                except Exception:
                    snap_business_day = snap_updated_at.date()
            is_current_day_snapshot = bool(snap_business_day and snap_business_day == _business_today())
            if isinstance(summary, dict) and is_current_day_snapshot:
                qa_app = int(summary.get("totalScans", 0) or 0)
                de = int(summary.get("deQaScans", 0) or 0)
                non_de = int(summary.get("nonDeQaScans", 0) or 0)
                combined = int(summary.get("combinedScans", qa_app + de + non_de) or 0)
                out.update({
                    "qaAppScans": qa_app,
                    "deQaScans": de,
                    "nonDeQaScans": non_de,
                    "combinedScans": combined,
                    "source": "sqlite:qa_dashboard_today_snapshot",
                })
                return out

            today_business = _business_today()
            start_date, end_date = today_business, today_business
            qa_data = qa_export.get_weekly_qa_comparison(start_date, end_date) or {}
            de_data = qa_export.get_de_qa_comparison(start_date, end_date) or {}
            non_de_data = qa_export.get_non_de_qa_comparison(start_date, end_date) or {}

            qa_app = sum(stats.get("total", 0) for name, stats in qa_data.items() if str(name).lower() != "(unassigned)")
            de = sum(stats.get("total", 0) for name, stats in de_data.items() if str(name).lower() != "(unassigned)")
            non_de = sum(stats.get("total", 0) for name, stats in non_de_data.items() if str(name).lower() != "(unassigned)")

            out.update({
                "qaAppScans": int(qa_app),
                "deQaScans": int(de),
                "nonDeQaScans": int(non_de),
                "combinedScans": int(qa_app + de + non_de),
                "source": "qa_dashboard_parity:ITAD_QA_App+audit_master",
            })
            return out
        except Exception:
            return out

    def _first_name(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return "—"
        if "@" in raw:
            raw = raw.split("@", 1)[0]
        raw = raw.replace("_", " ").replace("-", " ").replace(".", " ")
        parts = [p for p in raw.split() if p]
        if not parts:
            return "—"
        token = parts[0]
        if len(token) <= 3 and token.isupper():
            return token
        return token.capitalize()

    def _build_spotlight_payload() -> dict:
        out = {
            "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "goodsIn": {"name": "Unable to yet", "count": 0, "source": "pending_table"},
            "ia": {"name": "Unable to yet", "count": 0, "source": "pending_table"},
            "erasure": {"name": "—", "count": 0, "source": "sqlite:erasures"},
            "qa": {"name": "—", "count": 0, "source": "mariadb:ITAD_asset_info.de_completed_by"},
            "sorting": {"name": "—", "count": 0, "source": "mariadb:ITAD_QA_App.username"},
        }

        try:
            leaders = db_module.leaderboard(scope="today", limit=1) or []
            if leaders:
                row = leaders[0] or {}
                out["erasure"]["name"] = str(row.get("initials") or row.get("name") or "—")
                out["erasure"]["count"] = int(row.get("erasures") or row.get("count") or 0)
        except Exception:
            pass

        conn = None
        try:
            conn = qa_export.get_mariadb_connection()
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        """
                        SELECT de_completed_by, COUNT(*) AS cnt
                        FROM ITAD_asset_info
                        WHERE de_completed_date IS NOT NULL
                          AND DATE(de_completed_date) = CURDATE()
                          AND TRIM(COALESCE(de_completed_by, '')) <> ''
                        GROUP BY de_completed_by
                        ORDER BY cnt DESC
                        LIMIT 1
                        """
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        out["qa"]["name"] = _first_name(str(row[0]))
                        out["qa"]["count"] = int(row[1] or 0)
                finally:
                    cur.close()
                    conn.close()
                    conn = None
        except Exception:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

        try:
            qa_daily = qa_export.get_daily_qa_data(_business_today()) or {}
            best_name = "—"
            best_count = 0
            for uname, stats in qa_daily.items():
                if str(uname).lower() == "(unassigned)":
                    continue
                count = int((stats or {}).get("total_scans", 0) or 0)
                if count > best_count:
                    best_count = count
                    best_name = _first_name(str(uname))
            out["sorting"]["name"] = best_name
            out["sorting"]["count"] = best_count
        except Exception:
            pass

        return out

    def _build_spotlight_fallback_payload(reason: str) -> dict:
        return {
            "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "goodsIn": {"name": "Unable to yet", "count": 0, "source": "fallback"},
            "ia": {"name": "Unable to yet", "count": 0, "source": "fallback"},
            "erasure": {"name": "—", "count": 0, "source": "fallback"},
            "qa": {"name": "—", "count": 0, "source": "fallback"},
            "sorting": {"name": "—", "count": 0, "source": "fallback"},
            "degraded": True,
            "reason": reason,
        }

    def _build_sections_payload() -> dict:
        return {
            "sections": [
                _build_goods_in_payload(),
                _build_non_goods_mock("ia"),
                _build_non_goods_mock("erasure"),
                _build_non_goods_mock("qa"),
                _build_non_goods_mock("sorting"),
            ]
        }

    def _get_sorting_awaiting_live_count() -> tuple[int | None, str | None]:
        """Compute awaiting sorting from live MariaDB data with A100 pallet exclusion."""
        try:
            conn = qa_export.get_mariadb_connection()
            if not conn:
                return None, None
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT a.stockid)
                    FROM ITAD_asset_info a
                    LEFT JOIN (
                        SELECT stockid, MAX(added_date) AS last_sort_ts
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
                            q.last_sort_ts IS NULL
                            OR a.de_completed_date > q.last_sort_ts
                          )
                    """,
                    (sorting_lookback_days,),
                )
                row = cur.fetchone()
                live_count = int(row[0]) if row and row[0] is not None else 0
                return max(0, live_count), "mariadb:ITAD_QA_App+ITAD_asset_info(A100-excluded)"
            finally:
                cur.close()
                conn.close()
        except Exception:
            return None, None

    def _get_qa_awaiting_live_count() -> tuple[int | None, str | None]:
        """Compute DB awaiting QA from live erasure vs QA timestamp comparison."""
        try:
            qa_live = _compute_db_awaiting_qa(include_samples=False)
            return int(qa_live.get("dbAwaitingQa", 0) or 0), str(qa_live.get("source") or "")
        except Exception:
            return None, None

    def _apply_live_daily_totals(payload: dict | None) -> dict | None:
        if not isinstance(payload, dict):
            return payload
        sections = payload.get("sections")
        if not isinstance(sections, list):
            return payload

        try:
            qa_today = _get_qa_today_totals()
        except Exception:
            return payload

        sorting_awaiting_live, sorting_live_source = _get_sorting_awaiting_live_count()
        qa_awaiting_live, qa_awaiting_live_source = _get_qa_awaiting_live_count()

        qa_done = int((qa_today.get("deQaScans", 0) or 0) + (qa_today.get("nonDeQaScans", 0) or 0))
        sorting_done = int(qa_today.get("qaAppScans", 0) or 0)
        qa_source = str(qa_today.get("source") or "")

        for section in sections:
            if not isinstance(section, dict):
                continue
            key = str(section.get("sectionKey") or "").lower()
            rows = section.get("subMetrics")
            if not isinstance(rows, list):
                continue

            if key == "qa":
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if qa_awaiting_live is not None and str(row.get("label") or "").strip().lower() == "db awaiting qa":
                        row["value"] = qa_awaiting_live
                    if str(row.get("label") or "").strip().lower() == "completed qa today":
                        row["value"] = qa_done
                if qa_awaiting_live is not None:
                    section["currentQueue"] = qa_awaiting_live
                if qa_source and qa_source != "mock":
                    section["isLive"] = True
                    section["source"] = f"{section.get('source', 'snapshot')}+{qa_source}"
                if qa_awaiting_live is not None and qa_awaiting_live_source and qa_awaiting_live_source != "mock":
                    section["isLive"] = True
                    existing_source = str(section.get("source") or "snapshot")
                    if qa_awaiting_live_source not in existing_source:
                        section["source"] = f"{existing_source}+{qa_awaiting_live_source}"

            if key == "sorting":
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if sorting_awaiting_live is not None and str(row.get("label") or "").strip().lower() == "awaiting sorting":
                        row["value"] = sorting_awaiting_live
                    if str(row.get("label") or "").strip().lower() == "sorted today":
                        row["value"] = sorting_done
                if sorting_awaiting_live is not None:
                    section["currentQueue"] = sorting_awaiting_live
                if qa_source and qa_source != "mock":
                    section["isLive"] = True
                    section["source"] = f"{section.get('source', 'snapshot')}+{qa_source}"
                if sorting_awaiting_live is not None and sorting_live_source:
                    section["isLive"] = True
                    existing_source = str(section.get("source") or "snapshot")
                    if sorting_live_source not in existing_source:
                        section["source"] = f"{existing_source}+{sorting_live_source}"

        return payload

    def _build_sections_fallback_payload(reason: str) -> dict:
        now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        return {
            "sections": [
                _mock_goods_in_payload(now_iso),
                {
                    "sectionKey": "ia",
                    "sectionName": "IA",
                    "targetQueue": 72,
                    "currentQueue": 0,
                    "trendPctHour": 0,
                    "owner": "Assessment Team",
                    "queueLabel": "Totes Awaiting IA",
                    "subMetrics": [
                        {"label": "Awaiting IA", "value": 0},
                        {"label": "Completed IA", "value": 0},
                        {"label": "Ready for Erasure", "value": 0},
                    ],
                    "updatedAt": now_iso,
                    "isLive": False,
                    "source": "fallback",
                },
                {
                    "sectionKey": "erasure",
                    "sectionName": "Erasure",
                    "targetQueue": 140,
                    "currentQueue": 0,
                    "trendPctHour": 0,
                    "owner": "Erasure Team",
                    "queueLabel": "Data-Bearing Awaiting Erasure",
                    "subMetrics": [
                        {"label": "Roller 1 Queue", "value": 0},
                        {"label": "Roller 2 Queue", "value": 0},
                        {"label": "Roller 3 Queue", "value": 0},
                    ],
                    "updatedAt": now_iso,
                    "isLive": False,
                    "source": "fallback",
                },
                {
                    "sectionKey": "qa",
                    "sectionName": "QA",
                    "targetQueue": 95,
                    "currentQueue": 44,
                    "trendPctHour": -8,
                    "owner": "QA Team",
                    "queueLabel": "Items Awaiting QA",
                    "subMetrics": [
                        {"label": "DB Awaiting QA", "value": 44},
                        {"label": "Non-DB Awaiting QA", "value": 0},
                        {"label": "Completed QA Today", "value": 0},
                    ],
                    "updatedAt": now_iso,
                    "isLive": False,
                    "source": "fallback",
                },
                {
                    "sectionKey": "sorting",
                    "sectionName": "Sorting",
                    "targetQueue": 110,
                    "currentQueue": 118,
                    "trendPctHour": 5,
                    "owner": "Sorting Team",
                    "queueLabel": "Items Awaiting Sorting",
                    "subMetrics": [
                        {"label": "Awaiting Sorting", "value": 118},
                        {"label": "Sorted Today", "value": 0},
                        {"label": "Sorting Output Last Hour", "value": 0},
                    ],
                    "updatedAt": now_iso,
                    "isLive": False,
                    "source": "fallback",
                },
            ],
            "degraded": True,
            "reason": reason,
        }

    async def _refresh_sections_with_budget() -> dict:
        timeout_s = _get_refresh_timeout_seconds()
        return await asyncio.wait_for(asyncio.to_thread(_build_sections_payload), timeout=timeout_s)

    async def _refresh_spotlight_with_budget() -> dict:
        timeout_s = _get_refresh_timeout_seconds()
        return await asyncio.wait_for(asyncio.to_thread(_build_spotlight_payload), timeout=timeout_s)

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
                "currentQueue": 0,
                "trendPctHour": 0,
                "owner": "Assessment Team",
                "queueLabel": "Totes Awaiting IA",
                "subMetrics": [
                    {"label": "Awaiting IA", "value": 0},
                    {"label": "Completed IA", "value": 0},
                    {"label": "Ready for Erasure", "value": 0},
                ],
            }
        if section_key == "erasure":
            return {
                **base,
                "sectionKey": "erasure",
                "sectionName": "Erasure",
                "targetQueue": 140,
                "currentQueue": 0,
                "trendPctHour": 0,
                "owner": "Erasure Team",
                "queueLabel": "Data-Bearing Awaiting Erasure",
                "subMetrics": [
                    {"label": "Roller 1 Queue", "value": 0},
                    {"label": "Roller 2 Queue", "value": 0},
                    {"label": "Roller 3 Queue", "value": 0},
                ],
            }
        if section_key == "qa":
            qa_live = _compute_db_awaiting_qa(include_samples=False)
            db_awaiting = int(qa_live.get("dbAwaitingQa", 44))
            completed_today = 0
            # Hold non-DB awaiting at 0 until we wire a reliable source.
            non_db_awaiting = 0
            source = qa_live.get("source", "mock")
            is_live = source != "mock"
            try:
                qa_today = _get_qa_today_totals()
                completed_today = int((qa_today.get("deQaScans", 0) or 0) + (qa_today.get("nonDeQaScans", 0) or 0))
                if qa_today.get("source") != "mock":
                    source = f"{source}+{qa_today.get('source')}"
                    is_live = True
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
        if section_key == "sorting":
            awaiting_sorting = 118
            sorted_today = 74
            completed_qa_today = 74
            sorting_output_last_hour = 29
            source = "mock"
            is_live = False

            try:
                conn = qa_export.get_mariadb_connection()
                if conn:
                    cur = conn.cursor()
                    try:
                        # Awaiting sorting is defined as stock IDs completed in erasure that do not
                        # yet have a newer QA/sorting scan entry with a username.
                        cur.execute(
                            """
                            SELECT COUNT(DISTINCT a.stockid)
                            FROM ITAD_asset_info a
                            LEFT JOIN (
                                SELECT stockid, MAX(added_date) AS last_sort_ts
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
                                    q.last_sort_ts IS NULL
                                    OR a.de_completed_date > q.last_sort_ts
                                  )
                            """
                            ,
                            (sorting_lookback_days,),
                        )
                        row = cur.fetchone()
                        base_awaiting = int(row[0]) if row and row[0] is not None else 0

                        qa_today = _get_qa_today_totals()
                        sorted_today = int(qa_today.get("qaAppScans", 0))
                        completed_qa_today = int(qa_today.get("combinedScans", sorted_today))

                        cur.execute(
                            """
                            SELECT COUNT(DISTINCT stockid)
                            FROM ITAD_QA_App
                            WHERE added_date >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
                              AND TRIM(COALESCE(stockid, '')) <> ''
                              AND TRIM(COALESCE(username, '')) <> ''
                            """
                        )
                        row = cur.fetchone()
                        sorting_output_last_hour = int(row[0]) if row and row[0] is not None else 0

                        awaiting_sorting = max(0, base_awaiting)

                        source = "mariadb:ITAD_QA_App+ITAD_asset_info(A100-excluded)"
                        if qa_today.get("source") != "mock":
                            source = f"{source}+{qa_today.get('source')}"
                        is_live = True
                    finally:
                        cur.close()
                        conn.close()
            except Exception:
                pass

            return {
                **base,
                "sectionKey": "sorting",
                "sectionName": "Sorting",
                "targetQueue": 110,
                "currentQueue": max(0, awaiting_sorting),
                "trendPctHour": 5,
                "owner": "Sorting Team",
                "queueLabel": "Items Awaiting Sorting",
                "subMetrics": [
                    {"label": "Awaiting Sorting", "value": max(0, awaiting_sorting)},
                    {"label": "Sorted Today", "value": max(0, sorted_today)},
                    {"label": "Sorting Output Last Hour", "value": max(0, sorting_output_last_hour)},
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
        snapshot_key = "overall_sections"
        payload, age = _get_snapshot_payload(snapshot_key)
        has_snapshot = isinstance(payload, dict)
        if has_snapshot and age is not None and age <= float(snapshot_ttl_seconds):
            return _apply_live_daily_totals(payload)

        # If we have a stale snapshot, prefer serving it over returning full mock fallback.
        if has_snapshot and not _should_attempt_refresh("sections"):
            return _apply_live_daily_totals(payload)

        try:
            fresh_payload = await _refresh_sections_with_budget()
            _store_snapshot_payload(snapshot_key, fresh_payload, "overall_sections_build")
            return _apply_live_daily_totals(fresh_payload)
        except Exception:
            if has_snapshot:
                return _apply_live_daily_totals(payload)
            return _apply_live_daily_totals(_build_sections_fallback_payload("refresh_timeout_or_error"))

    @router.get("/overall/qa-awaiting-diagnostics")
    async def overall_qa_awaiting_diagnostics(request: Request):
        require_manager_or_admin(request)
        return _compute_db_awaiting_qa(include_samples=True, sample_limit=50)

    @router.get("/overall/spotlight")
    async def overall_spotlight() -> dict:
        snapshot_key = "overall_spotlight"
        payload, age = _get_snapshot_payload(snapshot_key)
        has_snapshot = isinstance(payload, dict)
        if has_snapshot and age is not None and age <= float(snapshot_ttl_seconds):
            return payload

        if has_snapshot and not _should_attempt_refresh("spotlight"):
            return payload

        try:
            fresh_payload = await _refresh_spotlight_with_budget()
            _store_snapshot_payload(snapshot_key, fresh_payload, "overall_spotlight_build")
            return fresh_payload
        except Exception:
            if has_snapshot:
                return payload
            return _build_spotlight_fallback_payload("refresh_timeout_or_error")

    return router
