from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent, RunContext

from agents.workout_generator.belt import toolset
from agents.workout_generator.deps import GeneratorDeps
from settings import settings


class WorkoutPlan(BaseModel):
    """The agent's typed output. Placeholder shape.

    To be respecified before the composition phase: slots with per-slot
    model-authored rationale citing tool-result ids, section structure, and
    the caution flags the safety validator requires. The pre-migration domain
    model (main: backend/src/plan/schemas.py) is the reference, not the spec.
    """

    model_config = ConfigDict(frozen=True)

    member_id: str
    duration_min: int


# Byte-stable on purpose — no f-strings, nothing per-request — so the cached
# prompt prefix survives across runs. Anything member- or run-specific belongs
# in deps and reaches the model through tool results, not through this string.
GENERATOR_SYSTEM = """\
You are a workout planning agent for a coach. Placeholder — the real prompt
lands with the first end-to-end run. It will cover: resolve every mention
before touching other graph tools; compose only from returned candidates;
cautions need an explicit coach-facing flag; cite tool results in rationale.
"""


MODEL = f"anthropic:{settings.anthropic_model}"
"""Passed at run time — `generator.run(..., model=MODEL)` — never bound at
construction: the Anthropic provider demands an API key the moment a model is
attached, and importing this module must not require one. Keyless behaviour
(replay, degraded mode) is the runner's decision, made where the key check
belongs."""


generator = Agent(
    deps_type=GeneratorDeps,
    output_type=WorkoutPlan,
    instructions=GENERATOR_SYSTEM,
    toolsets=[toolset],
)


@generator.output_validator
def enforce_safety(ctx: RunContext[GeneratorDeps], plan: WorkoutPlan) -> WorkoutPlan:
    """Deterministic safety re-filter over the final plan.

    Any blocked exercise fails the run with its evidence path via ModelRetry,
    regardless of the model's rationale; a caution without an explicit coach
    flag fails too. Lands with the rebuilt safety package.

    Raises:
        NotImplementedError: Scaffolding; not implemented yet.
    """
    raise NotImplementedError


@generator.output_validator
def enforce_time_budget(ctx: RunContext[GeneratorDeps], plan: WorkoutPlan) -> WorkoutPlan:
    """Sets x rest x transitions must fit the requested window — arithmetic,
    not search. What remains of pack.py.

    Raises:
        NotImplementedError: Scaffolding; not implemented yet.
    """
    raise NotImplementedError


@generator.output_validator
def enforce_citations(ctx: RunContext[GeneratorDeps], plan: WorkoutPlan) -> WorkoutPlan:
    """Every concept id in the plan must have been returned by a tool call
    this run — the allowlist check. The model cannot name an exercise it was
    never shown, even a real one.

    Raises:
        NotImplementedError: Scaffolding; not implemented yet.
    """
    raise NotImplementedError
