from typing import Any

from neo4j import Session

from constraints.models import Constraint, ConstraintSet, Effect, Origin
from graph.evidence import EvidencePath, Hop
from graph.schema import NodeLabel, RelType
from resolver.models import Namespace, make_concept_id
from safety.queries import CLINICAL_RULES

LIVE_INJURY_STATUSES: frozenset[str] = frozenset({"active", "recovering"})
"""An injury constrains only while live; a resolved one would contraindicate
forever with nothing saying why."""

RELATION_EFFECTS: dict[RelType, Effect] = {
    RelType.CONTRAINDICATES: Effect.BLOCK,
    RelType.CAUTIONS: Effect.CAUTION,
}
"""The clinician's verb decides the hardness: absolute vs relative
contraindication, on the edge, never inferred."""


def load_clinical(session: Session, member_id: str) -> ConstraintSet:
    """Read the member's clinical envelope from the graph.

    Args:
        session: An open Neo4j session onto the built graphs.
        member_id: The member whose injuries seed the traversal.

    Returns:
        Clinical-origin constraints with evidence paths, one per live rule.
        Empty for a member with no live injuries or no authored rules.

    Raises:
        ValueError: If the member does not exist — a silently empty envelope
            would validate every plan against nothing.
    """
    rows = [dict(row) for row in session.run(CLINICAL_RULES, member_id=member_id)]
    if not rows:
        raise ValueError(f"member {member_id!r} is not in the graph")
    return _constraints(rows)


def _constraints(rows: list[dict[str, Any]]) -> ConstraintSet:
    """Map retrieved rule rows onto constraints, judging liveness here.

    Pure: the query returns evidence, not survivors, so the status filter is
    testable without a database and a dropped row was still retrieved.
    """
    constraints = [
        Constraint(
            target=make_concept_id(Namespace.MOVEMENT_PATTERN, row["pattern"]),
            effect=RELATION_EFFECTS[RelType(row["relation"])],
            origin=Origin.CLINICAL,
            reason=row["rationale"],
            evidence=EvidencePath(
                entry=row["injury_id"],
                hops=(
                    Hop(
                        rel=RelType.DIAGNOSED_AS,
                        to_label=NodeLabel.CONDITION,
                        to_name=row["condition"],
                    ),
                    Hop(
                        rel=RelType(row["relation"]),
                        to_label=NodeLabel.MOVEMENT_PATTERN,
                        to_name=row["pattern"],
                    ),
                ),
            ),
        )
        for row in rows
        if row["injury_id"] is not None
        and row["injury_status"] in LIVE_INJURY_STATUSES
    ]
    return ConstraintSet(
        constraints=tuple(
            sorted(
                constraints,
                key=lambda c: (c.target, c.effect, c.evidence.entry if c.evidence else ""),
            )
        )
    )
