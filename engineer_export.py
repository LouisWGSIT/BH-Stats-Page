"""Manager-focused engineer performance tracking - weekly progression view"""
from datetime import datetime, timedelta, date
import sqlite3
from typing import Dict, List, Tuple
import database as db
from collections import defaultdict, Counter

WORK_HOURS_START = 8  # 8:00 AM
WORK_HOURS_END = 16   # 4:00 PM (16:00)

def get_week_dates(period: str) -> Tuple[date, date, str]:
    """Get Monday-Friday dates for a given period"""
    today = date.today()
    
    if period == "this_week":
        # Get Monday of this week
        start = today - timedelta(days=today.weekday())
        # End date is today (or Friday if today is weekend)
        if today.weekday() >= 5:  # Saturday or Sunday
            end = start + timedelta(days=4)  # Friday
        else:
            end = today
        label = "This Week"
    elif period == "last_week":
        # Get Monday-Friday of last week
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=4)  # Friday
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

def get_daily_engineer_data(date_str: str) -> Dict[str, Dict]:
    """Get all engineers' data for a specific day (work hours only)"""
    conn = sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()
    
    # Fetch records for this day during work hours (8-16:00)
    cursor.execute("""
        SELECT initials, device_type, duration_sec, manufacturer, model, drive_size
        FROM erasures
        WHERE date = ? AND event = 'success'
        ORDER BY initials
    """, (date_str,))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Aggregate by engineer
    data = defaultdict(lambda: {
        'erasures': 0,
        'device_types': Counter(),
        'manufacturers': Counter(),
        'durations': [],
        'disk_capacities': []
    })
    
    for initials, device_type, duration_sec, manufacturer, model, drive_size in rows:
        if not initials:
            initials = '(unassigned)'
        
        data[initials]['erasures'] += 1
        data[initials]['device_types'][device_type or 'unknown'] += 1
        if manufacturer:
            data[initials]['manufacturers'][manufacturer] += 1
        if duration_sec:
            try:
                data[initials]['durations'].append(int(duration_sec))
            except:
                pass
        if drive_size:
            try:
                data[initials]['disk_capacities'].append(int(drive_size))
            except:
                pass
    
    return data

def _get_period_totals(start_date: date, end_date: date) -> Dict[str, float]:
    conn = sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(1), AVG(duration_sec), AVG(drive_size)
        FROM erasures
        WHERE date >= ? AND date <= ? AND event = 'success'
        """,
        (start_date.isoformat(), end_date.isoformat())
    )
    total, avg_duration, avg_capacity = cursor.fetchone()
    conn.close()
    return {
        "total": total or 0,
        "avg_duration": round(avg_duration, 1) if avg_duration is not None else None,
        "avg_capacity_gb": round(avg_capacity / 1_000_000_000, 2) if avg_capacity is not None else None
    }

def _get_daily_breakdown(start_date: date, end_date: date) -> Dict[str, Dict]:
    conn = sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT date, device_type, COUNT(1) as cnt, AVG(duration_sec) as avg_dur
        FROM erasures
        WHERE date >= ? AND date <= ? AND event = 'success'
        GROUP BY date, device_type
        ORDER BY date ASC
        """,
        (start_date.isoformat(), end_date.isoformat())
    )
    rows = cursor.fetchall()
    conn.close()

    breakdown = defaultdict(lambda: {
        "total": 0,
        "devices": Counter(),
        "avg_duration": None
    })

    for date_str, device_type, cnt, avg_dur in rows:
        breakdown[date_str]["total"] += cnt
        breakdown[date_str]["devices"][device_type or "unknown"] += cnt
        if avg_dur is not None:
            breakdown[date_str]["avg_duration"] = round(avg_dur, 1)

    return breakdown

def _get_speed_challenge_for_date(date_str: str, time_window: str) -> List[Dict[str, any]]:
    conn = sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()
    if time_window == "am":
        start_hour, end_hour = 8, 12
    else:
        start_hour, end_hour = 13, 16

    cursor.execute(
        """
        SELECT initials, COUNT(*) as count
        FROM erasures
        WHERE date = ?
          AND event = 'success'
          AND initials IS NOT NULL
          AND CAST(strftime('%H', ts) AS INTEGER) >= ?
          AND CAST(strftime('%H', ts) AS INTEGER) < ?
        GROUP BY initials
        ORDER BY count DESC
        LIMIT 5
        """,
        (date_str, start_hour, end_hour)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"initials": row[0], "erasures": row[1]} for row in rows]

def generate_engineer_deepdive_export(period: str) -> Dict[str, List[List]]:
    """Generate manager-focused erasure export with exec summary and engineer detail"""
    start_date, end_date, period_label = get_week_dates(period)

    sheets = {}

    # Collect all engineers and their daily data
    all_engineers = {}
    current_date = start_date
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    day_index = 0
    is_week_period = period in ["this_week", "last_week"]

    while current_date <= end_date:
        daily_data = get_daily_engineer_data(current_date.isoformat())

        for engineer, data in daily_data.items():
            if engineer not in all_engineers:
                all_engineers[engineer] = {
                    'total': 0,
                    'daily': {},
                    'device_breakdown': Counter(),
                    'manufacturers': Counter(),
                    'durations': [],
                    'disk_capacities': []
                }

            count = data['erasures']
            all_engineers[engineer]['total'] += count
            if is_week_period and day_index < 5:
                all_engineers[engineer]['daily'][day_names[day_index]] = count
            all_engineers[engineer]['device_breakdown'].update(data['device_types'])
            all_engineers[engineer]['manufacturers'].update(data['manufacturers'])
            all_engineers[engineer]['durations'].extend(data['durations'])
            all_engineers[engineer]['disk_capacities'].extend(data['disk_capacities'])

        current_date += timedelta(days=1)
        if is_week_period:
            day_index += 1

    # SHEET 1: Executive Summary (Mon-Fri breakdown for weekly periods)
    totals = _get_period_totals(start_date, end_date)
    active_engineers = len([e for e in all_engineers.values() if e['total'] > 0])
    avg_per_day = round(totals['total'] / max(1, (end_date - start_date).days + 1), 1)

    exec_summary = []
    exec_summary.append([f"EXECUTIVE SUMMARY - {period_label}"])
    exec_summary.append([f"Period: {start_date} to {end_date}"])
    exec_summary.append([])
    exec_summary.append(["Key Metric", "Value"])
    exec_summary.append(["Total Erasures", totals['total']])
    exec_summary.append(["Avg/Day", avg_per_day])
    exec_summary.append(["Avg Duration (sec)", totals['avg_duration'] if totals['avg_duration'] is not None else "N/A"])
    exec_summary.append(["Avg Disk Capacity (GB)", totals['avg_capacity_gb'] if totals['avg_capacity_gb'] is not None else "N/A"])
    exec_summary.append(["Active Engineers", active_engineers])

    if is_week_period:
        exec_summary.append([])
        exec_summary.append(["MON-FRI ERASURE BREAKDOWN"])
        exec_summary.append(["Day", "Total", "Laptops/Desktops", "Servers", "Macs", "Mobiles", "Avg Duration (sec)"])

        daily_breakdown = _get_daily_breakdown(start_date, end_date)
        current_date = start_date
        day_index = 0
        while current_date <= end_date and day_index < 5:
            date_key = current_date.isoformat()
            day_name = day_names[day_index]
            day_data = daily_breakdown.get(date_key, {"total": 0, "devices": Counter(), "avg_duration": None})
            exec_summary.append([
                day_name,
                day_data["total"],
                day_data["devices"].get("laptops_desktops", 0),
                day_data["devices"].get("servers", 0),
                day_data["devices"].get("macs", 0),
                day_data["devices"].get("mobiles", 0),
                day_data["avg_duration"] if day_data["avg_duration"] is not None else "N/A"
            ])
            current_date += timedelta(days=1)
            day_index += 1

    sheets['Executive Summary'] = exec_summary

    # SHEET 2: Engineer Breakdown (manager view)
    breakdown_sheet = []
    breakdown_sheet.append([f"ENGINEER BREAKDOWN - {period_label}"])
    breakdown_sheet.append([f"Period: {start_date} to {end_date}"])
    breakdown_sheet.append([])
    breakdown_sheet.append([
        "Engineer", "Total Erasures", "Avg/Day", "Days Active", "Primary Device",
        "Avg Duration (sec)", "Laptops/Desktops", "Servers", "Macs", "Mobiles"
    ])

    for engineer in sorted(all_engineers.keys()):
        eng_data = all_engineers[engineer]
        total = eng_data['total']
        days_active = len([d for d in eng_data['daily'].values() if d > 0])
        avg_per_day = round(total / days_active, 1) if days_active > 0 else 0
        avg_duration = round(sum(eng_data['durations']) / len(eng_data['durations']), 1) if eng_data['durations'] else 'N/A'

        primary_device = eng_data['device_breakdown'].most_common(1)[0][0] if eng_data['device_breakdown'] else 'N/A'
        primary_device = primary_device.replace('_', ' ').title()

        breakdown_sheet.append([
            engineer,
            total,
            avg_per_day,
            days_active,
            primary_device,
            avg_duration,
            eng_data['device_breakdown'].get('laptops_desktops', 0),
            eng_data['device_breakdown'].get('servers', 0),
            eng_data['device_breakdown'].get('macs', 0),
            eng_data['device_breakdown'].get('mobiles', 0)
        ])

    sheets['Engineer Breakdown'] = breakdown_sheet

    # SHEET 3: Engineer Daily Progression
    daily_sheet = []
    daily_sheet.append([f"ENGINEER DAILY PROGRESSION - {period_label}"])
    daily_sheet.append([f"Period: {start_date} to {end_date}"])
    daily_sheet.append([])
    daily_sheet.append(["Engineer", "Mon", "Tue", "Wed", "Thu", "Fri", "Total"])

    if is_week_period:
        for engineer in sorted(all_engineers.keys()):
            eng_data = all_engineers[engineer]
            row = [
                engineer,
                eng_data['daily'].get('Mon', 0),
                eng_data['daily'].get('Tue', 0),
                eng_data['daily'].get('Wed', 0),
                eng_data['daily'].get('Thu', 0),
                eng_data['daily'].get('Fri', 0),
                eng_data['total']
            ]
            daily_sheet.append(row)
    else:
        daily_sheet.append(["Daily breakdown available for weekly periods only.", "", "", "", "", "", ""])

    sheets['Engineer Daily'] = daily_sheet

    # SHEET 4: Manufacturer Focus
    mfr_sheet = []
    mfr_sheet.append(["MANUFACTURER FOCUS BY ENGINEER"])
    mfr_sheet.append([])
    mfr_sheet.append(["Engineer", "Top Manufacturer", "Count", "2nd Manufacturer", "Count", "3rd Manufacturer", "Count"])

    for engineer in sorted(all_engineers.keys()):
        eng_data = all_engineers[engineer]
        top_3_mfrs = eng_data['manufacturers'].most_common(3)

        row = [engineer]
        for i in range(3):
            if i < len(top_3_mfrs):
                row.extend([top_3_mfrs[i][0], top_3_mfrs[i][1]])
            else:
                row.extend(['—', '—'])

        mfr_sheet.append(row)

    sheets['Manufacturers'] = mfr_sheet

    # SHEET 5: Engineer Performance Metrics (more detail)
    metrics_sheet = []
    metrics_sheet.append(["ENGINEER PERFORMANCE METRICS"])
    metrics_sheet.append([])
    metrics_sheet.append(["Engineer", "Total Erasures", "Avg Duration (sec)", "Avg Disk Capacity (GB)", "Days Active", "Consistency Score*"])

    for engineer in sorted(all_engineers.keys()):
        eng_data = all_engineers[engineer]
        total = eng_data['total']
        days_active = len([d for d in eng_data['daily'].values() if d > 0])

        avg_duration = round(sum(eng_data['durations']) / len(eng_data['durations']), 1) if eng_data['durations'] else 'N/A'

        if eng_data['disk_capacities']:
            avg_capacity_gb = round(sum(eng_data['disk_capacities']) / len(eng_data['disk_capacities']) / 1_000_000_000, 2)
        else:
            avg_capacity_gb = 'N/A'

        if len(eng_data['daily']) > 1:
            daily_values = list(eng_data['daily'].values())
            avg = sum(daily_values) / len(daily_values)
            variance = sum((x - avg) ** 2 for x in daily_values) / len(daily_values)
            consistency = round(100 - (variance / (avg + 1) * 10), 1) if avg > 0 else 0
            consistency = max(0, min(100, consistency))
        else:
            consistency = 'N/A'

        metrics_sheet.append([
            engineer,
            total,
            avg_duration,
            avg_capacity_gb,
            days_active,
            consistency
        ])

    metrics_sheet.append([])
    metrics_sheet.append(["* Consistency Score: 100 = perfectly consistent daily output, 0 = highly variable"])

    sheets['Performance Metrics'] = metrics_sheet

    # SHEET 6: Competition Stats (last pages)
    competition_sheet = []
    competition_sheet.append(["COMPETITION STATS"])
    competition_sheet.append([f"Reference Date: {end_date.isoformat()}"])
    competition_sheet.append([])

    # Leaderboard
    competition_sheet.append(["LEADERBOARD (Top 10)"])
    competition_sheet.append(["Engineer", "Erasures", "Last Active"])
    leaderboard_rows = db.leaderboard(date_str=end_date.isoformat(), limit=10)
    for row in leaderboard_rows:
        competition_sheet.append([row.get("initials"), row.get("erasures"), row.get("lastActive")])

    competition_sheet.append([])
    competition_sheet.append(["CONSISTENCY KINGS/QUEENS (Top 5)"])
    competition_sheet.append(["Engineer", "Consistency Score (lower = steadier)"])
    for row in db.get_consistency_stats(date_str=end_date.isoformat()):
        competition_sheet.append([row.get("initials"), row.get("consistencyScore")])

    competition_sheet.append([])
    competition_sheet.append(["SPEED CHALLENGE - AM"])
    competition_sheet.append(["Engineer", "Erasures"])
    for row in _get_speed_challenge_for_date(end_date.isoformat(), "am"):
        competition_sheet.append([row.get("initials"), row.get("erasures")])

    competition_sheet.append([])
    competition_sheet.append(["SPEED CHALLENGE - PM"])
    competition_sheet.append(["Engineer", "Erasures"])
    for row in _get_speed_challenge_for_date(end_date.isoformat(), "pm"):
        competition_sheet.append([row.get("initials"), row.get("erasures")])

    sheets['Competition Stats'] = competition_sheet

    return sheets
