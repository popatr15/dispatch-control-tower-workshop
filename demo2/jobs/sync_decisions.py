"""sync_decisions: Lakebase decisions -> UC `{catalog}.{schema}.decision_labels`.

Reads the app's audit_log (every decision with the features seen at decision
time), joins the current outcome of each stop from the gold `stops` table, and
overwrites the labeled table. Re-running is idempotent.
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
    p.add_argument("--app-src", required=True, help="path to demo2/app/src in the workspace")
    p.add_argument("--readers", default="", help="UC principal granted SELECT on the table")
    args = p.parse_args()
    sys.path.insert(0, args.app_src)

    from databricks.sdk import WorkspaceClient
    from pyspark.sql import SparkSession
    from pyspark.sql.types import (
        BooleanType,
        DoubleType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    from dispatch_tower.sync.jobs import (
        ident,
        lakebase_connection,
        read_audit,
        stop_ids_in,
        table_exists,
    )
    from dispatch_tower.sync.labels import LABEL_COLUMNS, build_decision_labels

    spark = SparkSession.builder.getOrCreate()
    ws = WorkspaceClient()
    catalog, schema = ident(args.catalog), ident(args.schema)

    with lakebase_connection(ws, args.lakebase_endpoint, args.lakebase_database) as conn:
        if not table_exists(conn, args.pg_schema, "audit_log"):
            print(
                f"{args.pg_schema}.audit_log not found: start the app once so it creates its schema"
            )
            audit = []
        else:
            audit = read_audit(conn, args.pg_schema)
    print(f"read {len(audit)} audit rows from Lakebase")

    outcomes = {}
    ids = stop_ids_in(audit)
    if ids:
        rows = spark.sql(
            f"SELECT stop_id, status, late_minutes FROM `{catalog}`.`{schema}`.stops "
            "WHERE array_contains(:ids, stop_id)",
            args={"ids": ids},
        ).collect()
        outcomes = {r["stop_id"]: r.asDict() for r in rows}

    labels = build_decision_labels(audit, outcomes)
    types = {
        "decision_id": LongType(),
        "feat_late_minutes": LongType(),
        "outcome_late_minutes": LongType(),
        "feat_route_risk_score": DoubleType(),
        "feat_to_route_risk_score": DoubleType(),
        "amount_usd": DoubleType(),
        "outcome_on_time": BooleanType(),
        "outcome_known": BooleanType(),
    }
    struct = StructType([StructField(c, types.get(c, StringType()), True) for c in LABEL_COLUMNS])
    rows = [
        tuple(
            int(r[c]) if isinstance(types.get(c), LongType) and r[c] is not None else r[c]
            for c in LABEL_COLUMNS
        )
        for r in labels
    ]
    df = spark.createDataFrame(rows, struct)
    target = f"`{catalog}`.`{schema}`.decision_labels"
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(target)
    spark.sql(
        f"COMMENT ON TABLE {target} IS 'Dispatcher/manager decisions synced from Lakebase "
        "(dispatch tower app): label = decision + reason, feat_* = what the user saw, "
        "outcome_* = what happened. Training signal for the next routing model.'"
    )
    if args.readers:
        spark.sql(f"GRANT SELECT ON TABLE {target} TO `{args.readers}`")
    print(f"wrote {len(labels)} rows to {target}")


if __name__ == "__main__":
    main()
