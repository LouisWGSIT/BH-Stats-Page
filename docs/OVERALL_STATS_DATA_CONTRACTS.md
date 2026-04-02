# Overall Stats Data Contracts

## Purpose
Define the backend payload shape for each section card so integrations can be delivered one source at a time without reworking frontend layout.

## Shared Section Contract
All section endpoints should return this envelope:

```json
{
  "sectionKey": "goods_in",
  "sectionName": "Goods In",
  "targetQueue": 90,
  "currentQueue": 128,
  "trendPctHour": 14,
  "owner": "Inbound Team",
  "queueLabel": "Totes Delivered",
  "subMetrics": [
    { "label": "Delivered This Morning", "value": 128 },
    { "label": "Checked In", "value": 92 },
    { "label": "Awaiting IA", "value": 36 }
  ],
  "updatedAt": "2026-04-02T09:15:00Z"
}
```

## Overall Endpoint (Phase 1/2 Bridge)
Frontend can consume one endpoint for all cards:

`GET /overall/sections`

```json
{
  "sections": [
    {
      "sectionKey": "goods_in",
      "sectionName": "Goods In",
      "targetQueue": 90,
      "currentQueue": 128,
      "trendPctHour": 14,
      "owner": "Inbound Team",
      "queueLabel": "Totes Delivered",
      "subMetrics": [
        { "label": "Delivered This Morning", "value": 128 },
        { "label": "Checked In", "value": 92 },
        { "label": "Awaiting IA", "value": 36 }
      ],
      "updatedAt": "2026-04-02T09:15:00Z"
    }
  ]
}
```

## Phase 2 - Goods In Contract
Required sub-metrics for Goods In:
- Delivered This Morning
- Checked In
- Awaiting IA

Proposed endpoint:
- `GET /overall/goods-in`

Goods In-specific response:

```json
{
  "sectionKey": "goods_in",
  "sectionName": "Goods In",
  "targetQueue": 90,
  "currentQueue": 128,
  "trendPctHour": 14,
  "owner": "Inbound Team",
  "queueLabel": "Totes Delivered",
  "subMetrics": [
    { "label": "Delivered This Morning", "value": 128 },
    { "label": "Checked In", "value": 92 },
    { "label": "Awaiting IA", "value": 36 }
  ],
  "updatedAt": "2026-04-02T09:15:00Z"
}
```

## Phase 3 - IA Contract
Required sub-metrics for IA:
- Awaiting IA
- Completed IA
- Ready for Erasure

## Phase 4 - Remaining Contracts
Required sub-metrics:
- Erasure: Roller 1 Queue, Roller 2 Queue, Roller 3 Queue
- QA: DB Awaiting QA, Non-DB Awaiting QA, Completed QA Today
- Sorting: Awaiting Sorting, Sorted This Morning, QA Output Last Hour

## Validation Rules
- All queue and metric values are integers >= 0.
- `targetQueue` should be > 0 for status calculation.
- `trendPctHour` may be negative, zero, or positive.
- Missing section payload should not break the page; frontend should render fallback state.

## Frontend Mapping
Current visual loader:
- `frontend/js/core/overall_stats_dashboard.js`

When backend becomes available:
1. Replace mock section array with fetch from `/overall/sections`.
2. Keep exact field names from this contract to avoid template rewrites.
3. If one section source is offline, render stale indicator on only that card.
