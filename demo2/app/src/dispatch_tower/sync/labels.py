"""Turn Lakebase decision rows into labeled training/audit data.

Pure Python (stdlib only) so the sync_decisions job and the unit tests share it.
One output row per decision: what was decided, why, by whom, the features the
user saw at decision time (from the audit payload) and the outcome when known
(from the stop's current gold row).

The output feeds the next routing model: `decision` + `reason_code` are labels,
`feat_*` columns are inputs, and `outcome_*` columns say whether it worked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

Row = dict[str, Any]

LABEL_COLUMNS = (
    "decision_id",
    "decision_type",
    "decision",
    "reason_code",
    "reason_text",
    "entity_type",
    "entity_id",
    "stop_id",
    "route_id",
    "to_route_id",
    "actor",
    "actor_role",
    "decided_at",
    "feat_stop_status",
    "feat_late_minutes",
    "feat_route_risk_score",
    "feat_to_route_risk_score",
    "feat_depot_id",
    "feat_carrier_id",
    "feat_region",
    "amount_usd",
    "outcome_status",
    "outcome_on_time",
    "outcome_late_minutes",
    "outcome_known",
    "synced_at",
)

# audit action -> (decision_type, decision)
ACTIONS = {
    "stop.reassign": ("reassignment", "reassign"),
    "exception.create": ("exception", "open"),
    "exception.update": ("exception", None),  # to_status
    "approval.request": ("approval", "request"),
    "approval.approve": ("approval", "approve"),
    "approval.reject": ("approval", "reject"),
    "route_state.update": ("route_state", None),  # to_state
}


def _payload(row: Row) -> dict[str, Any]:
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def build_decision_labels(
    audit_rows: list[Row], stop_outcomes: dict[str, Row], synced_at: datetime | None = None
) -> list[Row]:
    """`stop_outcomes` maps stop_id -> current gold `stops` row (status, late_minutes...)."""
    synced = _iso(synced_at or datetime.now(UTC))
    out: list[Row] = []
    for row in sorted(audit_rows, key=lambda r: r["id"]):
        kind = ACTIONS.get(row["action"])
        if kind is None:
            continue  # comments, Genie feedback: not decisions
        decision_type, decision = kind
        p = _payload(row)
        feats = p.get("features") or {}
        if decision is None:
            decision = p.get("to_status") or p.get("to_state")
        stop_id = row["entity_id"] if row["entity_type"] == "stop" else p.get("stop_id")
        route_id = (
            row["entity_id"]
            if row["entity_type"] == "route"
            else p.get("from_route_id") or p.get("route_id")
        )
        outcome = stop_outcomes.get(stop_id) if stop_id else None
        status = outcome.get("status") if outcome else None
        known = status in ("delivered", "on_time", "late") if outcome else False
        on_time = None
        if known and outcome is not None:
            on_time = status != "late" and int(outcome.get("late_minutes") or 0) == 0
        out.append(
            {
                "decision_id": int(row["id"]),
                "decision_type": decision_type,
                "decision": decision,
                "reason_code": row.get("reason")
                if decision_type == "reassignment"
                else (p.get("exception_type")),
                "reason_text": p.get("note")
                if decision_type == "reassignment"
                else row.get("reason"),
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "stop_id": stop_id,
                "route_id": route_id,
                "to_route_id": p.get("to_route_id"),
                "actor": row["actor"],
                "actor_role": p.get("role"),
                "decided_at": _iso(row["created_at"]),
                "feat_stop_status": feats.get("stop_status"),
                "feat_late_minutes": feats.get("late_minutes"),
                "feat_route_risk_score": feats.get("route_risk_score"),
                "feat_to_route_risk_score": feats.get("to_route_risk_score"),
                "feat_depot_id": feats.get("depot_id") or feats.get("route_depot_id"),
                "feat_carrier_id": feats.get("carrier_id"),
                "feat_region": feats.get("region"),
                "amount_usd": float(p["amount_usd"]) if p.get("amount_usd") is not None else None,
                "outcome_status": status,
                "outcome_on_time": on_time,
                "outcome_late_minutes": int(outcome["late_minutes"])
                if known and outcome and (outcome.get("late_minutes") is not None)
                else None,
                "outcome_known": bool(known),
                "synced_at": synced,
            }
        )
    return out
