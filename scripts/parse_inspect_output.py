import json
from pathlib import Path

INPUT = Path(__file__).with_name('inspect_output.json')
OUT = Path(__file__).with_name('inspect_summary.json')

KEY_FIELDS = [
    'de_complete', 'de_completed_date', 'pallet_id', 'palletID', 'last_update',
]

def extract_summary(data):
    summary = {}
    for stockid, buckets in data.items():
        summary[stockid] = {}
        for table, rows in buckets.items():
            if not rows:
                continue
            summary[stockid].setdefault(table, [])
            for row in rows:
                if not isinstance(row, dict):
                    continue
                entry = {}
                # pick keys of interest when present
                for k in KEY_FIELDS:
                    if k in row and row.get(k) is not None:
                        entry[k] = row.get(k)
                # add some helpful fallbacks
                if 'id' in row:
                    entry.setdefault('id', row.get('id'))
                if 'stockid' in row:
                    entry.setdefault('stockid', row.get('stockid'))
                # for blancco rows, indicate blancco presence
                if table.lower().find('blancco') >= 0 or row.get('erasures') or row.get('blancco_hardware_report'):
                    entry.setdefault('blancco', True)
                if entry:
                    summary[stockid][table].append(entry)
    return summary


def main():
    text = INPUT.read_text()
    # file may contain diagnostic lines before the JSON object; find first '{'
    idx = text.find('{')
    if idx == -1:
        raise SystemExit(f'no JSON object found in {INPUT}')
    raw = json.loads(text[idx:])
    summary = extract_summary(raw)
    OUT.write_text(json.dumps(summary, indent=2))
    print(f'wrote {OUT} (stocks: {len(summary)})')


if __name__ == '__main__':
    main()
