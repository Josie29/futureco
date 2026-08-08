from neo4j import Session
from pydantic import BaseModel, ConfigDict

from graph.schema import AnatomicalTier, NodeLabel, RelType

# Labels and relationship types cannot be query parameters in Cypher, so they
# are interpolated. Values come from the enums, never from input data — the
# same rule graph/build/writes.py follows.
#
# No query in this module filters. Anything a WHERE removes is invisible to the
# provenance trace, and an absence you never retrieved cannot be explained. So
# the catalog returns all 50 rows every time, missing equipment comes back as a
# list rather than a predicate, and an injury comes back with its status
# attached so Python can decide whether it still applies.

STANDING_CONSTRAINTS = f"""
MATCH (m:{NodeLabel.MEMBER} {{id: $member_id}})
OPTIONAL MATCH (m)-[:{RelType.HAS}]->(q:{NodeLabel.EQUIPMENT})
WITH m, collect(DISTINCT q.name) AS equipment
OPTIONAL MATCH (m)-[:{RelType.DISLIKES}]->(x:{NodeLabel.EXERCISE})
WITH m, equipment, collect(DISTINCT x.id) AS disliked
OPTIONAL MATCH (m)-[:{RelType.HAS}]->(i:{NodeLabel.INJURY})
RETURN equipment,
       disliked,
       [row IN collect(DISTINCT {{id: i.id, status: i.status, side: i.side, joint: i.joint}})
        WHERE row.id IS NOT NULL] AS injuries
"""

CATALOG_CANDIDATES = f"""
MATCH (e:{NodeLabel.EXERCISE})
OPTIONAL MATCH (e)-[:{RelType.REQUIRES}]->(q:{NodeLabel.EQUIPMENT})
WITH e, collect(DISTINCT q.name) AS required
OPTIONAL MATCH (e)-[:{RelType.IS_A}]->(p:{NodeLabel.MOVEMENT_PATTERN})
WITH e, required, collect(DISTINCT p.name) AS patterns
OPTIONAL MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(g:{NodeLabel.GOAL})
              -[:{RelType.TARGETS}]->(mu:{NodeLabel.MUSCLE})<-[:{RelType.TARGETS}]-(e)
WITH e, required, patterns,
     [row IN collect(DISTINCT {{id: g.id, priority: g.priority, muscle: mu.name}})
      WHERE row.id IS NOT NULL] AS goal_rows
RETURN e.id AS exercise_id,
       e.name AS name,
       e.supports_weight AS supports_weight,
       required,
       patterns,
       [q IN required WHERE NOT q IN $available] AS missing_equipment,
       goal_rows
ORDER BY e.name
"""

CLINICAL_SIGNALS = f"""
UNWIND $injury_ids AS injury_id
MATCH (i:{NodeLabel.INJURY} {{id: injury_id}})
      -[:{RelType.DIAGNOSED_AS}]->(c:{NodeLabel.CONDITION})
MATCH (c)-[r:{RelType.CONTRAINDICATES}|{RelType.CAUTIONS}]->(p:{NodeLabel.MOVEMENT_PATTERN})
      <-[:{RelType.IS_A}]-(e:{NodeLabel.EXERCISE})
RETURN e.id AS exercise_id,
       i.id AS injury_id,
       i.status AS injury_status,
       c.name AS condition,
       type(r) AS relation,
       r.rationale AS rationale,
       p.name AS pattern
"""

# Two directed legs, never an undirected variable-length match. Undirected
# `part_of*` walks up and then back down, so "knee" reaches "ankle" via
# "lower limb" — verified against this graph. The bound of 3 exceeds the real
# depth of 2 and shows a reviewer the traversal terminates.
ANATOMY_SIGNALS = f"""
UNWIND $structures AS entry_name
MATCH (entry:{NodeLabel.ANATOMICAL_STRUCTURE} {{name: entry_name}})
OPTIONAL MATCH (below:{NodeLabel.ANATOMICAL_STRUCTURE} {{tier: '{AnatomicalTier.JOINT}'}})
               -[:{RelType.PART_OF}*0..3]->(entry)
WITH entry, collect(DISTINCT below) AS descendants
OPTIONAL MATCH (entry)-[:{RelType.PART_OF}*0..3]
               ->(above:{NodeLabel.ANATOMICAL_STRUCTURE} {{tier: '{AnatomicalTier.JOINT}'}})
WITH entry, descendants, collect(DISTINCT above) AS ancestors
WITH entry, descendants + ancestors AS joints
UNWIND joints AS joint
MATCH (e:{NodeLabel.EXERCISE})-[:{RelType.STRESSES}]->(joint)
OPTIONAL MATCH (i:{NodeLabel.INJURY})-[:{RelType.AFFECTS}]->(joint)
RETURN DISTINCT e.id AS exercise_id,
       entry.name AS entry,
       joint.name AS joint,
       i.id AS injury_id,
       i.side AS injury_side,
       i.status AS injury_status
"""

PATTERN_SIBLINGS = f"""
MATCH (e:{NodeLabel.EXERCISE} {{id: $exercise_id}})
      -[:{RelType.IS_A}]->(p:{NodeLabel.MOVEMENT_PATTERN})
      <-[:{RelType.IS_A}]-(alt:{NodeLabel.EXERCISE})
WHERE alt <> e
RETURN DISTINCT alt.id AS exercise_id, alt.name AS name, p.name AS pattern
ORDER BY alt.name
"""

ALL_QUERIES: dict[str, str] = {
    "STANDING_CONSTRAINTS": STANDING_CONSTRAINTS,
    "CATALOG_CANDIDATES": CATALOG_CANDIDATES,
    "CLINICAL_SIGNALS": CLINICAL_SIGNALS,
    "ANATOMY_SIGNALS": ANATOMY_SIGNALS,
    "PATTERN_SIBLINGS": PATTERN_SIBLINGS,
}


class GoalOverlap(BaseModel):
    """A goal an exercise serves, and the muscle they share."""

    model_config = ConfigDict(frozen=True)

    goal_id: str
    priority: int
    muscle: str


class CatalogRow(BaseModel):
    """One exercise as the catalog query returns it, before any judgement."""

    model_config = ConfigDict(frozen=True)

    exercise_id: str
    name: str
    supports_weight: bool
    required: tuple[str, ...]
    patterns: tuple[str, ...]
    missing_equipment: tuple[str, ...]
    goal_rows: tuple[GoalOverlap, ...]


class ClinicalRow(BaseModel):
    """One condition-to-pattern rule reaching one exercise."""

    model_config = ConfigDict(frozen=True)

    exercise_id: str
    injury_id: str
    injury_status: str
    condition: str
    relation: RelType
    rationale: str
    pattern: str


class AnatomyRow(BaseModel):
    """One exercise loading a joint inside a flagged structure's closure."""

    model_config = ConfigDict(frozen=True)

    exercise_id: str
    entry: str
    joint: str
    injury_id: str | None = None
    injury_side: str | None = None
    injury_status: str | None = None


def catalog(session: Session, member_id: str, available: frozenset[str]) -> list[CatalogRow]:
    """Read every exercise with the evidence needed to judge it.

    Args:
        session: An open Neo4j session.
        member_id: Whose goals to measure overlap against.
        available: Equipment available for this request.

    Returns:
        All 50 rows, including those that will be excluded.
    """
    rows = session.run(CATALOG_CANDIDATES, member_id=member_id, available=sorted(available))
    return [
        CatalogRow(
            exercise_id=row["exercise_id"],
            name=row["name"],
            supports_weight=bool(row["supports_weight"]),
            required=tuple(row["required"]),
            patterns=tuple(row["patterns"]),
            missing_equipment=tuple(row["missing_equipment"]),
            goal_rows=tuple(
                GoalOverlap(goal_id=g["id"], priority=g["priority"], muscle=g["muscle"])
                for g in row["goal_rows"]
            ),
        )
        for row in rows
    ]


def clinical(session: Session, injury_ids: frozenset[str]) -> list[ClinicalRow]:
    """Read every contraindication and caution reaching an exercise.

    Args:
        session: An open Neo4j session.
        injury_ids: Injuries whose rules to collect.

    Returns:
        One row per rule-to-exercise pair, carrying the authored rationale and
        the injury's status so a resolved injury can be discounted later.
    """
    if not injury_ids:
        return []
    rows = session.run(CLINICAL_SIGNALS, injury_ids=sorted(injury_ids))
    return [ClinicalRow.model_validate(dict(row)) for row in rows]


def anatomy(session: Session, structures: frozenset[str]) -> list[AnatomyRow]:
    """Read every exercise loading a joint inside a flagged structure.

    Args:
        session: An open Neo4j session.
        structures: Anatomy the coach named, already resolved to canonical names.

    Returns:
        One row per exercise-joint pair. A structure whose joint closure is
        empty contributes no rows, which the caller reports rather than
        silently treating as "nothing to worry about".
    """
    if not structures:
        return []
    rows = session.run(ANATOMY_SIGNALS, structures=sorted(structures))
    return [AnatomyRow.model_validate(dict(row)) for row in rows]
