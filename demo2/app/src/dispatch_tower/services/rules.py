"""Business rules that guard writes: role gates and the approval state machine."""

from __future__ import annotations

from .identity import Identity


class Forbidden(Exception):
    pass


class InvalidTransition(Exception):
    pass


class ValidationFailed(Exception):
    pass


# Which roles may perform each action.
PERMISSIONS: dict[str, frozenset[str]] = {
    "stop.reassign": frozenset({"dispatcher", "manager"}),
    "exception.create": frozenset({"dispatcher", "manager"}),
    "exception.update": frozenset({"dispatcher", "manager"}),
    "approval.request": frozenset({"dispatcher", "manager"}),
    "approval.decide": frozenset({"manager"}),
    "comment.create": frozenset({"dispatcher", "manager"}),
    "route_state.update": frozenset({"dispatcher", "manager"}),
    "audit.read": frozenset({"dispatcher", "manager"}),
}


def require(identity: Identity, action: str) -> None:
    allowed = PERMISSIONS.get(action)
    if allowed is None:
        raise Forbidden(f"unknown action {action}")
    if identity.role not in allowed:
        raise Forbidden(f"role '{identity.role}' may not perform {action}")


# Approval state machine: pending -> approved | rejected; decided is terminal.
APPROVAL_TRANSITIONS: dict[str, dict[str, str]] = {
    "pending": {"approve": "approved", "reject": "rejected"},
    "approved": {},
    "rejected": {},
}


def next_approval_status(current: str, decision: str) -> str:
    try:
        return APPROVAL_TRANSITIONS[current][decision]
    except KeyError:
        raise InvalidTransition(f"cannot {decision} an approval that is {current}") from None
