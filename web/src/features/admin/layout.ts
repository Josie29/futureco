import { NodeLabel, type EdgeTypeSummary, type NodeTypeSummary } from "@/types/graph"

/**
 * Which column a node type sits in.
 *
 * The bands are the argument this view makes: KG2 is not a peer graph beside
 * KG1, it is a lens onto it, and the two meet on four shared node types. Put
 * those four in the middle and the seam is the picture.
 */
export enum Band {
  KG1_ONLY = "kg1_only",
  SHARED = "shared",
  KG2_ONLY = "kg2_only",
}

/** Preferred vertical order, chosen to keep edge crossings down.
 *
 * Ordering only — band membership comes from the API's `shared` flag, never
 * from this list. A node not named here still places, at the end of its band.
 * Authored rather than sorted by count so a node keeps its position when the
 * scope changes: a layout that re-sorts on every toggle reads as three
 * unrelated diagrams instead of one graph being revealed and hidden.
 */
const ROW_ORDER: NodeLabel[] = [
  NodeLabel.MOVEMENT_PATTERN,
  NodeLabel.ANATOMICAL_STRUCTURE,
  NodeLabel.CONDITION,
  // Exercise sits between the two labels it also links to, so both of its
  // in-band edges drop straight rather than bowing out into a corridor the
  // member's edges already occupy.
  NodeLabel.MUSCLE,
  NodeLabel.EXERCISE,
  NodeLabel.EQUIPMENT,
  NodeLabel.INJURY,
  NodeLabel.MEMBER,
  NodeLabel.GOAL,
  // KG2's timeline, ordered so each sits near what it reaches: Session by the
  // patterns it trained, Message by the concepts it names, and the
  // Observation/Metric pair adjacent because every edge between them is
  // internal to that pair.
  NodeLabel.COACH,
  NodeLabel.SESSION,
  NodeLabel.MESSAGE,
  NodeLabel.OBSERVATION,
  NodeLabel.METRIC,
]

export const BOX = { width: 168, height: 46 } as const

export interface Canvas {
  width: number
  height: number
}

const CANVAS_WIDTH = 860
const MIN_CANVAS_HEIGHT = 420
const CANVAS_PADDING = 44

/** Room for the band captions, which sit above the topmost row. */
const CAPTION_BAND = 18

// Band 1 is inset far enough that its outward bows and the `part_of` self-loop
// stay inside the viewBox. At x=104 they routed to -42 and were clipped.
const BAND_X: Record<Band, number> = {
  [Band.KG1_ONLY]: 160,
  [Band.SHARED]: 440,
  [Band.KG2_ONLY]: 720,
}

const ROW_SPACING = 110
const HALF_W = BOX.width / 2
const HALF_H = BOX.height / 2

export interface PositionedNode {
  label: NodeLabel
  count: number
  shared: boolean
  band: Band
  x: number
  y: number
  row: number
}

export interface PositionedEdge {
  /** Stable identity for a triple, since one rel type can appear twice. */
  key: string
  edge: EdgeTypeSummary
  path: string
  /** Stroke width, scaled so 128 `stresses` edges outweigh 1 `affects`. */
  width: number
  /** True for the clinical edges, which are the only ones drawn in red. */
  clinical: boolean
}

/**
 * Labels only KG2's builder authors. Mirrors `_KG2_AUTHORED` in
 * `backend/src/api/semantics.py`, which places an edge the same way.
 *
 * This was `Member` and `Goal` alone, written when those were the only two
 * node types KG2 owned. The longitudinal build-out added five more, and every
 * one of them fell through to the KG1 column — so Sessions, Messages,
 * Observations and Metrics were drawn under "Movement / clinical", which is
 * both wrong and what overflowed that band.
 */
const KG2_AUTHORED = new Set<NodeLabel>([
  NodeLabel.MEMBER,
  NodeLabel.GOAL,
  NodeLabel.COACH,
  NodeLabel.SESSION,
  NodeLabel.MESSAGE,
  NodeLabel.OBSERVATION,
  NodeLabel.METRIC,
])

function bandOf(node: NodeTypeSummary): Band {
  if (node.shared) return Band.SHARED
  return KG2_AUTHORED.has(node.label) ? Band.KG2_ONLY : Band.KG1_ONLY
}

/**
 * Place every node type present in the response, and size the canvas to hold them.
 *
 * The height is derived from the tallest band rather than fixed. It used to be
 * a constant 420, which fitted while KG2 was three node types; at seven it
 * needs 660 and the difference was rendered as boxes clipped off both ends of
 * the viewBox. A layout that silently crops when the graph grows is worse than
 * one that scrolls, so the canvas follows the content.
 *
 * @param nodeTypes Node types for the requested scope.
 * @returns One positioned node per type keyed by label, and the canvas that
 *   contains them.
 */
export function layoutNodes(nodeTypes: NodeTypeSummary[]): {
  nodes: Map<NodeLabel, PositionedNode>
  canvas: Canvas
} {
  const placed = new Map<NodeLabel, PositionedNode>()
  const rank = (label: NodeLabel) => {
    const index = ROW_ORDER.indexOf(label)
    return index === -1 ? ROW_ORDER.length : index
  }

  const bands = Object.values(Band).map((band) => ({
    band,
    present: nodeTypes
      .filter((n) => bandOf(n) === band)
      .sort((a, b) => rank(a.label) - rank(b.label)),
  }))

  const tallest = Math.max(0, ...bands.map((b) => b.present.length))
  const needed =
    (Math.max(tallest, 1) - 1) * ROW_SPACING + BOX.height + CANVAS_PADDING * 2 + CAPTION_BAND
  const canvas: Canvas = {
    width: CANVAS_WIDTH,
    height: Math.max(MIN_CANVAS_HEIGHT, needed),
  }

  for (const { band, present } of bands) {
    // Rows are evenly spaced and centred, so a band of two and a band of seven
    // share a midline rather than both starting at the top.
    const top = (canvas.height + CAPTION_BAND) / 2 - ((present.length - 1) * ROW_SPACING) / 2

    present.forEach((summary, row) => {
      placed.set(summary.label, {
        label: summary.label,
        count: summary.count,
        shared: summary.shared,
        band,
        x: BAND_X[band],
        y: top + row * ROW_SPACING,
        row,
      })
    })
  }

  return { nodes: placed, canvas }
}

/** A loop on the outward face of the box, for `part_of`'s self-reference. */
function selfLoopPath(node: PositionedNode): string {
  const dir = node.band === Band.KG1_ONLY ? -1 : 1
  const edgeX = node.x + dir * HALF_W
  const reach = edgeX + dir * 52
  return `M ${edgeX} ${node.y - 12} C ${reach} ${node.y - 34}, ${reach} ${node.y + 34}, ${edgeX} ${node.y + 12}`
}

/** A straight drop between vertical neighbours in the same band. */
function neighbourPath(from: PositionedNode, to: PositionedNode): string {
  const dir = Math.sign(to.y - from.y)
  return `M ${from.x} ${from.y + dir * HALF_H} L ${to.x} ${to.y - dir * HALF_H}`
}

/** An outward bow, for same-band nodes that are not neighbours. */
function bowPath(from: PositionedNode, to: PositionedNode): string {
  const dir = from.band === Band.KG1_ONLY ? -1 : 1
  const edgeX = from.x + dir * HALF_W
  const reach = edgeX + dir * 62
  return `M ${edgeX} ${from.y} C ${reach} ${from.y}, ${reach} ${to.y}, ${to.x + dir * HALF_W} ${to.y}`
}

/** A horizontal curve between bands, leaving and entering on facing sides. */
function crossPath(from: PositionedNode, to: PositionedNode): string {
  const dir = Math.sign(to.x - from.x)
  const sx = from.x + dir * HALF_W
  const tx = to.x - dir * HALF_W
  const curve = Math.abs(tx - sx) * 0.45
  return `M ${sx} ${from.y} C ${sx + dir * curve} ${from.y}, ${tx - dir * curve} ${to.y}, ${tx} ${to.y}`
}

const CLINICAL_RELS = new Set(["contraindicates", "cautions"])

/**
 * Route every edge type against the placed nodes.
 *
 * @param edgeTypes Edge types for the requested scope.
 * @param nodes Output of `layoutNodes`.
 * @returns Drawable edges. Triples whose endpoints are not both placed are
 *   dropped, which only happens if the API returns an edge for a node type it
 *   did not also return.
 */
export function layoutEdges(
  edgeTypes: EdgeTypeSummary[],
  nodes: Map<NodeLabel, PositionedNode>,
): PositionedEdge[] {
  const routed: PositionedEdge[] = []

  for (const edge of edgeTypes) {
    const from = nodes.get(edge.from_label)
    const to = nodes.get(edge.to_label)
    if (!from || !to) continue

    let path: string
    if (from.label === to.label) {
      path = selfLoopPath(from)
    } else if (from.band === to.band) {
      path = Math.abs(from.row - to.row) === 1 ? neighbourPath(from, to) : bowPath(from, to)
    } else {
      path = crossPath(from, to)
    }

    routed.push({
      key: `${edge.from_label}-${edge.rel}-${edge.to_label}`,
      edge,
      // Square root, so the widest edge is about four times the narrowest
      // rather than a hundred times it.
      width: Math.min(5, Math.max(1.1, 0.9 + Math.sqrt(edge.count) / 3)),
      clinical: CLINICAL_RELS.has(edge.rel),
      path,
    })
  }

  // Heaviest first, so the thin clinical edges land on top of the thick
  // structural ones rather than under them.
  return routed.sort((a, b) => b.width - a.width)
}
