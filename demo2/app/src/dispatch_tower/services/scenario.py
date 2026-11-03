"""Demo2 hero scenario: a read-time overlay on the gold routes and stops.

The shared workshop data (docs/DATA_CONTRACT.md, also used by demo1) stays as it is.
This layer reshapes what demo2 shows so the 60-second story is unambiguous:

- Newark (hub with the worst SLA history) has exactly one red route, R-002, with 12
  late and 8 at-risk stops.
- R-010, same hub, has no late stops, low risk and spare capacity, so R-002 gets a
  handful of clean reassign suggestions. Newark's other routes are full.
- Boston is the one amber hub; every other hub is green.
- Route risk is derived from stop status (`effective.derive_risk`), so "at risk"
  always means late or at-risk stops exist.
- Every route fits its vehicle (capacity >= stops), no over-capacity-by-construction.

Routes are identified by depot city and the trailing route number (R-YYYYMMDD-NNN), so
the same rules work for the warehouse tables and the offline mock. `apply_scenario` is
a pure function and idempotent.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from .effective import derive_risk

Row = dict[str, Any]

HERO_CITY, HERO_NUM, TARGET_NUM = "Newark", 2, 10
AMBER_CITY, AMBER_NUM = "Boston", 1
HERO_LATE, HERO_AT_RISK = 12, 8
AMBER_LATE, AMBER_AT_RISK = 5, 3
CALM_MAX_LATE, CALM_MAX_AT_RISK = 1, 2  # every other route
SPARE_SLOTS = 6


def route_number(route_id: str) -> int:
    try:
        return int(route_id.rsplit("-", 1)[-1])
    except ValueError:
        return -1


def _targets(route: Row, city: str, existing_late: int, existing_at_risk: int) -> tuple[int, int]:
    num = route_number(route["route_id"])
    if city == HERO_CITY and num == HERO_NUM:
        return HERO_LATE, HERO_AT_RISK
    if city == HERO_CITY:
        return 0, 0  # the hero hub's other routes are clean: the problem is one route
    if city == AMBER_CITY and num == AMBER_NUM:
        return AMBER_LATE, AMBER_AT_RISK
    return min(existing_late, CALM_MAX_LATE), min(existing_at_risk, CALM_MAX_AT_RISK)


def _reset(stop: Row) -> None:
    stop["status"] = "on_time"
    stop["late_minutes"] = 0
    stop["late_reason_code"] = None
    end = stop.get("promised_window_end")
    if end is not None:
        stop["eta_ts"] = end - timedelta(minutes=15)


def _place(stops: list[Row], late: int, at_risk: int, reason: str) -> None:
    """Spread `late` and `at_risk` stops evenly over the stops still to be served."""
    pool = sorted((s for s in stops if s["status"] != "delivered"), key=lambda s: s["sequence"])
    items = [("late", j / late) for j in range(late)] + [
        ("at_risk", j / at_risk) for j in range(at_risk)
    ]
    items.sort(key=lambda it: (it[1], it[0] != "late"))
    slots = len(items)
    if not slots or len(pool) < slots:
        return
    for i, (status, _) in enumerate(items):
        stop = pool[int((i + 0.5) * len(pool) / slots)]
        end = stop.get("promised_window_end")
        stop["status"] = status
        if status == "late":
            minutes = 25 + (i * 13) % 60
            stop["late_minutes"] = minutes
            stop["late_reason_code"] = reason if i % 2 == 0 else "traffic"
            if end is not None:
                stop["eta_ts"] = end + timedelta(minutes=minutes)
        else:
            stop["late_reason_code"] = "traffic"
            if end is not None:
                stop["eta_ts"] = end - timedelta(minutes=2)


def apply_scenario(
    depots: list[Row], routes: list[Row], stops: list[Row]
) -> tuple[list[Row], list[Row]]:
    """Return (routes, stops) reshaped for the hero scenario; inputs are not modified."""
    city = {d["depot_id"]: d.get("city") for d in depots}
    out_stops = [dict(s) for s in stops]
    by_route: dict[str, list[Row]] = defaultdict(list)
    for s in out_stops:
        by_route[s["route_id"]].append(s)

    out_routes: list[Row] = []
    for r in routes:
        row = dict(r)
        rid = row["route_id"]
        depot_city = city.get(row["depot_id"]) or ""
        members = by_route.get(rid, [])
        n_late = sum(1 for s in members if s["status"] == "late")
        n_risk = sum(1 for s in members if s["status"] == "at_risk")
        late, at_risk = _targets(row, depot_city, n_late, n_risk)
        for s in members:
            if s["status"] in ("late", "at_risk"):
                _reset(s)
        _place(
            members,
            late,
            at_risk,
            "weather" if depot_city in (HERO_CITY, AMBER_CITY) else "capacity",
        )
        late = sum(1 for s in members if s["status"] == "late")
        at_risk = sum(1 for s in members if s["status"] == "at_risk")
        risk = derive_risk(late, at_risk, len(members))
        row["risk_score"] = risk
        hero = depot_city == HERO_CITY and route_number(rid) == HERO_NUM
        if hero:
            row["risk_reason"] = f"{late} late stops: weather and traffic around Newark"
            row["status"] = "delayed"
        else:
            row["risk_reason"] = (
                "ETA drift on late-day stops" if risk >= 0.2 else "normal operating conditions"
            )
            if row.get("status") == "delayed":
                row["status"] = "in_progress"
        # Newark's other routes are full, so R-010 is the only place to move stops to.
        full = depot_city == HERO_CITY and route_number(rid) != TARGET_NUM
        spare = 0 if full else SPARE_SLOTS
        row["capacity_stops"] = max(int(row.get("capacity_stops") or 0), len(members) + spare)
        if full:
            row["capacity_stops"] = len(members)
        out_routes.append(row)
    return out_routes, out_stops
