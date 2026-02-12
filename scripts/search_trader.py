"""Search zaptest_ MariaDB for occurrences of the string 'trader' across key tables.

This is a read-only utility that connects using the existing connection settings
in `qa_export.get_mariadb_connection()` and inspects textual columns in the
specified tables, returning counts and up-to-5 sample rows per match.

Run: python scripts/search_trader.py
"""
from pprint import pprint
import sys, os
# Ensure project root is on sys.path so we can import qa_export
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import qa_export

TABLES_TO_SEARCH = [
    'ITAD_asset_info',
    'ITAD_QA_App',
    'audit_master',
    'ITAD_asset_info_blancco',
]

PATTERN = '%trader%'

def find_text_columns(cursor, table):
    cursor.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
          AND DATA_TYPE IN ('varchar','char','text','mediumtext','longtext')
        """,
        (qa_export.MARIADB_DB, table)
    )
    return [r[0] for r in cursor.fetchall()]

def search_table(conn, table):
    cursor = conn.cursor()
    cols = find_text_columns(cursor, table)
    results = []
    if not cols:
        cursor.close()
        return results

    for col in cols:
        try:
            query = f"SELECT COUNT(*) FROM `{table}` WHERE LOWER(`{col}`) LIKE %s"
            cursor.execute(query, (PATTERN,))
            count = cursor.fetchone()[0] or 0
            if count > 0:
                # fetch a few sample rows (limit 5) including an identifying column if present
                sample_query = f"SELECT * FROM `{table}` WHERE LOWER(`{col}`) LIKE %s LIMIT 5"
                cursor.execute(sample_query, (PATTERN,))
                samples = cursor.fetchall()
                col_names = [d[0] for d in cursor.description]
                results.append({'column': col, 'count': int(count), 'samples': [dict(zip(col_names, s)) for s in samples]})
        except Exception as e:
            results.append({'column': col, 'error': str(e)})

    cursor.close()
    return results

def main():
    conn = qa_export.get_mariadb_connection()
    if not conn:
        print('Could not connect to MariaDB')
        return

    try:
        overall = {}
        for table in TABLES_TO_SEARCH:
            print(f'--- Searching table: {table}')
            res = search_table(conn, table)
            overall[table] = res
            pprint(res)
        print('\nSearch complete. Summary:')
        pprint({k: sum(r['count'] for r in v if 'count' in r) for k, v in overall.items()})
        # Check for NOPOST pallets
        print('\n--- Checking NOPOST pallets in ITAD_asset_info')
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT pallet_id, COUNT(*) FROM ITAD_asset_info WHERE pallet_id IN ('NOPOST01','NOPOST02') GROUP BY pallet_id")
            rows = cursor.fetchall()
            print('Counts by pallet_id:')
            pprint(rows)
            cursor.execute("SELECT stockid, serialnumber, roller_location, last_update, de_complete, pallet_id, description FROM ITAD_asset_info WHERE pallet_id IN ('NOPOST01','NOPOST02') LIMIT 10")
            samples = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            print('Sample rows:')
            pprint([dict(zip(cols, r)) for r in samples])
        finally:
            try:
                cursor.close()
            except Exception:
                pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == '__main__':
    main()
