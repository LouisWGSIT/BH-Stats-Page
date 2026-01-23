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
**Use for:** Detailed analysis, error tracking, duration metrics

### 3. Engineer Stats Model
```
Engineer Stats
├── date (Date)
├── initials (Text)
└── count (Number)
```
**From:** `/api/powerbi/engineer-stats`
**Use for:** Leaderboards, engineer performance, trends by person

## API Query Patterns

### Pattern 1: Last 30 Days
```
GET /api/powerbi/daily-stats
    ?start_date=2025-12-23
    &end_date=2026-01-22
```
Returns all daily stats for the date range.

### Pattern 2: Today Only
```
GET /api/powerbi/daily-stats
    ?start_date=2026-01-22
    &end_date=2026-01-22
```
Returns a single record for today.

### Pattern 3: Filtered Events
```
GET /api/powerbi/erasure-events
    ?start_date=2026-01-01
    &end_date=2026-01-31
    &device_type=laptops_desktops
```
Returns events for a specific device category.

### Pattern 4: Historical Analysis
```
GET /api/powerbi/engineer-stats
    ?start_date=2025-01-01
    &end_date=2026-01-22
```
Returns engineer performance over a full year.

## Power BI Processing Flow

```
┌──────────────────────────┐
│  Power BI Desktop        │
│  "Get Data" > "Web"      │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────────────────────┐
│  Web.Contents()                          │
│  Sends: GET /api/powerbi/daily-stats     │
│         Accept: application/json         │
└────────────┬─────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────┐
│  FastAPI Server Processes Request        │
│  • Validates date parameters             │
│  • Queries SQLite database               │
│  • Returns JSON array                    │
└────────────┬─────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────┐
│  JSON Response                           │
│  {                                       │
│    "data": [                             │
│      {date, booked_in, erased, qa},      │
│      {date, booked_in, erased, qa},      │
│      ...                                 │
│    ]                                     │
│  }                                       │
└────────────┬─────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────┐
│  Power Query Processing                  │
│  • Parse JSON                            │
│  • Expand "data" array to table           │
│  • Set column data types                 │
│  • Apply transformations                 │
└────────────┬─────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────┐
│  Power BI Data Model                     │
│  • Load into memory                      │
│  • Create relationships                  │
│  • Calculate measures & columns          │
└────────────┬─────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────┐
│  Visualizations & Reports                │
│  • Cards, Charts, Tables, Gauges         │
│  • Dashboards with interactivity         │
│  • Filters and slicers                   │
└──────────────────────────────────────────┘
```

## Typical Daily Refresh Cycle

```
Time →

00:00 ──────────────────────────────────────────
      MIDNIGHT - New day starts
      Previous day's stats finalized
      DB ready for new date records

06:00 ──────────────────────────────────────────
      Morning shift begins
      Erasures start being recorded
      Stats accumulate in daily_stats table

09:00 ──────────────────────────────────────────
      ✓ Power BI could refresh now
      Dashboard shows morning progress
      Endpoint returns current day's data: {date: 2026-01-22, erased: 45, ...}

12:00 ──────────────────────────────────────────
      Mid-day refresh
      Shows progress so far

15:00 ──────────────────────────────────────────
      Afternoon refresh
      Dashboard tracks to daily target

18:00 ──────────────────────────────────────────
      End of day reset trigger
      Daily counts complete
      End-of-day snapshot can be captured

20:00 ──────────────────────────────────────────
      Evening refresh (optional)
      Final daily totals

00:00 ──────────────────────────────────────────
      Next day - cycle repeats
```

## Integration Options

### Option A: Direct API Connection (Recommended)
```
Power BI → GET /api/powerbi/daily-stats → SQLite
```
- Pros: Real-time, no intermediate storage, clean
- Cons: Requires server accessible from Power BI network
- Best for: Internal networks, on-premise Power BI

### Option B: Scheduled Export
```
Stats Server → CSV/Excel → Blob Storage → Power BI
```
- Pros: Works with cloud Power BI, scheduled
- Cons: Delayed updates
- Best for: Cloud environments

### Option C: Power BI Gateway
```
Power BI Service → On-Prem Gateway → Stats API → SQLite
```
- Pros: Cloud Power BI with local data
- Cons: Requires gateway installation
- Best for: Hybrid cloud/on-prem setups

**Current Setup:** Option A (Direct API Connection)

---

## Response Size & Performance

| Endpoint | Records | Avg Size | Query Time |
|----------|---------|----------|-----------|
| daily-stats (30 days) | ~30 | ~2 KB | <100ms |
| daily-stats (1 year) | ~365 | ~20 KB | <200ms |
| erasure-events (30 days) | ~1000s | ~500 KB | 500-1000ms |
| engineer-stats (30 days) | ~100s | ~10 KB | <100ms |

For large queries (1+ year), consider:
- Querying in chunks (e.g., 3 months at a time)
- Creating a separate data warehouse
- Using incremental refresh in Power BI Premium

---

**For questions about data flow, see specific endpoint documentation in POWERBI_SETUP.md**
