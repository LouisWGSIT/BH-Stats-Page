"""Quick test runner for Bottleneck Radar queries.

Usage:
  - Ensure your virtualenv is active (you already are in this repo).
  - Set MariaDB env vars: MARIADB_HOST, MARIADB_USER, MARIADB_PASSWORD, MARIADB_DB (optional: MARIADB_PORT).
  - Optionally set STATS_DB_PATH to point at the SQLite file (default: warehouse_stats.db).
  - Run: `python scripts/test_bottleneck.py`

This script runs the draft queries in PROJECT_STATUS.md against MariaDB and the local SQLite erasure feed
and prints a compact JSON summary. It's safe to run in staging or locally.
"""
import os
import json
from datetime import datetime, timedelta

from services import db_utils

STATS_DB_PATH = os.getenv('STATS_DB_PATH', 'warehouse_stats.db')

def fmt(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def run_query(query, params=None):
    try:
        rows = db_utils.safe_read(query, params)
        return rows
    except Exception as e:
        return {'error': str(e)}

def run_sqlite_query(sql):
    import sqlite3
    path = STATS_DB_PATH
    if not os.path.exists(path):
        return {'error': f'sqlite file not found: {path}'}
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        return rows
    finally:
        conn.close()

def main():
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=7)
    start_s = fmt(start_dt)
    end_s = fmt(end_dt)

    summary = {'ts': datetime.utcnow().isoformat(), 'window': {'start': start_s, 'end': end_s}}

    # Goods in (Stockbypallet)
    q_goods = """
    SELECT COUNT(DISTINCT pallet_id) FROM Stockbypallet
    WHERE received_date >= %s AND received_date < %s
    """
    summary['goods_in_totes'] = run_query(q_goods, (start_s, end_s))

    # Awaiting erasure
    q_awaiting = """
    SELECT COUNT(*) FROM ITAD_asset_info a
    WHERE (a.warehouse IS NULL OR a.warehouse = 'Berry Hill')
      AND a.stage_current = 'IA'
      AND NOT EXISTS (SELECT 1 FROM ITAD_asset_info_blancco b WHERE b.stockid = a.stockid)
      AND a.sla_complete_date >= %s AND a.sla_complete_date < %s
    """
    summary['awaiting_erasure'] = run_query(q_awaiting, (start_s, end_s))

    # Erased awaiting QA (SQLite local_erasures)
    sql_local = f"SELECT COUNT(DISTINCT stockid) FROM local_erasures WHERE ts >= '{start_s}' AND ts < '{end_s}'"
    summary['erased_awaiting_qa'] = run_sqlite_query(sql_local)

    # QA awaiting sorting
    q_qa_sort = """
    SELECT COUNT(DISTINCT q.stockid) FROM ITAD_QA_App q
    LEFT JOIN Stockbypallet s ON s.stockid = q.stockid
    WHERE (q.warehouse IS NULL OR q.warehouse = 'Berry Hill')
      AND s.stockid IS NULL
      AND q.added_date >= %s AND q.added_date < %s
    """
    summary['qa_awaiting_sorting'] = run_query(q_qa_sort, (start_s, end_s))

    # Sorted count
    q_sorted = "SELECT COUNT(DISTINCT stockid) FROM Stockbypallet WHERE received_date >= %s AND received_date < %s"
    summary['sorted'] = run_query(q_sorted, (start_s, end_s))

    # Disposition breakout
    q_disp = """
    SELECT
      SUM(CASE WHEN a.condition = 'Dest:Refurbishment' THEN 1 ELSE 0 END) AS awaiting_refurb,
      SUM(CASE WHEN a.condition = 'Dest:Breakfix' THEN 1 ELSE 0 END) AS awaiting_breakfix
    FROM ITAD_asset_info a
    WHERE (a.warehouse IS NULL OR a.warehouse = 'Berry Hill')
      AND a.sla_complete_date >= %s AND a.sla_complete_date < %s
    """
    summary['dispositions'] = run_query(q_disp, (start_s, end_s))

    # SLA overdue
    q_sla = """
    SELECT COUNT(*) FROM ITAD_asset_info a
    WHERE (a.warehouse IS NULL OR a.warehouse = 'Berry Hill')
      AND a.sla_complete_date < NOW() - INTERVAL 5 DAY
      AND (a.de_completed_date IS NULL OR a.de_completed_date = '')
    """
    summary['sla_overdue'] = run_query(q_sla)

    print(json.dumps(summary, default=str, indent=2))

if __name__ == '__main__':
    main()
