from graph.schema import NodeLabel, RelType

# Retrieval Cypher for the copilot. Same discipline as `safety/queries.py` and
# `api/member_queries.py`: labels and relationship types are interpolated from
# the enums, values are always parameters, and **no language model ever writes
# or edits a query here**. The model chooses which of these to run and with
# what arguments; the Cypher itself is a module constant.
#
# `api/member_queries.py` already reads the member page. These are the reads
# that page does not need — what a session actually trained, messages found by
# the concept they name, and a metric series with the band it is judged
# against.

# Sessions with the movement patterns they trained. The pattern join is what
# makes "what has she been working on" answerable at all: none of the recorded
# movements is a catalog exercise, so the pattern is the only shared vocabulary
# between her history and the rest of the graph.
SESSIONS_WITH_PATTERNS = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(s:{NodeLabel.SESSION})
WHERE s.date >= $since
OPTIONAL MATCH (s)-[t:{RelType.TRAINED}]->(p:{NodeLabel.MOVEMENT_PATTERN})
RETURN s.date AS date, s.title AS title, s.completed AS completed,
       s.duration_min AS duration_min, s.rpe AS rpe,
       collect(DISTINCT p.name) AS patterns,
       collect(DISTINCT t.movement) AS movements
ORDER BY s.date DESC
LIMIT $limit
"""

# How often each pattern has been trained in a window. The longitudinal read:
# "she has hit lower-pull twice this week" is one hop, not a scan.
PATTERN_FREQUENCY = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(s:{NodeLabel.SESSION})
      -[:{RelType.TRAINED}]->(p:{NodeLabel.MOVEMENT_PATTERN})
WHERE s.completed AND s.date >= $since
RETURN p.name AS pattern, count(DISTINCT s) AS sessions,
       collect(DISTINCT s.date) AS dates
ORDER BY sessions DESC, pattern
"""

# One metric's full series with the band it is read against, so a caller never
# has to pair a value with a threshold from somewhere else.
METRIC_SERIES = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(o:{NodeLabel.OBSERVATION})
      -[:{RelType.MEASURES}]->(m:{NodeLabel.METRIC} {{id: $metric_id}})
WHERE o.observed_on >= $since
WITH m, o ORDER BY o.observed_on
RETURN m.id AS metric_id, m.name AS name, m.unit AS unit,
       m.category AS category, m.direction AS direction,
       m.optimal_low AS optimal_low, m.optimal_high AS optimal_high,
       m.reference AS reference,
       collect({{observed_on: o.observed_on, value: o.value, panel: o.panel}}) AS readings
"""

# Every metric this member has been measured on, with how many readings and the
# most recent value. One call tells the copilot what it can ask about, so it
# never guesses a metric id.
METRIC_INDEX = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(o:{NodeLabel.OBSERVATION})
      -[:{RelType.MEASURES}]->(m:{NodeLabel.METRIC})
WITH m, o ORDER BY o.observed_on
WITH m, collect(o) AS readings
RETURN m.id AS metric_id, m.name AS name, m.unit AS unit,
       m.category AS category, m.direction AS direction,
       m.optimal_low AS optimal_low, m.optimal_high AS optimal_high,
       size(readings) AS reading_count,
       last(readings).value AS latest_value,
       last(readings).observed_on AS latest_on
ORDER BY m.category, m.id
"""

# Messages that name a given concept, found through the `mentions` edge rather
# than by string search. This is what lets "why does she have no barbell?" be
# answered with the message where she said so — the edge was written at build
# time by an exact/alias match, so a hit is a fact about the text, not a guess.
MESSAGES_BY_CONCEPT = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(m:{NodeLabel.MESSAGE})
      -[r:{RelType.MENTIONS}]->(c)
WHERE c.name = $concept
RETURN m.id AS id, m.ts AS ts, m.author AS author, m.text AS text,
       r.surface AS surface, labels(c)[0] AS concept_label
ORDER BY m.ts DESC
LIMIT $limit
"""

# The whole thread, newest first, for questions that are about the conversation
# rather than about a concept in it.
RECENT_MESSAGES = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(m:{NodeLabel.MESSAGE})
WHERE m.ts >= $since
RETURN m.id AS id, m.ts AS ts, m.author AS author, m.text AS text
ORDER BY m.ts DESC
LIMIT $limit
"""

# Every concept her messages have named, so the copilot can find the right
# argument for MESSAGES_BY_CONCEPT without guessing.
MENTIONED_CONCEPTS = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(:{NodeLabel.MESSAGE})
      -[r:{RelType.MENTIONS}]->(c)
RETURN DISTINCT c.name AS concept, labels(c)[0] AS label, count(r) AS mentions
ORDER BY mentions DESC, concept
"""

# What her live injuries rule out, walked from the injury rather than asserted.
# The same edges `safety.filter` enforces, read here for explanation — so the
# copilot's answer and the generator's exclusion cannot disagree.
CLINICAL_PICTURE = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(i:{NodeLabel.INJURY})
OPTIONAL MATCH (i)-[:{RelType.DIAGNOSED_AS}]->(c:{NodeLabel.CONDITION})
OPTIONAL MATCH (c)-[r:{RelType.CONTRAINDICATES}|{RelType.CAUTIONS}]->(p:{NodeLabel.MOVEMENT_PATTERN})
RETURN i.id AS injury_id, i.region AS region, i.status AS status,
       i.severity AS severity, i.since AS since, i.notes AS notes,
       c.name AS condition,
       [row IN collect(DISTINCT {{relation: type(r), pattern: p.name}})
        WHERE row.pattern IS NOT NULL] AS rules
ORDER BY i.id
"""

# Goals with how they are scored — muscles for the strength goals, a metric for
# the one with a number. The `measured_by` leg is what makes the sleep goal
# answerable at all.
GOALS_WITH_PROGRESS = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(g:{NodeLabel.GOAL})
OPTIONAL MATCH (g)-[:{RelType.TARGETS}]->(mu:{NodeLabel.MUSCLE})
WITH g, collect(DISTINCT mu.name) AS targets
OPTIONAL MATCH (g)-[:{RelType.MEASURED_BY}]->(m:{NodeLabel.METRIC})
RETURN g.id AS id, g.text AS text, g.priority AS priority,
       g.target_date AS target_date, targets,
       m.id AS metric_id, m.name AS metric_name
ORDER BY g.priority, g.id
"""

ALL_QUERIES: dict[str, str] = {
    "SESSIONS_WITH_PATTERNS": SESSIONS_WITH_PATTERNS,
    "PATTERN_FREQUENCY": PATTERN_FREQUENCY,
    "METRIC_SERIES": METRIC_SERIES,
    "METRIC_INDEX": METRIC_INDEX,
    "MESSAGES_BY_CONCEPT": MESSAGES_BY_CONCEPT,
    "RECENT_MESSAGES": RECENT_MESSAGES,
    "MENTIONED_CONCEPTS": MENTIONED_CONCEPTS,
    "CLINICAL_PICTURE": CLINICAL_PICTURE,
    "GOALS_WITH_PROGRESS": GOALS_WITH_PROGRESS,
}
