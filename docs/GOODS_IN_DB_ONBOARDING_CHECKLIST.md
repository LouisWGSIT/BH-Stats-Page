# Goods In DB Onboarding Checklist

## Purpose
Fast handoff checklist for wiring live Goods In data into Overall Stats with minimal rework.

## 1) Access Confirmation
- Confirm MariaDB host, database, username, and read-only permissions.
- Confirm VPN/network access from Render/runtime environment.
- Confirm source timezone and timestamp conventions.

## 2) Table and Column Mapping (fill this in)
- Table name:
- Primary identifier for tote/pallet count:
- Delivered timestamp column:
- Checked-in status column (if available):
- IA handoff/awaiting indicator column (if available):
- Any warehouse/site filter column:

## 3) Business Rules (confirm with manager)
- "Delivered This Morning" means:
- "Checked In" means:
- "Awaiting IA" means:
- Morning cutoff time (default 00:00 local vs shift start):
- Should weekends be included or excluded:

## 3.1) Optional Query Overrides (fast path)
If default query logic is not enough, define these environment variables:
- `OVERALL_GOODS_IN_DELIVERED_QUERY`
- `OVERALL_GOODS_IN_CHECKED_IN_QUERY`
- `OVERALL_GOODS_IN_AWAITING_IA_QUERY`

Each query must return a single numeric value (`COUNT(*)` style).

## 4) Query Validation
Run and verify these outputs before wiring:
- Delivered count for today
- Checked-in count for today
- Awaiting IA count for today
- Sample 10 rows for manual sanity check

## 5) Contract Validation
Endpoint contract file:
- docs/OVERALL_STATS_DATA_CONTRACTS.md

Required keys from `/overall/goods-in`:
- sectionKey
- sectionName
- targetQueue
- currentQueue
- trendPctHour
- owner
- queueLabel
- subMetrics[]
- updatedAt
- isLive
- source

## 6) Frontend Validation
UI loader file:
- frontend/js/core/overall_stats_dashboard.js

Confirm:
- Goods In card shows live values
- Other sections remain mock
- Live/Mock badge is correct
- Fallback to mock still renders if DB query fails

## 7) Done Criteria for GRE-5/6/7
- GRE-5: backend endpoint returns live Goods In values
- GRE-6: frontend renders live Goods In card without layout regressions
- GRE-7: fallback behavior verified and visible
