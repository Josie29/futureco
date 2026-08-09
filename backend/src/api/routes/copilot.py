import time
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from api import members as read
from api.deps import GraphSession
from api.traces import RunTrace, RunTraceSummary, build_copilot_trace
from copilot.agent import answer, has_key
from copilot.answer import CopilotAnswer

router = APIRouter(tags=["copilot"])

CoachId = Annotated[str, Header(alias="X-Coach-Id")]

OPENING_QUESTION = "Show me the brief"
"""What the thread opens on.

`frontend-spec.md` cut the morning brief as a dashboard panel because
ASSESSMENT.md:71 assigns it to the copilot. Delivering it as the first answered
turn means retrieval has already run before the coach types anything — the
brief proves the graph on first paint rather than describing it."""


class CopilotRequest(BaseModel):
    """One question about the loaded member."""

    prompt: str = Field(min_length=1)


def _authorize(session: GraphSession, coach_id: str, member_id: str) -> None:
    """Refuse a member this coach does not coach.

    404 for both an unknown member and someone else's, for the reason
    `routes/members.py` gives: a 403 confirms the member exists.
    """
    if not read.coaches_member(session, coach_id, member_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No member {member_id} on your roster.",
        )


def _ask(request: Request, session: GraphSession, member_id: str, prompt: str) -> CopilotAnswer:
    """Answer one question and record the run.

    Tracing wraps the call rather than living inside it, so a failure to record
    a trace can never change the answer a coach gets.
    """
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    started_at = datetime.now(UTC)
    began = time.perf_counter()

    result = answer(session, member_id, prompt, f"cp_{uuid.uuid4().hex[:10]}")
    duration_ms = (time.perf_counter() - began) * 1000

    request.app.state.runtime.traces.record(
        build_copilot_trace(
            run_id=run_id,
            prompt=prompt,
            started_at=started_at,
            duration_ms=duration_ms,
            queries=result.queries,
            result=result,
        )
    )
    return result.answer


@router.get("/members/{member_id}/copilot", summary="The thread, opened on the brief")
def get_thread(
    request: Request, session: GraphSession, member_id: str, coach_id: CoachId
) -> list[CopilotAnswer]:
    """Open the copilot thread with the morning brief already answered.

    Args:
        request: The active request, carrying the trace store.
        session: An open Neo4j session.
        member_id: Whose record to read.
        coach_id: The signed-in coach.

    Returns:
        A single turn — the brief. A list rather than one object because the
        thread grows from here and the console renders it as one.

    Raises:
        HTTPException: 404 when the member is not on this coach's roster.
    """
    _authorize(session, coach_id, member_id)
    return [_ask(request, session, member_id, OPENING_QUESTION)]


@router.post("/members/{member_id}/copilot", summary="Ask about this member")
def ask(
    request: Request,
    session: GraphSession,
    member_id: str,
    body: CopilotRequest,
    coach_id: CoachId,
) -> CopilotAnswer:
    """Answer a coach's question, grounded in the member's graph.

    Every answer carries `degraded` when it is less than a full one — synthesis
    unavailable, a citation dropped, the model declined. A partial answer that
    looked whole would be the worst thing this surface could return.

    Args:
        request: The active request, carrying the trace store.
        session: An open Neo4j session.
        member_id: Whose record to read.
        body: The question.
        coach_id: The signed-in coach.

    Returns:
        The answer, with any chart assembled server-side and any citation
        checked against what retrieval actually returned.

    Raises:
        HTTPException: 404 when the member is not on this coach's roster.
    """
    _authorize(session, coach_id, member_id)
    return _ask(request, session, member_id, body.prompt)


@router.get("/copilot/health", summary="Which answer path this process will take")
def copilot_health() -> dict:
    """Whether a key is configured, so the console can say so before asking.

    Deliberately not a secret: it reports presence, never the key, and a coach
    seeing "retrieval only" up front beats discovering it in a banner.
    """
    return {"synthesis": has_key(), "path": "model" if has_key() else "retrieval"}


# Written and left unregistered. The traces surface belongs to the generator
# stream, which is the bigger span producer and should pick the durable store
# (docs/copilot-plan.md, D4). These exist so that work starts from a running
# store with a real producer rather than from an empty file.
traces_router = APIRouter(tags=["traces"])


@traces_router.get("/traces")
def list_traces(request: Request) -> list[RunTraceSummary]:
    """Every run this process still holds, newest first."""
    return request.app.state.runtime.traces.list()


@traces_router.get("/traces/{run_id}")
def get_trace(request: Request, run_id: str) -> RunTrace:
    """One run's span waterfall.

    Raises:
        HTTPException: 404 when the run is unknown or has aged out of the ring.
    """
    trace = request.app.state.runtime.traces.get(run_id)
    if trace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No run {run_id}")
    return trace
