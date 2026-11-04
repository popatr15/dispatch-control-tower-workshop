# Dispatch Control Tower (demo1): delivery map

> Paste the rendered copy of this file (`demo1/PRP.rendered.md`, written by `data/setup.sh` with the values below filled in) into Genie Code. Table and column names are in `docs/DATA_CONTRACT.md`.

## What to build

A one-screen, **read-only** Databricks App that shows today's deliveries on a map. Nothing else: no reassigning, no exceptions, no chat, no writes.

## Data

Already loaded. Read-only, through the SQL warehouse `{{DBX_WAREHOUSE_ID}}`, from `{{DBX_CATALOG}}.{{DBX_SCHEMA}}`:

- `stops` (lat/lon, status: on_time / at_risk / late / delivered)
- `routes` (risk_score, risk_reason)
- `depots`, `route_paths` (lines to draw)

## Screen

One full-width map and a small legend. Nothing else on the page.

- **Stops:** one point per stop, colored by status (on_time, at_risk, late, delivered).
- **Depots:** a marker per depot, labeled with the depot name.
- **Routes:** a line per route from `route_paths`, passing through that route's own stops only.
- **Click a stop:** a small popup with stop id, route id, status, and the route's risk reason.
- **Legend:** the four status colors.

## Rules

- Use apx (FastAPI + React + TypeScript) and the Databricks SDK. Map with MapLibre and a free tile style.
- Read config from env vars; don't hardcode IDs in code.
- Only build what's above: no filters, no route list, no side panels, no Lakebase, no Genie, no writes, no routing optimization, no approvals, no user management.

## Done when

- The map loads with today's stops, depots, and routes, centered on the stops.
- Stops are colored by status and the legend matches.
- Each route's line passes through its own stops only.
- Clicking a stop shows its popup.
