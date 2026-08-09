from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel, RelType
from safety.evidence import EvidencePath, Hop, Signal, SignalKind
from safety.policy import Verdict

from plan.families import deciding_pattern
from plan.schemas import FamilyRole, MovementFacts, Section

# What the exercise itself is called at the far end of a path that was walked
# towards it. Matches the convention `safety.filter._anatomy_signals` set: hops
# are forward-only, so a traversal that ends at this exercise names it rather
# than reversing the arrow.
THIS = "(this)"


class ReasonKind(StrEnum):
    """Why a movement is where it is, positive and negative together.

    The first six are `SignalKind` exactly, in its declaration order, so the
    two diff cleanly and a `Signal` widens into a `Reason` without a mapping
    table. The rest is positive evidence, which the filter has no reason to
    emit — it exists to remove things, so every clean exercise leaves it with
    nothing to say. Those are this module's to add.
    """

    CONTRAINDICATION = "contraindication"
    MISSING_EQUIPMENT = "missing_equipment"
    DISLIKE = "dislike"
    COACH_EXCLUSION = "coach_exclusion"
    CAUTION = "caution"
    FLAGGED_STRUCTURE = "flagged_structure"

    CLEARED = "cleared"
    GOAL_SERVICE = "goal_service"
    FOCUS_MATCH = "focus_match"
    EQUIPMENT_FIT = "equipment_fit"
    PATTERN_ROLE = "pattern_role"
    SUBSTITUTION = "substitution"


class Reason(BaseModel):
    """One piece of evidence about one programmed movement.

    Field-for-field a `Signal`, so a filter signal converts by widening its
    `kind`. Every `detail` is either authored text, a fact read from the graph,
    or a fixed connective — the rule `policy._headline` already follows, which
    is what leaves no room for a generated justification.
    """

    model_config = ConfigDict(frozen=True)

    kind: ReasonKind
    detail: str
    path: EvidencePath
    annotation: str | None = None

    @classmethod
    def of(cls, signal: Signal) -> "Reason":
        """Widen a filter signal into a reason, unchanged."""
        return cls.model_validate(signal.model_dump())


def _cleared(name: str) -> Reason:
    """The safety claim itself, for a movement nothing argued against.

    An absence cannot be a traversal, so the path is the exercise alone. It is
    still the most load-bearing line on the block: the coach is accountable for
    it, and leaving it implicit would make a cleared movement look unexamined
    rather than examined and cleared.
    """
    return Reason(
        kind=ReasonKind.CLEARED,
        detail="no contraindicated movement pattern reaches it",
        path=EvidencePath(entry=name),
    )


def _goal_service(facts: MovementFacts) -> list[Reason]:
    """One reason per goal this movement advances.

    Walked from the goal, so the arrows stay forward: the goal targets a
    muscle, and this exercise targets it too.
    """
    return [
        Reason(
            kind=ReasonKind.GOAL_SERVICE,
            detail=f"trains {service.muscle}, which '{service.goal}' targets",
            path=EvidencePath(
                entry=service.goal,
                hops=(
                    Hop(rel=RelType.TARGETS, to_label=NodeLabel.MUSCLE, to_name=service.muscle),
                    Hop(rel=RelType.TARGETS, to_label=NodeLabel.EXERCISE, to_name=THIS),
                ),
            ),
        )
        for service in facts.goals
    ]


def _equipment_fit(facts: MovementFacts, name: str) -> Reason:
    """That every piece of kit it needs is kit she has.

    Worth stating rather than implying. Equipment removes twenty-six of this
    member's thirty-three dropped exercises, so surviving it is a fact about
    the movement, and a bodyweight exercise surviving it trivially is a
    different fact worth telling apart.
    """
    if not facts.equipment:
        return Reason(
            kind=ReasonKind.EQUIPMENT_FIT,
            detail="needs no equipment",
            path=EvidencePath(entry=name),
        )
    return Reason(
        kind=ReasonKind.EQUIPMENT_FIT,
        detail=f"needs {', '.join(facts.equipment)}, which is available",
        path=EvidencePath(
            entry=name,
            hops=tuple(
                Hop(rel=RelType.REQUIRES, to_label=NodeLabel.EQUIPMENT, to_name=item)
                for item in facts.equipment
            ),
        ),
    )


_ROLE_DETAIL: dict[Section, str] = {
    Section.WARMUP: "a warm-up is built from mobility patterns",
    Section.MAIN: "the main block is built from loaded patterns",
    Section.COOLDOWN: "a cool-down is built from static and restorative patterns",
}


def _pattern_role(facts: MovementFacts, role: FamilyRole, name: str) -> Reason:
    """Why it sits in this block rather than another.

    The pattern that decided the section, not every pattern it claims — the
    others did not place it, and listing them would suggest they had.
    """
    deciding = deciding_pattern(facts.patterns) or name
    return Reason(
        kind=ReasonKind.PATTERN_ROLE,
        detail=f"{_ROLE_DETAIL[role.section]}, and this is {deciding}",
        path=EvidencePath(
            entry=name,
            hops=(
                Hop(
                    rel=RelType.IS_A,
                    to_label=NodeLabel.MOVEMENT_PATTERN,
                    to_name=deciding,
                ),
            ),
        ),
    )


def _focus_match(facts: MovementFacts, name: str, focus: frozenset[str]) -> list[Reason]:
    """Muscles the coach asked for that this movement actually trains."""
    return [
        Reason(
            kind=ReasonKind.FOCUS_MATCH,
            detail=f"trains {muscle}, which the request asked to emphasise",
            path=EvidencePath(
                entry=name,
                hops=(Hop(rel=RelType.TARGETS, to_label=NodeLabel.MUSCLE, to_name=muscle),),
            ),
        )
        for muscle in sorted(focus & set(facts.muscles))
    ]


def reasons_for(
    verdict: Verdict,
    facts: MovementFacts,
    role: FamilyRole,
    focus: frozenset[str] = frozenset(),
) -> tuple[Reason, ...]:
    """Everything there is to say about one programmed movement.

    The filter's own signals first, then the positive evidence it never had
    cause to produce. Never empty: an exercise with no signals, no goal overlap
    and no focus match still carries its clearance, its equipment fit and the
    pattern that placed it — which is exactly the case for the best-ranked
    movements, the ones a coach is most likely to ask about.

    Args:
        verdict: The filter's judgement, carrying any signals against it.
        facts: The catalog facts for this exercise.
        role: Where the family table placed it.
        focus: Muscles the request asked to emphasise.

    Returns:
        The reasons, safety first. Ordering for display is the console's job.
    """
    reasons = [Reason.of(signal) for signal in verdict.signals]
    if not (verdict.of(SignalKind.CONTRAINDICATION) or verdict.of(SignalKind.CAUTION)):
        reasons.append(_cleared(verdict.name))
    reasons += _goal_service(facts)
    reasons += _focus_match(facts, verdict.name, focus)
    reasons.append(_equipment_fit(facts, verdict.name))
    reasons.append(_pattern_role(facts, role, verdict.name))
    return tuple(reasons)
