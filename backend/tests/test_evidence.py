from graph.evidence import EvidencePath, Hop
from graph.schema import NodeLabel, RelType


def test_hop_renders_rel_and_name() -> None:
    """A hop reads as the edge it walked.

    The rendered form lands verbatim in retry messages and coach-facing
    provenance; a wrong rendering misattributes a clinical decision.
    """
    hop = Hop(rel=RelType.DIAGNOSED_AS, to_label=NodeLabel.CONDITION, to_name="pfps")
    assert hop.render() == "-diagnosed_as-> pfps"


def test_path_renders_entry_then_hops() -> None:
    """A path reads entry-first, hops in traversal order."""
    path = EvidencePath(
        entry="inj_knee_left",
        hops=(
            Hop(
                rel=RelType.DIAGNOSED_AS,
                to_label=NodeLabel.CONDITION,
                to_name="patellofemoral pain syndrome",
            ),
            Hop(
                rel=RelType.CAUTIONS,
                to_label=NodeLabel.MOVEMENT_PATTERN,
                to_name="lower push - squat",
            ),
        ),
    )
    assert path.render() == (
        "inj_knee_left -diagnosed_as-> patellofemoral pain syndrome "
        "-cautions-> lower push - squat"
    )


def test_empty_hops_renders_entry_alone() -> None:
    """A hopless path is just its entry — a fact, not a traversal."""
    assert EvidencePath(entry="exercise:X").render() == "exercise:X"
