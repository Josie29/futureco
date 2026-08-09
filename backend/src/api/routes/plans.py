from fastapi import APIRouter, HTTPException, Query, Request, status

from agent.schemas import ExtractionResult
from api.deps import GraphSession
from api.plan_models import Eligibility, PlanPayload, PlanRequest
from api.plan_wire import eligibility, payload
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


def _extract(extractor, prompt: str) -> ExtractionResult:  # noqa: ANN001
    """Read the coach's sentence, if there is one.

    An empty prompt is a first-class request, not a degenerate one: the builder
    can submit switched-off constraints alone, and the CLI probe and the
    README's worked examples take exactly this path. Skipping the call also
    keeps a keyless deployment on the same code path rather than a fallback.
    """
    if not prompt.strip():
        return ExtractionResult()
    return extractor.extract(prompt)


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

    The prompt is accepted and echoed but not yet interpreted — extraction is
    the only part of this system a language model touches, and it is not wired
    in. Everything the plan *is* comes from `disabled[]` and the member's
    chart, which is also why this endpoint works with no API key.

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
    runtime = request.app.state.runtime
    heard = _extract(runtime.extractor, body.prompt)

    try:
        generated = generate(
            session,
            runtime.resolver,
            member_id,
            body.duration_min,
            to_instructions(body.disabled) + tuple(heard.instructions),
            tuple(heard.emphasis),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return payload(
        generated,
        body.prompt,
        _title(body.duration_min),
        "Today",
        unmapped=tuple(heard.unmapped),
    )


@router.post(
    "/members/{member_id}/plans/{run_id}/adjust",
    summary="Refine a session into a new run",
    response_model=PlanPayload,
)
def adjust_plan(
    member_id: str, run_id: str, body: PlanRequest, session: GraphSession, request: Request
) -> PlanPayload:
    """Build a new session that supersedes an earlier one.

    An adjustment is a new run carrying a pointer to its parent, never a
    mutation: the trace a coach already acted on stays intact and auditable.
    That also means the request carries its own full state — the prompt, the
    window and the switched-off items — so nothing here has to recall what the
    parent asked for, and no run store is needed to refine a plan.

    Args:
        member_id: Whose chart to build from.
        run_id: The run being refined, recorded as this one's parent.
        body: The full request, not a delta.
        session: An open Neo4j session.
        request: The active request, carrying the warmed resolver.

    Returns:
        A new session, with `parent_run_id` set.

    Raises:
        HTTPException: 404 if the member is not in the graph; 422 if a
            `disabled` id names something that cannot be switched off.
    """
    runtime = request.app.state.runtime
    heard = _extract(runtime.extractor, body.prompt)

    try:
        generated = generate(
            session,
            runtime.resolver,
            member_id,
            body.duration_min,
            to_instructions(body.disabled) + tuple(heard.instructions),
            tuple(heard.emphasis),
            parent_run_id=run_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return payload(
        generated,
        body.prompt,
        _title(body.duration_min),
        "Today",
        unmapped=tuple(heard.unmapped),
    )


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
