"""Exceptions, approvals, comments and the audit trail (Lakebase)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from ..deps import Ctx, Who
from ..models import (
    ApprovalDecisionIn,
    ApprovalIn,
    ApprovalOut,
    AuditOut,
    CommentIn,
    CommentOut,
    ExceptionIn,
    ExceptionOut,
    ExceptionPatchIn,
)
from ..services.rules import require

router = APIRouter(tags=["workflow"])


@router.get("/exceptions", response_model=list[ExceptionOut], operation_id="listExceptions")
def list_exceptions(ctx: Ctx, status: str | None = None, route_id: str | None = None):
    return ctx.store.list_exceptions(status=status, route_id=route_id)


@router.post("/exceptions", response_model=ExceptionOut, operation_id="createException")
def create_exception(ctx: Ctx, who: Who, body: ExceptionIn):
    return ctx.decisions.create_exception(who, body.stop_id, body.exception_type, body.reason)


@router.patch(
    "/exceptions/{exception_id}", response_model=ExceptionOut, operation_id="updateException"
)
def update_exception(ctx: Ctx, who: Who, exception_id: int, body: ExceptionPatchIn):
    return ctx.decisions.update_exception(who, exception_id, body.status, body.reason)


@router.get("/approvals", response_model=list[ApprovalOut], operation_id="listApprovals")
def list_approvals(ctx: Ctx, status: str | None = None, route_id: str | None = None):
    return ctx.store.list_approvals(status=status, route_id=route_id)


@router.post("/approvals", response_model=ApprovalOut, operation_id="requestApproval")
def request_approval(ctx: Ctx, who: Who, body: ApprovalIn):
    return ctx.decisions.request_approval(
        who, body.route_id, body.stop_id, body.amount_usd, body.justification
    )


@router.post(
    "/approvals/{approval_id}/decision", response_model=ApprovalOut, operation_id="decideApproval"
)
def decide_approval(ctx: Ctx, who: Who, approval_id: int, body: ApprovalDecisionIn):
    return ctx.decisions.decide_approval(who, approval_id, body.decision, body.comment)


@router.get("/comments", response_model=list[CommentOut], operation_id="listComments")
def list_comments(ctx: Ctx, entity_type: str, entity_id: str):
    return ctx.store.list_comments(entity_type, entity_id)


@router.post("/comments", response_model=CommentOut, operation_id="createComment")
def create_comment(ctx: Ctx, who: Who, body: CommentIn):
    return ctx.decisions.add_comment(who, body.entity_type, body.entity_id, body.body)


@router.get("/audit", response_model=list[AuditOut], operation_id="listAudit")
def list_audit(
    ctx: Ctx,
    who: Who,
    actor: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    since: datetime | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
):
    require(who, "audit.read")
    return ctx.store.list_audit(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        since=since,
        limit=limit,
    )
