from graph.schema import NodeLabel, RelType

# Read-side Cypher for the coach console. Labels and relationship types cannot
# be query parameters, so they are interpolated from the enums — never from
# input data, the same rule the build and safety layers follow.
#
# Split into named single-purpose reads rather than one join returning
# everything. Eight round trips to a local Neo4j cost single-digit milliseconds
# together, and a reviewer checking "where does typical session length come
# from" should find one query that answers exactly that.

COACHES = f"""
MATCH (c:{NodeLabel.COACH})
RETURN c.id AS id, c.name AS name
ORDER BY c.name
"""

# The authorization check. A member is readable when this coach coaches her —
# not when the caller can name her id.
COACHES_MEMBER = f"""
MATCH (:{NodeLabel.COACH} {{id: $coach_id}})-[:{RelType.COACHES}]->(m:{NodeLabel.MEMBER} {{id: $member_id}})
RETURN count(m) AS matched
"""

# Roster metadata for members the graph actually holds. Derived figures the
# roster shows — latest adherence, last completed session — come from the same
# nodes the member view reads, so the two cannot disagree.
ROSTER = f"""
MATCH (:{NodeLabel.COACH} {{id: $coach_id}})-[:{RelType.COACHES}]->(m:{NodeLabel.MEMBER})
OPTIONAL MATCH (m)-[:{RelType.HAS}]->(o:{NodeLabel.OBSERVATION})
                -[:{RelType.MEASURES}]->(:{NodeLabel.METRIC} {{id: 'weekly_adherence'}})
WITH m, o ORDER BY o.observed_on
WITH m, collect(o.value) AS adherence
OPTIONAL MATCH (m)-[:{RelType.HAS}]->(s:{NodeLabel.SESSION} {{completed: true}})
WITH m, adherence, max(s.date) AS last_session
OPTIONAL MATCH (m)-[:{RelType.HAS}]->(i:{NodeLabel.INJURY})
WHERE i.status IN $live_statuses
RETURN m.id AS id, m.name AS name, adherence, last_session,
       collect(i.joint)[0] AS injury_joint
ORDER BY m.name
"""

PROFILE = f"""
MATCH (m:{NodeLabel.MEMBER} {{id: $member_id}})
RETURN m.id AS id, m.name AS name, m.age AS age, m.tier AS tier,
       m.member_since AS member_since, m.trains_at AS trains_at,
       m.preferred_session_minutes AS preferred_session_minutes,
       m.training_days_per_week AS training_days_per_week
"""

# One row per goal, with both ways a goal can be scored attached: the muscles it
# trains, and — for a goal measured by a number rather than by muscles — the
# metric and every reading of it. Before `measured_by` existed, the sleep goal
# came back with two empty columns and the console invented its own target.
GOALS = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(g:{NodeLabel.GOAL})
OPTIONAL MATCH (g)-[:{RelType.TARGETS}]->(mu:{NodeLabel.MUSCLE})
WITH g, collect(DISTINCT mu.name) AS targets
OPTIONAL MATCH (g)-[:{RelType.MEASURED_BY}]->(mt:{NodeLabel.METRIC})
OPTIONAL MATCH (mt)<-[:{RelType.MEASURES}]-(o:{NodeLabel.OBSERVATION})
WITH g, targets, mt, o ORDER BY o.observed_on
RETURN g.id AS id, g.text AS text, g.priority AS priority,
       g.target_date AS target_date, targets,
       mt.id AS metric_id, mt.name AS metric_name, mt.unit AS metric_unit,
       mt.optimal_low AS metric_low, mt.optimal_high AS metric_high,
       [v IN collect(o.value) WHERE v IS NOT NULL] AS readings
ORDER BY g.priority, g.id
"""

EQUIPMENT = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(e:{NodeLabel.EQUIPMENT})
RETURN e.name AS name ORDER BY e.name
"""

INJURIES = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(i:{NodeLabel.INJURY})
OPTIONAL MATCH (i)-[:{RelType.DIAGNOSED_AS}]->(c:{NodeLabel.CONDITION})
RETURN i.id AS id, i.region AS region, i.joint AS joint, i.status AS status,
       i.severity AS severity, i.since AS since, i.notes AS notes,
       coalesce(c.name, '') AS condition
ORDER BY i.id
"""

# What her recorded injuries actually rule out, read from the clinical edges
# rather than authored as copy. Authored text would drift from the rules the
# filter enforces, and the panel would then describe a graph it no longer
# matches.
INJURY_RULES = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(i:{NodeLabel.INJURY})
WHERE i.status IN $live_statuses
MATCH (i)-[:{RelType.DIAGNOSED_AS}]->(:{NodeLabel.CONDITION})
      -[r:{RelType.CONTRAINDICATES}|{RelType.CAUTIONS}]->(p:{NodeLabel.MOVEMENT_PATTERN})
RETURN type(r) AS relation, collect(DISTINCT p.name) AS patterns
"""

DISLIKES = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.DISLIKES}]->(e:{NodeLabel.EXERCISE})
RETURN e.name AS name ORDER BY e.name
"""

SESSIONS = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(s:{NodeLabel.SESSION})
RETURN s.date AS date, s.title AS title, s.completed AS completed,
       s.duration_min AS duration_min, s.rpe AS rpe
ORDER BY s.date
"""

# Any metric's series, by id. One query serves adherence, sleep, weight, heart
# rate and every lab value — which is the payoff for reifying observations
# rather than leaving four differently-shaped blocks in the JSON.
OBSERVATIONS = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(o:{NodeLabel.OBSERVATION})
      -[:{RelType.MEASURES}]->(mt:{NodeLabel.METRIC} {{id: $metric_id}})
RETURN o.observed_on AS observed_on, o.value AS value, o.panel AS panel,
       mt.unit AS unit, mt.name AS name
ORDER BY o.observed_on
"""

MESSAGES = f"""
MATCH (:{NodeLabel.MEMBER} {{id: $member_id}})-[:{RelType.HAS}]->(m:{NodeLabel.MESSAGE})
RETURN m.id AS id, m.ts AS ts, m.author AS author, m.text AS text,
       m.attachment_types AS attachment_types,
       m.attachment_captions AS attachment_captions
ORDER BY m.ts
"""

ALL_QUERIES: dict[str, str] = {
    "COACHES": COACHES,
    "COACHES_MEMBER": COACHES_MEMBER,
    "ROSTER": ROSTER,
    "PROFILE": PROFILE,
    "GOALS": GOALS,
    "EQUIPMENT": EQUIPMENT,
    "INJURIES": INJURIES,
    "INJURY_RULES": INJURY_RULES,
    "DISLIKES": DISLIKES,
    "SESSIONS": SESSIONS,
    "OBSERVATIONS": OBSERVATIONS,
    "MESSAGES": MESSAGES,
}
