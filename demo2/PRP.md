# PRP: Dispatch Control Tower (demo2, full scope, DAB)

> Source of truth for the full reference app. Data comes from `demo1/data` (setup script) per `docs/DATA_CONTRACT.md`. This is a superset of `demo1/PRP.md`: implement every demo1 feature (map, at-risk list, reassign, exceptions, Genie) plus the items below.

## 1. Goal & Why

**Goal:** A production-shaped Databricks App, deployed entirely by `databricks bundle deploy`, that closes the action -> insight loop: warehouse + Genie in, Lakebase write-out, Lakebase decisions synced back to Unity Catalog as labeled data.

**Why:** Shows what a dashboard cannot: write-back, per-user state, workflow, audit trail, and training signal.

**Success:**
- `databricks bundle deploy && databricks bundle run` stands up app, Lakebase, jobs, Genie space, and dashboard in a fresh workspace given the demo1 data.
- Every action appears in the audit trail with user, time, reason, and in the synced UC labeled-data table.
- Two users see each other's route-state changes within a few seconds.

**Non-goals (hard boundaries):** No routing solver; no real telematics; no model training (only produce labeled data); no multi-tenant/billing; no mobile/driver app; no customer branding.

## 2. Context

**Stack (do not deviate):** apx (FastAPI + Pydantic, Python via `uv`; React + TypeScript via `bun`, shadcn/ui, TanStack Router/Query, Orval client). Map: MapLibre GL + deck.gl, open tiles. `databricks-sdk` only for Databricks calls. Lakebase via `psycopg` (OAuth). Deployment: Declarative Automation Bundles (`databricks.yml`) with targets `dev` and `prod`.

**Bundle resources (all in `databricks.yml` / `resources/`):** app (with resource bindings: SQL warehouse, Lakebase database, Genie space), Lakebase instance/database, Lakeflow job `sync_decisions` (Lakebase -> UC), job `seed_reset` (reset demo state), Genie space (curated instructions, sample questions, certified SQL for the canonical questions), AI/BI dashboard for managers (SLA by depot, exceptions by type, decision volume), UC grants. Variables: `catalog`, `schema`, `warehouse_id`. Check current docs/skills for how each resource type is declared; Lakebase and Genie space bundle support may need a setup step documented in README if not yet a native bundle resource.

**Features beyond demo1:**
1. Map layers (toggle/filter by depot, carrier, region, date): stop clusters, route lines, depot catchments (circles from `catchment_radius_km`), historical on-time heat layer from `delivery_history`.
2. Approval queue: request expedite fee (amount, justification) from a route; manager role approves/rejects with comment; table `approvals`.
3. Live route state: `route_state` in Lakebase; changes pushed to other users via SSE (or short polling fallback).
4. Per-user identity: use the Apps forwarded user identity (OBO headers) for `created_by`/`actor`; role from group membership (`dispatchers`, `managers`) with a config override for the workshop.
5. Audit trail: every write also writes `audit_log` in the same transaction; filterable audit view; comments on stops/routes.
6. Sync back: job reads Lakebase decision tables (reassignments, exceptions, approvals, audit) and writes UC table `{catalog}.gold.decision_labels` (decision, reason, features at decision time, outcome when known) via Lakebase sync to Delta; documents how it feeds the next routing model.
7. Genie: Conversation API with conversation history per user, SQL shown, feedback thumbs stored in Lakebase.

**Files & patterns:** mirror apx layout: `src/dispatch_tower/{app.py,routers/,services/,db/}`, `ui/src/routes/`, `tests/`, `resources/*.yml`. Routers use `operation_id`s. Repositories wrap each Lakebase write + audit in one transaction.

**Gotchas:** parameterized SQL only; Lakebase OAuth token refresh; warehouse cold start; cap map payloads (aggregate server-side for clusters); effective-route override rule in `docs/DATA_CONTRACT.md`; bundle deploy of app requires source path sync; never commit secrets or workspace URLs; public repo.

## 3. Blueprint

1. Read `docs/PRD.md`, `docs/DATA_CONTRACT.md`, `demo1/PRP.md`.
2. Scaffold apx project in `demo2/app`; add `databricks.yml` skeleton and validate (`databricks bundle validate`).
3. Backend services + Lakebase schema/migrations; audit-in-transaction repository layer.
4. Frontend: map layers/filters, route list, stop/route panels, exceptions, approvals, audit, Genie.
5. Live state (SSE) and role gating.
6. Jobs (`sync_decisions`, `seed_reset`), Genie space, dashboard, grants as bundle resources.
7. README with deploy steps and a workshop walkthrough script.
8. Run all gates; deploy to a dev target; verify the loop end to end.

## 4. Validation Gates

```bash
cd demo2/app && uv run ruff check . && uv run pytest -v
cd ui && bun run tsc --noEmit && bun run lint && bun run build
databricks bundle validate -t dev
databricks bundle deploy -t dev     # needs workspace; report if unavailable, never fake
```
Tests must cover: effective-route override, audit-in-transaction rollback, role gating, approval state machine, sync job transform. Genie eval: the 2 canonical questions plus 3 follow-ups executable and grounded in table rows.

**Definition of done:** all gates clean; the agent may NOT edit tests/gates to pass them.

## 5. Anti-Patterns

- Do not change the stack or add unlisted dependencies. Do not edit gates to fit code.
- Do not hardcode workspace hosts, tokens, IDs, or user emails. Do not commit secrets.
- Do not cross a non-goal (no solver, telematics, model training).
- Do not use raw HTTP for Databricks calls; use the SDK.
