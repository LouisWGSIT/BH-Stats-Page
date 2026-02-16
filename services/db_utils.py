"""MariaDB connection helpers extracted from qa_export.py."""
import os
import time
import logging
from contextlib import contextmanager
import pymysql
import request_context

logger = logging.getLogger("services.db_utils")

# Slow-query alerting removed. Keep threshold var for logs if needed.
DB_QUERY_ALERT_THRESHOLD = float(os.getenv("DB_QUERY_ALERT_THRESHOLD", "2.0"))

# MariaDB Connection Config - read from environment for security
MARIADB_HOST = os.getenv("MARIADB_HOST", "")
MARIADB_USER = os.getenv("MARIADB_USER", "")
MARIADB_PASSWORD = os.getenv("MARIADB_PASSWORD", "")
MARIADB_DB = os.getenv("MARIADB_DB", "")
MARIADB_PORT = int(os.getenv("MARIADB_PORT", "3306"))

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
                    logger.info("DB fetchall (%.3fs) req=%s: rows=%s", duration, rid, count)
                    return rows

                def fetchone(self):
                    start = time.time()
                    row = self._real.fetchone()
                    duration = time.time() - start
                    rid = request_context.request_id.get()
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
