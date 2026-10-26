from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from workshop_data.contract import TABLE_COLUMNS, TABLE_ORDER
from workshop_data.generate import generate

FIXED_DAY = date(2026, 10, 26)
MONTH_BOUNDARY_DAY = date(2026, 3, 1)
GOLDEN_DIGEST = "41a0efa297dadffdfa1cf1e976ee59d59056470cc1f57f4c73eb38718727caf3"


def digest(data: dict[str, list[dict]]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def test_generator_is_deterministic() -> None:
    first = generate(FIXED_DAY)
    second = generate(FIXED_DAY)
    assert digest(first) == digest(second)
    assert digest(first) == GOLDEN_DIGEST


def test_schema_conforms_to_contract_order_and_names() -> None:
    data = generate(FIXED_DAY)
    assert tuple(data) == TABLE_ORDER
    for table, columns in TABLE_COLUMNS.items():
        expected = [column.name for column in columns]
        assert data[table], table
        assert list(data[table][0]) == expected
        assert all(list(row) == expected for row in data[table])


def test_scale_and_today_storylines() -> None:
    data = generate(FIXED_DAY)
    assert len(data["depots"]) == 8
    assert sum(1 for depot in data["depots"] if depot["region"] == "Northeast") >= 2
    assert len(data["carriers"]) >= 3
    assert len(data["vehicles"]) >= 60
    assert len(data["routes"]) == 25
    assert len(data["stops"]) == 2500

    statuses = Counter(row["status"] for row in data["stops"])
    assert statuses["on_time"] > 0
    assert statuses["at_risk"] > 0
    assert statuses["late"] > 0

    high_risk_routes = [route for route in data["routes"] if route["risk_score"] >= 0.75]
    assert len(high_risk_routes) >= 5
    assert any("Northeast" in route["risk_reason"] for route in high_risk_routes)

    path_counts = Counter(row["route_id"] for row in data["route_paths"])
    assert all(count >= 3 for count in path_counts.values())
    assert set(path_counts) == {route["route_id"] for route in data["routes"]}


def test_last_week_chronic_sla_misses_and_ne_carrier_cluster() -> None:
    data = generate(FIXED_DAY)
    last_week = {
        (FIXED_DAY - timedelta(days=offset)).isoformat()
        for offset in range(1, 8)
    }
    misses_by_depot: dict[str, int] = defaultdict(int)
    for row in data["depot_sla_daily"]:
        if row["sla_date"] in last_week and not row["sla_met"]:
            misses_by_depot[row["depot_id"]] += 1

    assert {depot for depot, days in misses_by_depot.items() if days >= 4} == {
        "DEPOT_BOS",
        "DEPOT_NYC",
    }

    late_ne_by_carrier = Counter(
        row["carrier_id"]
        for row in data["delivery_history"]
        if row["region"] == "Northeast" and not row["on_time"]
    )
    assert late_ne_by_carrier.most_common(1)[0][0] == "CAR_NEF"
    assert late_ne_by_carrier["CAR_NEF"] > late_ne_by_carrier["CAR_RAP"]


def test_dates_are_relative_to_requested_run_day() -> None:
    data = generate(FIXED_DAY)
    assert {row["route_date"] for row in data["routes"]} == {FIXED_DAY.isoformat()}
    assert {row["route_date"] for row in data["stops"]} == {FIXED_DAY.isoformat()}
    history_dates = {row["delivery_date"] for row in data["delivery_history"]}
    assert (FIXED_DAY - timedelta(days=1)).isoformat() in history_dates
    assert (FIXED_DAY - timedelta(days=30)).isoformat() in history_dates
    assert FIXED_DAY.isoformat() not in history_dates

    boundary_data = generate(MONTH_BOUNDARY_DAY)
    boundary_history_dates = {row["delivery_date"] for row in boundary_data["delivery_history"]}
    assert (MONTH_BOUNDARY_DAY - timedelta(days=1)).isoformat() in boundary_history_dates
    assert (MONTH_BOUNDARY_DAY - timedelta(days=30)).isoformat() in boundary_history_dates


def test_allowed_values_and_stop_state_coherence() -> None:
    data = generate(FIXED_DAY)
    assert {row["region"] for row in data["depots"]} <= {
        "Northeast",
        "Southeast",
        "Midwest",
        "Southwest",
        "West",
    }
    assert {row["status"] for row in data["routes"]} <= {
        "planned",
        "in_progress",
        "delayed",
        "completed",
    }
    assert {row["status"] for row in data["stops"]} <= {"delivered", "on_time", "at_risk", "late"}
    assert {row["cause_code"] for row in data["delivery_history"]} <= {
        "traffic",
        "weather",
        "vehicle_down",
        "customer_unavailable",
        "address_issue",
        "capacity",
        "none",
    }
    route_status = {row["route_id"]: row["status"] for row in data["routes"]}
    for stop in data["stops"]:
        if route_status[stop["route_id"]] == "planned":
            assert stop["actual_arrival_ts"] is None
            assert stop["status"] not in {"delivered", "on_time"}
        if stop["status"] != "delivered":
            assert stop["actual_arrival_ts"] is None


def test_referential_integrity_and_carrier_spread() -> None:
    data = generate(FIXED_DAY)
    routes = {row["route_id"]: row for row in data["routes"]}
    vehicles = {row["vehicle_id"]: row for row in data["vehicles"]}
    carriers = {row["carrier_id"] for row in data["carriers"]}
    depots = {row["depot_id"] for row in data["depots"]}

    assert all(vehicle["depot_id"] in depots and vehicle["carrier_id"] in carriers for vehicle in vehicles.values())
    stop_carriers = Counter(row["carrier_id"] for row in data["stops"])
    assert len(stop_carriers) >= 3
    for stop in data["stops"]:
        route = routes[stop["route_id"]]
        vehicle = vehicles[route["vehicle_id"]]
        assert stop["depot_id"] == route["depot_id"]
        assert stop["carrier_id"] == vehicle["carrier_id"]
        assert stop["carrier_id"] in carriers


def test_contract_columns_match_docs() -> None:
    contract_path = Path(__file__).parents[2] / "docs" / "DATA_CONTRACT.md"
    text = contract_path.read_text(encoding="utf-8")
    for table in TABLE_ORDER:
        match = re.search(rf"^\| {table} \| (?P<columns>.+?) \|$", text, re.MULTILINE)
        assert match, table
        docs_columns = [part.split()[0] for part in match.group("columns").split(", ")]
        assert docs_columns == [column.name for column in TABLE_COLUMNS[table]]
