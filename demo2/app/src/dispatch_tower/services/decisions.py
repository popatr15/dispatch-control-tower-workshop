"""Every user write: validate, enforce the role gate, then persist the decision,
its audit_log row and its change event in a single Lakebase transaction.

The audit payload captures the features the user saw at decision time (stop
status, ETA, route risk), which the sync_decisions job turns into labeled data.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..db.schema import EXCEPTION_TYPES, REASSIGNMENT_REASONS, ROUTE_STATES
from ..db.store import NotFound, Row, Store
from .effective import apply_overrides
from .identity import Identity
from .rules import Forbidden, ValidationFailed, next_approval_status, require
from .warehouse import GoldReader


class DecisionService:
    def __init__(
        self,
        store: Store,
        reader: GoldReader,
        *,
        allow_self_approval: bool = False,
        max_expedite_usd: float = 10000.0,
    ) -> None:
        self.store = store
        self.reader = reader
        self.allow_self_approval = allow_self_approval
        self.max_expedite_usd = max_expedite_usd

    # --- lookups -----------------------------------------------------------

    def _day_for(self, day: date | None) -> date:
        if day:
            return day
        dates = self.reader.route_dates()
        if not dates:
            raise NotFound("no route dates in gold tables")
        return dates[0]

    def find_stop(self, stop_id: str, day: date | None = None) -> Row:
        stops = self.reader.stops(self._day_for(day))
        raw = next((s for s in stops if s["stop_id"] == stop_id), None)
        if raw is None:
            raise NotFound(f"stop {stop_id}")
        latest = self.store.latest_reassignments([stop_id])
        return apply_overrides([raw], latest)[0]

    def find_route(self, route_id: str, day: date | None = None) -> Row:
        routes = self.reader.routes(self._day_for(day))
        route = next((r for r in routes if r["route_id"] == route_id), None)
        if route is None:
            raise NotFound(f"route {route_id}")
        return route

    @staticmethod
    def _features(stop: Row | None, route: Row | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if stop:
            out.update(
                stop_status=stop.get("status"),
                late_minutes=stop.get("late_minutes"),
                eta_ts=stop.get("eta_ts"),
                promised_window_end=stop.get("promised_window_end"),
                late_reason_code=stop.get("late_reason_code"),
                depot_id=stop.get("depot_id"),
                carrier_id=stop.get("carrier_id"),
                region=stop.get("region"),
                route_date=stop.get("route_date"),
            )
        if route:
            out.update(
                route_risk_score=route.get("risk_score"),
                route_status=route.get("status"),
                route_depot_id=route.get("depot_id"),
            )
        return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in out.items()}

    # --- writes ------------------------------------------------------------

    def reassign_stop(
        self, who: Identity, stop_id: str, to_route_id: str, reason_code: str, note: str | None
    ) -> Row:
        require(who, "stop.reassign")
        if reason_code not in REASSIGNMENT_REASONS:
            raise ValidationFailed(f"unknown reason_code {reason_code}")
        stop = self.find_stop(stop_id)
        if stop["route_id"] == to_route_id:
            raise ValidationFailed("stop is already on that route")
        if stop["status"] == "delivered":
            raise ValidationFailed("delivered stops cannot be reassigned")
        target = self.find_route(to_route_id, stop["route_date"])
        source = self.find_route(stop["route_id"], stop["route_date"])
        features = self._features(stop, source)
        features["to_route_risk_score"] = target.get("risk_score")
        with self.store.transaction() as tx:
            row = tx.insert_reassignment(
                stop_id, stop["route_id"], to_route_id, reason_code, note, who.user
            )
            tx.insert_audit(
                who.user,
                "stop.reassign",
                "stop",
                stop_id,
                {
                    "reassignment_id": row["id"],
                    "from_route_id": stop["route_id"],
                    "to_route_id": to_route_id,
                    "note": note,
                    "role": who.role,
                    "features": features,
                },
                reason_code,
            )
            tx.notify(
                {
                    "type": "stop.reassigned",
                    "entity_id": stop_id,
                    "route_ids": [stop["route_id"], to_route_id],
                    "actor": who.user,
                }
            )
        return row

    def create_exception(
        self, who: Identity, stop_id: str, exception_type: str, reason: str
    ) -> Row:
        require(who, "exception.create")
        if exception_type not in EXCEPTION_TYPES:
            raise ValidationFailed(f"unknown exception_type {exception_type}")
        stop = self.find_stop(stop_id)
        route = self.find_route(stop["route_id"], stop["route_date"])
        with self.store.transaction() as tx:
            row = tx.insert_exception(stop_id, stop["route_id"], exception_type, reason, who.user)
            tx.insert_audit(
                who.user,
                "exception.create",
                "stop",
                stop_id,
                {
                    "exception_id": row["id"],
                    "exception_type": exception_type,
                    "route_id": stop["route_id"],
                    "role": who.role,
                    "features": self._features(stop, route),
                },
                reason,
            )
            tx.notify(
                {
                    "type": "exception.changed",
                    "entity_id": stop_id,
                    "route_ids": [stop["route_id"]],
                    "actor": who.user,
                }
            )
        return row

    def update_exception(
        self, who: Identity, exception_id: int, status: str, reason: str | None
    ) -> Row:
        require(who, "exception.update")
        if status not in ("open", "resolved"):
            raise ValidationFailed(f"unknown status {status}")
        with self.store.transaction() as tx:
            current = tx.get_exception(exception_id)
            if current is None:
                raise NotFound(f"exception {exception_id}")
            if current["status"] == status and not reason:
                raise ValidationFailed(f"exception is already {status}")
            row = tx.update_exception(exception_id, status, reason)
            tx.insert_audit(
                who.user,
                "exception.update",
                "stop",
                current["stop_id"],
                {
                    "exception_id": exception_id,
                    "from_status": current["status"],
                    "to_status": status,
                    "route_id": current["route_id"],
                    "role": who.role,
                },
                reason,
            )
            tx.notify(
                {
                    "type": "exception.changed",
                    "entity_id": current["stop_id"],
                    "route_ids": [current["route_id"]],
                    "actor": who.user,
                }
            )
        return row

    def request_approval(
        self,
        who: Identity,
        route_id: str,
        stop_id: str | None,
        amount_usd: float,
        justification: str,
    ) -> Row:
        require(who, "approval.request")
        if amount_usd <= 0 or amount_usd > self.max_expedite_usd:
            raise ValidationFailed(f"amount must be between 0 and {self.max_expedite_usd:.0f} USD")
        route = self.find_route(route_id)
        stop = None
        if stop_id:
            stop = self.find_stop(stop_id, route["route_date"])
            if stop["route_id"] != route_id:
                raise ValidationFailed("stop is not on that route")
        with self.store.transaction() as tx:
            row = tx.insert_approval(
                route_id, stop_id, round(amount_usd, 2), justification, who.user
            )
            tx.insert_audit(
                who.user,
                "approval.request",
                "route",
                route_id,
                {
                    "approval_id": row["id"],
                    "stop_id": stop_id,
                    "amount_usd": row["amount_usd"],
                    "role": who.role,
                    "features": self._features(stop, route),
                },
                justification,
            )
            tx.notify(
                {
                    "type": "approval.changed",
                    "entity_id": route_id,
                    "route_ids": [route_id],
                    "actor": who.user,
                }
            )
        return row

    def decide_approval(self, who: Identity, approval_id: int, decision: str, comment: str) -> Row:
        require(who, "approval.decide")
        with self.store.transaction() as tx:
            current = tx.get_approval_for_update(approval_id)
            if current is None:
                raise NotFound(f"approval {approval_id}")
            new_status = next_approval_status(current["status"], decision)
            if current["requested_by"] == who.user and not self.allow_self_approval:
                raise Forbidden("requesters cannot decide their own expedite request")
            row = tx.decide_approval(approval_id, new_status, who.user, comment)
            tx.insert_audit(
                who.user,
                f"approval.{decision}",
                "route",
                current["route_id"],
                {
                    "approval_id": approval_id,
                    "from_status": current["status"],
                    "to_status": new_status,
                    "amount_usd": current["amount_usd"],
                    "requested_by": current["requested_by"],
                    "role": who.role,
                },
                comment,
            )
            tx.notify(
                {
                    "type": "approval.changed",
                    "entity_id": current["route_id"],
                    "route_ids": [current["route_id"]],
                    "actor": who.user,
                }
            )
        return row

    def add_comment(self, who: Identity, entity_type: str, entity_id: str, body: str) -> Row:
        require(who, "comment.create")
        if entity_type == "stop":
            route_ids = [self.find_stop(entity_id)["route_id"]]
        elif entity_type == "route":
            route_ids = [self.find_route(entity_id)["route_id"]]
        else:
            raise ValidationFailed(f"unknown entity_type {entity_type}")
        with self.store.transaction() as tx:
            row = tx.insert_comment(entity_type, entity_id, body, who.user)
            tx.insert_audit(
                who.user,
                "comment.create",
                entity_type,
                entity_id,
                {"comment_id": row["id"], "role": who.role},
                None,
            )
            tx.notify(
                {
                    "type": "comment.added",
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "route_ids": route_ids,
                    "actor": who.user,
                }
            )
        return row

    def set_route_state(self, who: Identity, route_id: str, state: str, reason: str | None) -> Row:
        require(who, "route_state.update")
        if state not in ROUTE_STATES:
            raise ValidationFailed(f"unknown state {state}")
        route = self.find_route(route_id)
        current = next(
            (s for s in self.store.list_route_state() if s["route_id"] == route_id), None
        )
        before = current["state"] if current else route["status"]
        if before == state:
            raise ValidationFailed(f"route is already {state}")
        with self.store.transaction() as tx:
            row = tx.upsert_route_state(route_id, state, who.user)
            tx.insert_audit(
                who.user,
                "route_state.update",
                "route",
                route_id,
                {
                    "from_state": before,
                    "to_state": state,
                    "role": who.role,
                    "features": self._features(None, route),
                },
                reason,
            )
            tx.notify(
                {
                    "type": "route_state.changed",
                    "entity_id": route_id,
                    "route_ids": [route_id],
                    "state": state,
                    "actor": who.user,
                    "updated_at": row["updated_at"].isoformat(),
                }
            )
        return row
