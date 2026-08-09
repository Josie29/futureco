from typing import Any

from neo4j import Session

from api.models import GraphEdge, GraphNode, GraphScope, InstanceGraph, NodeLabel, RelType
from api.semantics import fallback_scope, rule_for

# Hard ceiling on a single response. The sample graph is 170 nodes, so this is
# headroom rather than a limit today — but an unbounded MATCH (n) is the query
# that stops being safe first as a catalog grows.
MAX_NODES = 3000

_ALL_NODES = "MATCH (n) RETURN elementId(n) AS id, labels(n)[0] AS label, properties(n) AS props"

_ALL_EDGES = """
MATCH (a)-[r]->(b)
RETURN elementId(r) AS id, elementId(a) AS source, elementId(b) AS target,
       type(r) AS rel, properties(r) AS props
"""

# Undirected on purpose: a coach exploring outward from Jordan expects to reach
# the exercises that require her equipment, and those edges point at it.
_NEIGHBOURHOOD = """
MATCH (root) WHERE elementId(root) = $root
CALL {{
  WITH root
  MATCH path = (root)-[*1..{depth}]-(other)
  RETURN nodes(path) AS ns, relationships(path) AS rs
}}
UNWIND ns AS n
WITH root, collect(DISTINCT n) AS nodes, collect(rs) AS rel_lists
UNWIND rel_lists AS rl
UNWIND rl AS r
RETURN [x IN nodes | {{id: elementId(x), label: labels(x)[0], props: properties(x)}}] AS nodes,
       collect(DISTINCT {{id: elementId(r), source: elementId(startNode(r)),
                          target: elementId(endNode(r)), rel: type(r),
                          props: properties(r)}}) AS edges
"""


def caption_for(label: NodeLabel, props: dict[str, Any]) -> str:
    """Pick the string a human would call this node.

    Args:
        label: The node's label.
        props: Its property bag.

    Returns:
        A display string. Falls back to the id, then the label, so a node with
        no readable property still draws with something on it.
    """
    for key in ("name", "text", "title"):
        value = props.get(key)
        if value:
            return str(value)

    if label is NodeLabel.INJURY:
        # No name property; `region` already reads as "left knee".
        region = props.get("region") or props.get("joint")
        if region:
            return str(region)

    if label is NodeLabel.OBSERVATION:
        # "sleep_hours 6.1" rather than the id, so a fan of 28 observations
        # around one member is readable without opening each node.
        metric, value = props.get("metric_id"), props.get("value")
        if metric is not None and value is not None:
            return f"{metric} {value}"

    if label is NodeLabel.MESSAGE:
        # The opening words, which is how anyone refers to a message. Truncated
        # because a caption is a label on a node, not the message itself — the
        # full text is in the property panel.
        text = str(props.get("text") or "")
        if text:
            return text if len(text) <= 40 else f"{text[:39]}…"

    return str(props.get("id") or label.value)


def _node_from(row: dict[str, Any]) -> GraphNode | None:
    try:
        label = NodeLabel(row["label"])
    except ValueError:
        return None
    props = dict(row["props"])
    return GraphNode(id=row["id"], label=label, caption=caption_for(label, props), props=props)


def _edge_from(row: dict[str, Any], labels: dict[str, NodeLabel]) -> GraphEdge | None:
    try:
        rel = RelType(row["rel"])
    except ValueError:
        return None
    from_label = labels.get(row["source"])
    to_label = labels.get(row["target"])
    if from_label is None or to_label is None:
        return None

    rule = rule_for((from_label, rel, to_label))
    return GraphEdge(
        id=row["id"],
        source=row["source"],
        target=row["target"],
        rel=rel,
        scope=rule.scope if rule else fallback_scope(from_label),
        props=dict(row["props"]),
    )


def _assemble(
    node_rows: list[dict[str, Any]],
    edge_rows: list[dict[str, Any]],
    scope: GraphScope,
    root_id: str | None,
    truncated: bool,
) -> InstanceGraph:
    """Turn raw rows into a drawable graph, filtered to one scope.

    Nodes are kept only if an in-scope edge touches them, matching how the
    schema view counts. Dropping that rule would leave the KG2 view showing all
    fifty exercises with two edges between them.
    """
    nodes = {n.id: n for row in node_rows if (n := _node_from(row))}
    labels = {node_id: node.label for node_id, node in nodes.items()}

    edges = [e for row in edge_rows if (e := _edge_from(row, labels))]
    if scope is not GraphScope.BOTH:
        edges = [e for e in edges if e.scope is scope]

    reachable = {e.source for e in edges} | {e.target for e in edges}
    if root_id:
        reachable.add(root_id)

    return InstanceGraph(
        scope=scope,
        nodes=[n for n in nodes.values() if n.id in reachable],
        edges=edges,
        root_id=root_id,
        truncated=truncated,
    )


def read_instances(session: Session, scope: GraphScope) -> InstanceGraph:
    """Read every node and relationship in the store.

    Args:
        session: An open Neo4j session.
        scope: Which subgraph to keep.

    Returns:
        The whole graph for that scope, capped at `MAX_NODES`.
    """
    node_rows = [dict(r) for r in session.run(_ALL_NODES)]
    truncated = len(node_rows) > MAX_NODES
    if truncated:
        node_rows = node_rows[:MAX_NODES]

    edge_rows = [dict(r) for r in session.run(_ALL_EDGES)]
    return _assemble(node_rows, edge_rows, scope, None, truncated)


def read_neighbourhood(
    session: Session, root_id: str, depth: int, scope: GraphScope
) -> InstanceGraph:
    """Read the subgraph within `depth` hops of one node.

    Args:
        session: An open Neo4j session.
        root_id: `elementId` of the node to expand from.
        depth: Hop count, 1 to 3. Interpolated into the query because Cypher
            does not accept a parameter inside a variable-length pattern; the
            value is clamped to an int first, never passed through from input.
        scope: Which subgraph to keep.

    Returns:
        The subgraph, or an empty graph if the root does not exist.
    """
    hops = max(1, min(3, int(depth)))
    record = session.run(_NEIGHBOURHOOD.format(depth=hops), root=root_id).single()
    if record is None:
        return InstanceGraph(scope=scope, nodes=[], edges=[], root_id=root_id, truncated=False)

    node_rows = [dict(n) for n in record["nodes"]]
    truncated = len(node_rows) > MAX_NODES
    if truncated:
        node_rows = node_rows[:MAX_NODES]

    return _assemble(node_rows, [dict(e) for e in record["edges"]], scope, root_id, truncated)


def find_root(session: Session, label: NodeLabel) -> str | None:
    """Find a node to open the explorer on.

    Args:
        session: An open Neo4j session.
        label: The label to look for.

    Returns:
        The `elementId` of one such node, or None if the store has none.
    """
    record = session.run(
        f"MATCH (n:{label}) RETURN elementId(n) AS id LIMIT 1"  # label comes from the enum
    ).single()
    return record["id"] if record else None
