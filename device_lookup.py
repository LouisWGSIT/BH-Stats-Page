"""Device lookup heuristics moved out of `qa_export.py`.

This module provides `get_device_location_hypotheses()` as a focused place
for UI heuristics and lookup helpers.
"""
from datetime import datetime
from typing import List, Dict
import sqlite3

from .qa_export import get_mariadb_connection, _parse_timestamp
from . import db


def get_device_location_hypotheses(stockid: str, top_n: int = 3) -> List[Dict[str, object]]:
    """Return a small ranked list of likely current locations for a device.

    Copied and refactored from the previous implementation in `qa_export.py`.
    """
    conn = get_mariadb_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor()
        # Gather primary asset row
        cur.execute(
            """
            SELECT COALESCE(pallet_id, palletID) as pallet_id, last_update, location, roller_location,
                   de_complete, de_completed_date, stage_current
            FROM ITAD_asset_info
            WHERE stockid = %s OR serialnumber = %s
            LIMIT 1
            """,
            (stockid, stockid)
        )
        asset = cur.fetchone()

        candidates = {}  # location -> {'score': float, 'evidence': []}

        def add_candidate(name: str, score_delta: float, ev: str, ts=None, src_conf: float = 1.0):
            if not name:
                return
            key = str(name).strip()
            entry = candidates.get(key, {'score': 0.0, 'evidence': [], 'last_seen': None})
            multiplier = 1.0
            dt = None
            if ts:
                try:
                    dt = _parse_timestamp(ts)
                    if dt:
                        now_local = datetime.utcnow()
                        try:
                            hours = (now_local - dt).total_seconds() / 3600.0
                        except Exception:
                            hours = None
                        if hours is not None:
                            multiplier = max(0.2, 1.0 - min(hours / 168.0, 0.9))
                        if not entry.get('last_seen') or (dt and dt > entry.get('last_seen')):
                            entry['last_seen'] = dt
                except Exception:
                    dt = None
            try:
                effective = float(score_delta) * float(multiplier) * float(src_conf)
            except Exception:
                effective = float(score_delta)
            entry['score'] += effective
            entry['evidence'].append({
                'source': ev,
                'raw': float(score_delta),
                'multiplier': float(multiplier),
                'src_conf': float(src_conf),
                'effective': float(effective),
            })
            if dt and (not entry.get('last_seen') or dt > entry.get('last_seen')):
                entry['last_seen'] = dt
            candidates[key] = entry

        # From asset_info
        if asset:
            pallet_id, last_update, location, roller_loc, de_complete, de_completed_date, stage_current = asset
            if pallet_id:
                cur.execute("SELECT pallet_location, destination, pallet_status, create_date FROM ITAD_pallet WHERE pallet_id = %s LIMIT 1", (pallet_id,))
                p = cur.fetchone()
                if p:
                    pallet_loc, dest, status, create_date = p
                    add_candidate(f"Pallet {pallet_id} ({pallet_loc or dest or 'unknown'})", 40, f"On pallet {pallet_id}", create_date, src_conf=0.9)
            if location:
                add_candidate(location, 35, "asset_info.location", last_update, src_conf=0.9)
            if roller_loc:
                add_candidate(roller_loc, 35, "asset_info.roller_location", last_update, src_conf=0.9)
            if de_complete and str(de_complete).lower() in ('yes', 'true', '1'):
                add_candidate('Erasure station', 25, 'asset_info.de_complete', de_completed_date, src_conf=0.95)

        # From QA scans
        cur.execute("""
            SELECT scanned_location, MAX(added_date) as last_seen, COUNT(*) as cnt
            FROM ITAD_QA_App
            WHERE stockid = %s
            GROUP BY scanned_location
            ORDER BY last_seen DESC
            LIMIT 10
        """, (stockid,))
        now = datetime.utcnow()
        qa_latest_user = None
        try:
            cur.execute("SELECT username, added_date FROM ITAD_QA_App WHERE stockid = %s ORDER BY added_date DESC LIMIT 1", (stockid,))
            qrow = cur.fetchone()
            if qrow:
                qa_latest_user = qrow[0]
        except Exception:
            qa_latest_user = None

        for loc, last_seen, cnt in cur.fetchall():
            if not loc:
                continue
            last_dt = _parse_timestamp(last_seen)
            hours = None
            if last_dt:
                try:
                    hours = (now - last_dt).total_seconds() / 3600.0
                except Exception:
                    hours = None
            recency_factor = 1.0
            if hours is not None:
                recency_factor = max(0.1, 1.0 - min(hours / 168.0, 0.9))
            base = 40.0 * recency_factor + min(15.0, float(cnt or 0))
            ev = {
                'source': f"QA scans",
                'count': int(cnt or 0),
                'last_seen': last_seen,
                'username': qa_latest_user,
            }
            add_candidate(loc, base, ev, last_seen, src_conf=0.95)

        # From Stockbypallet
        cur.execute("SELECT pallet_id FROM Stockbypallet WHERE stockid = %s LIMIT 1", (stockid,))
        sb = cur.fetchone()
        if sb and sb[0]:
            pid = sb[0]
            cur.execute("SELECT pallet_location, destination FROM ITAD_pallet WHERE pallet_id = %s LIMIT 1", (pid,))
            row = cur.fetchone()
            if row:
                pallet_loc, dest = row
                add_candidate(f"Pallet {pid} ({pallet_loc or dest or 'unknown'})", 20, "Stockbypallet/pallet", None, src_conf=0.9)

        # Blancco evidence
        try:
            try:
                cur.execute(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s AND TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = %s",
                    ("ITAD_asset_info_blancco", "added_date")
                )
                has_added_date = cur.fetchone() is not None
            except Exception:
                has_added_date = False

            if has_added_date:
                has_blancco_user = False
                try:
                    cur.execute(
                        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s AND TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = %s",
                        ("ITAD_asset_info_blancco", "username")
                    )
                    has_blancco_user = cur.fetchone() is not None
                except Exception:
                    has_blancco_user = False

                if has_blancco_user:
                    cur.execute("SELECT id, added_date, username FROM ITAD_asset_info_blancco WHERE stockid = %s ORDER BY added_date DESC LIMIT 1", (stockid,))
                    b = cur.fetchone()
                    if b:
                        _, added_dt, b_user = b
                        ev = {'source': 'ITAD_asset_info_blancco', 'added_date': added_dt, 'username': b_user}
                        add_candidate('Erasure (Blancco)', 30, ev, added_dt, src_conf=1.0)
                else:
                    cur.execute("SELECT id, added_date FROM ITAD_asset_info_blancco WHERE stockid = %s ORDER BY added_date DESC LIMIT 1", (stockid,))
                    b = cur.fetchone()
                    if b:
                        _, added_dt = b
                        ev = {'source': 'ITAD_asset_info_blancco', 'added_date': added_dt}
                        add_candidate('Erasure (Blancco)', 30, ev, added_dt, src_conf=1.0)
            else:
                cur.execute("SELECT id FROM ITAD_asset_info_blancco WHERE stockid = %s LIMIT 1", (stockid,))
                b2 = cur.fetchone()
                if b2:
                    ev = {'source': 'ITAD_asset_info_blancco'}
                    add_candidate('Erasure (Blancco)', 30, ev, None, src_conf=1.0)
        except Exception:
            pass

        # Confirmed locations from local store
        try:
            sqlite_conn = sqlite3.connect(db.DB_PATH)
            sqlite_cur = sqlite_conn.cursor()
            sqlite_cur.execute("""
                SELECT location, user, note, ts
                FROM confirmed_locations
                WHERE stockid = ?
                ORDER BY ts DESC
                LIMIT 1
            """, (stockid,))
            conf = sqlite_cur.fetchone()
            if conf:
                loc, user, note, ts = conf
                add_candidate(f"Confirmed: {loc}", 200, f"user_confirmed ({user})" + (f" - {note}" if note else ''), ts, src_conf=1.0)
            sqlite_cur.close()
            sqlite_conn.close()
        except Exception:
            pass

        cur.close()
        conn.close()

        if not candidates:
            return []

        max_score = max((v['score'] for v in candidates.values()), default=1.0) or 1.0
        out = []
        for loc, info in candidates.items():
            norm = int(round((info['score'] / max_score) * 100))
            evs = info.get('evidence', [])[:8]
            last_seen = info.get('last_seen')

            kind = 'physical'
            try:
                for e in evs:
                    src = e.get('source', '') if isinstance(e, dict) else str(e)
                    s = src.lower()
                    if 'blancco' in s or 'de_complete' in s or 'erasure' in s or s.startswith('asset_info.de_complete'):
                        kind = 'stage'
                        break
            except Exception:
                pass

            out.append({
                'location': loc,
                'score': norm,
                'raw_score': float(info.get('score', 0.0)),
                'evidence': [ (e if isinstance(e, dict) else {'source': e}) for e in evs ],
                'last_seen': last_seen.isoformat() if last_seen else None,
                'type': kind,
            })

        out.sort(key=lambda x: x['score'], reverse=True)
        return out[:top_n]
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        raise
