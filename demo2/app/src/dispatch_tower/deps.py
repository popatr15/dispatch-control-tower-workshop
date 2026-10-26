"""Shared request dependencies: the app context and the caller's identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from .config import Settings
from .db.store import Store
from .services.decisions import DecisionService
from .services.events import EventBus
from .services.genie import GenieClient
from .services.identity import GroupLookup, Identity, Unauthenticated, resolve_identity
from .services.warehouse import CachedReader


@dataclass
class AppContext:
    settings: Settings
    store: Store
    reader: CachedReader
    genie: GenieClient | None
    bus: EventBus
    decisions: DecisionService
    groups: GroupLookup | None


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


def get_identity(
    ctx: Ctx,
    email: Annotated[str | None, Header(alias="X-Forwarded-Email")] = None,
    username: Annotated[str | None, Header(alias="X-Forwarded-Preferred-Username")] = None,
    token: Annotated[str | None, Header(alias="X-Forwarded-Access-Token")] = None,
    role: Annotated[str | None, Header(alias="X-Dispatch-Role")] = None,
) -> Identity:
    try:
        return resolve_identity(
            ctx.settings,
            email=email,
            username=username,
            token=token,
            role_header=role,
            groups=ctx.groups,
        )
    except Unauthenticated as exc:
        raise HTTPException(401, str(exc)) from exc


Who = Annotated[Identity, Depends(get_identity)]
