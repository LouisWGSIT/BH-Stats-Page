"""Find where 'Trader' and related device metadata (location, last_user, condition)
appear in the zaptest_ schema and emit sample rows for investigation.

Run: python scripts/find_trader_locations.py
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import qa_export
from pprint import pprint


def column_exists(cursor, table, column):
    cursor.execute(
        """
        SELECT COUNT(1) FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (qa_export.MARIADB_DB, table, column)
    )
    return cursor.fetchone()[0] > 0


def inspect_trader_columns(conn):
    cursor = conn.cursor()
    tables = ['ITAD_asset_info', 'ITAD_pallet', 'ITAD_QA_App', 'audit_master']
    results = {}
    try:
        for t in tables:
            cols = []
            try:
                cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (qa_export.MARIADB_DB, t))
                cols = [r[0] for r in cursor.fetchall()]
            except Exception as e:
                results[t] = {'error': str(e)}
                continue

            has_trader = any(c.lower() == 'trader' for c in cols)
            results[t] = {'columns': cols, 'has_trader': has_trader}

            # If there's a trader column, fetch non-empty values
            if has_trader:
                try:
                    cursor.execute(f"SELECT `{ 'stockid' if 'stockid' in cols else cols[0] }`, trader, location, last_user, `condition`, cond, roller_location, pallet_id FROM `{t}` WHERE trader IS NOT NULL AND trader <> '' LIMIT 20")
                    rows = cursor.fetchall()
                    cols_out = [d[0] for d in cursor.description]
                    results[t]['sample_trader_rows'] = [dict(zip(cols_out, r)) for r in rows]
                except Exception as e:
                    results[t]['sample_error'] = str(e)

        return results
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def search_text_for_trader(conn):
    cursor = conn.cursor()
    PAT = '%trader%'
    tables = ['ITAD_asset_info', 'ITAD_QA_App', 'audit_master', 'ITAD_asset_info_blancco']
    out = {}
    try:
        for t in tables:
            out[t] = []
            # find text columns
            cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND DATA_TYPE IN ('varchar','char','text','mediumtext','longtext')", (qa_export.MARIADB_DB, t))
            cols = [r[0] for r in cursor.fetchall()]
            for col in cols:
                try:
                    cursor.execute(f"SELECT COUNT(1) FROM `{t}` WHERE LOWER(`{col}`) LIKE %s", (PAT,))
                    cnt = cursor.fetchone()[0]
                    if cnt and cnt > 0:
                        cursor.execute(f"SELECT * FROM `{t}` WHERE LOWER(`{col}`) LIKE %s LIMIT 5", (PAT,))
                        rows = cursor.fetchall()
                        cols_out = [d[0] for d in cursor.description]
                        out[t].append({'column': col, 'count': int(cnt), 'samples': [dict(zip(cols_out, r)) for r in rows]})
                except Exception as e:
                    out[t].append({'column': col, 'error': str(e)})
        return out
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def sample_last_user_location(conn, limit=50):
    cursor = conn.cursor()
    try:
        # Try common column names: last_user, lastupdate, location, cond/condition, roller_location, pallet_id
        query = """
        SELECT stockid, serialnumber, COALESCE(location, '') as location, COALESCE(last_user, '') as last_user,
               COALESCE(`condition`, cond, '') as cond, COALESCE(roller_location, '') as roller_location,
               COALESCE(pallet_id, palletID) as pallet_id, last_update, de_complete
        FROM ITAD_asset_info
        ORDER BY last_update DESC
        LIMIT %s
        """
        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def main():
    conn = qa_export.get_mariadb_connection()
    if not conn:
        print('Could not connect to MariaDB')
        return

    try:
        print('Inspecting schema for trader columns...')
        schema_info = inspect_trader_columns(conn)
        pprint(schema_info)

        print('\nSearching common text fields for the string "trader"...')
        text_hits = search_text_for_trader(conn)
        pprint(text_hits)

        print('\nSample recent rows showing last_user, location, cond, roller_location...')
        samples = sample_last_user_location(conn, limit=100)
        pprint(samples[:20])

    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
