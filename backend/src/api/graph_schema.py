from collections import defaultdict

from neo4j import Session
from pydantic import BaseModel

from api.models import (
    EdgeTypeSummary,
    GraphScope,
    NodeTypeSummary,
    SchemaGraph,
    SchemaTotals,
)
from api.semantics import EdgeTriple, fallback_scope, rule_for
from graph.schema import NodeLabel, RelType

# Every edge in the store, with both endpoints identified. ~450 rows on the
# sample data, so the aggregation is cheaper to do in Python than as five
# separate Cypher round-trips.
_EDGES_QUERY = """
MATCH (a)-[r]->(b)
RETURN elementId(a) AS from_id, labels(a)[0] AS from_label,
       type(r) AS rel,
       elementId(b) AS to_id, labels(b)[0] AS to_label
"""

_NODE_TOTAL_QUERY = "MATCH (n) RETURN count(n) AS c"


class EdgeRow(BaseModel):
    """One edge, flattened to its endpoints' identities and labels."""

    from_id: str
    from_label: NodeLabel
    rel: RelType
    to_id: str
    to_label: NodeLabel

    @property
    def triple(self) -> EdgeTriple:
        """The `(from, rel, to)` key the semantics table is indexed by."""
        return (self.from_label, self.rel, self.to_label)


def read_edge_rows(session: Session) -> list[EdgeRow]:
    """Read every edge in the store with both endpoints.

    Rows carrying a label or type outside the schema enums are skipped: the
    wire contract is typed to those enums, so an unknown value has nowhere to
    go. The builder only ever writes enum values, so this is a guard against a
    hand-edited store rather than an expected path.

    Args:
        session: An open Neo4j session.

    Returns:
        One row per edge, in no particular order.
    """
    rows: list[EdgeRow] = []
    for record in session.run(_EDGES_QUERY):
        try:
            rows.append(
                EdgeRow(
                    from_id=record["from_id"],
                    from_label=NodeLabel(record["from_label"]),
                    rel=RelType(record["rel"]),
                    to_id=record["to_id"],
                    to_label=NodeLabel(record["to_label"]),
                )
            )
        except ValueError:
            continue
    return rows


def read_node_total(session: Session) -> int:
    """Count every node in the store, regardless of label.

    Args:
        session: An open Neo4j session.

    Returns:
        The total node count.
    """
    record = session.run(_NODE_TOTAL_QUERY).single()
    return record["c"] if record else 0


def _scope_of(row: EdgeRow) -> GraphScope:
    """Decide which subgraph authored an edge."""
    rule = rule_for(row.triple)
    return rule.scope if rule else fallback_scope(row.from_label)


def build_schema_graph(rows: list[EdgeRow], scope: GraphScope, node_total: int) -> SchemaGraph:
    """Aggregate raw edges into the meta-graph for one scope.

    Node counts are the distinct nodes an in-scope edge touches, not the store
    totals. That is what makes the scope switch informative: Equipment is 32
    across the catalog and 5 once the view narrows to what this member owns.

    Args:
        rows: Every edge in the store, from `read_edge_rows`.
        scope: The subgraph asked for. `BOTH` keeps every edge.
        node_total: Store-wide node count, used to derive orphans.

    Returns:
        Node types, edge types, and totals for the requested scope.
    """
    edge_counts: dict[EdgeTriple, int] = defaultdict(int)
    nodes_by_label: dict[NodeLabel, set[str]] = defaultdict(set)
    labels_by_scope: dict[GraphScope, set[NodeLabel]] = defaultdict(set)
    connected: set[str] = set()

    for row in rows:
        connected.add(row.from_id)
        connected.add(row.to_id)

        row_scope = _scope_of(row)
        # `shared` is a property of the whole store, so both endpoints are
        # recorded against their authoring subgraph on every pass, including
        # the rows the requested scope is about to discard.
        labels_by_scope[row_scope].add(row.from_label)
        labels_by_scope[row_scope].add(row.to_label)

        if scope is not GraphScope.BOTH and row_scope is not scope:
            continue

        edge_counts[row.triple] += 1
        nodes_by_label[row.from_label].add(row.from_id)
        nodes_by_label[row.to_label].add(row.to_id)

    shared_labels = labels_by_scope[GraphScope.KG1] & labels_by_scope[GraphScope.KG2]

    node_types = [
        NodeTypeSummary(label=label, count=len(ids), shared=label in shared_labels)
        for label, ids in sorted(nodes_by_label.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]

    edge_types: list[EdgeTypeSummary] = []
    for triple, count in sorted(edge_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        from_label, rel, to_label = triple
        rule = rule_for(triple)
        edge_types.append(
            EdgeTypeSummary(
                rel=rel,
                from_label=from_label,
                to_label=to_label,
                count=count,
                scope=rule.scope if rule else fallback_scope(from_label),
                semantics=rule.semantics if rule else None,
            )
        )

    return SchemaGraph(
        scope=scope,
        node_types=node_types,
        edge_types=edge_types,
        totals=SchemaTotals(
            node_types=len(node_types),
            edge_types=len(edge_types),
            nodes=sum(len(ids) for ids in nodes_by_label.values()),
            edges=sum(edge_counts.values()),
            # Store-wide and scope-independent: a node no edge anywhere
            # touches. Counting per-scope would report every catalog exercise
            # outside this member's reach as an orphan, which they are not.
            orphan_nodes=max(0, node_total - len(connected)),
        ),
    )
