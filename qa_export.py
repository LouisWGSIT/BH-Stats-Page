"""QA Dashboard Stats - MariaDB Integration for Quality Assurance Metrics"""
import pymysql
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple
from collections import defaultdict, Counter

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

        cursor.execute("""
            SELECT user_id,
                   COUNT(*) as total_scans,
                   DATE(date_time) as scan_date
            FROM audit_master
            WHERE audit_type = 'DEAPP_Submission'
              AND user_id IS NOT NULL AND user_id <> ''
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

        cursor.execute("""
            SELECT user_id,
                   COUNT(*) as total_scans,
                   DATE(date_time) as scan_date
            FROM audit_master
            WHERE audit_type = 'Non_DEAPP_Submission'
              AND user_id IS NOT NULL AND user_id <> ''
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
    """Get the all-time record for most QA done in a single day"""
    conn = get_mariadb_connection()
    if not conn:
        return {'qa_record': 0, 'qa_engineer': 'Unknown', 'qa_date': None}
    
    try:
        cursor = conn.cursor()
        
        # Get QA app record
        cursor.execute("""
            SELECT DATE(added_date) as scan_date, username, COUNT(*) as scans
            FROM ITAD_QA_App
            GROUP BY DATE(added_date), username
            ORDER BY scans DESC
            LIMIT 1
        """)
        
        qa_row = cursor.fetchone()
        qa_record = 0
        qa_engineer = 'Unknown'
        qa_date = None
        
        if qa_row:
            qa_date, username, qa_record = qa_row
            qa_engineer = username or '(unassigned)'
            if '@' in qa_engineer:
                qa_engineer = qa_engineer.split('@')[0]
                parts = qa_engineer.split('.')
                if len(parts) >= 2:
                    qa_engineer = f"{parts[0].title()} {parts[1][0].upper()}"
        
        # Get DE QA (data-bearing) record
        cursor.execute("""
            SELECT DATE(submission_date) as submit_date, submitted_by, COUNT(*) as scans
            FROM view_audit_submission
            WHERE submission_date IS NOT NULL
            GROUP BY DATE(submission_date), submitted_by
            ORDER BY scans DESC
            LIMIT 1
        """)
        
        de_row = cursor.fetchone()
        de_record = 0
        de_engineer = 'Unknown'
        
        if de_row:
            de_date, username, de_record = de_row
            de_engineer = username or '(unassigned)'
            if '@' in de_engineer:
                de_engineer = de_engineer.split('@')[0]
                parts = de_engineer.split('.')
                if len(parts) >= 2:
                    de_engineer = f"{parts[0].title()} {parts[1][0].upper()}"
        
        # Get non-DE QA record
        cursor.execute("""
            SELECT DATE(submission_date) as submit_date, submitted_by, COUNT(*) as scans
            FROM audit_master
            WHERE submission_date IS NOT NULL
            GROUP BY DATE(submission_date), submitted_by
            ORDER BY scans DESC
            LIMIT 1
        """)
        
        non_de_row = cursor.fetchone()
        non_de_record = 0
        non_de_engineer = 'Unknown'
        
        if non_de_row:
            non_de_date, username, non_de_record = non_de_row
            non_de_engineer = username or '(unassigned)'
            if '@' in non_de_engineer:
                non_de_engineer = non_de_engineer.split('@')[0]
                parts = non_de_engineer.split('.')
                if len(parts) >= 2:
                    non_de_engineer = f"{parts[0].title()} {parts[1][0].upper()}"
        
        cursor.close()
        conn.close()
        
        # Combine QA records (all QA types)
        total_record = qa_record + de_record + non_de_record
        record_engineer = qa_engineer  # Use QA app engineer if they had the highest
        
        if de_record > qa_record and de_record >= non_de_record:
            record_engineer = de_engineer
            total_record = de_record
        elif non_de_record > qa_record and non_de_record >= de_record:
            record_engineer = non_de_engineer
            total_record = non_de_record
        
        return {
            'qa_record': int(total_record),
            'qa_engineer': record_engineer,
            'qa_date': qa_date.isoformat() if qa_date else None
        }
    
    except Exception as e:
        print(f"[QA Export] Error fetching all-time daily record: {e}")
        if conn:
            conn.close()
        return {'qa_record': 0, 'qa_engineer': 'Unknown', 'qa_date': None}