from typing import Any

import pytest

from api.instances import caption_for, read_instances
from api.models import GraphScope
from graph.schema import NodeLabel

_NODES: list[dict[str, Any]] = [
    {"id": "m1", "label": "Member", "props": {"name": "Jordan Rivera", "id": "mbr_1"}},
    {"id": "g1", "label": "Goal", "props": {"text": "Build lower-body strength", "id": "goal_1"}},
    {"id": "mu1", "label": "Muscle", "props": {"name": "glutes"}},
    {"id": "ex1", "label": "Exercise", "props": {"name": "Barbell Squat", "id": "ex_1"}},
    {"id": "eq1", "label": "Equipment", "props": {"name": "Barbell"}},
]

_EDGES: list[dict[str, Any]] = [
    {"id": "e1", "source": "m1", "target": "g1", "rel": "has", "props": {}},
    {"id": "e2", "source": "g1", "target": "mu1", "rel": "targets", "props": {}},
    {"id": "e3", "source": "ex1", "target": "mu1", "rel": "targets", "props": {}},
    {"id": "e4", "source": "ex1", "target": "eq1", "rel": "requires", "props": {}},
]


class _FakeSession:
    def run(self, query: str, **_: Any) -> list[dict[str, Any]]:
        if "count(n)" in query:
            return [{"c": len(_NODES)}]
        return _EDGES if "-[r]->" in query else _NODES


def test_scope_keeps_only_nodes_its_edges_touch():
    """The KG2 view must not list every exercise in the catalogue.

    Nodes come back from one unfiltered query, so without the incidence rule
    the member view would draw all fifty exercises floating unconnected —
    exactly the "picture of nothing" the neighbourhood default exists to avoid.
    """
    kg2 = read_instances(_FakeSession(), GraphScope.KG2)

    assert {n.id for n in kg2.nodes} == {"m1", "g1", "mu1"}
    assert {e.id for e in kg2.edges} == {"e1", "e2"}

    kg1 = read_instances(_FakeSession(), GraphScope.KG1)
    assert {n.id for n in kg1.nodes} == {"ex1", "mu1", "eq1"}


def test_muscle_is_reachable_from_both_sides():
    """glutes sits on a KG1 edge and a KG2 edge, so the union must not
    duplicate it — the seam is one node, not two.
    """
    both = read_instances(_FakeSession(), GraphScope.BOTH)

    assert len(both.nodes) == 5
    assert len([n for n in both.nodes if n.id == "mu1"]) == 1
    assert len(both.edges) == 4


def test_targets_scope_splits_by_source_label():
    """Goal->Muscle and Exercise->Muscle share a relationship type. If scope
    were decided by type alone, the member view would pull in every exercise's
    muscle coverage as well as her goals'.
    """
    graph = read_instances(_FakeSession(), GraphScope.BOTH)
    by_id = {e.id: e for e in graph.edges}

    assert by_id["e2"].scope is GraphScope.KG2
    assert by_id["e3"].scope is GraphScope.KG1


@pytest.mark.parametrize(
    ("label", "props", "expected"),
    [
        (NodeLabel.MEMBER, {"name": "Jordan Rivera"}, "Jordan Rivera"),
        # Goal holds its human text under `text`, not `name`.
        (NodeLabel.GOAL, {"text": "Sleep 7+ hours", "id": "goal_sleep"}, "Sleep 7+ hours"),
        # Injury has neither, and `region` already reads as a phrase.
        (NodeLabel.INJURY, {"region": "left knee", "id": "inj_1"}, "left knee"),
        (NodeLabel.INJURY, {"joint": "knee", "id": "inj_2"}, "knee"),
        # Nothing readable at all still has to draw with something on it.
        (NodeLabel.EQUIPMENT, {"id": "eq_9"}, "eq_9"),
        (NodeLabel.EQUIPMENT, {}, "Equipment"),
    ],
)
def test_caption_falls_back_rather_than_drawing_a_blank_node(label, props, expected):
    """Every label keeps its human name under a different property. Picking the
    wrong one leaves an unlabelled box the coach cannot identify.
    """
    assert caption_for(label, props) == expected
