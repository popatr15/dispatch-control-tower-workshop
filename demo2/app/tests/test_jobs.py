"""Helpers used by the sync_decisions and seed_reset jobs."""

import pytest

from dispatch_tower.sync.jobs import (
    ident,
    principal,
    reset_statements,
    stop_ids_in,
    table_exists,
)


def test_ident_rejects_injection():
    assert ident("workshop_dispatch_gold") == "workshop_dispatch_gold"
    for bad in ("x; DROP", "a-b", "", "1abc"):
        with pytest.raises(ValueError):
            ident(bad)


def test_principal_allowlist():
    assert principal("account users") == "`account users`"
    assert principal("first.last+ops@example.com") == "`first.last+ops@example.com`"
    assert principal("6f1c2d3e-0000-4b7a-9c1d-2e3f4a5b6c7d").startswith("`6f1c")
    for bad in (
        "",
        "x` ; DROP TABLE t; --",
        "evil`",
        "a'b",
        'a"b',
        "a;b",
        " leading",
        "trailing ",
        "ok\n",
        "new\nline",
        "x" * 300,
    ):
        with pytest.raises(ValueError):
            principal(bad)


def test_stop_ids_from_audit():
    audit = [
        {"entity_type": "stop", "entity_id": "S2", "payload": {}},
        {"entity_type": "route", "entity_id": "R1", "payload": {"stop_id": "S1"}},
        {"entity_type": "route", "entity_id": "R1", "payload": {"stop_id": None}},
    ]
    assert stop_ids_in(audit) == ["S1", "S2"]


def test_reset_truncates_all_decision_tables(pg_conninfo):
    import psycopg

    from dispatch_tower.db.postgres import PostgresStore, TokenProvider

    store = PostgresStore(pg_conninfo, TokenProvider(lambda: ("unused", None)), "reset_test")
    store.open()
    store.init_schema()
    with store.transaction() as tx:
        tx.insert_comment("stop", "S1", "hello", "u")
        tx.insert_audit("u", "comment.create", "stop", "S1", {}, None)
    store.close()
    with psycopg.connect(**pg_conninfo, autocommit=True) as conn:
        assert table_exists(conn, "reset_test", "audit_log")
        assert not table_exists(conn, "reset_test", "nope")
        for stmt in reset_statements("reset_test"):
            conn.execute(stmt)
        assert conn.execute("SELECT count(*) FROM reset_test.audit_log").fetchone()[0] == 0
        conn.execute("DROP SCHEMA reset_test CASCADE")
