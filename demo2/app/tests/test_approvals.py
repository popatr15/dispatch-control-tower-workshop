"""Approval state machine: pending -> approved | rejected; decided is terminal."""

import pytest

from dispatch_tower.services.rules import InvalidTransition, next_approval_status

from .conftest import DISPATCHER, DISPATCHER_B, MANAGER, make_ctx, make_settings, open_stop


@pytest.mark.parametrize(
    ("current", "decision", "expected"),
    [
        ("pending", "approve", "approved"),
        ("pending", "reject", "rejected"),
    ],
)
def test_valid_transitions(current, decision, expected):
    assert next_approval_status(current, decision) == expected


@pytest.mark.parametrize(
    ("current", "decision"),
    [
        ("approved", "approve"),
        ("approved", "reject"),
        ("rejected", "approve"),
        ("rejected", "reject"),
        ("pending", "cancel"),
        ("unknown", "approve"),
    ],
)
def test_invalid_transitions(current, decision):
    with pytest.raises(InvalidTransition):
        next_approval_status(current, decision)


def _request(client, ctx, headers=DISPATCHER, amount=300.0):
    stop = open_stop(ctx)
    return client.post(
        "/api/approvals",
        headers=headers,
        json={
            "route_id": stop["route_id"],
            "stop_id": stop["stop_id"],
            "amount_usd": amount,
            "justification": "customer SLA penalty",
        },
    )


def test_request_then_approve_then_conflict(client, ctx):
    created = _request(client, ctx)
    assert created.status_code == 200 and created.json()["status"] == "pending"
    aid = created.json()["id"]
    assert [a["id"] for a in client.get("/api/approvals?status=pending").json()] == [aid]
    ok = client.post(
        f"/api/approvals/{aid}/decision",
        headers=MANAGER,
        json={"decision": "approve", "comment": "go"},
    )
    assert ok.json()["status"] == "approved" and ok.json()["decision_comment"] == "go"
    again = client.post(
        f"/api/approvals/{aid}/decision",
        headers=MANAGER,
        json={"decision": "reject", "comment": "changed mind"},
    )
    assert again.status_code == 409
    actions = [a["action"] for a in client.get("/api/audit", headers=MANAGER).json()]
    assert actions == ["approval.approve", "approval.request"]


def test_amount_and_payload_validation(client, ctx):
    assert _request(client, ctx, amount=0).status_code == 422
    assert _request(client, ctx, amount=10_000_000).status_code == 422
    stop = open_stop(ctx)
    wrong = client.post(
        "/api/approvals",
        headers=DISPATCHER,
        json={
            "route_id": stop["route_id"],
            "stop_id": "S-not-real",
            "amount_usd": 5,
            "justification": "whatever",
        },
    )
    assert wrong.status_code == 404


def test_self_approval_blocked_unless_configured(ctx):
    from fastapi.testclient import TestClient

    from dispatch_tower.app import create_app

    for allow, expected in ((False, 403), (True, 200)):
        local = make_ctx(make_settings(DISPATCH_ALLOW_SELF_APPROVAL=allow))
        client = TestClient(create_app(local, serve_static=False))
        aid = _request(client, local, headers=MANAGER).json()["id"]
        resp = client.post(
            f"/api/approvals/{aid}/decision",
            headers=MANAGER,
            json={"decision": "approve", "comment": "mine"},
        )
        assert resp.status_code == expected


def test_missing_approval_is_404(client):
    resp = client.post(
        "/api/approvals/999/decision", headers=MANAGER, json={"decision": "approve", "comment": "x"}
    )
    assert resp.status_code == 404


def test_other_dispatcher_cannot_decide(client, ctx):
    aid = _request(client, ctx).json()["id"]
    resp = client.post(
        f"/api/approvals/{aid}/decision",
        headers=DISPATCHER_B,
        json={"decision": "reject", "comment": "no"},
    )
    assert resp.status_code == 403
