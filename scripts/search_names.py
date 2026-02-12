"""Search for specific IA personnel names across key QA tables.

Run: python scripts/search_names.py
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import qa_export
from pprint import pprint

NAMES = [
    'Zhilner.Deguilmo',
    'Leah.Haymes',
    'Nathan.Hawkes',
]

QUERIES = [
    ("ITAD_QA_App", "username"),
    ("ITAD_asset_info", "de_completed_by"),
    ("ITAD_asset_info", "de_fault_description"),
    ("audit_master", "user_id"),
    ("audit_master", "log_description"),
    ("ITAD_asset_info_blancco", "serial"),
]

def search_name(conn, name):
    cursor = conn.cursor()
    results = {}
    pattern = f"%{name}%"
    for table, col in QUERIES:
        try:
            query = f"SELECT COUNT(*) FROM `{table}` WHERE {col} LIKE %s"
            cursor.execute(query, (pattern,))
            count = cursor.fetchone()[0] or 0
            samples = []
            if count > 0:
                cursor.execute(f"SELECT * FROM `{table}` WHERE {col} LIKE %s LIMIT 5", (pattern,))
                rows = cursor.fetchall()
                cols = [d[0] for d in cursor.description]
                samples = [dict(zip(cols, r)) for r in rows]
            results[f"{table}.{col}"] = {'count': int(count), 'samples': samples}
        except Exception as e:
            results[f"{table}.{col}"] = {'error': str(e)}
    cursor.close()
    return results

def main():
    conn = qa_export.get_mariadb_connection()
    if not conn:
        print('Could not connect to MariaDB')
        return
    try:
        for name in NAMES:
            print('\n=== Searching for:', name)
            res = search_name(conn, name)
            pprint(res)
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == '__main__':
    main()
