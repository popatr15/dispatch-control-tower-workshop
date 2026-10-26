# Dispatch Control Tower (demo2): full-scope reference app

A Databricks App deployed with a Declarative Automation Bundle. It closes the
action -> insight loop on the shared workshop data:

| Layer | What it does here |
|---|---|
| SQL warehouse | Reads the gold Delta tables (map layers, routes, stops) |
| Genie (Conversation API) | "Why" questions, per-user history, SQL shown, thumbs feedback |
| Lakebase (Postgres) | Every user write: reassignments, exceptions, approvals, comments, live route state, audit log |
| Databricks Apps | The surface; identity comes from the Apps forwarded user headers |
| Lakeflow job `sync_decisions` | Lakebase decisions -> UC `decision_labels` (labeled training data) |
| AI/BI dashboard | Manager view: SLA by depot, late causes, exceptions by type, decision volume |

Specs: `PRP.md` (this demo), `../docs/PRD.md`, `../docs/DATA_CONTRACT.md`.

## Layout

```
demo2/
├── databricks.yml            # bundle: variables, targets dev/prod, UI build artifact
├── resources/
│   ├── app.yml               # app + bindings (warehouse, Lakebase, Genie) + UC table grants
│   ├── jobs.yml              # sync_decisions (hourly), seed_reset (on demand)
│   └── dashboard.yml         # manager AI/BI dashboard
├── dashboards/manager.lvdash.json
├── jobs/                     # job entrypoints (logic lives in app/src/dispatch_tower/sync)
└── app/                      # apx-style project: FastAPI + React/TS
    ├── src/dispatch_tower/   # app.py, routers/, services/, db/, sync/, mock/
    ├── ui/                   # Vite + React + TanStack Router/Query + Orval client + MapLibre/deck.gl
    └── tests/
```

## Prerequisites

1. Databricks CLI (v1.x) authenticated to the target workspace. Every command
   below passes `--profile <your-profile>` explicitly.
2. `uv`, `bun`, and Python 3.11+ locally (the bundle builds the UI during deploy).
3. The shared workshop data. Run the setup script from the repo root, choosing
   your catalog (see `../data/README.md`):

   ```bash
   data/setup.sh --profile <your-profile> --catalog <your_catalog>
   ```

   It creates the gold tables, a curated Genie space and a Lakebase project, then
   prints the values the bundle needs:

   ```
   DBX_CATALOG, DBX_SCHEMA, DBX_WAREHOUSE_ID, GENIE_SPACE_ID,
   LAKEBASE_BRANCH, LAKEBASE_DATABASE, LAKEBASE_ENDPOINT
   ```

## Deploy

The bundle commits **no** workspace-specific values. Pass them as variables:
either `--var name=value` flags or `BUNDLE_VAR_<name>` environment variables.

```bash
cd demo2
export BUNDLE_VAR_catalog=$DBX_CATALOG
export BUNDLE_VAR_schema=$DBX_SCHEMA
export BUNDLE_VAR_warehouse_id=$DBX_WAREHOUSE_ID
export BUNDLE_VAR_genie_space_id=$GENIE_SPACE_ID
export BUNDLE_VAR_lakebase_branch=$LAKEBASE_BRANCH       # projects/<id>/branches/<branch>
export BUNDLE_VAR_lakebase_database=$LAKEBASE_DATABASE   # .../databases/<database-id>
export BUNDLE_VAR_lakebase_endpoint=$LAKEBASE_ENDPOINT   # .../endpoints/<endpoint-id>

databricks bundle validate -t dev --strict --profile <your-profile>
databricks bundle deploy   -t dev --profile <your-profile>
databricks bundle run dispatch_tower -t dev --profile <your-profile>   # start the app
databricks bundle run seed_reset     -t dev --profile <your-profile>   # clean demo state
```

`deploy` builds the UI (`bun install && bun run build` in `app/ui`) into
`app/src/dispatch_tower/static` and uploads the app source. The app creates and
owns its own Postgres schema (`dispatch`, variable `pg_schema`) inside the
Lakebase database on first start, so it never collides with the tables
`data/setup.sh` created in `public`. Start the app once before running either job.

Optional variables: `app_name` (default `dispatch-tower`), `allow_role_switch`
(`true` in dev), `allow_self_approval` (`true` in dev), `role_overrides`
(`"user=manager,other=dispatcher"`, set at deploy time only), `label_readers`
(UC principal granted SELECT on `decision_labels`, default `account users`).

Targets: `dev` (development mode: resources prefixed per user, schedules paused)
and `prod` (production mode, deployed under the deployer's workspace folder).

### What gets deployed

- **App** `dispatch-tower` with resource bindings: SQL warehouse (`CAN_USE`),
  Lakebase branch/database (`CAN_CONNECT_AND_CREATE`), Genie space (`CAN_RUN`),
  and `SELECT` UC grants on the eight gold tables for the app service principal.
- **Job `sync_decisions`** (hourly): reads the app's `audit_log` from Lakebase,
  joins each stop's current outcome from `stops`, and overwrites
  `<catalog>.<schema>.decision_labels`; grants `SELECT` to `label_readers`.
- **Job `seed_reset`**: truncates every app table in Lakebase, seeds
  `route_state` from today's routes, and drops `decision_labels`.
- **Dashboard** "Dispatch Control Tower - manager view". The two decision panels
  read `decision_labels`, so they populate after the first `sync_decisions` run.

The Lakebase project and Genie space are **inputs** (created by `data/setup.sh`
and shared with demo1), so the bundle binds to them through variables instead of
creating its own.

## Roles and identity

The actor on every write is the signed-in user from the Apps forwarded headers
(`X-Forwarded-Email`). Role resolution, in order:

1. Workshop switch (`allow_role_switch=true`): the role picker in the header.
2. `role_overrides` for specific users.
3. Group membership read with the user's on-behalf-of token: `managers` or
   `dispatchers` (names configurable via `DISPATCH_MANAGER_GROUP` / `DISPATCH_DISPATCHER_GROUP`).
4. Default `dispatcher`.

Only managers can approve or reject expedite requests. Requesters cannot decide
their own request unless `allow_self_approval=true`.

## How the labeled data feeds the next routing model

`decision_labels` has one row per decision:

| Columns | Meaning |
|---|---|
| `decision_type`, `decision`, `reason_code`, `reason_text` | the label: what the dispatcher or manager did and why |
| `feat_*` (stop status, late minutes, route risk, target route risk, depot, carrier, region) | what the user saw at decision time, captured in the audit payload in the same transaction as the decision |
| `outcome_*` | what happened to the stop afterwards (known once it is delivered or late) |

A routing or recommendation model trains on `feat_* -> decision`, weighted or
filtered by `outcome_on_time`, so it learns the reassignments that actually
saved the SLA. This workshop stops at producing the table; no model is trained.

The job copies through a Lakebase connection on an hourly schedule. An
alternative is Lakebase Lakehouse Sync (CDC from Postgres into Delta, Beta),
which streams the raw tables into UC; the same `build_decision_labels`
transform can then run over those Delta tables.

## Local development (offline, no workspace)

```bash
cd demo2/app
uv sync
DISPATCH_MOCK=true DISPATCH_ALLOW_ROLE_SWITCH=true DISPATCH_ALLOW_SELF_APPROVAL=true \
  uv run uvicorn dispatch_tower.app:app --app-dir src --port 8000 --reload
# second terminal: hot-reloading UI on :5173, proxies /api to :8000
cd demo2/app/ui && bun install && bun run dev
```

Mock mode uses deterministic synthetic data shaped like the contract (8 depots,
25 routes, 2,500 stops for today), an in-memory transactional store, and canned
Genie answers. Open two browser windows to see live route-state updates.

After changing backend routes, regenerate the typed client:
`cd demo2/app/ui && bun run gen:api` (writes `openapi.json` and `src/lib/api.ts`).

## Validation gates

```bash
cd demo2/app && uv run ruff check . && uv run pytest -v
cd ui && bun run tsc --noEmit && bun run lint && bun run build
cd ../.. && databricks bundle validate -t dev --profile <your-profile>
```

The pytest suite covers the effective-route override, audit-in-transaction
rollback (in memory and against a throwaway local Postgres when `initdb`/`pg_ctl`
are installed; otherwise those tests skip), role gating, the approval state
machine, and the sync transform.

## Workshop walkthrough (about 15 minutes)

1. **Open the app** (Operations). Point out the map layers: stop clusters
   colored by worst status, route lines weighted by risk, depot catchment
   circles. Toggle "30-day late heat". Filter Region = Northeast.
2. **Spot the risk.** The left list is sorted by risk. Click the top route: the
   map fits to it and the Route tab shows its stops, state, and expedite form.
3. **Ask why.** Ask Genie tab -> "Which depots missed SLA most last week, and
   what do the late stops have in common?" Expand the SQL. Follow up with
   "Show late deliveries in the Northeast by carrier." Give a thumbs up.
4. **Act.** Click a late stop, choose a lower-risk route at the same depot,
   reason `sla_risk`, Reassign. The stop gets a purple ring and the route
   counts change. Log an exception (`customer_unavailable`) on another stop.
5. **Live state.** Open the app in a second window (or have a neighbor open
   it). Set the route's live state to `delayed`; the other window updates within
   a couple of seconds and shows who changed it.
6. **Approval workflow.** On the route, request a $250 expedite with a
   justification. Switch the role picker to Manager, open Approvals, approve
   with a comment. Switching back to Dispatcher shows the decide buttons gone.
7. **Audit.** Audit trail page: every action with actor, time, reason and the
   payload of features seen at decision time. Filter by your user.
8. **Close the loop.** Run `databricks bundle run sync_decisions -t dev
   --profile <your-profile>`, then query `<catalog>.<schema>.decision_labels`
   and open the manager dashboard: SLA by depot, exceptions by type, decision
   volume.
9. **Reset** for the next group: `databricks bundle run seed_reset -t dev
   --profile <your-profile>`.

### Genie evaluation questions

Ask these in the Genie tab; each answer must show SQL that runs and values that
match the tables (no invented depots or carriers):

1. Which depots missed SLA most last week, and what do the late stops have in common?
2. Show late deliveries in the Northeast by carrier.
3. Follow-up: Which cause codes drive those Northeast late deliveries?
4. Follow-up: Which routes are highest risk today, and at which depots?
5. Follow-up: How did the on-time rate of the two worst depots trend over the last 30 days?
