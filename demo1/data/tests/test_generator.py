from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, timedelta

from workshop_data.contract import TABLE_COLUMNS, TABLE_ORDER
from workshop_data.generate import generate

FIXED_DAY = date(2026, 10, 26)


def digest(data: dict[str, list[dict]]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def test_generator_is_deterministic() -> None:
    first = generate(FIXED_DAY)
    second = generate(FIXED_DAY)
    assert digest(first) == digest(second)


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

    assert misses_by_depot["DEPOT_BOS"] >= 4
    assert misses_by_depot["DEPOT_NYC"] >= 4

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
