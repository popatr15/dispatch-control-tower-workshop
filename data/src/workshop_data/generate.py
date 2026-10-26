"""Deterministic synthetic data generator for the Dispatch Control Tower workshop."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from workshop_data.contract import TABLE_COLUMNS, TABLE_ORDER

SEED = 20261026
TODAY_ROUTE_COUNT = 25
TODAY_STOP_COUNT = 2500
HISTORY_DAYS = 30

HIGH_RISK_DEPOTS = {"DEPOT_BOS", "DEPOT_NYC"}
NE_CARRIER_ID = "CAR_NEF"

DEPOTS = [
    ("DEPOT_BOS", "Boston Logan Depot", "Boston", "MA", "Northeast", 42.3601, -71.0589, 85.0, 0.93),
    ("DEPOT_NYC", "Newark Metro Depot", "Newark", "NJ", "Northeast", 40.7357, -74.1724, 80.0, 0.94),
    ("DEPOT_PHL", "Philadelphia Rail Depot", "Philadelphia", "PA", "Northeast", 39.9526, -75.1652, 70.0, 0.93),
    ("DEPOT_ATL", "Atlanta South Depot", "Atlanta", "GA", "Southeast", 33.7490, -84.3880, 95.0, 0.92),
    ("DEPOT_CHI", "Chicago Midway Depot", "Chicago", "IL", "Midwest", 41.8781, -87.6298, 100.0, 0.92),
    ("DEPOT_DAL", "Dallas Trinity Depot", "Dallas", "TX", "Southwest", 32.7767, -96.7970, 110.0, 0.91),
    ("DEPOT_DEN", "Denver Front Range Depot", "Denver", "CO", "West", 39.7392, -104.9903, 120.0, 0.91),
    ("DEPOT_LAX", "Los Angeles Basin Depot", "Los Angeles", "CA", "West", 34.0522, -118.2437, 90.0, 0.92),
]

CARRIERS = [
    ("CAR_NEF", "Northeast Freight Express", "NEFX"),
    ("CAR_RAP", "RapidRoute Logistics", "RPDL"),
    ("CAR_BLU", "BlueLine Carrier", "BLUC"),
    ("CAR_SUM", "Summit Parcel", "SUMP"),
]

CITY_OFFSETS = {
    "DEPOT_BOS": [
        ("Boston", "MA", 0.05, -0.04),
        ("Cambridge", "MA", 0.07, -0.10),
        ("Worcester", "MA", -0.45, -0.70),
        ("Lowell", "MA", 0.28, -0.37),
    ],
    "DEPOT_NYC": [
        ("Newark", "NJ", 0.02, -0.02),
        ("Jersey City", "NJ", -0.02, 0.10),
        ("Brooklyn", "NY", -0.08, 0.18),
        ("Yonkers", "NY", 0.28, 0.08),
    ],
    "DEPOT_PHL": [
        ("Philadelphia", "PA", 0.02, 0.04),
        ("Camden", "NJ", 0.02, 0.10),
        ("King of Prussia", "PA", 0.11, -0.38),
        ("Trenton", "NJ", 0.28, 0.50),
    ],
    "DEPOT_ATL": [
        ("Atlanta", "GA", 0.02, 0.02),
        ("Marietta", "GA", 0.20, -0.25),
        ("Decatur", "GA", 0.05, 0.20),
        ("Sandy Springs", "GA", 0.18, -0.05),
    ],
    "DEPOT_CHI": [
        ("Chicago", "IL", 0.02, 0.02),
        ("Evanston", "IL", 0.20, 0.02),
        ("Naperville", "IL", -0.10, -0.55),
        ("Gary", "IN", -0.25, 0.45),
    ],
    "DEPOT_DAL": [
        ("Dallas", "TX", 0.02, 0.02),
        ("Irving", "TX", 0.04, -0.18),
        ("Plano", "TX", 0.25, -0.05),
        ("Fort Worth", "TX", -0.02, -0.65),
    ],
    "DEPOT_DEN": [
        ("Denver", "CO", 0.02, 0.02),
        ("Aurora", "CO", -0.02, 0.25),
        ("Boulder", "CO", 0.28, -0.35),
        ("Lakewood", "CO", -0.06, -0.18),
    ],
    "DEPOT_LAX": [
        ("Los Angeles", "CA", 0.02, 0.02),
        ("Long Beach", "CA", -0.28, 0.10),
        ("Pasadena", "CA", 0.18, 0.15),
        ("Anaheim", "CA", -0.30, 0.35),
    ],
}


def stable_int(*parts: object) -> int:
    text = "|".join(str(part) for part in parts)
    return int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)


def iso_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat(sep=" ")


def weighted_choice(rng: random.Random, options: list[tuple[str, float]]) -> str:
    marker = rng.random() * sum(weight for _, weight in options)
    upto = 0.0
    for value, weight in options:
        upto += weight
        if marker <= upto:
            return value
    return options[-1][0]


def jittered_point(rng: random.Random, depot: dict[str, Any], sequence: int) -> tuple[str, str, float, float]:
    cities = CITY_OFFSETS[depot["depot_id"]]
    city, state, lat_offset, lon_offset = cities[sequence % len(cities)]
    return (
        city,
        state,
        round(depot["lat"] + lat_offset + rng.uniform(-0.08, 0.08), 6),
        round(depot["lon"] + lon_offset + rng.uniform(-0.08, 0.08), 6),
    )


def make_depots() -> list[dict[str, Any]]:
    keys = [
        "depot_id",
        "name",
        "city",
        "state",
        "region",
        "lat",
        "lon",
        "catchment_radius_km",
        "sla_target_pct",
    ]
    return [dict(zip(keys, row, strict=True)) for row in DEPOTS]


def make_carriers() -> list[dict[str, Any]]:
    return [dict(zip(["carrier_id", "name", "scac"], row, strict=True)) for row in CARRIERS]


def make_vehicles(depots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vehicle_types = ["sprinter_van", "box_truck", "reefer", "straight_truck"]
    vehicles = []
    for depot_index, depot in enumerate(depots):
        for vehicle_num in range(1, 9 if depot_index < 4 else 8):
            carrier_id = CARRIERS[(depot_index + vehicle_num) % len(CARRIERS)][0]
            if depot["region"] == "Northeast" and vehicle_num in {1, 2, 3}:
                carrier_id = NE_CARRIER_ID
            vehicles.append(
                {
                    "vehicle_id": f"VEH_{depot['depot_id'][-3:]}_{vehicle_num:02d}",
                    "depot_id": depot["depot_id"],
                    "carrier_id": carrier_id,
                    "vehicle_type": vehicle_types[(depot_index + vehicle_num) % len(vehicle_types)],
                    "capacity_stops": 90 + ((depot_index * 7 + vehicle_num * 11) % 35),
                }
            )
    return vehicles[:60]


def make_routes(
    today: date, depots: list[dict[str, Any]], vehicles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    routes = []
    depot_lookup = {depot["depot_id"]: depot for depot in depots}
    vehicles_by_depot: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for vehicle in vehicles:
        vehicles_by_depot[vehicle["depot_id"]].append(vehicle)

    route_num = 1
    depot_plan = [
        "DEPOT_BOS",
        "DEPOT_NYC",
        "DEPOT_PHL",
        "DEPOT_ATL",
        "DEPOT_CHI",
        "DEPOT_DAL",
        "DEPOT_DEN",
        "DEPOT_LAX",
    ] * 4
    for depot_id in depot_plan[:TODAY_ROUTE_COUNT]:
        depot = depot_lookup[depot_id]
        vehicle = vehicles_by_depot[depot_id][route_num % len(vehicles_by_depot[depot_id])]
        high_risk = route_num <= 7
        risk_score = round(0.82 + (route_num % 6) * 0.025, 3) if high_risk else round(0.18 + (route_num % 11) * 0.045, 3)
        status = "delayed" if high_risk and route_num % 2 == 0 else "in_progress"
        if route_num > 20:
            status = "planned"
        risk_reason = "weather and traffic cluster affecting Northeast SLA" if depot["region"] == "Northeast" and high_risk else "normal operating conditions"
        if high_risk and depot["region"] != "Northeast":
            risk_reason = "capacity pressure from dense delivery window"
        routes.append(
            {
                "route_id": f"R-{today.strftime('%Y%m%d')}-{route_num:03d}",
                "route_date": today.isoformat(),
                "depot_id": depot_id,
                "vehicle_id": vehicle["vehicle_id"],
                "driver_name": f"Driver {route_num:02d}",
                "planned_start_ts": iso_dt(datetime.combine(today, time(7 + route_num % 4, 0))),
                "status": status,
                "planned_stops": 0,
                "risk_score": risk_score,
                "risk_reason": risk_reason,
            }
        )
        route_num += 1
    return routes


def stop_status(route: dict[str, Any], seq: int, route_size: int) -> tuple[str, int, str | None]:
    high_risk = route["risk_score"] >= 0.75
    ne_late = route["depot_id"] in HIGH_RISK_DEPOTS and seq % 3 == 0
    if high_risk and (seq > route_size * 0.65 or ne_late):
        reason = "weather" if route["depot_id"] in HIGH_RISK_DEPOTS else "capacity"
        return "late", 18 + (seq % 9) * 7, reason
    if high_risk and seq % 5 in {1, 4}:
        return "at_risk", 0, "traffic" if route["depot_id"] in HIGH_RISK_DEPOTS else "capacity"
    if seq % 19 == 0:
        return "delivered", 0, None
    return "on_time", 0, None


def utc_today() -> date:
    return datetime.now(UTC).date()


def make_stops_and_paths(
    today: date, depots: list[dict[str, Any]], routes: list[dict[str, Any]], vehicles: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(SEED)
    depot_lookup = {depot["depot_id"]: depot for depot in depots}
    vehicle_lookup = {vehicle["vehicle_id"]: vehicle for vehicle in vehicles}
    base_per_route = TODAY_STOP_COUNT // len(routes)
    extra = TODAY_STOP_COUNT % len(routes)
    stops: list[dict[str, Any]] = []
    route_paths: list[dict[str, Any]] = []

    for route_index, route in enumerate(routes):
        depot = depot_lookup[route["depot_id"]]
        route_size = base_per_route + (1 if route_index < extra else 0)
        route["planned_stops"] = route_size
        route_paths.append(
            {"route_id": route["route_id"], "seq": 0, "lat": depot["lat"], "lon": depot["lon"]}
        )
        path_seq = 1
        start_dt = datetime.fromisoformat(route["planned_start_ts"])
        for seq in range(1, route_size + 1):
            city, state, lat, lon = jittered_point(rng, depot, seq)
            promised_start = start_dt + timedelta(minutes=8 * seq)
            promised_end = promised_start + timedelta(minutes=45)
            status, late_minutes, reason = stop_status(route, seq, route_size)
            if route["status"] == "planned":
                status, late_minutes, reason = "on_time", 0, None
            elif status == "on_time" and seq <= route_size * 0.35:
                status = "delivered"
            eta = promised_end + timedelta(minutes=late_minutes if status == "late" else -8)
            actual = eta if status == "delivered" else None
            carrier_id = vehicle_lookup[route["vehicle_id"]]["carrier_id"]
            stops.append(
                {
                    "stop_id": f"S-{today.strftime('%Y%m%d')}-{route_index + 1:03d}-{seq:03d}",
                    "route_id": route["route_id"],
                    "route_date": today.isoformat(),
                    "sequence": seq,
                    "customer_name": f"Customer {route_index + 1:03d}-{seq:03d}",
                    "address": f"{100 + seq} {city} Distribution Way",
                    "city": city,
                    "state": state,
                    "region": depot["region"],
                    "lat": lat,
                    "lon": lon,
                    "promised_window_start": iso_dt(promised_start),
                    "promised_window_end": iso_dt(promised_end),
                    "eta_ts": iso_dt(eta),
                    "actual_arrival_ts": iso_dt(actual),
                    "status": status,
                    "carrier_id": carrier_id,
                    "depot_id": route["depot_id"],
                    "late_minutes": late_minutes,
                    "late_reason_code": reason,
                }
            )
            if seq % max(1, math.floor(route_size / 12)) == 0 or seq == route_size:
                route_paths.append(
                    {
                        "route_id": route["route_id"],
                        "seq": path_seq,
                        "lat": lat,
                        "lon": lon,
                    }
                )
                path_seq += 1
    return stops, route_paths


def make_delivery_history(today: date, depots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for day_offset in range(1, HISTORY_DAYS + 1):
        delivery_date = today - timedelta(days=day_offset)
        for depot in depots:
            daily_deliveries = 295 + stable_int(delivery_date, depot["depot_id"]) % 45
            for seq in range(daily_deliveries):
                carrier_id = CARRIERS[(seq + day_offset) % len(CARRIERS)][0]
                cause = "none"
                late_probability = 0.035
                if day_offset <= 7 and depot["depot_id"] in HIGH_RISK_DEPOTS:
                    late_probability = 0.22
                    if seq % 2 == 0:
                        carrier_id = NE_CARRIER_ID
                if depot["depot_id"] in HIGH_RISK_DEPOTS and carrier_id == NE_CARRIER_ID:
                    late_probability += 0.08
                marker = (stable_int(today, depot["depot_id"], day_offset, seq) % 1000) / 1000
                is_late = marker < late_probability
                if is_late:
                    cause = "weather" if depot["region"] == "Northeast" and seq % 3 == 0 else "traffic"
                    if seq % 17 == 0:
                        cause = "vehicle_down"
                promised = datetime.combine(delivery_date, time(9, 0)) + timedelta(minutes=seq % 540)
                late_minutes = 0 if not is_late else 10 + (seq % 10) * 6
                rows.append(
                    {
                        "stop_id": f"H-{delivery_date.strftime('%Y%m%d')}-{depot['depot_id']}-{seq:04d}",
                        "delivery_date": delivery_date.isoformat(),
                        "depot_id": depot["depot_id"],
                        "carrier_id": carrier_id,
                        "region": depot["region"],
                        "promised_ts": iso_dt(promised),
                        "actual_ts": iso_dt(promised + timedelta(minutes=late_minutes - 5)),
                        "on_time": not is_late,
                        "late_minutes": late_minutes,
                        "cause_code": cause,
                        "weather_flag": cause == "weather",
                    }
                )
    return rows


def make_depot_sla_daily(
    depots: list[dict[str, Any]], delivery_history: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in delivery_history:
        grouped[(row["depot_id"], row["delivery_date"])].append(row)
    depot_targets = {depot["depot_id"]: depot["sla_target_pct"] for depot in depots}
    rows = []
    for depot_id, sla_date in sorted(grouped):
        records = grouped[(depot_id, sla_date)]
        on_time = sum(1 for row in records if row["on_time"])
        pct = round(on_time / len(records), 4)
        target = depot_targets[depot_id]
        rows.append(
            {
                "depot_id": depot_id,
                "sla_date": sla_date,
                "deliveries": len(records),
                "on_time": on_time,
                "on_time_pct": pct,
                "sla_target_pct": target,
                "sla_met": pct >= target,
            }
        )
    return rows


def generate(today: date | None = None) -> dict[str, list[dict[str, Any]]]:
    today = today or utc_today()
    depots = make_depots()
    carriers = make_carriers()
    vehicles = make_vehicles(depots)
    routes = make_routes(today, depots, vehicles)
    stops, route_paths = make_stops_and_paths(today, depots, routes, vehicles)
    delivery_history = make_delivery_history(today, depots)
    depot_sla_daily = make_depot_sla_daily(depots, delivery_history)
    return {
        "depots": depots,
        "carriers": carriers,
        "vehicles": vehicles,
        "routes": routes,
        "stops": stops,
        "route_paths": route_paths,
        "delivery_history": delivery_history,
        "depot_sla_daily": depot_sla_daily,
    }


def assert_schema(data: dict[str, list[dict[str, Any]]]) -> None:
    for table in TABLE_ORDER:
        expected = [column.name for column in TABLE_COLUMNS[table]]
        for row in data[table]:
            actual = list(row)
            if actual != expected:
                raise ValueError(f"{table} schema mismatch: expected {expected}, got {actual}")


def write_jsonl(data: dict[str, list[dict[str, Any]]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for table in TABLE_ORDER:
        with (output_dir / f"{table}.jsonl").open("w", encoding="utf-8") as handle:
            for row in data[table]:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic workshop JSONL data")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--today", type=date.fromisoformat, default=utc_today())
    args = parser.parse_args()
    data = generate(args.today)
    assert_schema(data)
    write_jsonl(data, args.output_dir)
    summary = {table: len(rows) for table, rows in data.items()}
    print(json.dumps({"seed": SEED, "today": args.today.isoformat(), "rows": summary}, indent=2))


if __name__ == "__main__":
    main()
