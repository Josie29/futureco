/** Wire contracts for the graph inspector.
 *
 * Mirrors `backend/src/api/models.py` and `backend/src/graph/schema.py`
 * one-for-one. The Python side uses StrEnum, so these are real TS enums with
 * matching values rather than string unions.
 */

/** Neo4j node labels. Values are the literal labels used in Cypher. */
export enum NodeLabel {
  EXERCISE = "Exercise",
  MUSCLE = "Muscle",
  EQUIPMENT = "Equipment",
  MOVEMENT_PATTERN = "MovementPattern",
  ANATOMICAL_STRUCTURE = "AnatomicalStructure",
  INJURY = "Injury",
  CONDITION = "Condition",
  MEMBER = "Member",
  GOAL = "Goal",
}

/** Neo4j relationship types. */
export enum RelType {
  TARGETS = "targets",
  STRESSES = "stresses",
  REQUIRES = "requires",
  IS_A = "is_a",
  PART_OF = "part_of",
  AFFECTS = "affects",
  DIAGNOSED_AS = "diagnosed_as",
  CONTRAINDICATES = "contraindicates",
  CAUTIONS = "cautions",
  HAS = "has",
  DISLIKES = "dislikes",
}

/** Which subgraph a request asks for. Edges are only ever KG1 or KG2. */
export enum GraphScope {
  KG1 = "kg1",
  KG2 = "kg2",
  BOTH = "both",
}

export interface NodeTypeSummary {
  label: NodeLabel
  /** Distinct nodes an in-scope edge touches — not the store total. */
  count: number
  /** True when both subgraphs have edges touching this label. */
  shared: boolean
}

export interface EdgeTypeSummary {
  rel: RelType
  from_label: NodeLabel
  to_label: NodeLabel
  count: number
  scope: GraphScope.KG1 | GraphScope.KG2
  /** Null marks a triple the API has no rule for — a schema-drift signal. */
  semantics: string | null
}

export interface SchemaTotals {
  node_types: number
  edge_types: number
  nodes: number
  edges: number
  /** Store-wide: nodes no edge anywhere touches. */
  orphan_nodes: number
}

export interface SchemaGraph {
  scope: GraphScope
  node_types: NodeTypeSummary[]
  edge_types: EdgeTypeSummary[]
  totals: SchemaTotals
}

export interface GraphNode {
  id: string
  label: NodeLabel
  /** What to print on the node, resolved server-side. */
  caption: string
  props: Record<string, unknown>
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  rel: RelType
  scope: GraphScope.KG1 | GraphScope.KG2
  props: Record<string, unknown>
}

export interface InstanceGraph {
  scope: GraphScope
  nodes: GraphNode[]
  edges: GraphEdge[]
  root_id: string | null
  truncated: boolean
}

/** The shape the API returns for an outage, alongside a 4xx/5xx status. */
export interface ApiProblem {
  detail: string
  remedy?: string
  code?: string
}

/** Short human labels for the node types, for use where the CamelCase
 *  Neo4j label would read as a database artifact rather than a concept. */
export const NODE_LABEL_TEXT: Record<NodeLabel, string> = {
  [NodeLabel.EXERCISE]: "Exercise",
  [NodeLabel.MUSCLE]: "Muscle",
  [NodeLabel.EQUIPMENT]: "Equipment",
  [NodeLabel.MOVEMENT_PATTERN]: "Movement pattern",
  [NodeLabel.ANATOMICAL_STRUCTURE]: "Anatomy",
  [NodeLabel.INJURY]: "Injury",
  [NodeLabel.CONDITION]: "Condition",
  [NodeLabel.MEMBER]: "Member",
  [NodeLabel.GOAL]: "Goal",
}
