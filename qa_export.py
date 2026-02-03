"""QA Dashboard Stats - MariaDB Integration for Quality Assurance Metrics"""
import pymysql
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple
from collections import defaultdict, Counter

# MariaDB Connection Config
MARIADB_HOST = "77.68.90.229"
MARIADB_USER = "louiswhitehouse"
MARIADB_PASSWORD = "Gr33nsafeIT2026"
MARIADB_DB = "Billingservices"
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
            
            data[username]['total_scans'] += scans
            data[username]['successful'] += (photos or 0)  # Photo = successful scan
            data[username]['locations'][location or 'Unknown'] += scans
            data[username]['daily_count'] = scans
        
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
            
            data[username]['total'] += total_scans
            data[username]['successful'] += (photos or 0)
            data[username]['daily'][day_name] = {
                'date': scan_date,
                'scans': total_scans,
                'passed': photos or 0
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
