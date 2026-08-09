from api.models import GraphScope
from graph.schema import NodeLabel, RelType

type EdgeTriple = tuple[NodeLabel, RelType, NodeLabel]


class EdgeRule:
    """Which subgraph owns a triple, and what the edge asserts.

    Attributes:
        scope: The owning subgraph. Never `BOTH` — an edge has one author.
        semantics: One line, matching the edge tables in the schema docs.
    """

    __slots__ = ("scope", "semantics")

    def __init__(self, scope: GraphScope, semantics: str) -> None:
        self.scope = scope
        self.semantics = semantics


_L = NodeLabel
_R = RelType

# Keyed by the full triple, not by relationship type. Two pairs collide on type
# alone and mean different things: `targets` is Exercise->Muscle in KG1 and
# Goal->Muscle in KG2, and `has` takes its meaning from the label it points at
# (see docs/kg2-schema.md). Both distinctions are lost if the key is the type.
EDGE_RULES: dict[EdgeTriple, EdgeRule] = {
    (_L.EXERCISE, _R.TARGETS, _L.MUSCLE): EdgeRule(
        GraphScope.KG1, "Which muscles the movement trains. Programming coverage."
    ),
    (_L.EXERCISE, _R.STRESSES, _L.ANATOMICAL_STRUCTURE): EdgeRule(
        GraphScope.KG1, "Load-bearing anatomy. Only ever points at the joint tier."
    ),
    (_L.EXERCISE, _R.REQUIRES, _L.EQUIPMENT): EdgeRule(
        GraphScope.KG1, "Kit the movement needs. The availability filter."
    ),
    (_L.EXERCISE, _R.IS_A, _L.MOVEMENT_PATTERN): EdgeRule(
        GraphScope.KG1, "Kinematic class. The axis equipment substitutions travel along."
    ),
    (_L.ANATOMICAL_STRUCTURE, _R.PART_OF, _L.ANATOMICAL_STRUCTURE): EdgeRule(
        GraphScope.KG1, "Self-nesting anatomy. Traversed both ways to bridge granularity."
    ),
    (_L.INJURY, _R.DIAGNOSED_AS, _L.CONDITION): EdgeRule(
        GraphScope.KG1, "Joins one member's case to the clinical knowledge about it."
    ),
    (_L.INJURY, _R.AFFECTS, _L.ANATOMICAL_STRUCTURE): EdgeRule(
        GraphScope.KG1, "Anatomical reference only. Never traversed to filter."
    ),
    (_L.CONDITION, _R.CONTRAINDICATES, _L.MOVEMENT_PATTERN): EdgeRule(
        GraphScope.KG1, "Hard exclude, carrying the rationale the trace reports."
    ),
    (_L.CONDITION, _R.CONTRAINDICATES, _L.EXERCISE): EdgeRule(
        GraphScope.KG1, "Hard exclude of a single movement rather than a whole pattern."
    ),
    (_L.CONDITION, _R.CAUTIONS, _L.MOVEMENT_PATTERN): EdgeRule(
        GraphScope.KG1, "Soft penalty. A relative contraindication, not a bar."
    ),
    (_L.CONDITION, _R.CAUTIONS, _L.EXERCISE): EdgeRule(
        GraphScope.KG1, "Soft penalty on a single movement rather than a whole pattern."
    ),
    (_L.MEMBER, _R.HAS, _L.GOAL): EdgeRule(GraphScope.KG2, "What she is training toward."),
    (_L.MEMBER, _R.HAS, _L.EQUIPMENT): EdgeRule(
        GraphScope.KG2, "What she owns. Filters KG1's requires."
    ),
    (_L.MEMBER, _R.HAS, _L.INJURY): EdgeRule(
        GraphScope.KG2, "Her recorded case, and the way in to the contraindication rules."
    ),
    (_L.MEMBER, _R.DISLIKES, _L.EXERCISE): EdgeRule(
        GraphScope.KG2, "Soft exclude. The only preference the graph models."
    ),
    (_L.GOAL, _R.TARGETS, _L.MUSCLE): EdgeRule(
        GraphScope.KG2, "What the goal trains. May be empty for a non-muscular goal."
    ),
    (_L.GOAL, _R.MEASURED_BY, _L.METRIC): EdgeRule(
        GraphScope.KG2, "How a goal with a number rather than muscles is scored."
    ),
    (_L.COACH, _R.COACHES, _L.MEMBER): EdgeRule(
        GraphScope.KG2, "Authority to read this member. The only edge auth consults."
    ),
    (_L.MEMBER, _R.HAS, _L.SESSION): EdgeRule(
        GraphScope.KG2, "A session on her record, completed or skipped."
    ),
    (_L.MEMBER, _R.HAS, _L.MESSAGE): EdgeRule(
        GraphScope.KG2, "One turn of the coach-member thread. Never a copilot turn."
    ),
    (_L.MEMBER, _R.HAS, _L.OBSERVATION): EdgeRule(
        GraphScope.KG2, "One measurement of one metric, on one date."
    ),
    (_L.SESSION, _R.TRAINED, _L.MOVEMENT_PATTERN): EdgeRule(
        GraphScope.KG2,
        "What class of work a session did. Pattern, not exercise: none of the "
        "recorded movements is in the catalog. Absent on a skipped session.",
    ),
    (_L.OBSERVATION, _R.MEASURES, _L.METRIC): EdgeRule(
        GraphScope.KG2, "Which quantity was measured, and so which band it is read against."
    ),
    # `mentions` reaches whatever the member's words landed on, so it is five
    # triples rather than one. Each is the same assertion about a different kind
    # of concept, which is why they share a sentence.
    **{
        (_L.MESSAGE, _R.MENTIONS, target): EdgeRule(
            GraphScope.KG2,
            "A concept named in writing. What gives a constraint a citation.",
        )
        for target in (
            _L.EXERCISE,
            _L.EQUIPMENT,
            _L.MUSCLE,
            _L.MOVEMENT_PATTERN,
            _L.ANATOMICAL_STRUCTURE,
        )
    },
}

# Labels only KG2 authors. Used to place an unrecognised triple when the rule
# table has no entry for it, so drift lands in a plausible scope instead of
# defaulting everything to KG1.
_KG2_AUTHORED: frozenset[NodeLabel] = frozenset(
    {
        NodeLabel.MEMBER,
        NodeLabel.GOAL,
        NodeLabel.COACH,
        NodeLabel.SESSION,
        NodeLabel.MESSAGE,
        NodeLabel.OBSERVATION,
        NodeLabel.METRIC,
    }
)


def rule_for(triple: EdgeTriple) -> EdgeRule | None:
    """Look up what a triple means.

    Args:
        triple: The `(from_label, rel_type, to_label)` observed in the store.

    Returns:
        The authored rule, or None when the store holds a shape this table does
        not describe.
    """
    return EDGE_RULES.get(triple)


def fallback_scope(from_label: NodeLabel) -> GraphScope:
    """Guess the owning subgraph for a triple with no authored rule.

    Args:
        from_label: Label of the node the edge leaves.

    Returns:
        `KG2` when only KG2's builder creates that label, `KG1` otherwise.
    """
    return GraphScope.KG2 if from_label in _KG2_AUTHORED else GraphScope.KG1
