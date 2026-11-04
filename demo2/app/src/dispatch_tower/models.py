"""Pydantic API models (request bodies end in `In`, responses in `Out`)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["dispatcher", "manager"]
StopStatus = Literal["delivered", "on_time", "at_risk", "late"]
RouteStatus = Literal["planned", "in_progress", "delayed", "completed"]
ReasonCode = Literal["vehicle_down", "weather", "capacity", "customer_request", "sla_risk", "other"]
ExceptionType = Literal["customer_unavailable", "weather", "vehicle_down", "other"]
ExceptionStatus = Literal["open", "resolved"]
ApprovalStatus = Literal["pending", "approved", "rejected"]
EntityType = Literal["stop", "route"]


class MeOut(BaseModel):
    user: str
    role: Role
    role_source: str
    can_switch_role: bool
    mock: bool


class HealthOut(BaseModel):
    status: str
    mock: bool
    lakebase: str
    warehouse: str


class DepotOut(BaseModel):
    depot_id: str
    name: str
    city: str
    state: str
    region: str
    lat: float
    lon: float
    catchment_radius_km: float
    sla_target_pct: float


class CarrierOut(BaseModel):
    carrier_id: str
    name: str
    scac: str | None = None


class FiltersOut(BaseModel):
    today: date
    dates: list[date]
    depots: list[DepotOut]
    carriers: list[CarrierOut]
    regions: list[str]
    reason_codes: list[str]
    exception_types: list[str]
    route_states: list[str]
    max_map_points: int


class RouteOut(BaseModel):
    route_id: str
    route_date: date
    depot_id: str
    vehicle_id: str | None = None
    carrier_id: str | None = None
    driver_name: str | None = None
    planned_start_ts: datetime | None = None
    status: RouteStatus
    state_updated_by: str | None = None
    state_updated_at: datetime | None = None
    planned_stops: int
    capacity_stops: int | None = None
    effective_stops: int
    late_stops: int
    at_risk_stops: int
    risk_score: float
    risk_reason: str | None = None
    open_exceptions: int = 0
    pending_approvals: int = 0


class StopOut(BaseModel):
    stop_id: str
    route_id: str
    original_route_id: str
    reassigned: bool
    route_date: date
    sequence: int
    customer_name: str
    address: str | None = None
    city: str
    state: str
    region: str
    lat: float
    lon: float
    promised_window_start: datetime | None = None
    promised_window_end: datetime | None = None
    eta_ts: datetime | None = None
    actual_arrival_ts: datetime | None = None
    status: StopStatus
    carrier_id: str
    depot_id: str
    late_minutes: int = 0
    late_reason_code: str | None = None


class ReassignmentOut(BaseModel):
    id: int
    stop_id: str
    from_route_id: str | None
    to_route_id: str
    reason_code: str
    note: str | None
    created_by: str
    created_at: datetime


class ReassignIn(BaseModel):
    to_route_id: str = Field(min_length=1, max_length=64)
    reason_code: ReasonCode
    note: str | None = Field(default=None, max_length=1000)


class ExceptionOut(BaseModel):
    id: int
    stop_id: str
    route_id: str
    exception_type: str
    reason: str
    status: ExceptionStatus
    created_by: str
    created_at: datetime
    updated_at: datetime


class ExceptionIn(BaseModel):
    stop_id: str = Field(min_length=1, max_length=64)
    exception_type: ExceptionType
    reason: str = Field(min_length=3, max_length=1000)


class ExceptionPatchIn(BaseModel):
    status: ExceptionStatus
    reason: str | None = Field(default=None, max_length=1000)


class ApprovalOut(BaseModel):
    id: int
    route_id: str
    stop_id: str | None
    amount_usd: float
    justification: str
    status: ApprovalStatus
    requested_by: str
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_comment: str | None = None
    created_at: datetime


class ApprovalIn(BaseModel):
    route_id: str = Field(min_length=1, max_length=64)
    stop_id: str | None = Field(default=None, max_length=64)
    amount_usd: float = Field(gt=0)
    justification: str = Field(min_length=5, max_length=1000)


class ApprovalDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(min_length=1, max_length=1000)


class CommentOut(BaseModel):
    id: int
    entity_type: EntityType
    entity_id: str
    body: str
    created_by: str
    created_at: datetime


class CommentIn(BaseModel):
    entity_type: EntityType
    entity_id: str = Field(min_length=1, max_length=64)
    body: str = Field(min_length=1, max_length=2000)


class RouteStateOut(BaseModel):
    route_id: str
    state: RouteStatus
    updated_by: str
    updated_at: datetime


class RouteStateIn(BaseModel):
    state: RouteStatus
    reason: str | None = Field(default=None, max_length=500)


class AuditOut(BaseModel):
    id: int
    actor: str
    action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    reason: str | None
    created_at: datetime


class StopDetailOut(BaseModel):
    stop: StopOut
    route_risk_score: float | None = None
    reassignments: list[ReassignmentOut]
    exceptions: list[ExceptionOut]
    comments: list[CommentOut]


class RouteDetailOut(BaseModel):
    route: RouteOut
    stops: list[StopOut]
    comments: list[CommentOut]
    approvals: list[ApprovalOut]


class HubOut(DepotOut):
    routes: int
    at_risk_routes: int
    stops: int
    late_stops: int
    at_risk_stops: int
    on_time_pct: float | None = None
    health: Literal["red", "amber", "green"] = "green"


class SuggestionOut(BaseModel):
    stop_id: str
    stop_status: StopStatus
    customer_name: str | None = None
    sequence: int
    late_minutes: int = 0
    from_route_id: str
    from_risk_score: float
    to_route_id: str
    to_risk_score: float
    risk_delta: float
    distance_km: float
    spare_slots: int
    rank: int
    score: float
    reason: str


class RouteSuggestionsOut(BaseModel):
    route_id: str
    at_risk: bool
    at_risk_threshold: float
    suggestions: list[SuggestionOut]


class ImpactOut(BaseModel):
    route_id: str
    hub_id: str
    hub_name: str | None = None
    moved_stops: int
    projected_on_time: int
    route_late_before: int
    route_late_after: int
    route_at_risk_before: int
    route_at_risk_after: int
    route_risk_before: float
    route_risk_after: float
    hub_on_time_before: float | None = None
    hub_on_time_after: float | None = None
    sla_target_pct: float | None = None
    meets_sla_before: bool | None = None
    meets_sla_after: bool | None = None


class StopClusterOut(BaseModel):
    lat: float
    lon: float
    count: int
    late: int
    at_risk: int
    on_time: int
    delivered: int
    worst_status: StopStatus


class RoutePathOut(BaseModel):
    route_id: str
    depot_id: str
    risk_score: float
    path: list[tuple[float, float]]


class HeatCellOut(BaseModel):
    lat: float
    lon: float
    deliveries: int
    on_time: int
    on_time_pct: float


class GenieAskIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    conversation_id: str | None = None


class GenieAnswerOut(BaseModel):
    conversation_id: str
    message_id: str
    question: str
    text: str | None = None
    sql: str | None = None
    description: str | None = None
    columns: list[str] = []
    rows: list[list[Any]] = []
    suggested_questions: list[str] = []
    created_at: datetime | None = None


class GenieFeedbackIn(BaseModel):
    conversation_id: str
    message_id: str
    rating: Literal["positive", "negative"]
    comment: str | None = Field(default=None, max_length=1000)


class OkOut(BaseModel):
    ok: bool = True
