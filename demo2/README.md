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

## The guided flow

The UI is a linear four-step stepper, about a 60-second hero workflow. The decision it
enables: **which late stops do I move, to which route, and why, before the SLA breach
compounds.** The step lives in the URL (`/?step=act&hub=DEPOT_NYC&route=R-...-002`), so any
step is deep-linkable.

| Step | What you do | Screenshot |
|---|---|---|
| **1 See** | Hubs with a red / amber / green status next to a map. Newark is the only red hub. Pick it, then its red route R-002. | [step 1](docs/guided-flow/step1-see.png) |
| **2 Why** | Ask Genie one of the two canonical questions. Answer plus collapsible SQL. | [step 2](docs/guided-flow/step2-why.png) |
| **3 Act** | 3-5 suggested reassigns for R-002. Apply (reason `sla_risk` prefilled) and confirm. "Pick another route" overrides the target. | [step 3](docs/guided-flow/step3-act.png) |
| **4 Prove** | Before/after strip (route late count and risk, hub on-time vs SLA target), your last five decisions with the features captured, and how they reach `decision_labels`. | [step 4](docs/guided-flow/step4-prove.png) |

The UI only shows this flow. The backend keeps every endpoint (approvals, exceptions,
comments, route state, role gating) and its tests; the Approvals page, role switch,
Exceptions, comments, route-state, expedite, filters and extra map layers are not in the UI.
`/audit` is still served and is linked from Prove.

### The hero scenario

`app/src/dispatch_tower/services/scenario.py` reshapes routes and stops **at read time**
(warehouse and offline mock alike). The shared gold tables, `generate.py` and the data
contract are untouched, so demo1 is unaffected.

| Rule | Result |
|---|---|
| Newark (`DEPOT_NYC`) route R-002 | The only red route: 12 late, 8 at-risk stops, risk 64% |
| Newark R-010 | Clean, risk 0%, 6 spare slots: the target for R-002's late stops |
| Newark's other routes | Clean and full (capacity = stops), so R-010 is the only place to move to |
| Boston (`DEPOT_BOS`) | The one amber hub (R-001: 5 late, 3 at risk) |
| Every other hub | Green: at most 1 late and 2 at-risk stops per route |
| Route `risk_score` | Derived from stop status (`effective.derive_risk`): a late stop counts 1, an at-risk stop 0.5, against a 25% tolerance. No late or at-risk stops means risk 0 |
| Capacity | Every route fits its vehicle (capacity >= stops) |
| Suggestions | At most 5 stops, one option each, within 60 km, same hub |

Impact (`GET /api/routes/{id}/impact`) is a heuristic, not a routing solver: a moved late or
at-risk stop counts as on time on its new route when that route has room for it.

### 60-second demo script

1. **See (10 s).** "One hub is red." Point at Newark on the map and in the list (93% on time,
   target 94%). Click Newark, then **R-002** (12 late, 8 at risk).
2. **Why (15 s).** Click *Which depots missed SLA most last week?* Newark and Boston lead.
   Open *Show the SQL Genie wrote*. Optionally click the carrier question.
3. **Act (25 s).** Five suggestions, all to R-010 (0% risk, room to spare). Click **Apply**,
   note the prefilled reason `sla_risk`, **Confirm**. Repeat for **all five** suggestions (risk
   only drops below the 50% line on the fifth move: 61%, 57%, 54%, 50%, 46%). Click **Prove it**.
4. **Prove (10 s).** Late stops 12 -> 7 after five moves, risk falls from 64% to 46%, below the 50% at-risk
   line, and Newark's on-time share climbs from 93% to 95%, past its 94% target. Your decisions are listed with the
   features captured. Run `sync_decisions`, then open the manager dashboard.

Reset between runs: `databricks bundle run seed_reset -t dev --profile <your-profile>`
(offline mock mode resets on restart).

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
(`"user=manager,other=dispatcher"`; default `none` means unset — empty string
cannot be passed through Apps env), `label_readers`
(UC principal granted SELECT on `decision_labels`, default `account users`;
the job refuses any value outside letters, digits, spaces and `. _ @ + -`).

> [!WARNING]
> **The `dev` target is workshop-only and NOT secure.** It sets
> `allow_role_switch=true` and `allow_self_approval=true`, so **any signed-in
> user can act as a manager** (the role picker sends `X-Dispatch-Role: manager`)
> and a manager can approve their own expedite request. The app logs a
> `WORKSHOP MODE` warning at startup whenever either toggle is on. The `prod`
> target pins both to `false` (guarded by `app/tests/test_bundle_config.py`);
> deploy anything beyond a workshop with `-t prod` and real group membership.

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

## Deploy demo2

From the repo root, `scripts/deploy-demo2.sh` runs the whole Deploy section above (UI build, validate, deploy, start the app, `seed_reset`, `sync_decisions`, wait for RUNNING):

```bash
scripts/deploy-demo2.sh --profile <your-profile> --values-file <file-with-setup-exports>
```

Run it with `--help` for flags (`--target`, `--skip-seed`, `--skip-sync`, `--dry-run`).

## Roles and identity

The actor on every write is the signed-in user from the Apps forwarded headers
(`X-Forwarded-Email`). Role resolution, in order:

1. Workshop switch (`allow_role_switch=true`): the `X-Dispatch-Role` request header. The guided UI has no role picker; the switch is API-only.
2. `role_overrides` for specific users.
3. Group membership read with the user's on-behalf-of token: `managers` or
   `dispatchers` (names configurable via `DISPATCH_MANAGER_GROUP` / `DISPATCH_DISPATCHER_GROUP`).
4. Default `dispatcher`.

Only managers can approve or reject expedite requests. Requesters cannot decide
their own request unless `allow_self_approval=true`.

**Deployment note: identity trusts the Apps proxy.** The user comes from
`X-Forwarded-Email` / `X-Forwarded-Preferred-Username` and groups from
`X-Forwarded-Access-Token`. These are only trustworthy because the Databricks
Apps proxy strips client-supplied `X-Forwarded-*` headers and sets its own. Do
not expose the app port any other way (another proxy, port-forward, sidecar)
without the same guarantee. As a cheap defence, outside mock mode a request
with no forwarded identity gets `401` (no silent fallback to a default user),
and a value that is not a single principal (commas, whitespace, quotes, control
characters) is rejected.

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

## Known limitations

- **History heat layer plots at depots.** The "30-day late heat" layer reads
  `delivery_history`, which has no latitude/longitude in the data contract. A
  delivery takes its stop's coordinates when that stop is still in `stops`,
  otherwise its depot's; with the shared data almost all history falls back to
  the depot, so the heat effectively shows which depots run late, not where
  along the routes. Live stops (today) use their own coordinates.
- **Impact is a projection.** Hub, route and map figures outside the Prove strip still show
  the raw statuses; only `/api/routes/{id}/impact` counts a moved late stop as on time.
- **Genie reads the unmodified gold tables.** The two canonical questions are history-based
  (`depot_sla_daily`, `delivery_history`: Newark and Boston miss SLA, `CAR_NEF` is the late
  Northeast carrier), so they agree with the hero scenario. A question about *today's* late
  stops reflects the gold `stops` table, not the scenario overlay.
- **Offline mock geography is rough.** The mock spirals stops outward from each depot, so some
  fall over water. The deployed data is land-anchored.
- Every Genie question is written to `genie_messages` with a `genie.ask` audit
  row in the same transaction; `sync_decisions` ignores that action (it is not a
  routing decision).

## Local development (offline, no workspace)

```bash
cd demo2/app
uv sync
DISPATCH_MOCK=true \
  uv run uvicorn dispatch_tower.app:app --app-dir src --port 8000 --reload
# second terminal: hot-reloading UI on :5173, proxies /api to :8000
cd demo2/app/ui && bun install && bun run dev
```

Mock mode uses deterministic synthetic data shaped like the contract (the same 8 depots
and carriers as the shared data, 25 routes, 2,500 stops for today) with the hero scenario
applied, an in-memory transactional store, and canned Genie answers. Open
`http://localhost:8000/` (built UI) or `:5173` (hot-reloading dev server).

After changing backend routes, regenerate the typed client:
`cd demo2/app/ui && bun run gen:api` (writes `openapi.json` and `src/lib/api.ts`).

## Validation gates

```bash
cd demo2/app && uv run ruff check . && uv run pytest -v
cd ui && bun run tsc --noEmit && bun run lint && bun run build
cd ../.. && databricks bundle validate -t dev --strict --profile <your-profile>
```

The pytest suite covers the effective-route override, audit-in-transaction
rollback (in memory and against a throwaway local Postgres when `initdb`/`pg_ctl`
are installed; otherwise those tests skip), role gating, the approval state
machine, and the sync transform.

## Workshop walkthrough (about 5 minutes)

Run the 60-second script above, then go one level deeper:

1. **Audit.** From Prove, open **Full audit trail**: every action with actor, time, reason and
   the payload of features seen at decision time. Filter by your user.
2. **Close the loop.** Run `databricks bundle run sync_decisions -t dev
   --profile <your-profile>`, then query `<catalog>.<schema>.decision_labels` and open the
   manager dashboard: SLA by depot, late causes, decision volume.
3. **Reset** for the next group: `databricks bundle run seed_reset -t dev
   --profile <your-profile>`.

Approvals (managers decide expedite fees), exceptions, comments and live route state are
still implemented in the API and covered by tests; they are not part of the guided UI. Use
the API (`/docs`) to show them.

### Genie evaluation questions

Ask these in the Why step (the first two are its buttons); each answer must show SQL that runs and values that
match the tables (no invented depots or carriers):

1. Which depots missed SLA most last week, and what do the late stops have in common?
2. Show late deliveries in the Northeast by carrier.
3. Follow-up: Which cause codes drive those Northeast late deliveries?
4. Follow-up: Which routes are highest risk today, and at which depots?
5. Follow-up: How did the on-time rate of the two worst depots trend over the last 30 days?
