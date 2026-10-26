"""Storage interface for everything the app writes (Lakebase in production).

Every write goes through `Store.transaction()`; the services layer records the
decision row, its `audit_log` row and the change event inside one transaction,
so either all of them commit or none do.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Protocol

Row = dict[str, Any]


class NotFound(Exception):
    pass


class Tx(Protocol):
    def insert_reassignment(
        self,
        stop_id: str,
        from_route_id: str | None,
        to_route_id: str,
        reason_code: str,
        note: str | None,
        created_by: str,
    ) -> Row: ...

    def insert_exception(
        self, stop_id: str, route_id: str, exception_type: str, reason: str, created_by: str
    ) -> Row: ...

    def get_exception(self, exception_id: int) -> Row | None: ...

    def update_exception(self, exception_id: int, status: str, reason: str | None) -> Row: ...

    def insert_approval(
        self,
        route_id: str,
        stop_id: str | None,
        amount_usd: float,
        justification: str,
        requested_by: str,
    ) -> Row: ...

    def get_approval_for_update(self, approval_id: int) -> Row | None: ...

    def decide_approval(
        self, approval_id: int, status: str, decided_by: str, comment: str
    ) -> Row: ...

    def insert_comment(
        self, entity_type: str, entity_id: str, body: str, created_by: str
    ) -> Row: ...

    def upsert_route_state(self, route_id: str, state: str, updated_by: str) -> Row: ...

    def insert_audit(
        self,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
        reason: str | None,
    ) -> Row: ...

    def insert_genie_message(
        self,
        user_name: str,
        conversation_id: str,
        message_id: str,
        question: str,
        answer: str | None,
        sql: str | None,
    ) -> Row: ...

    def insert_genie_feedback(
        self,
        user_name: str,
        conversation_id: str,
        message_id: str,
        rating: str,
        comment: str | None,
    ) -> Row: ...

    def notify(self, event: dict[str, Any]) -> None:
        """Queue a change event; delivered to listeners only if the transaction commits."""
        ...


class Store(Protocol):
    kind: str

    def init_schema(self) -> None: ...

    def transaction(self) -> AbstractContextManager[Tx]: ...

    def latest_reassignments(self, stop_ids: list[str] | None = None) -> dict[str, Row]: ...

    def list_reassignments(self, stop_id: str) -> list[Row]: ...

    def list_exceptions(
        self, status: str | None = None, route_id: str | None = None, stop_id: str | None = None
    ) -> list[Row]: ...

    def list_approvals(
        self, status: str | None = None, route_id: str | None = None
    ) -> list[Row]: ...

    def list_comments(self, entity_type: str, entity_id: str) -> list[Row]: ...

    def list_route_state(self) -> list[Row]: ...

    def list_audit(
        self,
        actor: str | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[Row]: ...

    def list_genie_messages(
        self, user_name: str, conversation_id: str | None = None
    ) -> list[Row]: ...
