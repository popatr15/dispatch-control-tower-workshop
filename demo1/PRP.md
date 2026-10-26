# Dispatch Control Tower (demo1)

> Paste the rendered copy of this file (`demo1/PRP.rendered.md`, written by `data/setup.sh` with the values below filled in) into Genie Code. Table and column names are in `docs/DATA_CONTRACT.md`.

## What to build

A one-screen Databricks App for logistics dispatchers. It shows today's deliveries on a map, flags routes at risk of missing their delivery window, lets the dispatcher move a stop to another route or log an exception with a reason, and has a chat box to ask Genie why things are late.

## Data

Already loaded. Read-only, through the SQL warehouse `{{DBX_WAREHOUSE_ID}}`, from `{{DBX_CATALOG}}.{{DBX_SCHEMA}}`:

- `stops` (lat/lon, status: on_time / at_risk / late / delivered)
- `routes` (risk_score, risk_reason)
- `depots`, `route_paths` (lines to draw), `carriers`, `vehicles`

Saved by the app in Lakebase (project `{{LAKEBASE_PROJECT}}`, branch `{{LAKEBASE_BRANCH}}`, endpoint `{{LAKEBASE_ENDPOINT}}`, database `{{PGDATABASE}}`). Create these tables if they don't exist:

- `stop_reassignments`: stop_id, from_route_id, to_route_id, reason_code, note, created_by, created_at
- `exceptions`: stop_id, route_id, exception_type (customer_unavailable / weather / vehicle_down / other), reason, status (open / resolved), created_by, created_at

Genie space for the chat box: `{{GENIE_SPACE_ID}}`.

## Screen

- **Left:** at-risk routes, highest risk first, with the reason. Click one to zoom the map to it.
- **Center:** map of today's stops colored by status, depot markers, and route lines.
- **Right:** click a stop to reassign it (pick a route, a reason, optional note) or log an exception. Tabs for the exception list and the Genie chat.

A reassigned stop shows on its new route after a page reload.

## Rules

- Use apx (FastAPI + React + TypeScript) and the Databricks SDK. Map with MapLibre and a free tile style.
- Read config from env vars; don't hardcode IDs in code.
- Only build what's above: no routing optimization, approvals, or user management.

## Done when

- The map loads with today's stops and routes.
- Reassigning a stop and logging an exception survive a reload.
- Asking Genie "Which depots missed SLA most last week?" returns an answer with its SQL.
