from datetime import datetime, timedelta
from typing import Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import os


def create_bottleneck_router(*, db_module, qa_export_module, require_manager_or_admin, compute_qa_dashboard_data, cache_get, cache_set, ttl_cache_cls, backfill_progress):
    router = APIRouter()
    db = db_module
    qa_export = qa_export_module
    BACKFILL_PROGRESS = backfill_progress

    def _build_bottleneck_snapshot(destination: str = None, limit_engineers: int = 5, days_threshold: int = 7) -> Dict[str, object]:
        """Summarize CURRENT bottleneck patterns - shows warehouse state for THIS WEEK.
        
        Shows:
        - Current unpalleted devices active this week
        - Current roller queue status (devices awaiting erasure/QA/pallet)
        - Roller station breakdown by workflow stage
        - Engineers with unpalleted devices assigned to them
        """
        import qa_export
    
        def normalize_destination(value: object) -> str:
            if value is None:
                return ""
            return str(value).strip()
    
        destination_norm = normalize_destination(destination).lower() if destination else None
        try:
            summary = qa_export.get_unpalleted_summary(
                destination=destination_norm,
                days_threshold=7  # This is now ignored, uses "this week" filtering
            )
        except Exception as ex:
            print(f"[Bottleneck] get_unpalleted_summary failed: {ex}")
            import traceback as _tb
            _tb.print_exc()
            summary = {"total_unpalleted": 0, "destination_counts": {}, "engineer_counts": {}}
    
        total_unpalleted = summary.get("total_unpalleted", 0)
        awaiting_erasure = summary.get("awaiting_erasure", 0)
        awaiting_qa = summary.get("awaiting_qa", 0)
        awaiting_pallet = summary.get("awaiting_pallet", 0)
        destination_counts = summary.get("destination_counts", {})
        engineer_counts = summary.get("engineer_counts", {})
    
        top_destinations = sorted(
            [{"destination": k, "count": v} for k, v in destination_counts.items()],
            key=lambda x: x["count"],
            reverse=True
        )
    
        top_engineers = sorted(
            [{"engineer": k, "missing_pallet_count": v} for k, v in engineer_counts.items()],
            key=lambda x: x["missing_pallet_count"],
            reverse=True
        )
    
        # Only flag REAL engineers (not unassigned/system entries) with high share
        flagged_engineers = []
        for item in top_engineers[:limit_engineers]:
            share = (item["missing_pallet_count"] / total_unpalleted) if total_unpalleted else 0
            item["share"] = round(share, 2)
            
            engineer_name = item["engineer"].lower()
            # Skip flagging unassigned, NO USER, system entries
            is_system_entry = any(x in engineer_name for x in ["unassigned", "no user", "system", "unknown"])
            
            if not is_system_entry and item["missing_pallet_count"] >= 10 and share >= 0.25:
                flagged_engineers.append({
                    "engineer": item["engineer"],
                    "missing_pallet_count": item["missing_pallet_count"],
                    "share": item["share"],
                    "reason": f"High volume of unpalleted devices ({item['missing_pallet_count']} devices, {int(share*100)}% of total)",
                })
    
        # Get accurate roller queue status (shows CURRENT state of all rollers this week)
        try:
            roller_status = qa_export.get_roller_queue_status(days_threshold=7)  # This is now ignored, uses "this week" filtering
            # Ensure totals/rollers structure exists
            if not isinstance(roller_status, dict):
                roller_status = {"totals": {}, "rollers": []}
            roller_totals = roller_status.get("totals", {})
            roller_rollers = roller_status.get("rollers", [])
        except Exception as ex:
            print(f"[Bottleneck] get_roller_queue_status failed: {ex}")
            import traceback as _tb
            _tb.print_exc()
            roller_totals = {"total": 0, "awaiting_erasure": 0, "awaiting_qa": 0, "awaiting_pallet": 0}
            roller_rollers = []
        
        return {
            "timestamp": datetime.now().isoformat(),
            "filter_period": "this_week",  # Changed from lookback_days
            "total_unpalleted": total_unpalleted,
            "awaiting_erasure": awaiting_erasure,
            "awaiting_qa": awaiting_qa,
            "awaiting_pallet": awaiting_pallet,
            "destination_counts": top_destinations,
            "engineer_missing_pallets": top_engineers[:limit_engineers],
            "flagged_engineers": flagged_engineers,
            "roller_queue": roller_totals,
            "roller_breakdown": roller_rollers,
        }
    
    
    @router.get("/api/bottlenecks")
    async def get_bottleneck_snapshot(request: Request, days: int = 7, debug: bool = False):
        """Return CURRENT bottleneck snapshot - warehouse state NOW (manager only)."""
        require_manager_or_admin(request)
        # Lightweight bottleneck implementation using recent-window counts.
        # Uses MariaDB via services.db_utils and local SQLite erasure feed for early erasure signals.
        try:
            from services import db_utils
            import sqlite3
            import os
    
            # Simple cache to avoid repeated heavy calls
            global _bottleneck_cache
            try:
                _bottleneck_cache
            except NameError:
                _bottleneck_cache = ttl_cache_cls(maxsize=128, ttl=int(os.getenv('BOTTLENECK_CACHE_TTL', '60')))
    
            now = datetime.utcnow()
            days = max(1, min(int(days or 7), 90))
            start = (now - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
            end = now.strftime('%Y-%m-%d %H:%M:%S')
            cache_key = f"bottleneck|{start}|{end}"
            cached = _bottleneck_cache.get(cache_key)
            if cached is not None:
                return JSONResponse(status_code=200, content=cached)
    
            # 1) Goods In (Stockbypallet) - best-effort
            q_goods = "SELECT COUNT(DISTINCT pallet_id) FROM Stockbypallet WHERE received_date >= %s AND received_date < %s"
            goods_res = db_utils.safe_read(q_goods, (start, end))
            goods_in = int(goods_res[0][0]) if goods_res and isinstance(goods_res, list) and goods_res[0] and goods_res[0][0] is not None else 0
    
            # 2) Awaiting Erasure (stage_current='IA' and no blancco)
            q_awaiting = (
                "SELECT COUNT(*) FROM ITAD_asset_info a "
                "WHERE (a.warehouse IS NULL OR a.warehouse = 'Berry Hill') "
                "AND a.stage_current = 'IA' "
                "AND NOT EXISTS (SELECT 1 FROM ITAD_asset_info_blancco b WHERE b.stockid = a.stockid) "
                "AND a.sla_complete_date >= %s AND a.sla_complete_date < %s"
            )
            awaiting_res = db_utils.safe_read(q_awaiting, (start, end))
            awaiting_erasure = int(awaiting_res[0][0]) if awaiting_res and awaiting_res[0] and awaiting_res[0][0] is not None else 0
    
            # 3) Awaiting QA: infer from local SQLite erasure feed vs MariaDB
            stats_db = os.getenv('STATS_DB_PATH', 'warehouse_stats.db')
            erased_awaiting_qa = 0
            diagnostics = {"sqlite_found": False, "sqlite_rows": 0, "batches": 0, "errors": []}
            try:
                if os.path.exists(stats_db):
                    diagnostics["sqlite_found"] = True
                    conn = sqlite3.connect(stats_db)
                    cur = conn.cursor()
                    # Pull distinct stockids with their latest erasure ts in the window
                    cur.execute("SELECT stockid, MAX(ts) as last_ts FROM local_erasures WHERE ts >= ? AND ts < ? GROUP BY stockid", (start, end))
                    rows = cur.fetchall()
                    cur.close()
                    conn.close()
                    # If local_erasures is empty and AUTO_BACKFILL enabled, try to seed from erasures table
                    if not rows:
                        try:
                            from os import getenv
                            if str(getenv('AUTO_BACKFILL', '')).lower() in ('1', 'true', 'yes'):
                                # backfill from erasures (recent events)
                                from database import DB_PATH, add_local_erasure
                                conn2 = sqlite3.connect(DB_PATH)
                                cur2 = conn2.cursor()
                                days_back = int(getenv('AUTO_BACKFILL_DAYS', '7'))
                                limit = int(getenv('AUTO_BACKFILL_LIMIT', '2000'))
                                from datetime import timedelta as _td
                                start_back = (datetime.utcnow() - _td(days=days_back)).isoformat()
                                q_back = ("SELECT id, job_id, system_serial, ts, device_type, initials FROM erasures "
                                          "WHERE event = 'success' AND ts >= ? ORDER BY ts ASC LIMIT ?")
                                cur2.execute(q_back, (start_back, limit))
                                back_rows = cur2.fetchall()
                                inserted = 0
                                # Initialize auto-backfill progress so UI can poll
                                try:
                                    BACKFILL_PROGRESS['running'] = True
                                    BACKFILL_PROGRESS['total'] = len(back_rows)
                                    BACKFILL_PROGRESS['processed'] = 0
                                    BACKFILL_PROGRESS['percent'] = 0
                                    BACKFILL_PROGRESS['last_updated'] = datetime.utcnow().isoformat()
                                    BACKFILL_PROGRESS['errors'] = []
                                except Exception:
                                    pass
                                for r in back_rows:
                                    eid, job_id, system_serial, ts_val, device_type, initials = r
                                    jid = job_id if job_id else f"erasures-backfill-{eid}"
                                    try:
                                        add_local_erasure(stockid=None, system_serial=system_serial, job_id=jid, ts=ts_val, warehouse=None, source='erasures-backfill', payload={'device_type': device_type, 'initials': initials})
                                        inserted += 1
                                    except Exception as _e:
                                        diagnostics.setdefault('errors', []).append(str(_e))
                                        try:
                                            BACKFILL_PROGRESS['errors'].append(str(_e))
                                        except Exception:
                                            pass
                                    finally:
                                        try:
                                            BACKFILL_PROGRESS['processed'] = BACKFILL_PROGRESS.get('processed', 0) + 1
                                            BACKFILL_PROGRESS['percent'] = int((BACKFILL_PROGRESS.get('processed', 0) / (BACKFILL_PROGRESS.get('total') or 1)) * 100)
                                            BACKFILL_PROGRESS['last_updated'] = datetime.utcnow().isoformat()
                                        except Exception:
                                            pass
                                cur2.close()
                                conn2.close()
                                # re-open the local_erasures query to pick up inserted rows
                                if inserted > 0:
                                    conn = sqlite3.connect(stats_db)
                                    cur = conn.cursor()
                                    cur.execute("SELECT stockid, MAX(ts) as last_ts FROM local_erasures WHERE ts >= ? AND ts < ? GROUP BY stockid", (start, end))
                                    rows = cur.fetchall()
                                    cur.close()
                                    conn.close()
                                    diagnostics['auto_backfilled'] = inserted
                                # Mark auto-backfill finished
                                try:
                                    BACKFILL_PROGRESS['running'] = False
                                    BACKFILL_PROGRESS['last_updated'] = datetime.utcnow().isoformat()
                                except Exception:
                                    pass
                        except Exception as _e:
                            diagnostics.setdefault('errors', []).append(str(_e))
    
                    if rows:
                        diagnostics["sqlite_rows"] = len(rows)
                        # Build map key -> last erasure ts where key is COALESCE(stockid, system_serial)
                        stock_ts = {}
                        for r in rows:
                            # r may be (stockid, last_ts) or (stockid, last_ts, system_serial) depending on query
                            s = r[0]
                            sys = None
                            try:
                                # if the row has a second column that's the ts, keep it as ts
                                ts_val = r[1]
                                # attempt to pick system_serial if stockid is falsy
                                if len(r) > 2:
                                    sys = r[2]
                            except Exception:
                                continue
                            key = None
                            if s is not None and str(s).strip() != '':
                                key = str(s)
                            elif sys is not None and str(sys).strip() != '':
                                key = str(sys)
                            if key:
                                stock_ts[key] = ts_val
                        stockids = list(stock_ts.keys())
                        batch_size = 200
                        awaiting = 0
    
                        # Helper to parse timestamps robustly
                        from datetime import datetime as _dt
                        def _parse_ts(v):
                            if not v:
                                return None
                            if isinstance(v, _dt):
                                return v
                            s = str(v).strip()
                            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                                try:
                                    return _dt.strptime(s, fmt)
                                except Exception:
                                    continue
                            try:
                                return _dt.fromisoformat(s.replace('Z', '+00:00'))
                            except Exception:
                                return None
    
                        for i in range(0, len(stockids), batch_size):
                            batch = stockids[i:i+batch_size]
                            diagnostics["batches"] += 1
                            placeholders = ",".join(["%s"] * len(batch))
    
                            # 1) Check ITAD_asset_info for matches by stockid OR system_serial and get last_update
                            q_asset = f"SELECT stockid, last_update, system_serial FROM ITAD_asset_info WHERE stockid IN ({placeholders}) OR system_serial IN ({placeholders})"
                            asset_rows = db_utils.safe_read(q_asset, tuple(batch) + tuple(batch)) or []
                            # asset_map holds last_update keyed by canonical stockid
                            asset_map = {}
                            # key_to_stockid maps the incoming key (stockid or system_serial) -> canonical stockid
                            key_to_stockid = {}
                            for ar in asset_rows:
                                try:
                                    a_stockid = str(ar[0]) if ar[0] is not None else None
                                    a_last = ar[1]
                                    a_sys = str(ar[2]) if len(ar) > 2 and ar[2] is not None else None
                                except Exception:
                                    continue
                                if a_stockid:
                                    asset_map[a_stockid] = a_last
                                    # map by stockid
                                    if a_stockid in batch:
                                        key_to_stockid[a_stockid] = a_stockid
                                if a_sys:
                                    # map system_serial back to canonical stockid when available
                                    key_to_stockid[a_sys] = a_stockid or a_sys
    
                            # 2) Check for any QA/audit rows after erasure ts (ITAD_QA_App + audit_master)
                            # Use UNION ALL to combine sources and get the max added_date per stockid
                            q_qa = (
                                f"SELECT stockid, MAX(added_date) as last_qa FROM ("
                                f"SELECT stockid, added_date FROM ITAD_QA_App WHERE stockid IN ({placeholders}) UNION ALL "
                                f"SELECT stockid, added_date FROM audit_master WHERE stockid IN ({placeholders})"
                                f") x GROUP BY stockid"
                            )
                            # For QA lookup, prefer canonical stockids mapped from the asset query
                            canonical_ids = list({key_to_stockid[k] for k in batch if k in key_to_stockid and key_to_stockid[k]})
                            qa_map = {}
                            if canonical_ids:
                                q_place = ",".join(["%s"] * len(canonical_ids))
                                q_qa_specific = (
                                    f"SELECT stockid, MAX(added_date) as last_qa FROM ("
                                    f"SELECT stockid, added_date FROM ITAD_QA_App WHERE stockid IN ({q_place}) UNION ALL "
                                    f"SELECT stockid, added_date FROM audit_master WHERE stockid IN ({q_place})"
                                    f") x GROUP BY stockid"
                                )
                                qa_params = tuple(canonical_ids) + tuple(canonical_ids)
                                qa_rows = db_utils.safe_read(q_qa_specific, qa_params) or []
                                qa_map = {str(r[0]): r[1] for r in qa_rows if r and r[0]}
                            else:
                                qa_rows = []
    
                            # Evaluate each stockid in the batch
                            for sid in batch:
                                er_ts_raw = stock_ts.get(sid)
                                er_ts_dt = _parse_ts(er_ts_raw)
    
                                # Resolve asset mapping: try to find a canonical stockid for this key
                                a_last_raw = None
                                q_last_raw = None
                                canonical = key_to_stockid.get(sid)
                                if canonical:
                                    a_last_raw = asset_map.get(canonical)
                                    q_last_raw = qa_map.get(canonical)
                                else:
                                    # No matching asset found by stockid/system_serial -> treat as awaiting
                                    awaiting += 1
                                    continue
    
                                a_last_dt = _parse_ts(a_last_raw)
                                q_last_dt = _parse_ts(q_last_raw)
    
                                # If no QA/audit seen after the erasure ts -> awaiting QA
                                if not q_last_dt:
                                    awaiting += 1
                                    continue
    
                                if er_ts_dt and q_last_dt and q_last_dt < er_ts_dt:
                                    # QA happened before the latest erasure -> awaiting again
                                    awaiting += 1
    
                        erased_awaiting_qa = int(awaiting)
                    else:
                        erased_awaiting_qa = 0
                else:
                    erased_awaiting_qa = 0
            except Exception as _e:
                diagnostics["errors"].append(str(_e))
                print(f"[Bottleneck] sqlite local_erasures read failed: {_e}")
    
            # 4) QA'd awaiting Sorting (ITAD_QA_App left join Stockbypallet)
            # NOTE: ITAD_QA_App does not include a `warehouse` column in some schemas.
            # Join through ITAD_asset_info to apply the warehouse filter safely.
            q_qa_sort = (
                "SELECT COUNT(DISTINCT q.stockid) FROM ITAD_QA_App q "
                "LEFT JOIN Stockbypallet s ON s.stockid = q.stockid "
                "LEFT JOIN ITAD_asset_info a ON a.stockid = q.stockid "
                "WHERE (a.warehouse IS NULL OR a.warehouse = 'Berry Hill') "
                "AND s.stockid IS NULL "
                "AND q.added_date >= %s AND q.added_date < %s"
            )
            qa_sort_res = db_utils.safe_read(q_qa_sort, (start, end))
            qa_awaiting_sorting = int(qa_sort_res[0][0]) if qa_sort_res and qa_sort_res[0] and qa_sort_res[0][0] is not None else 0
    
            # 5) Sorted count
            q_sorted = "SELECT COUNT(DISTINCT stockid) FROM Stockbypallet WHERE received_date >= %s AND received_date < %s"
            sorted_res = db_utils.safe_read(q_sorted, (start, end))
            sorted_count = int(sorted_res[0][0]) if sorted_res and sorted_res[0] and sorted_res[0][0] is not None else 0
    
            # 6) Disposition breakout from ITAD_asset_info
            q_disp = (
                "SELECT "
                "SUM(CASE WHEN a.condition = 'Dest:Refurbishment' THEN 1 ELSE 0 END) AS awaiting_refurb, "
                "SUM(CASE WHEN a.condition = 'Dest:Breakfix' THEN 1 ELSE 0 END) AS awaiting_breakfix "
                "FROM ITAD_asset_info a WHERE (a.warehouse IS NULL OR a.warehouse = 'Berry Hill') "
                "AND a.sla_complete_date >= %s AND a.sla_complete_date < %s"
            )
            disp_res = db_utils.safe_read(q_disp, (start, end))
            awaiting_refurb = int(disp_res[0][0] or 0) if disp_res and disp_res[0] else 0
            awaiting_breakfix = int(disp_res[0][1] or 0) if disp_res and disp_res[0] else 0
    
            # 7) SLA overdue
            q_sla = (
                "SELECT COUNT(*) FROM ITAD_asset_info a WHERE (a.warehouse IS NULL OR a.warehouse = 'Berry Hill') "
                "AND a.sla_complete_date < NOW() - INTERVAL 5 DAY "
                "AND (a.de_completed_date IS NULL OR a.de_completed_date = '')"
            )
            sla_res = db_utils.safe_read(q_sla)
            sla_overdue = int(sla_res[0][0]) if sla_res and sla_res[0] and sla_res[0][0] is not None else 0
    
            result = {
                "timestamp": datetime.utcnow().isoformat(),
                "filter_period": f"last_{days}_days",
                "goods_in_totes": goods_in,
                "awaiting_erasure": awaiting_erasure,
                "erased_awaiting_qa": erased_awaiting_qa,
                "qa_awaiting_sorting": qa_awaiting_sorting,
                "sorted": sorted_count,
                "dispositions": {"awaiting_refurb": awaiting_refurb, "awaiting_breakfix": awaiting_breakfix},
                "sla_overdue": sla_overdue,
            }
    
            # Attach diagnostics when requested (admin/manager only)
            try:
                if debug:
                    result["diagnostics"] = diagnostics
            except Exception:
                pass
    
            try:
                _bottleneck_cache.set(cache_key, result)
            except Exception:
                pass
    
            return JSONResponse(status_code=200, content=result)
        except Exception as e:
            import traceback as _tb
            print("Bottleneck snapshot error:")
            _tb.print_exc()
            return JSONResponse(status_code=500, content={"detail": "Bottleneck snapshot failed (server error). Check server logs."})
    
    
    @router.get("/api/bottlenecks/from-dashboard")
    async def get_bottleneck_from_dashboard(date: str = None, qa_user: str = None):
        """Lightweight bottleneck snapshot built from existing dashboard endpoints (today-only by default).
    
        Returns simple counts: awaiting_qa and awaiting_sorting plus small QA/erasure samples.
        """
        from datetime import date as _date, datetime as _dt
        import time
    
        # Use a short-lived TTL cache for identical dashboard queries
        global _bottleneck_dashboard_cache
        try:
            _bottleneck_dashboard_cache
        except NameError:
            _bottleneck_dashboard_cache = ttl_cache_cls(maxsize=256, ttl=60)
    
        CACHE_TTL = 60  # seconds (kept for compatibility)
    
        target_date = date if date else _date.today().isoformat()
        cache_key = f"{target_date}|{(qa_user or '').lower()}|default"
        print(f"[Bottleneck-From-Dashboard] request date={target_date} qa_user={(qa_user or '')} cache_key={cache_key}")
        cache_entry = _bottleneck_dashboard_cache.get(cache_key)
        if cache_entry is not None:
            print(f"[Bottleneck-From-Dashboard] cache hit for {cache_key}")
            return JSONResponse(status_code=200, content=cache_entry)
        print(f"[Bottleneck-From-Dashboard] cache miss for {cache_key}; calling dashboard endpoints")
    
        try:
    
            # Get merged daily stats (includes erased, qaApp, deQa, nonDeQa, qaTotal)
            print("[Bottleneck-From-Dashboard] loading daily stats directly")
            daily_rows = db.get_stats_range(target_date, target_date)
            try:
                _d = _date.fromisoformat(target_date)
                qa_daily = qa_export.get_qa_daily_totals_range(_d, _d)
                qa_by_date = {row.get("date"): row for row in (qa_daily or [])}
                for row in daily_rows:
                    qa_row = qa_by_date.get(row.get("date"), {})
                    row["qaApp"] = qa_row.get("qaApp", 0)
                    row["deQa"] = qa_row.get("deQa", 0)
                    row["nonDeQa"] = qa_row.get("nonDeQa", 0)
                    row["qaTotal"] = qa_row.get("qaTotal", 0)
            except Exception:
                pass
            daily = daily_rows[0] if daily_rows else {}
            print(f"[Bottleneck-From-Dashboard] daily rows={len(daily_rows)}")
    
            # Get QA dashboard today to fetch per-engineer counts
            print("[Bottleneck-From-Dashboard] calling QA dashboard helper")
            qa_dash = await compute_qa_dashboard_data("today", cache_get, cache_set)
            if isinstance(qa_dash, dict) and qa_dash.get('technicians'):
                print(f"[Bottleneck-From-Dashboard] qa_dash technicians={len(qa_dash.get('technicians', []))}")
    
            # Compute combined QA totals
            qa_total = daily.get("qaTotal") or qa_dash.get("summary", {}).get("combinedScans") or 0
            qa_app = daily.get("qaApp") or qa_dash.get("summary", {}).get("totalScans") or 0
            erased = daily.get("erased") or 0
    
            # Default lightweight calculation (bounded to dashboard totals)
            awaiting_qa = max(0, int(erased) - int(qa_total))
            awaiting_sorting = max(0, int(qa_total) - int(qa_app))
    
            # Attempt a more precise, device-level awaiting QA count by mapping
            # today's erasures (local SQLite) to stockids (MariaDB) and checking
            # for a QA/audit timestamp >= erasure timestamp. This is read-only
            # and grouped; if it fails we fall back to dashboard totals above.
            try:
                from datetime import date as _date
                precise = qa_export.get_awaiting_qa_counts_for_date(_date.fromisoformat(target_date))
                if precise and isinstance(precise, dict):
                    # Use the precise awaiting_qa where available (keeps value bounded by erased)
                    awaiting_qa = int(precise.get("awaiting_qa", awaiting_qa))
                    # Attach diagnostic fields to the result later
                    precise_meta = precise
                else:
                    precise_meta = None
            except Exception as _e:
                print(f"[Bottleneck-From-Dashboard] precise awaiting_qa check failed: {_e}")
                precise_meta = None
    
            # Use dashboard-derived counts only (erased - qa_total) to keep bottleneck
            # bounded by today's data captured on the Erasure/QA dashboards.
    
            # Find QA counts for requested qa_user (e.g., 'solomon')
            user_count = None
            if qa_user and qa_dash and qa_dash.get("technicians"):
                for tech in qa_dash["technicians"]:
                    if qa_user.lower() in str(tech.get("name", "")).lower():
                        user_count = tech.get("combinedScans")
                        break
    
            # Get erasure events for the day and aggregate by initials
            print("[Bottleneck-From-Dashboard] loading erasure events directly")
            erasures = db.get_erasure_events_range(target_date, target_date, None)
            print(f"[Bottleneck-From-Dashboard] erasures rows={len(erasures)}")
            erasure_by_initials = {}
            for ev in erasures:
                init = ev.get("initials") or ""
                if not init:
                    continue
                erasure_by_initials[init] = erasure_by_initials.get(init, 0) + 1
    
            # Find a sample pallet-scan by Owen in device history (stage == 'Sorting')
            print("[Bottleneck-From-Dashboard] loading device history directly")
            _d = _date.fromisoformat(target_date)
            hist_rows = qa_export.get_device_history_range(_d, _d)
            print(f"[Bottleneck-From-Dashboard] device_history rows={len(hist_rows)}")
            owen_pallet_sample = None
            for row in hist_rows:
                user = str(row.get("user") or "")
                stage = str(row.get("stage") or "")
                if "owen" in user.lower() and stage.lower() == "sorting":
                    owen_pallet_sample = {
                        "timestamp": row.get("timestamp"),
                        "stockid": row.get("stockid"),
                        "user": user,
                        "stage": stage,
                        "location": row.get("location")
                    }
                    break
    
            result = {
                "timestamp": _dt.now().isoformat(),
                "date": target_date,
                "awaiting_qa": awaiting_qa,
                "awaiting_sorting": awaiting_sorting,
                "erased": int(erased),
                "qa_total": int(qa_total),
                "qa_app": int(qa_app),
                "user_combined_scans": user_count,
                "erasure_by_initials": erasure_by_initials,
                "owen_pallet_sample": owen_pallet_sample,
                "note": "Data sourced from dashboard PowerBI and QA endpoints (today-only)."
            }
    
            # Include precise matching diagnostics when available
            if 'precise_meta' in locals() and precise_meta:
                result.update({
                    "precise_total_erasures": int(precise_meta.get("total_erasures", 0)),
                    "precise_matched_qas": int(precise_meta.get("matched", 0)),
                    "precise_awaiting_qa": int(precise_meta.get("awaiting_qa", 0)),
                })
    
            print(f"[Bottleneck-From-Dashboard] computed awaiting_qa={awaiting_qa} awaiting_sorting={awaiting_sorting}")
            try:
                _bottleneck_dashboard_cache.set(cache_key, result)
                print(f"[Bottleneck-From-Dashboard] cached result for {cache_key}")
            except Exception:
                print("[Bottleneck-From-Dashboard] cache write failed")
            return JSONResponse(status_code=200, content=result)
        except Exception as e:
            print(f"[Bottleneck-From-Dashboard] error: {e}")
            import traceback as _tb
            _tb.print_exc()
            return JSONResponse(status_code=500, content={"detail": "Failed to build bottleneck from dashboard."})
    
    
    @router.get("/api/bottlenecks/details")
    async def get_bottleneck_details(
        request: Request,
        category: str,
        value: str = None,
        limit: int = 100,
        days: int = 7,
        page: int = 1,
        page_size: int = 20
    ):
        """
        Get detailed device list for a specific bottleneck category - CURRENT state (no lookback).
        
        Categories:
        - unassigned: Devices without a QA user recorded
        - unpalleted: All unpalleted devices (current)
        - destination: Filter by destination/condition (value = destination name)
        - engineer: Filter by QA user (value = engineer email/name)
        - roller_pending: Data-bearing devices on rollers awaiting erasure
        - roller_awaiting_qa: Devices on rollers awaiting QA scan
        - roller_awaiting_pallet: Devices on rollers awaiting pallet ID
        - roller_station: Specific roller (value = roller name like "IA-ROLLER1")
        - quarantine: Devices in quarantine status
        """
        require_manager_or_admin(request)
        # pagination: normalize page and page_size; keep legacy `limit` as fallback
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or limit or 20), 500))
        days = max(1, min(int(days or 7), 90))
        
        import qa_export
        from datetime import datetime
        
        try:
            result = {
                "category": category,
                "value": value,
                "snapshot_timestamp": datetime.now().isoformat(),
                "devices": [],
                "total_count": 0,
                "showing": 0,
            }
            
            # Data-bearing device types (updated to match qa_export.py)
            DATA_BEARING_TYPES = [
                # Laptops
                'laptop', 'notebook', 'elitebook', 'probook', 'latitude', 'precision', 'xps', 'thinkpad', 'macbook', 'surface',
                # Desktops
                'desktop', 'optiplex', 'prodesk', 'precision', 'thinkcentre', 'imac', 'mac mini', 'mac pro',
                # Servers
                'server', 'blade', 'rackmount',
                # Network devices
                'switch', 'router', 'firewall', 'access point', 'network', 'hub',
                # Mobile devices
                'tablet', 'phone', 'mobile', 'smartphone', 'ipad', 'iphone', 'android', 'galaxy', 'handset', 'dect',
                # Storage devices
                'hard drive', 'ssd', 'hdd', 'nas', 'san',
                # Other computing devices
                'workstation', 'thin client', 'all-in-one'
            ]
            
            if category in ("roller_pending", "roller_awaiting_qa", "roller_awaiting_pallet", "roller_station"):
                # Query roller devices directly with recent activity window
                conn = qa_export.get_mariadb_connection()
                if not conn:
                    raise HTTPException(status_code=500, detail="Database connection failed")
                
                cursor = conn.cursor()
                
                # Base query for devices on rollers without pallet ID
                base_select = """
                    SELECT 
                        a.stockid, a.serialnumber, a.manufacturer, a.description,
                        a.condition, a.received_date, a.roller_location,
                        a.de_complete, a.de_completed_by, a.de_completed_date,
                        COALESCE(a.pallet_id, a.palletID) as pallet_id,
                        a.stage_current, a.last_update,
                        (SELECT MAX(q.added_date) FROM ITAD_QA_App q WHERE q.stockid = a.stockid) as last_qa_date
                    FROM ITAD_asset_info a
                """
                recent_clause = "AND a.last_update IS NOT NULL AND a.last_update >= DATE_SUB(NOW(), INTERVAL %s DAY)"
                
                if category == "roller_station" and value:
                    # Specific roller station - show all devices without pallet
                    offset = (page - 1) * page_size
                    cursor.execute(f"""
                            {base_select}
                            WHERE (a.roller_location = %s OR a.roller_location LIKE %s)
                                AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                                AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                                {recent_clause}
                            ORDER BY a.received_date DESC
                            LIMIT %s OFFSET %s
                                                    """, (value, f"%:{value}", days, page_size, offset))
                elif category == "roller_pending":
                    # Data-bearing devices awaiting erasure (not erased, no pallet)
                    # Build parameterized OR condition for data-bearing types to avoid
                    # passing raw '%' characters into pymysql's mogrify formatting.
                    types = DATA_BEARING_TYPES
                    type_clause = " OR ".join(["LOWER(a.description) LIKE %s" for _ in types])
                    type_params = tuple([f"%{t}%" for t in types])
                    offset = (page - 1) * page_size
                    cursor.execute(f"""
                            {base_select}
                            WHERE a.roller_location IS NOT NULL 
                                AND a.roller_location != ''
                                AND LOWER(a.roller_location) LIKE '%%roller%%'
                                AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                                AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                                AND (a.de_complete IS NULL OR LOWER(a.de_complete) NOT IN ('yes', 'true', '1'))
                                AND ({type_clause})
                                {recent_clause}
                            ORDER BY a.received_date DESC
                            LIMIT %s OFFSET %s
                                                    """, (*type_params, days, page_size, offset))
                elif category == "roller_awaiting_qa":
                    # Devices that are erased (or non-data-bearing) but haven't had QA scan
                    # On roller, no pallet, and either:
                    #   - Data-bearing: erased but no QA after erasure
                    #   - Non-data-bearing: no QA scan at all
                                    # Only include devices that are erased (de_complete) OR have Blancco records;
                                    # exclude devices whose destination/condition indicates Quarantine because
                                    # those are effectively awaiting sorting rather than QA.
                                    cursor.execute(f"""
                                            {base_select}
                                            WHERE a.roller_location IS NOT NULL 
                                                AND a.roller_location != ''
                                                AND LOWER(a.roller_location) LIKE '%%roller%%'
                                                AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                                                  AND LOWER(COALESCE(a.`condition`, '')) NOT LIKE '%%quarantine%%'
                                                AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                                                AND (
                                                    (LOWER(COALESCE(a.de_complete, '')) IN ('yes', 'true', '1')
                                                     AND NOT EXISTS (SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid AND q.added_date > a.de_completed_date))
                                                    OR
                                                    (EXISTS (SELECT 1 FROM ITAD_asset_info_blancco b WHERE b.stockid = a.stockid)
                                                     AND NOT EXISTS (SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid))
                                                )
                                                                                            {recent_clause}
                                                                                    ORDER BY a.received_date DESC
                                                                                    LIMIT %s OFFSET %s
                                                                                                                                    """, (days, page_size, (page-1)*page_size))
                else:  # roller_awaiting_pallet
                    # Devices that have been QA'd but don't have a pallet yet
                                    cursor.execute(f"""
                        {base_select}
                        WHERE a.roller_location IS NOT NULL 
                          AND a.roller_location != ''
                          AND LOWER(a.roller_location) LIKE '%%roller%%'
                          AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                          AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                          AND EXISTS (
                            SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid 
                            AND (a.de_completed_date IS NULL OR q.added_date > a.de_completed_date)
                          )
                                                {recent_clause}
                                            ORDER BY a.received_date DESC
                                            LIMIT %s OFFSET %s
                                                                    """, (days, page_size, (page-1)*page_size))
                
                devices = []
                for row in cursor.fetchall():
                    desc = row[3] or ""
                    is_data_bearing = any(t in desc.lower() for t in DATA_BEARING_TYPES)
                    is_erased = str(row[7] or "").lower() in ("yes", "true", "1")
                    last_qa = row[13]
                    de_completed = row[9]
                    
                    # Determine workflow stage
                    if is_data_bearing and not is_erased:
                        stage = "Awaiting Erasure"
                    elif last_qa and (not de_completed or last_qa > de_completed):
                        stage = "Awaiting Pallet"
                    else:
                        stage = "Awaiting QA"
                    
                    devices.append({
                        "stockid": row[0],
                        "serial": row[1],
                        "manufacturer": row[2],
                        "model": row[3],
                        "condition": row[4],
                        "received_date": str(row[5]) if row[5] else None,
                        "roller_location": row[6],
                        "de_complete": row[7],
                        "de_completed_by": row[8],
                        "de_completed_date": str(row[9]) if row[9] else None,
                        "pallet_id": row[10],
                        "stage_current": row[11],
                        "last_update": str(row[12]) if row[12] else None,
                        "workflow_stage": stage,
                        "is_data_bearing": is_data_bearing,
                    })
                
                # Get total count based on category
                if category == "roller_station" and value:
                    cursor.execute("""
                        SELECT COUNT(*) FROM ITAD_asset_info 
                        WHERE (roller_location = %s OR roller_location LIKE %s)
                          AND `condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                          AND (COALESCE(pallet_id, palletID, '') = '' OR COALESCE(pallet_id, palletID) IS NULL OR COALESCE(pallet_id, palletID) LIKE 'NOPOST%%')
                                                AND last_update IS NOT NULL
                                                AND last_update >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                    """, (value, f"%:{value}", days))
                elif category == "roller_pending":
                    # Count data-bearing devices awaiting erasure
                                    types = DATA_BEARING_TYPES
                                    type_clause = " OR ".join(["LOWER(description) LIKE %s" for _ in types])
                                    type_params = tuple([f"%{t}%" for t in types])
                                    cursor.execute(f"""
                                            SELECT COUNT(*) FROM ITAD_asset_info 
                                            WHERE roller_location IS NOT NULL AND roller_location != ''
                                                AND LOWER(roller_location) LIKE '%%roller%%'
                                                AND `condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                                                AND (COALESCE(pallet_id, palletID, '') = '' OR COALESCE(pallet_id, palletID) IS NULL OR COALESCE(pallet_id, palletID) LIKE 'NOPOST%%')
                                                AND (de_complete IS NULL OR LOWER(de_complete) NOT IN ('yes', 'true', '1'))
                                                AND ({type_clause})
                                                                                            AND last_update IS NOT NULL
                                                                                            AND last_update >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                                                    """, (*type_params, days,))
                elif category == "roller_awaiting_qa":
                    # Count devices awaiting QA
                    cursor.execute("""
                        SELECT COUNT(*) FROM ITAD_asset_info a
                        WHERE a.roller_location IS NOT NULL AND a.roller_location != ''
                          AND LOWER(a.roller_location) LIKE '%%roller%%'
                          AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                          AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                          AND (
                            (LOWER(COALESCE(a.de_complete, '')) IN ('yes', 'true', '1')
                             AND NOT EXISTS (SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid AND q.added_date > a.de_completed_date))
                            OR
                            (LOWER(COALESCE(a.de_complete, '')) NOT IN ('yes', 'true', '1')
                             AND NOT EXISTS (SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid))
                          )
                                                AND a.last_update IS NOT NULL
                                                AND a.last_update >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                    """, (days,))
                else:  # roller_awaiting_pallet
                    # Count devices with QA but no pallet
                    cursor.execute("""
                        SELECT COUNT(*) FROM ITAD_asset_info a
                        WHERE a.roller_location IS NOT NULL AND a.roller_location != ''
                          AND LOWER(a.roller_location) LIKE '%%roller%%'
                          AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                          AND (COALESCE(a.pallet_id, a.palletID, '') = '' OR COALESCE(a.pallet_id, a.palletID) IS NULL)
                          AND EXISTS (
                            SELECT 1 FROM ITAD_QA_App q WHERE q.stockid = a.stockid 
                            AND (a.de_completed_date IS NULL OR q.added_date > a.de_completed_date)
                          )
                                                AND a.last_update IS NOT NULL
                                                AND a.last_update >= DATE_SUB(NOW(), INTERVAL %s DAY)
                                    """, (days,))
                
                total = cursor.fetchone()[0]
                cursor.close()
                conn.close()
                
                result["devices"] = devices
                result["total_count"] = total
                result["showing"] = len(devices)
                
            else:
                # Use recent unpalleted devices query with filters
                all_devices = qa_export.get_unpalleted_devices_recent(days_threshold=days)
                
                filtered = []
                for d in all_devices:
                    qa_user = (d.get("qa_user") or "").strip()
                    condition = (d.get("condition") or "").strip()
                    
                    if category == "unassigned":
                        if not qa_user:
                            filtered.append(d)
                    elif category == "unpalleted":
                        filtered.append(d)
                    elif category == "destination" and value:
                        if condition.lower() == value.lower():
                            filtered.append(d)
                    elif category == "engineer" and value:
                        if qa_user.lower() == value.lower():
                            filtered.append(d)
                    elif category == "quarantine":
                        if "quarantine" in condition.lower():
                            filtered.append(d)
                
                result["total_count"] = len(filtered)
                result["devices"] = filtered[:limit]
                result["showing"] = len(result["devices"])
            
            # Add summary stats for the category
            if result["devices"]:
                # Count by manufacturer
                mfg_counts = {}
                condition_counts = {}
                for d in result["devices"]:
                    mfg = d.get("manufacturer") or "Unknown"
                    mfg_counts[mfg] = mfg_counts.get(mfg, 0) + 1
                    cond = d.get("condition") or "Unknown"
                    condition_counts[cond] = condition_counts.get(cond, 0) + 1
                
                result["breakdown"] = {
                    "by_manufacturer": sorted(
                        [{"name": k, "count": v} for k, v in mfg_counts.items()],
                        key=lambda x: x["count"], reverse=True
                    )[:10],
                    "by_condition": sorted(
                        [{"name": k, "count": v} for k, v in condition_counts.items()],
                        key=lambda x: x["count"], reverse=True
                    )[:10],
                }
            
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"Bottleneck details error: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))
    
    
    

    return router
