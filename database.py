import sqlite3
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple
from pathlib import Path
import os

# Use env var for persistent disk path on Render, fall back to local for dev
DB_PATH = os.getenv("STATS_DB_PATH", str(Path(__file__).parent / "warehouse_stats.db"))

def init_db():
    """Initialize database with required tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Daily stats table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            booked_in INTEGER DEFAULT 0,
            erased INTEGER DEFAULT 0,
            qa INTEGER DEFAULT 0
        )
    """)
    
    # Engineer stats table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS engineer_stats (
            date TEXT,
            initials TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (date, initials)
        )
    """)

    # Engineer stats by device type
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS engineer_stats_type (
            date TEXT,
            device_type TEXT,
            initials TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (date, device_type, initials)
        )
    """)
    
    # Seen IDs table for deduplication
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seen_ids (
            date TEXT,
            job_id TEXT,
            PRIMARY KEY (date, job_id)
        )
    """)

    # Detailed erasure events
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS erasures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            date TEXT,
            month TEXT,
            event TEXT,             -- success|failure|connected
            device_type TEXT,       -- laptops_desktops|servers|loose_drives|macs|mobiles
            initials TEXT,
            duration_sec INTEGER,
            error_type TEXT,
            job_id TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_erasures_date ON erasures(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_erasures_month ON erasures(month)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_erasures_type ON erasures(device_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_erasures_initials ON erasures(initials)")
    
    conn.commit()
    conn.close()

def get_today_str() -> str:
    """Get today's date as string"""
    return date.today().isoformat()

def get_yesterday_str() -> str:
    """Get yesterday's date as string (Friday if today is Monday)"""
    from datetime import timedelta
    today = date.today()
    # If today is Monday (0), go back to Friday (3 days)
    # Otherwise, go back 1 day
    days_back = 3 if today.weekday() == 0 else 1
    return (today - timedelta(days=days_back)).isoformat()

def delete_event_by_job(job_id: str) -> int:
    """Delete erasure events and seen_id by job_id. Returns rows deleted from erasures."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM erasures WHERE job_id = ?", (job_id,))
    deleted = cursor.rowcount
    cursor.execute("DELETE FROM seen_ids WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()
    return deleted

def get_daily_stats(date_str: str = None) -> Dict[str, int]:
    """Get stats for a specific date (defaults to today)"""
    if date_str is None:
        date_str = get_today_str()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT booked_in, erased, qa FROM daily_stats WHERE date = ?",
        (date_str,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {"bookedIn": row[0], "erased": row[1], "qa": row[2]}
    return {"bookedIn": 0, "erased": 0, "qa": 0}

def increment_stat(stat_name: str, amount: int = 1, date_str: str = None):
    """Increment a specific stat counter"""
    if date_str is None:
        date_str = get_today_str()
    
    # Map frontend names to DB columns
    column_map = {"bookedIn": "booked_in", "erased": "erased", "qa": "qa"}
    column = column_map.get(stat_name, stat_name)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Insert or update
    cursor.execute(f"""
        INSERT INTO daily_stats (date, {column})
        VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET {column} = {column} + ?
    """, (date_str, amount, amount))
    
    conn.commit()
    conn.close()

def is_job_seen(job_id: str, date_str: str = None) -> bool:
    """Check if a job ID has been seen today"""
    if date_str is None:
        date_str = get_today_str()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM seen_ids WHERE date = ? AND job_id = ?",
        (date_str, job_id)
    )
    result = cursor.fetchone() is not None
    conn.close()
    return result

def mark_job_seen(job_id: str, date_str: str = None):
    """Mark a job ID as seen"""
    if date_str is None:
        date_str = get_today_str()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO seen_ids (date, job_id) VALUES (?, ?)",
        (date_str, job_id)
    )
    conn.commit()
    conn.close()

def increment_engineer_count(initials: str, amount: int = 1, date_str: str = None):
    """Increment engineer erasure count"""
    if date_str is None:
        date_str = get_today_str()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO engineer_stats (date, initials, count)
        VALUES (?, ?, ?)
        ON CONFLICT(date, initials) DO UPDATE SET count = count + ?
    """, (date_str, initials, amount, amount))
    conn.commit()
    conn.close()

def increment_engineer_type_count(device_type: str, initials: str, amount: int = 1, date_str: str = None):
    """Increment engineer erasure count for a specific device type"""
    if date_str is None:
        date_str = get_today_str()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO engineer_stats_type (date, device_type, initials, count)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date, device_type, initials) DO UPDATE SET count = count + ?
    """, (date_str, device_type, initials, amount, amount))
    conn.commit()
    conn.close()

def add_erasure_event(*, event: str, device_type: str, initials: str = None, duration_sec: int = None,
                      error_type: str = None, job_id: str = None, ts: str = None):
    """Insert a detailed erasure event"""
    from datetime import datetime
    if ts is None:
        ts = datetime.utcnow().isoformat()
    d = ts[:10]
    month = ts[:7]

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO erasures (ts, date, month, event, device_type, initials, duration_sec, error_type, job_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ts, d, month, event, device_type, (initials or None), duration_sec, (error_type or None), (job_id or None))
    )
    conn.commit()
    conn.close()

def get_summary_today_month(date_str: str = None):
    """Return totals for a specific date and its month, success rate and avg duration.
    If date_str is None, uses today's date."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    target_date = date_str if date_str else get_today_str()
    month = target_date[:7]

    cursor.execute("SELECT COUNT(1) FROM erasures WHERE month = ?", (month,))
    month_total = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(1) FROM erasures WHERE date = ?", (target_date,))
    today_total_all = cursor.fetchone()[0] or 0
    cursor.execute("SELECT COUNT(1) FROM erasures WHERE date = ? AND event = 'success'", (target_date,))
    today_success = cursor.fetchone()[0] or 0
    cursor.execute("SELECT AVG(duration_sec) FROM erasures WHERE date = ? AND duration_sec IS NOT NULL", (target_date,))
    avg_dur = cursor.fetchone()[0]
    conn.close()

    success_rate = (today_success / today_total_all * 100.0) if today_total_all else 0.0
    return {
        "todayTotal": today_total_all,
        "monthTotal": month_total,
        "successRate": round(success_rate, 1),
        "avgDurationSec": int(avg_dur) if avg_dur is not None else None
    }

def get_counts_by_type_today():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    today = get_today_str()
    cursor.execute(
        "SELECT device_type, COUNT(1) FROM erasures WHERE date = ? AND event = 'success' GROUP BY device_type",
        (today,)
    )
    rows = cursor.fetchall()
    conn.close()
    return {k or "unknown": v for (k, v) in rows}

def get_error_distribution_today():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    today = get_today_str()
    cursor.execute(
        "SELECT COALESCE(error_type, 'Other') AS et, COUNT(1) FROM erasures WHERE date = ? AND event = 'failure' GROUP BY et",
        (today,)
    )
    rows = cursor.fetchall()
    conn.close()
    return {k: v for (k, v) in rows}

def top_engineers(scope: str = 'today', device_type: str = None, limit: int = 3):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if scope == 'month':
        key_col = 'month'
        key_val = get_today_str()[:7]
    else:
        key_col = 'date'
        key_val = get_today_str()

    where = f"{key_col} = ? AND event = 'success'"
    params = [key_val]
    if device_type:
        where += " AND device_type = ?"
        params.append(device_type)

    cursor.execute(f"SELECT initials, COUNT(1) c FROM erasures WHERE {where} AND initials IS NOT NULL GROUP BY initials ORDER BY c DESC LIMIT ?", (*params, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"initials": r[0], "count": r[1]} for r in rows]

def leaderboard(scope: str = 'today', limit: int = 6, date_str: str = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if date_str:
        # Explicit date provided
        key_col = 'date'
        key_val = date_str
    elif scope == 'month':
        key_col = 'month'
        key_val = get_today_str()[:7]
    elif scope == 'yesterday':
        key_col = 'date'
        key_val = get_yesterday_str()  # Use helper that handles Monday->Friday
    else:  # today
        key_col = 'date'
        key_val = get_today_str()

    cursor.execute(f"""
        SELECT initials,
               COUNT(1) AS total,
               MAX(ts) AS last_active
        FROM erasures
        WHERE {key_col} = ? AND initials IS NOT NULL
        GROUP BY initials
        ORDER BY total DESC
        LIMIT ?
    """, (key_val, limit))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "initials": r[0],
            "erasures": r[1],
            "lastActive": r[2],
        }
        for r in rows
    ]

def get_top_engineers(limit: int = 3, date_str: str = None) -> List[Dict[str, any]]:
    """Get top engineers by erasure count"""
    if date_str is None:
        date_str = get_today_str()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT initials, count
        FROM engineer_stats
        WHERE date = ?
        ORDER BY count DESC
        LIMIT ?
    """, (date_str, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{"initials": row[0], "count": row[1]} for row in rows]

def get_top_engineers_by_type(device_type: str, limit: int = 3, date_str: str = None) -> List[Dict[str, any]]:
    """Get top engineers for a given device type"""
    if date_str is None:
        date_str = get_today_str()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT initials, count
        FROM engineer_stats_type
        WHERE date = ? AND device_type = ?
        ORDER BY count DESC
        LIMIT ?
    """, (date_str, device_type, limit))

    rows = cursor.fetchall()
    conn.close()

    return [{"initials": row[0], "count": row[1]} for row in rows]

def get_weekly_category_trends() -> Dict[str, List[Dict]]:
    """Get last 7 days of category data for trend analysis"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get last 7 days
    cursor.execute("""
        SELECT date, device_type, SUM(count) as total
        FROM engineer_stats_type
        WHERE date >= date('now', '-7 days')
        GROUP BY date, device_type
        ORDER BY date ASC
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    # Organize by category
    trends = {}
    for row in rows:
        date_str, device_type, total = row
        if device_type not in trends:
            trends[device_type] = []
        trends[device_type].append({"date": date_str, "count": total})
    
    return trends

def get_weekly_engineer_stats() -> List[Dict]:
    """Get weekly totals and consistency for engineers"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get weekly totals and days active
    cursor.execute("""
        SELECT initials, 
               SUM(count) as weekly_total,
               COUNT(DISTINCT date) as days_active
        FROM engineer_stats
        WHERE date >= date('now', '-7 days')
        GROUP BY initials
        ORDER BY weekly_total DESC
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            "initials": row[0],
            "weeklyTotal": row[1],
            "daysActive": row[2],
            "consistency": round((row[2] / 7.0) * 100, 1)  # % of days active
        }
        for row in rows
    ]

def get_peak_hours() -> List[Dict]:
    """Get hourly breakdown of erasures for today"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    today = get_today_str()
    
    # Extract hour from timestamp and count
    cursor.execute("""
        SELECT CAST(strftime('%H', ts) AS INTEGER) as hour,
               COUNT(*) as count
        FROM erasures
        WHERE date(ts) = ?
        GROUP BY hour
        ORDER BY hour
    """, (today,))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Fill in missing hours with 0
    hourly_data = {i: 0 for i in range(24)}
    for row in rows:
        hourly_data[row[0]] = row[1]
    
    return [{"hour": h, "count": c} for h, c in hourly_data.items()]

def get_day_of_week_patterns() -> List[Dict]:
    """Get average erasures by day of week over last 4 weeks"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get day of week (0=Sunday, 6=Saturday) and average counts
    cursor.execute("""
        SELECT CAST(strftime('%w', date) AS INTEGER) as dow,
               AVG(erased) as avg_count
        FROM daily_stats
        WHERE date >= date('now', '-28 days')
        GROUP BY dow
        ORDER BY dow
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    day_names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    
    # Fill in missing days with 0
    dow_data = {i: 0 for i in range(7)}
    for row in rows:
        dow_data[row[0]] = round(row[1], 1)
    
    return [{"day": day_names[i], "avgCount": dow_data[i]} for i in range(7)]


def get_speed_challenge_stats(time_window: str = "am") -> List[Dict]:
    """Get speed challenge stats for AM (8:00-12:00) or PM (13:30-15:45)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    today = get_today_str()
    
    if time_window == "am":
        start_hour, end_hour = 8, 12
    else:  # pm
        start_hour, end_hour = 13, 16
    
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
    """Get top 3 specialists for each device category from erasures table"""
    if date_str is None:
        date_str = get_today_str()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    categories = ["laptops_desktops", "servers", "macs", "mobiles"]
    specialists = {}
    
    for category in categories:
        cursor.execute("""
            SELECT initials, COUNT(1) as total
            FROM erasures
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
    """Get consistency rankings - steadiest pace"""
    if date_str is None:
        date_str = get_today_str()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT initials, ts
        FROM erasures
        WHERE date = ? AND event = 'success' AND initials IS NOT NULL
        ORDER BY initials, ts
    """, (date_str,))
    
    rows = cursor.fetchall()
    conn.close()
    
    from collections import defaultdict
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
        if len(timestamps) < 3:
            continue
        
        gaps = []
        for i in range(1, len(timestamps)):
            gap_seconds = (timestamps[i] - timestamps[i-1]).total_seconds()
            gaps.append(gap_seconds / 60)
        
        if gaps:
            avg_gap = statistics.mean(gaps)
            std_dev = statistics.stdev(gaps) if len(gaps) > 1 else 0
            consistency_scores.append({
                "initials": initials,
                "erasures": len(timestamps),
                "avgGapMinutes": round(avg_gap, 1),
                "consistencyScore": round(std_dev, 1)
            })
    
    consistency_scores.sort(key=lambda x: x["consistencyScore"])
    return consistency_scores[:5]


def get_records_and_milestones() -> Dict:
    """Get historical records and milestones"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT date, erased
        FROM daily_stats
        WHERE erased > 0
        ORDER BY erased DESC
        LIMIT 1
    """)
    best_day = cursor.fetchone()
    
    # Get top engineer all-time (total across all days) from raw erasure events
    cursor.execute("""
        SELECT initials, COUNT(1) AS total_count
        FROM erasures
        WHERE initials IS NOT NULL
        GROUP BY initials
        ORDER BY total_count DESC
        LIMIT 1
    """)
    top_engineer = cursor.fetchone()
    
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
            "totalCount": top_engineer[1] if top_engineer else 0
        },
        "currentStreak": streak
    }


def get_speed_challenge_status(time_window: str = "am") -> Dict:
    """Get current status of speed challenge including time remaining"""
    from datetime import time as dt_time
    
    now = datetime.now()
    current_time = now.time()
    
    if time_window == "am":
        start_time = dt_time(8, 0)
        end_time = dt_time(12, 0)
        window_name = "Morning Speed Challenge"
    else:
        start_time = dt_time(13, 30)
        end_time = dt_time(15, 45)
        window_name = "Afternoon Speed Challenge"
    
    is_active = start_time <= current_time < end_time
    
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


def get_weekly_stats(date_str: str = None) -> Dict:
    """Get statistics for the current week (past 7 days including today)"""
    if date_str is None:
        date_str = get_today_str()
    
    from datetime import timedelta
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get past 7 days including today
    week_start = (datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=6)).strftime('%Y-%m-%d')
    week_end = date_str
    
    # Get all daily totals for the week
    cursor.execute("""
        SELECT date, erased
        FROM daily_stats
        WHERE date >= ? AND date <= ?
        ORDER BY date DESC
    """, (week_start, week_end))
    
    daily_totals = cursor.fetchall()
    
    if not daily_totals:
        conn.close()
        return {
            "weekTotal": 0,
            "bestDayOfWeek": {"date": None, "count": 0},
            "weekAverage": 0,
            "daysActive": 0
        }
    
    week_total = sum(total[1] for total in daily_totals)
    best_day = max(daily_totals, key=lambda x: x[1])
    days_active = len([t for t in daily_totals if t[1] > 0])
    week_average = round(week_total / 7) if len(daily_totals) > 0 else 0
    
    conn.close()
    
    return {
        "weekTotal": week_total,
        "bestDayOfWeek": {"date": best_day[0], "count": best_day[1]},
        "weekAverage": week_average,
        "daysActive": days_active
    }

def get_performance_trends(target: int = 500) -> Dict:
    """Get performance trends: WoW, MoM, rolling averages, and trend indicators"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    today = date.today()
    
    # Get current week total (last 7 days)
    cursor.execute("""
        SELECT COALESCE(SUM(erased), 0)
        FROM daily_stats
        WHERE date >= date('now', '-7 days')
    """)
    current_week_total = cursor.fetchone()[0]
    
    # Get previous week total (8-14 days ago)
    cursor.execute("""
        SELECT COALESCE(SUM(erased), 0)
        FROM daily_stats
        WHERE date >= date('now', '-14 days') AND date < date('now', '-7 days')
    """)
    previous_week_total = cursor.fetchone()[0]
    
    # Calculate WoW % change
    wow_change = 0
    if previous_week_total > 0:
        wow_change = round(((current_week_total - previous_week_total) / previous_week_total) * 100, 1)
    
    # Get current month total
    current_month = today.strftime('%Y-%m')
    cursor.execute("""
        SELECT COALESCE(SUM(erased), 0)
        FROM daily_stats
        WHERE date LIKE ?
    """, (f"{current_month}%",))
    current_month_total = cursor.fetchone()[0]
    
    # Get previous month total
    from datetime import timedelta
    first_of_month = today.replace(day=1)
    last_month = first_of_month - timedelta(days=1)
    previous_month = last_month.strftime('%Y-%m')
    cursor.execute("""
        SELECT COALESCE(SUM(erased), 0)
        FROM daily_stats
        WHERE date LIKE ?
    """, (f"{previous_month}%",))
    previous_month_total = cursor.fetchone()[0]
    
    # Calculate MoM % change
    mom_change = 0
    if previous_month_total > 0:
        mom_change = round(((current_month_total - previous_month_total) / previous_month_total) * 100, 1)
    
    # Get rolling 7-day average
    cursor.execute("""
        SELECT COALESCE(AVG(erased), 0)
        FROM daily_stats
        WHERE date >= date('now', '-7 days')
    """)
    rolling_7day_avg = round(cursor.fetchone()[0], 1)
    
    # Determine trend indicator
    trend = "→ Stable"
    if wow_change > 5:
        trend = "↑ Improving"
    elif wow_change < -5:
        trend = "↓ Declining"
    
    # Calculate vs target
    vs_target_pct = round((rolling_7day_avg / target) * 100, 1) if target > 0 else 0
    
    conn.close()
    
    return {
        "wowChange": wow_change,
        "momChange": mom_change,
        "rolling7DayAvg": rolling_7day_avg,
        "trend": trend,
        "vsTargetPct": vs_target_pct,
        "currentWeekTotal": current_week_total,
        "previousWeekTotal": previous_week_total,
        "currentMonthTotal": current_month_total,
        "previousMonthTotal": previous_month_total
    }

def get_target_achievement(target: int = 500) -> Dict:
    """Get target achievement metrics: days hitting target, streaks, projections"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    today = date.today()
    current_month = today.strftime('%Y-%m')
    
    # Get all days this month with their totals
    cursor.execute("""
        SELECT date, erased
        FROM daily_stats
        WHERE date LIKE ?
        ORDER BY date
    """, (f"{current_month}%",))
    daily_totals = cursor.fetchall()
    
    # Days hitting target this month
    days_hitting_target = len([d for d in daily_totals if d[1] >= target])
    total_days_this_month = len(daily_totals)
    hit_rate_pct = round((days_hitting_target / total_days_this_month) * 100, 1) if total_days_this_month > 0 else 0
    
    # Calculate current streak
    current_streak = 0
    streak_type = "above"
    for date_str, total in reversed(daily_totals):
        if total >= target:
            current_streak += 1
        else:
            if current_streak == 0:
                # We're in a below-target streak
                streak_type = "below"
                current_streak = 1
            else:
                break
    
    # Get month total and calculate projection
    month_total = sum(d[1] for d in daily_totals)
    days_in_month = (today.replace(month=today.month % 12 + 1, day=1) - timedelta(days=1)).day if today.month < 12 else 31
    current_day = today.day
    
    daily_avg = round(month_total / current_day, 1) if current_day > 0 else 0
    projected_month_total = round(daily_avg * days_in_month)
    
    # Calculate gap to monthly target
    monthly_target = target * days_in_month
    days_remaining = days_in_month - current_day
    gap_to_target = monthly_target - month_total
    daily_needed = round(gap_to_target / days_remaining, 1) if days_remaining > 0 else 0
    
    conn.close()
    
    return {
        "daysHittingTarget": days_hitting_target,
        "totalDaysThisMonth": total_days_this_month,
        "hitRatePct": hit_rate_pct,
        "currentStreak": current_streak,
        "streakType": streak_type,
        "projectedMonthTotal": projected_month_total,
        "monthTotal": month_total,
        "monthlyTarget": monthly_target,
        "gapToTarget": gap_to_target,
        "daysRemaining": days_remaining,
        "dailyNeeded": daily_needed,
        "daysInMonth": days_in_month
    }

# Initialize DB on import
init_db()
