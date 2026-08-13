from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic_ai import RunContext

from agents.workout_generator.deps import GeneratorDeps, ProvenanceEvent, ProvenanceKind
from constraints.diff import ConstraintDiff, diff
from constraints.models import Constraint, ConstraintSet, Effect, Origin
from resolver.models import Namespace

_NAMESPACE_PREFIXES = tuple(f"{ns.value}:" for ns in Namespace)


class CoachConstraint(BaseModel):
    """One coach directive. Targets are concept_ids from resolve_concept or
    member_snapshot — never raw text. Origin is not declarable, and neither
    is clinical vocabulary: constraints from the chart cannot be declared,
    weakened, or removed."""

    model_config = ConfigDict(frozen=True)

    target: str
    """A concept_id (namespace:name) seen this run."""

    effect: Literal[Effect.AVOID, Effect.PREFER, Effect.REQUIRE]
    reason: str
    """The coach's words that motivated it, e.g. "coach said no overhead work"."""


class InvalidTarget(BaseModel):
    """A target the declaration cannot install, and what to do about it."""

    model_config = ConfigDict(frozen=True)

    target: str
    problem: str


class DeclareOutput(BaseModel):
    """What the LLM sees back. Guidance is prompt real estate."""

    model_config = ConfigDict(frozen=True)

    status: Literal["accepted", "rejected"]
    active: tuple[Constraint, ...]
    """The full set now in force. On rejection this is the previous set,
    unchanged — a rejected declaration changes nothing."""

    added: tuple[Constraint, ...]
    removed: tuple[Constraint, ...]
    unchanged: tuple[Constraint, ...]
    invalid: tuple[InvalidTarget, ...]
    guidance: str


def _invalid_targets(ctx: RunContext[GeneratorDeps],
                     constraints: list[CoachConstraint]) -> tuple[InvalidTarget, ...]:
    problems = []
    for constraint in constraints:
        if not constraint.target.startswith(_NAMESPACE_PREFIXES):
            problems.append(InvalidTarget(
                target=constraint.target,
                problem="not a concept_id — use the namespace:name id a tool "
                        "returned, not raw text",
            ))
        elif not ctx.deps.concept_index.has(constraint.target):
            problems.append(InvalidTarget(
                target=constraint.target,
                problem="no such concept in the catalog — resolve the term "
                        "first and use the returned id",
            ))
    return tuple(problems)


def declare_constraints(
    ctx: RunContext[GeneratorDeps],
    constraints: list[CoachConstraint],
) -> DeclareOutput:
    """Declare the coach's directives — avoid, prefer, require — as the FULL
    set currently in force. Idempotent: every call replaces the whole set, so
    re-state everything still in force; anything omitted is dropped, and the
    diff shows the drop. Call after resolving the coach's mentions; call
    again whenever the coach's intent changes."""
    invalid = _invalid_targets(ctx, constraints)
    if invalid:
        ctx.deps.tool_log.append(ProvenanceEvent(
            kind=ProvenanceKind.CONSTRAINT_DECLARATION,
            rejected_targets=tuple(i.target for i in invalid),
        ))
        return DeclareOutput(
            status="rejected",
            active=ctx.deps.declared_constraints.constraints,
            added=(),
            removed=(),
            unchanged=(),
            invalid=invalid,
            guidance="Nothing changed; the previously declared set stands. "
                     "Fix the listed targets and re-declare the FULL set.",
        )

    declared = ConstraintSet(constraints=tuple(
        Constraint(target=c.target, effect=c.effect, origin=Origin.COACH, reason=c.reason)
        for c in constraints
    ))
    changes = diff(ctx.deps.declared_constraints, declared)
    ctx.deps.declared_constraints = declared
    ctx.deps.tool_log.append(ProvenanceEvent(
        kind=ProvenanceKind.CONSTRAINT_DECLARATION,
        constraint_set=declared,
        constraint_diff=changes,
    ))

    guidance = (
        "This set is in force until your next declaration replaces it. "
        "Clinical constraints from the chart compose with it automatically "
        "and cannot be declared, weakened, or removed."
    )
    if any(not c.target.startswith(f"{Namespace.EXERCISE.value}:") for c in constraints):
        guidance += (
            " Broad targets (muscle, movement pattern, equipment, anatomy) "
            "exclude every matching exercise from get_eligible_exercises, and "
            "a plan using an excluded exercise is rejected - call "
            "get_eligible_exercises after this declaration."
        )
    return DeclareOutput(
        status="accepted",
        active=declared.constraints,
        added=changes.added,
        removed=changes.removed,
        unchanged=changes.unchanged,
        invalid=(),
        guidance=guidance,
    )
