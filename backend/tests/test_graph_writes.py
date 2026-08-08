import pytest

from graph.build.writes import merge_nodes
from graph.driver import graph_session
from graph.schema import GraphSource, NodeLabel

# A name no catalog row uses, so the probe cannot collide with real data.
PROBE = "__writes_probe__"


@pytest.fixture(scope="module")
def session():
    """One Neo4j session, with the probe node removed either side."""
    with graph_session() as open_session:
        open_session.run(f"MATCH (n {{name: '{PROBE}'}}) DETACH DELETE n")
        yield open_session
        open_session.run(f"MATCH (n {{name: '{PROBE}'}}) DETACH DELETE n")


def properties(session, name: str) -> dict:
    """Every property currently on the probe node."""
    record = session.run(
        f"MATCH (n:{NodeLabel.EQUIPMENT} {{name: $name}}) RETURN properties(n) AS props",
        name=name,
    ).single()
    return record["props"] if record else {}


def test_a_removed_field_disappears_on_rebuild(session) -> None:
    """A field dropped from the source data leaves no stale value behind.

    `SET n += row` adds keys and never removes them, so renaming a catalog
    column leaves the old name readable holding its old value — after
    `estimated_rep_duration` became `estimated_rep_seconds` and was inverted,
    a query reaching for the old name would have got the reciprocal rather
    than an error. Silently wrong beats loudly broken only for the machine.
    """
    merge_nodes(
        session,
        NodeLabel.EQUIPMENT,
        "name",
        [{"name": PROBE, "renamed_away": 0.3, "kept": "yes"}],
        GraphSource.KG1,
    )
    assert properties(session, PROBE)["renamed_away"] == 0.3

    merge_nodes(
        session,
        NodeLabel.EQUIPMENT,
        "name",
        [{"name": PROBE, "renamed_to": 3.33, "kept": "yes"}],
        GraphSource.KG1,
    )
    after = properties(session, PROBE)
    assert "renamed_away" not in after
    assert after["renamed_to"] == 3.33
    assert after["kept"] == "yes"


def test_rebuilding_keeps_the_source_stamp(session) -> None:
    """`source` survives a replace, though no row carries it.

    It is set alongside the row rather than inside it, so switching from merge
    to replace could have dropped it — and every node would stop declaring
    which subgraph built it.
    """
    merge_nodes(session, NodeLabel.EQUIPMENT, "name", [{"name": PROBE}], GraphSource.KG1)
    assert properties(session, PROBE)["source"] == GraphSource.KG1.value
