"""MariaDB connection helpers extracted from qa_export.py."""
import os
import time
import logging
from contextlib import contextmanager
import pymysql
import backend.request_context as request_context

logger = logging.getLogger("services.db_utils")

# Slow-query alerting removed. Keep threshold var for logs if needed.
DB_QUERY_ALERT_THRESHOLD = float(os.getenv("DB_QUERY_ALERT_THRESHOLD", "2.0"))
DB_LOG_MODE = os.getenv('DB_LOG_MODE', 'minimal')  # 'detailed' or 'minimal'
DB_FETCH_LOG_ROWS = int(os.getenv('DB_FETCH_LOG_ROWS', '5000'))
DB_BATCH_LOG_EVERY = int(os.getenv('DB_BATCH_LOG_EVERY', '10'))

def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def _get_mariadb_config() -> dict:
    # Support both project-specific and platform/common variable names.
    host = _first_env("MARIADB_HOST", "MYSQLHOST", "DB_HOST")
    user = _first_env("MARIADB_USER", "MYSQLUSER", "DB_USER")
    password = _first_env("MARIADB_PASSWORD", "MYSQLPASSWORD", "DB_PASSWORD")
    database = _first_env("MARIADB_DB", "MYSQLDATABASE", "DB_NAME")
    port_raw = _first_env("MARIADB_PORT", "MYSQLPORT", "DB_PORT", default="3306")

    try:
        port = int(port_raw)
    except Exception:
        port = 3306

    return {
        "host": host,
        "user": user,
        "password": password,
        "database": database,
        "port": port,
    }

def get_mariadb_connection():
    """Create and return a MariaDB connection"""
    try:
        cfg = _get_mariadb_config()
        if not cfg["host"] or not cfg["user"] or not cfg["database"]:
            logger.warning(
                "MariaDB config incomplete (host/user/database missing). Falling back to mock-dependent paths."
            )
            return None

        conn = pymysql.connect(
            host=cfg["host"],
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            port=cfg["port"],
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30
        )
        try:
            conn.autocommit(True)
        except Exception:
            try:
                conn.autocommit = True
            except Exception:
                pass

        try:
            orig_cursor = conn.cursor

            class LoggingCursor:
                def __init__(self, real):
                    self._real = real

                def execute(self, query, params=None):
                    start = time.time()
                    try:
                        res = self._real.execute(query, params)
                        duration = time.time() - start
                        try:
                            rowcount = getattr(self._real, 'rowcount', None)
                        except Exception:
                            rowcount = None
                        rid = request_context.request_id.get()
                        if DB_LOG_MODE == 'detailed' or duration >= DB_QUERY_ALERT_THRESHOLD:
                            logger.info("DB execute (%.3fs) req=%s rows=%s: %s", duration, rid, rowcount, (query[:200] + ('...' if len(query) > 200 else '')))
                        return res
                    except Exception as e:
                        duration = time.time() - start
                        rid = request_context.request_id.get()
                        logger.exception("DB execute failed (%.3fs) req=%s: %s -> %s", duration, rid, (query[:200] + ('...' if len(query) > 200 else '')), e)
                        raise

                def executemany(self, query, seq_params):
                    start = time.time()
                    try:
                        res = self._real.executemany(query, seq_params)
                        duration = time.time() - start
                        rid = request_context.request_id.get()
                        if DB_LOG_MODE == 'detailed' or duration >= DB_QUERY_ALERT_THRESHOLD:
                            logger.info("DB executemany (%.3fs) req=%s: %s", duration, rid, (query[:200] + ('...' if len(query) > 200 else '')))
                        return res
                    except Exception as e:
                        duration = time.time() - start
                        rid = request_context.request_id.get()
                        logger.exception("DB executemany failed (%.3fs) req=%s: %s -> %s", duration, rid, (query[:200] + ('...' if len(query) > 200 else '')), e)
                        raise

                def fetchall(self):
                    start = time.time()
                    rows = self._real.fetchall()
                    duration = time.time() - start
                    try:
                        count = len(rows)
                    except Exception:
                        count = None
                    rid = request_context.request_id.get()
                    # In minimal mode, only log slow fetches or very large rowcounts
                    if DB_LOG_MODE == 'detailed' or duration >= DB_QUERY_ALERT_THRESHOLD or (count is not None and count >= DB_FETCH_LOG_ROWS):
                        logger.info("DB fetchall (%.3fs) req=%s: rows=%s", duration, rid, count)
                    else:
                        logger.debug("DB fetchall (%.3fs) req=%s: rows=%s (suppressed)", duration, rid, count)
                    return rows

                def fetchone(self):
                    start = time.time()
                    row = self._real.fetchone()
                    duration = time.time() - start
                    rid = request_context.request_id.get()
                    if DB_LOG_MODE == 'detailed' or duration >= DB_QUERY_ALERT_THRESHOLD:
                        logger.info("DB fetchone (%.3fs) req=%s: returned=%s", duration, rid, 1 if row else 0)
                    return row

                def __getattr__(self, name):
                    return getattr(self._real, name)

            def logging_cursor_factory(*args, **kwargs):
                real = orig_cursor(*args, **kwargs)
                return LoggingCursor(real)

            conn.cursor = logging_cursor_factory
        except Exception:
            logger.debug("Failed to attach LoggingCursor to connection")
        return conn
    except Exception as e:
        logger.exception("MariaDB connection error: %s", e)
        return None


@contextmanager
def mariadb_transaction():
    """Context manager for safe write transactions against MariaDB."""
    conn = get_mariadb_connection()
    if not conn:
        raise RuntimeError("MariaDB connection failed")

    cur = None
    try:
        try:
            conn.autocommit(False)
        except Exception:
            pass
        cur = conn.cursor()
        yield cur
        try:
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def safe_write(query: str, params: tuple = None):
    """Execute a write query safely using the transaction context manager.

    Returns cursor.lastrowid when available.
    """
    with mariadb_transaction() as cur:
        cur.execute(query, params or ())
        try:
            return getattr(cur, 'lastrowid', None)
        except Exception:
            return None


def safe_read(query: str, params: tuple = None):
    """Execute a read-only query with an independent short-lived connection.

    Returns fetched rows as a list of tuples.
    """
    conn = get_mariadb_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        raise


def stream_read(query: str, params: tuple = None, batch_size: int = 1000, log_every: int = None):
    """Stream rows from the database using a server-side cursor.

    Yields lists/tuples of rows in batches using pymysql.cursors.SSCursor where available.
    Logs per-batch progress at most every `log_every` batches (defaults to DB_BATCH_LOG_EVERY).
    """
    try:
        import pymysql.cursors
    except Exception:
        logger.exception("pymysql cursors not available for stream_read")
        # Fallback to safe_read for compatibility
        rows = safe_read(query, params)
        for i in range(0, len(rows), batch_size):
            yield rows[i:i+batch_size]
        return

    if log_every is None:
        log_every = DB_BATCH_LOG_EVERY

    conn = get_mariadb_connection()
    if not conn:
        return

    try:
        # Create server-side cursor
        cur = conn.cursor(pymysql.cursors.SSCursor)
        start_q = time.time()
        cur.execute(query, params or ())
        q_dur = time.time() - start_q
        rid = request_context.request_id.get()
        if DB_LOG_MODE == 'detailed' or q_dur >= DB_QUERY_ALERT_THRESHOLD:
            logger.info("DB stream execute (%.3fs) req=%s", q_dur, rid)

        batch_no = 0
        while True:
            batch_start = time.time()
            rows = cur.fetchmany(batch_size)
            batch_dur = time.time() - batch_start
            if not rows:
                break
            batch_no += 1
            if batch_no % max(1, log_every) == 0 or DB_LOG_MODE == 'detailed':
                try:
                    rss = None
                    if psutil := globals().get('psutil'):
                        rss = psutil.Process().memory_info().rss
                except Exception:
                    rss = None
                logger.info("DB stream batch req=%s batch_no=%d rows=%d dur=%.3fs rss=%s", rid, batch_no, len(rows), batch_dur, rss)
            yield rows
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        raise
