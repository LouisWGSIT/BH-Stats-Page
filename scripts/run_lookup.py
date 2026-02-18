import json
import sys
import os

# ensure repo root is on sys.path so imports like `import device_lookup` work
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# set a small audit lookback and prefer SIMPLE mode to avoid long-running
# audit_master LIKE scans during local checks
os.environ.setdefault('AUDIT_LOOKBACK_DAYS', '7')
os.environ.setdefault('SIMPLE_HYPOTHESES', '1')

try:
    from device_lookup import get_device_location_hypotheses
except Exception as e:
    print(f"IMPORT_ERROR: {e}")
    sys.exit(2)

stockid = '12968582'
try:
    res = get_device_location_hypotheses(stockid, top_n=10)
    print(json.dumps(res, indent=2, default=str))
except Exception as e:
    print(f"ERROR: {e}")
    raise
