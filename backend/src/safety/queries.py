from graph.schema import NodeLabel, RelType

# No query in this module filters. Anything a WHERE removes is invisible to
# the provenance trace, and an absence you never retrieved cannot be
# explained: injury status comes back attached, and Python decides liveness.
# Labels and relationship types are interpolated from the schema enums only;
# every value is a query parameter.

CLINICAL_RULES = f"""
MATCH (m:{NodeLabel.MEMBER} {{id: $member_id}})
OPTIONAL MATCH (m)-[:{RelType.HAS}]->(i:{NodeLabel.INJURY})
               -[:{RelType.DIAGNOSED_AS}]->(c:{NodeLabel.CONDITION})
               -[r:{RelType.CONTRAINDICATES}|{RelType.CAUTIONS}]->(p:{NodeLabel.MOVEMENT_PATTERN})
RETURN i.id AS injury_id,
       i.status AS injury_status,
       c.name AS condition,
       type(r) AS relation,
       r.rationale AS rationale,
       p.name AS pattern
"""

ALL_QUERIES: dict[str, str] = {
    "clinical_rules": CLINICAL_RULES,
}
