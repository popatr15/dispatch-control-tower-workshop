# PRP: Dispatch Control Tower (demo1, scoped-down, Genie app builder)

> Paste this whole file into Genie app builder as the build prompt. Data already exists: run `data/setup.sh` first (see `data/README.md`); demo1 and demo2 share this same data. The values below are placeholders; `data/setup.sh` writes a copy of this file with them filled in as `demo1/PRP.rendered.md` (gitignored). Paste the RENDERED copy into Genie Code. Table and column names are defined in `docs/DATA_CONTRACT.md` and must be used exactly.

## Environment values (filled in by setup.sh)

| Name | Value |
|---|---|
| DBX_CATALOG | `{{DBX_CATALOG}}` |
| DBX_SCHEMA | `{{DBX_SCHEMA}}` |
| DBX_WAREHOUSE_ID | `{{DBX_WAREHOUSE_ID}}` |
| GENIE_SPACE_ID | `{{GENIE_SPACE_ID}}` |
| Lakebase project / branch / endpoint | `{{LAKEBASE_PROJECT}}` / `{{LAKEBASE_BRANCH}}` / `{{LAKEBASE_ENDPOINT}}` |
| Lakebase database | `{{PGDATABASE}}` |

Tables are `{{DBX_CATALOG}}.{{DBX_SCHEMA}}.<table>` (names in `docs/DATA_CONTRACT.md`).

## 1. Goal & Why

**Goal:** A single-screen Databricks App where a dispatcher sees today's deliveries on a map, spots at-risk routes, reassigns a stop, logs an exception with a reason, and asks Genie why things are late.

**Why:** Dashboards show what happened but cannot record decisions. This app proves the action -> insight loop: warehouse + Genie in, Lakebase write-out, in one screen.

**Success:**
- Map renders today's stops (colored by status), depots, and route lines.
- Reassigning a stop and logging an exception persist to Lakebase and survive page reload.
- Spot at-risk route -> reassign -> reason recorded in under 60 seconds.
- Genie panel answers the two canonical questions in `docs/DATA_CONTRACT.md`.

**Non-goals (hard boundaries):**
- No routing optimization or auto-assignment. No telematics. No approval queue, live route state, comments, audit-log UI, or sync back to the lakehouse (those are demo2).
- No auth beyond the Databricks Apps default. No mobile view. No customer branding.

## 2. Context

**Stack (do not deviate):** apx: FastAPI + Pydantic backend (Python, `uv`), React + TypeScript frontend (`bun`, shadcn/ui, TanStack Router/Query). Generated API client via Orval; every route has an `operation_id`. Map: MapLibre GL JS (or deck.gl over MapLibre) with a no-key open tile style. Databricks access via `databricks-sdk` only (`WorkspaceClient`), never raw HTTP. Lakebase via `psycopg` with OAuth token auth.

**Data reads (SQL warehouse, via SDK statement execution):** `{{DBX_CATALOG}}.{{DBX_SCHEMA}}.stops`, `routes`, `depots`, `route_paths`, `carriers`, `vehicles`. Catalog/schema/warehouse come from env vars (`DBX_CATALOG`, `DBX_SCHEMA`, `DBX_WAREHOUSE_ID`) declared in `app.yaml`.

**Data writes (Lakebase):** tables `stop_reassignments`, `exceptions` from the contract. Create them on startup if absent (idempotent DDL). Instance/database from env (`PGHOST`, `PGDATABASE`, etc. via app resource binding).

**Genie:** Conversation API via SDK (`w.genie.start_conversation_and_wait`, follow-ups in the same conversation). Space id from env `GENIE_SPACE_ID`. Show the generated SQL and result table in the chat panel.

**Screen layout:** left: at-risk route list (sorted by risk_score desc, shows risk_reason). Center: map. Right: tabs "Stop", "Exceptions", "Ask Genie". Clicking a route or stop selects it everywhere. Map colors: on_time green, at_risk amber, late red, delivered gray. Use colorblind-safe palette plus shape/size cue for status.

**Gotchas:**
- Effective route of a stop = latest `stop_reassignments.to_route_id` else `stops.route_id`; apply on read by joining warehouse rows with Lakebase rows in the backend.
- Warehouse statements are slow to start; show skeletons, cache the day's stops in memory for 60s.
- Never build SQL by string concatenation with user input; use parameterized statements.
- Lakebase tokens expire; refresh credentials per connection pool recycle.
- Cap map payload (<= ~3,000 points); send compact JSON.

**Docs:** Databricks Apps (apx), Lakebase, Genie Conversation API docs; `docs/DATA_CONTRACT.md`.

## 3. Blueprint

1. Read `docs/DATA_CONTRACT.md`; scaffold apx project (`app.yaml`, env wiring, health route).
2. Backend: `GET /api/routes`, `GET /api/stops?route_id=`, `GET /api/depots`, `GET /api/route-paths`, `POST /api/stops/{id}/reassign`, `GET/POST /api/exceptions`, `PATCH /api/exceptions/{id}`, `POST /api/genie/ask`.
3. Lakebase module: connection, idempotent DDL, repository functions.
4. Frontend: map with layers, route list, stop panel with reassign form (route picker + reason code + note), exceptions tab, Genie chat.
5. Pytest for backend (mock warehouse/Lakebase); Playwright or Vitest smoke for the reassign flow.
6. Run all gates; deploy as a Databricks App; verify end to end.

## 4. Validation Gates

```bash
uv run ruff check src/ && uv run pytest -v
cd ui && bun run tsc --noEmit && bun run lint && bun run build
# smoke: reassign a stop, reload, confirm the override persists
curl -s -X POST $APP_URL/api/stops/<id>/reassign -d '{"to_route_id":"...","reason_code":"vehicle_down"}'
```

Genie eval (AI feature): the 2 canonical questions plus 3 follow-ups; each must return SQL that executes and an answer grounded in table rows (no fabricated depots/carriers).

**Definition of done:** all gates exit clean; the agent may NOT edit tests/gates to pass them.

## 5. Anti-Patterns

- Do not change the stack or add dependencies beyond the listed ones.
- Do not read from or write to tables outside the contract; do not hardcode workspace URLs, tokens, or IDs.
- Do not write demo2 features. Do not edit gates to fit code.
- Do not use raw HTTP for Databricks calls; use the SDK.
