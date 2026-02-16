from datetime import datetime, date, timedelta
from typing import List, Dict
import sqlite3
import re

# Lazy imports to avoid circular module import problems; functions will import
# database helpers from `qa_export` at runtime when needed.

# --------- Unpalleted devices ----------

def get_unpalleted_devices(start_date: date = None, end_date: date = None) -> List[Dict[str, object]]:
    from qa_export import get_mariadb_connection

    conn = get_mariadb_connection()
    if not conn:
        return []
    
    devices = []
    try:
        cursor = conn.cursor()
        date_clause = ""
        params = []
        if start_date and end_date:
            date_clause = "AND a.received_date >= %s AND a.received_date <= %s"
            params = [start_date.isoformat(), end_date.isoformat()]

        cursor.execute(f"""
            SELECT 
                src.stockid,
                a.serialnumber,
                a.manufacturer,
                a.description,
                a.condition,
                a.received_date,
                a.stage_current,
                a.location,
                a.roller_location,
                a.last_update,
                a.de_complete,
                a.de_completed_by,
                a.de_completed_date,
                q.added_date as qa_date,
                q.username as qa_user,
                q.scanned_location as qa_location
            FROM (
                SELECT stockid FROM ITAD_asset_info
                UNION
                SELECT stockid FROM ITAD_asset_info_blancco
                UNION
                SELECT stockid FROM Stockbypallet
                UNION
                SELECT sales_order AS stockid FROM audit_master WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload') AND sales_order IS NOT NULL
            ) src
            LEFT JOIN ITAD_asset_info a ON a.stockid = src.stockid
            LEFT JOIN (
                SELECT stockid, MAX(added_date) AS last_added
                FROM ITAD_QA_App
                GROUP BY stockid
            ) last_q ON last_q.stockid = a.stockid
            LEFT JOIN ITAD_QA_App q ON q.stockid = last_q.stockid AND q.added_date = last_q.last_added
            LEFT JOIN Stockbypallet sb ON sb.stockid = src.stockid
            LEFT JOIN (
                SELECT stockid, COUNT(*) AS blancco_count
                FROM ITAD_asset_info_blancco
                GROUP BY stockid
            ) b ON b.stockid = src.stockid
            WHERE (
                a.stockid IS NULL
                OR (
                    (a.pallet_id IS NULL OR a.pallet_id = '' OR a.palletID IS NULL OR a.palletID = '' OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                    AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
                )
            )
              {date_clause}
              AND (
                  LOWER(COALESCE(a.de_complete, '')) IN ('yes','true','1')
                  OR LOWER(COALESCE(sb.de_complete, '')) IN ('yes','true','1')
                  OR COALESCE(b.blancco_count, 0) > 0
                  OR EXISTS (
                      SELECT 1 FROM audit_master am
                      WHERE am.sales_order = src.stockid
                        AND am.audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload')
                  )
                  OR (a.last_update IS NOT NULL AND a.last_update >= DATE_SUB(NOW(), INTERVAL 30 DAY))
              )
            ORDER BY COALESCE(a.received_date, '1900-01-01') DESC
            LIMIT 10000
        """, params)

        for row in cursor.fetchall():
            devices.append({
                "stockid": row[0],
                "serial": row[1],
                "manufacturer": row[2],
                "model": row[3],
                "condition": row[4],
                "received_date": str(row[5]) if row[5] else None,
                "stage_current": row[6],
                "location": row[7],
                "roller_location": row[8],
                "last_update": str(row[9]) if row[9] else None,
                "de_complete": row[10],
                "de_completed_by": row[11],
                "de_completed_date": str(row[12]) if row[12] else None,
                "qa_date": str(row[13]) if row[13] else None,
                "qa_user": row[14],
                "qa_location": row[15],
            })

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[Manager Bottleneck] Error fetching unpalleted devices: {e}")
        if conn:
            conn.close()
    
    return devices


def get_unpalleted_devices_recent(days_threshold: int = 7) -> List[Dict[str, object]]:
    from qa_export import get_mariadb_connection

    conn = get_mariadb_connection()
    if not conn:
        return []

    devices = []
    days_threshold = max(1, min(int(days_threshold or 7), 90))

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                a.stockid,
                a.serialnumber,
                a.manufacturer,
                a.description,
                a.condition,
                a.received_date,
                a.stage_current,
                a.location,
                a.roller_location,
                a.last_update,
                a.de_complete,
                a.de_completed_by,
                a.de_completed_date,
                q.added_date as qa_date,
                q.username as qa_user,
                q.scanned_location as qa_location
            FROM ITAD_asset_info a
            LEFT JOIN (
                SELECT stockid, MAX(added_date) AS last_added
                FROM ITAD_QA_App
                GROUP BY stockid
            ) last_q ON last_q.stockid = a.stockid
            LEFT JOIN ITAD_QA_App q ON q.stockid = last_q.stockid AND q.added_date = last_q.last_added
            WHERE (a.pallet_id IS NULL OR a.pallet_id = '' OR a.palletID IS NULL OR a.palletID = '' OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
              AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
              AND a.last_update IS NOT NULL
              AND a.last_update >= DATE_SUB(NOW(), INTERVAL %s DAY)
            ORDER BY a.last_update DESC
            LIMIT 2000
        """, (days_threshold,))

        for row in cursor.fetchall():
            devices.append({
                "stockid": row[0],
                "serial": row[1],
                "manufacturer": row[2],
                "model": row[3],
                "condition": row[4],
                "received_date": str(row[5]) if row[5] else None,
                "stage_current": row[6],
                "location": row[7],
                "roller_location": row[8],
                "last_update": str(row[9]) if row[9] else None,
                "de_complete": row[10],
                "de_completed_by": row[11],
                "de_completed_date": str(row[12]) if row[12] else None,
                "qa_date": str(row[13]) if row[13] else None,
                "qa_user": row[14],
                "qa_location": row[15],
            })

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[Manager Bottleneck] Error fetching recent unpalleted devices: {e}")
        if conn:
            conn.close()

    return devices


def get_awaiting_qa_counts_for_date(target_date: date) -> Dict[str, int]:
    from qa_export import _parse_timestamp, safe_read
    import database as db

    result = {"total_erasures": 0, "matched": 0, "awaiting_qa": 0}

    try:
        sqlite_conn = sqlite3.connect(db.DB_PATH)
        cur = sqlite_conn.cursor()
        cur.execute(
            """
            SELECT ts, system_serial, disk_serial, job_id
            FROM erasures
            WHERE date = ? AND event = 'success'
            ORDER BY ts ASC
            """,
            (target_date.isoformat(),)
        )
        rows = cur.fetchall()
        cur.close()
        sqlite_conn.close()

        if not rows:
            return result

        erasures = []
        for ts, system_serial, disk_serial, job_id in rows:
            serial_value = system_serial or disk_serial or job_id
            if not serial_value:
                erasures.append({"serial": None, "ts": _parse_timestamp(ts)})
            else:
                erasures.append({"serial": str(serial_value).strip(), "ts": _parse_timestamp(ts)})

        result["total_erasures"] = len(erasures)

        serials = [e["serial"] for e in erasures if e.get("serial")]
        stockid_map = {}
        if serials:
            unique_serials = list({s for s in serials if s})
            placeholders = ",".join(["%s"] * len(unique_serials))
            query = f"SELECT stockid, serial FROM ITAD_asset_info_blancco WHERE serial IN ({placeholders})"
            try:
                rows = safe_read(query, tuple(unique_serials))
                for stockid, serial in rows:
                    if serial:
                        stockid_map[str(serial)] = stockid
            except Exception:
                return result

        stockids = list({v for v in stockid_map.values() if v})
        qa_latest = {}
        audit_latest = {}
        if stockids:
            placeholders = ",".join(["%s"] * len(stockids))
            try:
                q_rows = safe_read(f"SELECT stockid, MAX(added_date) FROM ITAD_QA_App WHERE stockid IN ({placeholders}) GROUP BY stockid", tuple(stockids))
                for stockid, max_dt in q_rows:
                    qa_latest[str(stockid)] = max_dt
            except Exception:
                pass

            try:
                a_rows = safe_read(f"SELECT sales_order, MAX(date_time) FROM audit_master WHERE sales_order IN ({placeholders}) AND audit_type IN ('DEAPP_Submission','DEAPP_Submission_EditStock_Payload') GROUP BY sales_order", tuple(stockids))
                for sales_order, max_dt in a_rows:
                    audit_latest[str(sales_order)] = max_dt
            except Exception:
                pass

        matched = 0
        for e in erasures:
            er_ts = e.get("ts")
            serial = e.get("serial")
            if not serial:
                continue
            stockid = stockid_map.get(serial)
            if not stockid:
                continue
            latest = None
            qa_dt = qa_latest.get(str(stockid))
            aud_dt = audit_latest.get(str(stockid))
            if qa_dt and (not latest or qa_dt > latest):
                latest = qa_dt
            if aud_dt and (not latest or aud_dt > latest):
                latest = aud_dt
            if latest and er_ts and latest >= er_ts:
                matched += 1

        result["matched"] = matched
        result["awaiting_qa"] = max(0, result["total_erasures"] - matched)
        return result

    except Exception as e:
        print(f"[Manager Bottleneck] Error computing awaiting QA counts: {e}")
        return result


def get_unpalleted_summary(destination: str = None, days_threshold: int = 7) -> Dict[str, object]:
    from qa_export import get_mariadb_connection

    conn = get_mariadb_connection()
    if not conn:
        return {
            "total_unpalleted": 0,
            "destination_counts": {},
            "engineer_counts": {},
        }

    params = []
    destination_clause = ""
    if destination:
        destination_clause = "AND LOWER(a.`condition`) = %s"
        params.append(destination.strip().lower())

    days_threshold = max(1, min(int(days_threshold or 7), 90))
    recency_clause = "a.last_update IS NOT NULL AND a.last_update >= DATE_SUB(CURDATE(), INTERVAL 3 DAY)"

    base_from = """
        FROM (
            SELECT stockid FROM ITAD_asset_info
            UNION
            SELECT stockid FROM ITAD_asset_info_blancco
            UNION
            SELECT stockid FROM Stockbypallet
            UNION
            SELECT sales_order AS stockid FROM audit_master WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload') AND sales_order IS NOT NULL
        ) src
        LEFT JOIN ITAD_asset_info a ON a.stockid = src.stockid
        LEFT JOIN (
            SELECT stockid, MAX(added_date) AS last_added
            FROM ITAD_QA_App
            GROUP BY stockid
        ) last_q ON last_q.stockid = a.stockid
        LEFT JOIN ITAD_QA_App q
            ON q.stockid = last_q.stockid AND q.added_date = last_q.last_added
        LEFT JOIN Stockbypallet sb ON sb.stockid = src.stockid
        LEFT JOIN (
            SELECT stockid, COUNT(*) AS blancco_count
            FROM ITAD_asset_info_blancco
            GROUP BY stockid
        ) b ON b.stockid = src.stockid
    """

    base_where = f"""
        WHERE (
            a.stockid IS NULL  -- Include devices that only exist in secondary tables (blancco/audit)
            OR (
                (a.pallet_id IS NULL OR a.pallet_id = '' OR a.palletID IS NULL OR a.palletID = '' OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
            )
        )
          AND {recency_clause}
          AND (
              LOWER(COALESCE(a.de_complete, '')) IN ('yes','true','1')
              OR LOWER(COALESCE(sb.de_complete, '')) IN ('yes','true','1')
              OR COALESCE(b.blancco_count, 0) > 0
              OR EXISTS (
                  SELECT 1 FROM audit_master am
                  WHERE am.sales_order = src.stockid
                    AND am.audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload')
                    AND YEARWEEK(am.date_time, 1) = YEARWEEK(CURDATE(), 1)
              )
          )
          {destination_clause}
    """

    result = {
        "total_unpalleted": 0,
        "awaiting_erasure": 0,
        "awaiting_qa": 0,
        "awaiting_pallet": 0,
        "destination_counts": {},
        "engineer_counts": {},
    }

    try:
        cursor = conn.cursor()

        cursor.execute(
            f"""
            SELECT COUNT(DISTINCT src.stockid)
            {base_from}
            {base_where}
            """,
            params
        )
        row = cursor.fetchone()
        result["total_unpalleted"] = int(row[0]) if row and row[0] is not None else 0

        cursor.execute(
            f"""
            SELECT 
                COUNT(DISTINCT CASE WHEN a.description IS NOT NULL AND 
                                         (LOWER(COALESCE(a.de_complete, '')) NOT IN ('yes','true','1') AND 
                                          COALESCE(b.blancco_count, 0) = 0) THEN src.stockid END) as awaiting_erasure,
                COUNT(DISTINCT CASE WHEN (LOWER(COALESCE(a.de_complete, '')) IN ('yes','true','1') OR 
                                          COALESCE(b.blancco_count, 0) > 0) AND
                                         (SELECT MAX(q.added_date) FROM ITAD_QA_App q WHERE q.stockid = src.stockid) IS NULL THEN src.stockid END) as awaiting_qa,
                COUNT(DISTINCT CASE WHEN (SELECT MAX(q.added_date) FROM ITAD_QA_App q WHERE q.stockid = src.stockid) IS NOT NULL AND
                                         COALESCE(a.pallet_id, a.palletID, '') = '' THEN src.stockid END) as awaiting_pallet
            {base_from}
            {base_where}
            """,
            params
        )
        workflow_row = cursor.fetchone()
        if workflow_row:
            result["awaiting_erasure"] = int(workflow_row[0] or 0)
            result["awaiting_qa"] = int(workflow_row[1] or 0)
            result["awaiting_pallet"] = int(workflow_row[2] or 0)

        cursor.execute(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(a.`condition`), ''), 'Unknown') AS destination,
                COUNT(DISTINCT src.stockid) AS device_count
            {base_from}
            {base_where}
            GROUP BY destination
            """,
            params
        )
        for dest, count in cursor.fetchall():
            result["destination_counts"][dest] = int(count)

        cursor.execute(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(q.username), ''), 'Unassigned (no QA user recorded)') AS qa_user,
                COUNT(DISTINCT src.stockid) AS device_count
            {base_from}
            {base_where}
            GROUP BY qa_user
            """,
            params
        )
        for qa_user, count in cursor.fetchall():
            result["engineer_counts"][qa_user] = int(count)

    finally:
        conn.close()

    return result


def normalize_roller_name(roller_location: str) -> str:
    if not roller_location:
        return "Unknown Roller"
    name = roller_location.strip()
    if ':' in name:
        parts = name.split(':', 1)
        if len(parts) > 1 and 'roller' in parts[1].lower():
            name = parts[1].strip()
    return name


DATA_BEARING_TYPES = [
    'laptop', 'notebook', 'elitebook', 'probook', 'latitude', 'precision', 'xps', 'thinkpad', 'macbook', 'surface',
    'desktop', 'optiplex', 'prodesk', 'precision', 'thinkcentre', 'imac', 'mac mini', 'mac pro',
    'server', 'blade', 'rackmount',
    'switch', 'router', 'firewall', 'access point', 'network', 'hub',
    'tablet', 'phone', 'mobile', 'smartphone', 'ipad', 'iphone', 'android', 'galaxy', 'handset', 'dect',
    'hard drive', 'ssd', 'hdd', 'nas', 'san',
    'workstation', 'thin client', 'all-in-one'
]


def is_data_bearing_device(description: str) -> bool:
    if not description:
        return False
    desc_lower = description.lower()
    for dtype in DATA_BEARING_TYPES:
        if dtype in desc_lower:
            return True
    return False


def get_roller_queue_status(days_threshold: int = 1, target_date: date | None = None, roller_whitelist: List[str] | None = None, qa_user_filter: List[str] | None = None) -> Dict[str, object]:
    from qa_export import get_mariadb_connection, _parse_timestamp
    conn = get_mariadb_connection()
    if not conn:
        return {
            "rollers": [], 
            "totals": {
                "total": 0, 
                "awaiting_qa": 0,       
                "awaiting_sorting": 0,  
            }
        }
    
    result = {
        "rollers": [],
        "totals": {
            "total": 0, 
            "awaiting_qa": 0,       
            "awaiting_sorting": 0,  
        }
    }

    try:
        cursor = conn.cursor()
        if target_date:
            date_clause = "AND DATE(a.last_update) = %s"
            params_for_assets = (target_date.isoformat(),)
        else:
            date_clause = "AND a.last_update IS NOT NULL AND a.last_update >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
            params_for_assets = (days_threshold,)

        cursor.execute(f"""
            SELECT 
                a.stockid,
                a.roller_location,
                a.serialnumber,
                a.description,
                a.de_complete,
                COALESCE(a.pallet_id, a.palletID) as pallet_id,
                (SELECT MAX(q.added_date) FROM ITAD_QA_App q WHERE q.stockid = a.stockid) as last_qa_date,
                (SELECT q2.username FROM ITAD_QA_App q2 WHERE q2.stockid = a.stockid ORDER BY q2.added_date DESC LIMIT 1) as last_qa_user,
                a.de_completed_date,
                NULL as blancco_last_job,
                COALESCE(b.blancco_count, 0) as blancco_count,
                COALESCE(NULLIF(TRIM(a.`condition`), ''), 'Unknown') as destination
            FROM ITAD_asset_info a
            LEFT JOIN (
                SELECT stockid, COUNT(*) AS blancco_count
                FROM ITAD_asset_info_blancco
                GROUP BY stockid
            ) b ON b.stockid = a.stockid
            WHERE a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
              {date_clause}
        """, params_for_assets)

        asset_rows = cursor.fetchall()

        roller_data = {}

        stockids = [str(r[0]) for r in asset_rows if r and r[0]]
        unique_stockids = list({s for s in stockids if s})
        audit_map: Dict[str, Dict[str, object]] = {}

        if unique_stockids:
            try:
                am_cur = conn.cursor()
                placeholders = ",".join(["%s"] * len(unique_stockids))
                am_query = f"""
                    SELECT t.sales_order, am.log_description, am.user_id, t.dt
                    FROM (
                        SELECT sales_order, MAX(date_time) as dt
                        FROM audit_master
                        WHERE audit_type IN (
                            'DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload',
                            'Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload'
                        )
                          AND sales_order IN ({placeholders})
                          {"AND DATE(date_time) = %s" if target_date else "AND date_time >= DATE_SUB(NOW(), INTERVAL %s DAY)"}
                        GROUP BY sales_order
                    ) t
                    JOIN audit_master am ON am.sales_order = t.sales_order AND am.date_time = t.dt
                """.replace('{placeholders}', placeholders)

                if target_date:
                    params = unique_stockids + [target_date.isoformat()]
                else:
                    params = unique_stockids + [days_threshold]

                am_cur.execute(am_query, params)
                for sales_order, log_description, user_id, dt in am_cur.fetchall():
                    key = str(sales_order)
                    audit_map[key] = {
                        'has_qa': True,
                        'log_description': str(log_description) if log_description is not None else None,
                        'last_date': dt,
                        'user_id': user_id,
                    }
            except Exception:
                audit_map = {}
            finally:
                try:
                    am_cur.close()
                except Exception:
                    pass

        normalized_whitelist = None
        if roller_whitelist:
            normalized_whitelist = {normalize_roller_name(r) for r in roller_whitelist}

        for row in asset_rows:
            stockid = row[0]
            roller_name_raw = row[1] or "Unknown Roller"
            roller_name = normalize_roller_name(roller_name_raw)
            if normalized_whitelist is not None and roller_name not in normalized_whitelist:
                continue
            serial = row[2]
            description = row[3] or ""
            de_complete_raw = row[4]
            pallet_id = row[5]
            last_qa_date = row[6]
            last_qa_user = row[7] if len(row) > 7 else None
            de_completed_date = row[8]
            blancco_last_job = row[9]
            blancco_count = int(row[10] or 0)
            destination_raw = row[11]
            destination_norm = (str(destination_raw).strip() if destination_raw is not None else '')

            is_data_bearing = is_data_bearing_device(description)
            is_erased_flag = str(de_complete_raw or "").lower() in ("yes", "true", "1")
            has_blancco = blancco_count > 0 or (blancco_last_job is not None)
            has_erasures = has_blancco or is_erased_flag or (de_completed_date is not None)
            has_qa = bool(last_qa_date)

            audit_entry = audit_map.get(str(stockid)) if stockid else None
            if not has_qa and audit_entry:
                am_user = (audit_entry.get('user_id') or '').lower() if audit_entry.get('user_id') else None
                if qa_user_filter:
                    matches = any((u.lower() in (am_user or '') or u.lower() == (last_qa_user or '').lower()) for u in qa_user_filter)
                    if not matches:
                        has_qa = False
                    else:
                        has_qa = True
                        last_qa_date = audit_entry.get('last_date')
                else:
                    has_qa = True
                    last_qa_date = audit_entry.get('last_date')

            has_pallet = bool(pallet_id and str(pallet_id).strip() and str(pallet_id).strip().lower() not in ('none', 'null', ''))

            if has_pallet:
                continue

            if not has_erasures and not has_qa:
                continue

            if (not roller_name_raw or roller_name_raw.strip() == '') and stockid and str(stockid) in audit_map:
                log_desc = audit_map.get(str(stockid)).get('log_description')
                if log_desc:
                    m = re.search(r'(IA-ROLLER\d+)', log_desc, re.IGNORECASE)
                    if m:
                        roller_name = normalize_roller_name(m.group(1))
                    else:
                        m2 = re.search(r'<location>([^<]+)</location>', log_desc, re.IGNORECASE)
                        if m2 and m2.group(1).strip():
                            roller_name = normalize_roller_name(m2.group(1).strip())
                        else:
                            roller_name = 'Unknown Roller'

            last_erasure_ts = _parse_timestamp(de_completed_date) if de_completed_date else None
            last_qa_ts = _parse_timestamp(last_qa_date) if last_qa_date else None

            if (last_erasure_ts and (not last_qa_ts or last_erasure_ts >= last_qa_ts)) or (has_blancco and not last_qa_ts) or (is_erased_flag and not last_qa_ts):
                stage = "awaiting_qa"
            elif last_qa_ts and not has_pallet:
                stage = "awaiting_sorting"
            else:
                continue

            if roller_name not in roller_data:
                roller_data[roller_name] = {
                    "roller": roller_name,
                    "total": 0,
                    "awaiting_qa": 0,
                    "awaiting_sorting": 0,
                    "data_bearing": 0,
                    "non_data_bearing": 0,
                    "samples": [],
                }

            roller_data[roller_name]["total"] += 1
            roller_data[roller_name][stage] += 1
            if is_data_bearing:
                roller_data[roller_name]["data_bearing"] += 1
            else:
                roller_data[roller_name]["non_data_bearing"] += 1

            if len(roller_data[roller_name]["samples"]) < 6:
                roller_data[roller_name]["samples"].append({
                    "stockid": stockid,
                    "serial": serial,
                    "description": description,
                    "de_complete": de_complete_raw,
                    "de_completed_date": str(de_completed_date) if de_completed_date else None,
                    "last_qa_date": str(last_qa_date) if last_qa_date else None,
                    "blancco_count": blancco_count,
                    "destination": destination_norm,
                })

        result["rollers"] = sorted(roller_data.values(), key=lambda x: x["roller"])
        result["totals"]["total"] = sum(r["total"] for r in result["rollers"])
        result["totals"]["awaiting_qa"] = sum(r["awaiting_qa"] for r in result["rollers"])
        result["totals"]["awaiting_sorting"] = sum(r["awaiting_sorting"] for r in result["rollers"])
        
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[QA Export] Error fetching roller queue status: {e}")
        if conn:
            conn.close()
    
    return result


def get_stale_devices(days_threshold: int = 7) -> List[Dict[str, object]]:
    from qa_export import get_mariadb_connection
    conn = get_mariadb_connection()
    if not conn:
        return []
    
    devices = []
    cutoff_date = (datetime.now() - timedelta(days=days_threshold)).date()
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                a.stockid,
                a.serialnumber,
                a.manufacturer,
                a.description,
                a.condition,
                a.received_date,
                a.stage_current,
                a.stage_next,
                a.location,
                a.roller_location,
                a.last_update,
                a.de_complete,
                a.process_complete,
                COALESCE(a.pallet_id, a.palletID) as pallet_id,
                DATEDIFF(CURDATE(), a.last_update) as days_since_update
            FROM ITAD_asset_info a
            WHERE a.last_update IS NOT NULL
              AND a.last_update < %s
              AND (a.process_complete IS NULL OR a.process_complete != 'Yes')
              AND a.`condition` NOT IN ('Disposed', 'Shipped', 'Sold')
            ORDER BY a.last_update ASC
            LIMIT 500
        """, (cutoff_date.isoformat(),))
        
        for row in cursor.fetchall():
            devices.append({
                "stockid": row[0],
                "serial": row[1],
                "manufacturer": row[2],
                "model": row[3],
                "condition": row[4],
                "received_date": str(row[5]) if row[5] else None,
                "stage_current": row[6],
                "stage_next": row[7],
                "location": row[8],
                "roller_location": row[9],
                "last_update": str(row[10]) if row[10] else None,
                "de_complete": row[11],
                "process_complete": row[12],
                "pallet_id": row[13],
                "days_since_update": row[14],
            })
        
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[QA Export] Error fetching stale devices: {e}")
        if conn:
            conn.close()
    
    return devices
