import asyncio
import os
from collections import OrderedDict
from datetime import datetime, timedelta
from time import time


class TTLCache:
    def __init__(self, maxsize: int = 256, ttl: float = 60.0):
        import threading

        self.maxsize = maxsize
        self.ttl = ttl
        self._store = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key, default=None):
        now = time()
        with self._lock:
            item = self._store.get(key)
            if not item:
                return default
            value, ts = item
            if now - ts > self.ttl:
                try:
                    del self._store[key]
                except Exception:
                    pass
                return default
            try:
                self._store.move_to_end(key)
            except Exception:
                pass
            return value

    def set(self, key, value):
        now = time()
        with self._lock:
            if key in self._store:
                try:
                    del self._store[key]
                except Exception:
                    pass
            self._store[key] = (value, now)
            try:
                while len(self._store) > self.maxsize:
                    self._store.popitem(last=False)
            except Exception:
                pass

    def clear(self):
        with self._lock:
            self._store.clear()


async def warm_cache_on_startup(*, db_module, qa_export_module, cache_set):
    try:
        await asyncio.sleep(1)
        try:
            data = db_module.get_daily_stats()
            cache_set("/metrics/today", data)
        except Exception:
            pass
        try:
            data = db_module.get_monthly_momentum()
            cache_set("/metrics/monthly-momentum", data)
        except Exception:
            pass
        try:
            if hasattr(db_module, "get_summary"):
                data = db_module.get_summary()
                cache_set("/metrics/summary", data)
        except Exception:
            pass
        try:
            if hasattr(qa_export_module, "get_qa_daily_totals_range"):
                end = datetime.now().date()
                start = end - timedelta(days=7)
                qa_data = qa_export_module.get_qa_daily_totals_range(start, end)
                cache_set("/api/insights/qa", {"data": qa_data})
        except Exception:
            pass
    except Exception:
        pass


async def memory_watchdog(*, psutil_module, cache_clear, take_tracemalloc_snapshot):
    try:
        if psutil_module is None:
            return
        try:
            limit = int(os.getenv("MEMORY_LIMIT_BYTES", str(512 * 1024 * 1024)))
        except Exception:
            limit = 512 * 1024 * 1024
        threshold = int(limit * 0.85)
        while True:
            try:
                rss = psutil_module.Process().memory_info().rss
                if rss and rss >= threshold:
                    try:
                        cache_clear()
                    except Exception:
                        pass
                    try:
                        take_tracemalloc_snapshot(reason="memory_watchdog", meta={"rss": rss})
                    except Exception:
                        pass
                await asyncio.sleep(30)
            except Exception:
                await asyncio.sleep(30)
    except Exception:
        return


async def check_daily_reset():
    while True:
        now = datetime.now()
        if now.hour == 18 and now.minute == 0:
            print(f"[{now}] Daily reset triggered at 18:00")
            try:
                pass
            except Exception as e:
                print(f"Error during daily reset: {e}")
            await asyncio.sleep(3600)
        else:
            await asyncio.sleep(60)


def sync_engineer_stats_on_startup(*, db_module):
    print("[Startup] Syncing engineer stats from erasures table...")
    try:
        synced = db_module.sync_engineer_stats_from_erasures()
        print(f"[Startup] Engineer stats sync complete: {synced} records")
    except Exception as e:
        print(f"[Startup] Error syncing engineer stats: {e}")

    try:
        synced_type = db_module.sync_engineer_stats_type_from_erasures()
        print(f"[Startup] Engineer stats by device type sync complete: {synced_type} records")
    except Exception as e:
        print(f"[Startup] Error syncing engineer stats by device type: {e}")


async def refresh_qa_snapshots_periodically(*, refresh_snapshots_func, interval_seconds: int = 120):
    """Periodically refresh QA dashboard snapshots to keep request path lightweight."""
    interval = max(30, int(interval_seconds or 120))
    await asyncio.sleep(5)
    while True:
        try:
            await refresh_snapshots_func()
        except Exception:
            pass
        await asyncio.sleep(interval)
