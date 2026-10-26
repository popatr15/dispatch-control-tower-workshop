"""Live verification for deployed workshop data assets."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from typing import Any

from databricks.sdk import WorkspaceClient

from workshop_data.deploy import (
    Config,
    build_genie_payload,
    execute_sql,
    find_genie_space,
    genie_title,
    owner_context,
    quote_ident,
    select_warehouse,
)

CANONICAL_QUESTIONS = [
    "Which depots missed SLA most last week, and what do the late stops have in common?",
    "Show late deliveries in the Northeast by carrier.",
]


def rows(response: Any) -> list[list[Any]]:
    return list(response.result.data_array or []) if response.result else []


def fq(config: Config, table: str) -> str:
    return f"{quote_ident(config.catalog)}.{quote_ident(config.schema)}.{quote_ident(table)}"


def scalar(w: WorkspaceClient, warehouse_id: str, sql: str) -> Any:
    result_rows = rows(execute_sql(w, warehouse_id, sql))
    if not result_rows:
        raise AssertionError(f"Query returned no rows: {sql}")
    return result_rows[0][0]


def scalar_int(w: WorkspaceClient, warehouse_id: str, sql: str) -> int:
    return int(scalar(w, warehouse_id, sql))


def assert_sql_story(config: Config, w: WorkspaceClient, warehouse_id: str) -> None:
    assert scalar_int(w, warehouse_id, f"SELECT COUNT(*) FROM {fq(config, 'depots')}") == 8
    assert scalar_int(w, warehouse_id, f"SELECT COUNT(*) FROM {fq(config, 'carriers')}") >= 3
    assert scalar_int(w, warehouse_id, f"SELECT COUNT(*) FROM {fq(config, 'vehicles')}") >= 60
    assert scalar_int(
        w,
        warehouse_id,
        f"SELECT COUNT(*) FROM {fq(config, 'stops')} WHERE route_date = current_date()",
    ) >= 2500
    assert scalar_int(
        w,
        warehouse_id,
        f"SELECT COUNT(*) FROM {fq(config, 'routes')} WHERE route_date = current_date() AND risk_score >= 0.75",
    ) >= 5

    statuses = {
        row[0]: int(row[1])
        for row in rows(
            execute_sql(
                w,
                warehouse_id,
                f"SELECT status, COUNT(*) FROM {fq(config, 'stops')} WHERE route_date = current_date() GROUP BY status",
            )
        )
    }
    for status in ["on_time", "at_risk", "late"]:
        if statuses.get(status, 0) <= 0:
            raise AssertionError(f"Expected today's stops to include {status}; got {statuses}")

    missed_depots = {
        row[0]
        for row in rows(
            execute_sql(
                w,
                warehouse_id,
                f"""
                SELECT depot_id
                FROM {fq(config, 'depot_sla_daily')}
                WHERE sla_date BETWEEN date_sub(current_date(), 7) AND date_sub(current_date(), 1)
                  AND sla_met = false
                GROUP BY depot_id
                HAVING COUNT(*) >= 4
                """,
            )
        )
    }
    expected = {"DEPOT_BOS", "DEPOT_NYC"}
    if missed_depots != expected:
        raise AssertionError(f"Expected exactly chronic SLA misses for {expected}; got {missed_depots}")

    top_ne_carrier = rows(
        execute_sql(
            w,
            warehouse_id,
            f"""
            SELECT carrier_id, COUNT(*) AS late_deliveries
            FROM {fq(config, 'delivery_history')}
            WHERE region = 'Northeast'
              AND on_time = false
              AND delivery_date >= date_sub(current_date(), 30)
            GROUP BY carrier_id
            ORDER BY late_deliveries DESC
            LIMIT 1
            """,
        )
    )[0][0]
    if top_ne_carrier != "CAR_NEF":
        raise AssertionError(f"Expected CAR_NEF as Northeast late-delivery cluster; got {top_ne_carrier}")


def run_cli_json(args: list[str], profile: str) -> Any:
    output = subprocess.run(
        ["databricks", *args, "--profile", profile, "-o", "json"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    return json.loads(output) if output.strip() else {}


def ask_genie(profile: str, space_id: str, question: str) -> dict[str, Any]:
    started = run_cli_json(["genie", "start-conversation", "--no-wait", space_id, question], profile)
    conversation_id = started["conversation_id"]
    message_id = started["message_id"]
    for _ in range(90):
        message = run_cli_json(["genie", "get-message", space_id, conversation_id, message_id], profile)
        status = message.get("status")
        if status in {"COMPLETED", "FAILED", "CANCELLED"}:
            if status != "COMPLETED":
                raise AssertionError(f"Genie failed for {question!r}: {message.get('error')}")
            message.setdefault("conversation_id", conversation_id)
            message.setdefault("message_id", message_id)
            return message
        time.sleep(2)
    raise AssertionError(f"Genie timed out for {question!r}")


def genie_result_rows(profile: str, space_id: str, message: dict[str, Any]) -> list[list[Any]]:
    conversation_id = message["conversation_id"]
    message_id = message["message_id"]
    for attachment in message.get("attachments", []):
        if "query" not in attachment:
            continue
        attachment_id = attachment.get("attachment_id") or attachment.get("id")
        if not attachment_id:
            continue
        result = run_cli_json(
            [
                "genie",
                "get-message-attachment-query-result",
                space_id,
                conversation_id,
                message_id,
                attachment_id,
            ],
            profile,
        )
        statement = result.get("statement_response", {})
        return statement.get("result", {}).get("data_array", []) or []
    raise AssertionError("Genie completed but did not return a query-result attachment.")


def assert_genie_answers(profile: str, space_id: str) -> None:
    expected_markers = [{"Boston", "Newark"}, {"Northeast Freight Express", "NEFX", "CAR_NEF"}]
    for question, markers in zip(CANONICAL_QUESTIONS, expected_markers, strict=True):
        message = ask_genie(profile, space_id, question)
        result_text = json.dumps(genie_result_rows(profile, space_id, message))
        if not result_text or not any(marker in result_text for marker in markers):
            raise AssertionError(f"Genie result rows for {question!r} did not include any of {markers}")
        print(f"Genie OK: {question}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify workshop data and Genie answers")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--catalog", default="workshop_dispatch")
    parser.add_argument("--schema", default="gold")
    parser.add_argument("--warehouse-id")
    parser.add_argument("--genie-space-id")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = Config(
        profile=args.profile,
        catalog=args.catalog,
        schema=args.schema,
        warehouse_id=args.warehouse_id,
        skip_lakebase=True,
    )
    w = WorkspaceClient(profile=args.profile)
    owner = owner_context(w)
    warehouse_id = select_warehouse(w, args.warehouse_id)
    assert_sql_story(config, w, warehouse_id)
    print("SQL row-count and storyline assertions passed.")
    # Build the payload in verification too; this catches certified SQL construction drift early.
    build_genie_payload(config)
    space_id = args.genie_space_id or find_genie_space(args.profile, genie_title(config, owner), owner.parent_path)
    if not space_id:
        raise AssertionError("No Genie space id supplied and no reusable workshop space found.")
    assert_genie_answers(args.profile, space_id)
    print("Verification complete.")


if __name__ == "__main__":
    main()
