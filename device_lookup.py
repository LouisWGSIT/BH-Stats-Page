"""Device lookup heuristics moved out of `qa_export.py`.

This module provides `get_device_location_hypotheses()` as a focused place
for UI heuristics and lookup helpers.
"""
from datetime import datetime
from typing import List, Dict
import sqlite3

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
                    if 'blancco' in s or 'de_complete' in s or 'erasure' in s or 'erasure station' in s:
                        return True
            except Exception:
                pass
            return False

        # Build a sorted list of candidates so we can compare top vs second.
        sorted_items = sorted(candidates.items(), key=lambda kv: kv[1]['score'], reverse=True)
        out = []
        for idx, (loc, info) in enumerate(sorted_items):
            norm = int(round((info['score'] / max_score) * 100))
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

            out.append({
                'location': loc,
                'score': norm,
                'raw_score': float(info.get('score', 0.0)),
                'evidence': [ (e if isinstance(e, dict) else {'source': e}) for e in evs ],
                'last_seen': last_seen.isoformat() if last_seen else None,
                'type': kind,
                'explanation': explanation,
                'ai_explanation': None,
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

                # Compose AI-style explanation
                parts = []
                # Opening: why this candidate
                if primary == 'erasure':
                    opener = f"I consider {item.get('location')} the most likely place because a Blancco/erasure record was found for this device."
                elif primary == 'pallet':
                    opener = f"I consider {item.get('location')} likely because Stockbypallet/ITAD_pallet records associate this device with that pallet."
                elif primary == 'confirmed':
                    opener = f"I consider {item.get('location')} likely because a manager previously confirmed this location."
                elif primary == 'qa':
                    opener = f"I consider {item.get('location')} likely because multiple QA scans observed the device there recently."
                else:
                    opener = f"I consider {item.get('location')} a likely location based on combined signals from the data sources."
                parts.append(opener)

                # Evidence summary
                if evid_texts:
                    parts.append('Key signals: ' + '; '.join(evid_texts[:3]) + '.')

                # Compare to next-best candidate to express ambiguity
                comp_note = ''
                try:
                    # find this location in sorted_items to compare to runner-up
                    runner = None
                    for loc_name, loc_info in sorted_items:
                        if loc_name == item.get('location'):
                            break
                    # get runner-up (second item)
                    if len(sorted_items) > 1 and sorted_items[0][0] == item.get('location'):
                        other_loc, other_info = sorted_items[1]
                        other_score = int(round((other_info['score'] / max_score) * 100))
                        top_score = int(round((item.get('raw_score', 0) / max_score) * 100))
                        gap = top_score - other_score
                        if gap < 15:
                            comp_note = f"There is some ambiguity: this ranks only slightly above {other_loc} ({top_score}% vs {other_score}%)."
                        else:
                            comp_note = f"This ranks above {other_loc} ({top_score}% vs {other_score}%)."
                except Exception:
                    comp_note = ''
                if comp_note:
                    parts.append(comp_note)

                # Confidence and uncertainty
                parts.append(f"Confidence: {conf} (approx. score {score_pct}%).")

                # Recommended action
                action = ''
                if primary == 'erasure':
                    action = 'Check the Blancco entry (date/operator) and the pallet/shipping queue before reassigning or shipping.'
                elif primary == 'pallet':
                    action = 'Verify the pallet contents and recent scans; inspect the pallet before moving or shipping.'
                elif primary == 'confirmed':
                    action = 'You can rely on the manager confirmation, but verify timestamp/note if available.'
                elif item.get('type') == 'physical':
                    action = 'Perform a quick QA or roller scan to confirm the device is present.'
                if action:
                    parts.append('Recommended action: ' + action)

                item['ai_explanation'] = ' '.join([p for p in parts if p]).strip()
            except Exception:
                item['ai_explanation'] = item.get('explanation') or ''

        # Already built in score-descending order
        return out[:top_n]
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        raise
