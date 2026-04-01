import sqlite3
from datetime import datetime, timedelta, UTC
from typing import Callable

from fastapi import APIRouter, HTTPException, Request


def create_admin_activity_router(
    *,
    require_admin: Callable[[Request], None],
    load_device_tokens: Callable[[], dict],
    activity_log,
    get_activity_writer: Callable[[], object | None],
) -> APIRouter:
    router = APIRouter()

    def _recent_from_memory(cutoff: datetime):
        recent = []
        for entry in list(activity_log):
            try:
                ts = datetime.fromisoformat(entry.get("ts")) if isinstance(entry.get("ts"), str) else None
            except Exception:
                ts = None
            if ts and ts >= cutoff:
                recent.append(entry)
        return recent

    @router.get("/admin/activity")
    def admin_activity(request: Request):
        """Return recent dashboard activity for last 24 hours."""
        require_admin(request)
        now = datetime.now(UTC).replace(tzinfo=None)
        cutoff = now - timedelta(hours=24)

        recent = []
        try:
            writer = get_activity_writer()
            if writer:
                conn = sqlite3.connect(writer.db_path, timeout=5, check_same_thread=False)
                cur = conn.cursor()
                cur.execute(
                    "SELECT ts, request_id, path, method, client_ip, duration_ms, rss "
                    "FROM activity WHERE ts >= ? ORDER BY ts DESC LIMIT 500",
                    (cutoff.isoformat(),),
                )
                rows = cur.fetchall()
                for row in rows:
                    recent.append(
                        {
                            "ts": row[0],
                            "request_id": row[1],
                            "path": row[2],
                            "method": row[3],
                            "client_ip": row[4],
                            "duration_ms": row[5],
                            "rss": row[6],
                        }
                    )
                conn.close()
            else:
                recent = _recent_from_memory(cutoff)
        except Exception:
            recent = _recent_from_memory(cutoff)

        exports = [x for x in recent if "/export" in (x.get("path") or "")]
        device_searches = [x for x in recent if "/api/device-lookup" in (x.get("path") or "")]
        fix_initials = [
            x
            for x in recent
            if "/admin/fix-initials" in (x.get("path") or "")
            or "/admin/undo-last-initials" in (x.get("path") or "")
        ]

        memory_samples = [x.get("rss") for x in recent if x.get("rss")]
        memory_peak = max(memory_samples) if memory_samples else None

        tokens = load_device_tokens()
        connected = []
        try:
            for token, info in tokens.items():
                connected.append(
                    {
                        "token": token,
                        "initials": info.get("initials"),
                        "role": info.get("role"),
                        "last_seen": info.get("last_seen"),
                        "last_client_ip": info.get("last_client_ip"),
                        "user_agent": info.get("user_agent"),
                    }
                )
        except Exception:
            connected = []

        recent_sorted = sorted(recent, key=lambda r: r.get("ts", ""), reverse=True)[:500]
        return {
            "now": now.isoformat(),
            "cutoff": cutoff.isoformat(),
            "counts": {
                "total_events": len(recent),
                "exports": len(exports),
                "device_searches": len(device_searches),
                "fix_initials": len(fix_initials),
                "unique_client_ips": len({x.get("client_ip") for x in recent if x.get("client_ip")}),
            },
            "memory_peak_rss": memory_peak,
            "connected_devices": connected,
            "recent": recent_sorted,
        }

    @router.get("/admin/activity/memory-series")
    def admin_activity_memory_series(request: Request, minutes: int = 1440, bucket_seconds: int = 60):
        """Return downsampled RSS memory samples for a lookback period."""
        require_admin(request)
        try:
            now = datetime.now(UTC).replace(tzinfo=None)
            cutoff = now - timedelta(minutes=minutes)
            writer = get_activity_writer()
            rows = []
            if writer:
                conn = sqlite3.connect(writer.db_path, timeout=5, check_same_thread=False)
                cur = conn.cursor()
                cur.execute(
                    "SELECT ts, rss FROM activity WHERE rss IS NOT NULL AND ts >= ? ORDER BY ts ASC",
                    (cutoff.isoformat(),),
                )
                rows = cur.fetchall()
                conn.close()
            else:
                for entry in list(activity_log):
                    try:
                        ts = entry.get("ts")
                        rss = entry.get("rss")
                        if not ts or not rss:
                            continue
                        t = datetime.fromisoformat(ts)
                        if t >= cutoff:
                            rows.append((ts, rss))
                    except Exception:
                        continue

            buckets = {}
            for ts_str, rss in rows:
                try:
                    t = datetime.fromisoformat(ts_str)
                    key = int(t.timestamp()) // bucket_seconds
                    if key not in buckets:
                        buckets[key] = {"sum": 0, "count": 0}
                    buckets[key]["sum"] += int(rss or 0)
                    buckets[key]["count"] += 1
                except Exception:
                    continue

            series = []
            for key in sorted(buckets.keys()):
                bucket = buckets[key]
                avg = int(bucket["sum"] / bucket["count"]) if bucket["count"] else 0
                ts = datetime.fromtimestamp(key * bucket_seconds, UTC).replace(tzinfo=None).isoformat()
                series.append({"ts": ts, "rss": avg})

            return {"series": series, "bucket_seconds": bucket_seconds}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return router
