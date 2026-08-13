from neo4j import Session
from pydantic import BaseModel, ConfigDict

from catalog.queries import CANDIDATES
from resolver.models import Namespace, make_concept_id


class GoalOverlap(BaseModel):
    """A member goal this exercise serves, and the muscle they share."""

    model_config = ConfigDict(frozen=True)

    goal_id: str
    text: str
    priority: int
    muscle: str


class ExerciseCard(BaseModel):
    """One catalog exercise, as facts. No verdicts — eligibility judges."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    """exercise:<name> — the plannable citation."""

    name: str
    patterns: tuple[str, ...]
    """movement_pattern:<name> ids, primary pattern first."""

    muscles: tuple[str, ...]
    equipment_required: tuple[str, ...]
    missing_equipment: tuple[str, ...]
    """Required minus the member's own — an annotation, never an exclusion."""

    joints: tuple[str, ...]
    is_reps: bool
    is_duration: bool
    estimated_rep_seconds: float
    is_bilateral: bool
    side: str | None
    supports_weight: bool
    disliked: bool
    goal_overlap: tuple[GoalOverlap, ...]

    @property
    def facet_ids(self) -> frozenset[str]:
        """Every concept id this card is made of — the expansion surface."""
        return frozenset(
            (self.concept_id, *self.patterns, *self.muscles,
             *self.equipment_required, *self.joints)
        )


def load_cards(session: Session, member_id: str) -> tuple[ExerciseCard, ...]:
    """Read the full catalog, annotated against one member.

    Args:
        session: An open Neo4j session onto the built graphs.
        member_id: The member equipment and dislikes are judged against.

    Returns:
        All catalog exercises, ordered by name, ids in concept-id currency.

    Raises:
        ValueError: If the member does not exist — an empty catalog would
            read as "nothing plannable" rather than "no such member".
    """
    rows = list(session.run(CANDIDATES, member_id=member_id))
    if not rows:
        raise ValueError(f"member {member_id!r} is not in the graph")
    return tuple(
        ExerciseCard(
            concept_id=make_concept_id(Namespace.EXERCISE, row["name"]),
            name=row["name"],
            patterns=tuple(
                make_concept_id(Namespace.MOVEMENT_PATTERN, p) for p in row["patterns"]
            ),
            muscles=tuple(make_concept_id(Namespace.MUSCLE, m) for m in row["muscles"]),
            equipment_required=tuple(
                make_concept_id(Namespace.EQUIPMENT, q) for q in row["equipment_required"]
            ),
            missing_equipment=tuple(
                make_concept_id(Namespace.EQUIPMENT, q) for q in row["missing_equipment"]
            ),
            joints=tuple(make_concept_id(Namespace.ANATOMY, j) for j in row["joints"]),
            is_reps=row["is_reps"],
            is_duration=row["is_duration"],
            estimated_rep_seconds=row["estimated_rep_seconds"],
            is_bilateral=row["is_bilateral"],
            side=row["side"],
            supports_weight=row["supports_weight"],
            disliked=row["disliked"],
            goal_overlap=tuple(
                GoalOverlap(
                    goal_id=g["id"],
                    text=g["text"],
                    priority=g["priority"],
                    muscle=make_concept_id(Namespace.MUSCLE, g["muscle"]),
                )
                for g in row["goal_rows"]
            ),
        )
        for row in rows
    )
