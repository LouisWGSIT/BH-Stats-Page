"""Enhanced Excel export for engineer deep-dive analysis"""
from datetime import datetime, timedelta, date
import sqlite3
from typing import Dict, List, Tuple
import database as db
from collections import defaultdict, Counter

def get_date_range(period: str) -> Tuple[str, str]:
    """Get start and end dates for a given period"""
    today = date.today()
    
    if period == "this_week":
        # Monday of this week to today
        start = today - timedelta(days=today.weekday())
        end = today
        label = "This Week"
    elif period == "last_week":
        # Monday to Sunday of last week
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        label = "Last Week"
    elif period == "this_month":
        # First day of this month to today
        start = today.replace(day=1)
        end = today
        label = "This Month"
    elif period == "last_month":
        # First to last day of last month
        last_month_end = today.replace(day=1) - timedelta(days=1)
        start = last_month_end.replace(day=1)
        end = last_month_end
        label = "Last Month"
    else:
        # Default to this week
        start = today - timedelta(days=today.weekday())
        end = today
        label = "This Week"
    
    return start.isoformat(), end.isoformat(), label

def get_engineer_erasures(start_date: str, end_date: str, initials: str = None) -> List[Dict]:
    """Get all erasure records for a date range, optionally filtered by engineer"""
    conn = sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()
    
    if initials:
        cursor.execute("""
            SELECT date, device_type, initials, duration_sec, manufacturer, model, 
                   system_serial, disk_serial, disk_capacity, timestamp
            FROM erasures
            WHERE date >= ? AND date <= ? AND initials = ? AND event = 'success'
            ORDER BY timestamp DESC
        """, (start_date, end_date, initials))
    else:
        cursor.execute("""
            SELECT date, device_type, initials, duration_sec, manufacturer, model, 
                   system_serial, disk_serial, disk_capacity, timestamp
            FROM erasures
            WHERE date >= ? AND date <= ? AND event = 'success'
            ORDER BY initials, timestamp DESC
        """, (start_date, end_date))
    
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            'date': row[0],
            'device_type': row[1] or 'unknown',
            'initials': row[2],
            'duration_sec': row[3],
            'manufacturer': row[4],
            'model': row[5],
            'system_serial': row[6],
            'disk_serial': row[7],
            'disk_capacity': row[8],
            'timestamp': row[9]
        })
    
    return results

def analyze_engineer_data(erasures: List[Dict]) -> Dict:
    """Analyze engineer erasure data to create insights"""
    if not erasures:
        return {
            'total': 0,
            'device_breakdown': {},
            'manufacturer_breakdown': {},
            'model_breakdown': {},
            'daily_breakdown': {},
            'avg_per_day': 0,
            'durations': []
        }
    
    # Aggregate data
    device_types = Counter()
    manufacturers = Counter()
    models = Counter()
    daily_counts = defaultdict(int)
    durations = []
    
    for e in erasures:
        device_types[e['device_type']] += 1
        if e['manufacturer']:
            manufacturers[e['manufacturer']] += 1
        if e['model']:
            models[e['model']] += 1
        if e['date']:
            daily_counts[e['date']] += 1
        if e['duration_sec']:
            try:
                durations.append(int(e['duration_sec']))
            except:
                pass
    
    # Calculate averages
    total_days = len(daily_counts) if daily_counts else 1
    avg_per_day = len(erasures) / total_days
    
    return {
        'total': len(erasures),
        'device_breakdown': dict(device_types.most_common()),
        'manufacturer_breakdown': dict(manufacturers.most_common(10)),  # Top 10
        'model_breakdown': dict(models.most_common(10)),  # Top 10
        'daily_breakdown': dict(daily_counts),
        'avg_per_day': round(avg_per_day, 1),
        'durations': durations,
        'avg_duration': round(sum(durations) / len(durations), 1) if durations else None,
        'days_active': total_days
    }

def create_engineer_overview_sheet(period_label: str, all_engineers: Dict) -> List[List]:
    """Create summary sheet showing all engineers"""
    data = []
    data.append([f"ENGINEER OVERVIEW - {period_label}"])
    data.append([])
    data.append(["Engineer", "Total Erasures", "Avg/Day", "Days Active", "Primary Device Type", "Top Manufacturer"])
    
    for initials, analysis in sorted(all_engineers.items(), key=lambda x: x[1]['total'], reverse=True):
        primary_device = max(analysis['device_breakdown'].items(), key=lambda x: x[1])[0] if analysis['device_breakdown'] else 'N/A'
        top_mfr = max(analysis['manufacturer_breakdown'].items(), key=lambda x: x[1])[0] if analysis['manufacturer_breakdown'] else 'N/A'
        
        data.append([
            initials,
            analysis['total'],
            analysis['avg_per_day'],
            analysis['days_active'],
            primary_device.replace('_', ' ').title(),
            top_mfr
        ])
    
    return data

def create_engineer_detail_sheet(initials: str, analysis: Dict, period_label: str) -> List[List]:
    """Create detailed analysis sheet for a single engineer"""
    data = []
    data.append([f"ENGINEER DEEP DIVE: {initials} - {period_label}"])
    data.append([])
    
    # Summary section
    data.append(["PERFORMANCE SUMMARY"])
    data.append(["Total Erasures", analysis['total']])
    data.append(["Days Active", analysis['days_active']])
    data.append(["Average Per Day", analysis['avg_per_day']])
    if analysis['avg_duration']:
        data.append(["Average Duration (sec)", analysis['avg_duration']])
    data.append([])
    
    # Device type breakdown
    data.append(["DEVICE TYPE BREAKDOWN"])
    data.append(["Device Type", "Count", "Percentage"])
    for device_type, count in analysis['device_breakdown'].items():
        percentage = round((count / analysis['total']) * 100, 1)
        data.append([device_type.replace('_', ' ').title(), count, f"{percentage}%"])
    data.append([])
    
    # Manufacturer breakdown
    data.append(["MANUFACTURER BREAKDOWN"])
    data.append(["Manufacturer", "Count", "Percentage"])
    for mfr, count in analysis['manufacturer_breakdown'].items():
        percentage = round((count / analysis['total']) * 100, 1)
        data.append([mfr, count, f"{percentage}%"])
    data.append([])
    
    # Model breakdown
    data.append(["TOP MODELS ERASED"])
    data.append(["Model", "Count"])
    for model, count in analysis['model_breakdown'].items():
        data.append([model or 'Unknown', count])
    data.append([])
    
    # Daily breakdown
    data.append(["DAILY ACTIVITY"])
    data.append(["Date", "Erasures"])
    for date_str, count in sorted(analysis['daily_breakdown'].items()):
        # Format date nicely
        try:
            dt = datetime.fromisoformat(date_str)
            formatted_date = dt.strftime("%A, %b %d")
        except:
            formatted_date = date_str
        data.append([formatted_date, count])
    
    return data

def generate_engineer_deepdive_export(period: str) -> Dict[str, List[List]]:
    """Generate comprehensive engineer analysis Excel export"""
    start_date, end_date, period_label = get_date_range(period)
    
    # Get all erasures for the period
    all_erasures = get_engineer_erasures(start_date, end_date)
    
    # Group by engineer
    engineer_erasures = defaultdict(list)
    for erasure in all_erasures:
        if erasure['initials']:
            engineer_erasures[erasure['initials']].append(erasure)
    
    # Analyze each engineer
    all_engineers = {}
    for initials, erasures in engineer_erasures.items():
        all_engineers[initials] = analyze_engineer_data(erasures)
    
    # Create sheets
    sheets_data = {}
    
    # Overview sheet
    sheets_data["Overview"] = create_engineer_overview_sheet(period_label, all_engineers)
    
    # Individual engineer sheets (top engineers by volume)
    sorted_engineers = sorted(all_engineers.items(), key=lambda x: x[1]['total'], reverse=True)
    for initials, analysis in sorted_engineers[:15]:  # Top 15 engineers
        sheet_name = f"{initials}"[:31]  # Excel sheet name limit
        sheets_data[sheet_name] = create_engineer_detail_sheet(initials, analysis, period_label)
    
    return sheets_data
