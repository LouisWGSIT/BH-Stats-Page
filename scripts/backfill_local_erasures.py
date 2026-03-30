#!/usr/bin/env python3
"""Backfill `local_erasures` from the SQLite `erasures` table.

Usage:
  python scripts/backfill_local_erasures.py --days 7 --limit 1000 [--dry-run]

This script finds recent successful erasures and inserts them into
the `local_erasures` table using the project's `database.add_local_erasure` helper.
"""
from datetime import datetime, timedelta
import argparse
import sqlite3
import json
import os

from database import DB_PATH, add_local_erasure


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7, help="Lookback days for erasures to backfill")
    p.add_argument("--limit", type=int, default=5000, help="Max rows to process")
    p.add_argument("--dry-run", action="store_true", help="Don't write, just report")
    return p.parse_args()


def main():
    args = parse_args()
    now = datetime.utcnow()
    start = (now - timedelta(days=args.days)).isoformat()

    if not os.path.exists(DB_PATH):
        print(f"SQLite DB not found at {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    q = (
        "SELECT id, job_id, system_serial, ts, device_type, initials FROM erasures "
        "WHERE event = 'success' AND ts >= ? ORDER BY ts ASC LIMIT ?"
    )
    cur.execute(q, (start, args.limit))
    rows = cur.fetchall()
    print(f"Found {len(rows)} erasure rows to consider (since {start})")

    inserted = 0
    for r in rows:
        eid, job_id, system_serial, ts, device_type, initials = r
        # Use existing job_id when present; otherwise create a stable backfill id
        jid = job_id if job_id else f"erasures-backfill-{eid}"
        payload = {"source": "erasures", "device_type": device_type, "initials": initials}
        if args.dry_run:
            print(f"DRY: would add job_id={jid} system_serial={system_serial} ts={ts}")
        else:
            try:
                add_local_erasure(stockid=None, system_serial=system_serial, job_id=jid, ts=ts, warehouse=None, source="erasures-backfill", payload=payload)
                inserted += 1
            except Exception as e:
                print(f"Failed to add_local_erasure for id={eid} job_id={jid}: {e}")

    cur.close()
    conn.close()
    print(f"Inserted {inserted} rows into local_erasures (dry_run={args.dry_run})")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
