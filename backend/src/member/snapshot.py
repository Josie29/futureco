from datetime import date

from neo4j import Session
from pydantic import BaseModel, ConfigDict

from member.queries import GOALS, PATTERN_HISTORY, STANDING
from resolver.models import Namespace, make_concept_id


class OwnedEquipment(BaseModel):
    """One piece of equipment the member has access to."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    name: str


class DislikedExercise(BaseModel):
    """An exercise the member has said they dislike."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    name: str


class InjuryFact(BaseModel):
    """One injury exactly as the chart records it — a fact, not a verdict."""

    model_config = ConfigDict(frozen=True)

    id: str
    """The graph node id (inj_...), not concept currency. Names the injury in
    provenance and seeds the future safety envelope."""

    region: str
    joint: str
    joint_concept_id: str
    side: str | None
    status: str
    severity: str
    since: date
    condition: str | None
    """Clinical condition name only — Condition is deliberately outside the
    concept-id currency."""

    notes: str
    """The chart's own words, verbatim."""


class GoalTarget(BaseModel):
    """A muscle a goal trains."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    name: str


class Goal(BaseModel):
    """One member goal, with what it targets or how it is measured."""

    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    priority: int
    target_date: date | None
    target_muscles: tuple[GoalTarget, ...]
    metric: str | None
    """For goals scored by a number rather than muscles."""


class PatternHistory(BaseModel):
    """How often a movement pattern has been trained, and how recently."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    name: str
    completed_sessions: int
    last_trained: date


class MemberSnapshot(BaseModel):
    """One member's chart, as the planning agent is allowed to see it.

    Facts only — no derived verdicts, no contraindication rules, and no
    wall-clock-relative figures (the dataset is anchored to a synthetic date;
    callers judge recency by comparing the dates). Everything that references
    a KG1 concept carries a concept_id in the resolver's namespace:name
    currency.
    """

    model_config = ConfigDict(frozen=True)

    member_id: str
    name: str
    age: int | None
    preferred_session_minutes: int | None
    training_days_per_week: int | None
    equipment: tuple[OwnedEquipment, ...]
    disliked_exercises: tuple[DislikedExercise, ...]
    injuries: tuple[InjuryFact, ...]
    goals: tuple[Goal, ...]
    pattern_history: tuple[PatternHistory, ...]


def load_snapshot(session: Session, member_id: str) -> MemberSnapshot:
    """Read one member's snapshot from the graph.

    Args:
        session: An open Neo4j session onto the built graphs.
        member_id: The member to read.

    Returns:
        The snapshot, with every KG1 reference in concept-id currency.

    Raises:
        ValueError: If the member does not exist. A silently empty snapshot
            would plan with no equipment limit and no injury context — the
            failure this refuses.
    """
    standing = session.run(STANDING, member_id=member_id).single()
    if standing is None:
        raise ValueError(f"member {member_id!r} is not in the graph")

    goals = [
        Goal(
            id=row["id"],
            text=row["text"],
            priority=row["priority"],
            target_date=row["target_date"],
            target_muscles=tuple(
                GoalTarget(concept_id=make_concept_id(Namespace.MUSCLE, name), name=name)
                for name in row["target_muscles"]
            ),
            metric=row["metric"],
        )
        for row in session.run(GOALS, member_id=member_id)
    ]
    history = [
        PatternHistory(
            concept_id=make_concept_id(Namespace.MOVEMENT_PATTERN, row["pattern"]),
            name=row["pattern"],
            completed_sessions=row["sessions"],
            last_trained=row["last_trained"],
        )
        for row in session.run(PATTERN_HISTORY, member_id=member_id)
    ]

    return MemberSnapshot(
        member_id=member_id,
        name=standing["name"],
        age=standing["age"],
        preferred_session_minutes=standing["preferred_session_minutes"],
        training_days_per_week=standing["training_days_per_week"],
        equipment=tuple(
            OwnedEquipment(concept_id=make_concept_id(Namespace.EQUIPMENT, name), name=name)
            for name in sorted(standing["equipment"])
        ),
        disliked_exercises=tuple(
            DislikedExercise(concept_id=make_concept_id(Namespace.EXERCISE, name), name=name)
            for name in sorted(standing["disliked"])
        ),
        injuries=tuple(
            InjuryFact(
                id=injury["id"],
                region=injury["region"],
                joint=injury["joint"],
                joint_concept_id=make_concept_id(Namespace.ANATOMY, injury["joint"]),
                side=injury["side"],
                status=injury["status"],
                severity=injury["severity"],
                since=injury["since"],
                condition=injury["condition"],
                notes=injury["notes"],
            )
            for injury in sorted(standing["injuries"], key=lambda i: i["id"])
        ),
        goals=tuple(goals),
        pattern_history=tuple(history),
    )
