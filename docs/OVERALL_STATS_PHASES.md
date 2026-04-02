# Overall Stats Dashboard Phases

## Goal
Give line managers a morning-ready view to place staff based on bottleneck pressure from Goods In through Sorting.

## Phase 1 - Layout and UX (Current)
- Add new `Overall Stats` dashboard view.
- Show section cards for: Goods In, IA, Erasure, QA, Sorting.
- Include current vs target, traffic status, trend indicator, and staffing recommendation.
- Use mock data to validate layout and discussion flow in huddles.

## Phase 2 - Goods In Live Data (Next)
- Add backend endpoint for Goods In section metrics.
- Replace Goods In mock values with live source data.
- Validate refresh cadence and fallback behavior.

## Phase 3 - IA Live Data
- Add IA data integration endpoint.
- Plug IA card into live values.
- Validate threshold tuning with manager feedback.

## Phase 4 - Erasure, QA, Sorting Live Data
- Wire each section one at a time.
- Keep traffic-light thresholds configurable.
- Capture baseline staffing recommendations.

## Phase 5 - Recommendation Tuning
- Refine recommendation logic based on real operations.
- Add simple confidence labels and optional notes.
- Define handover guidance for shift changes.

## Delivery Guardrails
- One source integration per PR.
- Keep contract tests updated for each new route/asset.
- No UI regressions on Erasure and QA dashboards.

## Done Criteria for Feature Start
- Overall view visible in dashboard switcher.
- Layout complete and demo-ready with mock data.
- Goods In integration ticket ready to implement as soon as DB access is provided.

## Current Status (2026-04-02)
- Phase 1 layout is implemented and test-validated.
- Dashboard navigation includes `Overall Stats` as the third page.
- Section cards support per-department `awaiting` and `done` style metrics.
- Next executable step is Phase 2 (Goods In live data wiring).

## Phase 2 Kickoff Checklist
- Confirm Goods In source database and read access credentials.
- Confirm tables/columns for delivered, checked-in, and awaiting IA counts.
- Create endpoint contract implementation for `GET /overall/goods-in`.
- Wire frontend to consume live Goods In payload while other sections remain mock.
- Validate refresh behavior and stale-state fallback for source outages.
