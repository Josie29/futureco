from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from agents.workout_generator.agent import (
    PlannedExercise,
    WorkoutPlan,
    enforce_citations,
    enforce_time_budget,
)
from agents.workout_generator.deps import GeneratorDeps, ProvenanceEvent, ProvenanceKind


def deps_with_log(*concept_ids: str, alternatives: tuple[str, ...] = ()) -> GeneratorDeps:
    deps = GeneratorDeps(
        member_id="m1",
        duration_min=45,
        graph=None,  # type: ignore[arg-type]
        concept_index=None,  # type: ignore[arg-type]
    )
    for concept_id in concept_ids:
        deps.tool_log.append(
            ProvenanceEvent(kind=ProvenanceKind.CONCEPT_RESOLUTION, concept=concept_id)
        )
    if alternatives:
        deps.tool_log.append(
            ProvenanceEvent(kind=ProvenanceKind.CONCEPT_RESOLUTION, alternatives=alternatives)
        )
    return deps


def slot(concept_id: str, seconds: int = 600) -> PlannedExercise:
    return PlannedExercise(
        concept_id=concept_id, label="x", sets=3, reps="8-10", seconds=seconds, rationale="r"
    )


def plan(*main: PlannedExercise, warmup: tuple[PlannedExercise, ...] = ()) -> WorkoutPlan:
    total = sum(s.seconds for s in (*warmup, *main))
    return WorkoutPlan(title="t", total_seconds=total, warmup=list(warmup), main=list(main))


def test_citations_pass_for_ids_the_run_was_shown() -> None:
    """A plan built from resolved ids goes through untouched.

    If shown ids were rejected, no plan could ever validate and every run
    would exhaust its retries.
    """
    ctx = SimpleNamespace(deps=deps_with_log("exercise:Goblet Squat"))
    p = plan(slot("exercise:Goblet Squat"))
    assert enforce_citations(ctx, p) is p


def test_citations_reject_an_id_the_run_never_saw() -> None:
    """The model cannot smuggle in an exercise it was never shown.

    Without this, a hallucinated-but-real-looking concept_id would flow into
    a coach-facing plan with no tool result behind it.
    """
    ctx = SimpleNamespace(deps=deps_with_log("exercise:Goblet Squat"))
    with pytest.raises(ModelRetry, match="never returned"):
        enforce_citations(ctx, plan(slot("exercise:Invented Movement")))


def test_citations_accept_ids_shown_only_as_alternatives() -> None:
    """Near-misses the tool displayed are fair game for the plan.

    The catalog is discovered through unresolved alternatives; rejecting them
    would force a redundant second resolve of a name the run already has.
    """
    ctx = SimpleNamespace(
        deps=deps_with_log(alternatives=("exercise:Kettlebell Swing",))
    )
    p = plan(slot("exercise:Kettlebell Swing"))
    assert enforce_citations(ctx, p) is p


def test_citations_reject_a_non_exercise_concept() -> None:
    """A resolved muscle or equipment id cannot occupy an exercise slot.

    "chest" resolves fine as a muscle — putting muscle:chest in the plan
    would hand downstream graph tools the wrong node type.
    """
    ctx = SimpleNamespace(deps=deps_with_log("muscle:chest"))
    with pytest.raises(ModelRetry, match="not exercises"):
        enforce_citations(ctx, plan(slot("muscle:chest")))


def test_budget_rejects_arithmetic_that_does_not_add_up() -> None:
    """total_seconds must equal the sum of the slots.

    A plan whose header disagrees with its body reads as a different length
    than it runs.
    """
    ctx = SimpleNamespace(deps=deps_with_log())
    p = WorkoutPlan(title="t", total_seconds=9999, main=[slot("exercise:X")])
    with pytest.raises(ModelRetry, match="sum"):
        enforce_time_budget(ctx, p)


def test_budget_rejects_a_plan_far_over_the_window() -> None:
    """A plan more than 15% over the window bounces back with the numbers.

    This is what remains of pack.py: the model composes, arithmetic verifies.
    45 min window tolerates up to 3105s; 3200s must fail.
    """
    ctx = SimpleNamespace(deps=deps_with_log())
    p = plan(slot("exercise:X", seconds=1600), slot("exercise:Y", seconds=1600))
    with pytest.raises(ModelRetry, match="window"):
        enforce_time_budget(ctx, p)


def test_budget_rejects_a_plan_far_under_the_window() -> None:
    """A plan more than 15% under the window is a short session, not a plan.

    The coach asked for 45 minutes; 30 minutes of work is a different
    product delivered without a word.
    """
    ctx = SimpleNamespace(deps=deps_with_log())
    p = plan(slot("exercise:X", seconds=1800))
    with pytest.raises(ModelRetry, match="window"):
        enforce_time_budget(ctx, p)


def test_budget_passes_within_the_tolerance_band() -> None:
    """A consistent plan close to the window goes through untouched.

    42 of 45 requested minutes is inside the 15% band — bouncing it would
    force pointless precision on rest-time guesses.
    """
    ctx = SimpleNamespace(deps=deps_with_log())
    p = plan(slot("exercise:X", seconds=1260), slot("exercise:Y", seconds=1260))
    assert enforce_time_budget(ctx, p) is p


def test_validators_see_every_section() -> None:
    """A slot hiding in the warmup is checked like any other.

    If validators only walked main, an unshown id in the warmup would reach
    the coach unvetted.
    """
    ctx = SimpleNamespace(deps=deps_with_log("exercise:Goblet Squat"))
    p = plan(slot("exercise:Goblet Squat"), warmup=(slot("exercise:Never Shown"),))
    with pytest.raises(ModelRetry, match="never returned"):
        enforce_citations(ctx, p)
