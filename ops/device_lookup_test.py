#!/usr/bin/env python3
"""Simple perf test harness for `device_lookup.get_device_location_hypotheses`.

Usage:
  python ops/device_lookup_test.py STOCKID1 [STOCKID2 ...]

If no stockids provided, edit the SAMPLE_IDS list below.
"""
import sys
import time
from statistics import mean, median

sys.path.insert(0, '..')

try:
    from device_lookup import get_device_location_hypotheses
except Exception as e:
    print('Error importing device_lookup:', e)
    raise

SAMPLE_IDS = [
    # replace with real sample stockids you have permission to query
    '12963675',
    '12345678',
]

def run_one(stockid, runs=3):
    times = []
    results = None
    for i in range(runs):
        t0 = time.time()
        try:
            r = get_device_location_hypotheses(stockid, top_n=3)
        except Exception as e:
            print(f'Error during lookup for {stockid}:', e)
            return None
        dt = time.time() - t0
        times.append(dt)
        results = r
    return results, times

def summary_for(ids):
    report = []
    for s in ids:
        print(f'Running test for {s}...')
        r = run_one(s, runs=3)
        if not r:
            print('  failed')
            continue
        results, times = r
        print(f'  times: {times} (avg {mean(times):.2f}s, med {median(times):.2f}s)')
        print('  sample output:', results)
        report.append((s, times, results))
    return report

if __name__ == '__main__':
    ids = sys.argv[1:] or SAMPLE_IDS
    summary_for(ids)
