import pytest

from api.graph_schema import EdgeRow, build_schema_graph
from api.models import GraphScope
from graph.schema import NodeLabel, RelType

_L = NodeLabel
_R = RelType


def _row(from_id: str, from_label: NodeLabel, rel: RelType, to_id: str, to_label: NodeLabel):
    return EdgeRow(
        from_id=from_id, from_label=from_label, rel=rel, to_id=to_id, to_label=to_label
    )


@pytest.fixture
def rows() -> list[EdgeRow]:
    """A miniature of the real store: both subgraphs meeting on shared nodes.

    Two exercises, of which the member owns the kit for one and dislikes the
    other — enough for every scope to produce a different answer.
    """
    return [
        # KG1: the catalog and its clinical rules.
        _row("ex1", _L.EXERCISE, _R.TARGETS, "m_glutes", _L.MUSCLE),
        _row("ex1", _L.EXERCISE, _R.TARGETS, "m_quads", _L.MUSCLE),
        _row("ex2", _L.EXERCISE, _R.TARGETS, "m_quads", _L.MUSCLE),
        _row("ex1", _L.EXERCISE, _R.REQUIRES, "eq_db", _L.EQUIPMENT),
        _row("ex2", _L.EXERCISE, _R.REQUIRES, "eq_bb", _L.EQUIPMENT),
        _row("ex1", _L.EXERCISE, _R.IS_A, "pat_squat", _L.MOVEMENT_PATTERN),
        _row("ex1", _L.EXERCISE, _R.STRESSES, "anat_knee", _L.ANATOMICAL_STRUCTURE),
        _row(
            "anat_knee", _L.ANATOMICAL_STRUCTURE, _R.PART_OF, "anat_limb", _L.ANATOMICAL_STRUCTURE
        ),
        _row("inj1", _L.INJURY, _R.DIAGNOSED_AS, "cond1", _L.CONDITION),
        _row("inj1", _L.INJURY, _R.AFFECTS, "anat_knee", _L.ANATOMICAL_STRUCTURE),
        _row("cond1", _L.CONDITION, _R.CAUTIONS, "pat_squat", _L.MOVEMENT_PATTERN),
        # KG2: the member, landing on nodes KG1 already created.
        _row("mem1", _L.MEMBER, _R.HAS, "goal1", _L.GOAL),
        _row("mem1", _L.MEMBER, _R.HAS, "eq_db", _L.EQUIPMENT),
        _row("mem1", _L.MEMBER, _R.HAS, "inj1", _L.INJURY),
        _row("mem1", _L.MEMBER, _R.DISLIKES, "ex2", _L.EXERCISE),
        _row("goal1", _L.GOAL, _R.TARGETS, "m_glutes", _L.MUSCLE),
    ]


def _count_for(graph, label: NodeLabel) -> int:
    return next((n.count for n in graph.node_types if n.label is label), 0)


def test_kg2_counts_what_the_member_reaches_not_the_catalog(rows):
    """The scope switch has to change the numbers, or it is decoration.

    Equipment is 2 across the catalog and 1 once the view narrows to what this
    member owns. If KG2 reported store totals instead, the whole premise of the
    overlay — seeing the member's reach carve down the catalog — would be lost.
    """
    kg2 = build_schema_graph(rows, GraphScope.KG2, node_total=13)

    assert _count_for(kg2, NodeLabel.EQUIPMENT) == 1
    assert _count_for(kg2, NodeLabel.EXERCISE) == 1
    assert _count_for(kg2, NodeLabel.MUSCLE) == 1
    assert kg2.totals.edges == 5

    kg1 = build_schema_graph(rows, GraphScope.KG1, node_total=13)
    assert _count_for(kg1, NodeLabel.EQUIPMENT) == 2
    assert _count_for(kg1, NodeLabel.EXERCISE) == 2


def test_shared_labels_come_from_edges_not_the_source_property(rows):
    """KG2 matches KG1's nodes rather than creating its own, so every shared
    node is stamped `source: kg1` in the store. Deriving `shared` from that
    property would mark nothing as shared and the union view would show no
    seam at all. These four are the green nodes in docs/kg2-schema.md.
    """
    graph = build_schema_graph(rows, GraphScope.BOTH, node_total=13)
    shared = {n.label for n in graph.node_types if n.shared}

    assert shared == {
        NodeLabel.EQUIPMENT,
        NodeLabel.EXERCISE,
        NodeLabel.MUSCLE,
        NodeLabel.INJURY,
    }


def test_shared_flag_survives_a_single_scope_request(rows):
    """Asking for KG1 alone still has to report that Equipment is shared.

    `shared` describes the store, not the request. Computing it only from
    in-scope rows would make the flag flip depending on which tab is open.
    """
    kg1 = build_schema_graph(rows, GraphScope.KG1, node_total=13)
    equipment = next(n for n in kg1.node_types if n.label is NodeLabel.EQUIPMENT)

    assert equipment.shared is True


def test_targets_splits_by_source_label(rows):
    """`targets` means two different things depending on where it starts.

    Exercise->Muscle is KG1 coverage; Goal->Muscle is KG2 intent. Keying the
    semantics table by relationship type alone would collapse them into one
    row and put half the member's graph in the wrong scope.
    """
    graph = build_schema_graph(rows, GraphScope.BOTH, node_total=13)
    targets = [e for e in graph.edge_types if e.rel is RelType.TARGETS]

    by_scope = {e.scope: e for e in targets}
    assert by_scope[GraphScope.KG1].from_label is NodeLabel.EXERCISE
    assert by_scope[GraphScope.KG1].count == 3
    assert by_scope[GraphScope.KG2].from_label is NodeLabel.GOAL
    assert by_scope[GraphScope.KG2].count == 1


def test_has_carries_a_different_meaning_per_target_label(rows):
    """docs/kg2-schema.md:20 makes the target label supply the meaning of
    `has`. One merged row for all three would drop that, and the viewer could
    not explain why owning equipment and having an injury are the same edge.
    """
    graph = build_schema_graph(rows, GraphScope.KG2, node_total=13)
    has_rows = [e for e in graph.edge_types if e.rel is RelType.HAS]

    assert {e.to_label for e in has_rows} == {
        NodeLabel.GOAL,
        NodeLabel.EQUIPMENT,
        NodeLabel.INJURY,
    }
    assert all(e.semantics for e in has_rows)
    assert len({e.semantics for e in has_rows}) == 3


def test_unknown_triple_is_reported_rather_than_dropped(rows):
    """A builder writing a shape the API has no rule for must stay visible.

    Dropping it would make the viewer quietly disagree with the store, which
    is the one thing an audit surface cannot do.
    """
    drifted = [*rows, _row("goal1", _L.GOAL, _R.HAS, "m_quads", _L.MUSCLE)]
    graph = build_schema_graph(drifted, GraphScope.BOTH, node_total=13)

    unknown = [e for e in graph.edge_types if e.semantics is None]
    assert len(unknown) == 1
    assert unknown[0].from_label is NodeLabel.GOAL
    # Only KG2's builder writes Goal, so the drift lands there rather than
    # defaulting into KG1.
    assert unknown[0].scope is GraphScope.KG2


def test_orphans_are_store_wide_not_per_scope(rows):
    """Counting orphans within a scope would report every catalog exercise
    outside the member's reach as an orphan on the KG2 tab — turning a data
    integrity signal into permanent false alarm.
    """
    connected = build_schema_graph(rows, GraphScope.KG2, node_total=13)
    assert connected.totals.orphan_nodes == 0

    with_strays = build_schema_graph(rows, GraphScope.KG2, node_total=15)
    assert with_strays.totals.orphan_nodes == 2
