# Project Status (Updated 31 March 2026)

## Summary
This project is now in a much cleaner, modular state and is stable on Render after recent refactors.

- Backend moved from a monolithic `main.py` to router-based modules under `backend/app/routes/`.
- Admin tooling is working (activity view, memory trend, initials fixes, device diagnostics).
- Dashboard remains live and functional for both Erasure Stats and QA Stats.
- Bottleneck logic is intentionally deferred for deeper correctness work later.

## Current Architecture

### Backend
- Entry: `main.py` (app wiring, auth middleware, startup hooks, route composition).
- Routers:
  - `backend/app/routes/auth.py`
  - `backend/app/routes/admin_*.py`
  - `backend/app/routes/erasure_insights.py`
  - `backend/app/routes/qa_insights.py`
  - `backend/app/routes/metrics_analytics.py`
  - `backend/app/routes/webhooks.py`
  - `backend/app/routes/device_lookup.py`
  - `backend/app/routes/bottlenecks.py`
  - `backend/app/routes/static_pages.py`
  - `backend/app/routes/hwid.py`
- Shared runtime tasks: `backend/app/runtime_tasks.py`
- Data layers:
  - MariaDB via `services/db_utils.py` and `backend/qa_export.py`
  - SQLite via `backend/database.py`

### Frontend
- Pages in `frontend/pages/`
- JS in `frontend/js/app.js`
- CSS in `frontend/css/styles.css`
- Dashboard modes: Erasure Stats and QA Stats (toggle in UI)

### Compatibility Shims
Root files like `database.py`, `qa_export.py`, `excel_export.py`, etc. currently act as import shims to `backend/*` modules for compatibility with older scripts/tests.

## Security and Secrets Status

### Completed in this update
- Removed tracked Power BI key file.
- Removed hardcoded export bearer password in frontend.
- Removed hardcoded default admin/manager passwords from backend.
- Removed hardcoded default webhook API key from backend.
- Replaced concrete MariaDB host/user defaults with placeholders.
- Expanded `.gitignore` to cover local DB/log/inspection artifacts.
- Untracked local runtime artifacts from git:
  - `db.sqlite`
  - `erasures.db`
  - `logs/activity.sqlite`
  - `scripts/inspect_output.json`
  - `scripts/inspect_summary.json`

### Important note
Old secrets that were committed historically should still be considered compromised and rotated.

## Webhook Key Clarification

- `WEBHOOK_API_KEY` is used for:
  - `/hooks/erasure`
  - `/hooks/erasure-detail`
  - `/hooks/engineer-erasure`
  - `/hwid`
- Ingestion endpoint `/api/ingest/local-erasure` uses:
  - `INGESTION_SECRET` (preferred, HMAC)
  - or `INGESTION_KEY` (legacy bearer/header key)

If your server-message JSON payloads are posting to `/hooks/...`, use `WEBHOOK_API_KEY`.
If posting to `/api/ingest/local-erasure`, use `INGESTION_SECRET` or `INGESTION_KEY`.

## Render Environment Variables (Practical Set)

### Required
- `DASHBOARD_ADMIN_PASSWORD`
- `DASHBOARD_MANAGER_PASSWORD`
- `DASHBOARD_VIEWER_PASSWORD`
- `WEBHOOK_API_KEY`
- `MARIADB_HOST`
- `MARIADB_USER`
- `MARIADB_PASSWORD`
- `MARIADB_DB`
- `MARIADB_PORT`
- `STATS_DB_PATH`

### Recommended
- `INGESTION_SECRET` (or `INGESTION_KEY` if not using signatures)
- `LOG_LEVEL`
- `DB_LOG_MODE`
- `DB_QUERY_ALERT_THRESHOLD`
- `DB_BATCH_LOG_EVERY`
- `QA_CACHE_TTL_SECONDS`
- `ENABLE_TRACEMALLOC`
- `TRACE_SNAPSHOT_DIR`
- `TRACE_SNAPSHOT_THRESHOLD_MB`
- `EXPORT_WRITE_MODE`
- `EXPORT_BATCH_SIZE`

### Optional
- `DASHBOARD_PUBLIC`
- `AUTO_BACKFILL`
- `AUTO_BACKFILL_DAYS`
- `AUTO_BACKFILL_LIMIT`
- `REDIS_URL` (only if using queued exports worker path)

### Can be removed (if still present)
- `POWERBI_API_KEY` (Power BI endpoints are removed)
- `ALERT_WEBHOOK_URL` (not used in current code path)

## Docker / Deploy Status
- `Procfile` remains valid for Render web process.
- Dockerfile currently contains duplicate definitions and should be cleaned to one canonical build path in next cleanup slice.

## Testing Status
- Contract and integration test suite is passing locally.
- Refactors are being done in safe slices with checkpoint commits.

## Roadmap (Next)

### Phase A: Base hardening and cleanup
1. Dockerfile cleanup (single definition, single port strategy).
2. Remove stale docs references to Power BI.
3. Optional: migrate `@app.on_event` handlers to FastAPI lifespan.

### Phase B: Dashboard domain split (main objective)
1. Separate Erasure Stats frontend logic into dedicated module(s).
2. Separate QA Stats frontend logic into dedicated module(s).
3. Keep shared auth/session/chart helpers in common module.
4. Prepare slots/modules for future domains:
   - IA
   - Breakfix
   - Refurb
   - Goods In

### Phase C: Bottleneck correctness (deferred)
1. Reconcile category definitions with real operational workflow.
2. Add focused tests around bottleneck calculations.
3. Improve reliability for MariaDB-read-dependent paths.

## Recent Milestone
- Major modularization complete: `main.py` reduced from multi-thousand-line monolith to focused app wiring.
- Deploy verified working after extraction of webhooks, runtime tasks, device lookup, and bottleneck routers.
