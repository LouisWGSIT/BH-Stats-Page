#!/usr/bin/env python3
import sys
import json
import mysql.connector

HOST = sys.argv[1]
USER = sys.argv[2]
PASSWORD = sys.argv[3]
DB = sys.argv[4]
PORT = int(sys.argv[5]) if len(sys.argv) > 5 else 3306

def table_columns(conn, table):
    cur = conn.cursor()
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s", (DB, table))
    cols = [r[0].lower() for r in cur.fetchall()]
    cur.close()
    return cols


queries = {
    'stockbypallet': "SELECT stockid, pallet_id FROM Stockbypallet WHERE stockid = %s",
    'pallet_details': "SELECT pallet_id, pallet_location, destination, pallet_status, create_date FROM ITAD_pallet WHERE pallet_id = %s LIMIT 1",
    'asset_info': "SELECT stockid, serialnumber, last_update, location, roller_location, de_complete, de_completed_by FROM ITAD_asset_info WHERE stockid = %s OR serialnumber = %s LIMIT 1",
    'audit': "SELECT date_time, audit_type, user_id, log_description FROM audit_master WHERE log_description LIKE %s OR log_description2 LIKE %s ORDER BY date_time DESC LIMIT 50",
}

stock = sys.argv[6] if len(sys.argv) > 6 else None
if not stock:
    print('Usage: mariadb_readonly_check.py HOST USER PASSWORD DB PORT STOCK')
    sys.exit(1)

out = {}
try:
    conn = mysql.connector.connect(host=HOST, user=USER, password=PASSWORD, database=DB, port=PORT, connection_timeout=10)
    cur = conn.cursor()
    # Probe columns to build robust queries for QA and Blancco
    qa_cols = table_columns(conn, 'ITAD_QA_App')
    bl_cols = table_columns(conn, 'ITAD_asset_info_blancco')

    # Build QA select with available columns
    qa_select_cols = []
    if 'username' in qa_cols:
        qa_select_cols.append('username')
    elif 'user' in qa_cols:
        qa_select_cols.append('user')
    else:
        qa_select_cols.append("'' as username")

    if 'scanned_location' in qa_cols:
        qa_select_cols.append('scanned_location')
    elif 'location' in qa_cols:
        qa_select_cols.append('location as scanned_location')
    else:
        qa_select_cols.append("'' as scanned_location")

    if 'added_date' in qa_cols:
        qa_select_cols.append('added_date')
    elif 'created_at' in qa_cols:
        qa_select_cols.append('created_at as added_date')
    else:
        qa_select_cols.append("NULL as added_date")

    qa_query = f"SELECT {', '.join(qa_select_cols)} FROM ITAD_QA_App WHERE stockid = %s ORDER BY added_date DESC LIMIT 50"
    cur.execute(qa_query, (stock,))
    out['qa_scans'] = [dict(username=r[0], scanned_location=r[1], added_date=str(r[2]) if r[2] else None) for r in cur.fetchall()]
    # stockbypallet
    cur.execute(queries['stockbypallet'], (stock,))
    out['stockbypallet'] = [dict(stockid=r[0], pallet_id=r[1]) for r in cur.fetchall()]
    # pallet details for first pallet if present
    if out['stockbypallet']:
        pid = out['stockbypallet'][0]['pallet_id']
        cur.execute(queries['pallet_details'], (pid,))
        row = cur.fetchone()
        out['pallet_details'] = dict(pallet_id=row[0], pallet_location=row[1], destination=row[2], pallet_status=row[3], create_date=str(row[4]) if row[4] else None) if row else None
    else:
        out['pallet_details'] = None
    # asset_info
    cur.execute(queries['asset_info'], (stock, stock))
    row = cur.fetchone()
    out['asset_info'] = dict(stockid=row[0], serialnumber=row[1], last_update=str(row[2]) if row[2] else None, location=row[3], roller_location=row[4], de_complete=row[5], de_completed_by=row[6]) if row else None
    # blancco (build select based on available columns)
    bl_select = []
    bl_map = [('id','id'), ('stockid','stockid'), ('serial','serial'), ('username','username'), ('added_date','added_date'), ('job_id','job_id'), ('manufacturer','manufacturer'), ('model','model')]
    for col, alias in bl_map:
        if col in bl_cols:
            bl_select.append(f"{col}")
        else:
            bl_select.append(f"NULL as {col}")
    bl_query = f"SELECT {', '.join(bl_select)} FROM ITAD_asset_info_blancco WHERE stockid = %s OR serial = %s ORDER BY added_date DESC LIMIT 20"
    cur.execute(bl_query, (stock, stock))
    out['blancco'] = []
    for r in cur.fetchall():
        out['blancco'].append({
            'id': r[0], 'stockid': r[1], 'serial': r[2], 'username': r[3], 'added_date': str(r[4]) if r[4] else None,
            'job_id': r[5], 'manufacturer': r[6], 'model': r[7]
        })
    # audit
    like = f"%{stock}%"
    cur.execute(queries['audit'], (like, like))
    out['audit'] = [dict(date_time=str(r[0]), audit_type=r[1], user_id=r[2], log_description=r[3]) for r in cur.fetchall()]
    cur.close()
    conn.close()
except mysql.connector.Error as e:
    print(json.dumps({'error':'mysql_error','detail':str(e)}))
    sys.exit(1)
except Exception as e:
    print(json.dumps({'error':'exception','detail':str(e)}))
    sys.exit(1)

print(json.dumps(out, indent=2))
