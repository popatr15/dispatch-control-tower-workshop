"""Every write records its audit row in the same transaction; failures leave nothing."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from dispatch_tower.app import create_app
from dispatch_tower.db.memory import MemoryTx
from dispatch_tower.db.postgres import PgTx, PostgresStore, TokenProvider
from dispatch_tower.services.events import EventBus
from dispatch_tower.services.identity import Identity

from .conftest import DISPATCHER, TODAY, make_ctx, open_stop, other_route

WHO = Identity("dispatcher-a", "dispatcher", "test")
MANAGER = Identity("manager-a", "manager", "test")


def _boom(*_a, **_k):
    raise RuntimeError("audit write failed")


def test_success_writes_decision_and_audit(ctx):
    stop = open_stop(ctx)
    row = ctx.decisions.reassign_stop(
        WHO, stop["stop_id"], other_route(ctx, stop["route_id"]), "weather", "storm"
    )
    [audit] = ctx.store.list_audit()
    assert audit["action"] == "stop.reassign" and audit["actor"] == WHO.user
    assert audit["reason"] == "weather"
    assert audit["payload"]["reassignment_id"] == row["id"]
    assert audit["payload"]["features"]["stop_status"] == stop["status"]


def test_memory_rollback_when_audit_fails(ctx, monkeypatch):
    stop = open_stop(ctx)
    monkeypatch.setattr(MemoryTx, "insert_audit", _boom)
    with pytest.raises(RuntimeError):
        ctx.decisions.reassign_stop(
            WHO, stop["stop_id"], other_route(ctx, stop["route_id"]), "weather", None
        )
    assert ctx.store.latest_reassignments() == {}
    assert ctx.store.list_audit() == []


def test_every_write_path_rolls_back(ctx, monkeypatch):
    stop = open_stop(ctx)
    exc = ctx.decisions.create_exception(WHO, stop["stop_id"], "weather", "flooded road")
    appr = ctx.decisions.request_approval(WHO, stop["route_id"], None, 250.0, "expedite fee")
    monkeypatch.setattr(MemoryTx, "insert_audit", _boom)
    calls = [
        lambda: ctx.decisions.create_exception(WHO, stop["stop_id"], "other", "x" * 5),
        lambda: ctx.decisions.update_exception(WHO, exc["id"], "resolved", None),
        lambda: ctx.decisions.request_approval(WHO, stop["route_id"], None, 10.0, "again!"),
        lambda: ctx.decisions.decide_approval(MANAGER, appr["id"], "approve", "ok"),
        lambda: ctx.decisions.add_comment(WHO, "stop", stop["stop_id"], "hello"),
        lambda: ctx.decisions.set_route_state(WHO, stop["route_id"], "completed", None),
    ]
    for call in calls:
        with pytest.raises(RuntimeError):
            call()
    assert [e["status"] for e in ctx.store.list_exceptions()] == ["open"]
    assert [a["status"] for a in ctx.store.list_approvals()] == ["pending"]
    assert ctx.store.list_comments("stop", stop["stop_id"]) == []
    assert ctx.store.list_route_state() == []
    assert len(ctx.store.list_audit()) == 2


def _ask_genie(ctx, question="Which routes are late?"):
    client = TestClient(create_app(ctx, serve_static=False), raise_server_exceptions=False)
    return client.post("/api/genie/ask", headers=DISPATCHER, json={"question": question})


def test_genie_ask_writes_message_and_audit(ctx):
    res = _ask_genie(ctx)
    assert res.status_code == 200
    [msg] = ctx.store.list_genie_messages(DISPATCHER["X-Forwarded-Email"])
    [audit] = ctx.store.list_audit(action="genie.ask")
    assert audit["actor"] == DISPATCHER["X-Forwarded-Email"]
    assert audit["entity_type"] == "genie_message" and audit["entity_id"] == msg["message_id"]
    assert audit["payload"]["conversation_id"] == msg["conversation_id"]


def test_genie_ask_rolls_back_when_audit_fails(ctx, monkeypatch):
    monkeypatch.setattr(MemoryTx, "insert_audit", _boom)
    assert _ask_genie(ctx).status_code == 500
    assert ctx.store.list_genie_messages(DISPATCHER["X-Forwarded-Email"]) == []
    assert ctx.store.list_audit() == []


def test_events_publish_only_after_commit(monkeypatch):
    async def run():
        ctx = make_ctx()
        queue = ctx.bus.subscribe()
        stop = open_stop(ctx)
        target = other_route(ctx, stop["route_id"])
        monkeypatch.setattr(MemoryTx, "insert_audit", _boom)
        with pytest.raises(RuntimeError):
            ctx.decisions.reassign_stop(WHO, stop["stop_id"], target, "weather", None)
        await asyncio.sleep(0)
        assert queue.empty()
        monkeypatch.undo()
        ctx.decisions.reassign_stop(WHO, stop["stop_id"], target, "weather", None)
        event = await asyncio.wait_for(queue.get(), 1)
        assert event["type"] == "stop.reassigned" and event["entity_id"] == stop["stop_id"]

    asyncio.run(run())


# --- the same guarantees against a real Postgres -----------------------------


@pytest.fixture
def pg_store(pg_conninfo):
    import psycopg

    schema = "dispatch_test"
    with psycopg.connect(**pg_conninfo, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    store = PostgresStore(
        pg_conninfo, TokenProvider(lambda: ("unused", None)), schema, EventBus(), max_size=2
    )
    store.open()
    store.init_schema()
    store.init_schema("tester")  # idempotent DDL; operator grants to an existing role
    store.grant_operator("no_such_role")  # missing role is logged, not fatal
    yield store
    store.close()


def test_postgres_commit_and_rollback(pg_store, monkeypatch):
    ctx = make_ctx(store=pg_store)
    stop = open_stop(ctx)
    target = other_route(ctx, stop["route_id"])
    monkeypatch.setattr(PgTx, "insert_audit", _boom)
    with pytest.raises(RuntimeError):
        ctx.decisions.reassign_stop(WHO, stop["stop_id"], target, "weather", None)
    assert pg_store.latest_reassignments() == {}
    assert pg_store.list_audit() == []
    monkeypatch.undo()
    row = ctx.decisions.reassign_stop(WHO, stop["stop_id"], target, "weather", "n")
    assert pg_store.latest_reassignments([stop["stop_id"]])[stop["stop_id"]]["id"] == row["id"]
    [audit] = pg_store.list_audit(action="stop.reassign")
    assert audit["payload"]["to_route_id"] == target  # JSONB round-trip
    assert audit["payload"]["features"]["route_date"] == TODAY.isoformat()


def test_postgres_genie_ask_rolls_back(pg_store, monkeypatch):
    ctx = make_ctx(store=pg_store)
    monkeypatch.setattr(PgTx, "insert_audit", _boom)
    assert _ask_genie(ctx).status_code == 500
    assert pg_store.list_genie_messages(DISPATCHER["X-Forwarded-Email"]) == []
    monkeypatch.undo()
    assert _ask_genie(ctx).status_code == 200
    assert len(pg_store.list_genie_messages(DISPATCHER["X-Forwarded-Email"])) == 1
    assert [a["action"] for a in pg_store.list_audit()] == ["genie.ask"]


def test_postgres_approval_flow_and_route_state(pg_store):
    ctx = make_ctx(store=pg_store)
    stop = open_stop(ctx)
    appr = ctx.decisions.request_approval(WHO, stop["route_id"], stop["stop_id"], 99.5, "rush")
    assert appr["amount_usd"] == 99.5 and appr["status"] == "pending"
    done = ctx.decisions.decide_approval(MANAGER, appr["id"], "reject", "not needed")
    assert done["status"] == "rejected" and done["decided_by"] == MANAGER.user
    state = ctx.decisions.set_route_state(WHO, stop["route_id"], "completed", None)
    again = pg_store.list_route_state()
    assert again[0]["state"] == "completed" and state["updated_by"] == WHO.user
    actions = [a["action"] for a in pg_store.list_audit()]
    assert actions == ["route_state.update", "approval.reject", "approval.request"]


def test_postgres_rejects_invalid_values(pg_store):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with pg_store.transaction() as tx:
            tx.insert_reassignment("S1", "R1", "R2", "teleport", None, "u")
    assert pg_store.latest_reassignments() == {}
