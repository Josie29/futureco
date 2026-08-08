from typing import Any

from neo4j import Session
from pydantic import BaseModel, ConfigDict

from graph.schema import AnatomicalTier, GraphSource, NodeLabel, RelType


class NodeMatch(BaseModel):
    """How to find a node that already exists.

    Attributes:
        label: The node's label.
        key: Property the row value is matched against.
        tier: When set, the node must also sit at this anatomical tier. This is
            what keeps `stresses` and `affects` from reaching a region.
    """

    model_config = ConfigDict(frozen=True)

    label: NodeLabel
    key: str = "name"
    tier: AnatomicalTier | None = None

    def pattern(self, alias: str, value: str) -> str:
        """Render this as a Cypher node pattern.

        Args:
            alias: Variable to bind the node to.
            value: Cypher expression holding the value to match, such as
                `row.target`.

        Returns:
            A pattern such as `(t:AnatomicalStructure {name: row.target, tier: 'joint'})`.
        """
        props = f"{self.key}: {value}"
        if self.tier:
            # A literal, not a parameter: the value comes from the enum, and
            # keeping it inline lets the whole pattern read as one string.
            props += f", tier: '{self.tier}'"
        return f"({alias}:{self.label} {{{props}}})"


class EdgeWrite(BaseModel):
    """Where an edge runs, and how to find the two nodes it joins.

    Attributes:
        rel: The relationship type to create.
        source: How to find the node the edge leaves.
        target: How to find the node the edge reaches.
        properties: Row fields to copy onto the edge, such as a `rationale`.
    """

    model_config = ConfigDict(frozen=True)

    rel: RelType
    source: NodeMatch
    target: NodeMatch
    properties: tuple[str, ...] = ()


def merge_nodes(
    session: Session,
    label: NodeLabel,
    key: str,
    rows: list[dict[str, Any]],
    source: GraphSource,
) -> None:
    """Create or update one node per row, keyed by a single property.

    Every field of a row lands on the node, so callers shape the row to hold
    exactly what belongs there — authoring metadata and values that are better
    expressed as edges are dropped before calling.

    Args:
        session: An open Neo4j session.
        label: Label to give the nodes.
        key: Property that identifies a node. A uniqueness constraint should
            already exist on it, or `MERGE` degrades to a full label scan.
        rows: One dict per node, each containing `key`.
        source: Which logical subgraph these nodes belong to.
    """
    if not rows:
        return
    session.run(
        f"""
        UNWIND $rows AS row
        MERGE (n:{label} {{{key}: row.{key}}})
        SET n += row, n.source = $source
        """,
        rows=rows,
        source=source.value,
    )


def link_nodes(session: Session, edge: EdgeWrite, rows: list[dict[str, Any]]) -> int:
    """Create edges between nodes that already exist.

    Neither end is created. A row naming a node that is absent writes nothing
    and is counted as unresolved, which is what the return value reports.

    Args:
        session: An open Neo4j session.
        edge: Where the edge runs and how to find its ends.
        rows: One dict per edge, each with `source` and `target` plus any
            fields named in `edge.properties`.

    Returns:
        How many edges were written, which is at most `len(rows)`.
    """
    if not rows:
        return 0
    assignments = ", ".join(f"r.{name} = row.{name}" for name in edge.properties)
    return session.run(
        f"""
        UNWIND $rows AS row
        MATCH {edge.source.pattern("s", "row.source")}
        MATCH {edge.target.pattern("t", "row.target")}
        MERGE (s)-[r:{edge.rel}]->(t)
        {f"SET {assignments}" if assignments else ""}
        RETURN count(*) AS linked
        """,
        rows=rows,
    ).single()["linked"]


def unmatched(session: Session, node: NodeMatch, values: set[str]) -> list[str]:
    """Find which of `values` name no node.

    Args:
        session: An open Neo4j session.
        node: How the values would be looked up.
        values: Candidate key values.

    Returns:
        The values with no matching node, sorted.
    """
    if not values:
        return []
    return session.run(
        f"""
        UNWIND $values AS value
        OPTIONAL MATCH {node.pattern("n", "value")}
        WITH value WHERE n IS NULL
        RETURN collect(value) AS missing
        """,
        values=sorted(values),
    ).single()["missing"]


def link_required(session: Session, edge: EdgeWrite, rows: list[dict[str, Any]]) -> None:
    """Create edges, insisting that every row resolves.

    Use this wherever a missing edge would make the graph misleading rather
    than merely incomplete — a severed anatomy hierarchy, or a contraindication
    that never reaches the movement it forbids. Those failures are silent in
    the store and permissive in a filter, so they have to stop the build.

    Args:
        session: An open Neo4j session.
        edge: Where the edge runs and how to find its ends.
        rows: One dict per edge.

    Raises:
        ValueError: If any row named a node that does not exist. The message
            names the values that failed, since that is what a fix needs.
    """
    linked = link_nodes(session, edge, rows)
    if linked == len(rows):
        return

    ends = {
        "source": (edge.source, {row["source"] for row in rows}),
        "target": (edge.target, {row["target"] for row in rows}),
    }
    detail = "; ".join(
        f"{end} {node.label} not found: {missing}"
        for end, (node, values) in ends.items()
        if (missing := unmatched(session, node, values))
    )
    raise ValueError(f"{edge.rel} resolved {linked} of {len(rows)} edges — {detail}")
