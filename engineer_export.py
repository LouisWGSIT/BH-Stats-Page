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
        SELECT initials, device_type, duration_sec, manufacturer, model, disk_capacity
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
    
    for initials, device_type, duration_sec, manufacturer, model, disk_capacity in rows:
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
        if disk_capacity:
            try:
                data[initials]['disk_capacities'].append(int(disk_capacity))
            except:
                pass
    
    return data

def generate_engineer_deepdive_export(period: str) -> Dict[str, List[List]]:
    """Generate comprehensive manager-focused weekly engineer tracking"""
    start_date, end_date, period_label = get_week_dates(period)
    
    sheets = {}
    
    # SHEET 1: Weekly Summary - KPI Overview
    summary_data = []
    summary_data.append([f"WEEKLY ENGINEER TRACKING - {period_label}"])
    summary_data.append([f"Period: {start_date} to {end_date}"])
    summary_data.append([])
    summary_data.append(["Engineer", "Total Erasures", "Avg/Day", "Mon", "Tue", "Wed", "Thu", "Fri", "Avg Duration (sec)", "Primary Device"])
    
    # Collect all engineers and their daily data
    all_engineers = {}
    daily_data_by_engineer = defaultdict(lambda: {})
    
    current_date = start_date
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    day_index = 0
    
    while current_date <= end_date and day_index < 5:
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
            all_engineers[engineer]['daily'][day_names[day_index]] = count
            all_engineers[engineer]['device_breakdown'].update(data['device_types'])
            all_engineers[engineer]['manufacturers'].update(data['manufacturers'])
            all_engineers[engineer]['durations'].extend(data['durations'])
            all_engineers[engineer]['disk_capacities'].extend(data['disk_capacities'])
        
        current_date += timedelta(days=1)
        day_index += 1
    
    # Build summary sheet with daily progression
    for engineer in sorted(all_engineers.keys()):
        eng_data = all_engineers[engineer]
        total = eng_data['total']
        days_active = len([d for d in eng_data['daily'].values() if d > 0])
        avg_per_day = round(total / days_active, 1) if days_active > 0 else 0
        
        # Get daily counts for each day
        daily_counts = [
            eng_data['daily'].get('Mon', 0),
            eng_data['daily'].get('Tue', 0),
            eng_data['daily'].get('Wed', 0),
            eng_data['daily'].get('Thu', 0),
            eng_data['daily'].get('Fri', 0)
        ]
        
        # Average duration
        avg_duration = round(sum(eng_data['durations']) / len(eng_data['durations']), 1) if eng_data['durations'] else 'N/A'
        
        # Primary device
        primary_device = eng_data['device_breakdown'].most_common(1)[0][0] if eng_data['device_breakdown'] else 'N/A'
        primary_device = primary_device.replace('_', ' ').title()
        
        summary_data.append([
            engineer,
            total,
            avg_per_day,
            *daily_counts,
            avg_duration,
            primary_device
        ])
    
    sheets['Summary'] = summary_data
    
    # SHEET 2: Daily Comparison (This vs Last Week - same day comparison)
    if period == "this_week":
        comparison_data = []
        comparison_data.append(["DAILY COMPARISON - This Week vs Last Week (Same Days)"])
        comparison_data.append([])
        comparison_data.append(["Engineer", "Mon This", "Mon Last", "Change", "Tue This", "Tue Last", "Change", 
                               "Wed This", "Wed Last", "Change", "Thu This", "Thu Last", "Change", 
                               "Fri This", "Fri Last", "Change"])
        
        # Get last week data for comparison
        last_start = start_date - timedelta(days=7)
        last_end = end_date - timedelta(days=7)
        
        current_date = last_start
        last_week_data = defaultdict(lambda: {})
        day_index = 0
        
        while current_date <= last_end and day_index < 5:
            daily_data = get_daily_engineer_data(current_date.isoformat())
            for engineer, data in daily_data.items():
                last_week_data[engineer][day_names[day_index]] = data['erasures']
            current_date += timedelta(days=1)
            day_index += 1
        
        # Build comparison
        for engineer in sorted(all_engineers.keys()):
            eng_data = all_engineers[engineer]
            comparison_row = [engineer]
            
            for day in day_names:
                this_week_val = eng_data['daily'].get(day, 0)
                last_week_val = last_week_data.get(engineer, {}).get(day, 0)
                change = this_week_val - last_week_val
                change_str = f"+{change}" if change > 0 else str(change)
                
                comparison_row.extend([this_week_val, last_week_val, change_str])
            
            comparison_data.append(comparison_row)
        
        sheets['Daily Comparison'] = comparison_data
    
    # SHEET 3: Device Type Distribution (Manager perspective)
    device_sheet = []
    device_sheet.append(["DEVICE TYPE DISTRIBUTION BY ENGINEER"])
    device_sheet.append([])
    device_sheet.append(["Engineer", "Laptops/Desktops", "Servers", "Macs", "Mobiles", "% Specialist (Top Device)"])
    
    for engineer in sorted(all_engineers.keys()):
        eng_data = all_engineers[engineer]
        total = eng_data['total']
        
        laptops = eng_data['device_breakdown'].get('laptops_desktops', 0)
        servers = eng_data['device_breakdown'].get('servers', 0)
        macs = eng_data['device_breakdown'].get('macs', 0)
        mobiles = eng_data['device_breakdown'].get('mobiles', 0)
        
        if total > 0:
            specialist_pct = round((max(laptops, servers, macs, mobiles) / total) * 100, 1)
        else:
            specialist_pct = 0
        
        device_sheet.append([
            engineer,
            laptops,
            servers,
            macs,
            mobiles,
            f"{specialist_pct}%"
        ])
    
    sheets['Device Types'] = device_sheet
    
    # SHEET 4: Performance Metrics (Duration, Throughput, Workload)
    metrics_sheet = []
    metrics_sheet.append(["ENGINEER PERFORMANCE METRICS"])
    metrics_sheet.append([])
    metrics_sheet.append(["Engineer", "Total Erasures", "Avg Duration (sec)", "Avg Disk Capacity (GB)", "Days Active", "Consistency Score*"])
    
    for engineer in sorted(all_engineers.keys()):
        eng_data = all_engineers[engineer]
        total = eng_data['total']
        days_active = len([d for d in eng_data['daily'].values() if d > 0])
        
        avg_duration = round(sum(eng_data['durations']) / len(eng_data['durations']), 1) if eng_data['durations'] else 'N/A'
        
        # Average disk capacity in GB
        if eng_data['disk_capacities']:
            avg_capacity_gb = round(sum(eng_data['disk_capacities']) / len(eng_data['disk_capacities']) / 1_000_000_000, 2)
        else:
            avg_capacity_gb = 'N/A'
        
        # Consistency score (how stable are daily numbers? lower variance = higher consistency)
        if len(eng_data['daily']) > 1:
            daily_values = list(eng_data['daily'].values())
            avg = sum(daily_values) / len(daily_values)
            variance = sum((x - avg) ** 2 for x in daily_values) / len(daily_values)
            consistency = round(100 - (variance / (avg + 1) * 10), 1) if avg > 0 else 0  # 0-100 scale
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
    
    # SHEET 5: Top Manufacturers (What are engineers working on?)
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
    
    return sheets
