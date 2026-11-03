"""Routes, stops and map layers (warehouse reads with Lakebase decisions applied)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from ..deps import Ctx, Who
from ..models import (
    DepotOut,
    HeatCellOut,
    HubOut,
    ImpactOut,
    ReassignIn,
    ReassignmentOut,
    RouteDetailOut,
    RouteOut,
    RoutePathOut,
    RouteStateIn,
    RouteStateOut,
    RouteSuggestionsOut,
    StopClusterOut,
    StopDetailOut,
    StopOut,
)
from ..services import effective, recommend

router = APIRouter(tags=["operations"])

SUGGESTION_RADIUS_KM = 60.0  # metro hubs are wide; stay within one hub's catchment


def _day(ctx, day: date | None) -> date:
    return day or ctx.reader.route_dates()[0]


def _effective_stops(ctx, day: date) -> list[dict]:
    stops = ctx.reader.stops(day)
    return effective.apply_overrides(stops, ctx.store.latest_reassignments())


def _routes(ctx, day: date) -> list[dict]:
    routes = effective.apply_route_state(ctx.reader.routes(day), ctx.store.list_route_state())
    return effective.route_rollups(
        routes,
        _effective_stops(ctx, day),
        ctx.store.list_exceptions(status="open"),
        ctx.store.list_approvals(status="pending"),
    )


@router.get("/depots", response_model=list[DepotOut], operation_id="listDepots")
def list_depots(ctx: Ctx):
    return ctx.reader.depots()


@router.get("/hubs", response_model=list[HubOut], operation_id="listHubs")
def list_hubs(ctx: Ctx, day: date | None = None):
    d = _day(ctx, day)
    routes = effective.apply_route_state(ctx.reader.routes(d), ctx.store.list_route_state())
    return recommend.hub_summaries(ctx.reader.depots(), routes, _effective_stops(ctx, d))


@router.get("/routes", response_model=list[RouteOut], operation_id="listRoutes")
def list_routes(
    ctx: Ctx,
    day: date | None = None,
    depot_id: str | None = None,
    carrier_id: str | None = None,
    region: str | None = None,
):
    rows = _routes(ctx, _day(ctx, day))
    if region:
        depots = {d["depot_id"] for d in ctx.reader.depots() if d["region"] == region}
        rows = [r for r in rows if r["depot_id"] in depots]
    return effective.filter_rows(rows, depot_id=depot_id, carrier_id=carrier_id)


@router.get("/routes/{route_id}", response_model=RouteDetailOut, operation_id="getRoute")
def get_route(ctx: Ctx, route_id: str, day: date | None = None):
    d = _day(ctx, day)
    route = next((r for r in _routes(ctx, d) if r["route_id"] == route_id), None)
    if route is None:
        raise HTTPException(404, f"route {route_id} not found")
    stops = sorted(
        effective.filter_rows(_effective_stops(ctx, d), route_id=route_id),
        key=lambda s: (s["original_route_id"] != route_id, s["sequence"]),
    )
    return RouteDetailOut(
        route=route,
        stops=stops,
        comments=ctx.store.list_comments("route", route_id),
        approvals=ctx.store.list_approvals(route_id=route_id),
    )


@router.get(
    "/routes/{route_id}/suggestions",
    response_model=RouteSuggestionsOut,
    operation_id="getRouteSuggestions",
)
def route_suggestions(ctx: Ctx, route_id: str, day: date | None = None):
    d = _day(ctx, day)
    routes = effective.apply_route_state(ctx.reader.routes(d), ctx.store.list_route_state())
    route = next((r for r in routes if r["route_id"] == route_id), None)
    if route is None:
        raise HTTPException(404, f"route {route_id} not found")
    return RouteSuggestionsOut(
        route_id=route_id,
        at_risk=(route.get("risk_score") or 0) >= recommend.AT_RISK_ROUTE_SCORE,
        at_risk_threshold=recommend.AT_RISK_ROUTE_SCORE,
        suggestions=recommend.suggest_reassigns(
            route_id,
            routes,
            _effective_stops(ctx, d),
            per_stop=1,
            max_stops=recommend.SUGGESTION_STOPS,
            max_distance_km=SUGGESTION_RADIUS_KM,
        ),
    )


@router.get("/routes/{route_id}/impact", response_model=ImpactOut, operation_id="getRouteImpact")
def route_impact(ctx: Ctx, route_id: str, day: date | None = None):
    """Before/after of the reassignments applied so far (heuristic projection)."""
    d = _day(ctx, day)
    routes = effective.apply_route_state(ctx.reader.routes(d), ctx.store.list_route_state())
    route = next((r for r in routes if r["route_id"] == route_id), None)
    if route is None:
        raise HTTPException(404, f"route {route_id} not found")
    depot = next((x for x in ctx.reader.depots() if x["depot_id"] == route["depot_id"]), None)
    return recommend.project_impact(
        route_id, routes, ctx.reader.stops(d), _effective_stops(ctx, d), depot
    )


@router.get("/stops", response_model=list[StopOut], operation_id="listStops")
def list_stops(
    ctx: Ctx,
    day: date | None = None,
    route_id: str | None = None,
    depot_id: str | None = None,
    carrier_id: str | None = None,
    region: str | None = None,
    status: str | None = None,
):
    rows = effective.filter_rows(
        _effective_stops(ctx, _day(ctx, day)),
        route_id=route_id,
        depot_id=depot_id,
        carrier_id=carrier_id,
        region=region,
        status=status,
    )
    return rows[: ctx.settings.max_map_points]


@router.get("/stops/{stop_id}", response_model=StopDetailOut, operation_id="getStop")
def get_stop(ctx: Ctx, stop_id: str, day: date | None = None):
    stop = ctx.decisions.find_stop(stop_id, day)
    route = next(
        (r for r in ctx.reader.routes(stop["route_date"]) if r["route_id"] == stop["route_id"]),
        None,
    )
    return StopDetailOut(
        stop=stop,
        route_risk_score=route["risk_score"] if route else None,
        reassignments=ctx.store.list_reassignments(stop_id),
        exceptions=ctx.store.list_exceptions(stop_id=stop_id),
        comments=ctx.store.list_comments("stop", stop_id),
    )


@router.post(
    "/stops/{stop_id}/reassign", response_model=ReassignmentOut, operation_id="reassignStop"
)
def reassign_stop(ctx: Ctx, who: Who, stop_id: str, body: ReassignIn):
    return ctx.decisions.reassign_stop(who, stop_id, body.to_route_id, body.reason_code, body.note)


@router.get("/route-state", response_model=list[RouteStateOut], operation_id="listRouteState")
def list_route_state(ctx: Ctx):
    return ctx.store.list_route_state()


@router.put("/routes/{route_id}/state", response_model=RouteStateOut, operation_id="setRouteState")
def set_route_state(ctx: Ctx, who: Who, route_id: str, body: RouteStateIn):
    return ctx.decisions.set_route_state(who, route_id, body.state, body.reason)


@router.get("/map/clusters", response_model=list[StopClusterOut], operation_id="getStopClusters")
def stop_clusters(
    ctx: Ctx,
    day: date | None = None,
    cell_deg: float = Query(default=0.1, gt=0.001, le=5.0),
    depot_id: str | None = None,
    carrier_id: str | None = None,
    region: str | None = None,
):
    rows = effective.filter_rows(
        _effective_stops(ctx, _day(ctx, day)),
        depot_id=depot_id,
        carrier_id=carrier_id,
        region=region,
    )
    return effective.cluster_stops(rows, cell_deg)


@router.get("/map/route-paths", response_model=list[RoutePathOut], operation_id="listRoutePaths")
def route_paths(
    ctx: Ctx, day: date | None = None, depot_id: str | None = None, carrier_id: str | None = None
):
    d = _day(ctx, day)
    routes = effective.filter_rows(ctx.reader.routes(d), depot_id=depot_id, carrier_id=carrier_id)
    return effective.build_paths(ctx.reader.route_paths(d), routes)


@router.get("/map/history-heat", response_model=list[HeatCellOut], operation_id="getHistoryHeat")
def history_heat(
    ctx: Ctx,
    day: date | None = None,
    days: int = Query(default=30, ge=1, le=90),
    depot_id: str | None = None,
    carrier_id: str | None = None,
    region: str | None = None,
):
    cells = ctx.reader.history_cells(_day(ctx, day), days)
    return effective.heat_cells(cells, depot_id=depot_id, carrier_id=carrier_id, region=region)
