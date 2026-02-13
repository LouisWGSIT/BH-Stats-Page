#!/usr/bin/env python3
"""ARCHIVE: moved from project root scripts — kept for reference.
Query QA records for specific engineers and show pallet/roller info for a date range.

This file was archived to reduce repository noise. It is not used by the application.
"""
import datetime

from qa_export import get_mariadb_connection

ENGINEERS = [
    'solomon.sony@greensafeit.com',
    'Kieran.Wilson@greensafeit.com',
]


def pallet_present(p1, p2):
    for v in (p1, p2):
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in ('none', 'null', ''):
            return True
    return False


def main():
    # Target date from the user's attachment
    start = datetime.datetime(2026, 2, 12)
    end = start + datetime.timedelta(days=1)

    conn = get_mariadb_connection()
    if not conn:
        print("No DB connection available.")
        return

    cur = conn.cursor()

    query = """
SELECT q.stockid, q.username, q.added_date, ai.pallet_id, ai.palletID, ai.roller_location, am.log_description
FROM ITAD_QA_App q
LEFT JOIN ITAD_asset_info ai ON ai.stockid = q.stockid
LEFT JOIN audit_master am ON am.sales_order = q.stockid
WHERE q.username IN (%s, %s)
  AND q.added_date >= %s AND q.added_date < %s
ORDER BY q.added_date DESC
"""

    cur.execute(query, (ENGINEERS[0], ENGINEERS[1], start, end))
    rows = cur.fetchall()

    print(f"Total QA rows for {ENGINEERS} on {start.date()}: {len(rows)}")

    palletless = []
    for r in rows:
        stockid, username, added_date, pallet_id, palletID, roller_loc, log_description = r
        has_pallet = pallet_present(pallet_id, palletID)
        out = {
            'stockid': stockid,
            'username': username,
            'added_date': added_date,
            'roller_loc': roller_loc,
            'log_description': log_description,
            'pallet_id': pallet_id,
            'palletID': palletID,
            'has_pallet': has_pallet,
        }
        if not has_pallet:
            palletless.append(out)

    print(f"Palletless rows: {len(palletless)}\n")
    for p in palletless:
        print(p)

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
