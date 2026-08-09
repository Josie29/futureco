from neo4j import Session

from graph.schema import NodeLabel, RelType

from plan.schemas import GoalService, MovementFacts

# Follows the convention in `safety/queries.py`: labels and relationship types
# are interpolated from the enums because Cypher cannot parameterise them, and
# nothing filters. The packer needs facts for every exercise the filter might
# hand it, and an absence you never retrieved cannot be explained.
MOVEMENT_FACTS = f"""
MATCH (e:{NodeLabel.EXERCISE})
OPTIONAL MATCH (e)-[:{RelType.IS_A}]->(p:{NodeLabel.MOVEMENT_PATTERN})
WITH e, collect(DISTINCT p.name) AS patterns
OPTIONAL MATCH (e)-[:{RelType.TARGETS}]->(mu:{NodeLabel.MUSCLE})
WITH e, patterns, collect(DISTINCT mu.name) AS muscles
OPTIONAL MATCH (e)-[:{RelType.REQUIRES}]->(q:{NodeLabel.EQUIPMENT})
WITH e, patterns, muscles, collect(DISTINCT q.name) AS equipment
OPTIONAL MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(g:{NodeLabel.GOAL})
              -[:{RelType.TARGETS}]->(gm:{NodeLabel.MUSCLE})<-[:{RelType.TARGETS}]-(e)
WITH e, patterns, muscles, equipment,
     [row IN collect(DISTINCT {{goal: g.text, muscle: gm.name, priority: g.priority}})
      WHERE row.goal IS NOT NULL] AS goals
RETURN e.id AS exercise_id,
       patterns,
       muscles,
       equipment,
       goals,
       e.estimated_rep_seconds AS rep_seconds,
       e.is_reps AS is_reps,
       e.is_bilateral AS is_bilateral
ORDER BY e.id
"""

# Exercises sharing a movement pattern with a given one. Built in
# `safety/queries.py` for this and unused until now: substitution walks the
# pattern axis, because that is the axis along which one movement can stand in
# for another. Muscle overlap alone would offer a tricep isolation as a
# substitute for a bench press.
PATTERN_SIBLINGS = f"""
MATCH (e:{NodeLabel.EXERCISE} {{id: $exercise_id}})
      -[:{RelType.IS_A}]->(p:{NodeLabel.MOVEMENT_PATTERN})
      <-[:{RelType.IS_A}]-(alt:{NodeLabel.EXERCISE})
WHERE alt <> e
RETURN DISTINCT alt.id AS exercise_id, alt.name AS name, p.name AS pattern
ORDER BY alt.name
"""


def movement_facts(session: Session, member_id: str) -> dict[str, MovementFacts]:
    """Read the catalog facts a plan doses and justifies itself from.

    From the graph rather than `exercises.json`, so a plan describes the same
    catalog the safety filter judged. Re-reading the file would let the two
    disagree after a rebuild.

    Args:
        session: An open Neo4j session.
        member_id: Whose goals to score the overlap against.

    Returns:
        Facts by exercise id, for the whole catalog.
    """
    return {
        row["exercise_id"]: MovementFacts(
            exercise_id=row["exercise_id"],
            patterns=tuple(sorted(row["patterns"])),
            muscles=tuple(sorted(row["muscles"])),
            equipment=tuple(sorted(row["equipment"])),
            goals=tuple(
                sorted(
                    (GoalService.model_validate(goal) for goal in row["goals"]),
                    key=lambda service: (service.priority, service.goal, service.muscle),
                )
            ),
            rep_seconds=row["rep_seconds"],
            is_reps=row["is_reps"],
            is_bilateral=row["is_bilateral"],
        )
        for row in session.run(MOVEMENT_FACTS, member_id=member_id)
    }


def pattern_siblings(session: Session, exercise_id: str) -> list[tuple[str, str, str]]:
    """Exercises sharing a movement pattern with this one.

    Args:
        session: An open Neo4j session.
        exercise_id: The dropped exercise to find stand-ins for.

    Returns:
        `(exercise_id, name, shared_pattern)` for every sibling, by name. Not
        filtered by eligibility — the caller intersects with the filter's own
        verdicts, which is what keeps substitution inside the safety boundary.
    """
    return [
        (row["exercise_id"], row["name"], row["pattern"])
        for row in session.run(PATTERN_SIBLINGS, exercise_id=exercise_id)
    ]
