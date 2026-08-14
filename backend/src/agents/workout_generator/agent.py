import time
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from agents.workout_generator.belt import toolset
from agents.workout_generator.deps import GeneratorDeps, ProvenanceEvent, ProvenanceKind
from catalog.cards import load_cards
from catalog.eligibility import EligibilityResult, Exclusion, apply
from constraints.compose import compose
from constraints.models import REQUIRING_EFFECTS
from resolver.models import Namespace
from safety.clinical import load_clinical
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

    caution_note: str = ""
    """Required non-empty when this exercise carries a clinical caution: one
    sentence saying how the prescription respects it (depth, load, volume).
    Must be empty otherwise. An acknowledgment, not a clearance."""


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
- get_eligible_exercises returns every exercise you may plan, judged
  against the member's chart and the declared constraints, with every
  exclusion and its cause.

Work like this:
1. Call member_snapshot first. Plan with the member's own equipment unless
   the coach names other equipment. Never plan a disliked exercise.
   Injuries on the chart activate a clinical envelope computed by
   deterministic code: exercises whose movement patterns a clinician
   contraindicated are blocked, and a plan using one is rejected with the
   evidence path. Cautioned exercises stay eligible, but each one you plan
   must carry a caution_note saying how the prescription respects the
   caution; leave caution_note empty on every other exercise. None of this
   is a clearance - never claim a plan is safe or cleared.
2. Extract every concrete mention from the request - exercises, muscles,
   equipment, body parts, movement patterns - and resolve each one before
   planning.
3. Declare the coach's directives with declare_constraints after resolving
   their targets. State the FULL set each call - anything omitted is
   dropped, and the diff will show the drop.
4. After declaring constraints, call get_eligible_exercises. Plan only
   with exercise concept_ids from its eligible cards or from
   resolve_concept results this run; never a retrieval-excluded id.
   Snapshot concept_ids are context, not citations. Re-call it after any
   re-declaration. resolve_concept remains the path for terms the coach
   names.
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
    retries={"tools": 2, "output": 4},
)


@generator.output_validator
def enforce_citations(ctx: RunContext[GeneratorDeps], plan: WorkoutPlan) -> WorkoutPlan:
    """Every concept id in the plan must have been returned by resolve_concept
    or get_eligible_exercises this run — the model cannot name an exercise it
    was never shown, and ids other tools surface as context never widen the
    plannable set.

    Raises:
        ModelRetry: If an id was never shown, or is not an exercise.
    """
    resolutions = [
        event for event in ctx.deps.tool_log
        if event.kind is ProvenanceKind.CONCEPT_RESOLUTION
    ]
    shown = {event.concept for event in resolutions if event.concept}
    shown |= {alt for event in resolutions for alt in event.alternatives}
    shown |= {
        candidate
        for event in ctx.deps.tool_log
        if event.kind is ProvenanceKind.CANDIDATE_RETRIEVAL
        for candidate in event.candidates
    }

    prefix = f"{Namespace.EXERCISE.value}:"
    unknown = [e.concept_id for e in plan.exercises if e.concept_id not in shown]
    wrong_kind = [
        e.concept_id
        for e in plan.exercises
        if e.concept_id not in unknown and not e.concept_id.startswith(prefix)
    ]
    problems: list[str] = []
    if unknown:
        problems.append(
            f"these concept_ids were never returned by resolve_concept or "
            f"get_eligible_exercises this run: {unknown}. Use only returned ids."
        )
    if wrong_kind:
        problems.append(
            f"these concept_ids are not exercises: {wrong_kind}. "
            f"Plan slots must use exercise concepts."
        )
    if problems:
        raise ModelRetry(" ".join(problems))
    return plan


def _safety_problems(plan: WorkoutPlan, result: EligibilityResult) -> list[str]:
    """The safety judgment over a finished plan, as retry feedback.

    Pure: the caller re-derives `result` from the graph; this only compares.
    The caution check verifies an acknowledgment exists, not that its
    content actually adapts anything — that limit is deliberate and stated.
    """
    exclusions_by_id: dict[str, list[Exclusion]] = {}
    for record in result.excluded:
        exclusions_by_id.setdefault(record.concept_id, []).append(record)
    cautions_by_id = {card.concept_id: card.cautions for card in result.eligible}

    problems: list[str] = []
    for slot in plan.exercises:
        for record in exclusions_by_id.get(slot.concept_id, []):
            evidence = f" [{record.evidence.render()}]" if record.evidence else ""
            problems.append(
                f"{slot.concept_id} is excluded ({record.cause.value} via "
                f"{record.matched_target}){evidence} {record.reason}".rstrip()
                + ". Replace this slot."
            )
        cautions = cautions_by_id.get(slot.concept_id, ())
        if cautions and not slot.caution_note:
            rendered = "; ".join(
                c.evidence.render() if c.evidence else c.matched_target for c in cautions
            )
            problems.append(
                f"{slot.concept_id} carries a clinical caution [{rendered}] but "
                f"no caution_note. Say in caution_note how the prescription "
                f"respects it - depth, load, or volume."
            )
        if not cautions and slot.caution_note:
            problems.append(
                f"{slot.concept_id} has a caution_note but carries no clinical "
                f"caution. Leave caution_note empty; commentary belongs in "
                f"rationale or coach_notes."
            )
    return problems


@generator.output_validator
def enforce_safety(ctx: RunContext[GeneratorDeps], plan: WorkoutPlan) -> WorkoutPlan:
    """The deterministic safety re-check over the final plan.

    Re-derives the judgment from the graph — clinical rules and catalog
    cards loaded fresh, composed with the declared set — trusting nothing
    the run mutated. Every exclusion cause is enforced here, and every
    cautioned slot must carry its acknowledgment.

    Raises:
        ModelRetry: If any slot is excluded, a cautioned slot lacks a
            caution_note, or a clean slot carries one.
    """
    clinical = load_clinical(ctx.deps.graph, ctx.deps.member_id)
    cards = load_cards(ctx.deps.graph, ctx.deps.member_id)
    result = apply(cards, compose(clinical, ctx.deps.declared_constraints))
    problems = _safety_problems(plan, result)
    if problems:
        raise ModelRetry(" ".join(problems))
    return plan


@generator.output_validator
def enforce_required_exercises(
    ctx: RunContext[GeneratorDeps], plan: WorkoutPlan
) -> WorkoutPlan:
    """Every declared exercise-level require appears in some section.

    Presence is not an exclusion, so enforce_safety does not cover it.

    Raises:
        ModelRetry: If a required exercise appears in no section.
    """
    planned = {e.concept_id for e in plan.exercises}
    prefix = f"{Namespace.EXERCISE.value}:"
    missing = [
        c
        for c in ctx.deps.declared_constraints.constraints
        if c.effect in REQUIRING_EFFECTS
        and c.target.startswith(prefix)
        and c.target not in planned
    ]
    if missing:
        raise ModelRetry(
            f"these declared require exercises appear in no section: "
            f"{[(c.target, c.reason) for c in missing]}. Add them, or if "
            f"impossible, re-declare without them and say why in coach_notes."
        )
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


class Usage(BaseModel):
    """What one run cost."""

    model_config = ConfigDict(frozen=True)

    llm_calls: int
    tokens_in: int
    tokens_out: int


class GenerationRun(BaseModel):
    """Everything one generation produced that a caller may persist."""

    model_config = ConfigDict(frozen=True)

    plan: WorkoutPlan
    messages_json: bytes
    """The full pydantic-ai message history, JSON — replayed on adjustment."""

    new_messages_json: bytes
    """This run's messages only — what the trace derives its LLM-turn spans
    from. An adjustment's full history would replay the parent's turns."""

    usage: Usage


async def generate(
    coach_prompt: str,
    deps: GeneratorDeps,
    message_history: Sequence[ModelMessage] | None = None,
) -> GenerationRun:
    """Run one generation end to end.

    Args:
        coach_prompt: The coach's request, verbatim.
        deps: The run's dependencies; its tool_log fills as the run proceeds.
        message_history: A prior run's conversation, for adjustments.

    Returns:
        The validated plan, the message history for the next turn, and usage.
    """
    deps.run_began = time.perf_counter()
    deps.clinical_constraints = load_clinical(deps.graph, deps.member_id)
    deps.tool_log.append(
        ProvenanceEvent(
            kind=ProvenanceKind.CLINICAL_ENVELOPE,
            started_ms=0.0,
            duration_ms=round((time.perf_counter() - deps.run_began) * 1000, 2),
            member=deps.member_id,
            constraint_set=deps.clinical_constraints,
        )
    )
    prompt = (
        f"Coach request: {coach_prompt}\n"
        f"Session window: {deps.duration_min} minutes."
    )
    result = await generator.run(
        prompt, deps=deps, model=build_model(), message_history=message_history
    )
    used = result.usage
    return GenerationRun(
        plan=result.output,
        messages_json=result.all_messages_json(),
        new_messages_json=result.new_messages_json(),
        usage=Usage(
            llm_calls=used.requests,
            tokens_in=used.input_tokens or 0,
            tokens_out=used.output_tokens or 0,
        ),
    )
