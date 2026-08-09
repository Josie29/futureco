import { describe, expect, it } from "vitest"
import { BOX, layoutNodes } from "@/features/admin/layout"
import { NodeLabel, type NodeTypeSummary } from "@/types/graph"

/**
 * The schema diagram's canvas used to be a fixed 420 tall, which fitted while
 * KG2 held three node types. It grew to seven and the extra rows were laid out
 * at negative y and past the bottom edge — rendered as boxes sliced off both
 * ends of the SVG, with nothing failing anywhere.
 *
 * That is the failure this file exists to catch: a layout that silently crops
 * when the graph gains a node type. Asserting containment rather than a
 * specific height keeps it true if the spacing is ever retuned.
 */

const KG2_ONLY = [
  NodeLabel.MEMBER,
  NodeLabel.GOAL,
  NodeLabel.COACH,
  NodeLabel.SESSION,
  NodeLabel.MESSAGE,
  NodeLabel.OBSERVATION,
  NodeLabel.METRIC,
]

const SHARED = [
  NodeLabel.EXERCISE,
  NodeLabel.MUSCLE,
  NodeLabel.EQUIPMENT,
  NodeLabel.INJURY,
  NodeLabel.MOVEMENT_PATTERN,
  NodeLabel.ANATOMICAL_STRUCTURE,
]

const KG1_ONLY = [NodeLabel.CONDITION]

function summaries(labels: NodeLabel[], shared: boolean): NodeTypeSummary[] {
  return labels.map((label) => ({ label, count: 1, shared }))
}

/** Every node type the API can return, which is the tallest the diagram gets. */
const EVERYTHING: NodeTypeSummary[] = [
  ...summaries(KG1_ONLY, false),
  ...summaries(SHARED, true),
  ...summaries(KG2_ONLY, false),
]

describe("schema diagram layout", () => {
  it("keeps every node box inside the canvas", () => {
    const { nodes, canvas } = layoutNodes(EVERYTHING)

    expect(nodes.size).toBe(EVERYTHING.length)
    for (const node of nodes.values()) {
      expect(node.y - BOX.height / 2).toBeGreaterThanOrEqual(0)
      expect(node.y + BOX.height / 2).toBeLessThanOrEqual(canvas.height)
      expect(node.x - BOX.width / 2).toBeGreaterThanOrEqual(0)
      expect(node.x + BOX.width / 2).toBeLessThanOrEqual(canvas.width)
    }
  })

  it("clears the band captions, which are drawn above the first row", () => {
    const { nodes } = layoutNodes(EVERYTHING)
    // The captions sit at y=22 in SchemaDiagram. A first row overlapping them
    // reads as a node type with a stray word across its top edge.
    const highest = Math.min(...[...nodes.values()].map((n) => n.y - BOX.height / 2))
    expect(highest).toBeGreaterThan(22)
  })

  it("grows the canvas when a band gains rows, rather than cropping", () => {
    const short = layoutNodes([...summaries(KG1_ONLY, false), ...summaries(SHARED, true)])
    const tall = layoutNodes(EVERYTHING)
    expect(tall.canvas.height).toBeGreaterThan(short.canvas.height)
  })

  it("centres each band on the same midline", () => {
    const { nodes, canvas } = layoutNodes(EVERYTHING)
    // A band of one and a band of seven have to share a centre, or the diagram
    // reads as three unrelated columns rather than one graph.
    const midlineOf = (labels: NodeLabel[]) => {
      const ys = labels.map((l) => nodes.get(l)!.y)
      return (Math.min(...ys) + Math.max(...ys)) / 2
    }
    expect(midlineOf(KG1_ONLY)).toBeCloseTo(midlineOf(KG2_ONLY), 5)
    expect(midlineOf(SHARED)).toBeCloseTo(midlineOf(KG2_ONLY), 5)
    expect(midlineOf(KG2_ONLY)).toBeLessThan(canvas.height)
  })
})
