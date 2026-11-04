"""sync_decisions transform: audit rows + current stop outcomes -> decision_labels rows."""

from datetime import UTC, datetime

from dispatch_tower.services.identity import Identity
from dispatch_tower.sync.labels import LABEL_COLUMNS, build_decision_labels

from .conftest import TODAY, open_stop, other_route

WHO = Identity("dispatcher-a", "dispatcher", "test")
MANAGER = Identity("manager-a", "manager", "test")
SYNCED = datetime(2026, 10, 27, tzinfo=UTC)


def _decisions(ctx):
    stop = open_stop(ctx)
    target = other_route(ctx, stop["route_id"])
    ctx.decisions.reassign_stop(WHO, stop["stop_id"], target, "vehicle_down", "engine light")
    exc = ctx.decisions.create_exception(WHO, stop["stop_id"], "customer_unavailable", "closed")
    ctx.decisions.update_exception(WHO, exc["id"], "resolved", None)
    appr = ctx.decisions.request_approval(WHO, target, None, 150.0, "same-day courier")
    ctx.decisions.decide_approval(MANAGER, appr["id"], "approve", "approved")
    ctx.decisions.add_comment(WHO, "stop", stop["stop_id"], "not a decision")
    ctx.decisions.set_route_state(WHO, target, "completed", "done early")
    return stop, target


def test_labels_shape_and_values(ctx):
    stop, target = _decisions(ctx)
    outcomes = {stop["stop_id"]: {**stop, "status": "late", "late_minutes": 42}}
    rows = build_decision_labels(ctx.store.list_audit(), outcomes, SYNCED)
    assert all(tuple(r) == LABEL_COLUMNS for r in rows)
    assert [(r["decision_type"], r["decision"]) for r in rows] == [
        ("reassignment", "reassign"),
        ("exception", "open"),
        ("exception", "resolved"),
        ("approval", "request"),
        ("approval", "approve"),
        ("route_state", "completed"),
    ]  # comment excluded, ordered by audit id
    re = rows[0]
    assert re["reason_code"] == "vehicle_down" and re["reason_text"] == "engine light"
    assert (re["route_id"], re["to_route_id"]) == (stop["route_id"], target)
    assert re["feat_stop_status"] == stop["status"] and re["feat_region"] == stop["region"]
    assert re["outcome_status"] == "late" and re["outcome_on_time"] is False
    assert re["outcome_late_minutes"] == 42 and re["outcome_known"] is True
    assert re["actor"] == "dispatcher-a" and re["actor_role"] == "dispatcher"
    assert rows[1]["reason_code"] == "customer_unavailable"
    assert rows[4]["actor"] == "manager-a" and rows[4]["amount_usd"] == 150.0
    assert rows[5]["outcome_known"] is False and rows[5]["stop_id"] is None
    assert {r["synced_at"] for r in rows} == {SYNCED.isoformat()}


def test_unknown_outcome_when_stop_still_open(ctx):
    stop, _ = _decisions(ctx)
    rows = build_decision_labels(
        ctx.store.list_audit(), {stop["stop_id"]: {**stop, "status": "at_risk"}}, SYNCED
    )
    assert rows[0]["outcome_known"] is False and rows[0]["outcome_on_time"] is None


def test_on_time_outcome_and_json_payloads():
    audit = [
        {
            "id": 7,
            "actor": "a",
            "action": "stop.reassign",
            "entity_type": "stop",
            "entity_id": "S9",
            "reason": "weather",
            "created_at": TODAY,
            "payload": '{"from_route_id": "R1", "to_route_id": "R2", "features": {}}',
        }
    ]
    [row] = build_decision_labels(audit, {"S9": {"status": "delivered", "late_minutes": 0}}, SYNCED)
    assert row["outcome_on_time"] is True and row["decided_at"] == TODAY.isoformat()
    assert build_decision_labels([], {}, SYNCED) == []
