import sqlite3
from datetime import datetime, date
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
    """Get yesterday's date as string"""
    from datetime import timedelta
    return (date.today() - timedelta(days=1)).isoformat()

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

def get_summary_today_month():
    """Return totals for today and this month, success rate and avg duration (today)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    today = get_today_str()
    month = today[:7]

    cursor.execute("SELECT COUNT(1) FROM erasures WHERE month = ?", (month,))
    month_total = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(1) FROM erasures WHERE date = ?", (today,))
    today_total_all = cursor.fetchone()[0] or 0
    cursor.execute("SELECT COUNT(1) FROM erasures WHERE date = ? AND event = 'success'", (today,))
    today_success = cursor.fetchone()[0] or 0
    cursor.execute("SELECT AVG(duration_sec) FROM erasures WHERE date = ? AND duration_sec IS NOT NULL", (today,))
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

def leaderboard(scope: str = 'today', limit: int = 6):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if scope == 'month':
        key_col = 'month'
        key_val = get_today_str()[:7]
    else:
        key_col = 'date'
        key_val = get_today_str()

    cursor.execute(f"""
        SELECT initials,
               COUNT(1) AS total,
               AVG(duration_sec) AS avg_dur,
               SUM(CASE WHEN event='success' THEN 1 ELSE 0 END) * 1.0 / COUNT(1) * 100.0 AS success_rate
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
            "avgDurationSec": int(r[2]) if r[2] is not None else None,
            "successRate": round(r[3], 1) if r[3] is not None else None,
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

# Initialize DB on import
init_db()
