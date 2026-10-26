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
MAX_JITTER_KM = 1.5
EARTH_RADIUS_KM = 6371.0

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

# Hand-picked land neighborhood anchors (name, state, lat, lon). Stay inland of harbors/lakes.
DEPOT_ANCHORS: dict[str, list[tuple[str, str, float, float]]] = {
    "DEPOT_BOS": [
        ("Back Bay", "MA", 42.3503, -71.0810),
        ("South End", "MA", 42.3388, -71.0765),
        ("Roxbury", "MA", 42.3152, -71.0914),
        ("Jamaica Plain", "MA", 42.3097, -71.1151),
        ("Brookline", "MA", 42.3318, -71.1212),
        ("Allston", "MA", 42.3532, -71.1321),
        ("Cambridge", "MA", 42.3736, -71.1097),
        ("Somerville", "MA", 42.3876, -71.0995),
        ("Charlestown", "MA", 42.3782, -71.0602),
        ("Dorchester", "MA", 42.3016, -71.0676),
        ("Medford", "MA", 42.4184, -71.1062),
        ("Watertown", "MA", 42.3709, -71.1828),
        ("Malden", "MA", 42.4251, -71.0662),
        ("Newton", "MA", 42.3370, -71.2092),
        ("Quincy", "MA", 42.2529, -71.0023),
    ],
    "DEPOT_NYC": [
        ("Newark Downtown", "NJ", 40.7357, -74.1724),
        ("Ironbound", "NJ", 40.7240, -74.1550),
        ("Harrison", "NJ", 40.7465, -74.1560),
        ("Kearny", "NJ", 40.7684, -74.1454),
        ("Jersey City Heights", "NJ", 40.7465, -74.0530),
        ("Hoboken", "NJ", 40.7440, -74.0324),
        ("Union City", "NJ", 40.7795, -74.0238),
        ("East Orange", "NJ", 40.7673, -74.2049),
        ("Irvington", "NJ", 40.7323, -74.2349),
        ("Bloomfield", "NJ", 40.8068, -74.1854),
        ("Montclair", "NJ", 40.8259, -74.2090),
        ("Elizabeth", "NJ", 40.6639, -74.2107),
        ("Bayonne", "NJ", 40.6687, -74.1143),
        ("Belleville", "NJ", 40.7937, -74.1501),
        ("Maplewood", "NJ", 40.7312, -74.2735),
    ],
    "DEPOT_PHL": [
        ("Center City", "PA", 39.9526, -75.1652),
        ("University City", "PA", 39.9522, -75.1932),
        ("Fishtown", "PA", 39.9712, -75.1340),
        ("Northern Liberties", "PA", 39.9640, -75.1450),
        ("South Philadelphia", "PA", 39.9215, -75.1635),
        ("West Philadelphia", "PA", 39.9600, -75.2200),
        ("Manayunk", "PA", 40.0265, -75.2250),
        ("Germantown", "PA", 40.0370, -75.1760),
        ("Chestnut Hill", "PA", 40.0760, -75.2080),
        ("Upper Darby", "PA", 39.9607, -75.2710),
        ("Camden", "NJ", 39.9259, -75.1196),
        ("Cherry Hill", "NJ", 39.9348, -75.0307),
        ("Conshohocken", "PA", 40.0793, -75.3016),
        ("King of Prussia", "PA", 40.0890, -75.3860),
        ("Media", "PA", 39.9168, -75.3877),
    ],
    "DEPOT_ATL": [
        ("Downtown", "GA", 33.7490, -84.3880),
        ("Midtown", "GA", 33.7838, -84.3830),
        ("West End", "GA", 33.7380, -84.4150),
        ("East Atlanta", "GA", 33.7410, -84.3450),
        ("Decatur", "GA", 33.7748, -84.2963),
        ("Buckhead", "GA", 33.8486, -84.3733),
        ("Brookhaven", "GA", 33.8601, -84.3402),
        ("Sandy Springs", "GA", 33.9304, -84.3733),
        ("Vinings", "GA", 33.8648, -84.4647),
        ("Smyrna", "GA", 33.8839, -84.5144),
        ("Marietta", "GA", 33.9526, -84.5499),
        ("College Park", "GA", 33.6534, -84.4494),
        ("East Point", "GA", 33.6796, -84.4394),
        ("Hapeville", "GA", 33.6601, -84.4091),
        ("Chamblee", "GA", 33.8920, -84.2988),
    ],
    "DEPOT_CHI": [
        ("Loop", "IL", 41.8819, -87.6278),
        ("South Loop", "IL", 41.8610, -87.6270),
        ("Pilsen", "IL", 41.8560, -87.6560),
        ("Bridgeport", "IL", 41.8380, -87.6510),
        ("Bronzeville", "IL", 41.8230, -87.6170),
        ("Hyde Park", "IL", 41.7943, -87.5907),
        ("Garfield Park", "IL", 41.8806, -87.7150),
        ("Humboldt Park", "IL", 41.9020, -87.7200),
        ("Wicker Park", "IL", 41.9088, -87.6796),
        ("Logan Square", "IL", 41.9230, -87.7090),
        ("Lincoln Park", "IL", 41.9214, -87.6513),
        ("Cicero", "IL", 41.8456, -87.7539),
        ("Oak Park", "IL", 41.8850, -87.7845),
        ("Evanston", "IL", 42.0451, -87.6877),
        ("Rogers Park", "IL", 42.0100, -87.6700),
    ],
    "DEPOT_DAL": [
        ("Downtown", "TX", 32.7767, -96.7970),
        ("Deep Ellum", "TX", 32.7840, -96.7810),
        ("Uptown", "TX", 32.8007, -96.8000),
        ("Oak Cliff", "TX", 32.7350, -96.8250),
        ("Irving", "TX", 32.8140, -96.9489),
        ("Grand Prairie", "TX", 32.7459, -96.9978),
        ("Arlington", "TX", 32.7357, -97.1081),
        ("Farmers Branch", "TX", 32.9265, -96.8961),
        ("Carrollton", "TX", 32.9756, -96.8897),
        ("Addison", "TX", 32.9618, -96.8292),
        ("Richardson", "TX", 32.9483, -96.7299),
        ("Plano", "TX", 33.0198, -96.6989),
        ("Garland", "TX", 32.9126, -96.6389),
        ("Mesquite", "TX", 32.7668, -96.5992),
        ("Duncanville", "TX", 32.6518, -96.9083),
    ],
    "DEPOT_DEN": [
        ("Downtown", "CO", 39.7392, -104.9903),
        ("Capitol Hill", "CO", 39.7348, -104.9790),
        ("Cherry Creek", "CO", 39.7170, -104.9500),
        ("Washington Park", "CO", 39.7000, -104.9650),
        ("RiNo", "CO", 39.7680, -104.9795),
        ("Highlands", "CO", 39.7620, -105.0110),
        ("Lakewood", "CO", 39.7047, -105.0814),
        ("Wheat Ridge", "CO", 39.7661, -105.0772),
        ("Arvada", "CO", 39.8028, -105.0875),
        ("Commerce City", "CO", 39.8083, -104.9339),
        ("Aurora", "CO", 39.7294, -104.8319),
        ("Englewood", "CO", 39.6478, -104.9878),
        ("Littleton", "CO", 39.6133, -105.0166),
        ("Centennial", "CO", 39.5807, -104.8772),
        ("Thornton", "CO", 39.8680, -104.9719),
    ],
    "DEPOT_LAX": [
        ("Downtown", "CA", 34.0522, -118.2437),
        ("Koreatown", "CA", 34.0610, -118.3000),
        ("Hollywood", "CA", 34.0928, -118.3287),
        ("East LA", "CA", 34.0239, -118.1720),
        ("Alhambra", "CA", 34.0953, -118.1270),
        ("Pasadena", "CA", 34.1478, -118.1445),
        ("Glendale", "CA", 34.1425, -118.2551),
        ("Burbank", "CA", 34.1808, -118.3089),
        ("Culver City", "CA", 34.0211, -118.3965),
        ("Inglewood", "CA", 33.9617, -118.3531),
        ("Compton", "CA", 33.8958, -118.2201),
        ("Downey", "CA", 33.9401, -118.1332),
        ("Torrance", "CA", 33.8358, -118.3406),
        ("Long Beach", "CA", 33.7701, -118.1937),
        ("Santa Monica", "CA", 34.0195, -118.4912),
    ],
}

# Coarse land polygons (lat, lon) that keep stops off major water bodies for each metro.
LAND_POLYGONS: dict[str, list[tuple[float, float]]] = {
    "DEPOT_BOS": [
        (42.20, -71.28),
        (42.20, -70.98),
        (42.30, -70.98),
        (42.38, -71.00),
        (42.45, -71.04),
        (42.46, -71.22),
        (42.36, -71.28),
    ],
    "DEPOT_NYC": [
        (40.62, -74.32),
        (40.62, -74.02),
        (40.72, -74.01),
        (40.84, -74.02),
        (40.86, -74.30),
        (40.72, -74.32),
    ],
    "DEPOT_PHL": [
        (39.86, -75.42),
        (39.86, -75.00),
        (40.12, -75.00),
        (40.12, -75.42),
    ],
    "DEPOT_ATL": [
        (33.60, -84.60),
        (33.60, -84.25),
        (34.00, -84.25),
        (34.00, -84.60),
    ],
    "DEPOT_CHI": [
        # Western cut keeps everything west of the Lake Michigan shoreline.
        (41.70, -87.92),
        (41.70, -87.55),
        (41.90, -87.53),
        (42.08, -87.55),
        (42.10, -87.78),
        (41.95, -87.92),
    ],
    "DEPOT_DAL": [
        (32.60, -97.18),
        (32.60, -96.55),
        (33.08, -96.55),
        (33.08, -97.18),
    ],
    "DEPOT_DEN": [
        (39.52, -105.15),
        (39.52, -104.78),
        (39.92, -104.78),
        (39.92, -105.15),
    ],
    "DEPOT_LAX": [
        # Stay east of the open Pacific; Santa Monica / coastal anchors remain inland of this cut.
        (33.72, -118.52),
        (33.72, -118.08),
        (34.22, -118.08),
        (34.22, -118.52),
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


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_rad(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return math.atan2(y, x)


def point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-cast point-in-polygon treating lon as x and lat as y."""
    inside = False
    j = len(polygon) - 1
    for i, (lat_i, lon_i) in enumerate(polygon):
        lat_j, lon_j = polygon[j]
        intersects = ((lat_i > lat) != (lat_j > lat)) and (
            lon < (lon_j - lon_i) * (lat - lat_i) / (lat_j - lat_i + 0.0) + lon_i
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def on_land(depot_id: str, lat: float, lon: float) -> bool:
    return point_in_polygon(lat, lon, LAND_POLYGONS[depot_id])


def within_catchment(depot: dict[str, Any], lat: float, lon: float) -> bool:
    return haversine_km(depot["lat"], depot["lon"], lat, lon) <= depot["catchment_radius_km"]


def offset_point(lat: float, lon: float, east_km: float, north_km: float) -> tuple[float, float]:
    d_lat = north_km / EARTH_RADIUS_KM * (180 / math.pi)
    d_lon = east_km / (EARTH_RADIUS_KM * math.cos(math.radians(lat))) * (180 / math.pi)
    return lat + d_lat, lon + d_lon


def jitter_on_land(
    rng: random.Random,
    depot: dict[str, Any],
    city: str,
    state: str,
    anchor_lat: float,
    anchor_lon: float,
) -> tuple[str, str, float, float]:
    for _ in range(24):
        radius = rng.uniform(0.0, MAX_JITTER_KM)
        angle = rng.uniform(0.0, 2 * math.pi)
        lat, lon = offset_point(anchor_lat, anchor_lon, radius * math.cos(angle), radius * math.sin(angle))
        lat, lon = round(lat, 6), round(lon, 6)
        if on_land(depot["depot_id"], lat, lon) and within_catchment(depot, lat, lon):
            return city, state, lat, lon
    # Anchors are hand-picked on land inside catchment; use them if jitter lands off-mask.
    return city, state, round(anchor_lat, 6), round(anchor_lon, 6)


def assign_anchor_groups(
    depot: dict[str, Any],
    anchors: list[tuple[str, str, float, float]],
    route_count: int,
) -> list[list[tuple[str, str, float, float]]]:
    ordered = sorted(
        anchors,
        key=lambda anchor: bearing_rad(depot["lat"], depot["lon"], anchor[2], anchor[3]),
    )
    groups: list[list[tuple[str, str, float, float]]] = []
    for route_index in range(route_count):
        start = route_index * len(ordered) // route_count
        end = (route_index + 1) * len(ordered) // route_count
        slice_anchors = ordered[start:end] or [ordered[route_index % len(ordered)]]
        seed = slice_anchors[len(slice_anchors) // 2]
        # Keep each route on 1-3 anchors near the sector seed (~8-10 km neighborhood).
        ranked = sorted(
            ordered,
            key=lambda anchor: haversine_km(seed[2], seed[3], anchor[2], anchor[3]),
        )
        nearby = [
            anchor
            for anchor in ranked
            if haversine_km(seed[2], seed[3], anchor[2], anchor[3]) <= 8.0
        ]
        group = (nearby or ranked)[:3]
        groups.append(group)
    return groups


def nearest_neighbor_order(
    start_lat: float, start_lon: float, points: list[tuple[float, float]]
) -> list[int]:
    remaining = list(range(len(points)))
    order: list[int] = []
    cur_lat, cur_lon = start_lat, start_lon
    while remaining:
        best = min(
            remaining,
            key=lambda idx: haversine_km(cur_lat, cur_lon, points[idx][0], points[idx][1]),
        )
        order.append(best)
        remaining.remove(best)
        cur_lat, cur_lon = points[best]
    return order


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
        risk_reason = (
            "weather and traffic cluster affecting Northeast SLA"
            if depot["region"] == "Northeast" and high_risk
            else "normal operating conditions"
        )
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

    routes_by_depot: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for route in routes:
        routes_by_depot[route["depot_id"]].append(route)
    anchor_groups_by_depot = {
        depot_id: assign_anchor_groups(depot_lookup[depot_id], DEPOT_ANCHORS[depot_id], len(depot_routes))
        for depot_id, depot_routes in routes_by_depot.items()
    }
    group_cursor: dict[str, int] = defaultdict(int)

    stops: list[dict[str, Any]] = []
    route_paths: list[dict[str, Any]] = []

    for route_index, route in enumerate(routes):
        depot = depot_lookup[route["depot_id"]]
        route_size = base_per_route + (1 if route_index < extra else 0)
        route["planned_stops"] = route_size
        group_index = group_cursor[route["depot_id"]]
        group_cursor[route["depot_id"]] += 1
        anchors = anchor_groups_by_depot[route["depot_id"]][group_index]

        candidates: list[tuple[str, str, float, float]] = []
        for seq in range(1, route_size + 1):
            city, state, anchor_lat, anchor_lon = anchors[(seq - 1) % len(anchors)]
            candidates.append(jitter_on_land(rng, depot, city, state, anchor_lat, anchor_lon))

        order = nearest_neighbor_order(
            depot["lat"],
            depot["lon"],
            [(lat, lon) for _, _, lat, lon in candidates],
        )
        route_paths.append(
            {"route_id": route["route_id"], "seq": 0, "lat": depot["lat"], "lon": depot["lon"]}
        )
        start_dt = datetime.fromisoformat(route["planned_start_ts"])
        for sequence, candidate_index in enumerate(order, start=1):
            city, state, lat, lon = candidates[candidate_index]
            promised_start = start_dt + timedelta(minutes=8 * sequence)
            promised_end = promised_start + timedelta(minutes=45)
            status, late_minutes, reason = stop_status(route, sequence, route_size)
            if route["status"] == "planned":
                status, late_minutes, reason = "on_time", 0, None
            elif status == "on_time" and sequence <= route_size * 0.35:
                status = "delivered"
            eta = promised_end + timedelta(minutes=late_minutes if status == "late" else -8)
            actual = eta if status == "delivered" else None
            carrier_id = vehicle_lookup[route["vehicle_id"]]["carrier_id"]
            stops.append(
                {
                    "stop_id": f"S-{today.strftime('%Y%m%d')}-{route_index + 1:03d}-{sequence:03d}",
                    "route_id": route["route_id"],
                    "route_date": today.isoformat(),
                    "sequence": sequence,
                    "customer_name": f"Customer {route_index + 1:03d}-{sequence:03d}",
                    "address": f"{100 + sequence} {city} Distribution Way",
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
            route_paths.append(
                {
                    "route_id": route["route_id"],
                    "seq": sequence,
                    "lat": lat,
                    "lon": lon,
                }
            )
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
