# Dispatch Control Tower

Workshop collateral for **Databricks Apps + Lakebase**: one logistics app built two ways, on the same synthetic data.

- **Business value:** a dashboard shows late deliveries but cannot act on them. These apps let a dispatcher decide in the app (move a late stop to another route, with a reason). The decision is audited per user and lands in the lakehouse as labeled training data. Target outcome: fewer missed SLAs, less expedite and fuel cost, evidence for carrier disputes. Dollar figures in the narrative are placeholders.
- **Data:** synthetic only. No real customers, PII, or secrets.

## Pick your path

| I want to... | Go to |
|---|---|
| Create the data, Genie space, and Lakebase project | [`data/`](data/README.md) |
| Build the simple app live with Genie Code (map only) | [`demo1/PRP.md`](demo1/PRP.md) |
| Deploy and present the full reference app | [`demo2/`](demo2/README.md) |
| Read the product spec | [`docs/PRD.md`](docs/PRD.md) |
| Look up table and column names | [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md) |

## The two demos

| | demo1 | demo2 |
|---|---|---|
| **Purpose** | Attendees build it live in Genie Code from a prompt | Presenter drives a finished reference app |
| **Scope** | Read-only map of today's stops, depots, and routes | Guided 4-step flow: See, Why, Act, Prove |
| **Writes** | None | Reassignments and audit rows in Lakebase, synced to Unity Catalog |
| **Genie** | Not used | "Why" questions with the SQL shown |
| **Deploy** | Genie Code builds an apx app | Declarative Automation Bundle (`databricks bundle deploy`) |

## Quick start

1. **Prerequisites:** Databricks CLI 1.0.0 or newer, `uv` (or Python 3.11+), a SQL warehouse, and a profile (`databricks auth login --host <workspace-url> --profile <profile>`).
2. **Create the data** from the repo root:

   ```bash
   data/setup.sh --profile <profile> --catalog <catalog>
   ```

   - **Creates:** gold Delta tables, a Genie space, a Lakebase project (skip with `--skip-lakebase`), and **deploys the demo2 app** (skip with `--skip-app`; `--skip-lakebase` also skips it). Add `--warehouse-id <w>` to pin the warehouse and `--dry-run` to preview.
   - **Prints:** the app environment values, the verify command, and the path to `demo1/PRP.rendered.md`.
   - **Result:** `data/setup.sh --profile <p> --catalog <c> --warehouse-id <w>` leaves the data and the app ready.
3. **Verify:** run the `data/verify.sh ...` command that setup prints.
4. **Then pick a demo:**
   - **demo1:** paste `demo1/PRP.rendered.md` into Genie Code.
   - **demo2:** already deployed by setup; see [`demo2/README.md`](demo2/README.md) to re-deploy or run it.

## Deploy demo2

The data is usually already in the workspace, so the common case is **pushing only the app**. `data/setup.sh` does this for you at the end of a fresh setup. To deploy (or re-deploy) just the app (bundle validate, bundle deploy, app start):

```bash
scripts/deploy-demo2.sh --profile <profile> --values-file <file-with-setup-exports>
```

- **Values:** save the `export ...` lines printed by `data/setup.sh` to a file (do not commit it), or pass `--catalog`, `--schema`, `--warehouse-id`, etc., or the env vars.
- **Prerequisites:** the Databricks CLI and `python3` only. No `bun`/Node: the built UI is committed (see [`demo2/README.md`](demo2/README.md#rebuilding-the-ui)).
- **App only by default:** it never touches data and never resets demo state. Add `--seed` to also run `seed_reset` (**wipes Lakebase app state**) and `--sync` for `sync_decisions`.
- **Other flags:** `--target prod`, `--dry-run`, `--help`.

## Architecture

| Layer | Role |
|---|---|
| SQL warehouse | Reads the gold Delta tables (map layers, routes, stops) |
| Genie (Conversation API) | Ad-hoc "why" questions (demo2) |
| Lakebase (Postgres) | Everything users write: reassignments, audit log (demo2) |
| Databricks Apps | The surface; identity comes from the Apps forwarded-user headers |
| Lakeflow job `sync_decisions` | Lakebase decisions into Unity Catalog `decision_labels` (demo2) |

## Repo layout

| Path | Contents |
|---|---|
| `data/` | One-command setup, verify, and teardown for the shared data space |
| `demo1/` | `PRP.md`, the map-only prompt for Genie Code |
| `demo2/` | Full reference app: FastAPI + React, bundle, jobs, dashboard |
| `docs/` | `PRD.md` and `DATA_CONTRACT.md` |

## Not in scope

- **No routing optimizer:** reassignment is manual; impact in demo2 is a heuristic projection.
- **No live telematics, multi-tenancy, or driver app.**
- **No model training:** the workshop only produces the labeled data.
