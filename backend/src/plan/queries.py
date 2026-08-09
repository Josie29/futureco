from neo4j import Session

from graph.schema import NodeLabel, RelType

from plan.schemas import MovementFacts

# Follows the convention in `safety/queries.py`: labels and relationship types
# are interpolated from the enums because Cypher cannot parameterise them, and
# nothing filters. The packer needs facts for every exercise the filter might
# hand it, and an absence you never retrieved cannot be explained.
MOVEMENT_FACTS = f"""
MATCH (e:{NodeLabel.EXERCISE})
OPTIONAL MATCH (e)-[:{RelType.IS_A}]->(p:{NodeLabel.MOVEMENT_PATTERN})
RETURN e.id AS exercise_id,
       collect(DISTINCT p.name) AS patterns,
       e.estimated_rep_seconds AS rep_seconds,
       e.is_reps AS is_reps,
       e.is_bilateral AS is_bilateral
ORDER BY e.id
"""


def movement_facts(session: Session) -> dict[str, MovementFacts]:
    """Read the catalog fields the packer doses from.

    From the graph rather than `exercises.json`, so a plan describes the same
    catalog the safety filter judged. Re-reading the file would let the two
    disagree after a rebuild.

    Args:
        session: An open Neo4j session.

    Returns:
        Facts by exercise id, for the whole catalog.
    """
    return {
        row["exercise_id"]: MovementFacts(
            exercise_id=row["exercise_id"],
            patterns=tuple(sorted(row["patterns"])),
            rep_seconds=row["rep_seconds"],
            is_reps=row["is_reps"],
            is_bilateral=row["is_bilateral"],
        )
        for row in session.run(MOVEMENT_FACTS)
    }
