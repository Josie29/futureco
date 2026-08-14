from pydantic import BaseModel, ConfigDict
from pydantic_ai import RunContext

from agents.workout_generator.deps import GeneratorDeps, ProvenanceEvent, ProvenanceKind
from catalog.cards import load_cards
from catalog.eligibility import EligibleExercise, Exclusion, apply
from constraints.compose import compose


class EligibleOutput(BaseModel):
    """What the LLM sees back. Guidance is prompt real estate."""

    model_config = ConfigDict(frozen=True)

    eligible: tuple[EligibleExercise, ...]
    excluded: tuple[Exclusion, ...]
    unmatched_requires: tuple[str, ...]
    guidance: str


def get_eligible_exercises(ctx: RunContext[GeneratorDeps]) -> EligibleOutput:
    """Browse the whole catalog judged against this member and the declared
    constraints: every eligible exercise as a card, every exclusion with its
    cause. Eligible concept_ids are plannable as returned. Call after
    declare_constraints, and call again after any re-declaration."""
    cards = load_cards(ctx.deps.graph, ctx.deps.member_id)
    result = apply(
        cards, compose(ctx.deps.clinical_constraints, ctx.deps.declared_constraints)
    )
    ctx.deps.tool_log.append(
        ProvenanceEvent(
            kind=ProvenanceKind.CANDIDATE_RETRIEVAL,
            member=ctx.deps.member_id,
            candidates=tuple(c.concept_id for c in result.eligible),
            exclusions=result.excluded,
            unmatched_requires=result.unmatched_requires,
        )
    )

    guidance = (
        "Eligibility was computed by deterministic code from the clinical "
        "envelope, the declared constraints and the member's dislikes, and "
        "is enforced by validation - a plan using an excluded id is "
        "rejected. Blocked exclusions carry the clinical evidence path and "
        "are non-negotiable. Cautioned cards are eligible, but every one you "
        "plan must carry a caution_note saying how the prescription respects "
        "the caution. Eligible-and-uncautioned is still not a clearance "
        "claim. missing_equipment is relative to the member's own equipment "
        "- judge whether a substitute implement is acceptable and say so in "
        "the rationale. Re-call this tool after any re-declaration."
    )
    if result.unmatched_requires:
        guidance += (
            f" WARNING: no eligible exercise satisfies these declared require "
            f"targets: {list(result.unmatched_requires)}. The plan will be "
            f"rejected unless you re-declare without them (and explain in "
            f"coach_notes) or the coach's intent changes."
        )
    return EligibleOutput(
        eligible=result.eligible,
        excluded=result.excluded,
        unmatched_requires=result.unmatched_requires,
        guidance=guidance,
    )
