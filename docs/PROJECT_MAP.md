# Project Map

This file is a quick orientation guide for the active code paths.

## Runtime entrypoints

- API + app entrypoint: `main.py`
- Main dashboard page: `frontend/pages/index.html` (served at `/` and `/index.html`)
- Admin page: `frontend/pages/admin.html` (served at `/admin.html`)
- Manager page: `frontend/pages/manager.html` (served at `/manager.html`)
- Frontend JS: `frontend/js/app.js` (served at `/app.js`)
- Frontend CSS: `frontend/css/styles.css` (served at `/styles.css`)

## Data layers

- SQLite stats/events: `backend/database.py` (default DB at project root `warehouse_stats.db`)
- MariaDB reads/writes: `services/db_utils.py`
- QA/business queries: `backend/qa_export.py`

## Compatibility shims

- Root modules (`database.py`, `qa_export.py`, `excel_export.py`, etc.) are import shims
  that forward to `backend/*` to keep existing imports stable during refactor.

## Exports

- Direct export endpoints: `main.py` + `backend/excel_export.py`
- Optional queued exports: `backend/export_jobs.py` + `backend/export_worker.py` (Redis/RQ)

## Manager/Bottleneck

- Manager bottleneck helper module: `manager/bottleneck.py`
- Device lookup logic: `backend/device_lookup.py`

## Ops/Deploy

- Render deploy notes: `docs/RENDER_DEPLOY.md`
- CI warm-cache workflow: `.github/workflows/post-deploy-warm.yml`
- Utility scripts: `scripts/`
- Local one-off scratch scripts: `scripts/scratch/` (git-ignored)
