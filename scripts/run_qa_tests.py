from __future__ import annotations
import json
import os
import sys
from pprint import pprint

# Ensure project root is on sys.path so imports from project root work when
# executing this script from the `scripts/` folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    from qa_export import get_unpalleted_summary, get_roller_queue_status, get_unpalleted_devices
    from qa_export import get_mariadb_connection
except Exception as e:
    print('ERROR importing qa_export:', e)
    raise

TARGET_STOCKS = {"12960382", "12958672", "12961241", "12956106"}

def as_list(obj):
    if obj is None:
        return []
    try:
        return list(obj)
    except Exception:
        return [obj]

def find_targets(rows):
    found = []
    for r in as_list(rows):
        # try common shapes: dict with 'stockid', tuple/list with first element
        sid = None
        if isinstance(r, dict):
            sid = str(r.get('stockid') or r.get('StockID') or r.get('stock_id') or r.get('stock'))
        elif isinstance(r, (list, tuple)) and len(r) > 0:
            sid = str(r[0])
        else:
            sid = str(r)
        if sid in TARGET_STOCKS:
            found.append(r)
    return found

def main():
    print('Running get_unpalleted_summary(destination=None, days_threshold=30)')
    up_summary = get_unpalleted_summary(None, 30)
    print('unpal_count=', up_summary.get('total_unpalleted', 0))
    
    # Check our target stock IDs directly
    print('\nChecking target stock IDs individually:')
    conn = get_mariadb_connection()
    if conn:
        cursor = conn.cursor()
        for sid in sorted(TARGET_STOCKS):
            # Check if it meets unpalleted criteria
            cursor.execute('''
                SELECT COUNT(*) FROM (
                    SELECT stockid FROM ITAD_asset_info
                    UNION
                    SELECT stockid FROM ITAD_asset_info_blancco
                    UNION
                    SELECT stockid FROM Stockbypallet
                    UNION
                    SELECT sales_order AS stockid FROM audit_master WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload') AND sales_order IS NOT NULL
                ) src
                LEFT JOIN ITAD_asset_info a ON a.stockid = src.stockid
                LEFT JOIN Stockbypallet sb ON sb.stockid = src.stockid
                LEFT JOIN (
                    SELECT stockid, COUNT(*) AS blancco_count
                    FROM ITAD_asset_info_blancco
                    GROUP BY stockid
                ) b ON b.stockid = src.stockid
                WHERE src.stockid = %s
                AND (
                    a.stockid IS NULL
                    OR (
                        (a.pallet_id IS NULL OR a.pallet_id = '' OR a.palletID IS NULL OR a.palletID = '' OR COALESCE(a.pallet_id, a.palletID) LIKE 'NOPOST%%')
                        AND a.condition NOT IN ('Disposed', 'Shipped', 'Sold')
                    )
                )
                AND (
                    LOWER(COALESCE(a.de_complete, '')) IN ('yes','true','1')
                    OR LOWER(COALESCE(sb.de_complete, '')) IN ('yes','true','1')
                    OR COALESCE(b.blancco_count, 0) > 0
                    OR EXISTS (
                        SELECT 1 FROM audit_master am
                        WHERE am.sales_order = src.stockid
                          AND am.audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload')
                    )
                    OR (a.last_update IS NOT NULL AND a.last_update >= DATE_SUB(NOW(), INTERVAL 30 DAY))
                )
            ''', (sid,))
            count = cursor.fetchone()[0]
            print(f'{sid}: {"YES" if count > 0 else "NO"} (qualifies for unpalleted)')
        cursor.close()
        conn.close()
    
    found_up = []  # Not checking device list anymore
    print('found_in_unpalleted: N/A (checked individually above)')
    pprint(found_up)

    print('\nRunning get_roller_queue_status(days_threshold=30)')
    roller_summary = get_roller_queue_status(30)
    print('roller_count=', roller_summary.get('totals', {}).get('total', 0))
    
    # Extract stock IDs from roller samples
    roller_devices = []
    for roller in roller_summary.get('rollers', []):
        roller_devices.extend(roller.get('samples', []))
    print('roller devices count=', len(roller_devices))
    try:
        stockids = [str(d.get('stockid', '')) for d in roller_devices if d.get('stockid')]
        print('roller stockids:', stockids[:50])
    except Exception as e:
        print('Error extracting roller stockids:', e)
        print('roller sample:', roller_devices[:10])
    found_r = find_targets(roller_devices)
    print('found_in_roller:', len(found_r))
    pprint(found_r)

    print('\nChecking authoritative signals for target stock IDs...')
    conn = get_mariadb_connection()
    if not conn:
        print('No DB connection available')
        return
    cursor = conn.cursor()
    for sid in sorted(TARGET_STOCKS):
        print(f'\n== {sid} ==')
        cursor.execute('SELECT stockid, de_complete, de_completed_date, pallet_id, palletID, last_update FROM ITAD_asset_info WHERE stockid = %s', (sid,))
        rows = cursor.fetchall()
        print('ITAD_asset_info:', rows)

        # Inspect blancco table columns then fetch rows
        try:
            cursor.execute('SHOW COLUMNS FROM ITAD_asset_info_blancco')
            print('ITAD_asset_info_blancco columns:', cursor.fetchall())
        except Exception as e:
            print('Error showing blancco columns:', e)
        try:
            cursor.execute('SELECT * FROM ITAD_asset_info_blancco WHERE stockid = %s LIMIT 10', (sid,))
            print('ITAD_asset_info_blancco rows:', cursor.fetchall())
        except Exception as e:
            print('Error selecting blancco rows:', e)

        cursor.execute('SELECT stockid, de_complete, pallet_id FROM Stockbypallet WHERE stockid = %s', (sid,))
        print('Stockbypallet:', cursor.fetchall())

        try:
            cursor.execute('SHOW COLUMNS FROM audit_master')
            print('audit_master columns:', cursor.fetchall())
        except Exception as e:
            print('Error showing audit_master columns:', e)
        try:
            cursor.execute("SELECT id, audit_type, date_time, user_id FROM audit_master WHERE audit_type LIKE %s ORDER BY date_time DESC LIMIT 10", ('%DEAPP_Submission%',))
            print('audit_master (DEAPP_SUBMISSION recent):', cursor.fetchall())
        except Exception as e:
            print('Error selecting from audit_master by type:', e)

if __name__ == '__main__':
    main()
