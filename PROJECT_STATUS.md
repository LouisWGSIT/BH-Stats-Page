# Project Status

## Summary
Warehouse stats dashboards for TV displays and staff access. The app serves Erasure Stats and QA Stats dashboards, with role-based access for exports/admin. Frontend is static HTML/CSS/JS, backend is FastAPI with MariaDB for QA and SQLite for erasures.

## Goals
- TV-friendly dashboards with stable layout, low CPU, and auto-refresh.
- Secure external access: viewer-only by default, password to elevate.
- Accurate exports across weekly/monthly scopes.
- Future: Power BI dashboards fed by API endpoints.

## Project Layout
- Frontend: index.html, admin.html, styles.css, app.js.
- Backend: main.py (FastAPI), database.py (SQLite + erasures logic), qa_export.py (MariaDB QA stats + exports), engineer_export.py, excel_export.py.
- Config: config.json (theme + targets).

## Architecture Overview
- Static frontend served by FastAPI StaticFiles.
- Auth flow handled in app.js and /auth/* endpoints.
- Dashboard data via JSON endpoints under /metrics, /analytics, /api/qa-*.
- Exports via /export/* endpoints, generated server-side.

## Roles and Access
- Viewer: auto-access on local network; no export/admin controls.
- Manager: export allowed, admin hidden.
- Admin: export + admin tools.
- Login via padlock icon; device token stored for auto-login.
- Auth header injected for all fetch calls in app.js after login.

## Roles and Access
- Viewer: auto-access on local network; no export/admin controls.
- Manager: export allowed, admin hidden.
- Admin: export + admin tools.
- Login via padlock icon; device token stored for auto-login.

## Dashboards
- Erasure Stats: primary, considered stable.
- QA Stats: current focus for UX polish and metrics accuracy.

## Frontend Behavior
- Dashboard switching: erasure <-> QA, persists in localStorage.
- QA dashboard auto-refresh every 2 minutes when active.
- QA trend panels: today/week/all-time, sparklines + metric chips.
- QA metrics card rotates between summary, data-bearing record, non-data-bearing record.
- QA rotating cards: data-bearing vs non-data-bearing panels, synced every 30s.
- SVG sparklines used for tracker cards (wider, stable, low CPU).

## Data Sources
- QA App data: MariaDB table ITAD_QA_App.
- Data-bearing QA: audit_master (DEAPP_Submission, DEAPP_Submission_EditStock_Payload).
- Non-data-bearing QA: audit_master (Non_DEAPP_Submission, Non_DEAPP_Submission_EditStock_Payload).
- Erasure stats: SQLite (erasures table) with FastAPI endpoints.

## QA Data Rules
- audit_master queries use DISTINCT sales_order to avoid duplicates.
- Managers excluded from daily record calculations (filter by email match).
- Unassigned records are excluded from totals where noted.
- QA totals on dashboard combine QA App + DE + Non-DE.

## Key QA Endpoints
- /api/qa-dashboard?period=... (this_week, last_week, this_month, last_month, today, all_time, last_available)
- /api/qa-trends?period=... (today, this_week, all_time)
- /api/insights/qa?period=...
- /api/insights/qa-engineers?period=... (per-engineer trends)
- /api/bottlenecks?days=7 (current warehouse bottleneck snapshot - manager/admin only)
- /api/bottlenecks/details?category=...&days=7 (detailed device list by category)

## Erasure Endpoints (Common)
- /metrics/summary (supports date range for monthly reporting)
- /metrics/records
- /metrics/monthly-momentum
- /analytics/daily-totals
- /analytics/hourly-totals

## Exports
- /export/qa-stats (QA engineer breakdown export)
- /export/engineer-deepdive (erasure deep dive)
- Exports accept period=... and must cover this_week, last_week, this_month, last_month, last_available.

## Environment and Config
- Config via config.json for theme + targets.
- MariaDB connection in qa_export.py.
- SQLite path can be set via STATS_DB_PATH.
- Render deployment uses runtime.txt and requirements.txt.

## Data Sources
- QA App data: MariaDB table ITAD_QA_App.
- Data-bearing QA: audit_master (DEAPP_Submission, DEAPP_Submission_EditStock_Payload).
- Non-data-bearing QA: audit_master (Non_DEAPP_Submission, Non_DEAPP_Submission_EditStock_Payload).
- Erasure stats: SQLite (erasures table) with FastAPI endpoints.

## Key QA Endpoints
- /api/qa-dashboard?period=... (this_week, last_week, this_month, last_month, today, all_time, last_available)
- /api/qa-trends?period=... (today, this_week, all_time)
- /api/insights/qa?period=...

## Exports
- /export/qa-stats (QA engineer breakdown export)
- /export/engineer-deepdive (erasure deep dive)

## Recent Changes (Feb 2026)
- Fixed non-data-bearing QA query implementation in qa_export.py.
- QA dashboard: trend panels, flip panels, metrics rotation, medals expanded to 6.
- QA counts deduplicated via DISTINCT sales_order in audit_master queries.
- Managers excluded from daily record calculations.

## Known Issues / Risks
- QA totals combine QA App + DE + Non-DE; verify no double counting in any views.
- Period handling differs across endpoints; verify all periods are supported consistently.
- All-time QA trend uses last 30 days window (not full historical).

## Current Focus
- Device tracking improvements to prevent lost devices (like 12745375 that went missing July 2025).
- Audit sheets for operational visibility: Unpalleted Devices, Stale Devices.
- Location enrichment in exports to show where devices are.
- QA Stats UX polish (more visual summary, reduce raw data exposure on UI).
- Verify export correctness for weekly/monthly periods.
- Power BI API endpoints exist but need refresh/validation.

## Device Tracking Features (Feb 2026)

### Device Search (Admin Panel)
- Search any stock ID to see complete timeline across all data sources.
- Data sources queried: ITAD_asset_info, Stockbypallet, ITAD_pallet, ITAD_QA_App, audit_master (DE+Non-DE), ITAD_asset_info_blancco, local SQLite erasures.
- Timeline shows: timestamp, source table, stage, user, and details.
- Color-coded by stage: sorting (blue), QA (green), erasure (orange), info (gray).
- Endpoint: /api/device-lookup/{stock_id}

### New Export Sheets
1. **Unpalleted Devices Audit** - devices that completed QA but have no pallet assigned. Helps catch devices falling through the cracks.
2. **Stale Devices Report** - devices with last activity 7+ days ago. Flags potentially lost or stuck devices.

### Enhanced Device History Columns
- **Last Asset Loc**: location field from ITAD_asset_info.
- **Roller Location**: roller_location field from ITAD_asset_info.
- **Days Since Update**: calculated days since last_update field.

### MariaDB Fields Discovered (Future Use)
From ITAD_asset_info: location, roller_location, last_update, stage_current, stage_next, received_date, quarantine, quarantine_reason, quarantine_raised_by, current_stage_raised_by, next_stage_raised_by, process_complete.

## Current Focus
- QA Stats UX polish (more visual summary, reduce raw data exposure on UI).
- Verify export correctness for weekly/monthly periods.
- Power BI API endpoints exist but need refresh/validation.

## UI Goals (QA)
- Visual first: trends, comparisons, and highlights on screen; raw detail in exports.
- Match Erasure styling and alignment for TV readability.
- Keep animations smooth and low CPU for Firestick/TV browsers.

## Open Items
- Review QA layout for TV readability and consistency with Erasure dashboard.
- Validate QA export sheets for all period scopes.
- Plan Power BI refresh and endpoint coverage.

## Power BI Integration
- Power BI pulls data from the live Render dashboard via API endpoints.
- Current semantic model: Query table with columns data.date, data.erased, data.booked_in, data.qa.
- Existing measures: Today Erased, Yesterday Erased, MTD Erased, Total Erased, Best Day Erased, Daily Target, Monthly Target, Days Elapsed MTD, Rolling 7D Avg, Target Achievement %, Total Booked In, Total QA, Is Zero, MTD Target (Dynamic).
- Pages: Executive Dashboard, Detailed Breakdown, Key Metrics.
- Last refreshed: 2026-02-09 (data dated 2026-02-04).
- Naming: rename report from "Warehouse Erasure Stats" to "Berry Hill Warehouse Stats".

### Terminology
- "Power BI dash" / "power" = Power BI report/service.
- "main dashboard" = web dashboard on Render (this VSCode project).

### Power BI Goals
- Professional KPI tracking for erasure, QA/Sorting, and per-engineer performance.
- Track averages and rolling trends to infer targets (since official targets are hard to get).
- Engineer deep-dive: daily/weekly/monthly averages, trajectories, consistency scores.
- Visual parity with web dashboard where possible.
- Exec Dashboard: cleaner layout, smaller cards, less "school presentation" feel; add QA summary.

### Proposed Power BI Structure
1. **Executive Dashboard** (combined overview)
   - Erasure: Today, MTD, Best Day, Rolling 7D Avg, Target Achievement %.
   - QA: Today QA'd, MTD QA'd, Data Bearing vs Non-Data Bearing split, Sorting total.
   - Small trend sparklines; avoid large card blocks.

2. **Erasure Section**
   - KPIs: day-by-day, week-by-week, month-by-month totals.
   - Engineer breakdown: table + bar chart of daily counts.
   - Device detail: model, drive size, durationSec (to explain "why" figures differ).
   - Multiple sheets if needed for clarity (e.g., Erasure Overview, Engineer Drilldown, Device Analysis).

3. **QA / Sorting Section**
   - Story flow: devices erased -> QA'd (data bearing / non-data bearing) -> sorted.
   - KPIs: QA totals by period, DE vs Non-DE breakdown.
   - Sorting totals (ITAD_QA_App scans).
   - Engineer performance: QA counts, consistency, daily pattern.

### Data Needed from API
- Erasure daily stats: date, erased, booked_in.
- Erasure engineer stats: initials, date, count, device details (model, driveSize, durationSec).
- QA daily stats: date, qaApp, deQa, nonDeQa, total.
- QA engineer stats: name, date, qaScans, deQaScans, nonDeQaScans.
- Sorting: ITAD_QA_App daily totals.

### Power BI Refresh Issues
- Possible auth blocking: if endpoints require auth header, Power BI refresh will fail.
- Solution: allow `/api/powerbi/*` with a static API key via header or query string.
- API key source: `POWERBI_API_KEY` env var or generated in powerbi_api_key.txt.
- Check CORS and network access from Power BI service to Render URL.

### Power BI API Endpoints (existing or needed)
- /api/powerbi/daily-stats (date, erased, booked_in, qa, qaApp, deQa, nonDeQa, qaTotal) — updated.
- /api/powerbi/engineer-stats (per-engineer daily counts) — exists.
- /api/powerbi/erasure-events (event-level detail with device info) — exists.
- /api/powerbi/qa-daily (date, qaApp, deQa, nonDeQa, total) — added.
- /api/powerbi/qa-engineer (name, date, qaScans, deQaScans, nonDeQaScans) — added.
- /api/powerbi/device-history (erasure + sorting device log) — added.

### Power BI Help Scope
- I can help design API schemas, write DAX measures, and structure report layouts.
- I cannot interact with Power BI service directly (no MCP tool), but I can generate .pbix import scripts, M queries, and DAX code.
- For Copilot in Power BI: requires admin to enable; in the meantime I can provide DAX/M snippets here.

## Change Log
- 2026-02-12: Fixed Bottleneck Radar "Unexpected token '<'" error - added content-type check before JSON parsing to handle 502/HTML error responses gracefully (admin.html, manager.html).
- 2026-02-12: Optimized Bottleneck Radar memory usage - replaced Python-side loops with SQL COUNT/GROUP BY aggregation to stay under Render's 512MB limit (qa_export.py: get_unpalleted_summary).
- 2026-02-12: Fixed Bottleneck Radar showing historical data instead of current warehouse state - added 7-day recency filter (last_update >= DATE_SUB(NOW(), INTERVAL 7 DAY)) to all bottleneck queries.
- 2026-02-12: Added days_threshold parameter to /api/bottlenecks endpoint (1-90 days, default 7).
- 2026-02-12: Added new functions: get_unpalleted_summary() (SQL aggregation), get_unpalleted_devices_recent() (recency-filtered list).
- 2026-02-12: Refined Bottleneck Radar roller logic to use Blancco/erasure presence for "Awaiting Erasure" detection and to classify devices as: Awaiting Erasure (data-bearing, no blancco/erasure), Awaiting QA (erased or non-data-bearing but no destination), Awaiting Sortation (QA'd but no pallet ID). Updated `get_roller_queue_status` in `qa_export.py` to include these rules.
- 2026-02-11: Added Device Search UI to admin panel - search any stock ID to see timeline across 7 data sources (ITAD_asset_info, Stockbypallet, ITAD_pallet, ITAD_QA_App, audit_master, ITAD_asset_info_blancco, local_erasures). Color-coded by stage type.
- 2026-02-11: Added /api/device-lookup/{stock_id} endpoint for device timeline queries.
- 2026-02-11: Added Unpalleted Devices Audit sheet to QA export (devices that completed QA but have no pallet assigned).
- 2026-02-11: Added Stale Devices Report sheet to QA export (devices inactive for 7+ days).
- 2026-02-11: Added Last Asset Location, Roller Location, Days Since Update columns to Device History and Device Log by Engineer sheets.
- 2026-02-11: Added export loading modal with spinner for long-running exports.
- 2026-02-11: Fixed Device History duplicates when merging QA events - added Python-side deduplication by (timestamp, stockid, stage, user).
- 2026-02-11: Database exploration: discovered useful unused fields in ITAD_asset_info (location, roller_location, last_update, stage_current, stage_next, received_date, quarantine fields).
- 2026-02-11: Enriched QA device events with ITAD_asset_info location data (asset_location, roller_location, last_update).
- 2026-02-10: Fixed Power BI daily-stats and engineer-stats endpoints to include today's live data from erasures table (not just daily_stats/engineer_stats tables which only sync periodically).
- 2026-02-10: Added device history export sheet (erasure + sorting) and Power BI device-history endpoint.
- 2026-02-10: Device history export grouped by date, collapsed by default, with shaded DATE/DEVICE headers.
- 2026-02-09: Power BI semantic model created with 5 tables (Daily Stats, Engineer Stats, Erasure Events, QA Daily, QA Engineer) and 20 measures. Date table linked. **BLOCKED**: Daily Stats numeric columns stored as Text type; need to convert erased, booked_in, qa, qaApp, deQa, nonDeQa, qaTotal to Whole Number in Power Query before visuals work.
- 2026-02-10: Separated QA totals from Sorting (qaApp) across all endpoints and UI cards. QA cards now show DE + Non-DE only; Sorting tracked separately.
- 2026-02-10: Fixed Power BI dynamic date range in M queries (removed hard-coded end_date). Now uses current year (Jan 1 to today).
- 2026-02-10: Fixed Power BI daily-stats and engineer-stats to always refresh today's data from live erasures table (overwrite stale rows).
- 2026-02-10: Fixed Power BI daily-stats endpoint to include today's data even when daily_stats table has stale rows.
- 2026-02-09: Power BI API key configured (87786640-8358-4aad-a092-005a47fb92a8) in Render env vars.
- 2026-02-09: Added persistent Power BI API key and QA columns on daily-stats.
- 2026-02-09: Added Power BI API key bypass and QA Power BI endpoints.
- 2026-02-09: Fixed non-data-bearing QA comparison query in qa_export.py; cleaned misplaced block.
- 2026-02-09: Added PROJECT_STATUS.md to track project context.
- 2026-02-09: Documented Power BI integration goals and current state.

## Working Agreement
- Update this file after significant changes, decisions, or new endpoints.

## Working Agreement
- Keep this file updated after each significant change or decision.

## Power BI Current Status
- **Semantic Model**: Created in Power BI Service.
- **Tables**: Daily Stats, Engineer Stats, Erasure Events, QA Daily, QA Engineer (all loaded from API endpoints).
- **Date Table**: Created with Day, Month, Month Name, Year columns. Relationships set (1:* from Date to each fact table).
- **Measures**: 20 core measures for Erasure (Today, MTD, Rolling 7D, Target Achievement), QA (Today, MTD, Rolling 7D, DE %, Non-DE %), and Targets (Daily Target, Days Elapsed MTD, MTD Target).
- **Data Types**: Fixed in Power Query (erased, booked_in, qa, qaApp, deQa, nonDeQa, qaTotal all converted to Whole Number).
- **Date Range**: Dynamic M query using Jan 1 of current year to today.
- **QA vs Sorting**: qaTotal = DE + Non-DE only (QA work); qaApp = Sorting scans (separate).
- **Next**: Build Exec dashboard with KPI cards, QA split donut, trend lines, and engineer table.

## Power BI Exec Dashboard Plan
1. **Row 1**: Today Erased, MTD Erased, Rolling 7D Avg (Erased), Target Achievement %
2. **Row 2**: Today QA, MTD QA, Rolling 7D Avg (QA), QA Split (Data Bearing vs Non-Data Bearing) donut
3. **Row 3**: Erasure trend line, QA trend line
4. **Bottom**: Top 5 Engineers table (initials, count)
