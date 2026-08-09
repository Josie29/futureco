import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Band, BOX, layoutEdges, layoutNodes, type Canvas, type PositionedNode } from "./layout"
import { NODE_LABEL_TEXT, type EdgeTypeSummary, type NodeLabel, type NodeTypeSummary } from "@/types/graph"

/** What the pointer or the edge list is currently pointing at. */
export type Focus =
  | { kind: "node"; label: NodeLabel }
  | { kind: "edge"; key: string }
  | null

const HALF_W = BOX.width / 2

/** How far in the view may zoom. 1 is the whole canvas, which is also the floor. */
const MAX_ZOOM = 5
const ZOOM_STEP = 1.25

/** The visible window in canvas units. At zoom 1 it is the canvas itself. */
interface Viewport {
  x: number
  y: number
  width: number
  height: number
}

function fit(canvas: Canvas): Viewport {
  return { x: 0, y: 0, width: canvas.width, height: canvas.height }
}

/**
 * Keep a viewport inside the canvas.
 *
 * Panning is clamped rather than free so the diagram cannot be dragged off
 * screen and lost — at zoom 1 both axes pin to 0, which is what makes the
 * fitted view feel fixed rather than loose.
 */
function clamp(view: Viewport, canvas: Canvas): Viewport {
  const width = Math.min(view.width, canvas.width)
  const height = Math.min(view.height, canvas.height)
  return {
    width,
    height,
    x: Math.min(Math.max(view.x, 0), canvas.width - width),
    y: Math.min(Math.max(view.y, 0), canvas.height - height),
  }
}

/** Zoom about a fixed point, so the graph grows toward the cursor. */
function zoomAt(view: Viewport, canvas: Canvas, factor: number, at: { x: number; y: number }) {
  const width = Math.min(canvas.width, Math.max(canvas.width / MAX_ZOOM, view.width / factor))
  const height = width * (canvas.height / canvas.width)
  // The canvas point under the cursor has to stay under it, so the new origin
  // is the old one moved by the share of the shrink on that side.
  const ratioX = (at.x - view.x) / view.width
  const ratioY = (at.y - view.y) / view.height
  return clamp(
    { x: at.x - ratioX * width, y: at.y - ratioY * height, width, height },
    canvas,
  )
}

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
  const { nodes, canvas } = useMemo(() => layoutNodes(nodeTypes), [nodeTypes])
  const edges = useMemo(() => layoutEdges(edgeTypes, nodes), [edgeTypes, nodes])

  const svgRef = useRef<SVGSVGElement>(null)
  const [view, setView] = useState<Viewport>(() => fit(canvas))
  const [panning, setPanning] = useState(false)
  const drag = useRef<{ x: number; y: number; view: Viewport } | null>(null)

  // Switching scope changes how many rows a band holds, and so the canvas. A
  // viewport carried across would be framing coordinates that no longer exist.
  useEffect(() => setView(fit(canvas)), [canvas])

  const zoomed = view.width < canvas.width - 0.5

  /**
   * Pointer position in canvas units, which is what every transform works in.
   *
   * Takes the viewport rather than closing over it, so the wheel handler can
   * read the current one inside a `setView` updater. Closing over `view` would
   * put it in the effect's dependencies and re-register the listener on every
   * tick of a zoom gesture.
   */
  const toCanvas = useCallback(
    (from: Viewport, event: { clientX: number; clientY: number }) => {
      const box = svgRef.current?.getBoundingClientRect()
      if (!box) return { x: from.x + from.width / 2, y: from.y + from.height / 2 }
      return {
        x: from.x + ((event.clientX - box.left) / box.width) * from.width,
        y: from.y + ((event.clientY - box.top) / box.height) * from.height,
      }
    },
    [],
  )

  const step = (factor: number) =>
    setView((current) =>
      zoomAt(current, canvas, factor, {
        x: current.x + current.width / 2,
        y: current.y + current.height / 2,
      }),
    )

  // Wheel is a non-passive native listener because React's onWheel is passive
  // and cannot preventDefault, which would let the page scroll away underneath
  // a zoom gesture.
  useEffect(() => {
    const element = svgRef.current
    if (!element) return

    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const factor = event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP
      setView((current) => zoomAt(current, canvas, factor, toCanvas(current, event)))
    }
    element.addEventListener("wheel", onWheel, { passive: false })
    return () => element.removeEventListener("wheel", onWheel)
  }, [canvas, toCanvas])

  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return
    drag.current = { x: event.clientX, y: event.clientY, view }
    setPanning(true)
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const from = drag.current
    const box = svgRef.current?.getBoundingClientRect()
    if (!from || !box) return
    // Screen pixels to canvas units, so the graph tracks the cursor exactly
    // however far it is zoomed in.
    const scale = from.view.width / box.width
    setView(
      clamp(
        {
          ...from.view,
          x: from.view.x - (event.clientX - from.x) * scale,
          y: from.view.y - (event.clientY - from.y) * scale,
        },
        canvas,
      ),
    )
  }

  const endPan = (event: React.PointerEvent<SVGSVGElement>) => {
    drag.current = null
    setPanning(false)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  // Hovering mid-drag would repaint the highlight on every frame of a pan.
  const focusUnlessPanning = (next: Focus) => {
    if (!panning) onFocus(next)
  }

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
    <div className="relative">
      {/* Controls rather than gesture-only: a trackpad user can pinch, but a
          mouse user reaching for a graph twice the height of its frame should
          not have to discover that scrolling zooms it. */}
      <div className="absolute top-1 right-1 z-10 flex items-center gap-1">
        {zoomed && (
          <button
            type="button"
            onClick={() => setView(fit(canvas))}
            className="rounded-[3px] border border-line bg-card px-1.5 py-0.5 text-micro text-dim hover:border-cobalt hover:text-cobalt"
          >
            Reset
          </button>
        )}
        <button
          type="button"
          onClick={() => step(1 / ZOOM_STEP)}
          disabled={!zoomed}
          aria-label="Zoom out"
          className="size-5 rounded-[3px] border border-line bg-card text-micro text-dim hover:border-cobalt hover:text-cobalt disabled:opacity-40 disabled:hover:border-line disabled:hover:text-dim"
        >
          −
        </button>
        <button
          type="button"
          onClick={() => step(ZOOM_STEP)}
          aria-label="Zoom in"
          className="size-5 rounded-[3px] border border-line bg-card text-micro text-dim hover:border-cobalt hover:text-cobalt"
        >
          +
        </button>
      </div>

      <svg
        ref={svgRef}
        viewBox={`${view.x} ${view.y} ${view.width} ${view.height}`}
        className={`w-full touch-none select-none ${panning ? "cursor-grabbing" : "cursor-grab"}`}
        role="img"
        aria-label={`Schema graph: ${nodeTypes.length} node types and ${edgeTypes.length} edge types. Drag to pan and scroll to zoom. The edge list beside it carries the same information as text.`}
        onMouseLeave={() => onFocus(null)}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPan}
        onPointerCancel={endPan}
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
              onMouseEnter={() => focusUnlessPanning({ kind: "edge", key })}
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
            onMouseEnter={() => focusUnlessPanning({ kind: "node", label: node.label })}
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
    </div>
  )
}
