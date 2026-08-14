import asyncio
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic_ai import ModelMessagesTypeAdapter

from agents.workout_generator.agent import GenerationRun, generate
from agents.workout_generator.deps import GeneratorDeps
from api.authz import CoachId, authorize
from api.deps import GraphSession
from api.plan_models import (
    EligibilityResponse,
    PlanRequest,
    PlanResponse,
    build_exercise_facts,
    build_provenance,
)
from api.runs import PlanRun
from api.traces import build_generator_trace
from catalog.cards import load_cards
from catalog.eligibility import ExclusionCause, apply
from constraints.compose import compose
from constraints.models import ConstraintSet
from safety.clinical import load_clinical

router = APIRouter(tags=["plans"])


def _run(
    request: Request,
    session: GraphSession,
    member_id: str,
    body: PlanRequest,
    parent: PlanRun | None,
) -> PlanResponse:
    """One generation or adjustment: run, persist, trace, respond.

    The trace and run records happen after the work, so a failure to record
    can never change the plan a coach gets.
    """
    runtime = request.app.state.runtime
    deps = GeneratorDeps(
        member_id=member_id,
        duration_min=body.duration_min,
        graph=session,
        concept_index=runtime.concept_index,
    )
    history = None
    if parent is not None:
        deps.declared_constraints = parent.declared_constraints
        if parent.message_history:
            history = ModelMessagesTypeAdapter.validate_json(parent.message_history)

    started_at = datetime.now(UTC)
    began = time.perf_counter()
    result: GenerationRun = asyncio.run(generate(body.prompt, deps, history))
    duration_ms = (time.perf_counter() - began) * 1000

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    runtime.plan_runs.record(
        PlanRun(
            run_id=run_id,
            parent_run_id=parent.run_id if parent else None,
            member_id=member_id,
            prompt=body.prompt,
            duration_min=body.duration_min,
            declared_constraints=deps.declared_constraints,
            message_history=result.messages_json.decode(),
            plan=result.plan,
        )
    )
    runtime.traces.record(
        build_generator_trace(
            run_id,
            body.prompt,
            started_at,
            duration_ms,
            deps.tool_log,
            list(ModelMessagesTypeAdapter.validate_json(result.new_messages_json)),
            result.usage,
        )
    )
    eligibility = apply(
        load_cards(session, member_id),
        compose(load_clinical(session, member_id), deps.declared_constraints),
    )
    return PlanResponse(
        run_id=run_id,
        parent_run_id=parent.run_id if parent else None,
        member_id=member_id,
        prompt=body.prompt,
        duration_min=body.duration_min,
        plan=result.plan,
        provenance=build_provenance(deps.tool_log, result.usage),
        exercise_facts=build_exercise_facts(result.plan, eligibility),
    )


@router.post("/members/{member_id}/plans")
def create_plan(
    request: Request,
    session: GraphSession,
    member_id: str,
    body: PlanRequest,
    coach_id: CoachId,
) -> PlanResponse:
    """Generate a plan for one member from a coach's request."""
    authorize(session, coach_id, member_id)
    return _run(request, session, member_id, body, parent=None)


@router.post("/members/{member_id}/plans/{run_id}/adjust")
def adjust_plan(
    request: Request,
    session: GraphSession,
    member_id: str,
    run_id: str,
    body: PlanRequest,
    coach_id: CoachId,
) -> PlanResponse:
    """Refine an existing plan, continuing its conversation.

    Raises:
        HTTPException: 404 when the run is unknown, aged out, or belongs to
            another member.
    """
    authorize(session, coach_id, member_id)
    parent = request.app.state.runtime.plan_runs.get(run_id)
    if parent is None or parent.member_id != member_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Run {run_id} is unknown or aged out; generate a fresh plan.",
        )
    return _run(request, session, member_id, body, parent=parent)


@router.get("/members/{member_id}/eligibility")
def get_eligibility(
    session: GraphSession,
    member_id: str,
    coach_id: CoachId,
) -> EligibilityResponse:
    """How the catalog stands for this member before any coach directive."""
    authorize(session, coach_id, member_id)
    cards = load_cards(session, member_id)
    result = apply(cards, compose(load_clinical(session, member_id), ConstraintSet()))

    def distinct(cause: ExclusionCause) -> int:
        return len({x.concept_id for x in result.excluded if x.cause is cause})

    return EligibilityResponse(
        total=len(cards),
        eligible=len(result.eligible),
        blocked=distinct(ExclusionCause.BLOCKED),
        cautioned=len([c for c in result.eligible if c.cautions]),
        disliked=distinct(ExclusionCause.DISLIKED),
    )
