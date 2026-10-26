"""API surface: reads, workflow writes, Genie history/feedback, mock-mode wiring."""

from .conftest import DISPATCHER, DISPATCHER_B, MANAGER, TODAY, open_stop


def test_reads(client):
    assert client.get("/api/health").json()["status"] == "ok"
    f = client.get("/api/filters").json()
    assert f["today"] == TODAY.isoformat() and len(f["depots"]) == 8
    assert "Northeast" in f["regions"] and "sla_risk" in f["reason_codes"]
    routes = client.get("/api/routes").json()
    assert [r["risk_score"] for r in routes] == sorted(
        (r["risk_score"] for r in routes), reverse=True
    )
    ne = client.get("/api/routes", params={"region": "Northeast"}).json()
    assert ne and all(r["depot_id"] in ("DEP-NYC", "DEP-BOS") for r in ne)
    detail = client.get(f"/api/routes/{routes[0]['route_id']}").json()
    assert detail["route"]["route_id"] == routes[0]["route_id"] and detail["stops"]
    assert client.get("/api/routes/R-nope").status_code == 404
    late = client.get("/api/stops", params={"status": "late"}).json()
    assert late and {s["status"] for s in late} == {"late"}
    paths = client.get("/api/map/route-paths").json()
    assert len(paths) == len(routes) and len(paths[0]["path"]) > 2
    heat = client.get("/api/map/history-heat").json()
    assert heat and 0 <= heat[0]["on_time_pct"] <= 1
    clusters = client.get("/api/map/clusters", params={"cell_deg": 0.5}).json()
    assert sum(c["count"] for c in clusters) == len(client.get("/api/stops").json())
    assert client.get("/api/map/clusters", params={"cell_deg": 0}).status_code == 422


def test_exception_lifecycle(client, ctx):
    stop = open_stop(ctx)
    created = client.post(
        "/api/exceptions",
        headers=DISPATCHER,
        json={"stop_id": stop["stop_id"], "exception_type": "weather", "reason": "ice storm"},
    )
    assert created.status_code == 200 and created.json()["route_id"] == stop["route_id"]
    eid = created.json()["id"]
    resolved = client.patch(
        f"/api/exceptions/{eid}",
        headers=DISPATCHER,
        json={"status": "resolved", "reason": "roads cleared"},
    )
    assert resolved.json()["status"] == "resolved"
    assert (
        client.patch(
            f"/api/exceptions/{eid}", headers=DISPATCHER, json={"status": "resolved"}
        ).status_code
        == 422
    )
    assert client.get("/api/exceptions", params={"status": "open"}).json() == []
    audit = client.get("/api/audit", headers=MANAGER, params={"entity_id": stop["stop_id"]})
    assert [a["action"] for a in audit.json()] == ["exception.update", "exception.create"]


def test_route_state_and_comments(client, ctx):
    route_id = ctx.reader.routes(TODAY)[0]["route_id"]
    ok = client.put(
        f"/api/routes/{route_id}/state", headers=DISPATCHER_B, json={"state": "completed"}
    )
    assert ok.status_code == 200
    assert (
        client.put(
            f"/api/routes/{route_id}/state", headers=DISPATCHER, json={"state": "completed"}
        ).status_code
        == 422
    )
    listed = {r["route_id"]: r for r in client.get("/api/routes").json()}
    assert listed[route_id]["status"] == "completed"
    assert listed[route_id]["state_updated_by"] == "dispatcher-b"
    client.post(
        "/api/comments",
        headers=DISPATCHER,
        json={"entity_type": "route", "entity_id": route_id, "body": "driver called"},
    )
    assert client.get(f"/api/routes/{route_id}").json()["comments"][0]["body"] == "driver called"
    assert (
        client.post(
            "/api/comments",
            headers=DISPATCHER,
            json={"entity_type": "route", "entity_id": "R-nope", "body": "x"},
        ).status_code
        == 404
    )


def test_audit_filters(client, ctx):
    stop = open_stop(ctx)
    client.post(
        "/api/comments",
        headers=DISPATCHER,
        json={"entity_type": "stop", "entity_id": stop["stop_id"], "body": "a"},
    )
    client.post(
        "/api/comments",
        headers=DISPATCHER_B,
        json={"entity_type": "stop", "entity_id": stop["stop_id"], "body": "b"},
    )
    rows = client.get("/api/audit", headers=MANAGER, params={"actor": "dispatcher-b"}).json()
    assert [r["actor"] for r in rows] == ["dispatcher-b"]
    assert client.get("/api/audit", headers=MANAGER, params={"limit": 1}).json()[0]["actor"] == (
        "dispatcher-b"
    )


def test_genie_history_is_per_user(client):
    a = client.post(
        "/api/genie/ask",
        headers=DISPATCHER,
        json={"question": "Show late deliveries in the Northeast by carrier."},
    )
    assert a.status_code == 200 and a.json()["sql"] and a.json()["columns"]
    conv = a.json()["conversation_id"]
    follow = client.post(
        "/api/genie/ask",
        headers=DISPATCHER,
        json={"question": "Which depots?", "conversation_id": conv},
    )
    assert follow.json()["conversation_id"] == conv
    assert (
        client.post(
            "/api/genie/ask",
            headers=DISPATCHER_B,
            json={"question": "hijack", "conversation_id": conv},
        ).status_code
        == 404
    )
    assert len(client.get("/api/genie/history", headers=DISPATCHER).json()) == 2
    assert client.get("/api/genie/history", headers=DISPATCHER_B).json() == []
    fb = {"conversation_id": conv, "message_id": a.json()["message_id"], "rating": "positive"}
    assert client.post("/api/genie/feedback", headers=DISPATCHER, json=fb).json() == {"ok": True}
    assert client.post("/api/genie/feedback", headers=DISPATCHER_B, json=fb).status_code == 404
    rows = client.get("/api/audit", headers=MANAGER, params={"action": "genie.feedback"}).json()
    assert rows[0]["payload"]["rating"] == "positive"


def test_openapi_operation_ids(client):
    spec = client.get("/openapi.json").json()
    ids = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    assert {
        "listRoutes",
        "listStops",
        "reassignStop",
        "createException",
        "updateException",
        "requestApproval",
        "decideApproval",
        "setRouteState",
        "listAudit",
        "askGenie",
        "sendGenieFeedback",
        "getStopClusters",
        "getHistoryHeat",
    } <= ids
