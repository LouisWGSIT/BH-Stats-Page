import sqlite3
import uuid
from pathlib import Path

import database


def test_init_db_and_add_local_erasure(workspace_temp_dir):
    db_file = workspace_temp_dir / f"test_warehouse_{uuid.uuid4().hex}.db"
    # point module to temp db path
    database.DB_PATH = str(db_file)
    # ensure fresh init
    database.init_db()

    # DB file should exist
    assert Path(database.DB_PATH).exists()

    # initially no local_erasures
    conn = sqlite3.connect(database.DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) FROM local_erasures")
    before = cur.fetchone()[0]
    assert before == 0

    # insert a local erasure
    database.add_local_erasure(stockid='S1', system_serial='SER123', job_id='job-1', ts='2026-01-01T00:00:00Z', warehouse='W1', source='test', payload={'k': 'v'})

    cur.execute("SELECT job_id, system_serial, stockid, ts FROM local_erasures WHERE job_id = ?", ('job-1',))
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == 'job-1'
    assert row[1] == 'SER123'
