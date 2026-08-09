import json
from datetime import UTC
from pathlib import Path

from neo4j import Session
from pydantic import BaseModel, ConfigDict

from graph.build.member import (
    ChatMessage,
    MemberContext,
    WorkoutSession,
    load_member_context,
    reference_date,
)
from graph.build.metrics import (
    MetricDefinition,
    Observation,
    check_against,
    load_metrics,
    observations,
)
from graph.build.writes import EdgeWrite, NodeMatch, link_nodes, link_required, merge_nodes
from graph.schema import GraphSource, NodeLabel, RelType
from resolve.mentions import scan
from resolve.vocabulary import Vocabulary
from settings import settings

_MEMBER = NodeMatch(label=NodeLabel.MEMBER, key="id")
_GOAL = NodeMatch(label=NodeLabel.GOAL, key="id")
_SESSION = NodeMatch(label=NodeLabel.SESSION, key="id")
_MESSAGE = NodeMatch(label=NodeLabel.MESSAGE, key="id")
_OBSERVATION = NodeMatch(label=NodeLabel.OBSERVATION, key="id")
_METRIC = NodeMatch(label=NodeLabel.METRIC, key="id")

# `has` is one edge type reaching five labels: the target's label already says
# what the relation means, so a `has_goal` / `has_session` prefix would only
# restate it. See docs/decisions.md, KG2 decision 1.
_HAS_GOAL = EdgeWrite(rel=RelType.HAS, source=_MEMBER, target=_GOAL)
_HAS_EQUIPMENT = EdgeWrite(
    rel=RelType.HAS, source=_MEMBER, target=NodeMatch(label=NodeLabel.EQUIPMENT)
)
_HAS_INJURY = EdgeWrite(
    rel=RelType.HAS, source=_MEMBER, target=NodeMatch(label=NodeLabel.INJURY, key="id")
)
_HAS_SESSION = EdgeWrite(rel=RelType.HAS, source=_MEMBER, target=_SESSION)
_HAS_MESSAGE = EdgeWrite(rel=RelType.HAS, source=_MEMBER, target=_MESSAGE)
_HAS_OBSERVATION = EdgeWrite(rel=RelType.HAS, source=_MEMBER, target=_OBSERVATION)

# These four carry meaning ownership does not, which is the exception that
# already justifies `dislikes` and `targets`.
_TARGETS = EdgeWrite(
    rel=RelType.TARGETS, source=_GOAL, target=NodeMatch(label=NodeLabel.MUSCLE)
)
_DISLIKES = EdgeWrite(
    rel=RelType.DISLIKES, source=_MEMBER, target=NodeMatch(label=NodeLabel.EXERCISE)
)
_COACHES = EdgeWrite(
    rel=RelType.COACHES, source=NodeMatch(label=NodeLabel.COACH, key="id"), target=_MEMBER
)
_TRAINED = EdgeWrite(
    rel=RelType.TRAINED,
    source=_SESSION,
    target=NodeMatch(label=NodeLabel.MOVEMENT_PATTERN),
    properties=("movement",),
)
_MEASURES = EdgeWrite(rel=RelType.MEASURES, source=_OBSERVATION, target=_METRIC)
_MEASURED_BY = EdgeWrite(rel=RelType.MEASURED_BY, source=_GOAL, target=_METRIC)

# `mentions` reaches whichever label the member's words landed on, so it needs
# one writer per target label rather than one for the type.
_MENTIONS: dict[NodeLabel, EdgeWrite] = {
    label: EdgeWrite(
        rel=RelType.MENTIONS,
        source=_MESSAGE,
        target=NodeMatch(label=label),
        properties=("surface", "matched_by"),
    )
    for label in (
        NodeLabel.EXERCISE,
        NodeLabel.EQUIPMENT,
        NodeLabel.MUSCLE,
        NodeLabel.MOVEMENT_PATTERN,
        NodeLabel.ANATOMICAL_STRUCTURE,
    )
}

_NEW_LABELS = (
    NodeLabel.MEMBER,
    NodeLabel.GOAL,
    NodeLabel.COACH,
    NodeLabel.SESSION,
    NodeLabel.MESSAGE,
    NodeLabel.OBSERVATION,
    NodeLabel.METRIC,
)

# `dislikes` is the only key of `preferences` that becomes edges. The rest —
# session length, training days, preferred days, free-text notes — are scalar
# facts with no edge to carry, so they land as `Member` properties instead.
_MEMBER_PREFERENCE_FIELDS = (
    "preferred_session_minutes",
    "training_days_per_week",
    "preferred_days",
    "notes",
)


class SessionPatterns(BaseModel):
    """One coach shorthand movement, mapped onto the patterns it belongs to."""

    model_config = ConfigDict(frozen=True)

    movement: str
    patterns: list[str]
    note: str


class Coach(BaseModel):
    """One entry of the authored coach directory."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    note: str = ""


class Kg2Report(BaseModel):
    """What the build could not join, where a miss is not a failure.

    Three separate lists rather than one, because they mean different things and
    a reader should not have to guess which. All three are free text a person
    wrote or a definition nobody exercised — none of them makes the graph
    misleading, which is the line `link_required` enforces everywhere else.
    """

    unmatched_dislikes: list[str] = []
    """Disliked movements the catalog does not stock. The preference is still
    true; there is simply nothing to exclude."""

    ambiguous_mentions: list[str] = []
    """Surfaces in the chat that named more than one concept, so no edge was
    written. Reported rather than guessed at."""

    unobserved_metrics: list[str] = []
    """Metrics defined but never measured for this member."""

    @property
    def is_clean(self) -> bool:
        """Whether every join landed."""
        return not (
            self.unmatched_dislikes or self.ambiguous_mentions or self.unobserved_metrics
        )


def load_session_patterns(path: Path) -> dict[str, list[str]]:
    """Read the map from coach shorthand onto catalog movement patterns.

    Args:
        path: Location of `session_patterns.json`.

    Returns:
        Movement name to the pattern names it trains.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If a row is malformed.
        ValueError: If a movement is mapped twice, or maps to nothing.
    """
    rows = [SessionPatterns.model_validate(row) for row in json.loads(path.read_text())]
    mapping: dict[str, list[str]] = {}
    for row in rows:
        if row.movement in mapping:
            raise ValueError(f"duplicate session pattern mapping for {row.movement!r}")
        if not row.patterns:
            raise ValueError(f"{row.movement!r} maps to no pattern")
        mapping[row.movement] = row.patterns
    return mapping


def load_coaches(path: Path) -> list[Coach]:
    """Read the authored coach directory.

    Args:
        path: Location of `coaches.json`.

    Returns:
        Every coach.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If a row is malformed.
    """
    return [Coach.model_validate(row) for row in json.loads(path.read_text())]


def _apply_constraints(session: Session) -> None:
    """Declare uniqueness constraints for the labels KG2 creates."""
    # Labels and property keys cannot be query parameters in Cypher, so they are
    # interpolated. Values come from the NodeLabel enum, never from input data.
    for label in _NEW_LABELS:
        session.run(
            f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        )


def _member_row(context: MemberContext) -> dict:
    """The Member node's properties: the profile, plus the scalar preferences.

    `weight_kg` is dropped: `biomarkers.weight_trend_kg` records the same fact
    as a dated series, and the latest observation is the answer. Keeping both
    would give two numbers that can disagree.
    """
    row = context.profile.model_dump(mode="json")
    row.pop("weight_kg", None)
    preferences = context.preferences.model_dump(mode="json")
    row.update({field: preferences[field] for field in _MEMBER_PREFERENCE_FIELDS})
    return row


def _build_coach(session: Session, context: MemberContext) -> None:
    """Create the coaching relationship the member's profile names.

    `Coach -coaches-> Member` is what turns the console's mock login into an
    authorization check: holding a member id is not authority to read that
    member. Fails the build if the profile names a coach the directory does not
    have, because a member nobody coaches is unreachable through the API.
    """
    coaches = load_coaches(settings.coaches_path)
    merge_nodes(
        session,
        NodeLabel.COACH,
        "id",
        [{"id": coach.id, "name": coach.name} for coach in coaches],
        GraphSource.KG2,
    )
    link_required(
        session, _COACHES, [{"source": context.profile.coach_id, "target": context.profile.id}]
    )


def _build_goals(session: Session, context: MemberContext) -> None:
    """Create goals and link them to what they train and how they are scored.

    A goal reaches muscles through `targets` or a metric through `measured_by`,
    and the two are alternatives rather than a pair: the strength goals name
    muscles, the sleep goal names a number. Before `measured_by` existed the
    sleep goal was the one goal the graph could say nothing about.
    """
    member_id = context.profile.id
    merge_nodes(
        session,
        NodeLabel.GOAL,
        "id",
        [
            {
                "id": goal.id,
                "text": goal.text,
                "priority": goal.priority,
                "target_date": goal.target_date.isoformat() if goal.target_date else None,
            }
            for goal in context.goals
        ],
        GraphSource.KG2,
    )
    link_required(
        session,
        _HAS_GOAL,
        [{"source": member_id, "target": goal.id} for goal in context.goals],
    )
    link_required(
        session,
        _TARGETS,
        [
            {"source": goal.id, "target": muscle}
            for goal in context.goals
            for muscle in goal.targets
        ],
    )
    link_required(
        session,
        _MEASURED_BY,
        [{"source": goal.id, "target": goal.metric} for goal in context.goals if goal.metric],
    )


def _build_metrics(
    session: Session, definitions: dict[str, MetricDefinition], rows: list[Observation]
) -> None:
    """Create the metric vertices and the observations pointing at them.

    Only metrics this member has actually been measured on are created. The
    definitions file is shared across members, so materialising all of them
    would leave every member's graph carrying vertices nothing reaches.
    """
    observed = {row.metric_id for row in rows}
    merge_nodes(
        session,
        NodeLabel.METRIC,
        "id",
        [
            definition.model_dump(mode="json")
            for metric_id, definition in sorted(definitions.items())
            if metric_id in observed
        ],
        GraphSource.KG2,
    )


def _build_observations(
    session: Session, context: MemberContext, rows: list[Observation]
) -> None:
    """Create one node per measurement and join it to its metric.

    `metric_id` is kept as a property as well as being the join key, so a node
    reads on its own in the Neo4j browser and in the instance explorer. That is
    denormalisation for legibility, not a second source of truth — the edge is
    what any query traverses.
    """
    member_id = context.profile.id
    merge_nodes(
        session,
        NodeLabel.OBSERVATION,
        "id",
        [
            {
                "id": row.id,
                "metric_id": row.metric_id,
                "value": row.value,
                "observed_on": row.observed_on.isoformat(),
                "panel": row.panel,
            }
            for row in rows
        ],
        GraphSource.KG2,
    )
    link_required(
        session, _HAS_OBSERVATION, [{"source": member_id, "target": row.id} for row in rows]
    )
    link_required(
        session, _MEASURES, [{"source": row.id, "target": row.metric_id} for row in rows]
    )


def _session_rows(history: list[WorkoutSession]) -> list[dict]:
    """Shape workout history into Session node rows."""
    return [
        {
            "id": entry.id,
            "date": entry.date.isoformat(),
            "title": entry.title,
            "planned": entry.planned,
            "completed": entry.completed,
            "duration_min": entry.duration_min,
            "rpe": entry.rpe,
            "movements": entry.exercises,
        }
        for entry in history
    ]


def _build_sessions(session: Session, context: MemberContext) -> None:
    """Create sessions and link them to the movement patterns they trained.

    The edge reaches `MovementPattern`, not `Exercise`, because none of the nine
    movements the sample records matches a catalog exercise — not one, not even
    as a substring. They are coach shorthand for movements this catalog does not
    stock, and the pattern is the grain the two vocabularies share. See
    `docs/decisions.md`, KG2.

    A skipped session names no movements and so carries no `trained` edges,
    which is the correct reading: nothing was trained. It is why "what has she
    actually done" is a traversal rather than a filter over a property.

    Raises:
        ValueError: If a recorded movement has no pattern mapping, or maps to a
            pattern KG1 does not have. Both would leave a session that silently
            trained nothing, which is indistinguishable from a skipped one.
    """
    history = context.workout_history
    if not history:
        return

    ids = [entry.id for entry in history]
    if len(set(ids)) != len(ids):
        raise ValueError(f"workout history has colliding session ids: {sorted(ids)}")

    mapping = load_session_patterns(settings.session_patterns_path)
    unmapped = sorted(
        {movement for entry in history for movement in entry.exercises if movement not in mapping}
    )
    if unmapped:
        raise ValueError(
            f"workout history names movements with no pattern mapping: {unmapped}. "
            f"Add them to {settings.session_patterns_path.name}."
        )

    merge_nodes(session, NodeLabel.SESSION, "id", _session_rows(history), GraphSource.KG2)
    link_required(
        session, _HAS_SESSION, [{"source": context.profile.id, "target": entry.id} for entry in history]
    )
    link_required(
        session,
        _TRAINED,
        [
            {"source": entry.id, "target": pattern, "movement": movement}
            for entry in history
            for movement in entry.exercises
            for pattern in mapping[movement]
        ],
    )


def _message_rows(messages: list[ChatMessage]) -> list[dict]:
    """Shape chat history into Message node rows.

    Timestamps are stored as UTC so they sort lexicographically. The sample is
    written in a single offset, where local ISO strings happen to sort correctly
    too — which is exactly the kind of accident that breaks on the first member
    who travels.
    """
    return [
        {
            "id": message.id,
            "ts": message.ts.astimezone(UTC).isoformat(),
            "author": message.author.value,
            "text": message.text,
            # Parallel arrays rather than a nested structure: Neo4j properties
            # hold primitives and arrays of primitives, not maps.
            "attachment_types": [a.type for a in message.attachments],
            "attachment_captions": [a.caption for a in message.attachments],
        }
        for message in messages
    ]


def _build_messages(session: Session, context: MemberContext, vocabulary: Vocabulary) -> list[str]:
    """Create messages and link them to the concepts they name.

    This is where an equipment constraint gets a citation: *"Still no barbell at
    home btw — only DBs and a kettlebell"* becomes three `mentions` edges, so
    the copilot can answer why she has no barbell by pointing at the message
    where she said so rather than asserting it from a list.

    Matching is exact and alias only — see `resolve.mentions.scan`. A message
    naming nothing is the common case and not a failure.

    Args:
        session: An open Neo4j session.
        context: The member's context.
        vocabulary: Loaded from the graph, so KG1 must already be built.

    Returns:
        Surfaces that matched more than one concept and were skipped, sorted.
    """
    messages = context.messages_oldest_first
    if not messages:
        return []

    merge_nodes(session, NodeLabel.MESSAGE, "id", _message_rows(messages), GraphSource.KG2)
    link_required(
        session,
        _HAS_MESSAGE,
        [{"source": context.profile.id, "target": message.id} for message in messages],
    )

    ambiguous: set[str] = set()
    by_label: dict[NodeLabel, list[dict]] = {label: [] for label in _MENTIONS}
    for message in messages:
        result = scan(message.text, vocabulary)
        ambiguous.update(result.ambiguous)
        for mention in result.mentions:
            by_label[mention.label].append(
                {
                    "source": message.id,
                    "target": mention.name,
                    "surface": mention.surface,
                    "matched_by": mention.matched_by.value,
                }
            )

    for label, rows in by_label.items():
        # Required, not best-effort: the scanner matched against names it read
        # out of this same graph, so a row that fails to link means the two went
        # out of step rather than that a member wrote something unrecognised.
        link_required(session, _MENTIONS[label], rows)

    return sorted(ambiguous)


def _link_dislikes(session: Session, context: MemberContext) -> list[str]:
    """Point the member at the exercises `preferences.dislikes` names.

    Unlike every other join in either graph, an unmatched name here is not a
    defect. A member may dislike a movement this catalog does not stock, and
    that preference is still true — there is simply nothing to exclude. So the
    misses are returned for reporting rather than raised.

    Args:
        session: An open Neo4j session.
        context: The member's context.

    Returns:
        Disliked names that matched no exercise, sorted.
    """
    disliked = context.preferences.dislikes
    if not disliked:
        return []

    member_id = context.profile.id
    rows = [{"source": member_id, "target": name} for name in disliked]
    linked = link_nodes(session, _DISLIKES, rows)
    if linked == len(rows):
        return []

    matched = session.run(
        f"""
        MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})
              -[:{RelType.DISLIKES}]->(e:{NodeLabel.EXERCISE})
        RETURN collect(e.name) AS names
        """,
        member_id=member_id,
    ).single()["names"]
    return sorted(set(disliked) - set(matched))


def build_kg2(session: Session, member_context_path: Path) -> Kg2Report:
    """Build the member-context graph.

    Idempotent, and dependent on KG1: `Equipment`, `Injury`, `Muscle`,
    `Exercise` and `MovementPattern` are resolved by name against nodes KG1
    created rather than being created here, so the two graphs share one set of
    nodes instead of two that drift. Build KG1 first.

    Args:
        session: An open Neo4j session.
        member_context_path: Location of `member-context.json`.

    Returns:
        What could not be joined, in the three cases where a miss is benign.

    Raises:
        FileNotFoundError: If any input file is missing.
        pydantic.ValidationError: If a block is malformed.
        ValueError: If a structural join fails — a goal naming an unknown
            muscle or metric, a session movement with no pattern mapping, a
            coach the directory does not have, or equipment and injuries KG1
            did not create.
    """
    context = load_member_context(member_context_path)
    member_id = context.profile.id
    as_of = reference_date(context)

    definitions = load_metrics(settings.metrics_path)
    rows = observations(context, as_of)
    unobserved = check_against(rows, definitions)

    _apply_constraints(session)
    merge_nodes(session, NodeLabel.MEMBER, "id", [_member_row(context)], GraphSource.KG2)
    _build_coach(session, context)

    _build_metrics(session, definitions, rows)
    _build_observations(session, context, rows)
    _build_goals(session, context)

    link_required(
        session,
        _HAS_EQUIPMENT,
        [{"source": member_id, "target": name} for name in context.equipment_available],
    )
    link_required(
        session,
        _HAS_INJURY,
        [{"source": member_id, "target": injury.id} for injury in context.injuries],
    )

    _build_sessions(session, context)
    # Loaded after KG1's nodes and this build's own writes, so the scanner
    # matches against exactly the vocabulary the store holds.
    vocabulary = Vocabulary.load(session, settings.aliases_path)
    ambiguous = _build_messages(session, context, vocabulary)

    return Kg2Report(
        unmatched_dislikes=_link_dislikes(session, context),
        ambiguous_mentions=ambiguous,
        unobserved_metrics=unobserved,
    )
