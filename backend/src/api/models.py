from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from graph.schema import NodeLabel, RelType


class GraphScope(StrEnum):
    """Which logical subgraph a request asks for.

    `KG1` and `KG2` also tag individual edges. `BOTH` is a request-level value
    only — every edge belongs to exactly one subgraph, never to both.
    """

    KG1 = "kg1"
    KG2 = "kg2"
    BOTH = "both"


class NodeTypeSummary(BaseModel):
    """One node label, counted within the requested scope."""

    label: NodeLabel
    count: int
    shared: bool
    """True when both subgraphs have edges touching this label.

    Computed from the edges present in the store rather than read from the
    node's `source` property. KG2's builder matches existing KG1 nodes instead
    of creating its own, so a shared node is stamped `source: kg1` and that
    property cannot tell the two apart.
    """


class EdgeTypeSummary(BaseModel):
    """One `(from)-[rel]->(to)` triple, counted across the whole store."""

    rel: RelType
    from_label: NodeLabel
    to_label: NodeLabel
    count: int
    scope: GraphScope
    semantics: str | None
    """What the edge means, or None for a triple this API has no rule for.

    A null reading is a schema-drift signal: the builder wrote a shape the API
    was never told about. Surfaced rather than dropped.
    """


class SchemaTotals(BaseModel):
    """Roll-up for the requested scope."""

    node_types: int
    edge_types: int
    nodes: int
    edges: int
    orphan_nodes: int
    """Nodes in the store that no in-scope edge touches.

    Non-zero means the build produced nodes nothing connects to, which the
    counts alone would hide.
    """


class SchemaGraph(BaseModel):
    """The meta-graph: node and edge types rather than instances."""

    scope: GraphScope
    node_types: list[NodeTypeSummary]
    edge_types: list[EdgeTypeSummary]
    totals: SchemaTotals


class GraphNode(BaseModel):
    """One real node, with enough to draw it and to inspect it."""

    id: str
    label: NodeLabel
    caption: str
    """What to print on the node. Resolved server-side because the property
    holding the human name differs per label — `name` on most, `text` on Goal,
    and nothing usable on Injury."""
    props: dict[str, Any]


class GraphEdge(BaseModel):
    """One real relationship."""

    id: str
    source: str
    target: str
    rel: RelType
    scope: GraphScope
    props: dict[str, Any]
    """Carries `rationale` on the contraindication edges, which is the text the
    provenance trace quotes."""


class InstanceGraph(BaseModel):
    """Actual data: Jordan and her goals, not Member and Goal."""

    scope: GraphScope
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    root_id: str | None
    """The node the view opens on, when the caller asked for one."""
    truncated: bool
    """True when a node cap stopped the result short of the full subgraph, so
    the UI can say so rather than implying it drew everything."""
