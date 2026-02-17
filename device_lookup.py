"""Device lookup heuristics moved out of `qa_export.py`.

This module provides `get_device_location_hypotheses()` as a focused place
for UI heuristics and lookup helpers.
"""
from datetime import datetime
import os
from typing import List, Dict
import sqlite3
import re

# Robust imports: prefer absolute imports when module is executed as top-level
try:
    import qa_export as _qa_export_mod
    get_mariadb_connection = _qa_export_mod.get_mariadb_connection
    _parse_timestamp = _qa_export_mod._parse_timestamp
except Exception:
    try:
        from .qa_export import get_mariadb_connection, _parse_timestamp
    except Exception:
        # Leave placeholders; callers should handle None
        get_mariadb_connection = None
        _parse_timestamp = None

# Import local SQLite helpers (module is `database.py` in this repo)
try:
    import database as db
except Exception:
    try:
        from . import database as db
    except Exception:
        db = None


def get_device_location_hypotheses(stockid: str, top_n: int = 3) -> List[Dict[str, object]]:
    """Return a small ranked list of likely current locations for a device.

    Copied and refactored from the previous implementation in `qa_export.py`.
    """
    conn = get_mariadb_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor()
        # Canonicalize input: if a serial was provided, try resolving a stockid so
        # subsequent queries (which generally key by stockid) find the same device
        # regardless of which identifier the caller passed.
        try:
            resolved = None
            try:
                cur.execute("SELECT stockid FROM ITAD_asset_info WHERE stockid = %s OR serialnumber = %s LIMIT 1", (stockid, stockid))
                r = cur.fetchone()
                if r and r[0]:
                    resolved = r[0]
            except Exception:
                resolved = None

            if not resolved:
                try:
                    cur.execute("SELECT stockid FROM ITAD_asset_info_blancco WHERE stockid = %s OR serial = %s LIMIT 1", (stockid, stockid))
                    r = cur.fetchone()
                    if r and r[0]:
                        resolved = r[0]
                except Exception:
                    resolved = None

            if resolved:
                # overwrite local variable so remaining queries use the canonical id
                stockid = resolved
        except Exception:
            # best-effort only; if canonicalization fails, continue with original input
            pass

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
            # Clamp individual candidate deltas and the running total to sane limits
            try:
                MAX_DELTA = float(os.getenv('CANDIDATE_MAX_DELTA', '100.0'))
                MAX_TOTAL = float(os.getenv('CANDIDATE_MAX_TOTAL', '1000.0'))
            except Exception:
                MAX_DELTA = 100.0
                MAX_TOTAL = 1000.0
            # clamp the effective delta
            if effective > MAX_DELTA:
                effective = MAX_DELTA
            elif effective < -MAX_DELTA:
                effective = -MAX_DELTA

            entry['score'] = float(entry.get('score', 0.0)) + float(effective)
            # clamp running total
            if entry['score'] > MAX_TOTAL:
                entry['score'] = MAX_TOTAL
            if entry['score'] < -MAX_TOTAL:
                entry['score'] = -MAX_TOTAL

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
            # `de_complete` in `ITAD_asset_info` represents a QA-related flag in
            # this environment (not a separate erasure location). Do NOT create a
            # separate 'Erasure station' candidate from it to avoid duplicate
            # locations — QA evidence will be gathered from `ITAD_QA_App` and
            # `audit_master` instead.

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
        qa_latest_location = None
        qa_latest_ts = None
        try:
            # capture the latest QA row including scanned_location so we can prefer
            # the exact place the latest QA user scanned this device
            cur.execute("SELECT username, scanned_location, added_date FROM ITAD_QA_App WHERE stockid = %s ORDER BY added_date DESC LIMIT 1", (stockid,))
            qrow = cur.fetchone()
            if qrow:
                qa_latest_user = qrow[0]
                qa_latest_location = qrow[1]
                qa_latest_ts = qrow[2]
        except Exception:
            qa_latest_user = None
            qa_latest_location = None
            qa_latest_ts = None

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
            # increase QA base weight so recent QA scans more strongly influence hypotheses
            base = 50.0 * recency_factor + min(20.0, float(cnt or 0))
            ev = {
                'source': f"QA scans",
                'count': int(cnt or 0),
                'last_seen': last_seen,
                'username': qa_latest_user,
            }
            add_candidate(loc, base, ev, last_seen, src_conf=1.0)

        # If we have a latest QA row for this exact stock, prefer the exact scanned_location
        # from that latest QA by adding a strong candidate tied to that user's scan.
        try:
            if qa_latest_location:
                ev2 = {'source': 'QA_latest', 'username': qa_latest_user, 'last_seen': qa_latest_ts}
                # strong boost to ensure the technician's scan location is favored when present
                add_candidate(qa_latest_location, 80, ev2, qa_latest_ts, src_conf=1.0)
        except Exception:
            pass

        # Check audit_master for a recent QA submission/user; if found, try to map that
        # user to their most-recent QA scanned_location and add as a candidate. This lets
        # 'last known user' from audit_master influence the hypotheses.
        try:
            try:
                cur.execute(
                    """
                    SELECT date_time, audit_type, user_id, log_description
                    FROM audit_master
                    WHERE audit_type IN ('DEAPP_Submission', 'DEAPP_Submission_EditStock_Payload',
                                         'Non_DEAPP_Submission', 'Non_DEAPP_Submission_EditStock_Payload')
                      AND (log_description LIKE %s OR log_description2 LIKE %s)
                    ORDER BY date_time DESC
                    LIMIT 1
                    """,
                    (f"%{stockid}%", f"%{stockid}%"),
                )
                ar = cur.fetchone()
            except Exception:
                ar = None

            if ar:
                am_dt, am_type, am_user, am_log = ar
                # Try to find the most-recent scanned_location for this user in ITAD_QA_App
                try:
                    cur.execute(
                        "SELECT scanned_location, MAX(added_date) as last_seen FROM ITAD_QA_App WHERE username = %s GROUP BY scanned_location ORDER BY last_seen DESC LIMIT 1",
                        (am_user,)
                    )
                    urow = cur.fetchone()
                except Exception:
                    urow = None

                if urow and urow[0]:
                    user_loc, user_loc_last = urow[0], urow[1]
                    ev3 = {'source': 'audit_master.user', 'username': am_user, 'log': am_log}
                    # add a meaningful boost but allow recency logic to refine ordering
                    add_candidate(user_loc, 70, ev3, user_loc_last or am_dt, src_conf=0.95)
                else:
                    # If we have no QA-scanned_location for the user, still add a named
                    # candidate that indicates the device was handled by this user.
                    user_label = f"QA Data Bearing (by {am_user})"
                    ev4 = {'source': 'audit_master.user', 'username': am_user, 'log': am_log}
                    add_candidate(user_label, 60, ev4, am_dt, src_conf=0.9)
        except Exception:
            pass

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

            # Co-location / temporal correlation heuristic (conservative)
            try:
                # Find other devices on the same pallet (limit to reasonable number)
                cur.execute("SELECT stockid FROM Stockbypallet WHERE pallet_id = %s AND stockid <> %s LIMIT 20", (pid, stockid))
                neighbors = [r[0] for r in cur.fetchall() if r and r[0]]
                if neighbors:
                    loc_counts = {}
                    blancco_count = 0
                    checked = 0
                    for n in neighbors:
                        if checked >= 20:
                            break
                        checked += 1
                        # try last asset_info location
                        try:
                            cur.execute("SELECT location, roller_location FROM ITAD_asset_info WHERE stockid = %s LIMIT 1", (n,))
                            arow = cur.fetchone()
                            if arow:
                                for v in (arow[0], arow[1]):
                                    if v:
                                        loc_counts[v] = loc_counts.get(v, 0) + 1
                        except Exception:
                            pass
                        # try QA latest scanned_location
                        try:
                            cur.execute("SELECT scanned_location FROM ITAD_QA_App WHERE stockid = %s ORDER BY added_date DESC LIMIT 1", (n,))
                            q = cur.fetchone()
                            if q and q[0]:
                                loc_counts[q[0]] = loc_counts.get(q[0], 0) + 1
                        except Exception:
                            pass
                        # check blancco presence
                        try:
                            cur.execute("SELECT 1 FROM ITAD_asset_info_blancco WHERE stockid = %s LIMIT 1", (n,))
                            if cur.fetchone():
                                blancco_count += 1
                        except Exception:
                            pass

                    # If a location appears in at least 2 neighbors, add a small inferred boost
                    for loc_name, cnt in loc_counts.items():
                        if cnt >= 2:
                            ev = {'source': 'co_location_inferred', 'count': cnt, 'pallet_id': pid}
                            # small boost and lower source confidence
                            add_candidate(f"Inferred: {loc_name} (from {cnt} co-located devices)", 8, ev, None, src_conf=0.6)

                    # If several neighbors show blancco, slightly boost erasure hypothesis
                    try:
                        if blancco_count >= 3:
                            add_candidate('Erasure (inferred from neighbors)', 6, {'source': 'co_location_blancco', 'count': blancco_count}, None, src_conf=0.6)
                    except Exception:
                        pass
            except Exception:
                pass

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

                # NOTE: In this deployment Blancco rows in MariaDB are a copy
                # of the server-side erasure messages and are not the canonical
                # source of truth for erasure events. True erasure events arrive
                # as server messages and are stored locally in SQLite (`erasures`).
                # Therefore, DO NOT create an 'Erasure station' candidate from
                # `ITAD_asset_info_blancco` to avoid elevating DB-copied Blancco
                # rows above QA evidence. We still probe `ITAD_asset_info_blancco`
                # for provenance to attach to timeline events, but hypotheses and
                # candidates should be driven by local erasure records (SQLite)
                # and QA scans in `ITAD_QA_App` / `audit_master`.
                pass
            else:
                # If the Blancco table lacks an explicit timestamp column we
                # may still find a row, but we deliberately do NOT convert
                # this into an 'Erasure station' candidate. Local server
                # messages (SQLite `erasures`) are the authoritative erasure
                # source and should drive any erasure hypothesis.
                cur.execute("SELECT id FROM ITAD_asset_info_blancco WHERE stockid = %s LIMIT 1", (stockid,))
                b2 = cur.fetchone()
                if b2:
                    # Attach no candidate; leave as provenance-only
                    pass
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

        # Helpers to render human-friendly explanation text for each candidate.
        def _source_name(s):
            try:
                if isinstance(s, dict):
                    return s.get('source') or s.get('type') or str(s)
                return str(s)
            except Exception:
                return str(s)

        def _format_ev(ev_item):
            # ev_item is the wrapped evidence we stored in add_candidate
            src = ev_item.get('source')
            # If the original source was a dict, try to extract more fields
            if isinstance(src, dict):
                sname = src.get('source') or src.get('type') or 'evidence'
                # QA scans
                if sname.lower().startswith('qa') or 'qa' in sname.lower():
                    cnt = src.get('count') or src.get('cnt')
                    last = src.get('last_seen') or src.get('last')
                    user = src.get('username')
                    parts = [sname]
                    if cnt is not None:
                        parts.append(f"({int(cnt)})")
                    if last:
                        parts.append(f"last seen {last}")
                    if user:
                        parts.append(f"by {user}")
                    return ' '.join(parts)
                # Blancco / erasure
                if 'blancco' in sname.lower() or 'erasure' in sname.lower():
                    ad = src.get('added_date') or src.get('added')
                    user = src.get('username')
                    parts = [sname]
                    if ad:
                        parts.append(f"on {ad}")
                    if user:
                        parts.append(f"by {user}")
                    return ' '.join(parts)
                # confirmed_locations record
                if sname.lower().startswith('user_confirmed') or sname.lower().startswith('confirmed'):
                    # the original add_candidate passed a string like 'user_confirmed (bob) - note'
                    return sname
                # generic dict
                # try to pretty-print keys like location/timestamp
                if 'location' in src:
                    return f"{sname}: {src.get('location')}"
                return sname

            # If source was stored as a plain string
            try:
                s = str(src)
                return s
            except Exception:
                return 'evidence'

        def _is_stage(evs):
            try:
                for e in evs:
                    src = e.get('source') if isinstance(e, dict) else e
                    s = ''
                    if isinstance(src, dict):
                        s = (src.get('source') or '')
                    else:
                        s = str(src)
                    s = s.lower()
                    if 'blancco' in s or 'erasure' in s or 'erasure station' in s:
                        return True
            except Exception:
                pass
            return False

        # Apply a conservative recency-priority boost so the most-recent activity
        # is favored for the majority of lookups. Configurable via environment:
        # RECENCY_PRIORITY_HOURS (window) and RECENCY_PRIORITY_BOOST_MAX (max points).
        try:
            # Make recency the dominant signal by default: prefer events within
            # the last week and allow a larger boost so the most-recent item
            # typically outranks other signals.
            RECENCY_PRIORITY_HOURS = float(os.getenv('RECENCY_PRIORITY_HOURS', '168'))
            RECENCY_PRIORITY_BOOST_MAX = float(os.getenv('RECENCY_PRIORITY_BOOST_MAX', '80'))
        except Exception:
            RECENCY_PRIORITY_HOURS = 168.0
            RECENCY_PRIORITY_BOOST_MAX = 80.0

        # Find the globally most recent timestamp among candidate 'last_seen' values.
        # Only consider 'meaningful' evidence types for recency (QA scans, Blancco/erasure,
        # confirmed locations, pallet evidence). This avoids generic asset_info metadata
        # updates from hijacking the recency boost.
        def _evidence_is_meaningful(evs):
            try:
                for e in evs:
                    src = e.get('source') if isinstance(e, dict) else e
                    if isinstance(src, dict):
                        sname = (src.get('source') or '')
                    else:
                        sname = str(src or '')
                    s = sname.lower()
                    if any(k in s for k in ('blancco', 'de_complete', 'erasure', 'qa', 'confirmed', 'pallet', 'stockbypallet', 'qa_latest')):
                        return True
            except Exception:
                return False
            return False

        global_most_recent = None
        for info in candidates.values():
            evs = info.get('evidence', [])
            if not _evidence_is_meaningful(evs):
                continue
            ls = info.get('last_seen')
            if ls:
                if not global_most_recent or ls > global_most_recent:
                    global_most_recent = ls

        # Tie-break: if a QA candidate exists and an Erasure candidate contains Blancco
        # evidence within a short window, prefer the QA candidate by penalising
        # the Erasure candidate score. Configurable via env: QA_BLANKCO_WINDOW_HOURS
        try:
            QA_BLN_WINDOW = float(os.getenv('QA_BLN_WINDOW_HOURS', '48'))
            BLANCCO_PENALTY = float(os.getenv('BLANCCO_TIE_PENALTY', '50'))
        except Exception:
            QA_BLN_WINDOW = 48.0
            BLANCCO_PENALTY = 50.0

        try:
            # find the most recent QA candidate timestamp
            qa_most_recent = None
            for key, info in candidates.items():
                evs = info.get('evidence', [])
                if any(('qa' in (str(e.get('source') or '')).lower() or 'qa' in str(e.get('source') or '').lower()) for e in evs):
                    if info.get('last_seen') and (not qa_most_recent or info.get('last_seen') > qa_most_recent):
                        qa_most_recent = info.get('last_seen')

            if qa_most_recent:
                for key, info in list(candidates.items()):
                    evs = info.get('evidence', [])
                    has_blancco = any((isinstance(e.get('source'), str) and 'blancco' in e.get('source').lower()) or (isinstance(e.get('source'), dict) and ('blancco' in (e.get('source').get('source') or '').lower() or 'erasure' in (e.get('source').get('source') or '').lower())) for e in evs)
                    if has_blancco and info.get('last_seen'):
                        try:
                            diff_hours = abs((info.get('last_seen') - qa_most_recent).total_seconds()) / 3600.0
                        except Exception:
                            diff_hours = None
                        if diff_hours is not None and diff_hours <= QA_BLN_WINDOW:
                            # apply penalty to make QA candidate comparatively stronger
                            info['score'] = info.get('score', 0.0) - float(BLANCCO_PENALTY)
                            info.setdefault('evidence', []).append({'source': 'qa_blancco_tie_penalty', 'raw': -BLANCCO_PENALTY, 'effective': -BLANCCO_PENALTY})
        except Exception:
            pass

        # If we have a recent timestamp, give nearby recent candidates a small boost
        if global_most_recent:
            try:
                for key, info in candidates.items():
                    ls = info.get('last_seen')
                    if not ls:
                        continue
                    try:
                        delta_hours = (global_most_recent - ls).total_seconds() / 3600.0
                    except Exception:
                        delta_hours = None
                    if delta_hours is None:
                        continue
                    if delta_hours <= RECENCY_PRIORITY_HOURS:
                        # linear-decay boost that is largest for the most-recent item
                        factor = max(0.0, 1.0 - (delta_hours / RECENCY_PRIORITY_HOURS))
                        boost = int(round(RECENCY_PRIORITY_BOOST_MAX * factor))
                        if boost > 0:
                            info['score'] = info.get('score', 0.0) + float(boost)
                            # record provenance of boost so the explanation can surface it
                            info.setdefault('evidence', []).append({'source': 'recency_boost', 'raw': boost, 'multiplier': 1.0, 'src_conf': 0.6, 'effective': float(boost)})
            except Exception:
                pass

        # Build a sorted list of candidates so we can compare top vs second.
        sorted_items = sorted(candidates.items(), key=lambda kv: kv[1]['score'], reverse=True)

        # Recompute max_score after any boosts and ensure normalization clamps to 0-100
        max_score = max((v['score'] for v in candidates.values()), default=1.0) or 1.0
        out = []
        for idx, (loc, info) in enumerate(sorted_items):
            # normalized percent (clamped)
            try:
                pct = (info.get('score', 0.0) / max_score) * 100.0
                norm = max(0, min(100, int(round(pct))))
            except Exception:
                norm = 0
            evs = info.get('evidence', [])[:8]
            last_seen = info.get('last_seen')

            kind = 'physical' if not _is_stage(evs) else 'stage'

            # Generate a human-friendly two-sentence explanation for the top candidates.
            def _compose_explanation(loc_name, info, idx, sorted_items):
                evs_local = info.get('evidence', [])[:6]
                formatted = []
                for e in evs_local:
                    try:
                        formatted.append(_format_ev(e))
                    except Exception:
                        formatted.append(str(e.get('source') if isinstance(e, dict) else e))

                # Identify signal types
                has_confirmed = any('confirmed' in str(_source_name(e.get('source'))).lower() for e in evs_local)
                has_blancco = any('blancco' in str(_source_name(e.get('source'))).lower() or 'erasure' in str(_source_name(e.get('source'))).lower() for e in evs_local)
                has_pallet = any('pallet' in str(_source_name(e.get('source'))).lower() for e in evs_local)
                has_qa = any('qa' in str(_source_name(e.get('source'))).lower() for e in evs_local)

                reasons = []
                implication = None

                if has_confirmed:
                    user = None
                    for e in evs_local:
                        s = _source_name(e.get('source'))
                        if 'user_confirmed' in str(s).lower() or 'confirmed' in str(s).lower():
                            try:
                                start = str(s).find('(')
                                end = str(s).find(')')
                                if start != -1 and end != -1 and end > start:
                                    user = str(s)[start+1:end]
                            except Exception:
                                user = None
                    if user:
                        reasons.append(f"a manager confirmed the location (by {user})")
                    else:
                        reasons.append("a manager confirmed this location")

                if has_blancco:
                    bl_info = None
                    for e in evs_local:
                        s = e.get('source') if isinstance(e, dict) else e
                        if isinstance(s, dict) and (('blancco' in (s.get('source') or '').lower()) or ('erasure' in (s.get('source') or '').lower())):
                            bl_info = s
                            break
                    if bl_info:
                        ad = bl_info.get('added_date') or bl_info.get('added')
                        if ad:
                            reasons.append(f"a Blancco erasure record on {ad}")
                        else:
                            reasons.append("a Blancco erasure record")
                    else:
                        reasons.append("an erasure record")
                    implication = "the device was erased and may be ready for resale or shipping"

                # If this candidate holds the most recent evidence, call it out
                try:
                    if global_most_recent and info.get('last_seen') and info.get('last_seen') == global_most_recent:
                        # format datetime to short date
                        try:
                            most_recent_str = info.get('last_seen').strftime('%Y-%m-%d')
                        except Exception:
                            most_recent_str = str(info.get('last_seen'))
                        reasons.append(f"most recent event recorded on {most_recent_str}")
                except Exception:
                    pass

                if has_pallet and not has_blancco:
                    pid = None
                    for e in evs_local:
                        s = e.get('source') if isinstance(e, dict) else e
                        if isinstance(s, str) and s.lower().startswith('on pallet'):
                            pid = s
                            break
                        if isinstance(s, dict) and s.get('source') and 'pallet' in s.get('source'):
                            pid = s.get('source')
                            break
                    if pid:
                        reasons.append(f"it appears on {pid}")
                    else:
                        reasons.append("Stockbypallet records point to a pallet")
                    implication = "the device is likely physically on that pallet and may be moving with it"

                if has_qa and not (has_blancco or has_pallet or has_confirmed):
                    qa_cnt = None
                    qa_last = None
                    qa_user = None
                    for e in evs_local:
                        s = e.get('source') if isinstance(e, dict) else e
                        if isinstance(s, dict) and ('qa' in (s.get('source') or '').lower() or 'qa' in str(s).lower()):
                            qa_cnt = s.get('count') or qa_cnt
                            qa_last = s.get('last_seen') or qa_last
                            qa_user = s.get('username') or qa_user
                    cnt_part = f"{int(qa_cnt)} scans" if qa_cnt else "recent scans"
                    when_part = f" last seen {qa_last}" if qa_last else ""
                    by_part = f" by {qa_user}" if qa_user else ""
                    reasons.append(f"{cnt_part}{when_part}{by_part}")
                    implication = f"the device was recently observed at {loc_name} and may still be there"

                if not reasons:
                    if formatted:
                        reasons.append('; '.join(formatted[:2]))
                    else:
                        reasons.append(f"strongest combined evidence (score {int(round((info.get('score',0)/max_score)*100))})")

                compare_note = ''
                if idx == 0 and len(sorted_items) > 1:
                    other_loc, other_info = sorted_items[1]
                    other_score = int(round((other_info['score'] / max_score) * 100))
                    top_score = int(round((info['score'] / max_score) * 100))
                    if top_score >= other_score + 20:
                        compare_note = f" It ranks substantially higher than {other_loc} (score {top_score}% vs {other_score}%)."
                    else:
                        compare_note = f" It ranks above {other_loc} (score {top_score}% vs {other_score}%)."

                reason_text = ' and '.join(reasons)
                sentence1 = f"{loc_name} is the best place to start looking for this device because {reason_text}.{compare_note}"
                sentence2 = f"This likely means {implication}." if implication else ""
                return (sentence1 + (' ' + sentence2 if sentence2 else '')).strip()

            try:
                explanation = _compose_explanation(loc, info, idx, sorted_items)
            except Exception:
                explanation = ''

            try:
                MAX_TOTAL = float(os.getenv('CANDIDATE_MAX_TOTAL', '1000.0'))
            except Exception:
                MAX_TOTAL = 1000.0
            out.append({
                'location': loc,
                'score': norm,
                'raw_score': float(min(info.get('score', 0.0), MAX_TOTAL)),
                'evidence': [ (e if isinstance(e, dict) else {'source': e}) for e in evs ],
                'last_seen': last_seen.isoformat() if last_seen else None,
                'type': kind,
                'explanation': explanation,
                'ai_explanation': None,
                'rank': idx + 1,
            })

        # Enrich with AI-style expanded explanations
        def _confidence_label(score_pct: int):
            if score_pct >= 80:
                return 'high'
            if score_pct >= 60:
                return 'medium-high'
            if score_pct >= 40:
                return 'medium'
            return 'low'

        for item in out:
            try:
                score_pct = int(item.get('score', 0))
                conf = _confidence_label(score_pct)
                evid = item.get('evidence', [])[:6]
                evid_texts = []
                for e in evid:
                    try:
                        evid_texts.append(_format_ev(e))
                    except Exception:
                        evid_texts.append(str(e.get('source') if isinstance(e, dict) else e))

                # Detect primary signal
                s_text = ' '.join(evid_texts).lower()
                primary = None
                if 'blancco' in s_text or 'erasure' in s_text:
                    primary = 'erasure'
                elif 'pallet' in s_text:
                    primary = 'pallet'
                elif any('confirmed' in t for t in s_text.split()):
                    primary = 'confirmed'
                elif 'qa' in s_text or 'scan' in s_text:
                    primary = 'qa'
                else:
                    primary = 'other'

                # Detect erasure operator/date if present in evidence
                er_user = None
                er_date = None
                try:
                    for e in evid:
                        src = e.get('source') if isinstance(e, dict) else e
                        if isinstance(src, dict) and (('blancco' in (src.get('source') or '').lower()) or ('erasure' in (src.get('source') or '').lower())):
                            er_user = src.get('username') or er_user
                            er_date = src.get('added_date') or src.get('added') or er_date
                except Exception:
                    er_user = None
                    er_date = None

                # detect whether pallet evidence exists (so recommendations can reference it accurately)
                has_pallet_evidence = any('pallet' in (t or '').lower() for t in evid_texts)

                # Compose AI-style explanation (neutral, non-first-person)
                # We'll build a single conversational paragraph that:
                # - states the likely location (or plausible for non-top)
                # - explains why (recency / primary signal)
                # - gives a recommended next step (check location then follow workflow)
                # - optionally compares recency to later-stage evidence
                # - summarizes cohort/pallet evidence when available
                parts = []
                # Opening: why this candidate (avoid first-person wording)
                if primary == 'erasure':
                    rank = int(item.get('rank', 0) or 0)
                    if er_user or er_date:
                        pieces = []
                        if er_user:
                            pieces.append(f"by {er_user}")
                        if er_date:
                            pieces.append(f"on {er_date}")
                        if rank and rank > 1:
                            opener = f"Evidence indicates {item.get('location')} is a plausible location because a Blancco/erasure record ({' '.join(pieces)}) was found for this device."
                        else:
                            opener = f"Evidence indicates {item.get('location')} is the most likely place because a Blancco/erasure record ({' '.join(pieces)}) was found for this device."
                    else:
                        if rank and rank > 1:
                            opener = f"Evidence indicates {item.get('location')} is a plausible location because a Blancco/erasure record was found for this device."
                        else:
                            opener = f"Evidence indicates {item.get('location')} is the most likely place because a Blancco/erasure record was found for this device."
                elif primary == 'pallet':
                    opener = f"Stockbypallet/ITAD_pallet records associate {item.get('location')} with this device's pallet, making it a likely location."
                elif primary == 'confirmed':
                    # If this is not the top-ranked candidate, avoid phrasing as definitive
                    if int(item.get('rank', 0) or 0) > 1:
                        opener = f"A manager previously confirmed {item.get('location')}, which is a plausible location."
                    else:
                        opener = f"A manager previously confirmed {item.get('location')} as the device's location."
                elif primary == 'qa':
                    opener = f"Multiple QA scans recently observed the device at {item.get('location')}, indicating it may still be there."
                else:
                    opener = f"Combined signals from the data sources indicate {item.get('location')} is a likely location."

                # Evidence summary (human-friendly)
                human_evid = []
                inferred_from_neighbors = False
                for t in evid_texts[:6]:
                    try:
                        lt = t.lower()
                        if 'blancco' in lt or 'erasure' in lt:
                            human_evid.append('Blancco (erasure) record' + (f" — {t}" if 'on ' in lt or 'by ' in lt else ''))
                        elif 'pallet' in lt:
                            human_evid.append(t.replace('Stockbypallet/ITAD_pallet records', 'Pallet record'))
                        elif 'qa' in lt or 'scan' in lt:
                            human_evid.append('Recent QA scans' + (f" — {t}" if '(' in t or 'last seen' in lt else ''))
                        elif 'confirmed' in lt or 'user_confirmed' in lt:
                            human_evid.append('Manager confirmation')
                        elif 'inferred' in lt or 'co_location' in lt or 'nearby' in lt:
                            human_evid.append('Inferred from nearby devices on same pallet')
                            inferred_from_neighbors = True
                        else:
                            human_evid.append(t)
                    except Exception:
                        human_evid.append(t)

                # We intentionally omit a separate 'Key records:' summary and
                # an explicit runner-up comparison; those made paragraphs
                # feel repetitive. Keep human_evid available only for
                # internal checks (cohort/pallet extraction below).
                context_sent = ''

                # Confidence and uncertainty
                conf_sent = f"Confidence: {conf} (approx. score {score_pct}%)."

                # Recommended action (clearer)
                action = ''
                if primary == 'erasure':
                    if has_pallet_evidence:
                        action = 'Check the Blancco/erasure record and inspect the indicated pallet — verify pallet contents and recent scans before reassigning or shipping.'
                    else:
                        action = 'Check the Blancco/erasure record; if the device has an associated pallet or shipping queue, inspect those and verify recent scans before reassigning or shipping.'
                elif primary == 'pallet':
                    action = 'Inspect the pallet shown and its recent scans; confirm the device is physically present before moving or shipping.'
                elif primary == 'confirmed':
                    action = 'Manager-confirmed location — verify the timestamp and any note, then proceed.'
                elif item.get('type') == 'physical':
                    action = 'Perform a quick QA or roller scan to confirm the device is present.'
                if action:
                    # assemble a single conversational paragraph similar to the user's example
                    try:
                        workflow = ['IA', 'Erasure', 'QA', 'Sorting']
                        def stage_rank(name: str):
                            n = (name or '').lower()
                            if 'roller' in n or 'ia' in n:
                                return 0
                            if 'erasure' in n or 'blancco' in n:
                                return 1
                            if 'qa' in n:
                                return 2
                            if 'pallet' in n or 'stockbypallet' in n:
                                return 3
                            return -1

                        this_stage = stage_rank(item.get('location') or '')
                        later_candidates = []
                        for loc_name, loc_info in sorted_items:
                            ls_stage = stage_rank(loc_name)
                            if ls_stage > this_stage and loc_info.get('last_seen') and item.get('last_seen'):
                                later_candidates.append((loc_name, loc_info))

                        recency_comp = ''
                        if later_candidates and item.get('last_seen'):
                            later = sorted(later_candidates, key=lambda x: x[1].get('last_seen') or datetime.min, reverse=True)[0]
                            later_name, later_info = later
                            try:
                                if item.get('last_seen') and later_info.get('last_seen') and item.get('last_seen') > later_info.get('last_seen'):
                                    next_stage = None
                                    if 'erasure' in later_name.lower() or 'blancco' in later_name.lower():
                                        next_stage = 'Erasure'
                                    elif 'pallet' in later_name.lower():
                                        next_stage = 'Pallet/Shipping'
                                    elif 'qa' in later_name.lower():
                                        next_stage = 'QA'
                                    if next_stage:
                                        recency_comp = (f"Since {item.get('location')} has a more recent date than {later_name}, "
                                                       f"it may have been put through the workflow again and could be awaiting {next_stage} (next on the workflow).")
                            except Exception:
                                recency_comp = ''

                        # extract pallet IDs from evidence texts for cohort summary
                        pallet_ids = set()
                        try:
                            for t in evid_texts + [item.get('location') or '']:
                                if not t:
                                    continue
                                lt = t.lower()
                                if 'pallet' in lt:
                                    m = re.search(r'(?i)pallet\s*([A-Za-z0-9_-]+)', t)
                                    if m:
                                        pallet_ids.add(m.group(1))
                                m2 = re.search(r'\bA?\d{6,8}\b', t)
                                if m2:
                                    pallet_ids.add(m2.group(0))
                        except Exception:
                            pass

                        cohort_note = ''
                        if pallet_ids:
                            pid_list = ', '.join(sorted(pallet_ids))
                            cohort_note = f"Other devices with the same destination were allocated to pallet(s) {pid_list}."

                        paragraph_parts = []
                        lead_word = 'is the most likely place' if int(item.get('rank', 0) or 0) == 1 else 'is a plausible location'
                        # prefer to mention recency boost if present
                        try:
                            recency_reason = 'due to having the most recent date' if any((isinstance(e, dict) and e.get('source') == 'recency_boost') for e in evid) else 'based on available signals'
                        except Exception:
                            recency_reason = 'based on available signals'
                        paragraph_parts.append(f"{item.get('location')} {lead_word} for the device, {recency_reason}.")
                        if context_sent:
                            paragraph_parts.append(context_sent)
                        if recency_comp:
                            paragraph_parts.append(recency_comp)
                        if this_stage == 0:
                            paragraph_parts.append('Check this location, then follow the workflow (IA -> Erasure -> QA -> Sorting) to trace where it would go next.')
                        elif this_stage == 1:
                            paragraph_parts.append('Check the erasure record and associated pallet/queue, then confirm via QA/roller as needed.')
                        elif this_stage == 3:
                            paragraph_parts.append('Inspect the pallet contents and recent scans; confirm the device is physically present before moving or shipping.')
                        if cohort_note:
                            paragraph_parts.append(cohort_note)
                        if conf_sent:
                            paragraph_parts.append(conf_sent)

                        item['ai_explanation'] = ' '.join([p for p in paragraph_parts if p]).strip()
                    except Exception:
                        item['ai_explanation'] = item.get('explanation') or ''
                else:
                    item['ai_explanation'] = item.get('explanation') or ''
            except Exception:
                item['ai_explanation'] = item.get('explanation') or ''
            # Add explicit flags and blancco details for UI
            try:
                evid = item.get('evidence', [])
                s_text = ' '.join([_format_ev(e).lower() for e in evid if e])
                item['is_blancco'] = ('blancco' in s_text or 'erasure' in s_text)
                item['is_inferred'] = any((isinstance(e, dict) and (('co_location' in (e.get('source') or '') ) or ('inferred' in str(e.get('source') or '').lower()))) for e in evid)
                item['is_confirmed'] = any('confirmed' in str(_source_name(e.get('source'))).lower() for e in evid)
                item['is_most_recent'] = False
                try:
                    if global_most_recent and item.get('last_seen') and item.get('last_seen') == global_most_recent:
                        item['is_most_recent'] = True
                except Exception:
                    item['is_most_recent'] = False

                # collect blancco details if present
                bl_user = None
                bl_date = None
                for e in evid:
                    try:
                        src = e.get('source') if isinstance(e, dict) else e
                        if isinstance(src, dict) and (('blancco' in (src.get('source') or '').lower()) or ('erasure' in (src.get('source') or '').lower())):
                            bl_user = bl_user or src.get('username') or src.get('user')
                            bl_date = bl_date or src.get('added_date') or src.get('added') or src.get('date')
                    except Exception:
                        continue
                if bl_user or bl_date:
                    item['blancco'] = {}
                    if bl_user:
                        item['blancco']['operator'] = bl_user
                    if bl_date:
                        item['blancco']['date'] = bl_date
            except Exception:
                pass

        # Already built in score-descending order
        return out[:top_n]
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        raise
