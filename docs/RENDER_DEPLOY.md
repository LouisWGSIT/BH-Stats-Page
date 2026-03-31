Render deployment checklist — make local_erasures durable

Overview
- By default the app uses a local SQLite DB `warehouse_stats.db` (path controlled by `STATS_DB_PATH`).
- On Render the filesystem is ephemeral unless you mount a persistent disk. To keep the local erasure feed between deploys use a persistent mount and point `STATS_DB_PATH` at it.

Quick steps
1. Create or attach a persistent disk on Render and mount it at `/data` (or another path you choose).
2. Set environment variables in your Render service settings (Environment -> Environment Variables):
   - `STATS_DB_PATH` = `/data/warehouse_stats.db`  # path on the mounted persistent disk
   - `MARIADB_HOST`, `MARIADB_USER`, `MARIADB_PASSWORD`, `MARIADB_DB`, `MARIADB_PORT` (if needed)
   - `INGESTION_KEY` or `INGESTION_SECRET` (to secure ingestion endpoints)
   - `DASHBOARD_ADMIN_PASSWORD`, `DASHBOARD_MANAGER_PASSWORD`
   - Other optional envs: `AUTO_BACKFILL`, `AUTO_BACKFILL_DAYS`, `POWERBI_API_KEY`, etc.
3. Commit & push your changes; deploy on Render.
4. After deployment, verify:
   - The DB file exists on the mounted disk: ssh into instance or use the Render shell and run `ls -l /data/warehouse_stats.db`.
   - The health endpoint: `GET https://<your-service>/health/db` should return `{"status":"ok","db":"ok"}` if MariaDB is configured, or `503` if not.
   - Ingest a small test event to `/api/ingest/local-erasure` with the ingestion key and confirm `local_erasures` has rows.

Notes & recommendations
- The repository will attempt to create the parent directory for `STATS_DB_PATH` at startup (so `/data` must be writable by the service user).
- If you expect multiple instances (autoscaling), prefer a shared DB (MariaDB) for `local_erasures`. Since you currently don't have write privileges on MariaDB, using a Render persistent disk is an acceptable interim solution.
- Backups: periodically copy `/data/warehouse_stats.db` to an external backup location if you want snapshots across deploys.

Migration (one-time)
- If you previously had erasure rows written to an ephemeral SQLite on Render and want to keep them, before switching mounts copy the file from the old instance to the persistent disk or export rows and re-import them after mounting.

Troubleshooting
- "DB not writable" on startup: check that the mount exists and Render mount permissions allow write by the app user.
- "No data after deploy": confirm `STATS_DB_PATH` points to the mounted location and that the mount is configured in the Render dashboard.

If you want, I can:
- Update the repo to add a small health-check endpoint verifying `STATS_DB_PATH` is writable, or
- Implement an optional periodic backup of `warehouse_stats.db` to a configured S3/remote location.

