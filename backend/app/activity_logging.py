from collections import deque
from datetime import datetime, timedelta, UTC
import os
import queue
import sqlite3
import threading


ACTIVITY_EXCLUDE_PREFIXES = [
    '/analytics',
    '/metrics',
    '/competitions',
    '/vendor',
    '/assets',
    '/styles.css',
    '/favicon.ico',
    '/auth/status',
    '/auth',
    '/health',
    '/static',
]

ACTIVITY_EXCLUDE_EXACT = {
    '/admin/activity',
    '/admin/activity/memory-series',
}


def create_activity_log(maxlen: int = 5000):
    return deque(maxlen=maxlen)


def get_process_rss_bytes(psutil_module=None) -> int | None:
    """Best-effort process RSS in bytes, even when psutil is unavailable."""
    try:
        if psutil_module:
            return psutil_module.Process().memory_info().rss
    except Exception:
        pass

    try:
        with open('/proc/self/status', 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except Exception:
        pass

    try:
        import resource

        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return rss * 1024 if rss < (10**10) else rss
    except Exception:
        pass

    return None


def should_record_request(request, exclude_prefixes=None, exclude_exact=None) -> bool:
    """Return True if the request should be recorded in activity log."""
    exclude_prefixes = exclude_prefixes or ACTIVITY_EXCLUDE_PREFIXES
    exclude_exact = exclude_exact or ACTIVITY_EXCLUDE_EXACT

    try:
        path = request.url.path or ''
        method = request.method or 'GET'

        if path in exclude_exact:
            return False

        if '/export' in path or '/api/device-lookup' in path or path.startswith('/admin'):
            return True

        if method != 'GET':
            return True

        for prefix in exclude_prefixes:
            if path.startswith(prefix):
                return False

        return True
    except Exception:
        return True


def record_activity(entry: dict, *, activity_log, get_activity_writer) -> None:
    try:
        entry.setdefault('ts', datetime.now(UTC).replace(tzinfo=None).isoformat())
        activity_log.append(entry)
        try:
            writer = get_activity_writer()
            if writer:
                writer.enqueue(entry)
        except Exception:
            pass
    except Exception:
        pass


class ActivityWriter:
    def __init__(self, db_path: str = 'logs/activity.sqlite', retention_days: int = 7, max_queue: int = 10000):
        self.db_path = db_path
        self.retention_days = retention_days
        self.queue = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        self._ensure_schema()
        self._thread.start()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)

    def _ensure_schema(self):
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT,
                    request_id TEXT,
                    path TEXT,
                    method TEXT,
                    client_ip TEXT,
                    role TEXT,
                    note TEXT,
                    duration_ms INTEGER,
                    rss INTEGER
                )
                '''
            )
            cur.execute('CREATE INDEX IF NOT EXISTS ix_activity_ts ON activity(ts)')
            cur.execute('CREATE INDEX IF NOT EXISTS ix_activity_path ON activity(path)')
            conn.commit()
        finally:
            conn.close()

    def enqueue(self, entry: dict):
        try:
            self.queue.put_nowait(entry)
        except queue.Full:
            pass

    def _flush_batch(self, cur, conn, batch):
        if not batch:
            return []
        for row in batch:
            try:
                cur.execute(
                    'INSERT INTO activity(ts, request_id, path, method, client_ip, role, note, duration_ms, rss) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        row.get('ts'),
                        row.get('request_id'),
                        row.get('path'),
                        row.get('method'),
                        row.get('client_ip'),
                        row.get('role'),
                        row.get('note'),
                        row.get('duration_ms'),
                        row.get('rss'),
                    ),
                )
            except Exception:
                continue
        conn.commit()
        return []

    def _run(self):
        conn = self._get_conn()
        cur = conn.cursor()
        batch = []
        try:
            while not self._stop.is_set():
                try:
                    item = self.queue.get(timeout=1.0)
                except Exception:
                    item = None

                if item is None:
                    batch = self._flush_batch(cur, conn, batch)
                    continue

                batch.append(item)
                if len(batch) >= 20:
                    batch = self._flush_batch(cur, conn, batch)
        finally:
            try:
                self._flush_batch(cur, conn, batch)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2.0)

    def prune_older_than_days(self, days: int):
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cutoff = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)).isoformat()
            cur.execute('DELETE FROM activity WHERE ts < ?', (cutoff,))
            conn.commit()
            conn.close()
        except Exception:
            pass


def start_activity_writer(app, db_path: str):
    try:
        app.state.activity_writer = ActivityWriter(db_path=db_path)
    except Exception:
        app.state.activity_writer = None


def stop_activity_writer(app):
    try:
        writer = getattr(app.state, 'activity_writer', None)
        if writer:
            writer.stop()
    except Exception:
        pass
