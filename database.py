import sqlite3
from datetime import datetime, date
from typing import List, Dict, Tuple
from pathlib import Path

DB_PATH = Path(__file__).parent / "warehouse_stats.db"

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
    
    conn.commit()
    conn.close()

def get_today_str() -> str:
    """Get today's date as string"""
    return date.today().isoformat()

def get_yesterday_str() -> str:
    """Get yesterday's date as string"""
    from datetime import timedelta
    return (date.today() - timedelta(days=1)).isoformat()

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
