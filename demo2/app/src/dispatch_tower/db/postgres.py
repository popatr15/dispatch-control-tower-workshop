"""Lakebase (Postgres) Store over psycopg 3.

Authentication uses short-lived OAuth database credentials minted through the
Databricks SDK. Each new pooled connection fetches the current token, and the
pool recycles connections well inside the token lifetime, so expired
credentials never reach the server.

Change events are sent with `pg_notify` inside the write transaction, so they
are delivered only on commit and reach every app worker (each worker LISTENs).
"""

from __future__ import annotations

import json
import logging
import select
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from ..services.events import EventBus
from .schema import ddl_statements, operator_grants
from .store import NotFound, Row

log = logging.getLogger(__name__)

CHANNEL = "dispatch_events"
_TOKEN_SKEW = timedelta(minutes=5)


class TokenProvider:
    """Caches a Lakebase OAuth credential and refreshes it shortly before expiry."""

    def __init__(self, mint: Callable[[], tuple[str, datetime | None]]) -> None:
        self._mint = mint
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires: datetime | None = None

    def token(self) -> str:
        with self._lock:
            now = datetime.now(UTC)
            if self._token is None or (self._expires and now >= self._expires - _TOKEN_SKEW):
                token, expires = self._mint()
                self._token = token
                # Tokens last one hour; assume that if the API omits expire_time.
                self._expires = expires or now + timedelta(minutes=55)
            return self._token


def sdk_token_minter(ws: Any, endpoint: str) -> Callable[[], tuple[str, datetime | None]]:
    def mint() -> tuple[str, datetime | None]:
        cred = ws.postgres.generate_database_credential(endpoint=endpoint)
        expires = None
        raw = getattr(cred, "expire_time", None)
        if isinstance(raw, datetime):
            expires = raw if raw.tzinfo else raw.replace(tzinfo=UTC)
        elif isinstance(raw, str) and raw:
            expires = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return cred.token, expires

    return mint


def resolve_endpoint(ws: Any, endpoint: str | None, branch: str | None) -> str:
    """Return the Lakebase endpoint resource path used to mint credentials."""
    if endpoint:
        return endpoint
    if not branch:
        raise RuntimeError("Set LAKEBASE_ENDPOINT or DISPATCH_LAKEBASE_BRANCH for Lakebase auth")
    for ep in ws.postgres.list_endpoints(parent=branch):
        return ep.name
    raise RuntimeError(f"no Lakebase endpoint found under {branch}")


class PgTx:
    def __init__(self, conn: psycopg.Connection, schema: str) -> None:
        self._c = conn
        self._s = schema

    def _one(self, sql: str, params: tuple | dict) -> Row:
        row = self._c.execute(sql.format(s=self._s), params).fetchone()
        assert row is not None
        return _normalize(row)

    def insert_reassignment(
        self, stop_id, from_route_id, to_route_id, reason_code, note, created_by
    ) -> Row:
        return self._one(
            "INSERT INTO {s}.stop_reassignments "
            "(stop_id, from_route_id, to_route_id, reason_code, note, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (stop_id, from_route_id, to_route_id, reason_code, note, created_by),
        )

    def insert_exception(self, stop_id, route_id, exception_type, reason, created_by) -> Row:
        return self._one(
            "INSERT INTO {s}.exceptions (stop_id, route_id, exception_type, reason, created_by) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (stop_id, route_id, exception_type, reason, created_by),
        )

    def get_exception(self, exception_id: int) -> Row | None:
        row = self._c.execute(
            f"SELECT * FROM {self._s}.exceptions WHERE id = %s FOR UPDATE", (exception_id,)
        ).fetchone()
        return _normalize(row) if row else None

    def update_exception(self, exception_id, status, reason) -> Row:
        row = self._c.execute(
            f"UPDATE {self._s}.exceptions SET status = %s, reason = COALESCE(%s, reason), "
            "updated_at = now() WHERE id = %s RETURNING *",
            (status, reason, exception_id),
        ).fetchone()
        if row is None:
            raise NotFound(f"exception {exception_id}")
        return _normalize(row)

    def insert_approval(self, route_id, stop_id, amount_usd, justification, requested_by) -> Row:
        return self._one(
            "INSERT INTO {s}.approvals (route_id, stop_id, amount_usd, justification, "
            "requested_by) VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (route_id, stop_id, amount_usd, justification, requested_by),
        )

    def get_approval_for_update(self, approval_id: int) -> Row | None:
        row = self._c.execute(
            f"SELECT * FROM {self._s}.approvals WHERE id = %s FOR UPDATE", (approval_id,)
        ).fetchone()
        return _normalize(row) if row else None

    def decide_approval(self, approval_id, status, decided_by, comment) -> Row:
        row = self._c.execute(
            f"UPDATE {self._s}.approvals SET status = %s, decided_by = %s, decided_at = now(), "
            "decision_comment = %s WHERE id = %s RETURNING *",
            (status, decided_by, comment, approval_id),
        ).fetchone()
        if row is None:
            raise NotFound(f"approval {approval_id}")
        return _normalize(row)

    def insert_comment(self, entity_type, entity_id, body, created_by) -> Row:
        return self._one(
            "INSERT INTO {s}.comments (entity_type, entity_id, body, created_by) "
            "VALUES (%s, %s, %s, %s) RETURNING *",
            (entity_type, entity_id, body, created_by),
        )

    def upsert_route_state(self, route_id, state, updated_by) -> Row:
        return self._one(
            "INSERT INTO {s}.route_state (route_id, state, updated_by) VALUES (%s, %s, %s) "
            "ON CONFLICT (route_id) DO UPDATE SET state = EXCLUDED.state, "
            "updated_by = EXCLUDED.updated_by, updated_at = now() RETURNING *",
            (route_id, state, updated_by),
        )

    def insert_audit(self, actor, action, entity_type, entity_id, payload, reason) -> Row:
        return self._one(
            "INSERT INTO {s}.audit_log (actor, action, entity_type, entity_id, payload, reason) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (actor, action, entity_type, entity_id, Jsonb(payload), reason),
        )

    def insert_genie_message(
        self, user_name, conversation_id, message_id, question, answer, sql
    ) -> Row:
        return self._one(
            "INSERT INTO {s}.genie_messages (user_name, conversation_id, message_id, question, "
            "answer, sql) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (user_name, conversation_id, message_id, question, answer, sql),
        )

    def insert_genie_feedback(self, user_name, conversation_id, message_id, rating, comment) -> Row:
        return self._one(
            "INSERT INTO {s}.genie_feedback (user_name, conversation_id, message_id, rating, "
            "comment) VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (user_name, conversation_id, message_id, rating, comment),
        )

    def notify(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, default=str)
        if len(payload) > 7000:  # NOTIFY payload limit is 8000 bytes
            payload = json.dumps({k: event[k] for k in ("type", "entity_id") if k in event})
        self._c.execute("SELECT pg_notify(%s, %s)", (CHANNEL, payload))


def _normalize(row: Row) -> Row:
    out = dict(row)
    for key, value in out.items():
        if key == "amount_usd" and value is not None:
            out[key] = float(value)
    return out


class PostgresStore:
    kind = "lakebase"

    def __init__(
        self,
        conninfo: dict[str, Any],
        tokens: TokenProvider,
        schema: str,
        bus: EventBus | None = None,
        *,
        min_size: int = 1,
        max_size: int = 8,
    ) -> None:
        self._conninfo = conninfo
        self._tokens = tokens
        self._schema = schema
        self._bus = bus
        self._stop = threading.Event()
        self._listener: threading.Thread | None = None
        self._pool = ConnectionPool(
            kwargs={**conninfo, "row_factory": dict_row},
            connection_class=self._connection_class(),
            min_size=min_size,
            max_size=max_size,
            max_lifetime=40 * 60,  # recycle well before the 1h token expiry
            max_idle=10 * 60,
            check=ConnectionPool.check_connection,
            open=False,
        )

    def _connection_class(self) -> type[psycopg.Connection]:
        tokens = self._tokens

        class TokenConnection(psycopg.Connection):
            @classmethod
            def connect(cls, conninfo: str = "", **kwargs: Any):  # type: ignore[override]
                kwargs["password"] = tokens.token()
                return super().connect(conninfo, **kwargs)

        return TokenConnection

    def open(self) -> None:
        self._pool.open(wait=True, timeout=60)

    def close(self) -> None:
        self._stop.set()
        self._pool.close()

    def init_schema(self, operator_role: str | None = None) -> None:
        with self._pool.connection() as conn:
            for stmt in ddl_statements(self._schema):
                conn.execute(stmt)
        if operator_role:
            self.grant_operator(operator_role)

    def grant_operator(self, role: str) -> None:
        from psycopg import sql

        try:
            with self._pool.connection() as conn:
                for stmt in operator_grants(self._schema):
                    conn.execute(
                        sql.SQL(stmt).format(
                            schema=sql.Identifier(self._schema), role=sql.Identifier(role)
                        )
                    )
        except psycopg.Error as exc:  # role may not exist yet in this branch
            log.warning("could not grant schema access to operator role: %s", exc)

    @contextmanager
    def transaction(self) -> Iterator[PgTx]:
        with self._pool.connection() as conn:
            with conn.transaction():
                yield PgTx(conn, self._schema)

    def ping(self) -> bool:
        with self._pool.connection() as conn:
            return conn.execute("SELECT 1 AS ok").fetchone() is not None

    # --- reads -------------------------------------------------------------

    def _all(self, sql: str, params: tuple | dict = ()) -> list[Row]:
        with self._pool.connection() as conn:
            return [_normalize(r) for r in conn.execute(sql.format(s=self._schema), params)]

    def latest_reassignments(self, stop_ids: list[str] | None = None) -> dict[str, Row]:
        where, params = "", ()
        if stop_ids is not None:
            where, params = "WHERE stop_id = ANY(%s)", (list(stop_ids),)
        rows = self._all(
            "SELECT DISTINCT ON (stop_id) * FROM {s}.stop_reassignments "
            + where
            + " ORDER BY stop_id, created_at DESC, id DESC",
            params,
        )
        return {r["stop_id"]: r for r in rows}

    def list_reassignments(self, stop_id: str) -> list[Row]:
        return self._all(
            "SELECT * FROM {s}.stop_reassignments WHERE stop_id = %s "
            "ORDER BY created_at DESC, id DESC",
            (stop_id,),
        )

    def list_exceptions(self, status=None, route_id=None, stop_id=None) -> list[Row]:
        return self._all(
            "SELECT * FROM {s}.exceptions WHERE (%(st)s::text IS NULL OR status = %(st)s) "
            "AND (%(r)s::text IS NULL OR route_id = %(r)s) "
            "AND (%(sp)s::text IS NULL OR stop_id = %(sp)s) ORDER BY id DESC LIMIT 500",
            {"st": status, "r": route_id, "sp": stop_id},
        )

    def list_approvals(self, status=None, route_id=None) -> list[Row]:
        return self._all(
            "SELECT * FROM {s}.approvals WHERE (%(st)s::text IS NULL OR status = %(st)s) "
            "AND (%(r)s::text IS NULL OR route_id = %(r)s) ORDER BY id DESC LIMIT 500",
            {"st": status, "r": route_id},
        )

    def list_comments(self, entity_type: str, entity_id: str) -> list[Row]:
        return self._all(
            "SELECT * FROM {s}.comments WHERE entity_type = %s AND entity_id = %s ORDER BY id",
            (entity_type, entity_id),
        )

    def list_route_state(self) -> list[Row]:
        return self._all("SELECT * FROM {s}.route_state")

    def list_audit(
        self, actor=None, action=None, entity_type=None, entity_id=None, since=None, limit=200
    ) -> list[Row]:
        return self._all(
            "SELECT * FROM {s}.audit_log WHERE (%(a)s::text IS NULL OR actor = %(a)s) "
            "AND (%(ac)s::text IS NULL OR action = %(ac)s) "
            "AND (%(et)s::text IS NULL OR entity_type = %(et)s) "
            "AND (%(ei)s::text IS NULL OR entity_id = %(ei)s) "
            "AND (%(since)s::timestamptz IS NULL OR created_at >= %(since)s) "
            "ORDER BY id DESC LIMIT %(lim)s",
            {
                "a": actor,
                "ac": action,
                "et": entity_type,
                "ei": entity_id,
                "since": since,
                "lim": max(1, min(limit, 1000)),
            },
        )

    def list_genie_messages(self, user_name: str, conversation_id: str | None = None) -> list[Row]:
        return self._all(
            "SELECT * FROM {s}.genie_messages WHERE user_name = %(u)s "
            "AND (%(c)s::text IS NULL OR conversation_id = %(c)s) ORDER BY id DESC LIMIT 200",
            {"u": user_name, "c": conversation_id},
        )[::-1]

    # --- LISTEN/NOTIFY -----------------------------------------------------

    def start_listener(self) -> None:
        if self._bus is None or self._listener is not None:
            return
        self._listener = threading.Thread(target=self._listen_loop, name="pg-listen", daemon=True)
        self._listener.start()

    def _listen_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                with psycopg.connect(
                    **self._conninfo, password=self._tokens.token(), autocommit=True
                ) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    backoff = 1.0
                    # Reconnect periodically so a fresh token is used.
                    while not self._stop.is_set() and time.monotonic() - started < 30 * 60:
                        if select.select([conn.fileno()], [], [], 5.0) == ([], [], []):
                            continue
                        for note in conn.notifies(timeout=0, stop_after=100):
                            try:
                                self._bus.publish(json.loads(note.payload))  # type: ignore[union-attr]
                            except ValueError:
                                log.warning("ignoring malformed notify payload")
            except Exception:  # noqa: BLE001 - keep listening across transient failures
                log.exception("Lakebase LISTEN loop failed; retrying in %.0fs", backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)
