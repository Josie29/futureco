from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from agents.workout_generator.belt import toolset
from agents.workout_generator.deps import GeneratorDeps, ProvenanceKind
from constraints.models import EXCLUDING_EFFECTS, REQUIRING_EFFECTS
from resolver.models import Namespace
from settings import settings


class PlannedExercise(BaseModel):
    """One slot in the plan."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    """An exercise concept_id returned by resolve_concept this run."""

    label: str
    sets: int = Field(ge=1)
    reps: str
    """A prescription the coach reads: "8-10", "30s", "5 per side"."""

    seconds: int = Field(ge=1)
    """Whole-session cost of this slot including its rest."""

    rationale: str
    """One sentence: why this exercise, for this request."""


class WorkoutPlan(BaseModel):
    """The agent's typed output."""

    model_config = ConfigDict(frozen=True)

    title: str
    total_seconds: int = Field(ge=1)
    warmup: list[PlannedExercise] = []
    main: list[PlannedExercise] = Field(min_length=1)
    cooldown: list[PlannedExercise] = []
    coach_notes: str = ""
    """Anything the coach must know: unresolved requests, substitutions,
    assumptions. Never silently drop part of the ask — say it here."""

    @property
    def exercises(self) -> list[PlannedExercise]:
        """Every slot, in session order."""
        return [*self.warmup, *self.main, *self.cooldown]


GENERATOR_SYSTEM = """\
You are a workout planning agent for a coach. Compose one workout plan for
one member from the coach's request and the session window given in the
user message.

Your graph tools:
- member_snapshot reads the member's chart: equipment, disliked exercises,
  injuries as recorded, goals, and recent training by movement pattern.
- resolve_concept maps one free-text term onto a canonical concept and is
  the sole source of plannable concept_ids.
- declare_constraints records the coach's directives (avoid, prefer,
  require) as the full set in force; the plan is validated against it.

Work like this:
1. Call member_snapshot first. Plan with the member's own equipment unless
   the coach names other equipment. Never plan a disliked exercise.
   Injuries are recorded facts, not verdicts: you have no safety tooling,
   so make no claim that a plan is safe or cleared - prefer work consistent
   with the injury notes, and say in coach_notes when an injury shaped a
   choice.
2. Extract every concrete mention from the request - exercises, muscles,
   equipment, body parts, movement patterns - and resolve each one before
   planning.
3. Declare the coach's directives with declare_constraints after resolving
   their targets. State the FULL set each call - anything omitted is
   dropped, and the diff will show the drop.
4. The plan may only contain exercise concept_ids that resolve_concept
   returned this run. Snapshot concept_ids are context, not citations. You
   do not know the catalog; discover it by proposing likely exercise names
   and resolving them. Unresolved results list near-misses that ARE real
   catalog names - resolve the promising ones.
5. Follow the guidance field on every tool result.
6. Per exercise, give sets, a reps prescription, a whole-slot cost in
   seconds including rest, and a one-sentence rationale.
7. Land the total within 15 percent of the session window.
8. If part of the request cannot be honored, say so in coach_notes rather
   than substituting silently.
"""


def build_model() -> AnthropicModel:
    """The run's model, keyed from settings — the process env is not consulted.

    Called at run time, never at import: constructing the provider demands a
    key, and importing this module must not.

    Raises:
        pydantic_ai.exceptions.UserError: If no API key is configured.
    """
    return AnthropicModel(
        settings.anthropic_model,
        provider=AnthropicProvider(api_key=settings.anthropic_api_key),
    )


generator = Agent(
    deps_type=GeneratorDeps,
    output_type=WorkoutPlan,
    instructions=GENERATOR_SYSTEM,
    toolsets=[toolset],
)


@generator.output_validator
def enforce_citations(ctx: RunContext[GeneratorDeps], plan: WorkoutPlan) -> WorkoutPlan:
    """Every concept id in the plan must have been returned by resolve_concept
    this run — the model cannot name an exercise it was never shown, and ids
    other tools surface as context never widen the plannable set.

    Raises:
        ModelRetry: If an id was never shown, or is not an exercise.
    """
    resolutions = [
        event for event in ctx.deps.tool_log
        if event.kind is ProvenanceKind.CONCEPT_RESOLUTION
    ]
    shown = {event.concept for event in resolutions if event.concept}
    shown |= {alt for event in resolutions for alt in event.alternatives}

    unknown = [e.concept_id for e in plan.exercises if e.concept_id not in shown]
    wrong_kind = [
        e.concept_id
        for e in plan.exercises
        if e.concept_id not in unknown and not e.concept_id.startswith("exercise:")
    ]
    problems = []
    if unknown:
        problems.append(
            f"these concept_ids were never returned by resolve_concept this run: "
            f"{unknown}. Resolve real catalog names and use only returned ids."
        )
    if wrong_kind:
        problems.append(
            f"these concept_ids are not exercises: {wrong_kind}. "
            f"Plan slots must use exercise concepts."
        )
    if problems:
        raise ModelRetry(" ".join(problems))
    return plan


@generator.output_validator
def enforce_declared_constraints(
    ctx: RunContext[GeneratorDeps], plan: WorkoutPlan
) -> WorkoutPlan:
    """Exercise-target directives are enforced here; broader targets (muscle,
    pattern, equipment, anatomy) are model-honored until the safety envelope
    can expand them through the graph.

    Raises:
        ModelRetry: If any section uses an avoided exercise, or a required
            exercise appears in no section.
    """
    planned = {e.concept_id for e in plan.exercises}
    prefix = f"{Namespace.EXERCISE.value}:"
    declared = [
        c for c in ctx.deps.declared_constraints.constraints
        if c.target.startswith(prefix)
    ]

    avoided = [c for c in declared if c.effect in EXCLUDING_EFFECTS and c.target in planned]
    missing = [
        c for c in declared if c.effect in REQUIRING_EFFECTS and c.target not in planned
    ]
    problems = []
    if avoided:
        problems.append(
            f"the plan uses exercises declared avoid: "
            f"{[(c.target, c.reason) for c in avoided]}. Replace these slots."
        )
    if missing:
        problems.append(
            f"these declared require exercises appear in no section: "
            f"{[(c.target, c.reason) for c in missing]}. Add them, or if "
            f"impossible, re-declare without them and say why in coach_notes."
        )
    if problems:
        raise ModelRetry(" ".join(problems))
    return plan


BUDGET_TOLERANCE = 0.15
"""How far the plan may land from the requested window, either side."""


@generator.output_validator
def enforce_time_budget(ctx: RunContext[GeneratorDeps], plan: WorkoutPlan) -> WorkoutPlan:
    """Slot seconds must sum to total_seconds and land near the window.

    Raises:
        ModelRetry: If the arithmetic is wrong or the total is outside the
            tolerance band around the requested window.
    """
    total = sum(e.seconds for e in plan.exercises)
    if total != plan.total_seconds:
        raise ModelRetry(
            f"total_seconds is {plan.total_seconds} but the slots sum to {total}. "
            f"Make them agree."
        )
    window = ctx.deps.duration_min * 60
    if abs(total - window) > window * BUDGET_TOLERANCE:
        raise ModelRetry(
            f"the plan costs {total} seconds but the session window is {window}; "
            f"land within {BUDGET_TOLERANCE:.0%} of it. Adjust sets or slots."
        )
    return plan


async def generate(coach_prompt: str, deps: GeneratorDeps) -> WorkoutPlan:
    """Run one generation end to end.

    Args:
        coach_prompt: The coach's request, verbatim.
        deps: The run's dependencies; its tool_log fills as the run proceeds.

    Returns:
        The validated plan.
    """
    prompt = (
        f"Coach request: {coach_prompt}\n"
        f"Session window: {deps.duration_min} minutes."
    )
    result = await generator.run(prompt, deps=deps, model=build_model())
    return result.output
