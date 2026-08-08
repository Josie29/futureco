from fastapi import APIRouter, Query

from api.deps import GraphSession
from api.graph_schema import build_schema_graph, read_edge_rows, read_node_total
from api.instances import find_root, read_instances, read_neighbourhood
from api.models import GraphScope, InstanceGraph, NodeLabel, SchemaGraph

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/schema", summary="Node and edge types with live counts")
def get_schema(session: GraphSession, scope: GraphScope = GraphScope.BOTH) -> SchemaGraph:
    """Read the meta-graph: what types exist and how they connect.

    Args:
        session: An open Neo4j session.
        scope: Which subgraph to describe. Defaults to the union.

    Returns:
        Node types, edge types, and totals, all counted from the store.
    """
    rows = read_edge_rows(session)
    return build_schema_graph(rows, scope, read_node_total(session))


@router.get("/instances", summary="Real nodes and relationships")
def get_instances(
    session: GraphSession,
    scope: GraphScope = GraphScope.BOTH,
    root: str | None = None,
    depth: int = Query(default=1, ge=1, le=3),
    full: bool = False,
) -> InstanceGraph:
    """Read actual data — Jordan and her goals, rather than Member and Goal.

    Defaults to the member's own neighbourhood, because opening on 170 nodes
    is a picture of nothing. Pass `full=true` for the whole graph, or `root`
    with `depth` to expand from any node.

    Args:
        session: An open Neo4j session.
        scope: Which subgraph to keep.
        root: `elementId` to expand from. Defaults to the Member node.
        depth: Hops from the root, 1 to 3.
        full: Return every node instead of a neighbourhood.

    Returns:
        Nodes and edges, each carrying its properties.
    """
    if full:
        return read_instances(session, scope)

    start = root or find_root(session, NodeLabel.MEMBER)
    if start is None:
        # No member in the store, so there is no sensible focus. The whole
        # graph is a better answer than an empty one.
        return read_instances(session, scope)
    return read_neighbourhood(session, start, depth, scope)
