from graph.schema import NodeLabel, RelType

# Single-purpose reads over one member's context. Labels and relationship
# types are interpolated from the schema enums only; every value is a query
# parameter. No model ever composes or edits these.

STANDING = f"""
MATCH (m:{NodeLabel.MEMBER} {{id: $member_id}})
OPTIONAL MATCH (m)-[:{RelType.HAS}]->(q:{NodeLabel.EQUIPMENT})
WITH m, collect(DISTINCT q.name) AS equipment
OPTIONAL MATCH (m)-[:{RelType.DISLIKES}]->(x:{NodeLabel.EXERCISE})
WITH m, equipment, collect(DISTINCT x.name) AS disliked
OPTIONAL MATCH (m)-[:{RelType.HAS}]->(i:{NodeLabel.INJURY})
OPTIONAL MATCH (i)-[:{RelType.DIAGNOSED_AS}]->(c:{NodeLabel.CONDITION})
RETURN m.name AS name,
       m.age AS age,
       m.preferred_session_minutes AS preferred_session_minutes,
       m.training_days_per_week AS training_days_per_week,
       equipment,
       disliked,
       [row IN collect(DISTINCT {{id: i.id, region: i.region, joint: i.joint,
                                  side: i.side, status: i.status,
                                  severity: i.severity, since: i.since,
                                  notes: i.notes, condition: c.name}})
        WHERE row.id IS NOT NULL] AS injuries
"""

GOALS = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(g:{NodeLabel.GOAL})
OPTIONAL MATCH (g)-[:{RelType.TARGETS}]->(mu:{NodeLabel.MUSCLE})
WITH g, collect(DISTINCT mu.name) AS target_muscles
OPTIONAL MATCH (g)-[:{RelType.MEASURED_BY}]->(mt:{NodeLabel.METRIC})
RETURN g.id AS id, g.text AS text, g.priority AS priority,
       g.target_date AS target_date, target_muscles, mt.name AS metric
ORDER BY g.priority, g.id
"""

PATTERN_HISTORY = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(s:{NodeLabel.SESSION})
      -[:{RelType.TRAINED}]->(p:{NodeLabel.MOVEMENT_PATTERN})
WHERE s.completed
RETURN p.name AS pattern,
       count(DISTINCT s) AS sessions,
       max(s.date) AS last_trained
ORDER BY last_trained DESC, pattern
"""

ALL_QUERIES: dict[str, str] = {
    "member_standing": STANDING,
    "member_goals": GOALS,
    "member_pattern_history": PATTERN_HISTORY,
}
