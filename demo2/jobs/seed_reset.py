"""seed_reset: put the demo back to a clean state before a workshop run.

Truncates every app-written Lakebase table, seeds `route_state` from today's
gold routes, and (optionally) empties the synced `decision_labels` table.
"""

import argparse
import sys


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", required=True)
    p.add_argument("--schema", required=True)
    p.add_argument("--lakebase-endpoint", required=True)
    p.add_argument("--lakebase-database", required=True)
    p.add_argument("--pg-schema", default="dispatch")
    p.add_argument("--app-src", required=True)
    p.add_argument("--clear-labels", default="true")
    args = p.parse_args()
    sys.path.insert(0, args.app_src)

    from databricks.sdk import WorkspaceClient
    from pyspark.sql import SparkSession

    from dispatch_tower.sync.jobs import ident, lakebase_connection, reset_statements, table_exists

    spark = SparkSession.builder.getOrCreate()
    ws = WorkspaceClient()
    catalog, schema, pg_schema = ident(args.catalog), ident(args.schema), ident(args.pg_schema)

    routes = spark.sql(
        f"SELECT route_id, status FROM `{catalog}`.`{schema}`.routes "
        "WHERE route_date = current_date()"
    ).collect()

    with lakebase_connection(ws, args.lakebase_endpoint, args.lakebase_database) as conn:
        if not table_exists(conn, pg_schema, "route_state"):
            raise SystemExit(f"{pg_schema} tables not found: deploy and start the app first")
        with conn.transaction():
            for stmt in reset_statements(pg_schema):
                conn.execute(stmt)
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {pg_schema}.route_state (route_id, state, updated_by) "
                    "VALUES (%s, %s, 'seed_reset')",
                    [(r["route_id"], r["status"]) for r in routes],
                )
    print(f"reset Lakebase schema {pg_schema}; seeded {len(routes)} route_state rows")

    if args.clear_labels.lower() == "true":
        spark.sql(f"DROP TABLE IF EXISTS `{catalog}`.`{schema}`.decision_labels")
        print("dropped decision_labels (re-created by sync_decisions)")


if __name__ == "__main__":
    main()
