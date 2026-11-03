"""Reassign suggestions (capacity, risk, same depot, override-aware, ranking) and hub summaries."""

from dispatch_tower.services.effective import apply_overrides
from dispatch_tower.services.recommend import (
    AT_RISK_ROUTE_SCORE,
    haversine_km,
    hub_summaries,
    suggest_reassigns,
)

from .conftest import DISPATCHER, MANAGER, TODAY


def _route(route_id, risk, depot="D1", cap=10, status="in_progress"):
    return {
        "route_id": route_id,
        "depot_id": depot,
        "risk_score": risk,
        "capacity_stops": cap,
        "status": status,
    }


def _stop(stop_id, route_id, lat, lon, status="on_time", seq=1, late=0, depot="D1"):
    return {
        "stop_id": stop_id,
        "route_id": route_id,
        "depot_id": depot,
        "lat": lat,
        "lon": lon,
        "status": status,
        "sequence": seq,
        "late_minutes": late,
        "customer_name": f"cust {stop_id}",
    }


def _scene():
    """R1 is at risk with one late stop at (40.0, -74.0); R2 is close, R3 is farther."""
    routes = [_route("R1", 0.8), _route("R2", 0.3, cap=5), _route("R3", 0.1, cap=5)]
    stops = [
        _stop("S1", "R1", 40.0, -74.0, status="late", late=45),
        _stop("S2", "R1", 40.01, -74.0, status="delivered", seq=2),
        _stop("A1", "R2", 40.01, -74.0),  # ~1.1 km from S1
        _stop("B1", "R3", 40.05, -74.0),  # ~5.6 km from S1
    ]
    return routes, stops


def test_ranks_by_distance_and_risk_delta():
    routes, stops = _scene()
    out = suggest_reassigns("R1", routes, stops)
    # R2: 1.1 km - 10*0.5 = -3.9 ; R3: 5.6 km - 10*0.7 = -1.4 -> R2 first
    assert [(s["stop_id"], s["to_route_id"], s["rank"]) for s in out] == [
        ("S1", "R2", 1),
        ("S1", "R3", 2),
    ]
    best = out[0]
    assert best["spare_slots"] == 4 and best["distance_km"] == round(
        haversine_km(40.0, -74.0, 40.01, -74.0), 2
    )
    assert best["reason"] == (
        "Move to R2: 1.1 km from its nearest stop, risk 0.30 vs 0.80, 4 spare slots"
    )


def test_only_late_and_at_risk_stops_get_suggestions():
    routes, stops = _scene()
    assert {s["stop_id"] for s in suggest_reassigns("R1", routes, stops)} == {"S1"}


def test_deterministic_ranking_and_order():
    # equal score candidates tie-break on route_id, regardless of input order
    routes = [_route("R1", 0.8), _route("RB", 0.3), _route("RA", 0.3)]
    stops = [
        _stop("S1", "R1", 40.0, -74.0, status="at_risk", seq=3),
        _stop("S2", "R1", 40.0, -74.0, status="late", late=10, seq=5),
        _stop("S3", "R1", 40.0, -74.0, status="late", late=60, seq=9),
        _stop("A1", "RA", 40.01, -74.0),
        _stop("B1", "RB", 40.01, -74.0),
    ]
    first = suggest_reassigns("R1", routes, stops)
    again = suggest_reassigns("R1", list(reversed(routes)), list(reversed(stops)))
    assert first == again
    # late before at_risk, most late minutes first
    assert [s["stop_id"] for s in first if s["rank"] == 1] == ["S3", "S2", "S1"]
    assert [s["to_route_id"] for s in first[:2]] == ["RA", "RB"]


def test_requires_lower_risk_same_depot_and_open_route():
    routes = [
        _route("R1", 0.8),
        _route("HIGHER", 0.9),
        _route("EQUAL", 0.8),
        _route("OTHER_DEPOT", 0.1, depot="D2"),
        _route("DONE", 0.1, status="completed"),
    ]
    stops = [
        _stop("S1", "R1", 40.0, -74.0, status="late"),
        _stop("H", "HIGHER", 40.0, -74.0),
        _stop("E", "EQUAL", 40.0, -74.0),
        _stop("O", "OTHER_DEPOT", 40.0, -74.0, depot="D2"),
        _stop("C", "DONE", 40.0, -74.0),
    ]
    assert suggest_reassigns("R1", routes, stops) == []


def test_capacity_full_or_unknown_is_skipped():
    routes = [_route("R1", 0.8), _route("FULL", 0.1, cap=1), _route("NOCAP", 0.1, cap=None)]
    stops = [
        _stop("S1", "R1", 40.0, -74.0, status="late"),
        _stop("F1", "FULL", 40.0, -74.0),
        _stop("N1", "NOCAP", 40.0, -74.0),
    ]
    assert suggest_reassigns("R1", routes, stops) == []


def test_top_pick_reserves_a_slot():
    routes = [_route("R1", 0.8), _route("R2", 0.1, cap=2), _route("R3", 0.3, cap=5)]
    stops = [
        _stop("S1", "R1", 40.0, -74.0, status="late", late=30),
        _stop("S2", "R1", 40.0, -74.0, status="late", late=20, seq=2),
        _stop("A1", "R2", 40.0, -74.0),
        _stop("B1", "R3", 40.0, -74.0),
    ]
    out = suggest_reassigns("R1", routes, stops)
    top = {s["stop_id"]: s["to_route_id"] for s in out if s["rank"] == 1}
    # R2 had one spare slot: S1 takes it, S2 falls back to R3
    assert top == {"S1": "R2", "S2": "R3"}
    assert [s["to_route_id"] for s in out if s["stop_id"] == "S2"] == ["R3"]


def test_override_aware_counts_and_source():
    routes = [_route("R1", 0.8), _route("R2", 0.1, cap=2)]
    gold = [
        _stop("S1", "R1", 40.0, -74.0, status="late"),
        _stop("S2", "R1", 40.0, -74.0, status="late", seq=2),
        _stop("A1", "R2", 40.0, -74.0),
    ]
    assert len([s for s in suggest_reassigns("R1", routes, gold) if s["rank"] == 1]) == 1
    # S2 already moved to R2 by an applied override: R2 is now full and S2 is no
    # longer a stop on R1, so nothing is suggested.
    effective = apply_overrides(gold, {"S2": {"to_route_id": "R2"}})
    assert suggest_reassigns("R1", routes, effective) == []
    # S1 moved onto R2 instead: R1 has a late stop left (S2) but R2 is full
    effective = apply_overrides(gold, {"S1": {"to_route_id": "R2"}})
    assert suggest_reassigns("R1", routes, effective) == []


def test_no_candidate_cases():
    routes, stops = _scene()
    assert suggest_reassigns("NOPE", routes, stops) == []
    low = [_route("R1", AT_RISK_ROUTE_SCORE - 0.01)] + routes[1:]
    assert suggest_reassigns("R1", low, stops) == []
    assert suggest_reassigns("R1", routes, stops, max_distance_km=0.5) == []


def test_hub_summaries_counts_effective_stops():
    depots = [
        {"depot_id": "D1", "name": "Alpha"},
        {"depot_id": "D2", "name": "Beta"},
        {"depot_id": "D3", "name": "Empty"},
    ]
    routes = [_route("R1", 0.8), _route("R2", 0.2), _route("R3", 0.1, depot="D2")]
    stops = [
        _stop("S1", "R1", 0, 0, status="late"),
        _stop("S2", "R1", 0, 0, status="at_risk"),
        _stop("S3", "R2", 0, 0, status="delivered"),
        _stop("S4", "R3", 0, 0, status="on_time", depot="D2"),
        # moved from a D1 route onto a D2 route: counts for D2
        _stop("S5", "R3", 0, 0, status="on_time", depot="D1"),
    ]
    hubs = {h["depot_id"]: h for h in hub_summaries(depots, routes, stops)}
    assert hubs["D1"] == {
        **depots[0],
        "routes": 2,
        "at_risk_routes": 1,
        "stops": 3,
        "late_stops": 1,
        "at_risk_stops": 1,
        "on_time_pct": round(1 / 3, 4),
        "health": "red",
    }
    assert hubs["D2"]["stops"] == 2 and hubs["D2"]["on_time_pct"] == 1.0
    assert hubs["D3"]["routes"] == 0 and hubs["D3"]["on_time_pct"] is None
    # attention first
    assert [h["depot_id"] for h in hub_summaries(depots, routes, stops)][0] == "D1"


# --- API ---------------------------------------------------------------------


def test_hubs_endpoint(client, ctx):
    hubs = client.get("/api/hubs").json()
    assert len(hubs) == 8
    routes = client.get("/api/routes").json()
    assert sum(h["routes"] for h in hubs) == len(routes)
    assert sum(h["stops"] for h in hubs) == len(ctx.reader.stops(TODAY))
    first = hubs[0]
    assert {"name", "lat", "lon", "at_risk_routes", "late_stops", "on_time_pct"} <= set(first)
    assert client.get("/api/hubs", params={"day": "not-a-date"}).status_code == 422


def test_routes_expose_capacity(client):
    assert all(r["capacity_stops"] for r in client.get("/api/routes").json())
    assert client.get("/api/filters").json()["max_map_points"] > 0


def _two_route_hub(ctx):
    """conftest builds one route per depot; put the two highest-risk routes on one depot."""
    routes = ctx.reader.routes(TODAY)
    hi, lo = routes[0], routes[-1]
    lo["depot_id"] = hi["depot_id"]
    hi["risk_score"] = 0.9
    anchor = next(s for s in ctx.reader.stops(TODAY) if s["route_id"] == hi["route_id"])
    for i, s in enumerate(x for x in ctx.reader.stops(TODAY) if x["route_id"] == lo["route_id"]):
        s.update(lat=anchor["lat"] + 0.001 * i, lon=anchor["lon"], depot_id=hi["depot_id"])
    return hi, lo


def test_suggestions_endpoint_and_apply(client, ctx):
    hi, lo = _two_route_hub(ctx)
    got = client.get(f"/api/routes/{hi['route_id']}/suggestions").json()
    assert got["at_risk"] is True and got["at_risk_threshold"] == AT_RISK_ROUTE_SCORE
    sugg = got["suggestions"]
    assert sugg and {s["to_route_id"] for s in sugg} == {lo["route_id"]}
    first = sugg[0]
    # Apply goes through the normal reassign path: audit row, reason sla_risk, note
    resp = client.post(
        f"/api/stops/{first['stop_id']}/reassign",
        headers=DISPATCHER,
        json={
            "to_route_id": first["to_route_id"],
            "reason_code": "sla_risk",
            "note": first["reason"],
        },
    )
    assert resp.status_code == 200, resp.text
    audit = client.get("/api/audit", headers=MANAGER, params={"entity_id": first["stop_id"]}).json()
    assert audit[0]["reason"] == "sla_risk" and audit[0]["payload"]["note"] == first["reason"]
    after = client.get(f"/api/routes/{hi['route_id']}/suggestions").json()["suggestions"]
    assert first["stop_id"] not in {s["stop_id"] for s in after}
    assert all(s["spare_slots"] < first["spare_slots"] for s in after if s["rank"] == 1)
    assert client.get("/api/routes/R-nope/suggestions").status_code == 404


def test_suggestions_for_low_risk_route_are_empty(client, ctx):
    low = ctx.reader.routes(TODAY)[-1]
    got = client.get(f"/api/routes/{low['route_id']}/suggestions").json()
    assert got["at_risk"] is False and got["suggestions"] == []
