"""Live Databricks setup and teardown for workshop data assets."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from databricks.sdk import WorkspaceClient

from workshop_data.contract import LAKEBASE_DDL, TABLE_COLUMNS, TABLE_ORDER
from workshop_data.generate import assert_schema, generate, utc_today, write_jsonl

GENIE_TITLE_PREFIX = "Dispatch Control Tower Workshop"
VOLUME_NAME = "workshop_seed"
SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
OWNER_PROPERTY = "dispatch_workshop.owner"
CREATED_PROPERTY = "dispatch_workshop.created"
STATE_DIR = Path(".setup-state")


@dataclass
class Config:
    profile: str
    catalog: str
    schema: str
    warehouse_id: str | None
    skip_lakebase: bool


@dataclass(frozen=True)
class OwnerContext:
    user_name: str
    user_slug: str
    marker: str
    parent_path: str


def owner_context(w: WorkspaceClient) -> OwnerContext:
    user_name = w.current_user.me().user_name
    user_slug = sanitize_resource_part(user_name.split("@")[0])[:24]
    marker = hashlib_text(user_name)[:16]
    return OwnerContext(
        user_name=user_name,
        user_slug=user_slug,
        marker=marker,
        parent_path=f"/Workspace/Users/{user_name}/genie_spaces",
    )


def hashlib_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def sanitize_resource_part(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]", "-", value.lower().replace("_", "-")).strip("-")
    return cleaned or "user"


def state_path(config: Config, owner: OwnerContext) -> Path:
    return STATE_DIR / f"{sanitize_resource_part(config.catalog)}-{sanitize_resource_part(config.schema)}-{owner.marker}.json"


def read_state(config: Config, owner: OwnerContext) -> dict[str, Any]:
    path = state_path(config, owner)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(config: Config, owner: OwnerContext, state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    state_path(config, owner).write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def genie_title(config: Config, owner: OwnerContext) -> str:
    return f"{GENIE_TITLE_PREFIX} - {config.catalog}.{config.schema} - {owner.user_slug}"


def quote_ident(name: str) -> str:
    if not SAFE_NAME.match(name):
        raise ValueError(
            f"Unsupported identifier {name!r}. Use letters, numbers, and underscores, "
            "starting with a letter or underscore."
        )
    return f"`{name}`"


def table_name(config: Config, table: str) -> str:
    return f"{quote_ident(config.catalog)}.{quote_ident(config.schema)}.{quote_ident(table)}"


def run_cli(args: list[str], profile: str, *, input_text: str | None = None) -> str:
    command = ["databricks", *args, "--profile", profile]
    try:
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Databricks CLI is required but was not found on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() or exc.stdout.strip()
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{details}") from exc
    return result.stdout.strip()


def run_cli_json(args: list[str], profile: str) -> Any:
    output = run_cli([*args, "-o", "json"], profile)
    return json.loads(output) if output else {}


def json_items(payload: Any, key: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        value = payload.get(key, [])
        return value if isinstance(value, list) else []
    return []


def wait_for_statement(w: WorkspaceClient, statement_id: str, timeout_seconds: int = 900) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"SQL statement {statement_id} did not finish within {timeout_seconds}s")
        response = w.statement_execution.get_statement(statement_id)
        state = str(response.status.state).split(".")[-1]
        if state in {"SUCCEEDED", "FAILED", "CANCELED", "CLOSED"}:
            if state != "SUCCEEDED":
                message = response.status.error.message if response.status.error else "unknown error"
                raise RuntimeError(f"SQL statement {statement_id} {state}: {message}")
            return response
        time.sleep(2)


def execute_sql(w: WorkspaceClient, warehouse_id: str, sql: str) -> Any:
    response = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=sql,
        wait_timeout="30s",
    )
    state = str(response.status.state).split(".")[-1]
    if state == "SUCCEEDED":
        return response
    if response.statement_id is None:
        raise RuntimeError(f"SQL statement did not return an id: {sql[:120]}")
    return wait_for_statement(w, response.statement_id)


def select_warehouse(w: WorkspaceClient, requested: str | None) -> str:
    if requested:
        print(f"Using provided SQL warehouse: {requested}")
        return requested
    warehouses = list(w.warehouses.list())
    if not warehouses:
        raise RuntimeError("No SQL warehouses found. Provide --warehouse-id after creating one.")

    def score(warehouse: Any) -> tuple[int, str]:
        state = str(getattr(warehouse, "state", "")).upper()
        serverless = bool(getattr(warehouse, "enable_serverless_compute", False))
        return (2 if state.endswith("RUNNING") else 0) + (1 if serverless else 0), warehouse.id

    selected = sorted(warehouses, key=score, reverse=True)[0]
    if score(selected)[0] == 0:
        print(
            "No running/serverless warehouse was found; using the first available warehouse. "
            "Startup may take longer.",
            file=sys.stderr,
        )
    print(f"Auto-selected SQL warehouse: {selected.id}")
    return selected.id


def create_uc_objects(config: Config, w: WorkspaceClient, warehouse_id: str) -> None:
    existing_catalogs = {catalog.name for catalog in w.catalogs.list()}
    if config.catalog not in existing_catalogs:
        try:
            execute_sql(w, warehouse_id, f"CREATE CATALOG IF NOT EXISTS {quote_ident(config.catalog)}")
        except Exception as exc:
            raise RuntimeError(
                f"Could not create catalog {config.catalog}. Ask an admin to grant CREATE CATALOG "
                "or rerun with --catalog pointing to an existing writable catalog."
            ) from exc
    try:
        execute_sql(
            w,
            warehouse_id,
            f"CREATE SCHEMA IF NOT EXISTS {quote_ident(config.catalog)}.{quote_ident(config.schema)}",
        )
        execute_sql(
            w,
            warehouse_id,
            "CREATE VOLUME IF NOT EXISTS "
            f"{quote_ident(config.catalog)}.{quote_ident(config.schema)}.{quote_ident(VOLUME_NAME)}",
        )
    except Exception as exc:
        raise RuntimeError(
            f"Could not create or access {config.catalog}.{config.schema} and volume {VOLUME_NAME}. "
            "Use a writable schema or ask an admin to grant CREATE SCHEMA/VOLUME."
        ) from exc


def upload_generated_files(config: Config, source_dir: Path) -> str:
    dbfs_path = f"dbfs:/Volumes/{config.catalog}/{config.schema}/{VOLUME_NAME}/gold_jsonl"
    run_cli(["fs", "rm", "-r", dbfs_path], config.profile) if path_exists(config, dbfs_path) else None
    run_cli(["fs", "mkdirs", dbfs_path], config.profile)
    run_cli(["fs", "cp", "-r", "--overwrite", str(source_dir), dbfs_path], config.profile)
    return f"/Volumes/{config.catalog}/{config.schema}/{VOLUME_NAME}/gold_jsonl"


def path_exists(config: Config, dbfs_path: str) -> bool:
    try:
        run_cli(["fs", "ls", dbfs_path], config.profile)
    except RuntimeError:
        return False
    return True


def table_exists(config: Config, w: WorkspaceClient, warehouse_id: str, table: str) -> bool:
    try:
        execute_sql(w, warehouse_id, f"DESCRIBE TABLE {table_name(config, table)}")
    except RuntimeError:
        return False
    return True


def table_property(config: Config, w: WorkspaceClient, warehouse_id: str, table: str, prop: str) -> str | None:
    response = execute_sql(w, warehouse_id, f"SHOW TBLPROPERTIES {table_name(config, table)} ('{prop}')")
    result_rows = response.result.data_array or [] if response.result else []
    if not result_rows:
        return None
    value = result_rows[0][-1]
    return None if value is None or str(value).startswith("Table property") else str(value)


def assert_table_owned_or_absent(config: Config, w: WorkspaceClient, warehouse_id: str, table: str, owner: OwnerContext) -> None:
    if not table_exists(config, w, warehouse_id, table):
        return
    marker = table_property(config, w, warehouse_id, table, OWNER_PROPERTY)
    if marker != owner.marker:
        raise RuntimeError(
            f"Refusing to replace {config.catalog}.{config.schema}.{table}: table exists but is not "
            "tagged as created by this setup run/user."
        )


def create_table_sql(config: Config, table: str, volume_path: str, owner: OwnerContext) -> str:
    projections = ",\n  ".join(f"{column.json_expr} AS {quote_ident(column.name)}" for column in TABLE_COLUMNS[table])
    path = f"{volume_path}/{table}.jsonl"
    return f"""
CREATE OR REPLACE TABLE {table_name(config, table)}
USING DELTA
TBLPROPERTIES ('{CREATED_PROPERTY}' = 'true', '{OWNER_PROPERTY}' = '{owner.marker}')
AS
SELECT
  {projections}
FROM read_files('{path}', format => 'json')
"""


def load_gold_tables(config: Config, w: WorkspaceClient, warehouse_id: str, volume_path: str, owner: OwnerContext) -> None:
    for table in TABLE_ORDER:
        assert_table_owned_or_absent(config, w, warehouse_id, table, owner)
        print(f"Creating {config.catalog}.{config.schema}.{table}")
        execute_sql(w, warehouse_id, create_table_sql(config, table, volume_path, owner))


def build_genie_payload(config: Config) -> dict[str, Any]:
    q1 = "Which depots missed SLA most last week, and what do the late stops have in common?"
    q2 = "Show late deliveries in the Northeast by carrier."
    identifiers = [f"{config.catalog}.{config.schema}.{table}" for table in TABLE_ORDER]
    column_descriptions = {
        "depot_id": "Depot identifier used to join routes, stops, history, and SLA facts.",
        "carrier_id": "Carrier identifier used to analyze late deliveries by carrier.",
        "region": "US operating region; Northeast is the seeded trouble area.",
        "on_time_pct": "Daily on-time rate as a decimal fraction, compared to sla_target_pct.",
        "sla_met": "Whether the depot met its daily SLA target.",
        "late_minutes": "Minutes late beyond the promised delivery time or window.",
        "cause_code": "Root cause for historical late deliveries.",
        "late_reason_code": "Reason attached to today's late or at-risk stop.",
        "risk_score": "Route-level risk from 0 to 1; values >= 0.75 are high risk.",
        "risk_reason": "Human-readable reason the route is at risk.",
    }
    tables = []
    for identifier in sorted(identifiers):
        table = identifier.split(".")[-1]
        configs = []
        for column in TABLE_COLUMNS[table]:
            entry: dict[str, Any] = {"column_name": column.name}
            if column.name in column_descriptions:
                entry["description"] = [column_descriptions[column.name]]
            if column.name in {"region", "carrier_id", "depot_id", "status", "cause_code"}:
                entry["enable_format_assistance"] = True
                entry["enable_entity_matching"] = True
            configs.append(entry)
        tables.append({"identifier": identifier, "column_configs": sorted(configs, key=lambda c: c["column_name"])})

    q1_sql = f"""
WITH last_week AS (
  SELECT
    depot_sla_daily.depot_id,
    SUM(depot_sla_daily.deliveries) AS deliveries,
    SUM(depot_sla_daily.on_time) AS on_time,
    AVG(depot_sla_daily.on_time_pct) AS avg_on_time_pct,
    AVG(depot_sla_daily.sla_target_pct) AS avg_sla_target_pct,
    SUM(CASE WHEN depot_sla_daily.sla_met = false THEN 1 ELSE 0 END) AS missed_days
  FROM {config.catalog}.{config.schema}.depot_sla_daily
  WHERE depot_sla_daily.sla_date BETWEEN date_sub(current_date(), 7) AND date_sub(current_date(), 1)
  GROUP BY depot_sla_daily.depot_id
),
late_traits AS (
  SELECT
    delivery_history.depot_id,
    delivery_history.cause_code,
    delivery_history.carrier_id,
    COUNT(*) AS late_stops
  FROM {config.catalog}.{config.schema}.delivery_history
  WHERE delivery_history.delivery_date BETWEEN date_sub(current_date(), 7) AND date_sub(current_date(), 1)
    AND delivery_history.on_time = false
  GROUP BY delivery_history.depot_id, delivery_history.cause_code, delivery_history.carrier_id
)
SELECT
  depots.name,
  depots.city,
  depots.region,
  last_week.deliveries,
  last_week.on_time,
  ROUND(last_week.avg_on_time_pct, 4) AS avg_on_time_pct,
  ROUND(last_week.avg_sla_target_pct, 4) AS avg_sla_target_pct,
  last_week.missed_days,
  late_traits.cause_code,
  carriers.name AS carrier_name,
  late_traits.late_stops
FROM last_week
JOIN {config.catalog}.{config.schema}.depots ON depots.depot_id = last_week.depot_id
LEFT JOIN late_traits ON late_traits.depot_id = last_week.depot_id
LEFT JOIN {config.catalog}.{config.schema}.carriers ON carriers.carrier_id = late_traits.carrier_id
WHERE last_week.missed_days > 0
ORDER BY last_week.missed_days DESC, late_traits.late_stops DESC
""".strip()
    q2_sql = f"""
SELECT
  carriers.name AS carrier_name,
  carriers.scac,
  delivery_history.region,
  COUNT(*) AS late_deliveries,
  ROUND(AVG(delivery_history.late_minutes), 1) AS avg_late_minutes,
  SUM(CASE WHEN delivery_history.cause_code = 'weather' THEN 1 ELSE 0 END) AS weather_late_stops,
  SUM(CASE WHEN delivery_history.cause_code = 'traffic' THEN 1 ELSE 0 END) AS traffic_late_stops
FROM {config.catalog}.{config.schema}.delivery_history
JOIN {config.catalog}.{config.schema}.carriers
  ON carriers.carrier_id = delivery_history.carrier_id
WHERE delivery_history.region = 'Northeast'
  AND delivery_history.on_time = false
  AND delivery_history.delivery_date >= date_sub(current_date(), 30)
GROUP BY carriers.name, carriers.scac, delivery_history.region
ORDER BY late_deliveries DESC
""".strip()
    return {
        "version": 2,
        "config": {
            "sample_questions": [
                {"id": "10000000000000000000000000000001", "question": [q1]},
                {"id": "10000000000000000000000000000002", "question": [q2]},
                {"id": "10000000000000000000000000000003", "question": ["Which routes are highest risk today?"]},
                {"id": "10000000000000000000000000000004", "question": ["Where are today's late stops clustered?"]},
            ]
        },
        "data_sources": {"tables": tables},
        "instructions": {
            "example_question_sqls": [
                {"id": "20000000000000000000000000000001", "question": [q1], "sql": [q1_sql]},
                {"id": "20000000000000000000000000000002", "question": [q2], "sql": [q2_sql]},
            ],
            "text_instructions": [
                {
                    "id": "30000000000000000000000000000001",
                    "content": [
                        "\n".join(
                            [
                                "## PURPOSE",
                                "- Answer dispatcher and ops manager questions about synthetic delivery operations.",
                                "- The SLA story lives in depot_sla_daily and delivery_history.",
                                "- Today's map and risk live in routes, stops, depots, and route_paths.",
                            ]
                        ),
                        "## DISAMBIGUATION\n- Last week means the prior seven complete calendar days, excluding today.\n- Northeast refers to rows where region = 'Northeast'.",
                        "\n".join(
                            [
                                "## Instructions you must follow when providing summaries",
                                "- Always name the date range used.",
                                "- For SLA questions, compare on_time_pct to sla_target_pct.",
                                "- Mention common late cause_code and carrier patterns.",
                            ]
                        ),
                    ],
                }
            ],
        },
        "benchmarks": {
            "questions": [
                {
                    "id": "40000000000000000000000000000001",
                    "question": [q1],
                    "answer": [{"format": "SQL", "content": [q1_sql]}],
                },
                {
                    "id": "40000000000000000000000000000002",
                    "question": [q2],
                    "answer": [{"format": "SQL", "content": [q2_sql]}],
                },
            ]
        },
    }


def find_genie_space(profile: str, title: str, parent_path: str | None = None) -> str | None:
    try:
        payload = run_cli_json(["genie", "list-spaces"], profile)
    except RuntimeError:
        return None
    spaces = json_items(payload, "spaces")
    for space in spaces:
        if space.get("title") != title:
            continue
        if parent_path and space.get("parent_path") not in {None, parent_path}:
            continue
        if space.get("title") == title:
            return space.get("space_id") or space.get("id")
    return None


def upsert_genie_space(config: Config, warehouse_id: str, owner: OwnerContext) -> str:
    serialized = json.dumps(build_genie_payload(config), separators=(",", ":"))
    title = genie_title(config, owner)
    existing_id = find_genie_space(config.profile, title, owner.parent_path)
    if existing_id:
        run_cli(
            ["genie", "update-space", existing_id, "--json", json.dumps({"serialized_space": serialized})],
            config.profile,
        )
        return existing_id

    run_cli(["workspace", "mkdirs", owner.parent_path], config.profile)
    created = run_cli_json(
        [
            "genie",
            "create-space",
            "--json",
            json.dumps(
                {
                    "warehouse_id": warehouse_id,
                    "title": title,
                    "description": "Curated Genie agent for Dispatch Control Tower workshop gold tables.",
                    "parent_path": owner.parent_path,
                    "serialized_space": serialized,
                }
            ),
        ],
        config.profile,
    )
    return created.get("space_id") or created.get("id") or find_genie_space(config.profile, title, owner.parent_path) or ""


def lakebase_project_id(config: Config, owner: OwnerContext) -> str:
    raw = f"dispatch-workshop-{owner.user_slug}-{config.catalog}-{config.schema}".lower().replace("_", "-")
    cleaned = re.sub(r"[^a-z0-9-]", "-", raw).strip("-")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"p-{cleaned}"
    return cleaned[:63].rstrip("-")


def wait_for_cli_items(args: list[str], profile: str, key: str, label: str, attempts: int = 30) -> list[Any]:
    for _ in range(attempts):
        items = json_items(run_cli_json(args, profile), key)
        if items:
            return items
        time.sleep(5)
    raise RuntimeError(f"Lakebase project is still provisioning: no {label} found after waiting.")


def ensure_lakebase(config: Config, owner: OwnerContext, state: dict[str, Any]) -> dict[str, str]:
    project_id = lakebase_project_id(config, owner)
    project_name = f"projects/{project_id}"
    projects = run_cli_json(["postgres", "list-projects"], config.profile)
    existing = json_items(projects, "projects")
    created_project = False
    if not any(project.get("name") == project_name for project in existing):
        print(f"Creating Lakebase project {project_id}")
        run_cli(
            [
                "postgres",
                "create-project",
                project_id,
                "--json",
                json.dumps({"spec": {"display_name": "Dispatch Control Tower Workshop"}}),
            ],
            config.profile,
        )
        created_project = True

    branch = wait_for_cli_items(["postgres", "list-branches", project_name], config.profile, "branches", "branches")[0]
    branch_name = branch["name"]
    endpoint = wait_for_cli_items(["postgres", "list-endpoints", branch_name], config.profile, "endpoints", "endpoints")[0]
    endpoint_name = endpoint["name"]
    database = wait_for_cli_items(["postgres", "list-databases", branch_name], config.profile, "databases", "databases")[0]
    database_name = database["name"]
    endpoint_detail = run_cli_json(["postgres", "get-endpoint", endpoint_name], config.profile)
    host = endpoint_detail.get("status", {}).get("hosts", {}).get("host", "")
    if not host:
        raise RuntimeError(f"Lakebase endpoint {endpoint_name} has no host yet; rerun setup after provisioning finishes.")
    postgres_db = database.get("status", {}).get("postgres_database") or "databricks_postgres"

    try:
        subprocess.run(
            [
                "databricks",
                "psql",
                "--project",
                project_id,
                "--profile",
                config.profile,
                "--",
                "-d",
                postgres_db,
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                LAKEBASE_DDL,
            ],
            text=True,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Databricks CLI is required but was not found on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() or exc.stdout.strip()
        raise RuntimeError(
            "Lakebase project was created/reused, but table DDL failed. The setup uses current "
            "`databricks postgres` project APIs plus `databricks psql` for Postgres DDL.\n"
            f"{details}"
        ) from exc

    if created_project:
        state["lakebase_project"] = project_name
        state["lakebase_created_by_setup"] = True

    return {
        "LAKEBASE_PROJECT": project_name,
        "LAKEBASE_BRANCH": branch_name,
        "LAKEBASE_ENDPOINT": endpoint_name,
        "LAKEBASE_DATABASE": database_name,
        "PGHOST": host,
        "PGDATABASE": postgres_db,
        "PGPORT": "5432",
        "PGSSLMODE": "require",
    }


def setup(config: Config) -> None:
    w = WorkspaceClient(profile=config.profile)
    owner = owner_context(w)
    state = read_state(config, owner)
    warehouse_id = select_warehouse(w, config.warehouse_id)
    create_uc_objects(config, w, warehouse_id)
    data = generate(utc_today())
    assert_schema(data)
    with tempfile.TemporaryDirectory(prefix="dispatch-workshop-") as tmp:
        out_dir = Path(tmp) / "gold"
        write_jsonl(data, out_dir)
        volume_path = upload_generated_files(config, out_dir)
        load_gold_tables(config, w, warehouse_id, volume_path, owner)

    lakebase_info = {"LAKEBASE_SKIPPED": "true"} if config.skip_lakebase else ensure_lakebase(config, owner, state)
    genie_space_id = upsert_genie_space(config, warehouse_id, owner)
    state.update(
        {
            "catalog": config.catalog,
            "schema": config.schema,
            "owner_marker": owner.marker,
            "genie_space_id": genie_space_id,
            "genie_title": genie_title(config, owner),
        }
    )
    write_state(config, owner, state)

    print("\nSetup complete. Configure the app with:")
    summary = {
        "DBX_CATALOG": config.catalog,
        "DBX_SCHEMA": config.schema,
        "DBX_WAREHOUSE_ID": warehouse_id,
        "GENIE_SPACE_ID": genie_space_id,
        **lakebase_info,
    }
    for key, value in summary.items():
        print(f"export {key}={value}")


def teardown(config: Config) -> None:
    w = WorkspaceClient(profile=config.profile)
    owner = owner_context(w)
    state = read_state(config, owner)
    warehouse_id = select_warehouse(w, config.warehouse_id)
    for table in reversed(TABLE_ORDER):
        if table_exists(config, w, warehouse_id, table):
            marker = table_property(config, w, warehouse_id, table, OWNER_PROPERTY)
            if marker != owner.marker:
                raise RuntimeError(f"Refusing to drop unowned table {config.catalog}.{config.schema}.{table}")
            execute_sql(w, warehouse_id, f"DROP TABLE IF EXISTS {table_name(config, table)}")
    run_cli(
        ["fs", "rm", "-r", f"dbfs:/Volumes/{config.catalog}/{config.schema}/{VOLUME_NAME}/gold_jsonl"],
        config.profile,
    )
    space_id = state.get("genie_space_id") or find_genie_space(config.profile, genie_title(config, owner), owner.parent_path)
    if space_id:
        run_cli(["genie", "trash-space", space_id], config.profile)
    if not config.skip_lakebase and state.get("lakebase_created_by_setup"):
        project_name = state.get("lakebase_project")
        try:
            run_cli(["postgres", "delete-project", project_name], config.profile)
        except RuntimeError as exc:
            print(f"Lakebase project delete skipped or failed: {exc}", file=sys.stderr)
    elif not config.skip_lakebase:
        print("Lakebase project not deleted because this setup did not record creating it.")
    print("Teardown complete.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or tear down workshop data assets")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--catalog", default="workshop_dispatch")
    parser.add_argument("--schema", default="gold")
    parser.add_argument("--warehouse-id")
    parser.add_argument("--skip-lakebase", action="store_true")
    parser.add_argument("--teardown", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    if shutil.which("databricks") is None:
        raise SystemExit("Databricks CLI is required but was not found on PATH.")
    args = parse_args(argv)
    config = Config(
        profile=args.profile,
        catalog=args.catalog,
        schema=args.schema,
        warehouse_id=args.warehouse_id,
        skip_lakebase=args.skip_lakebase,
    )
    if args.teardown:
        teardown(config)
    else:
        setup(config)


if __name__ == "__main__":
    main()
