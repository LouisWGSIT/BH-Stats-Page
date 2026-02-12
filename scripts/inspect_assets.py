"""Inspect assets by stockid across key tables to find where roller/QA/erasure/pallet info is stored.

Usage: python scripts/inspect_assets.py

This script uses the existing `qa_export.get_mariadb_connection()` settings in the repo.
"""
import json
import sys
import os
# Ensure repo root is on sys.path so we can import qa_export
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from qa_export import get_mariadb_connection

STOCKIDS = [
    # awaiting erasure
    '12962041', '12959078', '12961674', '12956106',
    # awaiting qa
    '12958425', '12960356', '12961123',
    # awaiting sorting
    '12960382', '12958672', '12961241'
]


def fetch_rows(conn, query, params):
    cur = conn.cursor()
    try:
        cur.execute(query, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return [dict(zip(cols, row)) for row in rows]
    except Exception as e:
        print(f"Query failed: {e}\nSQL: {query}\nParams: {params}")
        return []
    finally:
        try:
            cur.close()
        except Exception:
            pass


def inspect_stockid(conn, stockid):
    out = {"stockid": stockid}
    tables = [
        'ITAD_asset_info', 'ITAD_asset_info_blancco', 'ITAD_QA_App',
        'ITAD_pallet', 'audit_master', 'Stockbypallet'
    ]

    for table in tables:
        try:
            # Get columns for the table
            cur = conn.cursor()
            cur.execute(f"SHOW COLUMNS FROM {table}")
            cols = [r[0].lower() for r in cur.fetchall()]
            cur.close()
        except Exception:
            out[table] = []
            continue

        # Candidate column names that might contain stock id or order reference
        candidates = [c for c in cols if any(x in c for x in ('stock', 'serial', 'sales_order', 'pallet', 'order'))]
        if not candidates:
            # No obvious match; just return a small sample of rows for inspection
            try:
                out[table] = fetch_rows(conn, f"SELECT * FROM {table} LIMIT 5", ())
            except Exception:
                out[table] = []
            continue

        # Build WHERE clause using available candidate columns
        where_clauses = []
        params = []
        for c in candidates:
            where_clauses.append(f"`{c}` = %s")
            params.append(stockid)

        sql = f"SELECT * FROM {table} WHERE " + ' OR '.join(where_clauses) + " LIMIT 50"
        out[table] = fetch_rows(conn, sql, tuple(params))

    return out


def main():
    conn = get_mariadb_connection()
    if not conn:
        print('Unable to connect to MariaDB. Check qa_export.get_mariadb_connection() settings.')
        return
    result = {}
    for s in STOCKIDS:
        print(f"Inspecting {s}...")
        result[s] = inspect_stockid(conn, s)
    conn.close()
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()
