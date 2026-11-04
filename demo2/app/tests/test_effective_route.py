"""Override rule: effective route = latest stop_reassignments.to_route_id, else stops.route_id."""

from datetime import UTC, datetime, timedelta

from dispatch_tower.services.effective import apply_overrides, cluster_stops, route_rollups

from .conftest import DISPATCHER, TODAY, open_stop, other_route


def _stop(stop_id="S1", route_id="R1", status="on_time"):
    return {"stop_id": stop_id, "route_id": route_id, "status": status, "lat": 1.0, "lon": 2.0}


def test_no_override_keeps_gold_route():
    [row] = apply_overrides([_stop()], {})
    assert row["route_id"] == "R1"
    assert row["original_route_id"] == "R1"
    assert row["reassigned"] is False


def test_latest_reassignment_wins(ctx):
    t0 = datetime(2026, 10, 26, 9, tzinfo=UTC)
    with ctx.store.transaction() as tx:
        tx.insert_reassignment("S1", "R1", "R2", "weather", None, "u")
        tx.insert_reassignment("S1", "R2", "R3", "capacity", None, "u")
    latest = ctx.store.latest_reassignments(["S1"])
    assert latest["S1"]["to_route_id"] == "R3"
    [row] = apply_overrides([_stop()], latest)
    assert row["route_id"] == "R3" and row["original_route_id"] == "R1" and row["reassigned"]
    # created_at decides, then id: an older timestamp inserted later must not win
    latest["S1"] = {**latest["S1"], "created_at": t0 - timedelta(days=1)}
    assert ctx.store.latest_reassignments(["S1"])["S1"]["to_route_id"] == "R3"


def test_moving_back_to_original_route_is_not_flagged():
    [row] = apply_overrides([_stop()], {"S1": {"to_route_id": "R1"}})
    assert row["route_id"] == "R1"
    assert row["reassigned"] is False


def test_api_applies_override_and_rollups(client, ctx):
    stop = open_stop(ctx)
    target = other_route(ctx, stop["route_id"])
    before = {r["route_id"]: r for r in client.get("/api/routes").json()}
    resp = client.post(
        f"/api/stops/{stop['stop_id']}/reassign",
        headers=DISPATCHER,
        json={"to_route_id": target, "reason_code": "vehicle_down", "note": "n"},
    )
    assert resp.status_code == 200, resp.text
    got = client.get(f"/api/stops/{stop['stop_id']}").json()
    assert got["stop"]["route_id"] == target
    assert got["stop"]["original_route_id"] == stop["route_id"]
    assert got["reassignments"][0]["from_route_id"] == stop["route_id"]
    after = {r["route_id"]: r for r in client.get("/api/routes").json()}
    assert after[target]["effective_stops"] == before[target]["effective_stops"] + 1
    assert after[stop["route_id"]]["effective_stops"] == (
        before[stop["route_id"]]["effective_stops"] - 1
    )
    listed = client.get("/api/stops", params={"route_id": target}).json()
    assert stop["stop_id"] in {s["stop_id"] for s in listed}


def test_reassign_validations(client, ctx):
    stop = open_stop(ctx)
    same = client.post(
        f"/api/stops/{stop['stop_id']}/reassign",
        headers=DISPATCHER,
        json={"to_route_id": stop["route_id"], "reason_code": "weather"},
    )
    assert same.status_code == 422
    bad_reason = client.post(
        f"/api/stops/{stop['stop_id']}/reassign",
        headers=DISPATCHER,
        json={"to_route_id": "R-x", "reason_code": "teleport"},
    )
    assert bad_reason.status_code == 422
    missing = client.post(
        f"/api/stops/{stop['stop_id']}/reassign",
        headers=DISPATCHER,
        json={"to_route_id": "R-does-not-exist", "reason_code": "weather"},
    )
    assert missing.status_code == 404
    delivered = next(s for s in ctx.reader.stops(TODAY) if s["status"] == "delivered")
    resp = client.post(
        f"/api/stops/{delivered['stop_id']}/reassign",
        headers=DISPATCHER,
        json={"to_route_id": other_route(ctx, delivered["route_id"]), "reason_code": "weather"},
    )
    assert resp.status_code == 422


def test_clusters_aggregate_and_report_worst_status():
    stops = [
        _stop("a", status="on_time"),
        _stop("b", status="late"),
        {**_stop("c", status="delivered"), "lat": 50.0, "lon": 50.0},
    ]
    cells = cluster_stops(stops, 1.0)
    assert sorted(c["count"] for c in cells) == [1, 2]
    big = next(c for c in cells if c["count"] == 2)
    assert big["worst_status"] == "late" and big["late"] == 1 and big["on_time"] == 1


def test_route_rollups_count_open_work():
    routes = [{"route_id": "R1", "risk_score": 0.2}, {"route_id": "R2", "risk_score": 0.9}]
    stops = [_stop("a", "R1", "late"), _stop("b", "R1", "at_risk"), _stop("c", "R2")]
    out = route_rollups(routes, stops, [{"route_id": "R1"}], [{"route_id": "R2"}])
    assert [r["route_id"] for r in out] == ["R2", "R1"]  # risk desc
    r1 = next(r for r in out if r["route_id"] == "R1")
    assert (r1["late_stops"], r1["at_risk_stops"], r1["open_exceptions"]) == (1, 1, 1)
