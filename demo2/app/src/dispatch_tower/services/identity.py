"""Who is calling, and in which role.

Databricks Apps forwards the signed-in user's identity in request headers;
`X-Forwarded-Access-Token` (on-behalf-of token) lets us read their groups.
Role precedence: workshop role switch header (only when enabled) > configured
per-user override > group membership > configured default.

Trust model: these headers are only trustworthy because the Databricks Apps
proxy strips client-supplied `X-Forwarded-*` headers and sets its own. Outside
mock mode a request without them (i.e. one that bypassed the proxy) is refused.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..config import Settings

log = logging.getLogger(__name__)

ROLES = ("dispatcher", "manager")
# One principal: no list separators, whitespace, quotes or control characters.
_USER = re.compile(r"^[^\s,;\"'<>\x00-\x1f\x7f]{1,320}$")


class Unauthenticated(Exception):
    """The request carries no (or a malformed) proxy-forwarded identity."""


@dataclass(frozen=True)
class Identity:
    user: str
    role: str
    role_source: str

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"


class GroupLookup:
    """Caches group names per user for a few minutes (OBO SCIM `Me`)."""

    def __init__(self, fetch: Callable[[str], list[str]], ttl_seconds: int = 300) -> None:
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, list[str]]] = {}

    def groups(self, user: str, token: str) -> list[str]:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(user)
            if hit and now - hit[0] < self._ttl:
                return hit[1]
        try:
            groups = self._fetch(token)
        except Exception:  # noqa: BLE001 - fall back to the default role
            log.warning("group lookup failed for current user; using default role")
            groups = []
        with self._lock:
            self._cache[user] = (now, groups)
        return groups


def obo_groups(token: str) -> list[str]:
    from databricks.sdk import WorkspaceClient

    me = WorkspaceClient(token=token, auth_type="pat").current_user.me()
    return [g.display for g in (me.groups or []) if g.display]


def resolve_identity(
    settings: Settings,
    *,
    email: str | None,
    username: str | None,
    token: str | None,
    role_header: str | None,
    groups: GroupLookup | None,
) -> Identity:
    forwarded = (email or username or "").strip()
    if not forwarded:
        if not settings.mock:
            raise Unauthenticated("missing X-Forwarded-Email; is the app behind the Apps proxy?")
        forwarded = settings.dev_user
    if not _USER.fullmatch(forwarded):
        raise Unauthenticated("malformed forwarded identity header")
    user = forwarded
    if settings.allow_role_switch and role_header in ROLES:
        return Identity(user, role_header, "switch")
    override = settings.parsed_role_overrides().get(user.lower())
    if override:
        return Identity(user, override, "override")
    if token and groups is not None:
        names = {g.lower() for g in groups.groups(user, token)}
        if settings.manager_group.lower() in names:
            return Identity(user, "manager", "group")
        if settings.dispatcher_group.lower() in names:
            return Identity(user, "dispatcher", "group")
    return Identity(user, settings.default_role, "default")
