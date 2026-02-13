#!/usr/bin/env python3
"""Query audit_master for QA submissions by engineers and check pallet/roller in ITAD_asset_info.

Usage: python scripts/find_palletless_in_audit_master.py
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
    start = datetime.date(2026, 2, 12)

    conn = get_mariadb_connection()
    if not conn:
        print("No DB connection available.")
        return
    cur = conn.cursor()

    query = """
SELECT sales_order, user_id, date_time, log_description
FROM audit_master
WHERE user_id IN (%s, %s)
  AND DATE(date_time) = %s
  AND audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload', 'Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload')
ORDER BY date_time DESC
"""

    cur.execute(query, (ENGINEERS[0], ENGINEERS[1], start))
    rows = cur.fetchall()
    print(f"Audit master QA rows for {ENGINEERS} on {start}: {len(rows)}")

    palletless = []
    for sales_order, user_id, date_time, log_description in rows:
        # Skip null/empty sales_order
        if not sales_order:
            continue

        # look up asset info
        acur = conn.cursor()
        acur.execute("SELECT stockid, pallet_id, palletID, roller_location FROM ITAD_asset_info WHERE stockid = %s", (sales_order,))
        arow = acur.fetchone()
        pallet_id = None
        palletID = None
        roller_loc = None
        if arow:
            stockid, pallet_id, palletID, roller_loc = arow

        has_pallet = pallet_present(pallet_id, palletID)
        out = {
            'stockid': sales_order,
            'user': user_id,
            'date_time': date_time,
            'roller_loc': roller_loc,
            'pallet_id': pallet_id,
            'palletID': palletID,
            'has_pallet': has_pallet,
            'log_description': log_description,
        }
        if not has_pallet:
            palletless.append(out)
        acur.close()

    print(f"Palletless audit_master QA rows: {len(palletless)}\n")
    for p in palletless:
        print(p)

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
