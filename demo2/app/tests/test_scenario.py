"""Demo2 hero scenario: Newark R-002 is the only red route, R-010 can absorb its late stops."""

import pytest
from fastapi.testclient import TestClient

from dispatch_tower.app import create_app
from dispatch_tower.mock.fixtures import build
from dispatch_tower.services import recommend
from dispatch_tower.services.effective import apply_overrides, derive_risk
from dispatch_tower.services.scenario import apply_scenario
from dispatch_tower.services.warehouse import MockReader, ScenarioReader

from .conftest import DISPATCHER, MANAGER, TODAY, make_ctx

HERO, TARGET = "R-20261026-002", "R-20261026-010"


@pytest.fixture
def hero_ctx():
    return make_ctx(hero=True)


@pytest.fixture
def hero(hero_ctx) -> TestClient:
    return TestClient(create_app(hero_ctx, serve_static=False))


def _by_route(client):
    return {r["route_id"]: r for r in client.get("/api/routes").json()}


def test_only_r002_is_red(hero):
    routes = _by_route(hero)
    red = [r for r in routes.values() if r["risk_score"] >= recommend.AT_RISK_ROUTE_SCORE]
    assert [r["route_id"] for r in red] == [HERO]
    assert routes[HERO]["depot_id"] == "DEPOT_NYC"
    assert routes[HERO]["late_stops"] == 12 and routes[HERO]["at_risk_stops"] == 8
    assert routes[TARGET]["depot_id"] == "DEPOT_NYC" and routes[TARGET]["risk_score"] <= 0.1
    assert routes[TARGET]["late_stops"] == 0


def test_hub_colors_one_red_one_amber_rest_green(hero):
    hubs = {h["depot_id"]: h["health"] for h in hero.get("/api/hubs").json()}
    assert hubs["DEPOT_NYC"] == "red"
    assert [k for k, v in hubs.items() if v == "amber"] == ["DEPOT_BOS"]
    assert sorted(v for v in hubs.values()) == ["amber", "green"] * 0 + sorted(hubs.values())
    assert sum(v == "green" for v in hubs.values()) == 6
    newark = next(h for h in hero.get("/api/hubs").json() if h["depot_id"] == "DEPOT_NYC")
    assert newark["on_time_pct"] < newark["sla_target_pct"]


def test_r002_gets_three_to_five_clean_suggestions(hero):
    got = hero.get(f"/api/routes/{HERO}/suggestions").json()
    sugg = got["suggestions"]
    assert 3 <= len(sugg) <= 5
    assert {s["to_route_id"] for s in sugg} == {TARGET}
    assert len({s["stop_id"] for s in sugg}) == len(sugg)  # one option per stop, no wall
    assert all(s["stop_status"] == "late" for s in sugg)
    assert all(s["to_risk_score"] < s["from_risk_score"] for s in sugg)
    # no other route has anything to move
    others = [r for r in _by_route(hero) if r != HERO]
    assert all(hero.get(f"/api/routes/{r}/suggestions").json()["suggestions"] == [] for r in others)


def test_no_route_exceeds_its_vehicle(hero):
    for r in _by_route(hero).values():
        assert r["effective_stops"] <= r["capacity_stops"], r["route_id"]


def test_risk_is_derived_from_stop_status(hero):
    routes = _by_route(hero)
    for r in routes.values():
        assert r["risk_score"] == derive_risk(
            r["late_stops"], r["at_risk_stops"], r["effective_stops"]
        )
        if r["risk_score"] >= recommend.AT_RISK_ROUTE_SCORE:
            assert r["late_stops"] + r["at_risk_stops"] > 0
    assert derive_risk(0, 0, 100) == 0.0
    assert derive_risk(0, 0, 0) == 0.0
    assert derive_risk(12, 8, 100) == 0.64
    assert derive_risk(100, 0, 100) == 0.99  # capped
    assert derive_risk(10, 0, 100) < derive_risk(10, 5, 100) < derive_risk(15, 5, 100)


def test_scenario_is_idempotent_and_matches_the_warehouse_path():
    raw = build(TODAY)
    veh = {v["vehicle_id"]: v["capacity_stops"] for v in raw.vehicles}
    routes = [{**r, "capacity_stops": veh[r["vehicle_id"]]} for r in raw.routes]
    once = apply_scenario(raw.depots, routes, raw.stops)
    assert apply_scenario(raw.depots, *once) == once
    # ScenarioReader over untouched data (the deployed path) == build(hero=True) (offline path)
    via_reader = ScenarioReader(MockReader(raw))
    offline = MockReader(build(TODAY, hero=True))
    assert via_reader.stops(TODAY) == offline.stops(TODAY)
    assert {r["route_id"]: r["risk_score"] for r in via_reader.routes(TODAY)} == {
        r["route_id"]: r["risk_score"] for r in offline.routes(TODAY)
    }


def test_inputs_are_not_mutated():
    raw = build(TODAY)
    before = [dict(s) for s in raw.stops]
    apply_scenario(raw.depots, raw.routes, raw.stops)
    assert raw.stops == before


# --- impact projection -------------------------------------------------------


def test_impact_before_any_action_is_flat(hero):
    got = hero.get(f"/api/routes/{HERO}/impact").json()
    assert got["moved_stops"] == 0 and got["projected_on_time"] == 0
    assert got["route_late_before"] == got["route_late_after"] == 12
    assert got["hub_on_time_before"] == got["hub_on_time_after"]
    assert got["meets_sla_before"] is False and got["meets_sla_after"] is False
    assert hero.get("/api/routes/R-nope/impact").status_code == 404


def test_hero_path_apply_suggestions_writes_audit_and_changes_impact(hero):
    sugg = hero.get(f"/api/routes/{HERO}/suggestions").json()["suggestions"]
    before = hero.get(f"/api/routes/{HERO}/impact").json()
    for s in sugg:
        resp = hero.post(
            f"/api/stops/{s['stop_id']}/reassign",
            headers=DISPATCHER,
            json={"to_route_id": s["to_route_id"], "reason_code": "sla_risk", "note": s["reason"]},
        )
        assert resp.status_code == 200, resp.text
    after = hero.get(f"/api/routes/{HERO}/impact").json()
    n = len(sugg)
    assert after["moved_stops"] == n and after["projected_on_time"] == n
    assert after["route_late_before"] == before["route_late_before"] == 12
    assert after["route_late_after"] == 12 - n
    assert after["route_risk_after"] < after["route_risk_before"]
    assert after["route_risk_before"] >= recommend.AT_RISK_ROUTE_SCORE
    assert after["route_risk_after"] < recommend.AT_RISK_ROUTE_SCORE
    assert after["hub_on_time_after"] > after["hub_on_time_before"]
    assert after["meets_sla_before"] is False and after["meets_sla_after"] is True
    # one audit row per move, attributed to the caller, with the features the user saw
    audit = hero.get(
        "/api/audit", headers=MANAGER, params={"actor": "dispatcher-a", "action": "stop.reassign"}
    ).json()
    assert len(audit) == n
    assert all(a["reason"] == "sla_risk" for a in audit)
    feats = audit[0]["payload"]["features"]
    assert (
        feats["stop_status"] == "late" and feats["route_risk_score"] == before["route_risk_before"]
    )
    assert feats["to_route_risk_score"] <= 0.1


def test_moved_stop_stays_late_when_target_has_no_slack():
    routes = [
        {"route_id": "A", "depot_id": "D", "risk_score": 0.6, "capacity_stops": 2},
        {"route_id": "B", "depot_id": "D", "risk_score": 0.0, "capacity_stops": 1},
    ]
    gold = [
        {"stop_id": "s1", "route_id": "A", "status": "late"},
        {"stop_id": "s2", "route_id": "A", "status": "on_time"},
        {"stop_id": "s3", "route_id": "B", "status": "on_time"},
    ]
    eff = apply_overrides(gold, {"s1": {"to_route_id": "B"}})  # B now holds 2 > capacity 1
    out = recommend.project_impact("A", routes, gold, eff, {"name": "D", "sla_target_pct": 0.9})
    assert out["moved_stops"] == 1 and out["projected_on_time"] == 0
    assert out["route_late_after"] == 0  # it left route A either way
    assert out["hub_on_time_after"] == out["hub_on_time_before"]
