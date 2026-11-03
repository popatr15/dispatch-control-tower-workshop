"""Deterministic synthetic gold data for offline dev and tests.

Shapes and column names follow docs/DATA_CONTRACT.md. Dates are relative to the
day the process starts, like the demo1 setup script. Storylines mirror the
contract: late stops concentrate on one Northeast carrier.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from ..services.effective import derive_risk
from ..services.scenario import apply_scenario

Row = dict[str, Any]

# Same ids, order and names as the shared workshop data (data/src/workshop_data/generate.py),
# so rehearsing offline shows the same hubs and routes as the deployed app.
DEPOTS = [  # noqa: E501
    ("DEPOT_BOS", "Boston Logan Depot", "Boston", "MA", "Northeast", 42.3601, -71.0589, 85.0, 0.93),
    ("DEPOT_NYC", "Newark Metro Depot", "Newark", "NJ", "Northeast", 40.7357, -74.1724, 80.0, 0.94),
    (
        "DEPOT_PHL",
        "Philadelphia Rail Depot",
        "Philadelphia",
        "PA",
        "Northeast",
        39.9526,
        -75.1652,
        70.0,
        0.93,
    ),
    (
        "DEPOT_ATL",
        "Atlanta South Depot",
        "Atlanta",
        "GA",
        "Southeast",
        33.7490,
        -84.3880,
        95.0,
        0.92,
    ),
    (
        "DEPOT_CHI",
        "Chicago Midway Depot",
        "Chicago",
        "IL",
        "Midwest",
        41.8781,
        -87.6298,
        100.0,
        0.92,
    ),
    (
        "DEPOT_DAL",
        "Dallas Trinity Depot",
        "Dallas",
        "TX",
        "Southwest",
        32.7767,
        -96.7970,
        110.0,
        0.91,
    ),
    (
        "DEPOT_DEN",
        "Denver Front Range Depot",
        "Denver",
        "CO",
        "West",
        39.7392,
        -104.9903,
        120.0,
        0.91,
    ),
    (
        "DEPOT_LAX",
        "Los Angeles Basin Depot",
        "Los Angeles",
        "CA",
        "West",
        34.0522,
        -118.2437,
        90.0,
        0.92,
    ),
]
NE_CARRIER = "CAR_NEF"
CARRIERS = [
    (NE_CARRIER, "Northeast Freight Express", "NEFX"),
    ("CAR_RAP", "RapidRoute Logistics", "RPDL"),
    ("CAR_BLU", "BlueLine Carrier", "BLUC"),
    ("CAR_SUM", "Summit Parcel", "SUMP"),
]
CUSTOMERS = [
    "Acme Supply",
    "Globex Retail",
    "Initech Parts",
    "Umbrella Pharmacy",
    "Hooli Market",
    "Vandelay Imports",
    "Stark Hardware",
    "Wayne Grocers",
    "Wonka Sweets",
    "Cyberdyne Labs",
]
DRIVERS = [
    "A. Rivera",
    "B. Chen",
    "C. Okafor",
    "D. Novak",
    "E. Haddad",
    "F. Silva",
    "G. Ito",
    "H. Moreau",
    "I. Patel",
    "J. Kowalski",
]
CAUSES = ["traffic", "weather", "vehicle_down", "customer_unavailable", "address_issue", "capacity"]


@dataclass
class MockData:
    today: date
    depots: list[Row] = field(default_factory=list)
    carriers: list[Row] = field(default_factory=list)
    vehicles: list[Row] = field(default_factory=list)
    routes: list[Row] = field(default_factory=list)
    stops: list[Row] = field(default_factory=list)
    route_paths: list[Row] = field(default_factory=list)
    history_cells: list[Row] = field(default_factory=list)


def build(
    today: date | None = None,
    *,
    routes_per_day: int = 25,
    stops_per_route: int = 100,
    seed: int = 42,
    hero: bool = False,
) -> MockData:
    """Synthetic day of data. `hero=True` applies the demo2 hero scenario (services/scenario.py)."""
    rng = random.Random(seed)
    today = today or datetime.now(UTC).date()
    data = MockData(today=today)
    data.depots = [
        dict(
            depot_id=d[0],
            name=d[1],
            city=d[2],
            state=d[3],
            region=d[4],
            lat=d[5],
            lon=d[6],
            catchment_radius_km=d[7],
            sla_target_pct=d[8],
        )
        for d in DEPOTS
    ]
    data.carriers = [dict(carrier_id=c[0], name=c[1], scac=c[2]) for c in CARRIERS]
    for i in range(60):
        depot = data.depots[i % len(data.depots)]
        data.vehicles.append(
            dict(
                vehicle_id=f"VEH-{i + 1:03d}",
                depot_id=depot["depot_id"],
                carrier_id=NE_CARRIER if depot["region"] == "Northeast" else CARRIERS[1 + i % 3][0],
                vehicle_type="box_truck" if i % 3 else "van",
                # 100 (full at the default 100 stops/route), 110 or 120
                capacity_stops=100 + 10 * (i % 3),
            )
        )

    stop_seq = 0
    for r in range(routes_per_day):
        vehicle = data.vehicles[r]
        depot = next(d for d in data.depots if d["depot_id"] == vehicle["depot_id"])
        carrier_id = vehicle["carrier_id"]
        troubled = depot["region"] == "Northeast" and carrier_id == NE_CARRIER
        route_id = f"R-{today:%Y%m%d}-{r + 1:03d}"
        start = datetime.combine(today, time(7, 0), tzinfo=UTC) + timedelta(minutes=15 * (r % 4))
        late_p = 0.35 if troubled else 0.04 + 0.02 * (r % 3)
        risk_p = 0.25 if troubled else 0.08
        statuses: list[str] = []
        stop_rows: list[Row] = []
        path = [(depot["lat"], depot["lon"])]
        angle = rng.uniform(0, 2 * math.pi)
        radius_deg = depot["catchment_radius_km"] / 111.0
        for s in range(stops_per_route):
            stop_seq += 1
            # Spiral outward from the depot so each route draws a plausible line.
            frac = (s + 1) / stops_per_route
            a = angle + frac * 2.5 + rng.uniform(-0.15, 0.15)
            dist = radius_deg * (0.15 + 0.8 * frac) * rng.uniform(0.85, 1.1)
            lat = depot["lat"] + dist * math.sin(a)
            lon = depot["lon"] + dist * math.cos(a) / math.cos(math.radians(depot["lat"]))
            window_start = start + timedelta(minutes=5 * s)
            window_end = window_start + timedelta(hours=2)
            roll = rng.random()
            if s < stops_per_route * 0.3:
                status = "delivered"
            elif roll < late_p:
                status = "late"
            elif roll < late_p + risk_p:
                status = "at_risk"
            else:
                status = "on_time"
            late_minutes = rng.randint(15, 120) if status == "late" else 0
            eta = (
                window_end + timedelta(minutes=late_minutes)
                if status == "late"
                else (window_end - timedelta(minutes=rng.randint(5, 60)))
            )
            actual = (
                window_start + timedelta(minutes=rng.randint(0, 100))
                if status == "delivered"
                else None
            )
            cause = None
            if status == "late":
                cause = rng.choice(["weather", "traffic"]) if troubled else rng.choice(CAUSES)
            statuses.append(status)
            stop_rows.append(
                dict(
                    stop_id=f"S-{today:%Y%m%d}-{stop_seq:05d}",
                    route_id=route_id,
                    route_date=today,
                    sequence=s + 1,
                    customer_name=rng.choice(CUSTOMERS),
                    address=f"{rng.randint(10, 9999)} Commerce St",
                    city=depot["city"],
                    state=depot["state"],
                    region=depot["region"],
                    lat=round(lat, 6),
                    lon=round(lon, 6),
                    promised_window_start=window_start,
                    promised_window_end=window_end,
                    eta_ts=eta,
                    actual_arrival_ts=actual,
                    status=status,
                    carrier_id=carrier_id,
                    depot_id=depot["depot_id"],
                    late_minutes=late_minutes,
                    late_reason_code=cause,
                )
            )
            path.append((round(lat, 6), round(lon, 6)))
        late = statuses.count("late")
        at_risk = statuses.count("at_risk")
        risk = derive_risk(late, at_risk, stops_per_route)
        reason = None
        if risk >= 0.5:
            reason = (
                "Weather and traffic delays on carrier route"
                if troubled
                else ("Capacity: stop density above plan")
            )
        elif risk >= 0.25:
            reason = "ETA drift on late-day stops"
        data.routes.append(
            dict(
                route_id=route_id,
                route_date=today,
                depot_id=depot["depot_id"],
                vehicle_id=vehicle["vehicle_id"],
                carrier_id=carrier_id,
                driver_name=DRIVERS[r % len(DRIVERS)],
                planned_start_ts=start,
                status="delayed" if risk >= 0.5 else ("in_progress" if r % 5 else "planned"),
                planned_stops=stops_per_route,
                risk_score=risk,
                risk_reason=reason,
            )
        )
        data.stops.extend(stop_rows)
        data.route_paths.extend(
            dict(route_id=route_id, seq=i, lat=p[0], lon=p[1]) for i, p in enumerate(path)
        )

    # Pre-aggregated 30-day on-time history, 0.1 degree cells (what the SQL returns).
    for depot in data.depots:
        for _ in range(40):
            lat = round(depot["lat"] + rng.uniform(-0.4, 0.4), 1)
            lon = round(depot["lon"] + rng.uniform(-0.5, 0.5), 1)
            deliveries = rng.randint(80, 400)
            base = 0.78 if depot["region"] == "Northeast" else 0.93
            on_time = int(deliveries * min(1.0, max(0.5, rng.gauss(base, 0.05))))
            data.history_cells.append(
                dict(
                    lat=lat,
                    lon=lon,
                    depot_id=depot["depot_id"],
                    region=depot["region"],
                    carrier_id=CARRIERS[rng.randrange(len(CARRIERS))][0],
                    deliveries=deliveries,
                    on_time=on_time,
                )
            )
    if hero:
        capacity = {v["vehicle_id"]: v["capacity_stops"] for v in data.vehicles}
        routes = [{**r, "capacity_stops": capacity.get(r["vehicle_id"])} for r in data.routes]
        routes, data.stops = apply_scenario(data.depots, routes, data.stops)
        # Capacity lives on the vehicle in the contract; carry the scenario's value back.
        by_vehicle = {r["vehicle_id"]: r["capacity_stops"] for r in routes}
        for v in data.vehicles:
            v["capacity_stops"] = by_vehicle.get(v["vehicle_id"], v["capacity_stops"])
        data.routes = [{k: v for k, v in r.items() if k != "capacity_stops"} for r in routes]
    return data
