# Dispatch Workshop Data Setup

This folder creates the shared data space for the Dispatch Control Tower workshop. It creates the gold Delta tables, a curated Genie space, and, unless skipped, a Lakebase Postgres project with the demo1 and demo2 write-back tables.

## 5-Step Quick Start

1. Install prerequisites: Databricks CLI, `uv` or Python 3.11+, and an authenticated Databricks CLI profile with a SQL warehouse available.

2. Confirm auth:

   ```bash
   databricks auth profiles
   ```

3. Run the one-command setup with an explicit profile:

   ```bash
   demo1/data/setup.sh --profile <your-profile>
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
   demo1/data/verify.sh --profile <your-profile>
   ```

5. Tear down workshop-created assets:

   ```bash
   demo1/data/setup.sh --profile <your-profile> --teardown
   ```

## What Setup Prints

At the end, setup prints the app environment values:

```bash
export DBX_CATALOG=workshop_dispatch
export DBX_SCHEMA=gold
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
```

## Implementation Notes

- The generator is deterministic with a fixed seed and writes JSONL files locally.
- Setup uploads those files to a managed UC volume named `workshop_seed`, then creates Delta tables with SQL warehouse `CREATE OR REPLACE TABLE ... AS SELECT ... FROM read_files(...)`.
- Lakebase uses the current Autoscaling CLI surface documented in the Databricks Lakebase skill: `databricks postgres create-project/list-branches/list-endpoints/list-databases/get-endpoint` and `databricks psql` for idempotent Postgres DDL.
- Genie uses the current CLI surface documented in the Genie Agents skill: `databricks genie list-spaces/create-space/update-space/start-conversation/get-message`.
- No secrets, tokens, workspace URLs, or emails are stored by these files.

## Troubleshooting

- `--profile is required`: pass the exact Databricks CLI profile. The scripts never default or auto-select.
- `Could not create the catalog/schema/volume`: your profile lacks Unity Catalog create permissions. Ask an admin to create the catalog/schema or grant permissions, then rerun.
- `No SQL warehouses found`: create a SQL warehouse or pass `--warehouse-id`.
- `databricks-sdk is required`: install `uv` or run `python3 -m pip install databricks-sdk`.
- Lakebase DDL failure: confirm your CLI supports `databricks postgres` and `databricks psql`, and that Lakebase is enabled in the workspace.
- Genie verification fails: rerun `verify.sh` after setup has completed; if the space was created manually, pass `--genie-space-id`.

## Offline Developer Gates

From this folder:

```bash
uv run ruff check .
uv run pytest
```
