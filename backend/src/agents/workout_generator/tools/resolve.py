from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic_ai import RunContext

from agents.workout_generator.deps import GeneratorDeps, ProvenanceEvent, ProvenanceKind
from resolver.core import resolve
from resolver.models import Namespace, ResolutionResult, ResolvedConcept

CONFIRM_CONFIDENCE = 0.85
"""Above this a match is returned as settled; below it the model is told to
judge. Distinct from the resolver's own acceptance thresholds."""


class AltConcept(BaseModel):
    """A runner-up the model may choose or offer to the coach."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    label: str
    confidence: float


class ResolveOutput(BaseModel):
    """What the LLM sees back. Docstrings and descriptions here are prompt
    real estate — they steer the model's next move as surely as the system
    prompt does."""

    model_config = ConfigDict(frozen=True)

    status: Literal["resolved", "ambiguous", "unresolved"]
    concept_id: str | None
    label: str | None
    confidence: float | None
    alternatives: tuple[AltConcept, ...]
    guidance: str
    """Tells the model what to do next."""


def _to_alts(result: ResolutionResult) -> tuple[AltConcept, ...]:
    return tuple(
        AltConcept(concept_id=a.concept_id, label=a.label, confidence=a.confidence)
        for a in result.alternatives
    )


def _log_resolution(deps: GeneratorDeps, term: str, namespace: Namespace,
                    result: ResolutionResult) -> None:
    """Record the resolution decision — SKOS mapping provenance, free."""
    resolved: ResolvedConcept | None = result.resolved
    deps.tool_log.append(
        ProvenanceEvent(
            kind=ProvenanceKind.CONCEPT_RESOLUTION,
            query=term,
            namespace=namespace,
            method=resolved.method if resolved else None,
            concept=resolved.concept_id if resolved else None,
            confidence=resolved.confidence if resolved else None,
            alternatives=tuple(a.concept_id for a in result.alternatives),
        )
    )


def resolve_concept(
    ctx: RunContext[GeneratorDeps],
    term: str,
    namespace: Namespace,
) -> ResolveOutput:
    """Map a free-text mention onto a canonical graph concept. Call once per
    extracted mention BEFORE using any other graph tool. Graph tools accept
    only concept_ids returned by this tool, never raw text."""
    result = resolve(term, namespace, ctx.deps.concept_index)
    _log_resolution(ctx.deps, term, namespace, result)

    if result.resolved and result.resolved.confidence >= CONFIRM_CONFIDENCE:
        return ResolveOutput(
            status="resolved",
            concept_id=result.resolved.concept_id,
            label=result.resolved.label,
            confidence=result.resolved.confidence,
            alternatives=(),
            guidance="Proceed with this concept_id.",
        )
    strong_tie = result.resolved is None and any(
        a.confidence >= CONFIRM_CONFIDENCE for a in result.alternatives
    )
    if result.resolved:  # Matched but shaky, or close alternatives exist.
        return ResolveOutput(
            status="ambiguous",
            concept_id=result.resolved.concept_id,
            label=result.resolved.label,
            confidence=result.resolved.confidence,
            alternatives=_to_alts(result),
            guidance="Low confidence. If alternatives differ materially for "
                     "safety (different joints/injuries), ask the coach to "
                     "confirm. Otherwise proceed with best match and flag it "
                     "in the plan rationale.",
        )
    if strong_tie:
        return ResolveOutput(
            status="ambiguous",
            concept_id=None,
            label=None,
            confidence=None,
            alternatives=_to_alts(result),
            guidance="Recognized, but it has multiple canonical readings and "
                     "no best match. Pick an alternative only if member "
                     "context clearly favors one, and flag the choice in the "
                     "plan rationale; otherwise ask the coach which was meant.",
        )
    return ResolveOutput(
        status="unresolved",
        concept_id=None,
        label=None,
        confidence=None,
        alternatives=_to_alts(result),
        guidance="No match above threshold. Tell the coach this term wasn't "
                 "recognized; offer the near-misses if any.",
    )
