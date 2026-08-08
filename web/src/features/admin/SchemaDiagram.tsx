import { useMemo } from "react"
import { Band, BOX, CANVAS, layoutEdges, layoutNodes, type PositionedNode } from "./layout"
import { NODE_LABEL_TEXT, type EdgeTypeSummary, type NodeLabel, type NodeTypeSummary } from "@/types/graph"

/** What the pointer or the edge list is currently pointing at. */
export type Focus =
  | { kind: "node"; label: NodeLabel }
  | { kind: "edge"; key: string }
  | null

const HALF_W = BOX.width / 2

function nodeFill(node: PositionedNode): string {
  if (node.band === Band.KG2_ONLY) return "var(--color-ink)"
  return node.shared ? "var(--color-cobalt-wash)" : "var(--color-card)"
}

function nodeStroke(node: PositionedNode): string {
  if (node.band === Band.KG2_ONLY) return "var(--color-ink)"
  return node.shared ? "var(--color-cobalt)" : "var(--color-line)"
}

function BandCaption({ band, x }: { band: Band; x: number }) {
  const text = {
    [Band.KG1_ONLY]: "Movement / clinical",
    [Band.SHARED]: "Shared",
    [Band.KG2_ONLY]: "Member context",
  }[band]

  return (
    <text
      x={x}
      y={22}
      textAnchor="middle"
      className="fill-faint text-[0.625rem] font-semibold"
    >
      {text}
    </text>
  )
}

export function SchemaDiagram({
  nodeTypes,
  edgeTypes,
  focus,
  onFocus,
}: {
  nodeTypes: NodeTypeSummary[]
  edgeTypes: EdgeTypeSummary[]
  focus: Focus
  onFocus: (focus: Focus) => void
}) {
  const nodes = useMemo(() => layoutNodes(nodeTypes), [nodeTypes])
  const edges = useMemo(() => layoutEdges(edgeTypes, nodes), [edgeTypes, nodes])

  const isEdgeLit = (key: string, edge: EdgeTypeSummary) => {
    if (!focus) return true
    if (focus.kind === "edge") return focus.key === key
    return edge.from_label === focus.label || edge.to_label === focus.label
  }

  const isNodeLit = (label: NodeLabel) => {
    if (!focus) return true
    if (focus.kind === "node") return focus.label === label
    const lit = edges.find((e) => e.key === focus.key)
    return lit ? lit.edge.from_label === label || lit.edge.to_label === label : true
  }

  const bandsPresent = [...new Set([...nodes.values()].map((n) => n.band))]

  return (
    <svg
      viewBox={`0 0 ${CANVAS.width} ${CANVAS.height}`}
      className="w-full"
      role="img"
      aria-label={`Schema graph: ${nodeTypes.length} node types and ${edgeTypes.length} edge types. The edge list beside it carries the same information as text.`}
      onMouseLeave={() => onFocus(null)}
    >
      <defs>
        {/* One marker per stroke colour; SVG markers do not inherit it. */}
        <marker id="tip" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M 0 1 L 7 4 L 0 7 z" fill="var(--color-faint)" />
        </marker>
        <marker id="tip-red" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M 0 1 L 7 4 L 0 7 z" fill="var(--color-red)" />
        </marker>
      </defs>

      {bandsPresent.map((band) => {
        const x = [...nodes.values()].find((n) => n.band === band)!.x
        return <BandCaption key={band} band={band} x={x} />
      })}

      {edges.map(({ key, edge, path, width, clinical }) => {
        const lit = isEdgeLit(key, edge)
        return (
          <g key={key}>
            {/* A transparent fat stroke, so a 1px edge is still catchable. */}
            <path
              d={path}
              fill="none"
              stroke="transparent"
              strokeWidth={14}
              style={{ pointerEvents: "stroke" }}
              onMouseEnter={() => onFocus({ kind: "edge", key })}
            />
            <path
              d={path}
              fill="none"
              stroke={clinical ? "var(--color-red)" : "var(--color-faint)"}
              strokeWidth={lit ? width + 0.6 : width}
              strokeOpacity={lit ? (clinical ? 1 : 0.75) : 0.12}
              markerEnd={clinical ? "url(#tip-red)" : "url(#tip)"}
              className="pointer-events-none transition-[stroke-opacity] duration-150"
            />
          </g>
        )
      })}

      {[...nodes.values()].map((node) => {
        const lit = isNodeLit(node.label)
        const onInk = node.band === Band.KG2_ONLY
        return (
          <g
            key={node.label}
            opacity={lit ? 1 : 0.25}
            className="transition-opacity duration-150"
            onMouseEnter={() => onFocus({ kind: "node", label: node.label })}
          >
            <rect
              x={node.x - HALF_W}
              y={node.y - BOX.height / 2}
              width={BOX.width}
              height={BOX.height}
              rx={4}
              fill={nodeFill(node)}
              stroke={nodeStroke(node)}
              strokeWidth={node.shared ? 1.5 : 1}
            />
            <text
              x={node.x - HALF_W + 12}
              y={node.y + 5}
              className={onInk ? "fill-white text-[0.75rem] font-semibold" : "fill-ink text-[0.75rem] font-semibold"}
            >
              {NODE_LABEL_TEXT[node.label]}
            </text>
            <text
              x={node.x + HALF_W - 12}
              y={node.y + 6}
              textAnchor="end"
              className={onInk ? "num fill-white text-[0.9375rem]" : "num fill-ink text-[0.9375rem]"}
            >
              {node.count}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
