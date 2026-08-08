from pathlib import Path

from neo4j import Session

from graph.build.member import MemberContext, load_member_context
from graph.build.writes import EdgeWrite, NodeMatch, link_nodes, link_required, merge_nodes
from graph.schema import GraphSource, NodeLabel, RelType

_MEMBER = NodeMatch(label=NodeLabel.MEMBER, key="id")
_GOAL = NodeMatch(label=NodeLabel.GOAL, key="id")

# `has` is one edge type reaching three labels: the target's label already says
# what the relation means, so a `has_goal` / `has_equipment` prefix would only
# restate it. See docs/decisions.md, KG2 decision 1.
_HAS_GOAL = EdgeWrite(rel=RelType.HAS, source=_MEMBER, target=_GOAL)
_HAS_EQUIPMENT = EdgeWrite(
    rel=RelType.HAS, source=_MEMBER, target=NodeMatch(label=NodeLabel.EQUIPMENT)
)
_HAS_INJURY = EdgeWrite(
    rel=RelType.HAS, source=_MEMBER, target=NodeMatch(label=NodeLabel.INJURY, key="id")
)
_TARGETS = EdgeWrite(
    rel=RelType.TARGETS, source=_GOAL, target=NodeMatch(label=NodeLabel.MUSCLE)
)
_DISLIKES = EdgeWrite(
    rel=RelType.DISLIKES, source=_MEMBER, target=NodeMatch(label=NodeLabel.EXERCISE)
)

# The only key of `preferences` the graph models. The rest — session length,
# training days, free-text notes — are scalar facts with no edge to carry, so
# they stay in member-context.json for the copilot to read directly.
DISLIKES_KEY = "dislikes"


def _apply_constraints(session: Session) -> None:
    """Declare uniqueness constraints for the labels KG2 creates."""
    # Labels and property keys cannot be query parameters in Cypher, so they are
    # interpolated. Values come from the NodeLabel enum, never from input data.
    for label in (NodeLabel.MEMBER, NodeLabel.GOAL):
        session.run(
            f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        )


def _build_goals(session: Session, context: MemberContext) -> None:
    """Create goals, link them to the member, and to the muscles they train.

    `targets` becomes edges rather than a node property, so a goal and the
    muscles it trains are reachable in one traversal from either end.
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
    disliked = context.preferences.get(DISLIKES_KEY, [])
    if not isinstance(disliked, list):
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


def build_kg2(session: Session, member_context_path: Path) -> list[str]:
    """Build the member-context graph.

    Idempotent, and dependent on KG1: `Equipment`, `Injury`, `Muscle`, and
    `Exercise` are resolved by name against nodes KG1 created rather than being
    created here, so the two graphs share one set of nodes instead of two that
    drift. Build KG1 first.

    Args:
        session: An open Neo4j session.
        member_context_path: Location of `member-context.json`.

    Returns:
        Disliked exercise names that matched nothing in the catalog.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If a modelled block is malformed.
        ValueError: If a goal names an unknown muscle, or the member names
            equipment or an injury that KG1 did not create.
    """
    context = load_member_context(member_context_path)
    member_id = context.profile.id

    _apply_constraints(session)
    merge_nodes(
        session,
        NodeLabel.MEMBER,
        "id",
        [context.profile.model_dump(mode="json")],
        GraphSource.KG2,
    )
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
    return _link_dislikes(session, context)
