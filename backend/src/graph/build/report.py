from neo4j import Session
from pydantic import BaseModel

from graph.schema import NodeLabel, RelType


class BuildReport(BaseModel):
    """What actually landed in the store, read back after a build."""

    nodes_by_label: dict[str, int]
    edges_by_type: dict[str, int]

    @property
    def node_total(self) -> int:
        return sum(self.nodes_by_label.values())

    @property
    def edge_total(self) -> int:
        return sum(self.edges_by_type.values())


def read_report(session: Session) -> BuildReport:
    """Count what is in the store, rather than what a build believes it wrote.

    Args:
        session: An open Neo4j session.

    Returns:
        Counts for every known label and relationship type, including zeroes.
    """
    # Labels and relationship types cannot be query parameters in Cypher, so
    # they are interpolated. Values come from the enums, never from input data.
    nodes = {
        label.value: session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]
        for label in NodeLabel
    }
    edges = {
        rel.value: session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c").single()["c"]
        for rel in RelType
    }
    return BuildReport(nodes_by_label=nodes, edges_by_type=edges)
