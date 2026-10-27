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
    read_state,
    resolve_verify_config,
    select_warehouse,
)

CANONICAL_QUESTIONS = [
    "Which depots missed SLA most last week, and what do the late stops have in common?",
    "Show late deliveries in the Northeast by carrier.",
]
CHRONIC_SLA_DEPOTS = {"DEPOT_BOS", "DEPOT_NYC"}
DEPOT_ALIASES = {
    "DEPOT_BOS": "DEPOT_BOS",
    "DEPOT_NYC": "DEPOT_NYC",
    "Boston Logan Depot": "DEPOT_BOS",
    "Newark Metro Depot": "DEPOT_NYC",
    "Boston": "DEPOT_BOS",
    "Newark": "DEPOT_NYC",
}
TOP_NE_CARRIER = "CAR_NEF"
CARRIER_ALIASES = {
    "CAR_NEF": "CAR_NEF",
    "Northeast Freight Express": "CAR_NEF",
    "NEFX": "CAR_NEF",
}


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
        str(row[0])
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
    if missed_depots != CHRONIC_SLA_DEPOTS:
        raise AssertionError(
            f"Expected exactly chronic SLA misses for {CHRONIC_SLA_DEPOTS}; got {missed_depots}"
        )

    top_ne_carrier = str(
        rows(
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
    )
    if top_ne_carrier != TOP_NE_CARRIER:
        raise AssertionError(f"Expected {TOP_NE_CARRIER} as Northeast late-delivery cluster; got {top_ne_carrier}")


def certified_sqls(config: Config) -> list[str]:
    payload = build_genie_payload(config)
    return [item["sql"][0] for item in payload["instructions"]["example_question_sqls"]]


def depot_ids_from_rows(result_rows: list[list[Any]]) -> set[str]:
    found: set[str] = set()
    for row in result_rows:
        for cell in row:
            alias = DEPOT_ALIASES.get("" if cell is None else str(cell))
            if alias:
                found.add(alias)
    return found


def top_carrier_from_rows(result_rows: list[list[Any]]) -> str:
    if not result_rows:
        raise AssertionError("Expected at least one carrier row")
    for cell in result_rows[0]:
        alias = CARRIER_ALIASES.get("" if cell is None else str(cell))
        if alias:
            return alias
    return "" if result_rows[0][0] is None else str(result_rows[0][0])


def assert_genie_key_match(question: str, certified_rows: list[list[Any]], genie_rows: list[list[Any]]) -> None:
    if question == CANONICAL_QUESTIONS[0]:
        certified_depots = depot_ids_from_rows(certified_rows)
        genie_depots = depot_ids_from_rows(genie_rows)
        if certified_depots != genie_depots:
            raise AssertionError(
                f"Genie depot set for {question!r} did not match certified set. "
                f"certified={certified_depots} genie={genie_depots}"
            )
        if certified_depots != CHRONIC_SLA_DEPOTS:
            raise AssertionError(
                f"Expected certified depot set {CHRONIC_SLA_DEPOTS}; got {certified_depots}"
            )
        return
    if question == CANONICAL_QUESTIONS[1]:
        certified_top = top_carrier_from_rows(certified_rows)
        genie_top = top_carrier_from_rows(genie_rows)
        if certified_top != genie_top:
            raise AssertionError(
                f"Genie top carrier for {question!r} did not match certified. "
                f"certified={certified_top} genie={genie_top}"
            )
        if certified_top != TOP_NE_CARRIER:
            raise AssertionError(f"Expected certified top carrier {TOP_NE_CARRIER}; got {certified_top}")
        return
    raise AssertionError(f"No key-column matcher for question {question!r}")


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


def assert_genie_answers(
    config: Config, w: WorkspaceClient, warehouse_id: str, profile: str, space_id: str
) -> None:
    for question, certified_sql in zip(CANONICAL_QUESTIONS, certified_sqls(config), strict=True):
        certified_rows = rows(execute_sql(w, warehouse_id, certified_sql))
        if not certified_rows:
            raise AssertionError(f"Certified SQL returned no rows for {question!r}")
        message = ask_genie(profile, space_id, question)
        genie_rows = genie_result_rows(profile, space_id, message)
        assert_genie_key_match(question, certified_rows, genie_rows)
        print(f"Genie OK: {question}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify workshop data and Genie answers")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--catalog")
    parser.add_argument("--schema")
    parser.add_argument("--warehouse-id")
    parser.add_argument("--genie-space-id")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = resolve_verify_config(args)
    w = WorkspaceClient(profile=args.profile)
    owner = owner_context(w)
    warehouse_id = select_warehouse(w, args.warehouse_id)
    assert_sql_story(config, w, warehouse_id)
    print("SQL row-count and storyline assertions passed.")
    state = read_state(config, owner)
    space_id = (
        args.genie_space_id
        or state.get("genie_space_id")
        or find_genie_space(args.profile, genie_title(config, owner), owner.parent_path)
    )
    if not space_id:
        raise AssertionError("No Genie space id supplied and no reusable workshop space found.")
    assert_genie_answers(config, w, warehouse_id, args.profile, space_id)
    print("Verification complete.")


if __name__ == "__main__":
    main()
