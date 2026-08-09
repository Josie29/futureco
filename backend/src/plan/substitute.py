from neo4j import Session
from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel, RelType
from safety.evidence import EvidencePath, Hop, SignalKind
from safety.filter import FilterResult

from plan.families import deciding_pattern
from plan.queries import pattern_siblings
from plan.schemas import MovementFacts
from plan.why import Reason, ReasonKind

# Causes worth offering a stand-in for. A missing dumbbell or a coach's
# exclusion is a circumstance, and another movement of the same pattern does
# the same job. A contraindication is not a circumstance, and a dislike is the
# member's own standing preference — proposing around either would be
# answering a question nobody asked.
SUBSTITUTABLE: frozenset[SignalKind] = frozenset(
    {SignalKind.MISSING_EQUIPMENT, SignalKind.COACH_EXCLUSION}
)


class Substitution(BaseModel):
    """A dropped movement and the eligible one standing in for it.

    `replacement_id` is None when the catalog holds no eligible sibling. That
    is a real answer and the more common one here — saying so beats offering a
    movement that does a different job.
    """

    model_config = ConfigDict(frozen=True)

    dropped_id: str
    dropped_name: str
    cause: SignalKind
    shared_pattern: str | None = None
    replacement_id: str | None = None
    replacement_name: str | None = None

    @property
    def satisfied(self) -> bool:
        """Whether a stand-in was found."""
        return self.replacement_id is not None

    def reason(self) -> Reason:
        """The stand-in's own justification, for the block that carries it."""
        return Reason(
            kind=ReasonKind.SUBSTITUTION,
            detail=(
                f"stands in for {self.dropped_name}, which shares "
                f"{self.shared_pattern} and was dropped because it "
                f"{self.cause.value.replace('_', ' ')}"
            ),
            path=EvidencePath(
                entry=self.dropped_name,
                hops=(
                    Hop(
                        rel=RelType.IS_A,
                        to_label=NodeLabel.MOVEMENT_PATTERN,
                        to_name=self.shared_pattern or "",
                    ),
                    Hop(
                        rel=RelType.IS_A,
                        to_label=NodeLabel.EXERCISE,
                        to_name=self.replacement_name or "",
                    ),
                ),
            ),
        )


def substitutions(
    session: Session, result: FilterResult, facts: dict[str, MovementFacts]
) -> tuple[Substitution, ...]:
    """Offer a stand-in for each movement dropped by circumstance.

    Runs over a finished `FilterResult` rather than inside `filter.run`, which
    would break its contract that every one of the fifty rows gets exactly one
    verdict and its attribution arithmetic. A substitution is not a verdict; it
    is a relation between two of them.

    The safety property falls straight out of that:

        the siblings are intersected with `result.eligible`, so this can only
        ever propose a movement the filter has already cleared.

    Which is only available because `run` scores the whole catalog rather than
    filtering it. A contraindicated sibling is excluded, so it is not in
    `eligible`, so it is unreachable from here.

    A sibling must share the dropped movement's *deciding* pattern, not merely
    some pattern. Twenty-nine of the fifty exercises claim several, and
    matching on any of them lets a peripheral one drive the swap: *Med Ball
    Hamstring Walkout* and *High Plank Bird Dog* both resist rotation, so a
    hinge came back offered as a bird dog.

    Args:
        session: An open Neo4j session.
        result: Verdicts for the whole catalog.
        facts: Movement facts by exercise id, for the deciding pattern.

    Returns:
        One entry per substitutable removal, best stand-in first by the same
        rank the plan uses, and `replacement_id` None where none exists.
    """
    eligible = {verdict.exercise_id: verdict for verdict in result.eligible}
    found: list[Substitution] = []

    for verdict in result.verdicts:
        cause = verdict.attributed_to
        if cause not in SUBSTITUTABLE:
            continue

        movement = facts.get(verdict.exercise_id)
        defining = deciding_pattern(movement.patterns) if movement else None
        candidates = [
            (eligible[sibling_id], pattern)
            for sibling_id, _, pattern in pattern_siblings(session, verdict.exercise_id)
            if sibling_id in eligible and pattern == defining
        ]
        if not candidates:
            found.append(
                Substitution(
                    dropped_id=verdict.exercise_id, dropped_name=verdict.name, cause=cause
                )
            )
            continue

        best, pattern = min(candidates, key=lambda pair: (pair[0].sort_key, pair[1]))
        found.append(
            Substitution(
                dropped_id=verdict.exercise_id,
                dropped_name=verdict.name,
                cause=cause,
                shared_pattern=pattern,
                replacement_id=best.exercise_id,
                replacement_name=best.name,
            )
        )
    return tuple(found)
