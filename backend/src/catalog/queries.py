from graph.schema import NodeLabel, RelType

# No query in this module filters. Anything a WHERE removes is invisible to
# the provenance trace, and an absence you never retrieved cannot be
# explained. The catalog returns all rows every time; missing equipment comes
# back as a list, never a predicate. Labels and relationship types are
# interpolated from the schema enums only; every value is a query parameter.

CANDIDATES = f"""
MATCH (m:{NodeLabel.MEMBER} {{id: $member_id}})
OPTIONAL MATCH (m)-[:{RelType.HAS}]->(q:{NodeLabel.EQUIPMENT})
WITH m, collect(DISTINCT q.name) AS owned
MATCH (e:{NodeLabel.EXERCISE})
OPTIONAL MATCH (m)-[d:{RelType.DISLIKES}]->(e)
WITH m, owned, e, count(d) > 0 AS disliked
OPTIONAL MATCH (m)-[:{RelType.HAS}]->(g:{NodeLabel.GOAL})
              -[:{RelType.TARGETS}]->(mu:{NodeLabel.MUSCLE})<-[:{RelType.TARGETS}]-(e)
WITH owned, e, disliked,
     [row IN collect(DISTINCT {{id: g.id, text: g.text, priority: g.priority,
                                muscle: mu.name}})
      WHERE row.id IS NOT NULL] AS goal_rows
RETURN e.name AS name,
       e.movement_patterns AS patterns,
       e.muscle_groups AS muscles,
       e.equipment_required AS equipment_required,
       [q IN e.equipment_required WHERE NOT q IN owned] AS missing_equipment,
       e.joints_loaded AS joints,
       e.is_reps AS is_reps,
       e.is_duration AS is_duration,
       e.estimated_rep_seconds AS estimated_rep_seconds,
       e.is_bilateral AS is_bilateral,
       e.side AS side,
       e.supports_weight AS supports_weight,
       disliked,
       goal_rows
ORDER BY e.name
"""

ALL_QUERIES: dict[str, str] = {
    "catalog_candidates": CANDIDATES,
}
