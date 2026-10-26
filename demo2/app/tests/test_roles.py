"""Role gating: who may do what, and how the role is resolved."""

import pytest

from dispatch_tower.services.identity import (
    GroupLookup,
    Identity,
    Unauthenticated,
    resolve_identity,
)
from dispatch_tower.services.rules import PERMISSIONS, Forbidden, require

from .conftest import DISPATCHER, MANAGER, make_ctx, make_settings, open_stop


def test_only_managers_decide_approvals():
    require(Identity("m", "manager", "t"), "approval.decide")
    with pytest.raises(Forbidden):
        require(Identity("d", "dispatcher", "t"), "approval.decide")
    with pytest.raises(Forbidden):
        require(Identity("m", "manager", "t"), "unknown.action")
    assert all("manager" in roles for roles in PERMISSIONS.values())


def test_api_role_gate(client, ctx):
    stop = open_stop(ctx)
    appr = client.post(
        "/api/approvals",
        headers=DISPATCHER,
        json={"route_id": stop["route_id"], "amount_usd": 120, "justification": "late truck"},
    ).json()
    denied = client.post(
        f"/api/approvals/{appr['id']}/decision",
        headers=DISPATCHER,
        json={"decision": "approve", "comment": "self"},
    )
    assert denied.status_code == 403
    ok = client.post(
        f"/api/approvals/{appr['id']}/decision",
        headers=MANAGER,
        json={"decision": "approve", "comment": "fine"},
    )
    assert ok.status_code == 200 and ok.json()["decided_by"] == "manager-a"


def test_role_switch_header_ignored_unless_enabled():
    s = make_settings(DISPATCH_ALLOW_ROLE_SWITCH=False)
    who = resolve_identity(
        s, email="x", username=None, token=None, role_header="manager", groups=None
    )
    assert who.role == "dispatcher" and who.role_source == "default"


def test_none_sentinel_means_no_role_overrides():
    assert make_settings(DISPATCH_ROLE_OVERRIDES="none").parsed_role_overrides() == {}
    assert make_settings(DISPATCH_ROLE_OVERRIDES="").parsed_role_overrides() == {}


def test_override_beats_groups_and_default():
    s = make_settings(
        DISPATCH_ALLOW_ROLE_SWITCH=False, DISPATCH_ROLE_OVERRIDES="Boss=manager, bad=root"
    )
    who = resolve_identity(
        s,
        email="boss",
        username=None,
        token="t",
        role_header=None,
        groups=GroupLookup(lambda _t: ["dispatchers"]),
    )
    assert (who.role, who.role_source) == ("manager", "override")
    assert s.parsed_role_overrides() == {"boss": "manager"}


def test_group_membership_and_fallbacks():
    s = make_settings(DISPATCH_ALLOW_ROLE_SWITCH=False)
    mgr = resolve_identity(
        s,
        email="a",
        username=None,
        token="t",
        role_header=None,
        groups=GroupLookup(lambda _t: ["Managers"]),
    )
    assert (mgr.role, mgr.role_source) == ("manager", "group")

    def broken(_t):
        raise RuntimeError("scim down")

    fallback = resolve_identity(
        s, email="b", username=None, token="t", role_header=None, groups=GroupLookup(broken)
    )
    assert (fallback.role, fallback.role_source) == ("dispatcher", "default")
    local = resolve_identity(
        s, email=None, username=None, token=None, role_header=None, groups=None
    )
    assert local.user == s.dev_user


def test_me_endpoint_reports_identity(client):
    me = client.get("/api/me", headers=MANAGER).json()
    assert me == {
        "user": "manager-a",
        "role": "manager",
        "role_source": "switch",
        "can_switch_role": True,
        "mock": True,
    }


def test_actor_comes_from_forwarded_identity(client, ctx):
    stop = open_stop(ctx)
    client.post(
        "/api/comments",
        headers=DISPATCHER,
        json={"entity_type": "stop", "entity_id": stop["stop_id"], "body": "gate code 12"},
    )
    [audit] = client.get("/api/audit", headers=MANAGER).json()
    assert audit["actor"] == "dispatcher-a" and audit["action"] == "comment.create"


def test_default_role_validation():
    with pytest.raises(ValueError):
        make_settings(DISPATCH_DEFAULT_ROLE="admin")
    assert make_ctx().settings.default_role == "dispatcher"


def test_identity_required_outside_mock_mode():
    s = make_settings(DISPATCH_MOCK=False)
    with pytest.raises(Unauthenticated):
        resolve_identity(s, email=None, username=None, token=None, role_header=None, groups=None)
    who = resolve_identity(
        s, email="a@example.com", username=None, token=None, role_header=None, groups=None
    )
    assert who.user == "a@example.com"


def test_malformed_forwarded_identity_rejected():
    s = make_settings()
    for bad in ("a@x.com, b@x.com", "a b", "a\x00b", 'a"b', "x" * 400):
        with pytest.raises(Unauthenticated):
            resolve_identity(s, email=bad, username=None, token=None, role_header=None, groups=None)


def test_api_returns_401_without_proxy_identity():
    from fastapi.testclient import TestClient

    from dispatch_tower.app import create_app

    app = create_app(make_ctx(make_settings(DISPATCH_MOCK=False)), serve_static=False)
    client = TestClient(app)
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"X-Forwarded-Email": "a@example.com"}).status_code == 200


def test_workshop_toggles_log_warning(caplog):
    from dispatch_tower.app import warn_workshop_toggles

    off = make_settings(DISPATCH_ALLOW_ROLE_SWITCH=False, DISPATCH_ALLOW_SELF_APPROVAL=False)
    with caplog.at_level("WARNING", logger="dispatch_tower"):
        assert warn_workshop_toggles(off) == []
    assert not caplog.records
    on = make_settings(DISPATCH_ALLOW_ROLE_SWITCH=True, DISPATCH_ALLOW_SELF_APPROVAL=True)
    with caplog.at_level("WARNING", logger="dispatch_tower"):
        enabled = warn_workshop_toggles(on)
    assert enabled == ["DISPATCH_ALLOW_ROLE_SWITCH", "DISPATCH_ALLOW_SELF_APPROVAL"]
    assert "WORKSHOP MODE" in caplog.text
