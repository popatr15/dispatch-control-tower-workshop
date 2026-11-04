from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..deps import Ctx, Who
from ..models import GenieAnswerOut, GenieAskIn, GenieFeedbackIn, OkOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/genie", tags=["genie"])


@router.post("/ask", response_model=GenieAnswerOut, operation_id="askGenie")
def ask(ctx: Ctx, who: Who, body: GenieAskIn):
    if ctx.genie is None:
        raise HTTPException(503, "Genie is not configured (GENIE_SPACE_ID)")
    if body.conversation_id:
        owned = ctx.store.list_genie_messages(who.user, body.conversation_id)
        if not owned:
            raise HTTPException(404, "conversation not found for this user")
    answer = ctx.genie.ask(body.question, body.conversation_id)
    with ctx.store.transaction() as tx:
        row = tx.insert_genie_message(
            who.user,
            answer.conversation_id,
            answer.message_id,
            body.question,
            answer.text,
            answer.sql,
        )
        tx.insert_audit(
            who.user,
            "genie.ask",
            "genie_message",
            answer.message_id,
            {"conversation_id": answer.conversation_id, "genie_message_id": row["id"]},
            None,
        )
    return GenieAnswerOut(question=body.question, created_at=row["created_at"], **answer.__dict__)


@router.get("/history", response_model=list[GenieAnswerOut], operation_id="listGenieHistory")
def history(ctx: Ctx, who: Who, conversation_id: str | None = None):
    return [
        GenieAnswerOut(
            conversation_id=r["conversation_id"],
            message_id=r["message_id"],
            question=r["question"],
            text=r["answer"],
            sql=r["sql"],
            created_at=r["created_at"],
        )
        for r in ctx.store.list_genie_messages(who.user, conversation_id)
    ]


@router.post("/feedback", response_model=OkOut, operation_id="sendGenieFeedback")
def feedback(ctx: Ctx, who: Who, body: GenieFeedbackIn):
    owned = ctx.store.list_genie_messages(who.user, body.conversation_id)
    if not any(r["message_id"] == body.message_id for r in owned):
        raise HTTPException(404, "message not found for this user")
    with ctx.store.transaction() as tx:
        tx.insert_genie_feedback(
            who.user, body.conversation_id, body.message_id, body.rating, body.comment
        )
        tx.insert_audit(
            who.user,
            "genie.feedback",
            "genie_message",
            body.message_id,
            {"conversation_id": body.conversation_id, "rating": body.rating},
            body.comment,
        )
    if ctx.genie is not None:
        try:
            ctx.genie.feedback(body.conversation_id, body.message_id, body.rating)
        except Exception:  # noqa: BLE001 - Lakebase copy is the source of truth
            log.warning("forwarding feedback to Genie failed")
    return OkOut()
