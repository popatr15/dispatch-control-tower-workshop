"""In-memory Store for local dev and tests.

Transactions are real: writes go to a working copy that replaces the committed
state only when the `with` block exits cleanly, so a failure part-way through
(for example while writing the audit row) leaves nothing behind.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from ..services.events import EventBus
from .store import NotFound, Row

_TABLES = (
    "stop_reassignments",
    "exceptions",
    "approvals",
    "comments",
    "audit_log",
    "genie_messages",
    "genie_feedback",
)


def _now() -> datetime:
    return datetime.now(UTC)


class _State:
    def __init__(self) -> None:
        self.tables: dict[str, list[Row]] = {name: [] for name in _TABLES}
        self.route_state: dict[str, Row] = {}
        self.seq: dict[str, int] = {name: 0 for name in _TABLES}


class MemoryTx:
    def __init__(self, state: _State) -> None:
        self._s = state
        self.events: list[dict[str, Any]] = []

    def _insert(self, table: str, row: Row) -> Row:
        self._s.seq[table] += 1
        row = {"id": self._s.seq[table], **row}
        self._s.tables[table].append(row)
        return dict(row)

    def _find(self, table: str, row_id: int) -> Row | None:
        return next((r for r in self._s.tables[table] if r["id"] == row_id), None)

    def insert_reassignment(
        self, stop_id, from_route_id, to_route_id, reason_code, note, created_by
    ) -> Row:
        return self._insert(
            "stop_reassignments",
            {
                "stop_id": stop_id,
                "from_route_id": from_route_id,
                "to_route_id": to_route_id,
                "reason_code": reason_code,
                "note": note,
                "created_by": created_by,
                "created_at": _now(),
            },
        )

    def insert_exception(self, stop_id, route_id, exception_type, reason, created_by) -> Row:
        now = _now()
        return self._insert(
            "exceptions",
            {
                "stop_id": stop_id,
                "route_id": route_id,
                "exception_type": exception_type,
                "reason": reason,
                "status": "open",
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
            },
        )

    def get_exception(self, exception_id: int) -> Row | None:
        row = self._find("exceptions", exception_id)
        return dict(row) if row else None

    def update_exception(self, exception_id, status, reason) -> Row:
        row = self._find("exceptions", exception_id)
        if row is None:
            raise NotFound(f"exception {exception_id}")
        row["status"] = status
        if reason:
            row["reason"] = reason
        row["updated_at"] = _now()
        return dict(row)

    def insert_approval(self, route_id, stop_id, amount_usd, justification, requested_by) -> Row:
        return self._insert(
            "approvals",
            {
                "route_id": route_id,
                "stop_id": stop_id,
                "amount_usd": float(amount_usd),
                "justification": justification,
                "status": "pending",
                "requested_by": requested_by,
                "decided_by": None,
                "decided_at": None,
                "decision_comment": None,
                "created_at": _now(),
            },
        )

    def get_approval_for_update(self, approval_id: int) -> Row | None:
        row = self._find("approvals", approval_id)
        return dict(row) if row else None

    def decide_approval(self, approval_id, status, decided_by, comment) -> Row:
        row = self._find("approvals", approval_id)
        if row is None:
            raise NotFound(f"approval {approval_id}")
        row.update(
            status=status, decided_by=decided_by, decided_at=_now(), decision_comment=comment
        )
        return dict(row)

    def insert_comment(self, entity_type, entity_id, body, created_by) -> Row:
        return self._insert(
            "comments",
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "body": body,
                "created_by": created_by,
                "created_at": _now(),
            },
        )

    def upsert_route_state(self, route_id, state, updated_by) -> Row:
        row = {"route_id": route_id, "state": state, "updated_by": updated_by, "updated_at": _now()}
        self._s.route_state[route_id] = row
        return dict(row)

    def insert_audit(self, actor, action, entity_type, entity_id, payload, reason) -> Row:
        return self._insert(
            "audit_log",
            {
                "actor": actor,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "payload": copy.deepcopy(payload),
                "reason": reason,
                "created_at": _now(),
            },
        )

    def insert_genie_message(
        self, user_name, conversation_id, message_id, question, answer, sql
    ) -> Row:
        return self._insert(
            "genie_messages",
            {
                "user_name": user_name,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "question": question,
                "answer": answer,
                "sql": sql,
                "created_at": _now(),
            },
        )

    def insert_genie_feedback(self, user_name, conversation_id, message_id, rating, comment) -> Row:
        return self._insert(
            "genie_feedback",
            {
                "user_name": user_name,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "rating": rating,
                "comment": comment,
                "created_at": _now(),
            },
        )

    def notify(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class MemoryStore:
    kind = "memory"

    def __init__(self, bus: EventBus | None = None) -> None:
        self._state = _State()
        self._lock = threading.RLock()
        self._bus = bus

    def init_schema(self) -> None:
        return None

    @contextmanager
    def transaction(self) -> Iterator[MemoryTx]:
        with self._lock:
            working = copy.deepcopy(self._state)
            tx = MemoryTx(working)
            yield tx  # an exception here discards `working`
            self._state = working
        if self._bus:
            for event in tx.events:
                self._bus.publish(event)

    def reset(self) -> None:
        with self._lock:
            self._state = _State()

    # --- reads -------------------------------------------------------------

    def _rows(self, table: str) -> list[Row]:
        with self._lock:
            return [dict(r) for r in self._state.tables[table]]

    def latest_reassignments(self, stop_ids: list[str] | None = None) -> dict[str, Row]:
        latest: dict[str, Row] = {}
        wanted = set(stop_ids) if stop_ids is not None else None
        for row in self._rows("stop_reassignments"):
            if wanted is not None and row["stop_id"] not in wanted:
                continue
            prev = latest.get(row["stop_id"])
            if prev is None or (row["created_at"], row["id"]) >= (prev["created_at"], prev["id"]):
                latest[row["stop_id"]] = row
        return latest

    def list_reassignments(self, stop_id: str) -> list[Row]:
        rows = [r for r in self._rows("stop_reassignments") if r["stop_id"] == stop_id]
        return sorted(rows, key=lambda r: (r["created_at"], r["id"]), reverse=True)

    def list_exceptions(self, status=None, route_id=None, stop_id=None) -> list[Row]:
        rows = [
            r
            for r in self._rows("exceptions")
            if (status is None or r["status"] == status)
            and (route_id is None or r["route_id"] == route_id)
            and (stop_id is None or r["stop_id"] == stop_id)
        ]
        return sorted(rows, key=lambda r: r["id"], reverse=True)

    def list_approvals(self, status=None, route_id=None) -> list[Row]:
        rows = [
            r
            for r in self._rows("approvals")
            if (status is None or r["status"] == status)
            and (route_id is None or r["route_id"] == route_id)
        ]
        return sorted(rows, key=lambda r: r["id"], reverse=True)

    def list_comments(self, entity_type: str, entity_id: str) -> list[Row]:
        rows = [
            r
            for r in self._rows("comments")
            if r["entity_type"] == entity_type and r["entity_id"] == entity_id
        ]
        return sorted(rows, key=lambda r: r["id"])

    def list_route_state(self) -> list[Row]:
        with self._lock:
            return [dict(r) for r in self._state.route_state.values()]

    def list_audit(
        self, actor=None, action=None, entity_type=None, entity_id=None, since=None, limit=200
    ) -> list[Row]:
        rows = [
            r
            for r in self._rows("audit_log")
            if (actor is None or r["actor"] == actor)
            and (action is None or r["action"] == action)
            and (entity_type is None or r["entity_type"] == entity_type)
            and (entity_id is None or r["entity_id"] == entity_id)
            and (since is None or r["created_at"] >= since)
        ]
        return sorted(rows, key=lambda r: r["id"], reverse=True)[:limit]

    def list_genie_messages(self, user_name: str, conversation_id: str | None = None) -> list[Row]:
        rows = [
            r
            for r in self._rows("genie_messages")
            if r["user_name"] == user_name
            and (conversation_id is None or r["conversation_id"] == conversation_id)
        ]
        return sorted(rows, key=lambda r: r["id"])

    def table_rows(self, table: str) -> list[Row]:
        """Raw table access for tests and the sync transform's local runs."""
        if table == "route_state":
            return self.list_route_state()
        return self._rows(table)
