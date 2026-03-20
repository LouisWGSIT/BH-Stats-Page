# Project Status

## Summary
Warehouse stats dashboards for TV displays and staff access. The app provides Erasure and QA dashboards with role-based access and export capabilities. Frontend is static HTML/CSS/JS; backend is FastAPI with MariaDB (QA) and SQLite (erasures). This document summarizes current status, recent work, priorities, and suggested next steps.

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

## Recent Changes (Feb–Mar 2026)
- 2026-02-16: Added conservative co-location / temporal-correlation inference to device lookup: inspects up to 20 co-located devices on the same pallet and adds small, clearly-labeled inferred evidence (low confidence, capped influence) to improve hypotheses when direct evidence is sparse. (`device_lookup.py`)
 - 2026-02-17: Device lookup improvements — canonicalized Blancco handling and hypothesis updates.
    - Suppress duplicate MariaDB `ITAD_asset_info_blancco` rows when a local server-message erasure (`local_erasures`) exists; merge MariaDB copies into the local provenance so the timeline shows a single authoritative Blancco row (engineer initials, job_id, timestamp).
    - Added explicit `Data Erasure (by <initials>)` hypothesis (lower-score than QA) and enriched hypotheses evidence with Blancco/local erasure details so UI displays both QA-confirmed location and erasure as separate readable entries.
    - Prevented erasure records from overwriting QA `last_known_user` so the QA-confirmed hypothesis remains the top, actionable signal.
    - Removed the generic `Location (asset_info)` timeline row to reduce noise; `asset_info` metadata is still available in the response but no longer shown as a top-line timeline entry.
    - Outcome verified locally: timeline now shows the QA event and a single `Blancco record by <initials>` row; hypotheses list QA as primary and Data Erasure as secondary.
    - Next: user will scan the device to a pallet (Owen). After that, I'll validate the deployed instance to ensure the most-likely location updates correctly. Visual polish (UI colours/text) is planned next — will follow up once behaviour is stable.
- 2026-02-16: UI tweak — removed inline AI paragraph above "Explain more" so long-form `ai_explanation` only appears when expanded in the admin/manager device lookup views.
- 2026-02-16: Ran import smoke tests for key modules (`device_lookup`, `qa_export`, `services.db_utils`, `manager.bottleneck`) — all imports OK. Committed and pushed changes (commit b3dfd02).
 - 2026-02-16: Updated wording and UI for device lookup explanations: the full, human-friendly AI-style paragraph is now shown inline (no "Explain more" toggle). Explanations avoid internal table names and present clear, actionable signals and next steps (e.g., "Blancco (erasure) record", "Pallet X — inspect contents and recent scans").
 
- Fixed non-data-bearing QA query implementation in qa_export.py.
- QA dashboard: trend panels, flip panels, metrics rotation, medals expanded to 6.
- QA counts deduplicated via DISTINCT sales_order in audit_master queries.
- Managers excluded from daily record calculations.

### March 2026 (recent, actionable)
- 2026-03-09: Added `POST /hwid` endpoint and `GET /hwid` health check to capture HashID data from USB boot scripts. Logs are written to `logs/hwid_log.jsonl`. (See `main.py`.)
- 2026-03-09: Endpoint authentication re-uses existing `WEBHOOK_API_KEY` behavior (checks `x-api-key` or `Authorization: Bearer ...`).
 - 2026-03-09: Added `POST /hwid` endpoint and `GET /hwid` health check to capture HashID data from USB boot scripts. Logs are written to `logs/hwid_log.jsonl`. (See `main.py`.)
 - 2026-03-09: Endpoint authentication re-uses existing `WEBHOOK_API_KEY` behavior (checks `x-api-key` or `Authorization: Bearer ...`).
 - 2026-03-20: Addressed gradual memory growth observed on Render:
    - Replaced unbounded in-process caches with a small thread-safe TTL/LRU cache (`TTLCache`) for `QA_CACHE`, `_summary_cache`, and dashboard caches to avoid unbounded memory accumulation.
    - Added optional `tracemalloc` snapshotting and an admin-only endpoint `POST /admin/memory-snapshot` to capture heap allocation top-lists for post-mortem analysis. Controlled by `ENABLE_TRACEMALLOC` and `TRACE_SNAPSHOT_THRESHOLD_MB` env vars.
    - Changed Excel export flow to write the workbook to a temporary file and serve it via `FileResponse` (deleted after send) to avoid holding large BytesIO objects in the web dyno memory.
    - Added RSS logging around heavy endpoints to correlate memory use with requests; `psutil` is optional (falls back to `resource` or `/proc` parsing).

These March entries reflect recent backend work that should be deployed to Render and validated with the USB boot/test script.

## Known Issues / Risks
- QA totals combine QA App + DE + Non-DE; verify no double counting in any views.
- Period handling differs across endpoints; verify all periods are supported consistently.
- All-time QA trend uses last 30 days window (not full historical).


## Database Safety: MariaDB transactions

- Severity: HIGH — long-held MariaDB transactions can acquire locks that block other updates and cause timeouts (we observed a 2-hour lock incident). Treat this as a first-class operational risk.
- Rules to follow:
  - Always use explicit `commit()` or `rollback()` after any transaction that modifies data. Do not rely on process exit to flush transactions.
  - Keep transactions as short as possible: fetch required values first, then open a transaction only for the minimal set of writes.
  - For read-only queries, prefer running them outside explicit transactions (autocommit / read-only connection) to avoid accidental lock escalation.
  - Wrap DB work in try/except/finally blocks and ensure `conn.close()` in the `finally` block.
  - Use sensible connection timeouts and server-side statement timeouts where available to avoid runaway queries.
  - Avoid long-running SELECT ... FOR UPDATE unless strictly necessary — they escalate locks.
  - Monitor for locks: use `SHOW PROCESSLIST` and `INFORMATION_SCHEMA.INNODB_LOCKS` when investigating live issues; be prepared to `KILL` problematic sessions cautiously.

- Example Python pattern (use in `qa_export.py` or any MariaDB write path):

```python
conn = get_mariadb_connection()
try:
   cur = conn.cursor()
   # Keep transactional work minimal
   cur.execute("UPDATE my_table SET x=%s WHERE id=%s", (val, id_))
   conn.commit()
except Exception:
   conn.rollback()
   raise
finally:
   try:
      cur.close()
   except Exception:
      pass
   conn.close()
```

- Operational action items:
  - Add connection/statement timeouts in production (Render env) and enable query logging for long-running statements.
  - Add a lightweight health endpoint that performs a quick read-only check against MariaDB and fails fast if the DB is unresponsive.
  - When running any maintenance or long exports, notify the team and run during off-peak windows.

Treat the above as mandatory guidelines — commit/rollback discipline and short transactions will prevent cross-team outages.

## Current Focus
- Device tracking improvements to prevent lost devices (like 12745375 that went missing July 2025).
- Audit sheets for operational visibility: Unpalleted Devices, Stale Devices.
- Location enrichment in exports to show where devices are.
- **Device Lookup UI/UX polish (hypotheses grouping, color split, tag logic, clarity, and modern look) is now complete and deployed.**
- QA Stats UX polish (more visual summary, reduce raw data exposure on UI).
- Verify export correctness for weekly/monthly periods.
- Power BI API endpoints exist but need refresh/validation.

## Current Status (concise)
- **Backend:** Stable FastAPI codebase. Recent additions include HWID capture endpoints in `main.py` and several fixes in `qa_export.py` and `device_lookup.py`.
- **Frontend:** Static dashboards (TV-friendly) are up-to-date; manager device lookup UI has been polished and deployed.
- **Data:** MariaDB provides QA data; SQLite stores erasures. Power BI endpoints exist but require refresh and type checks.
- **Deployments:** Ready for redeploy after latest commits; Render needs to be redeployed to pick up `POST /hwid`.

## Next Actions / Recommendations
- **Deploy & Test:** Redeploy to Render, run the PowerShell tester against `/hwid` and confirm `200 OK` and that `logs/hwid_log.jsonl` receives entries.
- **Separate Key (optional):** Consider adding a dedicated `HWID_API_KEY` env var instead of re-using `WEBHOOK_API_KEY` to isolate access.
- **Rotation & Retention:** Add log rotation / retention for `logs/hwid_log.jsonl` (daily rotate or push to centralized logs like Papertrail/LogDNA).
- **Validation:** Add basic schema validation for the HWID payload (optional) to prevent malformed entries.
- **Monitoring:** Add an alert/heartbeat for the `GET /hwid` health check or a periodic task that verifies log writes.

### Recent Code-Only Device Lookup Optimizations (ready for test)

The following code-only changes were implemented to make `device_lookup` fast and safe without any DB schema changes:

- Added an in-memory TTL cache for device lookups (`DEVICE_LOOKUP_CACHE_TTL`, default 45s).
- Added a fast short-circuit path that immediately returns when strong local evidence exists (confirmed_locations, Stockbypallet, or recent `ITAD_asset_info`).
- Rewrote QA queries to use datetime range comparisons (no DATE(...) wrapping) so indexes can be effective when DB-side indices are added by ops.
- Added a query timeout wrapper (`DEVICE_LOOKUP_QUERY_TIMEOUT`, default 5s) to bound per-neighbor DB calls and avoid blocking the web dyno.
- Reduced neighbor scan limits and added batching (`DEVICE_LOOKUP_NEIGHBOR_LIMIT`, default 8; `DEVICE_LOOKUP_NEIGHBOR_BATCH`, default 5) to cap work done per lookup.
- Wrapped per-neighbor DB calls with timeouts and added logging warnings for timeouts to aid diagnosis.
- Added an `ops/device_lookup_test.py` perf script to run repeat lookups and report timings for sample stockids.

These changes are code-only and safe to deploy; they aim to make typical interactive device lookups return in a few seconds or less. Please deploy and run the perf script or exercise the manager UI to validate responsiveness. If you see slow cases, capture the `stockid` and logs and I'll tune the limits or add finer-grained telemetry.

## Actionable Backlog (short)
- **High:** Verify Power BI auth and refresh; ensure `POWERBI_API_KEY` is configured in Render.
- **Medium:** Add `HWID_API_KEY` and rotate keys; add payload schema validation and unit tests for `main.py` hooks.
- **Low:** Export improvements for additional sheets (device history flattening, BI-friendly types), and UI polish as requested by stakeholders.

### Planned DB & Device Lookup Work (March 2026)

We're prioritising performance and safety for the `device_lookup` flow. The following five tasks will be worked on first (user requested). These are listed in order of low-risk / high-impact changes to reduce query cost and make lookups safe for back-to-back use:

1. Rewrite queries to avoid `DATE(column)` wrapping so indexes can be used.
   - Replace `WHERE DATE(added_date) >= DATE_SUB(NOW(), INTERVAL ? DAY)` with `WHERE added_date >= DATE_SUB(NOW(), INTERVAL ? DAY)` in `main.py`, `qa_export.py`, and any other QA lookup code.
   - Rationale: applying functions to column values prevents index seeks and forces full scans. Comparing the raw `DATETIME`/`TIMESTAMP` allows efficient range scans.

2. Create a composite index on `ITAD_QA_App(stockid, added_date)` (and optionally include frequently-selected fields to make it a covering index).
   - Example SQL (test in staging first):
     ```sql
     CREATE INDEX idx_itad_qa_stockid_added_date ON ITAD_QA_App (stockid, added_date);
     ```
   - Rationale: lets the DB quickly find recent rows for a specific stockid.

3. Run `EXPLAIN` before/after index creation to confirm the query plan uses the new index and to measure rows scanned/reduced.
   - We'll capture `EXPLAIN` output for representative queries (30-day and 120-day variants) and keep the outputs for audit.

4. Add sensible limits / aggregation to QA queries where possible.
   - Use `LIMIT`/bounded result windows for UI timelines and offer a separate 'full history' mode for long exports.
   - Prefer `COUNT`/`GROUP BY` for summary views rather than fetching every row.

5. Short-circuit heuristics in `device_lookup` to stop QA/history scanning early when high-confidence provenance is already found.
   - Examples: if `asset_info` + `local_erasures` + `Stockbypallet` provide a strong location signal, skip the heavier QA history scan, or only request a small sample of QA rows.

Status: Working on items 1–5 now; code changes and index recommendations will be implemented in staging, validated with `EXPLAIN`, then rolled to production during a maintenance window.

#### Step 2 — Index DDL & EXPLAIN (DBA instructions)

You have readonly permissions on MariaDB. Below are safe, copy-paste-ready commands and example `EXPLAIN` queries your DBA or infra team can run in staging (or a maintenance window) to create the recommended index and validate query plans. Ask them to capture the `EXPLAIN` output (JSON or text) and share it back so we can confirm the new plan reduces scanned rows and uses the index.

- Recommended (simple) index to create in staging first:

```sql
-- Basic composite index
CREATE INDEX idx_itad_qa_stockid_added_date
   ON ITAD_QA_App (stockid, added_date);
```

- If your MariaDB build supports online DDL and you want minimal locking, consider:

```sql
ALTER TABLE ITAD_QA_App
   ADD INDEX idx_itad_qa_stockid_added_date (stockid, added_date)
   ALGORITHM=INPLACE, LOCK=NONE;
```

- Representative queries to `EXPLAIN` before and after the index (use a real `stockid` and substitute `{start_dt}` / `{end_dt}` as timestamps):

```sql
-- Device-specific recent rows (30 days)
EXPLAIN FORMAT=JSON
SELECT stockid, added_date, username, scanned_location
FROM ITAD_QA_App
WHERE stockid = '12345678'
   AND added_date >= '{start_dt}'
   AND added_date <  '{end_dt}'
ORDER BY added_date DESC
LIMIT 100;

-- Period aggregation (30-day window)
EXPLAIN FORMAT=JSON
SELECT DATE(added_date) as scan_date, COUNT(*) as total_scans
FROM ITAD_QA_App
WHERE added_date >= '{start_dt}'
   AND added_date <  '{end_dt}'
GROUP BY DATE(added_date)
ORDER BY scan_date;
```

- What to look for in `EXPLAIN`:
   - `key` or the JSON `query_block` -> `table` -> `used_index` showing `idx_itad_qa_stockid_added_date` (or the index name you created).
   - A significant reduction in `rows` scanned for the representative queries (compare before/after).
   - If the plan still shows `ALL` / full table scan, we'll need to validate the predicate shapes match the index (e.g., `stockid = ... AND added_date >= ...`).

- Optional: create a covering index if the queries select a small fixed set of columns frequently (beware index size):

```sql
-- Covering index example (only if sizing is acceptable)
CREATE INDEX idx_itad_qa_stockid_addeddate_cover
   ON ITAD_QA_App (stockid, added_date, username, scanned_location);
```

- After creating the index, capture `EXPLAIN FORMAT=JSON` outputs for both the 30-day and 120-day representative queries and paste them into a gist or a repo file (e.g., `ops/explain_30d.json`, `ops/explain_120d.json`) so we can review.

- If your DB team needs a safe rollback path, they can drop the index:

```sql
DROP INDEX idx_itad_qa_stockid_added_date ON ITAD_QA_App;
```

If you'd like, I can also prepare a small README-style snippet or a one-shot SQL script that runs the `EXPLAIN` queries for a given `stockid` and time windows and writes results to files. Tell me a sample `stockid` (or confirm you want me to use placeholders) and I'll prepare that next.


## Agent Onboarding Notes (Feb 2026)
- **Frontend:**
   - manager.html: Device lookup UI is now grouped, color-coded, and decluttered as described below. All tag logic and visual polish is up to date as of 2026-02-18.
   - index.html, admin.html: Standard dashboards, see prior sections for details.
   - styles.css: Contains all color and badge styles for device journey hypotheses.
- **Backend:**
   - main.py, device_lookup.py: FastAPI endpoints for device lookup and dashboard data. No changes needed for recent UI/UX work; all required data is already provided.
   - database.py, qa_export.py, engineer_export.py: Data access and export logic. See prior change log for recent fixes and enhancements.
- **Recent priorities:**
   - UI/UX for device lookup hypotheses is now visually clear, modern, and matches user requirements. No further frontend changes are pending unless new feedback is received.
   - Backend is stable; focus is on data accuracy and export correctness.
- **How to get up to speed:**
   - Review manager.html for the latest device lookup UI logic and tag/color handling.
   - See device_lookup.py for backend data structure and endpoint logic.
   - PROJECT_STATUS.md (this file) is kept up to date after each significant change—check here for context before making further changes.
### 2026-02-18: Device Lookup UI/UX Overhaul
   - Major improvements to the device journey hypotheses section in the device lookup (manager.html):
      - Hypotheses are now grouped by type (Sorting, QA, Erasure) with collapsible headers and a "last updated" timestamp per group.
      - Distinct color coding: Sorting (blue), QA (green), Erasure (red).
      - Only the top hypothesis is marked as "Most recent"; all others are untagged.
      - All Blancco tags and inferred tags have been removed for clarity.
      - The explanation/paragraph above the Confirm button has been removed for a cleaner UI.
      - Hover effects, icons, and visually distinct badges added for each hypothesis type.
      - Timeline section is now collapsible for better readability.
   - All changes are implemented in manager.html (static HTML/JS/CSS); backend (device_lookup.py) provides all required data, no changes needed for these UI/UX requests.
   - Changes were iteratively tested, committed, and pushed after user feedback and screenshot validation.
   - See commit: "UI/UX: Remove explanation/paragraph above Confirm, only top hypothesis gets 'Most recent', blue/green/red color split for Sorting/QA/Erasure, remove Blancco tag entirely."

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
- 2026-02-12: **Project Review Completed** - Verified all code is working as intended. No conflicting code, duplicates, or unused code found. QA export functions now correctly include devices with DE/blancco evidence. Device token storage enhanced with SQLite fallback. All modules import successfully. Scripts directory contains development/testing tools that are useful to keep.
- 2026-02-12: Fixed Bottleneck Radar "Unexpected token '<'" error - added content-type check before JSON parsing to handle 502/HTML error responses gracefully (admin.html, manager.html).
- 2026-02-12: Optimized Bottleneck Radar memory usage - replaced Python-side loops with SQL COUNT/GROUP BY aggregation to stay under Render's 512MB limit (qa_export.py: get_unpalleted_summary).
- 2026-02-12: Fixed Bottleneck Radar showing historical data instead of current warehouse state - added 7-day recency filter (last_update >= DATE_SUB(NOW(), INTERVAL 7 DAY)) to all bottleneck queries.
- 2026-02-12: Added days_threshold parameter to /api/bottlenecks endpoint (1-90 days, default 7).
- 2026-02-12: Added new functions: get_unpalleted_summary() (SQL aggregation), get_unpalleted_devices_recent() (recency-filtered list).
- 2026-02-12: Refined Bottleneck Radar roller logic to use Blancco/erasure presence for "Awaiting Erasure" detection and to classify devices as: Awaiting Erasure (data-bearing, no blancco/erasure), Awaiting QA (erased or non-data-bearing but no destination), Awaiting Sortation (QA'd but no pallet ID). Updated `get_roller_queue_status` in `qa_export.py` to include these rules.
 - 2026-02-12: Treat `NOPOST01` / `NOPOST02` pallet assignments as still in-process (included on Bottleneck Radar) because these items require out-of-unit wiping before QA/sortation. Updated queries to treat `pallet_id LIKE 'NOPOST%'` as unpalleted.
 - 2026-02-12: Found IA personnel evidence: `zhilner.deguilmo@greensafeit.com` appears in `ITAD_asset_info.de_completed_by` and `audit_master.user_id`, with many rows referencing `IA-ROLLER1` and stock allocations — likely IA operator using the booking tool. `Leah.Haymes` and `Nathan.Hawkes` returned no matches in the quick search; I can run targeted queries if you want.
- 2026-02-11: Added Device Search UI to admin panel - search any stock ID to see timeline across 7 data sources (ITAD_asset_info, Stockbypallet, ITAD_pallet, ITAD_QA_App, audit_master, ITAD_asset_info_blancco, local_erasures). Color-coded by stage type.

## How to verify / test key items
- HWID endpoint (quick):
   - `GET /hwid` — should return a small JSON status confirming endpoint is live.
   - `POST /hwid` with header `x-api-key: <WEBHOOK_API_KEY>` and a JSON body — should return `{"status":"ok"}` and append a JSON line to `logs/hwid_log.jsonl` on the instance.
- PowerShell example (tester):
   - Use the existing tester flow (example sent earlier). Ensure the URL is `https://<your-app>/hwid` (no API key in path).

## Ownership / Contacts
- **Owner:** Louis (repo maintainer)
- **Notes:** Update this file after major changes or deploy-affecting commits.

## Working Agreement
- Keep this file updated after each significant change, endpoint addition, or operational decision.


Naming conventions and caveats
----------------------------
- The upstream databases use inconsistent naming for workflow stages and audit entries. Two notable examples:
   - Blancco erasure records are stored in `ITAD_asset_info_blancco` and commonly refer to an erasure job. Historically we surfaced those as "Erasure (Successful)" rows in the timeline. To reduce confusion the application now presents these rows as a canonical `Erasure station` timeline event and includes the raw `blancco_status` and operator (`is_blancco_record=true`) so the UI can show Blancco evidence without creating a separate "Erasure (Blancco)" search location.
   - `audit_master` entries sometimes use names (or log text) that suggest an operator "erased" or "processed" a device when in practice the action recorded was a QA scan or manual confirmation. We do not change upstream data; instead the app maps these signals into clearer UI labels (`QA Data Bearing`, `QA Non-Data Bearing`, `Erasure station`) and exposes provenance so operators can inspect the raw audit text before acting.

Notes for future work
---------------------
- If the database schema changes (field names added/removed in `ITAD_asset_info_blancco`), the app probes `INFORMATION_SCHEMA` and falls back to a safe projection. Keep this behavior when refactoring timeline ingestion.
- Consider a small onboarding doc for QA and Erasure teams explaining how their database labels map to UI terms; this reduces support friction when audit text is ambiguous.
 - Long-term timeline improvements planned:
    - Use a canonical set of stages (IA, Erasure station, QA Data Bearing, Sorting, Pallet) and always attach raw provenance fields (`source_table`, `operator`, `raw_status`, `job_id`) to timeline events.
    - Compute recency from "meaningful" signals only (QA scans, Blancco/erasure, confirmed_locations, pallet evidence) so generic `ITAD_asset_info` metadata updates do not hijack the recency boost.
    - Merge near-duplicate timeline rows (events within a short window, default 60s) into a single timeline entry with combined provenance to avoid double-counting (e.g., a Blancco record and an audit_master QA entry recorded at the same time).
    - Maintain and document a mapping table so UI labels consistently map to upstream audit text and schema fields; this file serves as the single source of truth for these mappings.

These changes are being implemented incrementally: recency filtering and Blancco canonicalization are done; next steps include merge-on-render and a small onboarding doc for operators.
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

## Recent Changes (2026-02-17)
- 2026-02-17: Device lookup: normalization, dedupe, and pallet annotation (commit f66e3c3)
    - Root cause: QA scan + co-location inference produced near-duplicate "IA Roller 1" hypotheses because location strings were formatted differently and the co-location heuristic keyed on the raw text.
    - Fixes implemented in `device_lookup.py`:
       - Added `normalize_loc()` to canonicalize location strings for de-duplication and co-location checks.
       - Keyed candidate merging on normalized location so inferred and explicit QA candidates are collapsed.
       - Pallet candidates are now annotated with the recent QA origin (e.g., "Pallet A1005849 (Refurbishment) from IA Roller 1") so the UI shows a single authoritative pallet entry while preserving QA provenance.
       - Blancco/erasure rows from MariaDB are merged into local erasure provenance (no DB writes) so the timeline shows a single canonical Blancco/erasure event.
    - Tools & verification:
       - Added a read-only schema-aware inspector `tools/mariadb_readonly_check.py` used to safely probe MariaDB (INFORMATION_SCHEMA-aware, safe SELECT lists). Inspector output for `stockid=12963675` was saved for audit and shows QA scan then pallet assignment.
       - Verified locally by calling `get_device_location_hypotheses('12963675')`: before the change there were duplicate Roller1 entries; after the change the output shows one pallet candidate annotated with the QA origin and QA evidence retained in provenance.
    - Notes / next steps:
       - No writes to upstream DBs were performed; all DB access is read-only.
          - Please redeploy to Render and verify the UI shows the single pallet entry annotated with QA origin; report any regressions and I'll iterate on label/score tuning.
          - Optional: add a one-line entry in this file referencing the inspector JSON output (I can add that if you want).

 - 2026-02-18: Simplified hypotheses default (recency-first)
    - The `SIMPLE_HYPOTHESES` recency-only mode has been made the default behavior. It short-circuits the heavier inference engine and returns deterministic, timestamp-ranked hypotheses (most recent = 100%).
    - To opt out and run the full heuristic engine, set `SIMPLE_HYPOTHESES=0` in the environment and redeploy.
