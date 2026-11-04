from __future__ import annotations

from fastapi import APIRouter

from ..db.schema import EXCEPTION_TYPES, REASSIGNMENT_REASONS, ROUTE_STATES
from ..deps import Ctx, Who
from ..models import FiltersOut, HealthOut, MeOut

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthOut, operation_id="health")
def health(ctx: Ctx) -> HealthOut:
    lakebase = ctx.store.kind
    ping = getattr(ctx.store, "ping", None)
    if ping:
        try:
            lakebase = "ok" if ping() else "error"
        except Exception:  # noqa: BLE001
            lakebase = "error"
    return HealthOut(
        status="ok", mock=ctx.settings.mock, lakebase=lakebase, warehouse=ctx.reader.kind
    )


@router.get("/me", response_model=MeOut, operation_id="getMe")
def me(ctx: Ctx, who: Who) -> MeOut:
    return MeOut(
        user=who.user,
        role=who.role,
        role_source=who.role_source,
        can_switch_role=ctx.settings.allow_role_switch,
        mock=ctx.settings.mock,
    )


@router.get("/filters", response_model=FiltersOut, operation_id="getFilters")
def filters(ctx: Ctx) -> FiltersOut:
    dates = ctx.reader.route_dates()
    depots = ctx.reader.depots()
    return FiltersOut(
        today=dates[0],
        dates=dates,
        depots=depots,
        carriers=ctx.reader.carriers(),
        regions=sorted({d["region"] for d in depots}),
        reason_codes=list(REASSIGNMENT_REASONS),
        exception_types=list(EXCEPTION_TYPES),
        route_states=list(ROUTE_STATES),
        max_map_points=ctx.settings.max_map_points,
    )
