# Dispatch Workshop Data Setup

This folder creates the shared data space for the Dispatch Control Tower workshop. It creates the gold Delta tables, a curated Genie space, and, unless skipped, a Lakebase Postgres project with the demo1 and demo2 write-back tables.

## Catalog and Schema Selection

Run commands from the repo root. `--catalog` is required in non-interactive runs unless `DBX_CATALOG` is set. In an interactive terminal, omitting `--catalog` lists available non-sharing catalogs and prompts for one. If `--schema`/`DBX_SCHEMA` is omitted, setup uses a per-user default like `workshop_dispatch_<user_slug>_<hash>` so multiple attendees do not collide.

Examples:

```bash
data/setup.sh --profile <your-profile> --catalog <catalog> --schema workshop_dispatch
DBX_CATALOG=<catalog> DBX_SCHEMA=workshop_dispatch data/setup.sh --profile <your-profile>
DBX_CATALOG=<catalog> data/setup.sh --profile <your-profile>  # per-user schema default
```

## 5-Step Quick Start

1. Install prerequisites: Databricks CLI 1.0.0 or newer, `uv` or Python 3.11+, and a SQL warehouse available. From the repo root, create or refresh a profile:

   ```bash
   databricks auth login --host <workspace-url> --profile <your-profile>
   ```

2. Confirm auth:

   ```bash
   databricks auth profiles
   ```

3. Run the one-command setup with an explicit profile:

   ```bash
   data/setup.sh --profile <your-profile> --catalog <catalog> --schema workshop_dispatch
   ```

   Optional flags:

   ```bash
   --catalog workshop_dispatch
   --schema gold
   --warehouse-id <warehouse-id>
   --skip-lakebase
   ```

4. Verify the deployment:

   ```bash
   data/verify.sh --profile <your-profile> --catalog <catalog> --schema workshop_dispatch
   ```

5. Tear down workshop-created assets only when you are sure you no longer need them:

   ```bash
   data/setup.sh --profile <your-profile> --catalog <catalog> --schema workshop_dispatch --teardown
   ```

## What Setup Prints

At the end, setup prints the app environment values:

```bash
export DBX_CATALOG=<catalog>
export DBX_SCHEMA=workshop_dispatch
export DBX_WAREHOUSE_ID=<warehouse-id>
export GENIE_SPACE_ID=<space-id>
export LAKEBASE_PROJECT=projects/<project-id>
export LAKEBASE_BRANCH=projects/<project-id>/branches/<branch-id>
export LAKEBASE_ENDPOINT=projects/<project-id>/branches/<branch-id>/endpoints/<endpoint-id>
export LAKEBASE_DATABASE=projects/<project-id>/branches/<branch-id>/databases/<database-id>
export PGHOST=<lakebase-host>
export PGDATABASE=databricks_postgres
export PGPORT=5432
export PGSSLMODE=require
Rendered PRP: <repo>/demo1/PRP.rendered.md
```

## Implementation Notes

- The generator is deterministic with a fixed seed and writes JSONL files locally.
- Setup uploads those files to a managed UC volume named `workshop_seed`, then creates Delta tables with SQL warehouse `CREATE OR REPLACE TABLE ... TBLPROPERTIES (...) AS SELECT ... FROM read_files(...)`.
- Setup refuses to overwrite contract-named tables that were not tagged by this script for the current user.
- Staged JSONL files are written under a per-user path inside the `workshop_seed` volume.
- Genie spaces and Lakebase projects are scoped by catalog, schema, and current user to avoid shared-workspace collisions.
- Lakebase uses the current Autoscaling CLI surface documented in the Databricks Lakebase skill: `databricks postgres create-project/list-branches/list-endpoints/list-databases/get-endpoint` and `databricks psql` for idempotent Postgres DDL.
- Genie uses the current CLI surface documented in the Genie Agents skill: `databricks genie list-spaces/create-space/update-space/start-conversation/get-message`.
- No secrets, tokens, workspace URLs, or emails are stored by these files.
- Runtime is typically several minutes because the SQL warehouse loads about 75k historical delivery rows plus today’s 2,500 stops. Warehouse and Lakebase usage may incur workspace costs.

## Shared Workspace Warning

Use your own catalog/schema when possible. Teardown only drops tables tagged as created by this setup for your current user and only deletes a Lakebase project recorded as created by your local setup state. It intentionally leaves the shared UC volume itself in place.

## App Grants

After deploying a Databricks App, grant its service principal access to the gold tables and Lakebase project. Replace placeholders with your app service principal and deployed catalog/schema:

```sql
GRANT USE CATALOG ON CATALOG <catalog> TO `<app-service-principal>`;
GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO `<app-service-principal>`;
GRANT SELECT ON SCHEMA <catalog>.<schema> TO `<app-service-principal>`;
```

For Lakebase, grant the app resource permission in the app configuration or UI so the app service principal can connect to the project/database.

## Troubleshooting

- `--profile is required`: pass the exact Databricks CLI profile. The scripts never default or auto-select.
- `Could not create the catalog/schema/volume`: your profile lacks Unity Catalog create permissions. Ask an admin to create the catalog/schema or grant permissions, then rerun.
- `No SQL warehouses found`: create a SQL warehouse or pass `--warehouse-id`.
- `databricks-sdk is required`: install `uv` or run `python3 -m pip install databricks-sdk`.
- `Refusing to replace ... table exists but is not tagged`: choose a different schema, run teardown for your own tagged setup, or ask the schema owner before manually removing pre-existing tables.
- Lakebase DDL failure: confirm your CLI supports `databricks postgres` and `databricks psql`, and that Lakebase is enabled in the workspace.
- Genie verification fails: rerun `verify.sh` after setup has completed; if the space was created manually, pass `--genie-space-id`.

## Offline Developer Gates

From this folder:

```bash
uv run ruff check .
uv run pytest
```
