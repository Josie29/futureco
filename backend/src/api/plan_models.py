from pydantic import BaseModel, ConfigDict, Field

from agents.workout_generator.agent import Usage, WorkoutPlan
from agents.workout_generator.deps import ProvenanceEvent, ProvenanceKind
from catalog.eligibility import Exclusion
from constraints.models import Constraint


class PlanRequest(BaseModel):
    """What the coach asks for."""

    prompt: str = Field(min_length=1)
    duration_min: int = Field(default=45, ge=15, le=240)


class ClinicalRule(BaseModel):
    """One chart-derived constraint, with its traversal rendered."""

    model_config = ConfigDict(frozen=True)

    target: str
    effect: str
    reason: str
    evidence: str


class ResolutionRecord(BaseModel):
    """One resolve_concept decision."""

    model_config = ConfigDict(frozen=True)

    query: str
    concept: str | None
    method: str | None
    confidence: float | None
    alternatives: tuple[str, ...]


class DeclaredConstraint(BaseModel):
    """One constraint as the coach declared it."""

    model_config = ConfigDict(frozen=True)

    target: str
    effect: str
    reason: str


class DeclarationRecord(BaseModel):
    """One declare_constraints call, as its diff."""

    model_config = ConfigDict(frozen=True)

    added: tuple[DeclaredConstraint, ...]
    removed: tuple[DeclaredConstraint, ...]
    unchanged: tuple[DeclaredConstraint, ...]
    rejected_targets: tuple[str, ...]


class ExclusionRecord(BaseModel):
    """One reason one exercise was not plannable."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    cause: str
    matched_target: str
    reason: str
    evidence: str | None


class RetrievalRecord(BaseModel):
    """The latest get_eligible_exercises outcome."""

    model_config = ConfigDict(frozen=True)

    eligible_count: int
    exclusions: tuple[ExclusionRecord, ...]
    unmatched_requires: tuple[str, ...]


class PlanProvenance(BaseModel):
    """Every decision behind the plan, projected from the run's tool log."""

    model_config = ConfigDict(frozen=True)

    clinical: tuple[ClinicalRule, ...]
    resolutions: tuple[ResolutionRecord, ...]
    declarations: tuple[DeclarationRecord, ...]
    retrieval: RetrievalRecord | None
    usage: Usage


class PlanResponse(BaseModel):
    """The wire contract for one generated or adjusted plan."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    parent_run_id: str | None
    member_id: str
    prompt: str
    duration_min: int
    plan: WorkoutPlan
    provenance: PlanProvenance


class EligibilityResponse(BaseModel):
    """How the catalog stands for this member before any coach directive."""

    model_config = ConfigDict(frozen=True)

    total: int
    eligible: int
    blocked: int
    cautioned: int
    disliked: int


def _declared(constraints: tuple[Constraint, ...]) -> tuple[DeclaredConstraint, ...]:
    return tuple(
        DeclaredConstraint(target=c.target, effect=c.effect.value, reason=c.reason)
        for c in constraints
    )


def _exclusions(records: tuple[Exclusion, ...]) -> tuple[ExclusionRecord, ...]:
    return tuple(
        ExclusionRecord(
            concept_id=x.concept_id,
            cause=x.cause.value,
            matched_target=x.matched_target,
            reason=x.reason,
            evidence=x.evidence.render() if x.evidence else None,
        )
        for x in records
    )


def build_provenance(tool_log: list[ProvenanceEvent], usage: Usage) -> PlanProvenance:
    """Project one run's tool log onto the wire shape.

    Args:
        tool_log: The run's provenance events, in order.
        usage: What the run cost.

    Returns:
        The typed provenance: clinical envelope, every resolution and
        declaration, and the latest retrieval outcome.
    """
    clinical: tuple[ClinicalRule, ...] = ()
    resolutions: list[ResolutionRecord] = []
    declarations: list[DeclarationRecord] = []
    retrieval: RetrievalRecord | None = None

    for event in tool_log:
        if event.kind is ProvenanceKind.CLINICAL_ENVELOPE and event.constraint_set:
            clinical = tuple(
                ClinicalRule(
                    target=c.target,
                    effect=c.effect.value,
                    reason=c.reason,
                    evidence=c.evidence.render() if c.evidence else "",
                )
                for c in event.constraint_set.constraints
            )
        elif event.kind is ProvenanceKind.CONCEPT_RESOLUTION:
            resolutions.append(
                ResolutionRecord(
                    query=event.query or "",
                    concept=event.concept,
                    method=event.method.value if event.method else None,
                    confidence=event.confidence,
                    alternatives=event.alternatives,
                )
            )
        elif event.kind is ProvenanceKind.CONSTRAINT_DECLARATION:
            diff = event.constraint_diff
            declarations.append(
                DeclarationRecord(
                    added=_declared(diff.added) if diff else (),
                    removed=_declared(diff.removed) if diff else (),
                    unchanged=_declared(diff.unchanged) if diff else (),
                    rejected_targets=event.rejected_targets,
                )
            )
        elif event.kind is ProvenanceKind.CANDIDATE_RETRIEVAL:
            retrieval = RetrievalRecord(
                eligible_count=len(event.candidates),
                exclusions=_exclusions(event.exclusions),
                unmatched_requires=event.unmatched_requires,
            )

    return PlanProvenance(
        clinical=clinical,
        resolutions=tuple(resolutions),
        declarations=tuple(declarations),
        retrieval=retrieval,
        usage=usage,
    )
