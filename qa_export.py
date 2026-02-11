"""QA Dashboard Stats - MariaDB Integration for Quality Assurance Metrics"""
import pymysql
import sqlite3
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple
from collections import defaultdict, Counter
import calendar
import re
import database as db

# MariaDB Connection Config
MARIADB_HOST = "77.68.90.229"
MARIADB_USER = "louiswhitehouse"
MARIADB_PASSWORD = "Gr33nsafeIT2026"
MARIADB_DB = "zaptest_"
MARIADB_PORT = 3306

def get_mariadb_connection():
    """Create and return a MariaDB connection"""
    try:
        conn = pymysql.connect(
            host=MARIADB_HOST,
            user=MARIADB_USER,
            password=MARIADB_PASSWORD,
            database=MARIADB_DB,
            port=MARIADB_PORT,
            connect_timeout=10,
            read_timeout=30
        )
        return conn
    except Exception as e:
        print(f"[QA Export] MariaDB connection error: {e}")
        return None

def get_week_dates(period: str) -> Tuple[date, date, str]:
    """Get Monday-Friday dates for a given period"""
    today = date.today()

    if period == "last_available":
        min_date, max_date = get_qa_data_bounds()
        if max_date:
            end = max_date
            start = max_date - timedelta(days=6)
            label = "Last Available"
            return start, end, label
    
    if period == "all_time":
        min_date, max_date = get_qa_data_bounds()
        if min_date and max_date:
            label = "All Time"
            return min_date, max_date, label
        # Fallback to a large range if bounds unavailable
        start = today - timedelta(days=365)
        end = today
        label = "All Time"
        return start, end, label
    
    if period == "today":
        label = "Today"
        return today, today, label

    if period == "this_year":
        start = date(today.year, 1, 1)
        end = today
        label = "This Year"
        return start, end, label

    if period == "last_year":
        last_year = today.year - 1
        start = date(last_year, 1, 1)
        end = date(last_year, 12, 31)
        label = "Last Year"
        return start, end, label

    if period == "last_year_h1":
        last_year = today.year - 1
        start = date(last_year, 1, 1)
        end = date(last_year, 6, 30)
        label = "Last Year (Jan-Jun)"
        return start, end, label

    if period == "last_year_h2":
        last_year = today.year - 1
        start = date(last_year, 7, 1)
        end = date(last_year, 12, 31)
        label = "Last Year (Jul-Dec)"
        return start, end, label
    
    if period == "this_week":
        start = today - timedelta(days=today.weekday())
        if today.weekday() >= 5:  # Saturday or Sunday
            end = start + timedelta(days=4)  # Friday
        else:
            end = today
        label = "This Week"
    elif period == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=4)
        label = "Last Week"
    elif period == "this_month":
        start = today.replace(day=1)
        end = today
        label = "This Month"
    elif period == "last_month":
        last_month_end = today.replace(day=1) - timedelta(days=1)
        start = last_month_end.replace(day=1)
        end = last_month_end
        label = "Last Month"
    else:
        start = today - timedelta(days=today.weekday())
        if today.weekday() >= 5:
            end = start + timedelta(days=4)
        else:
            end = today
        label = "This Week"
    
    return start, end, label

def get_qa_data_bounds() -> Tuple[date | None, date | None]:
    """Return the min/max QA scan dates available in MariaDB."""
    conn = get_mariadb_connection()
    if not conn:
        return None, None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MIN(DATE(added_date)) AS min_date,
                   MAX(DATE(added_date)) AS max_date
            FROM ITAD_QA_App
        """)
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0], row[1]
    except Exception as e:
        print(f"[QA Export] Error fetching QA data bounds: {e}")
        if conn:
            conn.close()
        return None, None

def get_daily_qa_data(date_obj: date) -> Dict[str, Dict]:
    """Get QA data for a specific day aggregated by technician"""
    conn = get_mariadb_connection()
    if not conn:
        return {}
    
    try:
        cursor = conn.cursor()
        date_str = date_obj.isoformat()
        
        # Query QA records for this date
        cursor.execute("""
            SELECT username, scanned_location, COUNT(*) as scans,
                   SUM(CASE WHEN photo_location IS NOT NULL THEN 1 ELSE 0 END) as with_photo
            FROM ITAD_QA_App
            WHERE DATE(added_date) = %s
            GROUP BY username, scanned_location
        """, (date_str,))
        
        rows = cursor.fetchall()
        
        data = defaultdict(lambda: {
            'total_scans': 0,
            'successful': 0,
            'locations': Counter(),
            'daily_count': 0
        })
        
        for username, location, scans, photos in rows:
            if not username or username == 'NO USER':
                username = '(unassigned)'
            
            scans_int = int(scans or 0)
            photos_int = int(photos or 0)
            data[username]['total_scans'] += scans_int
            data[username]['successful'] += photos_int  # Photo = successful scan
            data[username]['locations'][location or 'Unknown'] += scans_int
            data[username]['daily_count'] = scans_int
        
        cursor.close()
        conn.close()
        return dict(data)
    
    except Exception as e:
        print(f"[QA Export] Error fetching daily QA data for {date_str}: {e}")
        if conn:
            conn.close()
        return {}

def get_weekly_qa_comparison(start_date: date, end_date: date) -> Dict[str, Dict]:
    """Get aggregated QA data for entire week/period"""
    conn = get_mariadb_connection()
    if not conn:
        return {}
    
    try:
        cursor = conn.cursor()
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()
        
        # Get aggregated stats
        cursor.execute("""
            SELECT username, 
                   COUNT(*) as total_scans,
                   SUM(CASE WHEN photo_location IS NOT NULL THEN 1 ELSE 0 END) as with_photo,
                   DATE(added_date) as scan_date
            FROM ITAD_QA_App
            WHERE DATE(added_date) >= %s AND DATE(added_date) <= %s
            GROUP BY username, DATE(added_date)
            ORDER BY username, scan_date
        """, (start_str, end_str))
        
        rows = cursor.fetchall()
        
        data = defaultdict(lambda: {
            'total': 0,
            'successful': 0,
            'daily': {},
            'pass_rate': 0.0
        })
        
        for username, total_scans, photos, scan_date in rows:
            if not username or username == 'NO USER':
                username = '(unassigned)'
            
            day_name = scan_date.strftime('%A') if scan_date else 'Unknown'

            total_scans_int = int(total_scans or 0)
            photos_int = int(photos or 0)
            
            data[username]['total'] += total_scans_int
            data[username]['successful'] += photos_int
            data[username]['daily'][day_name] = {
                'date': scan_date,
                'scans': total_scans_int,
                'passed': photos_int
            }
        
        # Calculate pass rates
        for username in data:
            if data[username]['total'] > 0:
                data[username]['pass_rate'] = round(
                    (data[username]['successful'] / data[username]['total']) * 100, 1
                )
        
        cursor.close()
        conn.close()
        return dict(data)
    
    except Exception as e:
        print(f"[QA Export] Error fetching weekly QA data: {e}")
        if conn:
            conn.close()
        return {}

def get_de_qa_comparison(start_date: date, end_date: date) -> Dict[str, Dict]:
    """Get DE QA data from audit_master (DEAPP_Submission) for the period."""
    conn = get_mariadb_connection()
    if not conn:
        return {}

    try:
        cursor = conn.cursor()
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        # Use DISTINCT sales_order to avoid counting duplicates from DEAPP_Submission_EditStock_Payload
        cursor.execute("""
            SELECT user_id,
                   COUNT(DISTINCT sales_order) as total_scans,
                   DATE(date_time) as scan_date
            FROM audit_master
            WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload')
              AND user_id IS NOT NULL AND user_id <> ''
              AND sales_order IS NOT NULL AND sales_order <> ''
              AND DATE(date_time) >= %s AND DATE(date_time) <= %s
            GROUP BY user_id, DATE(date_time)
            ORDER BY user_id, scan_date
        """, (start_str, end_str))

        rows = cursor.fetchall()

        data = defaultdict(lambda: {
            'total': 0,
            'daily': {}
        })

        for username, total_scans, scan_date in rows:
            if not username:
                username = '(unassigned)'

            day_name = scan_date.strftime('%A') if scan_date else 'Unknown'
            total_scans_int = int(total_scans or 0)

            data[username]['total'] += total_scans_int
            data[username]['daily'][day_name] = {
                'date': scan_date,
                'scans': total_scans_int
            }

        cursor.close()
        conn.close()
        return dict(data)

    except Exception as e:
        print(f"[QA Export] Error fetching DE QA data: {e}")
        if conn:
            conn.close()
        return {}


def get_non_de_qa_comparison(start_date: date, end_date: date) -> Dict[str, Dict]:
    """Get Non-DE QA data from audit_master (Non_DEAPP_Submission) for the period."""
    conn = get_mariadb_connection()
    if not conn:
        return {}

    try:
        cursor = conn.cursor()
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        # Use DISTINCT sales_order to avoid counting duplicates from Non_DEAPP_Submission_EditStock_Payload
        cursor.execute("""
            SELECT user_id,
                   COUNT(DISTINCT sales_order) as total_scans,
                   DATE(date_time) as scan_date
            FROM audit_master
            WHERE audit_type IN ('Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload')
              AND user_id IS NOT NULL AND user_id <> ''
              AND sales_order IS NOT NULL AND sales_order <> ''
              AND DATE(date_time) >= %s AND DATE(date_time) <= %s
            GROUP BY user_id, DATE(date_time)
            ORDER BY user_id, scan_date
        """, (start_str, end_str))

        rows = cursor.fetchall()

        data = defaultdict(lambda: {
            'total': 0,
            'daily': {}
        })

        for username, total_scans, scan_date in rows:
            if not username:
                username = '(unassigned)'

            day_name = scan_date.strftime('%A') if scan_date else 'Unknown'
            total_scans_int = int(total_scans or 0)

            data[username]['total'] += total_scans_int
            data[username]['daily'][day_name] = {
                'date': scan_date,
                'scans': total_scans_int
            }

        cursor.close()
        conn.close()
        return dict(data)

    except Exception as e:
        print(f"[QA Export] Error fetching Non-DE QA data: {e}")
        if conn:
            conn.close()
        return {}

def get_qa_daily_totals_range(start_date: date, end_date: date) -> List[Dict[str, int]]:
    """Return daily totals for QA App, DE QA, and Non-DE QA combined."""
    conn = get_mariadb_connection()
    if not conn:
        return []

    totals = defaultdict(lambda: {"qaApp": 0, "deQa": 0, "nonDeQa": 0})
    try:
        cursor = conn.cursor()
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        cursor.execute("""
            SELECT DATE(added_date) as scan_date, COUNT(*) as total_scans
            FROM ITAD_QA_App
            WHERE DATE(added_date) >= %s AND DATE(added_date) <= %s
            GROUP BY DATE(added_date)
            ORDER BY scan_date
        """, (start_str, end_str))
        for scan_date, total_scans in cursor.fetchall():
            if scan_date:
                totals[scan_date]["qaApp"] = int(total_scans or 0)

        cursor.execute("""
            SELECT DATE(date_time) as scan_date, COUNT(DISTINCT sales_order) as total_scans
            FROM audit_master
            WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload')
              AND user_id IS NOT NULL AND user_id <> ''
              AND sales_order IS NOT NULL AND sales_order <> ''
              AND DATE(date_time) >= %s AND DATE(date_time) <= %s
            GROUP BY DATE(date_time)
            ORDER BY scan_date
        """, (start_str, end_str))
        for scan_date, total_scans in cursor.fetchall():
            if scan_date:
                totals[scan_date]["deQa"] = int(total_scans or 0)

        cursor.execute("""
            SELECT DATE(date_time) as scan_date, COUNT(DISTINCT sales_order) as total_scans
            FROM audit_master
            WHERE audit_type IN ('Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload')
              AND user_id IS NOT NULL AND user_id <> ''
              AND sales_order IS NOT NULL AND sales_order <> ''
              AND DATE(date_time) >= %s AND DATE(date_time) <= %s
            GROUP BY DATE(date_time)
            ORDER BY scan_date
        """, (start_str, end_str))
        for scan_date, total_scans in cursor.fetchall():
            if scan_date:
                totals[scan_date]["nonDeQa"] = int(total_scans or 0)

        cursor.close()
        conn.close()

        results = []
        for scan_date in sorted(totals.keys()):
            row = totals[scan_date]
            results.append({
                "date": scan_date.isoformat(),
                "qaApp": row["qaApp"],  # Sorting scans (separate)
                "deQa": row["deQa"],
                "nonDeQa": row["nonDeQa"],
                "qaTotal": row["deQa"] + row["nonDeQa"],  # QA only (no sorting)
                "total": row["qaApp"] + row["deQa"] + row["nonDeQa"]  # Everything combined
            })
        return results
    except Exception as e:
        print(f"[QA Export] Error fetching QA daily totals: {e}")
        if conn:
            conn.close()
        return []

def get_qa_hourly_totals(date_obj: date) -> List[Dict[str, int]]:
    """Return hourly totals for QA App, DE QA, and Non-DE QA for a single day."""
    conn = get_mariadb_connection()
    if not conn:
        return []

    totals = defaultdict(lambda: {"qaApp": 0, "deQa": 0, "nonDeQa": 0})
    date_str = date_obj.isoformat()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT HOUR(added_date) as hour_slot, COUNT(*) as total_scans
            FROM ITAD_QA_App
            WHERE DATE(added_date) = %s
            GROUP BY HOUR(added_date)
            ORDER BY hour_slot
        """, (date_str,))
        for hour_slot, total_scans in cursor.fetchall():
            if hour_slot is not None:
                totals[int(hour_slot)]["qaApp"] = int(total_scans or 0)

        cursor.execute("""
            SELECT HOUR(date_time) as hour_slot, COUNT(DISTINCT sales_order) as total_scans
            FROM audit_master
            WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload')
              AND user_id IS NOT NULL AND user_id <> ''
              AND sales_order IS NOT NULL AND sales_order <> ''
              AND DATE(date_time) = %s
            GROUP BY HOUR(date_time)
            ORDER BY hour_slot
        """, (date_str,))
        for hour_slot, total_scans in cursor.fetchall():
            if hour_slot is not None:
                totals[int(hour_slot)]["deQa"] = int(total_scans or 0)

        cursor.execute("""
            SELECT HOUR(date_time) as hour_slot, COUNT(DISTINCT sales_order) as total_scans
            FROM audit_master
            WHERE audit_type IN ('Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload')
              AND user_id IS NOT NULL AND user_id <> ''
              AND sales_order IS NOT NULL AND sales_order <> ''
              AND DATE(date_time) = %s
            GROUP BY HOUR(date_time)
            ORDER BY hour_slot
        """, (date_str,))
        for hour_slot, total_scans in cursor.fetchall():
            if hour_slot is not None:
                totals[int(hour_slot)]["nonDeQa"] = int(total_scans or 0)

        cursor.close()
        conn.close()

        results = []
        for hour in range(24):
            row = totals[hour]
            results.append({
                "hour": hour,
                "qaApp": row["qaApp"],  # Sorting scans (separate)
                "deQa": row["deQa"],
                "nonDeQa": row["nonDeQa"],
                "qaTotal": row["deQa"] + row["nonDeQa"],  # QA only (no sorting)
                "total": row["qaApp"] + row["deQa"] + row["nonDeQa"]  # Everything combined
            })
        return results
    except Exception as e:
        print(f"[QA Export] Error fetching QA hourly totals: {e}")
        if conn:
            conn.close()
        return []

def get_qa_engineer_daily_totals_range(start_date: date, end_date: date) -> Dict[str, Dict[str, int]]:
    """Return per-engineer daily totals (combined QA App + DE + Non-DE)."""
    conn = get_mariadb_connection()
    if not conn:
        return {}

def get_qa_engineer_daily_breakdown_range(start_date: date, end_date: date) -> List[Dict[str, int | str]]:
    """Return per-engineer daily QA breakdown for QA App, DE, and Non-DE scans."""
    conn = get_mariadb_connection()
    if not conn:
        return []

    results: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(lambda: {
        "qaScans": 0,
        "deQaScans": 0,
        "nonDeQaScans": 0
    })
    try:
        cursor = conn.cursor()
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        cursor.execute("""
            SELECT username, DATE(added_date) as scan_date, COUNT(*) as total_scans
            FROM ITAD_QA_App
            WHERE DATE(added_date) >= %s AND DATE(added_date) <= %s
            GROUP BY username, DATE(added_date)
        """, (start_str, end_str))
        for username, scan_date, total_scans in cursor.fetchall():
            name = username if username else '(unassigned)'
            if scan_date:
                key = (name, scan_date.isoformat())
                results[key]["qaScans"] += int(total_scans or 0)

        cursor.execute("""
            SELECT user_id, DATE(date_time) as scan_date, COUNT(DISTINCT sales_order) as total_scans
            FROM audit_master
            WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload')
              AND user_id IS NOT NULL AND user_id <> ''
              AND sales_order IS NOT NULL AND sales_order <> ''
              AND DATE(date_time) >= %s AND DATE(date_time) <= %s
            GROUP BY user_id, DATE(date_time)
        """, (start_str, end_str))
        for user_id, scan_date, total_scans in cursor.fetchall():
            name = user_id if user_id else '(unassigned)'
            if scan_date:
                key = (name, scan_date.isoformat())
                results[key]["deQaScans"] += int(total_scans or 0)

        cursor.execute("""
            SELECT user_id, DATE(date_time) as scan_date, COUNT(DISTINCT sales_order) as total_scans
            FROM audit_master
            WHERE audit_type IN ('Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload')
              AND user_id IS NOT NULL AND user_id <> ''
              AND sales_order IS NOT NULL AND sales_order <> ''
              AND DATE(date_time) >= %s AND DATE(date_time) <= %s
            GROUP BY user_id, DATE(date_time)
        """, (start_str, end_str))
        for user_id, scan_date, total_scans in cursor.fetchall():
            name = user_id if user_id else '(unassigned)'
            if scan_date:
                key = (name, scan_date.isoformat())
                results[key]["nonDeQaScans"] += int(total_scans or 0)

        cursor.close()
        conn.close()

        rows: List[Dict[str, int | str]] = []
        for (name, date_str), totals in sorted(results.items(), key=lambda x: (x[0][1], x[0][0])):
            total = totals["qaScans"] + totals["deQaScans"] + totals["nonDeQaScans"]
            rows.append({
                "name": name,
                "date": date_str,
                "qaScans": totals["qaScans"],
                "deQaScans": totals["deQaScans"],
                "nonDeQaScans": totals["nonDeQaScans"],
                "total": total
            })
        return rows
    except Exception as e:
        print(f"[QA Export] Error fetching QA engineer breakdown: {e}")
        if conn:
            conn.close()
        return []

    results: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    try:
        cursor = conn.cursor()
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        cursor.execute("""
            SELECT username, DATE(added_date) as scan_date, COUNT(*) as total_scans
            FROM ITAD_QA_App
            WHERE DATE(added_date) >= %s AND DATE(added_date) <= %s
            GROUP BY username, DATE(added_date)
        """, (start_str, end_str))
        for username, scan_date, total_scans in cursor.fetchall():
            name = username if username else '(unassigned)'
            if scan_date:
                results[name][scan_date.isoformat()] += int(total_scans or 0)

        cursor.execute("""
            SELECT user_id, DATE(date_time) as scan_date, COUNT(DISTINCT sales_order) as total_scans
            FROM audit_master
            WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload')
              AND user_id IS NOT NULL AND user_id <> ''
              AND sales_order IS NOT NULL AND sales_order <> ''
              AND DATE(date_time) >= %s AND DATE(date_time) <= %s
            GROUP BY user_id, DATE(date_time)
        """, (start_str, end_str))
        for user_id, scan_date, total_scans in cursor.fetchall():
            name = user_id if user_id else '(unassigned)'
            if scan_date:
                results[name][scan_date.isoformat()] += int(total_scans or 0)

        cursor.execute("""
            SELECT user_id, DATE(date_time) as scan_date, COUNT(DISTINCT sales_order) as total_scans
            FROM audit_master
            WHERE audit_type IN ('Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload')
              AND user_id IS NOT NULL AND user_id <> ''
              AND sales_order IS NOT NULL AND sales_order <> ''
              AND DATE(date_time) >= %s AND DATE(date_time) <= %s
            GROUP BY user_id, DATE(date_time)
        """, (start_str, end_str))
        for user_id, scan_date, total_scans in cursor.fetchall():
            name = user_id if user_id else '(unassigned)'
            if scan_date:
                results[name][scan_date.isoformat()] += int(total_scans or 0)

        cursor.close()
        conn.close()
        return dict(results)
    except Exception as e:
        print(f"[QA Export] Error fetching QA engineer totals: {e}")
        if conn:
            conn.close()
        return {}

def generate_qa_export(period: str) -> Dict[str, List[List]]:
    """Generate comprehensive QA stats export with multiple sheets"""
    start_date, end_date, period_label = get_week_dates(period)
    
    sheets = {}
    
    # Get the QA data
    qa_data = get_weekly_qa_comparison(start_date, end_date)
    
    if not qa_data:
        # Return empty sheets if no data
        return {
            "QA Daily Summary": [["No QA data available for period"]],
            "QA by Technician": [["No QA data available for period"]],
            "QA by Location": [["No QA data available for period"]],
            "Performance KPIs": [["No QA data available for period"]]
        }
    
    # ============= SHEET 1: Daily QA Summary =============
    sheet_data = []
    sheet_data.append(["QA DAILY SUMMARY - " + period_label.upper()])
    sheet_data.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_data.append([])
    
    header = ["Date", "Technician", "Devices Scanned", "Pass Rate (%)", "Primary Location", "Scans"]
    sheet_data.append(header)
    
    # Iterate through dates and technicians
    current_date = start_date
    while current_date <= end_date:
        daily_data = get_daily_qa_data(current_date)
        
        for tech, stats in sorted(daily_data.items()):
            if stats['total_scans'] > 0:
                pass_rate = round((stats['successful'] / stats['total_scans']) * 100, 1)
                primary_loc = stats['locations'].most_common(1)[0][0] if stats['locations'] else "Unknown"
                
                sheet_data.append([
                    current_date.isoformat(),
                    tech,
                    stats['total_scans'],
                    pass_rate,
                    primary_loc,
                    stats['total_scans']
                ])
        
        current_date += timedelta(days=1)
    
    sheets["QA Daily Summary"] = sheet_data
    
    # ============= SHEET 2: QA by Technician =============
    sheet_data = []
    sheet_data.append(["QA TECHNICIAN PERFORMANCE - " + period_label.upper()])
    sheet_data.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_data.append([])
    
    header = ["Technician", "Total Scanned", "Pass Rate (%)", "Avg/Day"]
    
    # Add day columns for this_week
    if period == "this_week":
        header.extend(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    
    header.extend(["Consistency Score*"])
    sheet_data.append(header)
    
    for tech in sorted(qa_data.keys()):
        stats = qa_data[tech]
        avg_per_day = round(stats['total'] / max(1, len(stats['daily'])), 1)
        
        # Calculate consistency score based on daily variance
        daily_counts = [stats['daily'].get(day, {}).get('scans', 0) 
                       for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
                       if day in stats['daily']]
        
        consistency_score = 100
        if daily_counts and len(daily_counts) > 1:
            avg = sum(daily_counts) / len(daily_counts)
            if avg > 0:
                variance = sum((x - avg) ** 2 for x in daily_counts) / len(daily_counts)
                consistency_score = max(0, min(100, 100 - (variance / (avg + 1) * 10)))
        
        row = [tech, stats['total'], stats['pass_rate'], avg_per_day]
        
        if period == "this_week":
            for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
                if day in stats['daily']:
                    row.append(stats['daily'][day]['scans'])
                else:
                    row.append(0)
        
        row.append(round(consistency_score, 1))
        sheet_data.append(row)
    
    sheet_data.append([])
    sheet_data.append(["* 100 = perfectly consistent daily output"])
    sheet_data.append(["  0 = highly variable daily output"])
    
    sheets["QA by Technician"] = sheet_data
    
    # ============= SHEET 3: QA by Location =============
    sheet_data = []
    sheet_data.append(["QA LOCATION ANALYSIS - " + period_label.upper()])
    sheet_data.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_data.append([])
    
    # Aggregate by location
    location_stats = defaultdict(lambda: {'total': 0, 'passed': 0, 'technicians': Counter()})
    
    conn = get_mariadb_connection()
    if conn:
        cursor = conn.cursor()
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()
        
        cursor.execute("""
            SELECT scanned_location, COUNT(*) as total,
                   SUM(CASE WHEN photo_location IS NOT NULL THEN 1 ELSE 0 END) as passed,
                   username
            FROM ITAD_QA_App
            WHERE DATE(added_date) >= %s AND DATE(added_date) <= %s
            GROUP BY scanned_location, username
        """, (start_str, end_str))
        
        for location, total, passed, username in cursor.fetchall():
            loc = location or "Unknown"
            location_stats[loc]['total'] += total
            location_stats[loc]['passed'] += (passed or 0)
            location_stats[loc]['technicians'][username or 'NO USER'] += total
        
        cursor.close()
        conn.close()
    
    sheet_data.append(["Location", "Devices Scanned", "Pass Rate (%)", "Top Technician", "Tech Scans"])
    
    for location in sorted(location_stats.keys()):
        stats = location_stats[location]
        pass_rate = round((stats['passed'] / stats['total']) * 100, 1) if stats['total'] > 0 else 0
        top_tech = stats['technicians'].most_common(1)[0] if stats['technicians'] else ('Unknown', 0)
        
        sheet_data.append([
            location,
            stats['total'],
            pass_rate,
            top_tech[0],
            top_tech[1]
        ])
    
    sheets["QA by Location"] = sheet_data
    
    # ============= SHEET 4: Performance KPIs =============
    sheet_data = []
    sheet_data.append(["QA TECHNICIAN KPIs - " + period_label.upper()])
    sheet_data.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_data.append([])
    
    sheet_data.append(["Technician", "Total Units", "Pass Rate (%)", "Avg/Day", "Days Active", "Reliability Score*"])
    
    for tech in sorted(qa_data.keys()):
        stats = qa_data[tech]
        days_active = len([d for d in stats['daily'] if stats['daily'][d]['scans'] > 0])
        avg_per_day = round(stats['total'] / max(1, days_active), 1) if days_active > 0 else 0
        
        # Reliability score: combination of pass rate and consistency
        pass_rate = stats['pass_rate']
        daily_counts = [stats['daily'][day]['scans'] 
                       for day in stats['daily'] if stats['daily'][day]['scans'] > 0]
        
        consistency = 100
        if daily_counts and len(daily_counts) > 1:
            avg = sum(daily_counts) / len(daily_counts)
            if avg > 0:
                variance = sum((x - avg) ** 2 for x in daily_counts) / len(daily_counts)
                consistency = max(0, min(100, 100 - (variance / (avg + 1) * 10)))
        
        # Reliability = weighted combination of pass rate and consistency
        reliability_score = (pass_rate * 0.6) + (consistency * 0.4)
        
        sheet_data.append([
            tech,
            stats['total'],
            stats['pass_rate'],
            avg_per_day,
            days_active,
            round(reliability_score, 1)
        ])
    
    sheet_data.append([])
    sheet_data.append(["* Reliability Score combines Pass Rate (60%) and Consistency (40%)"])
    
    sheets["Performance KPIs"] = sheet_data
    
    return sheets

def get_all_time_daily_record() -> Dict:
    """Get the all-time records for most QA done in a single day"""
    conn = get_mariadb_connection()
    if not conn:
        return {'data_bearing_records': [], 'non_data_bearing_records': []}
    
    try:
        cursor = conn.cursor()
        
        # Get top 4 data-bearing records (excluding managers) - only best record per person
        cursor.execute("""
            SELECT user_id, qa_count, qa_date
            FROM (
                SELECT user_id,
                       COUNT(DISTINCT sales_order) as qa_count,
                       DATE(date_time) as qa_date,
                       ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY COUNT(DISTINCT sales_order) DESC, DATE(date_time) DESC) as rn
                FROM audit_master
                WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload')
                  AND user_id IS NOT NULL AND user_id <> ''
                  AND sales_order IS NOT NULL AND sales_order <> ''
                  AND user_id NOT LIKE '%mark.aldington%'
                  AND user_id NOT LIKE '%brandon.brace%'
                GROUP BY user_id, DATE(date_time)
            ) ranked
            WHERE rn = 1
            ORDER BY qa_count DESC
            LIMIT 6
        """)
        
        data_bearing_records = []
        for row in cursor.fetchall():
            username, count, scan_date = row
            name = username or '(unassigned)'
            if '@' in name:
                name = name.split('@')[0]
                parts = name.split('.')
                if len(parts) >= 2:
                    name = f"{parts[0].title()} {parts[1][0].upper()}"
            data_bearing_records.append({
                'name': name,
                'count': int(count),
                'date': scan_date.isoformat() if scan_date else None
            })
        
        # Get top 6 non-data-bearing records (excluding managers) - only best record per person
        cursor.execute("""
            SELECT user_id, qa_count, qa_date
            FROM (
                SELECT user_id,
                       COUNT(DISTINCT sales_order) as qa_count,
                       DATE(date_time) as qa_date,
                       ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY COUNT(DISTINCT sales_order) DESC, DATE(date_time) DESC) as rn
                FROM audit_master
                WHERE audit_type IN ('Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload')
                  AND user_id IS NOT NULL AND user_id <> ''
                  AND sales_order IS NOT NULL AND sales_order <> ''
                  AND user_id NOT LIKE '%mark.aldington%'
                  AND user_id NOT LIKE '%brandon.brace%'
                GROUP BY user_id, DATE(date_time)
            ) ranked
            WHERE rn = 1
            ORDER BY qa_count DESC
            LIMIT 6
        """)
        
        non_data_bearing_records = []
        for row in cursor.fetchall():
            username, count, scan_date = row
            name = username or '(unassigned)'
            if '@' in name:
                name = name.split('@')[0]
                parts = name.split('.')
                if len(parts) >= 2:
                    name = f"{parts[0].title()} {parts[1][0].upper()}"
            non_data_bearing_records.append({
                'name': name,
                'count': int(count),
                'date': scan_date.isoformat() if scan_date else None
            })
        
        cursor.close()
        conn.close()
        
        return {
            'data_bearing_records': data_bearing_records,
            'non_data_bearing_records': non_data_bearing_records
        }
    
    except Exception as e:
        print(f"[QA Export] Error fetching all-time daily records: {e}")
        if conn:
            conn.close()
        return {'data_bearing_records': [], 'non_data_bearing_records': []}

def _parse_timestamp(value: str | datetime | date | None, fallback_date: str | None = None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str) and value.strip():
        cleaned = value.strip().replace("Z", "")
        try:
            return datetime.fromisoformat(cleaned)
        except Exception:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    return datetime.strptime(cleaned, fmt)
                except Exception:
                    continue
    if fallback_date:
        try:
            return datetime.fromisoformat(fallback_date)
        except Exception:
            return None
    return None

def _format_timestamp(value: str | datetime | date | None) -> str | None:
    parsed = _parse_timestamp(value)
    if not parsed:
        return str(value) if value is not None else None
    return parsed.strftime("%Y-%m-%d %H:%M:%S")

def _format_drive_size_gb(value: object) -> str | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except Exception:
        return None
    if numeric <= 0:
        return None
    if numeric >= 1_000_000_000:
        gb = numeric / 1_000_000_000
    else:
        gb = numeric
    return f"{gb:.1f}"

def _normalize_id_value(value: object) -> object | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and not text.startswith("0"):
        try:
            return int(text)
        except Exception:
            return text
    return text

def _extract_from_text(text: str | None, patterns: List[str]) -> str | None:
    if not text:
        return None
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return None

def _extract_stock_id(text: str | None) -> str | None:
    patterns = [
        r"<stock_id>([^<]+)</stock_id>",
        r"stock_id\s*=\s*'([^']+)'",
        r"stock_id\s*=\s*\"([^\"]+)\"",
        r"stockID\";s:\d+:\"([^\"]+)\"",
        r"stockid\";s:\d+:\"([^\"]+)\"",
        r"stockID\s*[:=]\s*\"?([^\",\s]+)\"?",
        r"stockid\s*[:=]\s*\"?([^\",\s]+)\"?",
    ]
    return _extract_from_text(text, patterns)

def _extract_serial(text: str | None) -> str | None:
    patterns = [
        r"serialnumber\s*=\s*'([^']+)'",
        r"serialnumber\s*=\s*\"([^\"]+)\"",
        r"stock_serial_frm\";s:\d+:\"([^\"]+)\"",
        r"serial\s*[:=]\s*\"?([^\",\s]+)\"?",
    ]
    return _extract_from_text(text, patterns)

def get_qa_device_events_range(start_date: date, end_date: date) -> List[Dict[str, object]]:
    """Return QA device events (data bearing + non-data bearing) between dates."""
    conn = get_mariadb_connection()
    if not conn:
        return []

    events: List[Dict[str, object]] = []
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT date_time, audit_type, user_id, log_description, log_description2
            FROM audit_master
            WHERE audit_type IN (
                'DEAPP_Submission',
                'DEAPP_Submission_EditStock_Payload',
                'Non_DEAPP_Submission',
                'Non_DEAPP_Submission_EditStock_Payload'
            )
              AND DATE(date_time) >= %s AND DATE(date_time) <= %s
            ORDER BY date_time ASC
            """,
            (start_date.isoformat(), end_date.isoformat())
        )
        rows = cursor.fetchall()

        stock_ids: List[str] = []
        for date_time, audit_type, user_id, log_desc, log_desc2 in rows:
            stock_id = _extract_stock_id(log_desc) or _extract_stock_id(log_desc2)
            serial = _extract_serial(log_desc2) or _extract_serial(log_desc)
            if stock_id:
                stock_ids.append(stock_id)

            stage = "QA Data Bearing" if audit_type.startswith("DEAPP_") else "QA Non-Data Bearing"
            events.append({
                "timestamp": date_time.isoformat() if isinstance(date_time, (datetime, date)) else date_time,
                "stage": stage,
                "stockid": stock_id,
                "serial": serial,
                "user": user_id,
                "location": None,
                "device_type": None,
                "manufacturer": None,
                "model": None,
                "drive_size": None,
                "drive_type": None,
                "drive_count": None,
                "destination": None,
                "pallet_id": None,
                "pallet_destination": None,
                "pallet_location": None,
                "pallet_status": None,
                "source": "audit_master",
            })

        asset_map: Dict[str, Dict[str, object]] = {}
        if stock_ids:
            unique_ids = list({s for s in stock_ids if s})
            if unique_ids:
                placeholders = ",".join(["%s"] * len(unique_ids))
                cursor.execute(
                    f"""
                    SELECT stockid, serialnumber, manufacturer, description, `condition`, 
                           COALESCE(pallet_id, palletID), location, roller_location, last_update
                    FROM ITAD_asset_info
                    WHERE stockid IN ({placeholders})
                    """,
                    unique_ids
                )
                for row in cursor.fetchall():
                    stockid, serialnumber, manufacturer, description, condition, pallet_id, location, roller_location, last_update = row
                    asset_map[str(stockid)] = {
                        "serial": serialnumber,
                        "manufacturer": manufacturer,
                        "model": description,
                        "destination": condition,
                        "pallet_id": pallet_id,
                        "asset_location": location,
                        "roller_location": roller_location,
                        "last_update": str(last_update) if last_update else None,
                    }

                missing_pallet_ids = [
                    stockid for stockid in unique_ids
                    if not asset_map.get(str(stockid), {}).get("pallet_id")
                ]
                if missing_pallet_ids:
                    placeholders = ",".join(["%s"] * len(missing_pallet_ids))
                    cursor.execute(
                        f"""
                        SELECT stockid, pallet_id
                        FROM Stockbypallet
                        WHERE stockid IN ({placeholders})
                        """,
                        missing_pallet_ids
                    )
                    for stockid, pallet_id in cursor.fetchall():
                        if pallet_id:
                            asset_map.setdefault(str(stockid), {})["pallet_id"] = pallet_id

        for event in events:
            stock_id = event.get("stockid")
            if stock_id and str(stock_id) in asset_map:
                asset = asset_map[str(stock_id)]
                if not event.get("serial"):
                    event["serial"] = asset.get("serial")
                event["manufacturer"] = asset.get("manufacturer")
                event["model"] = asset.get("model")
                event["destination"] = asset.get("destination")
                event["pallet_id"] = asset.get("pallet_id")
                event["asset_location"] = asset.get("asset_location")
                event["roller_location"] = asset.get("roller_location")
                event["last_update"] = asset.get("last_update")

        pallet_ids = [str(event.get("pallet_id")) for event in events if event.get("pallet_id")]
        unique_pallets = list({p for p in pallet_ids if p})
        pallet_map: Dict[str, Dict[str, object]] = {}
        if unique_pallets:
            placeholders = ",".join(["%s"] * len(unique_pallets))
            cursor.execute(
                f"""
                SELECT pallet_id, destination, pallet_location, pallet_status
                FROM ITAD_pallet
                WHERE pallet_id IN ({placeholders})
                """,
                unique_pallets
            )
            for pallet_id, destination, pallet_location, pallet_status in cursor.fetchall():
                pallet_map[str(pallet_id)] = {
                    "pallet_destination": destination,
                    "pallet_location": pallet_location,
                    "pallet_status": pallet_status,
                }

        for event in events:
            pallet_id = event.get("pallet_id")
            if pallet_id and str(pallet_id) in pallet_map:
                pallet = pallet_map[str(pallet_id)]
                event["pallet_destination"] = pallet.get("pallet_destination")
                event["pallet_location"] = pallet.get("pallet_location")
                event["pallet_status"] = pallet.get("pallet_status")

        cursor.close()
        conn.close()
        return events
    except Exception as e:
        print(f"[QA Export] Error fetching QA device events: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return []

def get_device_history_range(start_date: date, end_date: date) -> List[Dict[str, object]]:
    """Return device history entries (erasure + sorting) between start_date and end_date."""
    history: List[Dict[str, object]] = []

    conn = get_mariadb_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Use subquery to get only one row per stockid from blancco table
            cursor.execute(
                """
                SELECT q.added_date,
                       q.username,
                       q.scanned_location,
                       q.stockid,
                       b.serial,
                       b.manufacturer,
                       b.model
                FROM ITAD_QA_App q
                LEFT JOIN (
                    SELECT stockid, serial, manufacturer, model,
                           ROW_NUMBER() OVER (PARTITION BY stockid ORDER BY job_date DESC) as rn
                    FROM ITAD_asset_info_blancco
                ) b ON b.stockid = q.stockid AND b.rn = 1
                WHERE DATE(q.added_date) >= %s AND DATE(q.added_date) <= %s
                ORDER BY q.added_date ASC
                """,
                (start_date.isoformat(), end_date.isoformat())
            )
            for added_date, username, scanned_location, stockid, serial, manufacturer, model in cursor.fetchall():
                sort_dt = _parse_timestamp(added_date)
                history.append({
                    "timestamp": added_date.isoformat() if isinstance(added_date, (datetime, date)) else added_date,
                    "stage": "Sorting",
                    "stockid": stockid,
                    "serial": serial,
                    "user": username,
                    "location": scanned_location,
                    "device_type": None,
                    "manufacturer": manufacturer,
                    "model": model,
                    "drive_size": None,
                    "drive_type": None,
                    "drive_count": None,
                    "destination": None,
                    "pallet_id": None,
                    "pallet_destination": None,
                    "pallet_location": None,
                    "pallet_status": None,
                    "source": "ITAD_QA_App",
                    "_sort_key": sort_dt
                })
            cursor.close()
        except Exception as e:
            print(f"[QA Export] Error fetching device sorting history: {e}")
        finally:
            conn.close()

    try:
        sqlite_conn = sqlite3.connect(db.DB_PATH)
        cursor = sqlite_conn.cursor()
        cursor.execute(
            """
            SELECT ts, date, initials, device_type, manufacturer, model,
                   system_serial, disk_serial, job_id, drive_size, drive_type, drive_count
            FROM erasures
            WHERE date >= ? AND date <= ? AND event = 'success'
            ORDER BY date ASC, ts ASC
            """,
            (start_date.isoformat(), end_date.isoformat())
        )
        for row in cursor.fetchall():
            ts, date_str, initials, device_type, manufacturer, model, system_serial, disk_serial, job_id, drive_size, drive_type, drive_count = row
            serial_value = system_serial or disk_serial or job_id
            sort_dt = _parse_timestamp(ts, fallback_date=date_str)
            history.append({
                "timestamp": ts or date_str,
                "stage": "Erasure",
                "stockid": None,
                "serial": serial_value,
                "user": initials,
                "location": None,
                "device_type": device_type,
                "manufacturer": manufacturer,
                "model": model,
                "drive_size": drive_size,
                "drive_type": drive_type,
                "drive_count": drive_count,
                "destination": None,
                "pallet_id": None,
                "pallet_destination": None,
                "pallet_location": None,
                "pallet_status": None,
                "source": "erasures",
                "_sort_key": sort_dt
            })
        cursor.close()
        sqlite_conn.close()
    except Exception as e:
        print(f"[QA Export] Error fetching device erasure history: {e}")

    try:
        asset_conn = get_mariadb_connection()
        if asset_conn:
            cursor = asset_conn.cursor()
            stock_ids = [str(item.get("stockid")) for item in history if item.get("stockid")]
            unique_ids = list({s for s in stock_ids if s})
            if unique_ids:
                placeholders = ",".join(["%s"] * len(unique_ids))
                cursor.execute(
                    f"""
                    SELECT stockid, `condition`, COALESCE(pallet_id, palletID)
                    FROM ITAD_asset_info
                    WHERE stockid IN ({placeholders})
                    """,
                    unique_ids
                )
                asset_map = {
                    str(stockid): {
                        "destination": condition,
                        "pallet_id": pallet_id
                    }
                    for stockid, condition, pallet_id in cursor.fetchall()
                }
                missing_pallet_ids = [
                    stockid for stockid in unique_ids
                    if not asset_map.get(str(stockid), {}).get("pallet_id")
                ]
                if missing_pallet_ids:
                    placeholders = ",".join(["%s"] * len(missing_pallet_ids))
                    cursor.execute(
                        f"""
                        SELECT stockid, pallet_id
                        FROM Stockbypallet
                        WHERE stockid IN ({placeholders})
                        """,
                        missing_pallet_ids
                    )
                    for stockid, pallet_id in cursor.fetchall():
                        if pallet_id:
                            asset_map.setdefault(str(stockid), {})["pallet_id"] = pallet_id
                for item in history:
                    stock_id = item.get("stockid")
                    if stock_id and str(stock_id) in asset_map:
                        asset = asset_map[str(stock_id)]
                        item["destination"] = asset.get("destination")
                        item["pallet_id"] = asset.get("pallet_id")
            cursor.close()
            pallet_ids = [str(item.get("pallet_id")) for item in history if item.get("pallet_id")]
            unique_pallets = list({p for p in pallet_ids if p})
            if unique_pallets:
                placeholders = ",".join(["%s"] * len(unique_pallets))
                cursor = asset_conn.cursor()
                cursor.execute(
                    f"""
                    SELECT pallet_id, destination, pallet_location, pallet_status
                    FROM ITAD_pallet
                    WHERE pallet_id IN ({placeholders})
                    """,
                    unique_pallets
                )
                pallet_map = {
                    str(pallet_id): {
                        "pallet_destination": destination,
                        "pallet_location": pallet_location,
                        "pallet_status": pallet_status,
                    }
                    for pallet_id, destination, pallet_location, pallet_status in cursor.fetchall()
                }
                for item in history:
                    pallet_id = item.get("pallet_id")
                    if pallet_id and str(pallet_id) in pallet_map:
                        pallet = pallet_map[str(pallet_id)]
                        item["pallet_destination"] = pallet.get("pallet_destination")
                        item["pallet_location"] = pallet.get("pallet_location")
                        item["pallet_status"] = pallet.get("pallet_status")
                cursor.close()
            asset_conn.close()
    except Exception as e:
        print(f"[QA Export] Error fetching destination/pallet data: {e}")

    history.sort(key=lambda item: item.get("_sort_key") or datetime.min)
    for item in history:
        item.pop("_sort_key", None)

    return history


def _iter_month_ranges(start_date: date, end_date: date) -> List[Tuple[date, date]]:
    ranges: List[Tuple[date, date]] = []
    current = date(start_date.year, start_date.month, 1)
    end_anchor = date(end_date.year, end_date.month, 1)
    while current <= end_anchor:
        last_day = calendar.monthrange(current.year, current.month)[1]
        month_start = current
        month_end = date(current.year, current.month, last_day)
        if month_start < start_date:
            month_start = start_date
        if month_end > end_date:
            month_end = end_date
        ranges.append((month_start, month_end))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return ranges


def get_unpalleted_devices(start_date: date, end_date: date) -> List[Dict[str, object]]:
    """Find devices that have QA or sorting records but NO pallet assignment."""
    conn = get_mariadb_connection()
    if not conn:
        return []
    
    devices = []
    try:
        cursor = conn.cursor()
        # Get devices from QA/sorting that have no pallet_id in ITAD_asset_info
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
            LEFT JOIN ITAD_QA_App q ON q.stockid = a.stockid
            WHERE (a.pallet_id IS NULL OR a.pallet_id = '' OR a.palletID IS NULL OR a.palletID = '')
              AND a.received_date >= %s AND a.received_date <= %s
              AND a.condition NOT IN ('Disposed', 'Shipped', 'Sold')
            ORDER BY a.received_date DESC
        """, (start_date.isoformat(), end_date.isoformat()))
        
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
        print(f"[QA Export] Error fetching unpalleted devices: {e}")
        if conn:
            conn.close()
    
    return devices


def get_stale_devices(days_threshold: int = 7) -> List[Dict[str, object]]:
    """Find devices that haven't had activity in X days but aren't complete."""
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
              AND a.condition NOT IN ('Disposed', 'Shipped', 'Sold')
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


def _build_unpalleted_devices_sheet(start_date: date, end_date: date, period_label: str) -> Dict[str, object]:
    """Build sheet showing devices without pallet assignment."""
    devices = get_unpalleted_devices(start_date, end_date)
    
    sheet_rows = []
    sheet_rows.append(["UNPALLETED DEVICES AUDIT - " + period_label.upper()])
    sheet_rows.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_rows.append([f"Devices received in period with NO pallet assignment. Total: {len(devices)}"])
    sheet_rows.append([])
    
    header = [
        "Stock ID", "Serial", "Manufacturer", "Model", "Condition",
        "Received Date", "Current Stage", "Location", "Roller Location",
        "Last Update", "DE Complete", "DE By", "DE Date",
        "QA Date", "QA User", "QA Location"
    ]
    sheet_rows.append(header)
    
    for device in devices:
        sheet_rows.append([
            device.get("stockid"),
            device.get("serial"),
            device.get("manufacturer"),
            device.get("model"),
            device.get("condition"),
            device.get("received_date"),
            device.get("stage_current"),
            device.get("location"),
            device.get("roller_location"),
            device.get("last_update"),
            device.get("de_complete"),
            device.get("de_completed_by"),
            device.get("de_completed_date"),
            device.get("qa_date"),
            device.get("qa_user"),
            device.get("qa_location"),
        ])
    
    return {
        "rows": sheet_rows,
        "col_widths": {
            1: 12, 2: 16, 3: 14, 4: 28, 5: 14,
            6: 12, 7: 14, 8: 12, 9: 14,
            10: 18, 11: 10, 12: 18, 13: 18,
            14: 18, 15: 22, 16: 14
        }
    }


def _build_stale_devices_sheet() -> Dict[str, object]:
    """Build sheet showing devices with stale activity (no updates in 7+ days)."""
    devices = get_stale_devices(days_threshold=7)
    
    sheet_rows = []
    sheet_rows.append(["STALE DEVICES REPORT"])
    sheet_rows.append([f"Devices with no activity in 7+ days (not complete). Total: {len(devices)}"])
    sheet_rows.append(["Use this to identify devices that may be stuck or lost in the process."])
    sheet_rows.append([])
    
    header = [
        "Stock ID", "Serial", "Manufacturer", "Model", "Condition",
        "Received Date", "Current Stage", "Next Stage", "Location", "Roller Location",
        "Last Update", "Days Since Update", "DE Complete", "Process Complete", "Pallet ID"
    ]
    sheet_rows.append(header)
    
    for device in devices:
        sheet_rows.append([
            device.get("stockid"),
            device.get("serial"),
            device.get("manufacturer"),
            device.get("model"),
            device.get("condition"),
            device.get("received_date"),
            device.get("stage_current"),
            device.get("stage_next"),
            device.get("location"),
            device.get("roller_location"),
            device.get("last_update"),
            device.get("days_since_update"),
            device.get("de_complete"),
            device.get("process_complete"),
            device.get("pallet_id"),
        ])
    
    return {
        "rows": sheet_rows,
        "col_widths": {
            1: 12, 2: 16, 3: 14, 4: 28, 5: 14,
            6: 12, 7: 14, 8: 14, 9: 12, 10: 14,
            11: 18, 12: 8, 13: 10, 14: 10, 15: 14
        }
    }


def _build_device_history_sheet(start_date: date, end_date: date, period_label: str) -> Dict[str, object]:
    # Combine ALL event sources: Sorting, Erasure, AND QA (Data Bearing + Non-Data Bearing)
    history_rows = get_device_history_range(start_date, end_date)
    history_rows.extend(get_qa_device_events_range(start_date, end_date))
    
    # Deduplicate: remove exact duplicates based on (timestamp, stockid, stage, user)
    seen = set()
    deduped_rows = []
    for row in history_rows:
        key = (
            str(row.get("timestamp")),
            str(row.get("stockid")),
            str(row.get("stage")),
            str(row.get("user")),
        )
        if key not in seen:
            seen.add(key)
            deduped_rows.append(row)
    history_rows = deduped_rows
    
    # Sort ALL entries chronologically by timestamp
    history_rows.sort(key=lambda item: _parse_timestamp(item.get("timestamp")) or datetime.min)
    
    grouped_by_date: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in history_rows:
        ts = _parse_timestamp(row.get("timestamp"))
        date_key = ts.date().isoformat() if ts else "unknown"
        grouped_by_date[date_key].append(row)

    sheet_rows: List[List] = []
    sheet_groups: List[Tuple[int, int, int, bool]] = []

    sheet_rows.append(["DEVICE HISTORY - " + period_label.upper()])
    sheet_rows.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_rows.append([])
    sheet_rows.append([
        "Complete device history: Sorting scans, Erasure events, and QA checks (Data Bearing + Non-Data Bearing). Sorted chronologically."
    ])
    sheet_rows.append([])

    header = [
        "Timestamp",
        "Stage",
        "Stock ID",
        "Serial",
        "User/Initials",
        "Location",
        "Manufacturer",
        "Model",
        "Device Type",
        "Drive Size (GB)",
        "Destination",
        "Pallet ID",
        "Pallet Destination",
        "Pallet Status",
        "Source",
        "Last Asset Loc",
        "Roller Location",
        "Days Since Update"
    ]

    for date_key in sorted(grouped_by_date.keys()):
        date_entries = grouped_by_date[date_key]
        date_entries.sort(key=lambda item: _parse_timestamp(item.get("timestamp")) or datetime.min)

        sheet_rows.append([f"DATE: {date_key}"])
        sheet_rows.append(header)
        date_start = len(sheet_rows) + 1

        grouped_history: Dict[str, List[Dict[str, object]]] = defaultdict(list)
        for row in date_entries:
            device_key = row.get("serial") or row.get("stockid") or "unknown"
            grouped_history[str(device_key)].append(row)

        for device_key in sorted(grouped_history.keys()):
            entries = grouped_history[device_key]
            entries.sort(key=lambda item: _parse_timestamp(item.get("timestamp")) or datetime.min)

            stock_id = next((e.get("stockid") for e in entries if e.get("stockid")), None)
            serial = next((e.get("serial") for e in entries if e.get("serial")), None)
            if stock_id is not None and serial is not None and str(stock_id).strip() == str(serial).strip():
                stock_id = None
            device_label = f"DEVICE: {device_key}"
            if stock_id or serial:
                parts = []
                if stock_id:
                    parts.append(f"Stock ID: {stock_id}")
                if serial:
                    parts.append(f"Serial: {serial}")
                device_label = f"{device_label} | " + " | ".join(parts)

            sheet_rows.append([device_label])
            data_start = len(sheet_rows) + 1

            for row in entries:
                stock_value = row.get("stockid")
                serial_value = row.get("serial")
                if stock_value is not None and serial_value is not None and str(stock_value).strip() == str(serial_value).strip():
                    stock_value = None
                
                # Calculate days since last update
                days_since = None
                last_update = row.get("last_update")
                if last_update:
                    try:
                        if isinstance(last_update, datetime):
                            update_dt = last_update
                        else:
                            update_dt = _parse_timestamp(last_update)
                        if update_dt:
                            days_since = (datetime.now() - update_dt).days
                    except Exception:
                        pass
                
                sheet_rows.append([
                    _format_timestamp(row.get("timestamp")),
                    row.get("stage"),
                    _normalize_id_value(stock_value),
                    _normalize_id_value(serial_value),
                    row.get("user"),
                    row.get("location"),
                    row.get("manufacturer"),
                    row.get("model"),
                    row.get("device_type"),
                    _format_drive_size_gb(row.get("drive_size")),
                    row.get("destination"),
                    _normalize_id_value(row.get("pallet_id")),
                    row.get("pallet_destination"),
                    row.get("pallet_status"),
                    row.get("source"),
                    row.get("asset_location"),
                    row.get("roller_location"),
                    days_since
                ])

            data_end = len(sheet_rows)
            if data_end >= data_start:
                sheet_groups.append((data_start, data_end, 2, True))

            sheet_rows.append([])

        date_end = len(sheet_rows) - 1
        if date_end >= date_start:
            sheet_groups.append((date_start, date_end, 1, True))

        sheet_rows.append([])

    return {
        "rows": sheet_rows,
        "groups": sheet_groups,
        "col_widths": {
            1: 19,  # Timestamp
            2: 16,  # Stage
            3: 12,  # Stock ID
            4: 14,  # Serial
            5: 20,  # User/Initials
            6: 14,  # Location
            7: 16,  # Manufacturer
            8: 28,  # Model
            9: 16,  # Device Type
            10: 12, # Drive Size (GB)
            11: 18, # Destination
            12: 12, # Pallet ID
            13: 18, # Pallet Destination
            14: 12, # Pallet Status
            15: 14, # Source
            16: 16, # Last Asset Loc
            17: 14, # Roller Location
            18: 16, # Days Since Update
        }
    }


def _build_device_log_by_engineer_sheet(start_date: date, end_date: date, period_label: str) -> Dict[str, object]:
    history_rows = [
        row for row in get_device_history_range(start_date, end_date)
        if row.get("stage") == "Sorting"
    ]
    history_rows.extend(get_qa_device_events_range(start_date, end_date))
    grouped_by_engineer: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in history_rows:
        engineer_key = row.get("user") or "(unassigned)"
        grouped_by_engineer[str(engineer_key)].append(row)

    sheet_rows: List[List] = []
    sheet_groups: List[Tuple[int, int, int, bool]] = []

    sheet_rows.append(["DEVICE LOG BY ENGINEER - " + period_label.upper()])
    sheet_rows.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_rows.append([])
    sheet_rows.append([
        "Note: Device-level QA (DE/Non-DE) is parsed from audit_master logs. This log includes QA + sorting scans only."
    ])
    sheet_rows.append([])

    header = [
        "Timestamp",
        "Stage",
        "Stock ID",
        "Serial",
        "Location",
        "Manufacturer",
        "Model",
        "Device Type",
        "Drive Size (GB)",
        "Destination",
        "Pallet ID",
        "Pallet Destination",
        "Pallet Status",
        "Source",
        "Last Asset Loc",
        "Roller Location",
        "Days Since Update"
    ]

    for engineer_key in sorted(grouped_by_engineer.keys()):
        entries = grouped_by_engineer[engineer_key]
        entries.sort(key=lambda item: _parse_timestamp(item.get("timestamp")) or datetime.min)

        sheet_rows.append([f"ENGINEER: {engineer_key}"])
        sheet_rows.append(header)
        data_start = len(sheet_rows) + 1

        for row in entries:
            stock_value = row.get("stockid")
            serial_value = row.get("serial")
            if stock_value is not None and serial_value is not None and str(stock_value).strip() == str(serial_value).strip():
                stock_value = None
            
            # Calculate days since last update
            days_since = None
            last_update = row.get("last_update")
            if last_update:
                try:
                    if isinstance(last_update, datetime):
                        update_dt = last_update
                    else:
                        update_dt = _parse_timestamp(last_update)
                    if update_dt:
                        days_since = (datetime.now() - update_dt).days
                except Exception:
                    pass
            
            sheet_rows.append([
                _format_timestamp(row.get("timestamp")),
                row.get("stage"),
                _normalize_id_value(stock_value),
                _normalize_id_value(serial_value),
                row.get("location"),
                row.get("manufacturer"),
                row.get("model"),
                row.get("device_type"),
                _format_drive_size_gb(row.get("drive_size")),
                row.get("destination"),
                _normalize_id_value(row.get("pallet_id")),
                row.get("pallet_destination"),
                row.get("pallet_status"),
                row.get("source"),
                row.get("asset_location"),
                row.get("roller_location"),
                days_since
            ])

        data_end = len(sheet_rows)
        if data_end >= data_start:
            sheet_groups.append((data_start, data_end, 1, True))

        sheet_rows.append([])

    return {
        "rows": sheet_rows,
        "groups": sheet_groups,
        "col_widths": {
            1: 24,  # Timestamp / Engineer header
            2: 16,  # Stage
            3: 12,  # Stock ID
            4: 14,  # Serial
            5: 14,  # Location
            6: 16,  # Manufacturer
            7: 28,  # Model
            8: 16,  # Device Type
            9: 12,  # Drive Size (GB)
            10: 18, # Destination
            11: 12, # Pallet ID
            12: 18, # Pallet Destination
            13: 12, # Pallet Status
            14: 14, # Source
            15: 16, # Last Asset Loc
            16: 14, # Roller Location
            17: 16, # Days Since Update
        }
    }


def get_weekly_chunks(start_date: date, end_date: date) -> List[Tuple[date, date, str]]:
    """Split a date range into weekly chunks (Mon-Sun or Mon-end_date)"""
    chunks = []
    current = start_date
    
    # Align to Monday if not already
    while current.weekday() != 0 and current <= end_date:
        current += timedelta(days=1)
    
    # Handle partial first week if start wasn't Monday
    if start_date < current and current <= end_date:
        week_end = current - timedelta(days=1)
        if week_end >= start_date:
            label = f"Week {len(chunks)+1} ({start_date.strftime('%b %d')} - {week_end.strftime('%b %d')})"
            chunks.append((start_date, week_end, label))
    
    # Generate full weeks
    while current <= end_date:
        week_end = current + timedelta(days=6)
        if week_end > end_date:
            week_end = end_date
        label = f"Week {len(chunks)+1} ({current.strftime('%b %d')} - {week_end.strftime('%b %d')})"
        chunks.append((current, week_end, label))
        current = week_end + timedelta(days=1)
    
    return chunks


def generate_qa_engineer_export_chunked(period: str, start_year: int = None, start_month: int = None, end_year: int = None, end_month: int = None) -> List[Tuple[str, Dict[str, List[List]]]]:
    """
    Generate QA engineer export split into weekly chunks to avoid memory issues.
    Returns list of (filename_suffix, sheets_dict) tuples.
    """
    # Handle custom range
    if period == "custom_range" and start_year and start_month and end_year and end_month:
        start_date = date(start_year, start_month, 1)
        last_day = calendar.monthrange(end_year, end_month)[1]
        end_date = date(end_year, end_month, last_day)
        period_label = f"{start_date.strftime('%b %Y')} - {end_date.strftime('%b %Y')}"
    else:
        start_date, end_date, period_label = get_week_dates(period)
    
    # For short periods (<=7 days), just return single export
    date_span = (end_date - start_date).days
    if date_span <= 7:
        return [("", generate_qa_engineer_export(period, start_year, start_month, end_year, end_month))]
    
    # Split into weekly chunks
    chunks = get_weekly_chunks(start_date, end_date)
    results = []
    
    for chunk_start, chunk_end, chunk_label in chunks:
        # Generate export for this chunk using custom_range internally
        sheets = {}
        
        # Get all QA data types for this chunk
        de_qa_data = get_de_qa_comparison(chunk_start, chunk_end)
        non_de_qa_data = get_non_de_qa_comparison(chunk_start, chunk_end)
        sorting_data = get_weekly_qa_comparison(chunk_start, chunk_end)
        
        all_engineers = set()
        all_engineers.update(de_qa_data.keys())
        all_engineers.update(non_de_qa_data.keys())
        all_engineers.update(sorting_data.keys())
        
        # ============= SHEET 1: Overall QA Summary =============
        sheet_data = []
        sheet_data.append(["QA ENGINEER SUMMARY - " + chunk_label.upper()])
        sheet_data.append([f"Period: {chunk_start.isoformat()} to {chunk_end.isoformat()}"])
        sheet_data.append([])
        
        header = ["Engineer", "Total QA", "Data Bearing", "Non-Data Bearing", "Sorting", "Avg/Day", "Days Active"]
        sheet_data.append(header)
        
        for engineer in sorted(all_engineers):
            de_total = de_qa_data.get(engineer, {}).get('total', 0)
            non_de_total = non_de_qa_data.get(engineer, {}).get('total', 0)
            sorting_total = sorting_data.get(engineer, {}).get('total', 0)
            qa_total = de_total + non_de_total
            
            days_active = len(set(
                list(de_qa_data.get(engineer, {}).get('daily', {}).keys()) +
                list(non_de_qa_data.get(engineer, {}).get('daily', {}).keys()) +
                list(sorting_data.get(engineer, {}).get('daily', {}).keys())
            ))
            
            avg_per_day = round(qa_total / max(1, days_active), 1) if days_active > 0 else 0
            sheet_data.append([engineer, qa_total, de_total, non_de_total, sorting_total, avg_per_day, days_active])
        
        sheets["Overall QA Summary"] = sheet_data
        
        # ============= SHEET 2: Device History (weekly chunk) =============
        sheets["Device History"] = _build_device_history_sheet(chunk_start, chunk_end, chunk_label)
        
        # ============= SHEET 3: Device Log by Engineer (weekly chunk) =============
        sheets["Device Log by Engineer"] = _build_device_log_by_engineer_sheet(chunk_start, chunk_end, chunk_label)
        
        # Create filename suffix from dates
        suffix = f"_{chunk_start.strftime('%Y%m%d')}-{chunk_end.strftime('%Y%m%d')}"
        results.append((suffix, sheets))
    
    return results


def generate_qa_engineer_export(period: str, start_year: int = None, start_month: int = None, end_year: int = None, end_month: int = None) -> Dict[str, List[List]]:
    """Generate comprehensive QA engineer breakdown export with overall, data-bearing, non-data-bearing, sorting, and comparison sections"""
    
    # Handle custom range
    if period == "custom_range" and start_year and start_month and end_year and end_month:
        start_date = date(start_year, start_month, 1)
        # End date is last day of end_month
        last_day = calendar.monthrange(end_year, end_month)[1]
        end_date = date(end_year, end_month, last_day)
        period_label = f"{start_date.strftime('%b %Y')} - {end_date.strftime('%b %Y')}"
    else:
        start_date, end_date, period_label = get_week_dates(period)
    
    sheets = {}
    
    # Get all QA data types
    de_qa_data = get_de_qa_comparison(start_date, end_date)
    non_de_qa_data = get_non_de_qa_comparison(start_date, end_date)
    sorting_data = get_weekly_qa_comparison(start_date, end_date)  # From ITAD_QA_App
    
    # Combine all engineer names
    all_engineers = set()
    all_engineers.update(de_qa_data.keys())
    all_engineers.update(non_de_qa_data.keys())
    all_engineers.update(sorting_data.keys())
    
    # ============= SHEET 1: Overall QA Summary (All Types Combined) =============
    sheet_data = []
    sheet_data.append(["QA ENGINEER SUMMARY - " + period_label.upper()])
    sheet_data.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_data.append([])
    
    header = ["Engineer", "Total QA", "Data Bearing", "Non-Data Bearing", "Sorting", "Avg/Day", "Days Active"]
    
    if period in ["this_week", "last_week"]:
        header.extend(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    
    sheet_data.append(header)
    
    for engineer in sorted(all_engineers):
        de_total = de_qa_data.get(engineer, {}).get('total', 0)
        non_de_total = non_de_qa_data.get(engineer, {}).get('total', 0)
        sorting_total = sorting_data.get(engineer, {}).get('total', 0)
        qa_total = de_total + non_de_total
        
        # Calculate days active (any activity)
        days_active = len(set(
            list(de_qa_data.get(engineer, {}).get('daily', {}).keys()) +
            list(non_de_qa_data.get(engineer, {}).get('daily', {}).keys()) +
            list(sorting_data.get(engineer, {}).get('daily', {}).keys())
        ))
        
        avg_per_day = round(qa_total / max(1, days_active), 1) if days_active > 0 else 0
        
        row = [engineer, qa_total, de_total, non_de_total, sorting_total, avg_per_day, days_active]
        
        if period in ["this_week", "last_week"]:
            for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
                de_day = de_qa_data.get(engineer, {}).get('daily', {}).get(day, {}).get('scans', 0)
                non_de_day = non_de_qa_data.get(engineer, {}).get('daily', {}).get(day, {}).get('scans', 0)
                row.append(de_day + non_de_day)
        
        sheet_data.append(row)
    
    sheets["Overall QA Summary"] = sheet_data
    
    # ============= SHEET 2: Data Bearing QA =============
    sheet_data = []
    sheet_data.append(["DATA BEARING QA - " + period_label.upper()])
    sheet_data.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_data.append([])
    
    header = ["Engineer", "Total", "Avg/Day", "Days Active"]
    
    if period in ["this_week", "last_week"]:
        header.extend(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    
    header.append("Consistency Score")
    sheet_data.append(header)
    
    for engineer in sorted(de_qa_data.keys()):
        stats = de_qa_data[engineer]
        avg_per_day = round(stats['total'] / max(1, len(stats['daily'])), 1)
        days_active = len(stats['daily'])
        
        # Calculate consistency score
        daily_counts = [stats['daily'][day]['scans'] for day in stats['daily']]
        consistency = 100
        if daily_counts and len(daily_counts) > 1:
            avg = sum(daily_counts) / len(daily_counts)
            if avg > 0:
                variance = sum((x - avg) ** 2 for x in daily_counts) / len(daily_counts)
                consistency = max(0, min(100, 100 - (variance / (avg + 1) * 10)))
        
        row = [engineer, stats['total'], avg_per_day, days_active]
        
        if period in ["this_week", "last_week"]:
            for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
                row.append(stats['daily'].get(day, {}).get('scans', 0))
        
        row.append(round(consistency, 1))
        sheet_data.append(row)
    
    sheet_data.append([])
    sheet_data.append(["* Consistency Score: 100 = perfectly consistent, 0 = highly variable"])
    
    sheets["Data Bearing QA"] = sheet_data
    
    # ============= SHEET 3: Non-Data Bearing QA =============
    sheet_data = []
    sheet_data.append(["NON-DATA BEARING QA - " + period_label.upper()])
    sheet_data.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_data.append([])
    
    header = ["Engineer", "Total", "Avg/Day", "Days Active"]
    
    if period in ["this_week", "last_week"]:
        header.extend(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    
    header.append("Consistency Score")
    sheet_data.append(header)
    
    for engineer in sorted(non_de_qa_data.keys()):
        stats = non_de_qa_data[engineer]
        avg_per_day = round(stats['total'] / max(1, len(stats['daily'])), 1)
        days_active = len(stats['daily'])
        
        # Calculate consistency score
        daily_counts = [stats['daily'][day]['scans'] for day in stats['daily']]
        consistency = 100
        if daily_counts and len(daily_counts) > 1:
            avg = sum(daily_counts) / len(daily_counts)
            if avg > 0:
                variance = sum((x - avg) ** 2 for x in daily_counts) / len(daily_counts)
                consistency = max(0, min(100, 100 - (variance / (avg + 1) * 10)))
        
        row = [engineer, stats['total'], avg_per_day, days_active]
        
        if period in ["this_week", "last_week"]:
            for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
                row.append(stats['daily'].get(day, {}).get('scans', 0))
        
        row.append(round(consistency, 1))
        sheet_data.append(row)
    
    sheet_data.append([])
    sheet_data.append(["* Consistency Score: 100 = perfectly consistent, 0 = highly variable"])
    
    sheets["Non-Data Bearing QA"] = sheet_data
    
    # ============= SHEET 4: Sorting (ITAD QA App) =============
    sheet_data = []
    sheet_data.append(["SORTING (ITAD QA APP) - " + period_label.upper()])
    sheet_data.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_data.append([])
    
    header = ["Engineer", "Total Scans", "Avg/Day", "Days Active", "Pass Rate"]
    
    if period in ["this_week", "last_week"]:
        header.extend(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    
    sheet_data.append(header)
    
    for engineer in sorted(sorting_data.keys()):
        stats = sorting_data[engineer]
        avg_per_day = round(stats['total'] / max(1, len(stats['daily'])), 1)
        days_active = len(stats['daily'])
        pass_rate = stats.get('pass_rate', 0)
        
        row = [engineer, stats['total'], avg_per_day, days_active, f"{pass_rate}%"]
        
        if period in ["this_week", "last_week"]:
            for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
                row.append(stats['daily'].get(day, {}).get('scans', 0))
        
        sheet_data.append(row)
    
    sheets["Sorting"] = sheet_data
    
    # ============= SHEET 5: QA vs Sorting Comparison =============
    sheet_data = []
    sheet_data.append(["QA vs SORTING COMPARISON - " + period_label.upper()])
    sheet_data.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_data.append([])
    sheet_data.append(["This sheet compares items QA'd (data+non-data) vs items Sorted"])
    sheet_data.append([])
    
    header = ["Engineer", "Total QA'd", "Total Sorted", "Difference", "QA/Sorting Ratio", "Primary Activity"]
    sheet_data.append(header)
    
    for engineer in sorted(all_engineers):
        de_total = de_qa_data.get(engineer, {}).get('total', 0)
        non_de_total = non_de_qa_data.get(engineer, {}).get('total', 0)
        qa_total = de_total + non_de_total
        sorting_total = sorting_data.get(engineer, {}).get('total', 0)
        
        difference = qa_total - sorting_total
        
        if qa_total > 0 and sorting_total > 0:
            ratio = f"{round(qa_total / sorting_total, 2)}:1"
        elif qa_total > 0:
            ratio = "QA Only"
        elif sorting_total > 0:
            ratio = "Sorting Only"
        else:
            ratio = "N/A"
        
        if qa_total > sorting_total * 1.5:
            primary = "QA Focus"
        elif sorting_total > qa_total * 1.5:
            primary = "Sorting Focus"
        elif qa_total > 0 or sorting_total > 0:
            primary = "Balanced"
        else:
            primary = "Inactive"
        
        sheet_data.append([engineer, qa_total, sorting_total, difference, ratio, primary])
    
    sheet_data.append([])
    sheet_data.append(["* QA/Sorting Ratio shows how many items QA'd per item Sorted"])
    sheet_data.append(["* Primary Activity indicates if engineer focuses more on QA or Sorting"])
    
    sheets["QA vs Sorting"] = sheet_data
    
    # ============= SHEET 6: Daily Breakdown =============
    sheet_data = []
    sheet_data.append(["DAILY BREAKDOWN - " + period_label.upper()])
    sheet_data.append([f"Period: {start_date.isoformat()} to {end_date.isoformat()}"])
    sheet_data.append([])
    
    header = ["Date", "Day", "Engineer", "Data Bearing", "Non-Data", "Total QA", "Sorting"]
    sheet_data.append(header)
    
    # Iterate through each date in the period
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.isoformat()
        day_name = current_date.strftime('%A')
        
        # Get all engineers active on this date
        active_engineers = set()
        for engineer in all_engineers:
            if day_name in de_qa_data.get(engineer, {}).get('daily', {}):
                active_engineers.add(engineer)
            if day_name in non_de_qa_data.get(engineer, {}).get('daily', {}):
                active_engineers.add(engineer)
            if day_name in sorting_data.get(engineer, {}).get('daily', {}):
                active_engineers.add(engineer)
        
        for engineer in sorted(active_engineers):
            de_count = de_qa_data.get(engineer, {}).get('daily', {}).get(day_name, {}).get('scans', 0)
            non_de_count = non_de_qa_data.get(engineer, {}).get('daily', {}).get(day_name, {}).get('scans', 0)
            qa_total = de_count + non_de_count
            sorting_count = sorting_data.get(engineer, {}).get('daily', {}).get(day_name, {}).get('scans', 0)
            
            sheet_data.append([date_str, day_name, engineer, de_count, non_de_count, qa_total, sorting_count])
        
        current_date += timedelta(days=1)
    
    sheets["Daily Breakdown"] = sheet_data

    # ============= SHEET 7/8: Device History + Log by Engineer =============
    if period in ["this_year", "last_year", "last_year_h1", "last_year_h2"]:
        for month_start, month_end in _iter_month_ranges(start_date, end_date):
            month_label = month_start.strftime("%b %Y")
            month_suffix = month_start.strftime("%Y-%m")
            sheets[f"Device History {month_suffix}"] = _build_device_history_sheet(
                month_start,
                month_end,
                month_label
            )
            sheets[f"Device Log by Engineer {month_suffix}"] = _build_device_log_by_engineer_sheet(
                month_start,
                month_end,
                month_label
            )
    else:
        sheets["Device History"] = _build_device_history_sheet(start_date, end_date, period_label)
        sheets["Device Log by Engineer"] = _build_device_log_by_engineer_sheet(start_date, end_date, period_label)
    
    # ============= AUDIT SHEETS: Unpalleted + Stale Devices =============
    sheets["Unpalleted Devices"] = _build_unpalleted_devices_sheet(start_date, end_date, period_label)
    sheets["Stale Devices (7+ days)"] = _build_stale_devices_sheet()
    
    return sheets
