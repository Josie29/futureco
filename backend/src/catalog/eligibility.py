from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from catalog.cards import ExerciseCard
from constraints.models import (
    EXCLUDING_EFFECTS,
    REQUIRING_EFFECTS,
    ConstraintSet,
    Effect,
)


class ExclusionCause(StrEnum):
    """Why an exercise is not eligible."""

    AVOIDED = "avoided"
    DISLIKED = "disliked"
    # The envelope adds BLOCKED; EXCLUDING_EFFECTS growing BLOCK feeds it.


class Exclusion(BaseModel):
    """One reason one exercise is out. A card can carry several."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    cause: ExclusionCause
    matched_target: str
    """The constraint target that hit, or the card's own id for dislikes."""

    reason: str = ""
    """The constraint's reason verbatim; empty for dislikes."""


class EligibleExercise(ExerciseCard):
    """A card that survived, annotated with why the declared set favors it."""

    preferred_because: tuple[str, ...] = ()
    required_because: tuple[str, ...] = ()
    # Envelope seam: cautions land here as an additive field.


class EligibilityResult(BaseModel):
    """Everything one eligibility pass decided."""

    model_config = ConfigDict(frozen=True)

    eligible: tuple[EligibleExercise, ...]
    excluded: tuple[Exclusion, ...]
    unmatched_requires: tuple[str, ...]
    """REQUIRE targets no eligible card carries — matched nothing, or their
    only carriers were excluded. The plan cannot satisfy these without a
    re-declaration."""


def apply(cards: tuple[ExerciseCard, ...], declared: ConstraintSet) -> EligibilityResult:
    """Judge every card against the declared constraint set.

    Pure and deterministic: exclusion by facet intersection with the
    excluding effects (the graph expansion, done through the card's own
    facts), dislike exclusion unless an exact-exercise REQUIRE overrides,
    one record per hit with no cause arbitration, and PREFER/REQUIRE
    annotations on survivors.

    Args:
        cards: The catalog, member-annotated.
        declared: The constraint set in force.

    Returns:
        Eligible cards, every exclusion record, and the REQUIRE targets no
        eligible card can satisfy.
    """
    excluding = declared.targets(*EXCLUDING_EFFECTS)
    requiring = declared.targets(*REQUIRING_EFFECTS)
    preferring = declared.targets(Effect.PREFER)
    reasons: dict[str, str] = {}
    for constraint in declared.constraints:
        if constraint.effect in EXCLUDING_EFFECTS:
            existing = reasons.get(constraint.target)
            reasons[constraint.target] = (
                f"{existing}; {constraint.reason}" if existing else constraint.reason
            )

    eligible: list[EligibleExercise] = []
    excluded: list[Exclusion] = []
    for card in cards:
        records = [
            Exclusion(
                concept_id=card.concept_id,
                cause=ExclusionCause.AVOIDED,
                matched_target=target,
                reason=reasons[target],
            )
            for target in sorted(card.facet_ids & excluding)
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
