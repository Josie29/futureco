from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from catalog.cards import ExerciseCard
from constraints.models import (
    EXCLUDING_EFFECTS,
    REQUIRING_EFFECTS,
    ConstraintSet,
    Effect,
)
from graph.evidence import EvidencePath


class ExclusionCause(StrEnum):
    """Why an exercise is not eligible."""

    AVOIDED = "avoided"
    BLOCKED = "blocked"
    DISLIKED = "disliked"


CAUSE_BY_EFFECT: dict[Effect, ExclusionCause] = {
    Effect.AVOID: ExclusionCause.AVOIDED,
    Effect.BLOCK: ExclusionCause.BLOCKED,
}
"""Every excluding effect maps to a cause; a test pins the coverage."""


class Exclusion(BaseModel):
    """One reason one exercise is out. A card can carry several."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    cause: ExclusionCause
    matched_target: str
    """The constraint target that hit, or the card's own id for dislikes."""

    reason: str = ""
    """The constraint's reason verbatim; empty for dislikes."""

    evidence: EvidencePath | None = None
    """The traversal behind a clinical exclusion; None otherwise."""


class Caution(BaseModel):
    """A clinical caution touching an eligible exercise."""

    model_config = ConfigDict(frozen=True)

    matched_target: str
    reason: str
    evidence: EvidencePath | None = None


class EligibleExercise(ExerciseCard):
    """A card that survived, annotated with how the constraint set touches it."""

    preferred_because: tuple[str, ...] = ()
    required_because: tuple[str, ...] = ()
    cautions: tuple[Caution, ...] = ()
    """Clinical cautions on this exercise. Planning it requires a caution_note
    acknowledging each."""


class EligibilityResult(BaseModel):
    """Everything one eligibility pass decided."""

    model_config = ConfigDict(frozen=True)

    eligible: tuple[EligibleExercise, ...]
    excluded: tuple[Exclusion, ...]
    unmatched_requires: tuple[str, ...]
    """REQUIRE targets no eligible card carries — matched nothing, or their
    only carriers were excluded. The plan cannot satisfy these without a
    re-declaration."""


def apply(cards: tuple[ExerciseCard, ...], constraints: ConstraintSet) -> EligibilityResult:
    """Judge every card against the composed constraint set.

    Pure and deterministic. Exclusion is facet intersection with the
    excluding effects — one record per (constraint, hit), each keeping its
    own reason and evidence. Dislikes exclude unless an exact-exercise
    REQUIRE overrides; nothing overrides a BLOCK. Cautions never exclude;
    they annotate survivors.

    Args:
        cards: The catalog, member-annotated.
        constraints: The composed set (clinical + declared) in force.

    Returns:
        Eligible cards, every exclusion record, and the REQUIRE targets no
        eligible card can satisfy.
    """
    excluding = [c for c in constraints.constraints if c.effect in EXCLUDING_EFFECTS]
    cautioning = [c for c in constraints.constraints if c.effect is Effect.CAUTION]
    requiring = constraints.targets(*REQUIRING_EFFECTS)
    preferring = constraints.targets(Effect.PREFER)

    eligible: list[EligibleExercise] = []
    excluded: list[Exclusion] = []
    for card in cards:
        records = [
            Exclusion(
                concept_id=card.concept_id,
                cause=CAUSE_BY_EFFECT[constraint.effect],
                matched_target=constraint.target,
                reason=constraint.reason,
                evidence=constraint.evidence,
            )
            for constraint in excluding
            if constraint.target in card.facet_ids
        ]
        if card.disliked and card.concept_id not in requiring:
            records.append(
                Exclusion(
                    concept_id=card.concept_id,
                    cause=ExclusionCause.DISLIKED,
                    matched_target=card.concept_id,
                )
            )
        if records:
            excluded.extend(records)
            continue
        eligible.append(
            EligibleExercise(
                **card.model_dump(),
                preferred_because=tuple(sorted(card.facet_ids & preferring)),
                required_because=tuple(sorted(card.facet_ids & requiring)),
                cautions=tuple(
                    sorted(
                        (
                            Caution(
                                matched_target=constraint.target,
                                reason=constraint.reason,
                                evidence=constraint.evidence,
                            )
                            for constraint in cautioning
                            if constraint.target in card.facet_ids
                        ),
                        key=lambda c: c.matched_target,
                    )
                ),
            )
        )

    satisfied = frozenset(
        target for card in eligible for target in card.required_because
    )
    return EligibilityResult(
        eligible=tuple(eligible),
        excluded=tuple(
            sorted(excluded, key=lambda x: (x.concept_id, x.cause, x.matched_target))
        ),
        unmatched_requires=tuple(sorted(requiring - satisfied)),
    )
