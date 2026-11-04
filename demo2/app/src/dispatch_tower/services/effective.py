"""Read-time view of the gold data with Lakebase decisions applied.

Override rule (docs/DATA_CONTRACT.md): a stop's effective route is the latest
`stop_reassignments.to_route_id` for that stop, else `stops.route_id`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

Row = dict[str, Any]

STATUS_SEVERITY = {"late": 3, "at_risk": 2, "on_time": 1, "delivered": 0}

# A route is "at risk" (score >= 0.5, see recommend.AT_RISK_ROUTE_SCORE) once its weighted
# late share reaches half of this tolerance: a late stop counts 1, an at-risk stop 0.5.
RISK_TOLERANCE = 0.25


def derive_risk(late: int, at_risk: int, total: int) -> float:
    """Route risk 0-1 from its stop statuses, so a route with no late or at-risk stops is
    never flagged (late/at_risk both 0 -> 0.0)."""
    if total <= 0:
        return 0.0
    return round(min(0.99, (late + 0.5 * at_risk) / (RISK_TOLERANCE * total)), 3)


def apply_overrides(stops: list[Row], latest: dict[str, Row]) -> list[Row]:
    out = []
    for stop in stops:
        row = dict(stop)
        row["original_route_id"] = stop["route_id"]
        override = latest.get(stop["stop_id"])
        row["route_id"] = override["to_route_id"] if override else stop["route_id"]
        row["reassigned"] = override is not None and row["route_id"] != stop["route_id"]
        out.append(row)
    return out


def filter_rows(
    rows: list[Row],
    *,
    depot_id: str | None = None,
    carrier_id: str | None = None,
    region: str | None = None,
    route_id: str | None = None,
    status: str | None = None,
) -> list[Row]:
    return [
        r
        for r in rows
        if (depot_id is None or r.get("depot_id") == depot_id)
        and (carrier_id is None or r.get("carrier_id") == carrier_id)
        and (region is None or r.get("region") == region)
        and (route_id is None or r.get("route_id") == route_id)
        and (status is None or r.get("status") == status)
    ]


def apply_route_state(routes: list[Row], states: list[Row]) -> list[Row]:
    by_id = {s["route_id"]: s for s in states}
    out = []
    for route in routes:
        row = dict(route)
        state = by_id.get(route["route_id"])
        row["state_updated_by"] = state["updated_by"] if state else None
        row["state_updated_at"] = state["updated_at"] if state else None
        if state:
            row["status"] = state["state"]
        out.append(row)
    return out


def route_rollups(
    routes: list[Row],
    effective_stops: list[Row],
    open_exceptions: list[Row],
    pending_approvals: list[Row],
) -> list[Row]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for stop in effective_stops:
        c = counts[stop["route_id"]]
        c["total"] += 1
        c[stop["status"]] += 1
    exc = defaultdict(int)
    for e in open_exceptions:
        exc[e["route_id"]] += 1
    appr = defaultdict(int)
    for a in pending_approvals:
        appr[a["route_id"]] += 1
    out = []
    for route in routes:
        c = counts.get(route["route_id"], {})
        out.append(
            {
                **route,
                "effective_stops": c.get("total", 0),
                "late_stops": c.get("late", 0),
                "at_risk_stops": c.get("at_risk", 0),
                "open_exceptions": exc.get(route["route_id"], 0),
                "pending_approvals": appr.get(route["route_id"], 0),
            }
        )
    return sorted(out, key=lambda r: (-(r.get("risk_score") or 0), r["route_id"]))


def cluster_stops(stops: list[Row], cell_deg: float) -> list[Row]:
    """Grid-aggregate stops so the map never receives more points than it needs."""
    if cell_deg <= 0:
        raise ValueError("cell_deg must be positive")
    cells: dict[tuple[int, int], Row] = {}
    for stop in stops:
        key = (math.floor(stop["lat"] / cell_deg), math.floor(stop["lon"] / cell_deg))
        cell = cells.setdefault(
            key,
            {
                "lat": 0.0,
                "lon": 0.0,
                "count": 0,
                "late": 0,
                "at_risk": 0,
                "on_time": 0,
                "delivered": 0,
            },
        )
        cell["lat"] += stop["lat"]
        cell["lon"] += stop["lon"]
        cell["count"] += 1
        cell[stop["status"]] += 1
    out = []
    for cell in cells.values():
        n = cell["count"]
        worst = max(
            ("late", "at_risk", "on_time", "delivered"),
            key=lambda s: (cell[s] > 0, STATUS_SEVERITY[s]),
        )
        out.append(
            {
                **cell,
                "lat": round(cell["lat"] / n, 5),
                "lon": round(cell["lon"] / n, 5),
                "worst_status": worst,
            }
        )
    return sorted(out, key=lambda c: -c["count"])


def build_paths(points: list[Row], routes: list[Row]) -> list[Row]:
    by_route: dict[str, list[Row]] = defaultdict(list)
    for p in points:
        by_route[p["route_id"]].append(p)
    meta = {r["route_id"]: r for r in routes}
    out = []
    for route_id, pts in by_route.items():
        if route_id not in meta:
            continue
        pts.sort(key=lambda p: p["seq"])
        out.append(
            {
                "route_id": route_id,
                "depot_id": meta[route_id]["depot_id"],
                "risk_score": meta[route_id].get("risk_score") or 0.0,
                "path": [(p["lon"], p["lat"]) for p in pts],  # deck.gl order: [lon, lat]
            }
        )
    return out


def heat_cells(cells: list[Row], *, depot_id=None, carrier_id=None, region=None) -> list[Row]:
    merged: dict[tuple[float, float], Row] = {}
    for c in filter_rows(cells, depot_id=depot_id, carrier_id=carrier_id, region=region):
        key = (c["lat"], c["lon"])
        m = merged.setdefault(
            key, {"lat": c["lat"], "lon": c["lon"], "deliveries": 0, "on_time": 0}
        )
        m["deliveries"] += int(c["deliveries"] or 0)
        m["on_time"] += int(c["on_time"] or 0)
    return [
        {**m, "on_time_pct": round(m["on_time"] / m["deliveries"], 4) if m["deliveries"] else 0.0}
        for m in merged.values()
    ]
