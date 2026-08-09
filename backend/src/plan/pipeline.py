from uuid import uuid4

from neo4j import Session
from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel
from resolve.resolver import Resolution, Resolver
from safety.constraints import Composition, compose
from safety.directives import Instruction, to_directives
from safety.filter import run
from safety.policy import Policy
from safety.standing import load_standing
from safety.trace import ProvenanceTrace, trace

from plan.pack import pack
from plan.queries import movement_facts
from plan.schemas import Block, WorkoutPlan
from plan.substitute import Substitution, substitutions

# A coach emphasising something means a muscle. Restricting the label is what
# stops "pecs" being resolved as an exercise name, the same reason
# `directives._LABELS` exists.
FOCUS_LABELS = frozenset({NodeLabel.MUSCLE})


class GeneratedPlan(BaseModel):
    """One session, and everything needed to defend it.

    Carries the filter's own `ProvenanceTrace` unchanged rather than a second
    account of the same run — `safety/trace.py` already records the PROV-O
    header, the graph fingerprint, the constraint fold and per-verdict
    evidence, which is what `ASSESSMENT.md:33` asks for.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    parent_run_id: str | None = None
    member_id: str
    requested_minutes: int
    plan: WorkoutPlan
    trace: ProvenanceTrace
    substitutions: tuple[Substitution, ...]
    focus: tuple[Resolution, ...] = ()
    """What each emphasis phrase resolved to, including the ones that did not
    — a request that changed nothing must not look like one that was applied."""

    @property
    def composition(self) -> Composition:
        """The constraint fold this plan was built from."""
        return self.trace.result.composition


def resolve_focus(resolver: Resolver, phrases: tuple[str, ...]) -> tuple[Resolution, ...]:
    """Resolve emphasis phrases onto muscles.

    Emphasis is deliberately not a `ConstraintKind`. All five of those narrow
    the catalog, and adding a sixth that widens it would put goal fit into the
    safety filter, which `decisions.md` promises it is subordinate to. It acts
    on the packer's tie-break instead.

    Args:
        resolver: The concept resolver, over the graph's vocabulary.
        phrases: What the coach asked to emphasise.

    Returns:
        One resolution per phrase, in order, resolved or not.
    """
    return tuple(resolver.resolve(phrase, FOCUS_LABELS) for phrase in phrases)


def _with_substitutions(
    blocks: tuple[Block, ...], offered: tuple[Substitution, ...]
) -> tuple[Block, ...]:
    """Tell each stand-in whose place it is taking.

    Attached after packing because a substitution is a relation between two
    verdicts, and only the packer knows which stand-ins made the session. A
    block that appears because something else was dropped is otherwise
    indistinguishable from one chosen on its own merits.
    """
    by_replacement: dict[str, list[Substitution]] = {}
    for substitution in offered:
        if substitution.satisfied:
            by_replacement.setdefault(substitution.replacement_id, []).append(substitution)

    return tuple(
        block.model_copy(
            update={
                "reasons": block.reasons
                + tuple(s.reason() for s in by_replacement.get(block.exercise_id, ()))
            }
        )
        if block.exercise_id in by_replacement
        else block
        for block in blocks
    )


def generate(
    session: Session,
    resolver: Resolver,
    member_id: str,
    minutes: int,
    instructions: tuple[Instruction, ...] = (),
    emphasis: tuple[str, ...] = (),
    policy: Policy | None = None,
    parent_run_id: str | None = None,
) -> GeneratedPlan:
    """Build a session for one member under one request.

    The whole deterministic half of the system, in order: read the chart,
    resolve this request's instructions, fold them together, judge the catalog,
    offer stand-ins for what circumstance removed, and pack what survives into
    the window. No language model is involved, and none can be — `filter.run`
    takes a `Composition`, so free text has no path to the traversal.

    Args:
        session: An open Neo4j session.
        resolver: The concept resolver, over the graph's vocabulary.
        member_id: Whose chart to build from.
        minutes: The requested session length.
        instructions: This request's structured instructions.
        emphasis: Muscles the request asked to emphasise, unresolved.
        policy: Weights to apply. Defaults to `Policy()`.
        parent_run_id: The run this one adjusts, when it adjusts one.

    Returns:
        The session, its provenance, and every stand-in offered.

    Raises:
        ValueError: If the member is not in the graph.
    """
    composition = compose(
        load_standing(session, member_id), to_directives(resolver, list(instructions))
    )
    result = run(session, composition, policy)
    facts = movement_facts(session, member_id)
    offered = substitutions(session, result, facts)

    focus = resolve_focus(resolver, emphasis)
    muscles = frozenset(r.match.name for r in focus if r.match)

    plan = pack(result, facts, minutes, muscles)
    plan = plan.model_copy(update={"blocks": _with_substitutions(plan.blocks, offered)})

    return GeneratedPlan(
        run_id=uuid4().hex,
        parent_run_id=parent_run_id,
        member_id=member_id,
        requested_minutes=minutes,
        plan=plan,
        trace=trace(session, result),
        substitutions=offered,
        focus=focus,
    )
