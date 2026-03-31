import os
import sys
import sqlite3
import uuid
from pathlib import Path
import importlib


def _reload_app_with_env(env: dict, tmp_db_path: Path):
    # Ensure environment and module reload so main picks up DB_PATH and INGESTION_KEY
    for k, v in env.items():
        os.environ[k] = v

    # Ensure database module uses the tmp DB
    if 'database' in sys.modules:
        del sys.modules['database']
    if 'main' in sys.modules:
        del sys.modules['main']

    import database as database_mod
    database_mod.DB_PATH = str(tmp_db_path)
    # import main after setting env
    import main
    importlib.reload(main)
    return main


def test_ingest_local_endpoint(workspace_temp_dir):
    tmp_db = workspace_temp_dir / f"ingest_test_{uuid.uuid4().hex}.db"
    env = {
        'STATS_DB_PATH': str(tmp_db),
        'INGESTION_KEY': 'testkey123'
    }
    main = _reload_app_with_env(env, tmp_db)

    from fastapi.testclient import TestClient
    client = TestClient(main.app)

    body = {
        'system_serial': 'TSERIAL001',
        'job_id': 'test-job-42',
        'ts': '2026-03-30T00:00:00Z',
        'warehouse': 'local-test',
        'source': 'pytest',
        'payload': {'test': True}
    }

    headers = {'Authorization': 'Bearer testkey123'}
    resp = client.post('/api/ingest/local-erasure', headers=headers, json=body)
    assert resp.status_code == 200
    js = resp.json()
    assert js.get('ok') is True

    # Verify written to sqlite
    conn = sqlite3.connect(str(tmp_db))
    cur = conn.cursor()
    cur.execute("SELECT job_id, system_serial FROM local_erasures WHERE job_id = ?", ('test-job-42',))
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 'test-job-42'
