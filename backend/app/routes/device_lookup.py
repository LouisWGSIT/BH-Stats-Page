from datetime import datetime, timedelta
from typing import Dict

from fastapi import APIRouter, HTTPException, Request
import json
import os


def create_device_lookup_router(*, db_module, qa_export_module, require_manager_or_admin, get_role_from_request, ttl_cache_cls):
    router = APIRouter()
    db = db_module
    qa_export = qa_export_module

    @router.get("/api/device-lookup/{stock_id}")
    async def device_lookup(stock_id: str, request: Request):
        """Search for a device across all data sources to trace its journey (manager only)"""
        require_manager_or_admin(request)
        
        results = {
            "stock_id": stock_id,
            "found_in": [],
            "timeline": [],
            "asset_info": None,
            "pallet_info": None,
            "last_known_user": None,
            "last_known_location": None,
        }
        
        import time, logging
        logger = logging.getLogger('device_lookup')
        try:
            # quick guard: ensure connection runs read-only where possible
            try:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
            except Exception:
                pass
            start_all = time.time()
            # honor per-request audit lookback (default 30 days, deep lookup 120 days)
            try:
                audit_days = int(request.query_params.get('audit_days', '30'))
            except Exception:
                audit_days = 30
            conn = qa_export.get_mariadb_connection()
            if not conn:
                raise HTTPException(status_code=500, detail="Database connection failed")
            # ensure read-only intent to avoid accidental write locks where supported
            try:
                conn.autocommit = True
            except Exception:
                pass
            try:
                cur_tmp = conn.cursor()
                try:
                    cur_tmp.execute("SET SESSION TRANSACTION READ ONLY")
                except Exception:
                    pass
                try:
                    cur_tmp.close()
                except Exception:
                    pass
            except Exception:
                pass
    
            cursor = conn.cursor()
            
            # 1. Check ITAD_asset_info for asset details
            asset_row = None
            # Some deployments have newer optional columns (quarantine, etc.).
            # Probe INFORMATION_SCHEMA for the presence of the `quarantine` column
            # to avoid issuing a SELECT that references missing columns (which
            # caused the "Unknown column 'quarantine'" error previously).
            try:
                try:
                    cursor.execute(
                        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s AND TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = %s",
                        ("ITAD_asset_info", "quarantine")
                    )
                    has_quarantine = cursor.fetchone() is not None
                except Exception:
                    # If the probe fails (lack of privilege), default to safe path
                    has_quarantine = False
    
                if has_quarantine:
                    cursor.execute("""
                        SELECT stockid, serialnumber, manufacturer, description, `condition`, 
                               COALESCE(pallet_id, palletID) as pallet_id, last_update, location,
                               roller_location, stage_current, stage_next, received_date,
                               quarantine, quarantine_reason, process_complete,
                               de_complete, de_completed_by, de_completed_date
                        FROM ITAD_asset_info 
                        WHERE stockid = %s OR serialnumber = %s
                    """, (stock_id, stock_id))
                else:
                    cursor.execute("""
                        SELECT stockid, serialnumber, manufacturer, description, `condition`, 
                               COALESCE(pallet_id, palletID) as pallet_id, last_update, location
                        FROM ITAD_asset_info 
                        WHERE stockid = %s OR serialnumber = %s
                    """, (stock_id, stock_id))
                asset_row = cursor.fetchone()
            except Exception:
                # As a final fallback, try the minimal projection to avoid hard failures
                try:
                    cursor.execute("""
                        SELECT stockid, serialnumber, manufacturer, description, `condition`, 
                               COALESCE(pallet_id, palletID) as pallet_id, last_update, location
                        FROM ITAD_asset_info 
                        WHERE stockid = %s OR serialnumber = %s
                    """, (stock_id, stock_id))
                    asset_row = cursor.fetchone()
                except Exception:
                    asset_row = None
            row = asset_row
            if row:
                results["found_in"].append("ITAD_asset_info")
                results["asset_info"] = {
                    "stock_id": row[0],
                    "serial": row[1],
                    "manufacturer": row[2],
                    "model": row[3],
                    "condition": row[4],
                    "pallet_id": row[5],
                    "last_update": str(row[6]) if row[6] else None,
                    "location": row[7],
                }
                if len(row) > 8:
                    results["asset_info"].update({
                        "roller_location": row[8],
                        "stage_current": row[9],
                        "stage_next": row[10],
                        "received_date": str(row[11]) if row[11] else None,
                        "quarantine": row[12],
                        "quarantine_reason": row[13],
                        "process_complete": row[14],
                        "de_complete": row[15] if len(row) > 15 else None,
                        "de_completed_by": row[16] if len(row) > 16 else None,
                        "de_completed_date": str(row[17]) if len(row) > 17 and row[17] else None,
                    })
                if row[5]:  # pallet_id
                    results["pallet_info"] = {"pallet_id": row[5]}
                if row[7]:  # location
                    results["last_known_location"] = row[7]
                # Asset info is recorded in `results["asset_info"]` but we avoid
                # emitting a separate generic timeline row here since it often
                # contains no human-friendly location. Timeline rows are built from
                # richer, action-oriented sources (QA, audit, erasure, pallet).
            
            # 2. Check Stockbypallet for pallet assignment
            t0 = time.time()
            cursor.execute("""
                SELECT stockid, pallet_id
                FROM Stockbypallet
                WHERE stockid = %s
            """, (stock_id,))
            row = cursor.fetchone()
            logger.info("Stockbypallet lookup: %.3fs", time.time()-t0)
            if row:
                results["found_in"].append("Stockbypallet")
                if not results["pallet_info"]:
                    results["pallet_info"] = {}
                results["pallet_info"]["pallet_id"] = row[1]
            
            # 3. Get pallet details if we have a pallet_id
            # Guard against unexpected None for `results` or `pallet_info`.
            pallet_id = None
            pallet_info = (results or {}).get("pallet_info") if isinstance(results, dict) else None
            if pallet_info and pallet_info.get("pallet_id"):
                pallet_id = pallet_info.get("pallet_id")
                cursor.execute("""
                    SELECT pallet_id, destination, pallet_location, pallet_status, create_date
                    FROM ITAD_pallet
                    WHERE pallet_id = %s
                """, (pallet_id,))
                row = cursor.fetchone()
                if row:
                    results["pallet_info"].update({
                        "destination": row[1],
                        "location": row[2],
                        "status": row[3],
                        "create_date": str(row[4]) if row[4] else None,
                    })
                    # Add a dedicated pallet creation/assignment event to the timeline
                    try:
                        results.setdefault("timeline", [])
                        pallet_ts = str(row[4]) if row[4] else None
                        results["timeline"].append({
                            "timestamp": pallet_ts,
                            "stage": f"Pallet {pallet_id}",
                            "user": None,
                            "location": row[2],
                            "source": "ITAD_pallet",
                            "pallet_id": pallet_id,
                            "pallet_destination": row[1],
                            "pallet_location": row[2],
                            "details": "pallet record",
                        })
                    except Exception:
                        pass
            
            # 4. Check ITAD_QA_App for sorting scans (include richer metadata when available)
            # Decide whether extended QA projection is safe by probing INFORMATION_SCHEMA
            t0 = time.time()
            try:
                try:
                    cursor.execute(
                        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s AND TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = %s",
                        ("ITAD_QA_App", "sales_order")
                    )
                    has_sales_order = cursor.fetchone() is not None
                except Exception:
                    has_sales_order = False
    
                # Respect audit_days to limit QA scan lookback and avoid long-running queries
                if has_sales_order:
                    cursor.execute("""
                        SELECT added_date, username, scanned_location, stockid, photo_location, sales_order
                        FROM ITAD_QA_App
                        WHERE stockid = %s
                          AND DATE(added_date) >= DATE_SUB(NOW(), INTERVAL %s DAY)
                        ORDER BY added_date ASC
                    """, (stock_id, audit_days))
                else:
                    cursor.execute("""
                        SELECT added_date, username, scanned_location, stockid
                        FROM ITAD_QA_App
                        WHERE stockid = %s
                          AND DATE(added_date) >= DATE_SUB(NOW(), INTERVAL %s DAY)
                        ORDER BY added_date ASC
                    """, (stock_id, audit_days))
                rows = cursor.fetchall()
            except Exception as _ex:
                # If anything goes wrong, avoid raising DB error to caller; log and continue
                logger.exception("[device_lookup] QA projection probe/execute failed: %s", _ex)
                rows = []
            logger.info("ITAD_QA_App lookup: %.3fs", time.time()-t0)
    
            # start background confirmed_locations read to overlap IO
            import sqlite3
            from concurrent.futures import ThreadPoolExecutor
            def _fetch_confirmed():
                try:
                    sqlite_conn = sqlite3.connect(db.DB_PATH)
                    sqlite_cur = sqlite_conn.cursor()
                    sqlite_cur.execute("SELECT location, user, ts FROM confirmed_locations WHERE stockid = ? ORDER BY ts DESC LIMIT 1", (stock_id,))
                    conf = sqlite_cur.fetchone()
                    sqlite_cur.close()
                    sqlite_conn.close()
                    return conf
                except Exception:
                    return None
            try:
                _executor = ThreadPoolExecutor(max_workers=1)
                conf_future = _executor.submit(_fetch_confirmed)
            except Exception:
                conf_future = None
    
            for row in rows:
                try:
                    # Unpack defensively depending on which projection succeeded
                    if len(row) >= 6:
                        added_date, username, scanned_location, q_stockid, photo_location, sales_order = row
                    elif len(row) >= 4:
                        added_date, username, scanned_location, q_stockid = row[0], row[1], row[2], row[3]
                        photo_location = None
                        sales_order = None
                    else:
                        added_date, username, scanned_location = (row[0], row[1], row[2])
                        q_stockid = None
                        photo_location = None
                        sales_order = None
                except Exception:
                    added_date, username, scanned_location = (None, None, None)
                    q_stockid = None
                    photo_location = None
                    sales_order = None
                results.setdefault("found_in", [])
                if "ITAD_QA_App" not in results["found_in"]:
                    results["found_in"].append("ITAD_QA_App")
                results["timeline"].append({
                    "timestamp": str(added_date) if added_date is not None else None,
                    "stage": "Sorting",
                    "user": username,
                    "location": scanned_location,
                    "source": "ITAD_QA_App",
                    "stockid": q_stockid or stock_id,
                    "serial": None,
                    "device_type": None,
                    "manufacturer": (results.get("asset_info") or {}).get("manufacturer"),
                    "model": (results.get("asset_info") or {}).get("model"),
                    "pallet_id": (results.get("pallet_info") or {}).get("pallet_id"),
                    "pallet_destination": (results.get("pallet_info") or {}).get("destination"),
                    "pallet_location": (results.get("pallet_info") or {}).get("location"),
                    "sales_order": sales_order,
                    "photo_location": photo_location,
                })
                results["last_known_user"] = username
                results["last_known_location"] = scanned_location
            
            # 5. Check audit_master for QA submissions (include descriptions)
            cursor.execute("""
                SELECT date_time, audit_type, user_id, log_description, log_description2
                FROM audit_master
                WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload', 
                         'Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload')
                  AND (log_description LIKE %s OR log_description2 LIKE %s)
                  AND date_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
                ORDER BY date_time ASC
            """, (f'%{stock_id}%', f'%{stock_id}%', audit_days))
            for row in cursor.fetchall():
                try:
                    date_time, audit_type, user_id, log_description, log_description2 = row
                except Exception:
                    date_time, audit_type, user_id = row[0], row[1], row[2]
                    log_description = None
                    log_description2 = None
                results.setdefault("found_in", [])
                results["found_in"].append("audit_master") if "audit_master" not in results["found_in"] else None
                stage = "QA Data Bearing" if str(audit_type or '').startswith("DEAPP_") else "QA Non-Data Bearing"
                results["timeline"].append({
                    "timestamp": str(date_time),
                    "stage": stage,
                    "user": user_id,
                    "location": None,
                    "source": "audit_master",
                    "stockid": stock_id,
                    "log_description": log_description,
                    "log_description2": log_description2,
                })
                results["last_known_user"] = user_id
            
            # 6. Check ITAD_asset_info_blancco for erasure records (include serial/manufacturer/model)
            # Probe INFORMATION_SCHEMA to choose safe blancco projection
            try:
                try:
                    cursor.execute(
                        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s AND TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = %s",
                        ("ITAD_asset_info_blancco", "added_date")
                    )
                    has_added_date = cursor.fetchone() is not None
                except Exception:
                    has_added_date = False
    
                if has_added_date:
                    cursor.execute("""
                        SELECT stockid, serial, manufacturer, model, erasure_status, added_date, username
                        FROM ITAD_asset_info_blancco
                        WHERE stockid = %s OR serial = %s
                    """, (stock_id, stock_id))
                else:
                    cursor.execute("""
                        SELECT stockid, serial, manufacturer, model, erasure_status
                        FROM ITAD_asset_info_blancco
                        WHERE stockid = %s OR serial = %s
                    """, (stock_id, stock_id))
                b_rows = cursor.fetchall()
            except Exception as _ex_b:
                print(f"[device_lookup] Blancco projection probe/execute failed: {_ex_b}")
                b_rows = []
    
            for row in b_rows:
                try:
                    if len(row) >= 7:
                        b_stockid, b_serial, b_manufacturer, b_model, b_status, b_added, b_user = row
                    elif len(row) >= 5:
                        b_stockid, b_serial, b_manufacturer, b_model, b_status = row[0], row[1], row[2], row[3], row[4]
                        b_added = None
                        b_user = None
                    else:
                        # Unexpected shape
                        continue
                except Exception:
                    b_stockid = b_serial = b_manufacturer = b_model = b_status = None
                    b_added = None
                    b_user = None
                results.setdefault("found_in", [])
                if "ITAD_asset_info_blancco" not in results["found_in"]:
                    results["found_in"].append("ITAD_asset_info_blancco")
                # Represent Blancco rows as a canonical 'Erasure station' timeline event
                # (previously surfaced as 'Erasure (Successful)' or similar). The
                # database naming is inconsistent: Blancco reports may appear to be
                # labelled as 'erasure' or even show operator names that are actually
                # QA actions. We surface the canonical stage name 'Erasure station'
                # and include the raw blancco status and operator so the UI can
                # display the authoritative Blancco evidence without creating a
                # separate 'Erasure (Blancco)' location to look in.
                # Try to merge Blancco evidence into an existing nearby QA/audit event
                    # If we already have a local_erasures provenance for this stock/serial,
                    # skip adding the MariaDB Blancco copy to avoid duplicate/confusing entries.
                    try:
                        suppressed = False
                        existing = results.get('timeline', []) or []
                        for ev in existing:
                            try:
                                if ev.get('source') == 'local_erasures':
                                    # match by serial or stockid/job
                                    if b_serial and (str(ev.get('system_serial') or ev.get('serial') or '').strip() == str(b_serial).strip()):
                                        suppressed = True
                                        break
                                    if b_stockid and (str(ev.get('job_id') or ev.get('stockid') or '') == str(b_stockid)):
                                        suppressed = True
                                        break
                            except Exception:
                                continue
                        if not suppressed:
                            # Represent Blancco rows as a canonical 'Erasure station' timeline event
                            # (previously surfaced as 'Erasure (Successful)' or similar). The
                            # database naming is inconsistent: Blancco reports may appear to be
                            # labelled as 'erasure' or even show operator names that are actually
                            # QA actions. We surface the canonical stage name 'Erasure station'
                            # and include the raw blancco status and operator so the UI can
                            # display the authoritative Blancco evidence without creating a
                            # separate 'Erasure (Blancco)' location to look in.
                            # Try to merge Blancco evidence into an existing nearby QA/audit event
                            from datetime import datetime as _dt
                            MERGE_WINDOW = int(os.getenv('MERGE_TIMELINE_WINDOW_SECONDS', '60'))
    
                            def _parse_ts_local(ts):
                                if not ts:
                                    return None
                                try:
                                    if isinstance(ts, str):
                                        try:
                                            return _dt.fromisoformat(ts.replace('Z', '+00:00'))
                                        except Exception:
                                            pass
                                        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                                            try:
                                                return _dt.strptime(ts, fmt)
                                            except Exception:
                                                continue
                                    elif hasattr(ts, 'timetuple'):
                                        return ts
                                except Exception:
                                    return None
    
                            def _try_attach_blancco():
                                if not b_added:
                                    return False
                                try:
                                    b_dt = _parse_ts_local(b_added)
                                except Exception:
                                    b_dt = None
                                for ev in results.get('timeline', []):
                                    try:
                                        if not ev.get('timestamp'):
                                            continue
                                        ev_dt = _parse_ts_local(ev.get('timestamp'))
                                        if not ev_dt or not b_dt:
                                            continue
                                        if abs((ev_dt - b_dt).total_seconds()) <= MERGE_WINDOW:
                                            ev.setdefault('sources', [])
                                            ev['sources'].append({
                                                'type': 'blancco',
                                                'source': 'ITAD_asset_info_blancco',
                                                'ts': b_added,
                                                'initials': b_user,
                                                'status': b_status,
                                                'manufacturer': b_manufacturer,
                                                'model': b_model,
                                                'serial': b_serial,
                                            })
                                            ev['is_blancco_record'] = True
                                            return True
                                    except Exception:
                                        continue
                                return False
    
                            attached = _try_attach_blancco()
                            if not attached:
                                results["timeline"].append({
                                    "timestamp": str(b_added) if b_added else None,
                                    "stage": "Blancco record",
                                    "user": b_user,
                                    "location": None,
                                    "source": "ITAD_asset_info_blancco",
                                    "serial": b_serial,
                                    "stockid": b_stockid,
                                    "manufacturer": b_manufacturer,
                                    "model": b_model,
                                    "details": f"{b_manufacturer} {b_model}" if b_manufacturer or b_model else None,
                                    "blancco_status": b_status,
                                    "is_blancco_record": True,
                                })
                    except Exception:
                        # fallback to appending as before
                        # fallback: append as a Blancco record (see note above)
                        results["timeline"].append({
                            "timestamp": str(b_added) if b_added else None,
                            "stage": "Blancco record",
                            "user": b_user,
                            "location": None,
                            "source": "ITAD_asset_info_blancco",
                            "serial": b_serial,
                            "stockid": b_stockid,
                            "manufacturer": b_manufacturer,
                            "model": b_model,
                            "details": f"{b_manufacturer} {b_model}" if b_manufacturer or b_model else None,
                            "blancco_status": b_status,
                            "is_blancco_record": True,
                        })
                try:
                    from datetime import datetime as _dt
                    MERGE_WINDOW = int(os.getenv('MERGE_TIMELINE_WINDOW_SECONDS', '60'))
    
                    def _parse_ts_local(ts):
                        if not ts:
                            return None
                        try:
                            if isinstance(ts, str):
                                try:
                                    return _dt.fromisoformat(ts.replace('Z', '+00:00'))
                                except Exception:
                                    pass
                                for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                                    try:
                                        return _dt.strptime(ts, fmt)
                                    except Exception:
                                        continue
                            elif hasattr(ts, 'timetuple'):
                                return ts
                        except Exception:
                            return None
                        return None
    
                    merged_into_existing = False
                    b_dt = _parse_ts_local(str(b_added)) if b_added else None
                    for ev in results.get('timeline', []):
                        try:
                            ev_ts = _parse_ts_local(ev.get('timestamp'))
                            if not ev_ts or not b_dt:
                                # also allow exact string match as fallback
                                if ev.get('timestamp') and b_added and str(ev.get('timestamp')) == str(b_added):
                                    ev.setdefault('sources', [ev.get('source')])
                                    if 'ITAD_asset_info_blancco' not in ev['sources']:
                                        ev['sources'].append('ITAD_asset_info_blancco')
                                    ev['blancco_status'] = b_status
                                    ev['is_blancco_record'] = True
                                    merged_into_existing = True
                                    break
                                continue
                            diff = abs((ev_ts - b_dt).total_seconds())
                            if diff <= MERGE_WINDOW and (str(ev.get('source') or '').lower().startswith('audit_master') or 'qa' in str(ev.get('stage') or '').lower()):
                                # attach blancco provenance to this existing QA/audit event
                                ev.setdefault('sources', [ev.get('source')])
                                if 'ITAD_asset_info_blancco' not in ev['sources']:
                                    ev['sources'].append('ITAD_asset_info_blancco')
                                ev['blancco_status'] = b_status
                                ev['is_blancco_record'] = True
                                merged_into_existing = True
                                break
                        except Exception:
                            continue
                    if not merged_into_existing:
                        # Do NOT create a separate 'Erasure station' search location
                        # from MariaDB Blancco rows. In this deployment Blancco rows
                        # in MariaDB are a downstream copy of server messages and
                        # should only act as provenance. If they don't merge into an
                        # existing QA/audit event, append a lightweight 'Blancco
                        # record' timeline entry for visibility but it will not be
                        # treated as a separate plausible search location.
                        results["timeline"].append({
                            "timestamp": str(b_added) if b_added else None,
                            "stage": "Blancco record",
                            "user": b_user,
                            "location": None,
                            "source": "ITAD_asset_info_blancco",
                            "serial": b_serial,
                            "stockid": b_stockid,
                            "manufacturer": b_manufacturer,
                            "model": b_model,
                            "details": f"{b_manufacturer} {b_model}" if b_manufacturer or b_model else None,
                            "blancco_status": b_status,
                            "is_blancco_record": True,
                        })
                except Exception:
                    # fallback to appending as before
                    # fallback: append as a Blancco record (see note above)
                    results["timeline"].append({
                        "timestamp": str(b_added) if b_added else None,
                        "stage": "Blancco record",
                        "user": b_user,
                        "location": None,
                        "source": "ITAD_asset_info_blancco",
                        "serial": b_serial,
                        "stockid": b_stockid,
                        "manufacturer": b_manufacturer,
                        "model": b_model,
                        "details": f"{b_manufacturer} {b_model}" if b_manufacturer or b_model else None,
                        "blancco_status": b_status,
                        "is_blancco_record": True,
                    })
            
            cursor.close()
            conn.close()
            
            # 7. Check local SQLite erasures table
            try:
                import sqlite3
                sqlite_conn = sqlite3.connect(db.DB_PATH)
                sqlite_cursor = sqlite_conn.cursor()
                # Build candidate identifiers: include the requested stock_id plus
                # any serial known from asset_info so that lookups by stock id
                # also match erasure rows recorded by serial number.
                candidates = [str(stock_id)]
                try:
                    ai = results.get('asset_info') or {}
                    asset_serial = (ai.get('serial') or '').strip()
                    if asset_serial and asset_serial not in candidates:
                        candidates.append(asset_serial)
                except Exception:
                    asset_serial = None
    
                # Prepare placeholders and parameters for IN (...) clauses
                placeholders = ','.join(['?'] * len(candidates))
                params = tuple(candidates)
    
                sqlite_cursor.execute(f"""
                    SELECT ts, date, initials, device_type, event, manufacturer, model, system_serial, disk_serial, job_id, drive_size, drive_type, drive_count
                    FROM erasures
                    WHERE system_serial IN ({placeholders}) OR disk_serial IN ({placeholders}) OR job_id IN ({placeholders})
                    ORDER BY date ASC, ts ASC
                """, params * 3)
                for row in sqlite_cursor.fetchall():
                    try:
                        ts, date_str, initials, device_type, event, manufacturer, model, system_serial, disk_serial, job_id, drive_size, drive_type, drive_count = row
                    except Exception:
                        ts, date_str, initials, device_type, event = row[0], row[1], row[2], row[3], row[4]
                        manufacturer = model = system_serial = disk_serial = job_id = drive_size = drive_type = drive_count = None
                    results.setdefault("found_in", [])
                    results["found_in"].append("local_erasures") if "local_erasures" not in results["found_in"] else None
    
                    # Build a provenance object for this erasure record
                    erasure_prov = {
                        "type": "erasure",
                        "source": "local_erasures",
                        "ts": ts or date_str,
                        "initials": initials,
                        "job_id": job_id,
                        "device_type": device_type,
                        "manufacturer": manufacturer,
                        "model": model,
                        "system_serial": system_serial,
                        "disk_serial": disk_serial,
                        "drive_size": drive_size,
                        "drive_type": drive_type,
                        "drive_count": drive_count,
                    }
    
                    # Try to attach this erasure provenance to a nearby QA/audit/asset event
                    attached = False
                    try:
                        from datetime import datetime as _dt
                        MERGE_WINDOW = int(os.getenv('MERGE_TIMELINE_WINDOW_SECONDS', '60'))
    
                        def _to_dt(val):
                            if not val:
                                return None
                            if isinstance(val, _dt):
                                return val
                            try:
                                if isinstance(val, str):
                                    return _dt.fromisoformat(val.replace('Z', '+00:00'))
                            except Exception:
                                try:
                                    # fallback common format
                                    return _dt.strptime(val, '%Y-%m-%d %H:%M:%S')
                                except Exception:
                                    return None
                            return None
    
                        e_ts = _to_dt(ts or date_str)
                        # prefer attaching to QA/audit/history/asset events
                        for ev in results.get('timeline', []):
                            try:
                                src = (ev.get('source') or '')
                                stage = (ev.get('stage') or '').lower()
                                # candidate sources/stages indicating QA/audit/asset
                                if not any(k in (src or '').lower() for k in ('audit_master', 'qa', 'qa_export', 'asset_info', 'qa_export.history')) and not ('qa' in stage or 'audit' in stage or 'history' in stage):
                                    continue
                                ev_ts = _to_dt(ev.get('timestamp'))
                                if not ev_ts or not e_ts:
                                    continue
                                delta = abs((ev_ts - e_ts).total_seconds())
                                if delta <= MERGE_WINDOW:
                                    # attach provenance
                                    ev.setdefault('sources', [])
                                    ev['sources'].append(erasure_prov)
                                    # mark that this event has blancco provenance for UI
                                    ev['is_blancco_record'] = True
                                    attached = True
                                    try:
                                        logging.info("[device_lookup] attached erasure prov job=%s initials=%s stock=%s to event source=%s stage=%s ts=%s", job_id, initials, stock_id, ev.get('source'), ev.get('stage'), ev.get('timestamp'))
                                    except Exception:
                                        pass
                                    break
                            except Exception:
                                continue
                    except Exception:
                        attached = False
    
                    if not attached:
                        # Fallback: add a provenance-only timeline event
                        results["timeline"].append({
                            "timestamp": ts or date_str,
                            "stage": "Blancco record",
                            "user": initials,
                            "location": None,
                            "source": "local_erasures",
                            "device_type": device_type,
                            "manufacturer": manufacturer,
                            "model": model,
                            "system_serial": system_serial,
                            "disk_serial": disk_serial,
                            "job_id": job_id,
                            "drive_size": drive_size,
                            "drive_type": drive_type,
                            "drive_count": drive_count,
                            "is_blancco_record": True,
                            "sources": [erasure_prov],
                        })
                        try:
                            logging.info("[device_lookup] added blancco provenance-only event job=%s initials=%s stock=%s ts=%s", job_id, initials, stock_id, ts or date_str)
                        except Exception:
                            pass
                    else:
                        # If attached, ensure last_known_user is captured
                        pass
    
                    # Prefer last_known_user from QA/audit sources. Only set from
                    # erasure initials if no last_known_user is already present.
                    try:
                        if initials and not results.get("last_known_user"):
                            results["last_known_user"] = initials
                    except Exception:
                        pass
    
                    # Cleanup: find any MariaDB-copied Blancco timeline events that
                    # refer to the same serial/job and merge them into the local
                    # erasure provenance we just attached/added, then remove the
                    # duplicate MariaDB event so the timeline is not confusing.
                    try:
                        to_remove_idxs = []
                        # find the timeline event that contains our local_erasures provenance
                        target_ev = None
                        for tev in results.get('timeline', []):
                            try:
                                for s in tev.get('sources', []) or []:
                                    if s and s.get('source') == 'local_erasures' and (s.get('job_id') == job_id or (s.get('system_serial') and system_serial and str(s.get('system_serial')) == str(system_serial))):
                                        target_ev = tev
                                        break
                                if target_ev:
                                    break
                            except Exception:
                                continue
    
                        # If we didn't find a target event, try to locate a provenance-only
                        # local_erasures event we just appended (match by job_id and ts)
                        if not target_ev:
                            for tev in reversed(results.get('timeline', [])):
                                try:
                                    if tev.get('source') == 'local_erasures' and (tev.get('job_id') == job_id or (system_serial and str(tev.get('system_serial') or '') == str(system_serial))):
                                        target_ev = tev
                                        break
                                except Exception:
                                    continue
    
                        # Now find any ITAD_asset_info_blancco events that match and merge
                        for idx, ev in enumerate(list(results.get('timeline', []))):
                            try:
                                if (ev.get('source') or '').lower() == 'itad_asset_info_blancco' or 'blancco' in str(ev.get('source') or '').lower():
                                    # match by serial or stockid/job
                                    ev_serial = ev.get('serial') or ev.get('stockid') or ev.get('stockid')
                                    ev_job = ev.get('stockid') or ev.get('job_id') or None
                                    if (system_serial and ev_serial and str(ev_serial).strip() == str(system_serial).strip()) or (job_id and ev_job and str(ev_job).strip() == str(job_id).strip()):
                                        # attach this blancco event as provenance to target_ev if present
                                        if target_ev is not None:
                                            target_ev.setdefault('sources', [])
                                            blobj = {
                                                'type': 'blancco',
                                                'source': 'ITAD_asset_info_blancco',
                                                'ts': ev.get('timestamp'),
                                                'initials': ev.get('user'),
                                                'job_id': ev.get('stockid') or ev.get('job_id'),
                                                'manufacturer': ev.get('manufacturer'),
                                                'model': ev.get('model'),
                                                'serial': ev.get('serial') or ev.get('stockid'),
                                                'blancco_status': ev.get('blancco_status') or ev.get('status')
                                            }
                                            # avoid duplicates
                                            if not any((s.get('type') == 'blancco' and str(s.get('serial')) == str(blobj.get('serial'))) for s in target_ev.get('sources', [])):
                                                target_ev['sources'].append(blobj)
                                                target_ev['is_blancco_record'] = True
                                        # mark this blancco event for removal
                                        to_remove_idxs.append(idx)
                            except Exception:
                                continue
    
                        # remove in reverse order to keep indices valid
                        for ridx in sorted(set(to_remove_idxs), reverse=True):
                            try:
                                del results['timeline'][ridx]
                            except Exception:
                                continue
                        if to_remove_idxs:
                            try:
                                logging.info("[device_lookup] removed %d duplicate ITAD_asset_info_blancco events for job=%s serial=%s stock=%s", len(to_remove_idxs), job_id, system_serial, stock_id)
                            except Exception:
                                pass
                    except Exception:
                        pass
                # Additionally, if a spreadsheet-style erasure table exists (imported manually),
                # query it by the same candidate serials and attach those rows as provenance.
                try:
                    sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ('erasure_spreadsheet',))
                    if sqlite_cursor.fetchone():
                        sqlite_cursor.execute(f"SELECT ts, initials, manufacturer, model, serial, job_id, drive_size FROM erasure_spreadsheet WHERE serial IN ({placeholders}) OR job_id IN ({placeholders}) ORDER BY ts ASC", params * 2)
                        for r in sqlite_cursor.fetchall():
                            try:
                                ets, einits, emfg, emod, eserial, ejob, edrive = r
                            except Exception:
                                continue
                            prov = {
                                'type': 'erasure_sheet',
                                'source': 'erasure_spreadsheet',
                                'ts': ets,
                                'initials': einits,
                                'job_id': ejob,
                                'manufacturer': emfg,
                                'model': emod,
                                'serial': eserial,
                                'drive_size': edrive,
                            }
                            # Attach as provenance-only event (will be merged if timestamps align)
                            results.setdefault('found_in', [])
                            if 'erasure_spreadsheet' not in results['found_in']:
                                results['found_in'].append('erasure_spreadsheet')
                            results['timeline'].append({
                                'timestamp': ets,
                                'stage': 'Erasure (spreadsheet)',
                                'user': einits,
                                'location': None,
                                'source': 'erasure_spreadsheet',
                                'manufacturer': emfg,
                                'model': emod,
                                'system_serial': eserial,
                                'job_id': ejob,
                                'drive_size': edrive,
                                'is_blancco_record': True,
                                'sources': [prov],
                            })
                            try:
                                logging.info("[device_lookup] attached erasure_spreadsheet prov job=%s initials=%s stock=%s", ejob, einits, stock_id)
                            except Exception:
                                pass
                except Exception:
                    pass
                sqlite_cursor.close()
                sqlite_conn.close()
            except Exception as e:
                print(f"SQLite lookup error: {e}")
    
            # 7b. Enrich timeline with device history from QA export (broad range, best-effort)
            try:
                from datetime import date, timedelta
                # request a history window limited by audit_days to avoid fetching huge datasets
                start = date.today() - timedelta(days=audit_days)
                end = date.today()
                try:
                    history = qa_export.get_device_history_range(start, end)
                except Exception:
                    history = []
                # Debug: report how many history rows we received from qa_export
                try:
                    hist_len = len(history) if isinstance(history, (list, tuple)) else 0
                except Exception:
                    hist_len = 0
                logging.info("[device_lookup] qa_export.get_device_history_range returned %d rows for %s", hist_len, stock_id)
    
                for h in history:
                    try:
                        # Normalize identifiers for flexible matching
                        h_stock = str(h.get('stockid') or '').strip()
                        h_serial = str(h.get('serial') or '').strip()
                        if not h_stock and not h_serial:
                            continue
    
                        norm_req = str(stock_id or '').strip().lower()
                        match = False
                        if h_stock and h_stock.strip().lower() == norm_req:
                            match = True
                        if h_serial and h_serial.strip().lower() == norm_req:
                            match = True
                        # Allow substring matches to catch slight formatting differences
                        if not match:
                            if h_stock and norm_req and norm_req in h_stock.lower():
                                match = True
                            if h_serial and norm_req and norm_req in h_serial.lower():
                                match = True
                        if not match:
                            continue
    
                        # Surface full history fields (manufacturer/model/pallet/device_type)
                        results.setdefault("found_in", [])
                        if "qa_export.history" not in results.get("found_in", []):
                            results["found_in"].append("qa_export.history")
    
                        ev = {
                            "timestamp": h.get('timestamp'),
                            "stage": h.get('stage') or 'History',
                            "user": h.get('user'),
                            "location": h.get('location'),
                            "source": h.get('source') or 'qa_export.history',
                            "stockid": h_stock or None,
                            "serial": h_serial or None,
                            "manufacturer": h.get('manufacturer'),
                            "model": h.get('model'),
                            "device_type": h.get('device_type'),
                            "pallet_id": h.get('pallet_id'),
                            "pallet_destination": h.get('pallet_destination'),
                            "pallet_location": h.get('pallet_location'),
                            "details": json.dumps({k: v for k, v in h.items() if k in ('drive_size', 'drive_type', 'drive_count')}) if h else None,
                        }
    
                        results["timeline"].append(ev)
    
                        # If this history row includes a pallet assignment, add a dedicated Pallet event
                        try:
                            pid = ev.get('pallet_id')
                            if pid:
                                results["timeline"].append({
                                    "timestamp": h.get('timestamp'),
                                    "stage": f"Pallet {pid}",
                                    "user": h.get('user'),
                                    "location": ev.get('pallet_location'),
                                    "source": "qa_export.pallet",
                                    "pallet_id": pid,
                                    "pallet_destination": ev.get('pallet_destination'),
                                    "pallet_location": ev.get('pallet_location'),
                                })
                        except Exception:
                            pass
    
                    except Exception:
                        continue
            except Exception:
                pass
    
            # 7c. Include admin action history tied to erasures rows (undo/fix-initials etc.)
            try:
                import sqlite3 as _sqlite
                sconn = _sqlite.connect(db.DB_PATH)
                scur = sconn.cursor()
                scur.execute("SELECT rowid FROM erasures WHERE system_serial = ? OR disk_serial = ? OR job_id = ?", (stock_id, stock_id, stock_id))
                affected_rowids = [r[0] for r in scur.fetchall() if r and r[0]]
                if affected_rowids:
                    placeholders = ','.join(['?'] * len(affected_rowids))
                    q = f"SELECT a.created_at, a.action, a.from_initials, a.to_initials, ar.rowid FROM admin_actions a JOIN admin_action_rows ar ON a.id = ar.action_id WHERE ar.rowid IN ({placeholders}) ORDER BY a.created_at ASC"
                    scur.execute(q, affected_rowids)
                    for created_at, action, from_i, to_i, rowid in scur.fetchall():
                        results.setdefault("found_in", []).append("admin_actions") if "admin_actions" not in results.get("found_in", []) else None
                        results["timeline"].append({
                            "timestamp": created_at,
                            "stage": f"Admin: {action}",
                            "user": from_i or to_i,
                            "location": None,
                            "source": "admin_actions",
                            "details": f"rowid={rowid} from={from_i} to={to_i}",
                        })
                scur.close()
                sconn.close()
            except Exception:
                pass
    
            # 7d. Include manager confirmations history from confirmed_locations
            try:
                # Prefer the background confirmed_locations read if available
                conf_rows = None
                try:
                    if 'conf_future' in locals() and conf_future:
                        single = conf_future.result(timeout=0.05)
                        if single:
                            # we only have the latest in the future; for history fall back
                            conf_rows = [ (single[2], single[0], single[1], None) ]
                except Exception:
                    conf_rows = None
    
                if conf_rows is None:
                    import sqlite3 as _sqlite2
                    sc = _sqlite2.connect(db.DB_PATH)
                    curc = sc.cursor()
                    curc.execute("SELECT ts, location, user, note FROM confirmed_locations WHERE stockid = ? ORDER BY ts ASC", (stock_id,))
                    conf_rows = curc.fetchall()
                    curc.close()
                    sc.close()
    
                for ts, loc, user, note in conf_rows:
                    results.setdefault("found_in", []).append("confirmed_locations") if "confirmed_locations" not in results.get("found_in", []) else None
                    results["timeline"].append({
                        "timestamp": ts,
                        "stage": "Manager Confirmation",
                        "user": user,
                        "location": loc,
                        "source": "confirmed_locations",
                        "details": note,
                    })
            except Exception:
                pass
    
            # 7e. Hypothesis-derived events intentionally omitted from timeline
            # Reason: hypotheses are represented separately in `results.hypotheses` and
            # including them here caused duplicate timestamps (same occurrence shown
            # twice). We keep hypotheses in the hypotheses list but do not append them
            # as separate timeline events to avoid duplication.
            
            # De-dupe timeline events that are identical across sources/rows
            deduped_timeline = []
            seen_events = set()
            for event in results["timeline"]:
                key = (
                    event.get("timestamp"),
                    event.get("stage"),
                    event.get("user"),
                    event.get("location"),
                    event.get("source"),
                    event.get("details"),
                )
                if key in seen_events:
                    continue
                seen_events.add(key)
                deduped_timeline.append(event)
    
            # Sort timeline most-recent-first (newest at the top)
            deduped_timeline.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
            results["timeline"] = deduped_timeline
    
            # Debug: report final timeline size and a small sample for inspection
            try:
                logging.info("[device_lookup] timeline events after dedupe/sort: %d for %s", len(deduped_timeline), stock_id)
                for ev in deduped_timeline[:6]:
                    logging.info("[device_lookup] sample event: source=%s stage=%s ts=%s loc=%s", ev.get('source'), ev.get('stage'), ev.get('timestamp'), ev.get('location'))
            except Exception:
                pass
    
            # Backfill missing metadata on timeline events (pallet/destination/manufacturer/model)
            try:
                pallet_info = results.get('pallet_info') or {}
                for ev in results.get('timeline', []):
                    try:
                        if not ev.get('pallet_id') and pallet_info.get('pallet_id'):
                            ev['pallet_id'] = pallet_info.get('pallet_id')
                        if not ev.get('pallet_destination') and pallet_info.get('destination'):
                            ev['pallet_destination'] = pallet_info.get('destination')
                        if not ev.get('pallet_location') and pallet_info.get('location'):
                            ev['pallet_location'] = pallet_info.get('location')
                        # Fill manufacturer/model from asset_info when missing
                        asset_info = results.get('asset_info') or {}
                        if not ev.get('manufacturer') and asset_info.get('manufacturer'):
                            ev['manufacturer'] = asset_info.get('manufacturer')
                        if not ev.get('model') and asset_info.get('model'):
                            ev['model'] = asset_info.get('model')
                        # Normalize timestamp strings where possible
                        if ev.get('timestamp'):
                            try:
                                # keep as string but try to ensure ISO-like form
                                _t = ev.get('timestamp')
                                if isinstance(_t, (int, float)):
                                    # epoch -> iso
                                    from datetime import datetime as _dt
                                    ev['timestamp'] = _dt.utcfromtimestamp(float(_t)).isoformat()
                            except Exception:
                                pass
                    except Exception:
                        continue
            except Exception:
                pass
    
            # Add likely-location hypotheses (top N) from DB heuristics
            try:
                hypotheses = qa_export.get_device_location_hypotheses(stock_id, top_n=3)
                results["hypotheses"] = hypotheses or []
            except Exception as e:
                # Hypothesis generation is optional; log exception for debugging and return empty list
                logging.exception("Hypothesis generation failed for %s: %s", stock_id, e)
                results["hypotheses"] = []
    
            # If we know the last user (from QA/audit) and there's no pallet assignment,
            # surface a QA-confirmed hypothesis indicating the device was QA'd by that
            # user and is likely awaiting Sorting. This makes it easy to search for
            # devices handled by a technician and not yet assigned to a pallet.
            try:
                last_user = results.get('last_known_user')
                pallet_info = results.get('pallet_info') or {}
                asset_info = results.get('asset_info') or {}
                # Always surface a QA-confirmed hypothesis when we know the last user
                # (from audit_master), even if a pallet assignment exists. This keeps
                # the QA action visible in the UI between Sorting and later-stage
                # events like Erasure.
                if last_user:
                    # Find last seen timestamp for this user in the timeline
                    last_seen = None
                    for ev in reversed(results.get('timeline', [])):
                        try:
                            if ev.get('user') and str(ev.get('user')).lower() == str(last_user).lower():
                                last_seen = ev.get('timestamp') or last_seen
                                break
                        except Exception:
                            continue
    
                    qa_label = f"QA Data Bearing (by {last_user})"
                    qa_evidence = [{'source': 'audit_master', 'username': last_user}]
                    # Determine latest timeline timestamp so we can mark whether
                    # this QA hypothesis corresponds to the most-recent event.
                    latest_ts = None
                    try:
                        for tev in results.get('timeline', []) or []:
                            t = tev.get('timestamp')
                            if not t:
                                continue
                            try:
                                if isinstance(t, str):
                                    from datetime import datetime as _dt
                                    tdt = _dt.fromisoformat(t.replace('Z', '+00:00'))
                                else:
                                    tdt = t
                            except Exception:
                                continue
                            if not latest_ts or (tdt and tdt > latest_ts):
                                latest_ts = tdt
                    except Exception:
                        latest_ts = None
                    # prepend so it shows prominently; score 85 to be competitive but still
                    # allow true recency to reorder if other signals are fresher.
                    # mark `is_most_recent` True when the user's last_seen equals the
                    # most recent timeline timestamp (within 60 seconds) so the UI
                    # can highlight this as the freshest signal.
                    is_most_recent_flag = False
                    try:
                        if last_seen and latest_ts:
                            try:
                                from datetime import datetime as _dt
                                if isinstance(last_seen, str):
                                    last_dt = _dt.fromisoformat(last_seen.replace('Z', '+00:00'))
                                else:
                                    last_dt = last_seen
                                if last_dt and abs((latest_ts - last_dt).total_seconds()) <= 60:
                                    is_most_recent_flag = True
                            except Exception:
                                is_most_recent_flag = False
                    except Exception:
                        is_most_recent_flag = False
    
                    qa_hyp = {
                        'location': qa_label,
                        # Compute QA score relative to existing top hypothesis so
                        # QA does not accidentally outrank a more-recent Sorting
                        # candidate. If a top hypothesis exists and its score is
                        # lower than the configured QA_CONFIRMED_SCORE, give QA a
                        # slightly lower score so it appears second.
                        'score': None,
                        'raw_score': None,
                        'evidence': qa_evidence,
                        'last_seen': last_seen,
                        'type': 'stage',
                        'explanation': f"Device was recorded in audit_master by {last_user} and likely passed QA.",
                        'ai_explanation': f"Recorded as QA Data Bearing by {last_user}; likely awaiting Sorting.",
                        'rank': 1,
                        'is_qa_confirmed': True,
                        'awaiting_sorting': True,
                        'is_most_recent': is_most_recent_flag,
                    }
                    # Ensure the QA-confirmed hypothesis is present and prominent.
                    # Even when a pallet assignment exists, operators want to see
                    # the QA confirmation alongside pallet/inferred candidates.
                    results.setdefault('hypotheses', [])
                    # avoid duplicate QA hypotheses
                    found_qa = False
                    try:
                        for h in results.get('hypotheses', []):
                            try:
                                if h.get('is_qa_confirmed') or (isinstance(h.get('location'), str) and h.get('location').lower().startswith('qa data bearing')):
                                    found_qa = True
                                    break
                            except Exception:
                                continue
                    except Exception:
                        found_qa = False
                    if not found_qa:
                        # Determine an appropriate numeric score for the QA
                        # hypothesis so ordering is driven by numeric sort when
                        # possible. Prefer to keep QA slightly below the current
                        # top hypothesis if that hypothesis exists.
                        try:
                            top_score = None
                            if results.get('hypotheses'):
                                top_score = max((int(h.get('score') or 0) for h in results.get('hypotheses')))
                        except Exception:
                            top_score = None
                        try:
                            if top_score is not None and top_score < int(QA_CONFIRMED_SCORE):
                                qa_score = max(0, int(top_score) - 1)
                            else:
                                qa_score = int(QA_CONFIRMED_SCORE)
                        except Exception:
                            qa_score = int(QA_CONFIRMED_SCORE)
                        qa_hyp['score'] = qa_score
                        qa_hyp['raw_score'] = float(qa_score)
    
                        # Insert QA just after the top hypothesis when possible.
                        if results.get('hypotheses') and len(results.get('hypotheses')) >= 1:
                            try:
                                results['hypotheses'].insert(1, qa_hyp)
                            except Exception:
                                results['hypotheses'].insert(0, qa_hyp)
                        else:
                            results['hypotheses'].insert(0, qa_hyp)
            except Exception:
                pass
    
            # Build a compact smart advisory from the top hypothesis (if available)
            try:
                smart_advisory = None
                # --- Enrich hypotheses with any erasure provenance found in the timeline ---
                try:
                    if results.get('hypotheses') and results.get('timeline'):
                        # Collect erasure provenance objects from timeline
                        erasures_found = []
                        for ev in results.get('timeline', []):
                            for s in ev.get('sources', []) or []:
                                try:
                                    if s and (s.get('type') == 'erasure' or (s.get('source') and 'local_erasures' in str(s.get('source')))):
                                        erasures_found.append(s)
                                except Exception:
                                    continue
    
                        # Also collect Blancco timeline events (MariaDB copies) as provenance
                        blancco_found = []
                        for ev in results.get('timeline', []):
                            try:
                                src = (ev.get('source') or '')
                                if ev.get('is_blancco_record') or ('blancco' in str(src).lower()):
                                    blancco_found.append({
                                        'type': 'blancco',
                                        'source': src,
                                        'ts': ev.get('timestamp'),
                                        'initials': ev.get('user'),
                                        'blancco_status': ev.get('blancco_status') or ev.get('status'),
                                        'manufacturer': ev.get('manufacturer'),
                                        'model': ev.get('model'),
                                        'serial': ev.get('serial') or ev.get('stockid'),
                                    })
                            except Exception:
                                continue
    
                        if erasures_found or blancco_found:
                            for h in results.get('hypotheses', []):
                                try:
                                    h.setdefault('evidence', h.get('evidence') or [])
                                    # attach shallow copies (avoid mutating DB rows)
                                    for e in erasures_found:
                                        # Build a concise evidence object for UI
                                        ev_obj = {
                                            'source': 'local_erasures',
                                            'type': 'erasure',
                                            'initials': e.get('initials'),
                                            'job_id': e.get('job_id'),
                                            'ts': e.get('ts'),
                                            'manufacturer': e.get('manufacturer'),
                                            'model': e.get('model'),
                                            'disk_serial': e.get('disk_serial'),
                                            'drive_size': e.get('drive_size')
                                        }
                                        # Avoid duplicate evidence entries
                                        if not any((ev.get('job_id') and ev.get('job_id') == ev_obj['job_id']) for ev in h['evidence'] if isinstance(ev, dict)):
                                            h['evidence'].append(ev_obj)
                                    # Add Blancco evidence too
                                    for b in blancco_found:
                                        bobj = {
                                            'source': 'ITAD_asset_info_blancco',
                                            'type': 'blancco',
                                            'initials': b.get('initials'),
                                            'ts': b.get('ts'),
                                            'status': b.get('blancco_status'),
                                            'manufacturer': b.get('manufacturer'),
                                            'model': b.get('model'),
                                            'serial': b.get('serial')
                                        }
                                        if not any((ev.get('type') == 'blancco' and ev.get('serial') == bobj.get('serial')) for ev in h['evidence'] if isinstance(ev, dict)):
                                            h['evidence'].append(bobj)
                                    # Mark hypothesis as having Blancco evidence (UI can show badge)
                                    if blancco_found:
                                        h['is_blancco'] = True
                                        if 'blancco' not in h:
                                            h['blancco'] = blancco_found[0]
                                except Exception:
                                    continue
                        # If we found erasure provenance, also add an explicit
                        # 'Data Erasure' hypothesis (lower score than QA) so the UI
                        # lists both QA confirmation and Data Erasure as top items.
                        try:
                            if erasures_found:
                                # prefer the most-recent erasure provenance
                                e = erasures_found[-1]
                                er_initials = e.get('initials') or 'Unknown'
                                er_ts = e.get('ts')
                                er_evidence = [{
                                    'source': 'local_erasures',
                                    'type': 'erasure',
                                    'initials': e.get('initials'),
                                    'job_id': e.get('job_id'),
                                    'ts': e.get('ts'),
                                    'manufacturer': e.get('manufacturer'),
                                    'model': e.get('model'),
                                    'disk_serial': e.get('disk_serial'),
                                    'drive_size': e.get('drive_size')
                                }]
                                er_hyp = {
                                    'location': f"Data Erasure (by {er_initials})",
                                    'score': max(0, int(QA_CONFIRMED_SCORE) - 10),
                                    'raw_score': float(max(0, int(QA_CONFIRMED_SCORE) - 10)),
                                    'evidence': er_evidence,
                                    'last_seen': er_ts,
                                    'type': 'stage',
                                    'explanation': f"Device erasure recorded by {er_initials}.",
                                    'ai_explanation': f"Erasure recorded by {er_initials} on {er_ts}.",
                                    'rank': 2,
                                    'is_blancco': True,
                                }
                                # Ensure hypotheses list exists and append if not duplicate
                                results.setdefault('hypotheses', [])
                                # avoid adding duplicate erasure hyp
                                if not any(h.get('location', '').lower().startswith('data erasure') for h in results['hypotheses']):
                                    results['hypotheses'].append(er_hyp)
                        except Exception:
                            pass
                except Exception:
                    pass
                if results.get("hypotheses"):
                    top = results["hypotheses"][0]
                    # confidence: use normalized score if present, else raw_score
                    try:
                        conf_pct = int(top.get('score', top.get('raw_score', 0)))
                    except Exception:
                        conf_pct = int(top.get('raw_score', 0) or 0)
    
                    # last activity
                    last_act = top.get('last_seen')
                    last_dt = None
                    try:
                        if last_act:
                            # last_seen might already be iso string or datetime
                            if isinstance(last_act, str):
                                from datetime import datetime as _dt
                                try:
                                    last_dt = _dt.fromisoformat(last_act.replace('Z', '+00:00'))
                                except Exception:
                                    last_dt = None
                            else:
                                last_dt = last_act
                    except Exception:
                        last_dt = None
    
                    hours_since = None
                    from datetime import datetime as _dt
                    try:
                        if last_dt:
                            hours_since = round((datetime.now(last_dt.tzinfo) - last_dt).total_seconds() / 3600.0, 1)
                    except Exception:
                        hours_since = None
    
                    # simple predicted next step based on candidate type or keywords
                    predicted_next = None
                    locname = (top.get('location') or '').lower()
                    if 'erasure' in locname or 'blancco' in locname:
                        predicted_next = 'QA Review'
                    elif 'pallet' in locname:
                        predicted_next = 'Pallet Move / Shipping'
                    elif 'roller' in locname or 'ia' in locname:
                        predicted_next = 'Erasure'
                    else:
                        predicted_next = results.get('insights', {}).get('predicted_next_step') or None
    
                    # reason: use first sentence of ai_explanation if available
                    reason = None
                    try:
                        aiex = top.get('ai_explanation') or top.get('explanation') or ''
                        if aiex:
                            reason = str(aiex).split('.')[:1][0].strip()
                    except Exception:
                        reason = None
    
                    recommended = None
                    # derive recommended action from ai_explanation trailing phrases if possible
                    try:
                        if aiex and 'recommended action' in aiex.lower():
                            rec = aiex.lower().split('recommended action:')[-1].strip()
                            recommended = rec[0:200].strip()
                    except Exception:
                        recommended = None
    
                    smart_advisory = {
                        'predicted_next': predicted_next,
                        'confidence_pct': conf_pct,
                        'last_activity': last_act if isinstance(last_act, str) else (last_dt.isoformat() if last_dt else None),
                        'time_since_hours': hours_since,
                        'reason': reason,
                        'recommended_action': recommended,
                        'source_candidate': top.get('location'),
                    }
                    # also attach advisory to the hypothesis object for UI convenience
                    results['hypotheses'][0]['smart_advisory'] = smart_advisory
                results['smart_advisory'] = smart_advisory
                # Provide a short timeline advisory note (human-friendly) derived from top hypothesis
                try:
                    if results.get('hypotheses') and results['hypotheses'][0].get('ai_explanation'):
                        note = results['hypotheses'][0].get('ai_explanation')
                        # keep it short (first two sentences)
                        sn = '.'.join(str(note).split('.')[:2]).strip()
                        results['timeline_advisory_note'] = sn
                    else:
                        results['timeline_advisory_note'] = None
                except Exception:
                    results['timeline_advisory_note'] = None
            except Exception:
                results['smart_advisory'] = None
    
            # Build smart insights (simple prediction + risk signals)
            from datetime import datetime
    
            def parse_timestamp(value):
                if not value:
                    return None
                if isinstance(value, datetime):
                    return value
                raw = str(value).strip()
                if not raw:
                    return None
                try:
                    return datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except Exception:
                    pass
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(raw, fmt)
                    except Exception:
                        continue
                return None
    
            last_activity_dt = None
            last_activity_label = None
            for event in reversed(results["timeline"]):
                ts = parse_timestamp(event.get("timestamp"))
                if ts:
                    last_activity_dt = ts
                    last_activity_label = event.get("timestamp")
                    break
            if not last_activity_dt and results.get("asset_info"):
                asset_last = parse_timestamp(results["asset_info"].get("last_update"))
                if asset_last:
                    last_activity_dt = asset_last
                    last_activity_label = results["asset_info"].get("last_update")
    
            hours_since = None
            if last_activity_dt:
                try:
                    delta = datetime.now(last_activity_dt.tzinfo) - last_activity_dt
                    hours_since = round(delta.total_seconds() / 3600, 1)
                except Exception:
                    hours_since = None
    
            asset_info = results.get("asset_info") or {}
            stage_next = asset_info.get("stage_next")
            stage_current = asset_info.get("stage_current")
            pallet_id = (results.get("pallet_info") or {}).get("pallet_id")
            has_qa = any((evt.get("stage") or "").lower().startswith("qa") for evt in results["timeline"])
            has_erasure = any("erasure" in (evt.get("stage") or "").lower() for evt in results["timeline"])
            last_stage = None
            if results["timeline"]:
                last_stage = results["timeline"][-1].get("stage")
    
            predicted_next = None
            confidence = 0.35
            if stage_next:
                predicted_next = stage_next
                confidence = 0.78
            elif last_stage:
                stage_lower = last_stage.lower()
                if "erasure" in stage_lower:
                    predicted_next = "QA Review"
                    confidence = 0.6
                elif stage_lower.startswith("qa"):
                    predicted_next = "Pallet Assignment" if not pallet_id else "Pallet Move / Shipping"
                    confidence = 0.65
                elif "sorting" in stage_lower:
                    predicted_next = "QA Review"
                    confidence = 0.55
            elif stage_current:
                predicted_next = "Continue workflow"
                confidence = 0.4
    
            signals = []
            recommendations = []
            risk_score = 10
            risk_level = "low"
    
            if hours_since is not None and hours_since >= 48:
                signals.append(f"No activity for {hours_since} hours")
                recommendations.append("Investigate current location and assign owner")
                risk_score += 35
            if has_qa and not pallet_id:
                signals.append("QA complete but no pallet assignment")
                recommendations.append("Assign pallet or confirm destination")
                risk_score += 30
            if asset_info.get("quarantine"):
                signals.append("Device is in quarantine")
                if asset_info.get("quarantine_reason"):
                    signals.append(f"Quarantine reason: {asset_info.get('quarantine_reason')}")
                recommendations.append("Resolve quarantine before next stage")
                risk_score += 40
    
            roller_location = (asset_info.get("roller_location") or "").strip()
            if roller_location and "roller" in roller_location.lower():
                de_complete = str(asset_info.get("de_complete") or "").lower() in ("yes", "true", "1")
                if de_complete or has_erasure:
                    signals.append(f"Roller status: {roller_location} (erased, waiting QA)")
                    recommendations.append("Prioritize QA scan to clear roller queue")
                    risk_score += 15
                else:
                    signals.append(f"Roller status: {roller_location} (waiting erasure)")
                    recommendations.append("Route to erasure queue or verify intake")
                    risk_score += 20
    
            if risk_score >= 70:
                risk_level = "high"
            elif risk_score >= 35:
                risk_level = "medium"
    
            results["insights"] = {
                "predicted_next_step": predicted_next,
                "confidence": confidence,
                "risk_score": min(risk_score, 100),
                "risk_level": risk_level,
                "last_activity": last_activity_label,
                "hours_since_activity": hours_since,
                "signals": signals,
                "recommendations": recommendations,
            }
    
            # Destination-specific bottleneck snapshot removed from device lookup
    
            # Summary
            # Merge near-duplicate timeline events (events within a short window)
            try:
                from datetime import datetime as _dt
    
                MERGE_WINDOW = int(os.getenv('MERGE_TIMELINE_WINDOW_SECONDS', '60'))
    
                def _parse_ts(ts):
                    if not ts:
                        return None
                    try:
                        if isinstance(ts, str):
                            # Handle ISO and common SQL formats
                            try:
                                return _dt.fromisoformat(ts.replace('Z', '+00:00'))
                            except Exception:
                                pass
                            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                                try:
                                    return _dt.strptime(ts, fmt)
                                except Exception:
                                    continue
                        elif hasattr(ts, 'timetuple'):
                            return ts
                    except Exception:
                        return None
                    return None
    
                # Build a list of (dt, event) and sort by dt desc, keep None timestamps at end
                evs = results.get('timeline', []) or []
                evs_with_dt = []
                evs_none = []
                for e in evs:
                    try:
                        d = _parse_ts(e.get('timestamp'))
                    except Exception:
                        d = None
                    if d:
                        evs_with_dt.append((d, e))
                    else:
                        evs_none.append((None, e))
    
                evs_with_dt.sort(key=lambda x: x[0], reverse=True)
    
                merged = []
                i = 0
                while i < len(evs_with_dt):
                    base_dt, base_ev = evs_with_dt[i]
                    group = [(base_dt, base_ev)]
                    j = i + 1
                    while j < len(evs_with_dt):
                        nxt_dt, nxt_ev = evs_with_dt[j]
                        try:
                            diff = abs((base_dt - nxt_dt).total_seconds())
                        except Exception:
                            diff = None
                        if diff is not None and diff <= MERGE_WINDOW:
                            group.append((nxt_dt, nxt_ev))
                            # extend base_dt to the most recent in group for subsequent comparisons
                            if nxt_dt and nxt_dt > base_dt:
                                base_dt = nxt_dt
                            j += 1
                        else:
                            break
                    # Produce merged event: prefer the event with the latest timestamp as primary
                    primary = max(group, key=lambda x: x[0] or _dt.min)[1]
                    merged_event = dict(primary)
                    # attach provenance of merged events
                    merged_event['merged'] = True if len(group) > 1 else False
                    merged_event['merged_from'] = []
                    for d, ev in group:
                        merged_event['merged_from'].append({
                            'timestamp': ev.get('timestamp'),
                            'stage': ev.get('stage'),
                            'source': ev.get('source'),
                            'user': ev.get('user')
                        })
                    merged.append(merged_event)
                    i = j
    
                # Append events with no timestamps after the merged ones (preserve order)
                for _, e in evs_none:
                    merged.append(e)
    
                results['timeline'] = merged
            except Exception:
                # If merge fails for any reason, fall back to raw timeline
                pass
    
            results["total_events"] = len(results["timeline"])
            results["data_sources_checked"] = [
                "ITAD_asset_info", "Stockbypallet", "ITAD_pallet", 
                "ITAD_QA_App", "audit_master", "ITAD_asset_info_blancco", "local_erasures"
            ]
            
            return results
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"Device lookup error: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))
    
    
    _SUMMARY_TTL = float(os.getenv("SUMMARY_TTL", "60"))
    # Short-lived cache for device summary
    _summary_cache = ttl_cache_cls(maxsize=int(os.getenv("SUMMARY_MAXSIZE", "512")), ttl=_SUMMARY_TTL)
    
    @router.get("/api/device-lookup/{stock_id}/summary")
    async def device_lookup_summary(stock_id: str, request: Request):
        """Return a lightweight top suggestion for a device. Cached for short TTL."""
        require_manager_or_admin(request)
        cached = _summary_cache.get(stock_id)
        if cached is not None:
            return {"stock_id": stock_id, "summary": cached, "cached": True}
        try:
            import device_lookup as dl
            # request a single top hypothesis; device_lookup's SIMPLE_MODE will keep this light
            hyps = dl.get_device_location_hypotheses(stock_id, top_n=1)
            top = hyps[0] if hyps else None
            _summary_cache.set(stock_id, top)
            return {"stock_id": stock_id, "summary": top, "cached": False}
        except Exception as e:
            return {"stock_id": stock_id, "summary": None, "error": str(e)}
    
    
    @router.post("/api/device-lookup/{stock_id}/confirm")
    async def confirm_device_location(stock_id: str, request: Request):
        """Record a user-confirmed device location to improve future hypotheses (manager/admin only)."""
        require_manager_or_admin(request)
        payload = await request.json()
        location = payload.get('location')
        note = payload.get('note')
        role = get_role_from_request(request) or 'manager'
        if not location:
            raise HTTPException(status_code=400, detail='location required')
    
        import sqlite3
        try:
            conn = sqlite3.connect(db.DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS confirmed_locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stockid TEXT,
                    location TEXT,
                    user TEXT,
                    note TEXT,
                    ts TEXT
                )
            """)
            ts = __import__('datetime').datetime.utcnow().isoformat()
            cur.execute("INSERT INTO confirmed_locations (stockid, location, user, note, ts) VALUES (?, ?, ?, ?, ?)",
                        (stock_id, location, role, note, ts))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Confirm location error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
        return { 'ok': True, 'stockid': stock_id, 'location': location, 'ts': ts }
    
    
    

    return router
