"""Hub summaries and heuristic reassign suggestions (plain rules, no model).

Both work on the *effective* view: stops already carry their effective route
(latest `stop_reassignments.to_route_id`, else `stops.route_id`, see
`effective.apply_overrides`), so applied overrides count against the target
route's capacity and a moved stop is judged on the route it is on now.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

Row = dict[str, Any]

AT_RISK_ROUTE_SCORE = 0.5  # a route at or above this risk_score is "at risk"
ACTIONABLE = ("late", "at_risk")  # stops a suggestion may move
KM_PER_RISK_POINT = 10.0  # ranking: 0.1 lower target risk is worth 1 km of detour
CLOSED_ROUTE_STATES = ("completed",)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def hub_summaries(depots: list[Row], routes: list[Row], effective_stops: list[Row]) -> list[Row]:
    """One row per depot: route/stop counts and on-time share for the day.

    A stop counts toward the depot of the route it is effectively on.
    `on_time_pct` is the share of stops that are delivered or on time.
    """
    route_depot = {r["route_id"]: r["depot_id"] for r in routes}
    stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in routes:
        s = stats[r["depot_id"]]
        s["routes"] += 1
        if (r.get("risk_score") or 0) >= AT_RISK_ROUTE_SCORE:
            s["at_risk_routes"] += 1
    for stop in effective_stops:
        s = stats[route_depot.get(stop["route_id"], stop["depot_id"])]
        s["stops"] += 1
        s[stop["status"]] += 1
    out = []
    for d in depots:
        s = stats.get(d["depot_id"], {})
        stops = s.get("stops", 0)
        good = s.get("on_time", 0) + s.get("delivered", 0)
        out.append(
            {
                **d,
                "routes": s.get("routes", 0),
                "at_risk_routes": s.get("at_risk_routes", 0),
                "stops": stops,
                "late_stops": s.get("late", 0),
                "at_risk_stops": s.get("at_risk", 0),
                "on_time_pct": round(good / stops, 4) if stops else None,
            }
        )
    # Hubs that need attention first, then by name for a stable order.
    return sorted(out, key=lambda h: (-h["at_risk_routes"], -h["late_stops"], h["name"]))


def _spare(route: Row, load: int) -> int | None:
    cap = route.get("capacity_stops")
    return None if cap is None else int(cap) - load


def _reason(to_route_id: str, distance_km: float, src_risk: float, dst: Row, spare: int) -> str:
    slots = "slot" if spare == 1 else "slots"
    return (
        f"Move to {to_route_id}: {distance_km:.1f} km from its nearest stop, "
        f"risk {dst.get('risk_score') or 0:.2f} vs {src_risk:.2f}, {spare} spare {slots}"
    )


def suggest_reassigns(
    route_id: str,
    routes: list[Row],
    effective_stops: list[Row],
    *,
    per_stop: int = 2,
    max_stops: int = 25,
    max_distance_km: float = 30.0,
) -> list[Row]:
    """Suggested target routes for the late/at-risk stops on an at-risk route.

    Candidates: other open routes from the same depot with a lower risk_score and
    spare capacity (vehicle capacity_stops minus the stops effectively on it now).
    Ranked by `distance_km - KM_PER_RISK_POINT * risk_delta`, ties by route_id, so
    the output is deterministic. A candidate's slot is reserved once it is the top
    pick for a stop, so following every top suggestion never overfills a route.
    Returns [] when the route is not at risk or nothing qualifies.
    """
    by_id = {r["route_id"]: r for r in routes}
    source = by_id.get(route_id)
    if source is None:
        return []
    src_risk = source.get("risk_score") or 0.0
    if src_risk < AT_RISK_ROUTE_SCORE:
        return []

    on_route: dict[str, list[Row]] = defaultdict(list)
    for stop in effective_stops:
        on_route[stop["route_id"]].append(stop)

    spare: dict[str, int] = {}
    for r in routes:
        if (
            r["route_id"] == route_id
            or r["depot_id"] != source["depot_id"]
            or r.get("status") in CLOSED_ROUTE_STATES
            or (r.get("risk_score") or 0.0) >= src_risk
            or not on_route.get(r["route_id"])
        ):
            continue
        free = _spare(r, len(on_route[r["route_id"]]))
        if free is not None and free > 0:
            spare[r["route_id"]] = free

    movable = sorted(
        (s for s in on_route.get(route_id, []) if s["status"] in ACTIONABLE),
        key=lambda s: (s["status"] != "late", -(s.get("late_minutes") or 0), s["sequence"]),
    )[:max_stops]

    out: list[Row] = []
    for stop in movable:
        ranked = []
        for cand_id in spare:
            if spare[cand_id] <= 0:
                continue
            dist = min(
                haversine_km(stop["lat"], stop["lon"], o["lat"], o["lon"])
                for o in on_route[cand_id]
            )
            if dist > max_distance_km:
                continue
            delta = src_risk - (by_id[cand_id].get("risk_score") or 0.0)
            ranked.append((round(dist - KM_PER_RISK_POINT * delta, 4), cand_id, dist, delta))
        ranked.sort(key=lambda t: (t[0], t[1]))
        for rank, (score, cand_id, dist, delta) in enumerate(ranked[:per_stop], start=1):
            dst = by_id[cand_id]
            out.append(
                {
                    "stop_id": stop["stop_id"],
                    "stop_status": stop["status"],
                    "customer_name": stop.get("customer_name"),
                    "sequence": stop["sequence"],
                    "late_minutes": stop.get("late_minutes") or 0,
                    "from_route_id": route_id,
                    "from_risk_score": src_risk,
                    "to_route_id": cand_id,
                    "to_risk_score": dst.get("risk_score") or 0.0,
                    "risk_delta": round(delta, 4),
                    "distance_km": round(dist, 2),
                    "spare_slots": spare[cand_id],
                    "rank": rank,
                    "score": score,
                    "reason": _reason(cand_id, dist, src_risk, dst, spare[cand_id]),
                }
            )
        if ranked:
            spare[ranked[0][1]] -= 1
    return out
