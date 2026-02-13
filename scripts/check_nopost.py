"""Check for NOPOST pallet assignments in ITAD_asset_info.

Run: python scripts/check_nopost.py
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import qa_export
from pprint import pprint

def main():
    conn = qa_export.get_mariadb_connection()
    if not conn:
        print('Could not connect to MariaDB')
        return
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT pallet_id, COUNT(*) FROM ITAD_asset_info WHERE pallet_id IN ('NOPOST01','NOPOST02') GROUP BY pallet_id")
        counts = cursor.fetchall()
        print('NOPOST counts:')
        pprint(counts)

        cursor.execute("SELECT COUNT(*) FROM ITAD_asset_info WHERE pallet_id LIKE 'NOPOST%%'")
        total_nopost = cursor.fetchone()[0]
        print('Total NOPOST* rows:', total_nopost)

        cursor.execute("SELECT stockid, serialnumber, roller_location, last_update, de_complete, pallet_id, description FROM ITAD_asset_info WHERE pallet_id LIKE 'NOPOST%%' LIMIT 20")
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        print('Sample NOPOST rows:')
        pprint([dict(zip(cols, r)) for r in rows])
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

if __name__ == '__main__':
    main()
