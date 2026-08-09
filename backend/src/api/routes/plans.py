import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, status

from agent.extract import Extraction, Extractor
from agent.schemas import ExtractionResult
from api.deps import GraphSession
from api.plan_models import Eligibility, PlanPayload, PlanRequest
from api.plan_wire import eligibility, payload
from api.runs import PlanRun, accumulate
from api.traces import build_generator_trace
from graph.recording import RunRecorder
from plan.pipeline import generate
from safety.constraints import ConstraintKind, Op, compose
from safety.directives import Instruction, to_directives
from safety.filter import run
from safety.standing import load_standing

router = APIRouter(tags=["plans"])

# Constraint kinds a coach may switch off for one session. `INJURY` is absent
# by construction, not by check: `constraints._WAIVABLE` already refuses it,
# and leaving it out here means the request cannot even name it.
DISABLEABLE: dict[str, ConstraintKind] = {
    ConstraintKind.EQUIPMENT.value: ConstraintKind.EQUIPMENT,
    ConstraintKind.EXCLUDED_EXERCISE.value: ConstraintKind.EXCLUDED_EXERCISE,
    ConstraintKind.EXCLUDED_PATTERN.value: ConstraintKind.EXCLUDED_PATTERN,
    ConstraintKind.FLAGGED_STRUCTURE.value: ConstraintKind.FLAGGED_STRUCTURE,
}


def to_instructions(disabled: list[str]) -> tuple[Instruction, ...]:
    """Turn the builder's switched-off items into instructions.

    Each id is `kind:label`, the form `ConstraintItem.id` takes. Switching an
    item off removes that one constraint for this session, which is exactly
    `Op.REMOVE` — so the builder's per-item switches reach the filter through
    the same path a typed instruction does, and get the same refusals.

    Args:
        disabled: `ConstraintItem.id`s the coach switched off.

    Returns:
        One removal instruction per recognised id.

    Raises:
        HTTPException: 422 if an id names a constraint kind that cannot be
            switched off, which includes every injury.
    """
    instructions = []
    for item in disabled:
        kind, _, label = item.partition(":")
        if kind not in DISABLEABLE or not label:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{item!r} is not a constraint that can be switched off",
            )
        instructions.append(Instruction(op=Op.REMOVE, kind=DISABLEABLE[kind], phrase=label))
    return tuple(instructions)


def _extract(extractor: Extractor, prompt: str) -> Extraction:
    """Read the coach's sentence, if there is one.

    An empty prompt is a first-class request, not a degenerate one: the builder
    can submit switched-off constraints alone, and the CLI probe and the
    README's worked examples take exactly this path. Skipping the call also
    keeps a keyless deployment on the same code path rather than a fallback.
    """
    if not prompt.strip():
        return Extraction(result=ExtractionResult())
    return extractor.extract(prompt)


def _build(
    request: Request,
    session: GraphSession,
    member_id: str,
    body: PlanRequest,
    parent: PlanRun | None,
) -> PlanPayload:
    """Generate one session, record what it was asked for, and trace the run.

    The single path behind both endpoints. A fresh build is the case where
    there is no parent — not a different procedure — so an adjustment cannot
    drift from a build and the trace has one shape.

    Args:
        request: The active request, carrying the runtime and its stores.
        session: An open Neo4j session.
        member_id: Whose chart to build from.
        body: The prompt, the window, and any switched-off constraints.
        parent: The run being refined, or None.

    Returns:
        The session, its provenance and its dropped movements.

    Raises:
        HTTPException: 404 if the member is not in the graph; 422 if a
            `disabled` id names something that cannot be switched off.
    """
    runtime = request.app.state.runtime
    started_at = datetime.now(UTC)
    began = time.perf_counter()

    heard = _extract(runtime.extractor, body.prompt)
    # The switched-off items are this request's, never the parent's: they are
    # the builder's live state, and a coach who switched equipment back on
    # would otherwise keep refining against the version that was off.
    asked = to_instructions(body.disabled) + tuple(heard.result.instructions)
    instructions, emphasis = accumulate(parent, asked, tuple(heard.result.emphasis))

    recorder = RunRecorder()
    try:
        generated = generate(
            session,
            runtime.resolver,
            member_id,
            body.duration_min,
            instructions,
            emphasis,
            parent_run_id=parent.run_id if parent else None,
            recorder=recorder,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    duration_ms = (time.perf_counter() - began) * 1000

    runtime.plan_runs.record(
        PlanRun(
            run_id=generated.run_id,
            parent_run_id=generated.parent_run_id,
            member_id=member_id,
            prompt=body.prompt,
            duration_min=body.duration_min,
            instructions=instructions,
            emphasis=emphasis,
        )
    )
    # Tracing wraps the run rather than living inside it, so a store that is
    # down can never change the plan a coach gets — the same rule the copilot
    # route follows.
    runtime.traces.record(
        build_generator_trace(
            run_id=generated.run_id,
            prompt=body.prompt,
            started_at=started_at,
            duration_ms=duration_ms,
            recorder=recorder,
            extraction=heard,
            generated=generated,
        )
    )

    trail = [run.prompt for run in runtime.plan_runs.lineage(generated.run_id) if run.prompt]
    return payload(
        generated,
        body.prompt,
        _title(body.duration_min),
        "Today",
        unmapped=tuple(heard.result.unmapped),
        prompt_trail=tuple(trail),
    )


def _title(minutes: int) -> str:
    """Name the session from what was asked for, not from what it contains.

    Composing a title out of the movements would mean generating prose about a
    plan, which is the one thing this endpoint does not do.
    """
    return f"{minutes}-minute session"


@router.post(
    "/members/{member_id}/plans",
    summary="Generate a session",
    response_model=PlanPayload,
)
def create_plan(
    member_id: str, body: PlanRequest, session: GraphSession, request: Request
) -> PlanPayload:
    """Build a plan for one member under one request.

    A fresh run: nothing before it constrains it. The coach's sentence becomes
    `Instruction`s through one extraction call, and everything after that is
    Python and Cypher.

    Args:
        member_id: Whose chart to build from.
        body: The prompt, the window, and any switched-off constraints.
        session: An open Neo4j session.
        request: The active request, carrying the warmed resolver.

    Returns:
        The session, its provenance and its dropped movements.

    Raises:
        HTTPException: 404 if the member is not in the graph; 422 if a
            `disabled` id names something that cannot be switched off.
    """
    return _build(request, session, member_id, body, parent=None)


@router.post(
    "/members/{member_id}/plans/{run_id}/adjust",
    summary="Refine a session into a new run",
    response_model=PlanPayload,
)
def adjust_plan(
    member_id: str, run_id: str, body: PlanRequest, session: GraphSession, request: Request
) -> PlanPayload:
    """Refine an earlier session into a new one.

    An adjustment is a new run carrying a pointer to its parent, never a
    mutation: the trace a coach already acted on stays intact and auditable.

    It **composes onto** the parent rather than replacing it. The parent's
    accumulated `Instruction`s are loaded and this utterance's are appended, so
    *"only dumbbells"* followed by *"exclude lunges"* is a session with both —
    which is what a coach refining a plan means, and what this endpoint
    previously got wrong by rebuilding from the adjustment alone.

    Appending is the whole of the merge because `safety.constraints.compose`
    folds directives in sequence: the later utterance is the one that wins
    where the two conflict. What is *not* inherited is `disabled[]`, which is
    the builder's live state and belongs to this request.

    Args:
        member_id: Whose chart to build from.
        run_id: The run being refined, recorded as this one's parent.
        body: This utterance and the current builder state.
        session: An open Neo4j session.
        request: The active request, carrying the warmed resolver.

    Returns:
        A new session, with `parent_run_id` set and the full prompt trail.

    Raises:
        HTTPException: 404 if the member is not in the graph, or if the run
            being refined is unknown — a plan cannot be built on a request the
            server can no longer read, and silently treating it as a fresh
            build would drop constraints the coach never withdrew. 422 if a
            `disabled` id names something that cannot be switched off.
    """
    parent = request.app.state.runtime.plan_runs.get(run_id)
    if parent is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No run {run_id} to refine. Build a new plan instead.",
        )
    if parent.member_id != member_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Run {run_id} does not belong to {member_id}."
        )
    return _build(request, session, member_id, body, parent=parent)


@router.get(
    "/members/{member_id}/eligibility",
    summary="How many movements this member may do",
    response_model=Eligibility,
)
def get_eligibility(
    member_id: str,
    session: GraphSession,
    request: Request,
    disabled: list[str] = Query(default=[]),
) -> Eligibility:
    """Count the pool without building a session.

    The builder shows this live as a coach flips switches, so it runs the
    filter and stops — no packing, no substitution.

    Args:
        member_id: Whose chart to count against.
        session: An open Neo4j session.
        request: The active request, carrying the warmed resolver.
        disabled: `ConstraintItem.id`s the coach has switched off.

    Returns:
        The catalog total, how many survive, and what removed the rest.

    Raises:
        HTTPException: 404 if the member is not in the graph; 422 if a
            `disabled` id names something that cannot be switched off.
    """
    resolver = request.app.state.runtime.resolver
    try:
        standing = load_standing(session, member_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    directives = to_directives(resolver, list(to_instructions(disabled)))
    result = run(session, compose(standing, directives))
    return eligibility(result.attribution, len(result.verdicts))
