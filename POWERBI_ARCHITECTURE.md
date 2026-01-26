# Power BI Integration Architecture

## Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    WAREHOUSE OPERATIONS                       │
│         (Erasure devices, scanning, QA checks)                │
└──────────────────┬───────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────┐
│                    STATS PAGE SERVER                          │
│                   (FastAPI Application)                       │
├──────────────────────────────────────────────────────────────┤
│  Endpoints:                                                   │
│  • POST /hooks/erasure         (Webhook: Record events)       │
│  • POST /hooks/erasure-detail  (Detailed events)              │
│  • GET  /metrics/today         (Quick daily summary)          │
│  • GET  /metrics/yesterday     (Previous day summary)         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │        ✨ NEW: POWER BI ENDPOINTS ✨                │   │
│  ├──────────────────────────────────────────────────────┤   │
│  │  • GET  /api/powerbi/daily-stats                     │   │
│  │  • GET  /api/powerbi/erasure-events                  │   │
│  │  • GET  /api/powerbi/engineer-stats                  │   │
│  └──────────────────────────────────────────────────────┘   │
│  All support: ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD    │
└──────────────────┬───────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────┐
│                  SQLite3 DATABASE                             │
│              (warehouse_stats.db)                             │
├──────────────────────────────────────────────────────────────┤
│  Tables:                                                      │
│  • daily_stats          (Daily counts: booked_in, erased, qa) │
│  • erasures             (Detailed events: ts, device_type, initials) │
│  • engineer_stats       (Engineer counts by date)             │
│  • engineer_stats_type  (Engineer counts by device type)      │
│  • seen_ids             (Deduplication)                       │
└──────────────────┬───────────────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
    ┌────────────┐    ┌──────────────────┐
    │   Stats    │    │  POWER BI DESKTOP│
    │   Page UI  │    │  or Online       │
    │ (Browser)  │    │                  │
    └────────────┘    │ Uses Web API     │
                      │ connector to     │
                      │ query endpoints  │
                      │                  │
                      │ Creates:         │
                      │ • Dashboards     │
                      │ • Reports        │
                      │ • Visualizations │
                      └──────────────────┘
```

## Data Models

### 1. Daily Stats Model
```
Daily Stats
├── date (Date)
├── booked_in (Number)
├── erased (Number)
└── qa (Number)
```
**From:** `/api/powerbi/daily-stats`
**Use for:** KPIs, trends, daily performance tracking

### 2. Erasure Events Model
```
Erasure Events
├── timestamp (DateTime)
├── date (Date)
├── month (Text: YYYY-MM)
├── event (Text: success|failure|connected)
├── device_type (Text: laptops_desktops|servers|etc)
├── initials (Text: Engineer code)
├── duration_seconds (Number)
├── error_type (Text: If failed)
└── job_id (Text: Unique identifier)
```

**From:** `/api/powerbi/erasure-events`
