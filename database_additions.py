# New functions to add to database.py for competition system

def get_speed_challenge_stats(time_window: str = "am") -> List[Dict]:
    """
    Get speed challenge stats for AM (8:00-12:00) or PM (13:30-15:45) window
    Returns top engineers by erasure count in that time window for today
    """
    import sqlite3
    from datetime import datetime
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    today = get_today_str()
    
    if time_window == "am":
        start_hour, end_hour = 8, 12
    else:  # pm
        start_hour, end_hour = 13, 16  # 13:30-15:45, using 16 as upper bound
    
    cursor.execute("""
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
    """, (today, start_hour, end_hour))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{"initials": row[0], "erasures": row[1]} for row in rows]


def get_category_specialists(date_str: str = None) -> Dict[str, List[Dict]]:
    """
    Get top 3 specialists for each device category
    Returns dict with category names as keys
    """
    import sqlite3
    
    if date_str is None:
        date_str = get_today_str()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    categories = ["laptops_desktops", "servers", "macs", "mobiles"]
    specialists = {}
    
    for category in categories:
        cursor.execute("""
            SELECT initials, SUM(count) as total
            FROM engineer_stats_type
            WHERE date = ? AND device_type = ? AND initials IS NOT NULL
            GROUP BY initials
            ORDER BY total DESC
            LIMIT 3
        """, (date_str, category))
        
        rows = cursor.fetchall()
        specialists[category] = [{"initials": row[0], "count": row[1]} for row in rows]
    
    conn.close()
    return specialists


def get_consistency_stats(date_str: str = None) -> List[Dict]:
    """
    Get consistency rankings - engineers with steadiest pace (smallest gaps between erasures)
    Returns top 5 most consistent engineers
    """
    import sqlite3
    
    if date_str is None:
        date_str = get_today_str()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all timestamps per engineer, calculate gaps
    cursor.execute("""
        SELECT initials, ts
        FROM erasures
        WHERE date = ? AND event = 'success' AND initials IS NOT NULL
        ORDER BY initials, ts
    """, (date_str,))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Calculate consistency scores (standard deviation of time gaps)
    from collections import defaultdict
    from datetime import datetime
    import statistics
    
    engineer_timestamps = defaultdict(list)
    for initials, ts in rows:
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            engineer_timestamps[initials].append(dt)
        except:
            continue
    
    consistency_scores = []
    for initials, timestamps in engineer_timestamps.items():
        if len(timestamps) < 3:  # Need at least 3 erasures to calculate consistency
            continue
        
        # Calculate gaps in minutes
        gaps = []
        for i in range(1, len(timestamps)):
            gap_seconds = (timestamps[i] - timestamps[i-1]).total_seconds()
            gap_minutes = gap_seconds / 60
            gaps.append(gap_minutes)
        
        # Lower standard deviation = more consistent
        if gaps:
            avg_gap = statistics.mean(gaps)
            std_dev = statistics.stdev(gaps) if len(gaps) > 1 else 0
            consistency_scores.append({
                "initials": initials,
                "erasures": len(timestamps),
                "avgGapMinutes": round(avg_gap, 1),
                "consistencyScore": round(std_dev, 1),  # Lower is better
                "totalGapMinutes": round(sum(gaps), 1)
            })
    
    # Sort by consistency (lower std dev = better)
    consistency_scores.sort(key=lambda x: x["consistencyScore"])
    return consistency_scores[:5]


def get_records_and_milestones() -> Dict:
    """
    Get historical records and milestones
    """
    import sqlite3
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Best day ever (highest total erasures in a single day)
    cursor.execute("""
        SELECT date, erased
        FROM daily_stats
        WHERE erased > 0
        ORDER BY erased DESC
        LIMIT 1
    """)
    best_day = cursor.fetchone()
    
    # Top engineer all-time (highest single-day count)
    cursor.execute("""
        SELECT initials, date, count
        FROM engineer_stats
        WHERE count > 0
        ORDER BY count DESC
        LIMIT 1
    """)
    top_engineer = cursor.fetchone()
    
    # Current streak (consecutive days above target)
    # Assuming target is 500/day - get from config if needed
    target = 500
    cursor.execute("""
        SELECT date, erased
        FROM daily_stats
        WHERE date <= date('now')
        ORDER BY date DESC
        LIMIT 30
    """)
    recent_days = cursor.fetchall()
    
    streak = 0
    for date_str, erased in recent_days:
        if erased >= target:
            streak += 1
        else:
            break
    
    conn.close()
    
    return {
        "bestDay": {
            "date": best_day[0] if best_day else None,
            "count": best_day[1] if best_day else 0
        },
        "topEngineer": {
            "initials": top_engineer[0] if top_engineer else None,
            "date": top_engineer[1] if top_engineer else None,
            "count": top_engineer[2] if top_engineer else 0
        },
        "currentStreak": streak
    }


def get_speed_challenge_status(time_window: str = "am") -> Dict:
    """
    Get current status of speed challenge including time remaining
    """
    from datetime import datetime, time
    
    now = datetime.now()
    current_hour = now.hour
    current_minute = now.minute
    
    if time_window == "am":
        start_time = time(8, 0)
        end_time = time(12, 0)
        window_name = "Morning Speed Challenge"
    else:  # pm
        start_time = time(13, 30)
        end_time = time(15, 45)
        window_name = "Afternoon Speed Challenge"
    
    # Calculate if we're currently in the window
    current_time = now.time()
    is_active = start_time <= current_time < end_time
    
    # Calculate time remaining if active
    time_remaining_minutes = 0
    if is_active:
        end_datetime = datetime.combine(now.date(), end_time)
        time_remaining_minutes = int((end_datetime - now).total_seconds() / 60)
    
    return {
        "window": time_window,
        "name": window_name,
        "isActive": is_active,
        "timeRemainingMinutes": time_remaining_minutes,
        "startTime": start_time.strftime("%H:%M"),
        "endTime": end_time.strftime("%H:%M")
    }
