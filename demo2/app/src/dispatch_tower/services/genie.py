"""Genie Conversation API (SDK) and an offline stand-in."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

MAX_ROWS = 200


@dataclass
class GenieAnswer:
    conversation_id: str
    message_id: str
    text: str | None = None
    sql: str | None = None
    description: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    suggested_questions: list[str] = field(default_factory=list)


class GenieClient(Protocol):
    kind: str

    def ask(self, question: str, conversation_id: str | None) -> GenieAnswer: ...

    def feedback(self, conversation_id: str, message_id: str, rating: str) -> None: ...


class SdkGenie:
    kind = "genie"

    def __init__(self, ws: Any, space_id: str) -> None:
        self._ws = ws
        self._space = space_id

    def ask(self, question: str, conversation_id: str | None) -> GenieAnswer:
        if conversation_id:
            msg = self._ws.genie.create_message_and_wait(self._space, conversation_id, question)
        else:
            msg = self._ws.genie.start_conversation_and_wait(self._space, question)
        answer = GenieAnswer(
            conversation_id=msg.conversation_id, message_id=msg.message_id or msg.id
        )
        if msg.error and not msg.attachments:
            answer.text = f"Genie could not answer: {msg.error.error or msg.error}"
        for att in msg.attachments or []:
            if att.text and att.text.content:
                answer.text = (answer.text + "\n\n" if answer.text else "") + att.text.content
            if att.suggested_questions and att.suggested_questions.questions:
                answer.suggested_questions = list(att.suggested_questions.questions)
            if att.query and att.query.query:
                answer.sql = att.query.query
                answer.description = att.query.description
                result = self._ws.genie.get_message_attachment_query_result(
                    self._space, msg.conversation_id, answer.message_id, att.attachment_id
                )
                stmt = result.statement_response
                if stmt and stmt.manifest and stmt.manifest.schema:
                    answer.columns = [c.name for c in stmt.manifest.schema.columns or []]
                if stmt and stmt.result and stmt.result.data_array:
                    answer.rows = [list(r) for r in stmt.result.data_array[:MAX_ROWS]]
        return answer

    def feedback(self, conversation_id: str, message_id: str, rating: str) -> None:
        from databricks.sdk.service.dashboards import GenieFeedbackRating

        value = (
            GenieFeedbackRating.POSITIVE if rating == "positive" else (GenieFeedbackRating.NEGATIVE)
        )
        self._ws.genie.send_message_feedback(self._space, conversation_id, message_id, value)


class MockGenie:
    """Canned, deterministic answers so the chat panel works offline."""

    kind = "mock"

    def __init__(self, reader: Any) -> None:
        self._reader = reader

    def ask(self, question: str, conversation_id: str | None) -> GenieAnswer:
        conv = conversation_id or uuid.uuid4().hex
        msg = uuid.uuid4().hex
        q = question.lower()
        day = self._reader.route_dates()[0]
        stops = self._reader.stops(day)
        if "carrier" in q or "northeast" in q:
            counts: dict[str, int] = {}
            for s in stops:
                if s["status"] == "late" and s["region"] == "Northeast":
                    counts[s["carrier_id"]] = counts.get(s["carrier_id"], 0) + 1
            rows = sorted(([k, v] for k, v in counts.items()), key=lambda r: -r[1])
            return GenieAnswer(
                conv,
                msg,
                text="(mock) Late Northeast stops by carrier today.",
                sql="SELECT carrier_id, COUNT(*) AS late_stops FROM stops WHERE region = "
                "'Northeast' AND status = 'late' GROUP BY carrier_id ORDER BY 2 DESC",
                columns=["carrier_id", "late_stops"],
                rows=rows,
                suggested_questions=["What causes are most common for those late stops?"],
            )
        late: dict[str, int] = {}
        for s in stops:
            if s["status"] == "late":
                late[s["depot_id"]] = late.get(s["depot_id"], 0) + 1
        rows = sorted(([k, v] for k, v in late.items()), key=lambda r: -r[1])[:5]
        return GenieAnswer(
            conv,
            msg,
            text="(mock) Depots with the most late stops today.",
            sql="SELECT depot_id, COUNT(*) AS late_stops FROM stops WHERE status = 'late' "
            "GROUP BY depot_id ORDER BY 2 DESC LIMIT 5",
            columns=["depot_id", "late_stops"],
            rows=rows,
            suggested_questions=["Show late deliveries in the Northeast by carrier."],
        )

    def feedback(self, conversation_id: str, message_id: str, rating: str) -> None:
        return None
