# Testing Strategy

## Goal

Keep refactors safe by proving behavior before and after each change.

## Test layers

- Unit/contract tests (default): no real external credentials required.
  - Fast and deterministic.
  - Uses mocks for MariaDB dependency boundaries.
- Integration tests (optional): only run when real credentials are present.
  - Verifies real service connectivity and query path.

## Run tests

- All default tests:
  - `.\.venv\Scripts\python.exe -m pytest tests`
- Only integration tests:
  - `.\.venv\Scripts\python.exe -m pytest tests -m integration`

## Credential-gated tests

Integration tests are skipped unless all of these env vars are set:

- `MARIADB_HOST`
- `MARIADB_USER`
- `MARIADB_PASSWORD`
- `MARIADB_DB`

When those are present, `tests/test_integration_mariadb.py` validates
`GET /health/db` end-to-end against the real DB.

## Refactor workflow (Phase 2)

1. Run default tests and confirm green baseline.
2. Make one small structural change.
3. Run default tests again.
4. Repeat in small slices.
5. Run integration tests when credentials are available.
