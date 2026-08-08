import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import cytoscape, { type Core, type ElementDefinition, type LayoutOptions } from "cytoscape"
import fcose from "cytoscape-fcose"
import { fetchNeighbourhood, useInstanceGraph } from "@/api/graph"
import { cn } from "@/lib/utils"
import {
  GraphScope,
  NODE_LABEL_TEXT,
  NodeLabel,
  type GraphEdge,
  type GraphNode,
  type InstanceGraph,
} from "@/types/graph"
import { LABEL_STYLE, buildStylesheet } from "./cytoscapeStyle"
import { NodeDetails } from "./NodeDetails"

cytoscape.use(fcose)

/**
 * fCoSE options, which the base cytoscape types do not describe — the cast is
 * confined here rather than repeated at each call site.
 *
 * @param initial True for the first layout of a fresh element set, false when
 *   re-running after an expansion.
 *
 *   This drives `randomize`, and the distinction is not cosmetic. Freshly added
 *   nodes all sit at (0,0); seeding the solver from those identical positions
 *   gives it no gradient to work with and it returns them in a diagonal stack.
 *   An expansion is the opposite case — most nodes already hold good positions
 *   and re-randomising would throw away the picture the user is reading.
 * @param nodeCount How many nodes the layout is about to place. Spacing that
 *   reads well for a dozen nodes packs the whole catalogue into an unreadable
 *   knot, so the separation scales with the count.
 */
function layoutOptions(initial: boolean, nodeCount: number): LayoutOptions {
  // Three tiers, not two. An isolated neighbourhood is a pure star — every
  // node hangs off the centre and none off each other — so the ring has to be
  // wide enough for exercise names to sit side by side without touching.
  const tier = nodeCount > 60 ? 2 : nodeCount > 12 ? 1 : 0
  return {
    name: "fcose",
    animate: true,
    animationDuration: 400,
    nodeSeparation: [140, 190, 220][tier],
    idealEdgeLength: [150, 210, 240][tier],
    nodeRepulsion: [12000, 30000, 60000][tier],
    // Fewer, longer passes: the big graph needs room to unfold before it
    // settles, and stopping early is what leaves it looking tangled.
    numIter: tier === 2 ? 4000 : 2500,
    // Nodes are as wide as their captions, so the solver has to treat the text
    // as part of the box. Without this, long goal titles sit on top of their
    // neighbours no matter how far the centres are pushed apart.
    nodeDimensionsIncludeLabels: true,
    randomize: initial,
    padding: 40,
    fit: initial,
  } as unknown as LayoutOptions
}

function toElements(graph: InstanceGraph): ElementDefinition[] {
  const nodes: ElementDefinition[] = graph.nodes.map((n) => ({
    group: "nodes",
    data: { id: n.id, label: n.label, caption: n.caption },
  }))
  const edges: ElementDefinition[] = graph.edges.map((e) => ({
    group: "edges",
    data: { id: e.id, source: e.source, target: e.target, rel: e.rel },
  }))
  return [...nodes, ...edges]
}

function LabelFilter({
  labels,
  hidden,
  onToggle,
}: {
  labels: NodeLabel[]
  hidden: Set<NodeLabel>
  onToggle: (label: NodeLabel) => void
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {labels.map((label) => {
        const off = hidden.has(label)
        const style = LABEL_STYLE[label]
        return (
          <button
            key={label}
            type="button"
            aria-pressed={!off}
            onClick={() => onToggle(label)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2 py-[0.1875rem] text-micro",
              off ? "border-line text-faint" : "border-ink text-ink",
            )}
          >
            <i
              aria-hidden
              className="size-2 rounded-[1px]"
              style={{
                background: off ? "transparent" : style.bg,
                border: `1px solid ${off ? "var(--color-faint)" : style.border}`,
              }}
            />
            {NODE_LABEL_TEXT[label]}
          </button>
        )
      })}
    </div>
  )
}

export function InstanceExplorer({ scope }: { scope: GraphScope }) {
  // KG2 is one member's graph, so it opens rooted on her. KG1 and the union
  // have no equivalent centre — there is no single node the catalogue is
  // "about" — so those load whole. The parent remounts this on scope change,
  // which is what makes this initial value hold.
  const [full, setFull] = useState(scope !== GraphScope.KG2)
  const [rootId, setRootId] = useState<string | null>(null)
  const { data, error, isPending } = useInstanceGraph(scope, full, rootId)

  const container = useRef<HTMLDivElement>(null)
  const cy = useRef<Core | null>(null)

  // The canonical record of what is on the canvas. Cytoscape holds only what
  // it needs to draw; the details panel needs full property bags.
  const [nodes, setNodes] = useState<Map<string, GraphNode>>(new Map())
  const [edges, setEdges] = useState<Map<string, GraphEdge>>(new Map())
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [hidden, setHidden] = useState<Set<NodeLabel>>(new Set())
  const [query, setQuery] = useState("")
  const [busy, setBusy] = useState(false)

  // Build the instance once and keep it for the component's life; re-creating
  // it on every data change would throw away pan, zoom and node positions.
  useEffect(() => {
    if (!container.current || cy.current) return
    const instance = cytoscape({
      container: container.current,
      style: buildStylesheet(),
      minZoom: 0.15,
      maxZoom: 3,
    })

    instance.on("tap", "node", (event) => setSelectedId(event.target.id()))
    instance.on("tap", (event) => {
      if (event.target === instance) setSelectedId(null)
    })
    // Press and hold re-centres the view on that node, so isolating a
    // neighbourhood never needs a trip to the side panel.
    instance.on("taphold", "node", (event) => {
      const id = event.target.id()
      setSelectedId(id)
      setRootId(id)
    })
    instance.on("mouseover", "edge", (event) => event.target.addClass("hovered"))
    instance.on("mouseout", "edge", (event) => event.target.removeClass("hovered"))

    cy.current = instance
    return () => {
      instance.destroy()
      cy.current = null
    }
  }, [])

  // A new scope or a switch to the full graph replaces the canvas outright.
  useEffect(() => {
    if (!cy.current || !data) return
    const instance = cy.current

    setNodes(new Map(data.nodes.map((n) => [n.id, n])))
    setEdges(new Map(data.edges.map((e) => [e.id, e])))
    setExpandedIds(data.root_id ? new Set([data.root_id]) : new Set())
    setSelectedId(data.root_id)

    instance.elements().remove()
    instance.add(toElements(data))
    if (data.root_id) instance.getElementById(data.root_id).addClass("root")

    const layout = instance.layout(layoutOptions(true, data.nodes.length))
    // fCoSE's own `fit` runs against pre-animation positions, which leaves
    // nodes clipped at the edges. Re-framing once it settles is what actually
    // gets the whole graph on screen.
    layout.one("layoutstop", () => instance.fit(undefined, 36))
    layout.run()
  }, [data])

  // Dashed border marks a node whose neighbours have not been pulled in.
  useEffect(() => {
    if (!cy.current) return
    cy.current.nodes().forEach((n) => {
      n.toggleClass("unexpanded", !expandedIds.has(n.id()))
    })
  }, [expandedIds, nodes])

  useEffect(() => {
    if (!cy.current) return
    cy.current.nodes().forEach((n) => {
      const label = n.data("label") as NodeLabel
      n.style("display", hidden.has(label) ? "none" : "element")
    })
  }, [hidden, nodes])

  useEffect(() => {
    if (!cy.current || !selectedId) return
    cy.current.$(":selected").unselect()
    cy.current.getElementById(selectedId).select()
  }, [selectedId])

  const expand = useCallback(
    async (nodeId: string) => {
      if (!cy.current || expandedIds.has(nodeId)) return
      setBusy(true)
      try {
        const result = await fetchNeighbourhood(nodeId, scope)
        const instance = cy.current

        const freshNodes = result.nodes.filter((n) => !nodes.has(n.id))
        const freshEdges = result.edges.filter((e) => !edges.has(e.id))

        if (freshNodes.length > 0 || freshEdges.length > 0) {
          setNodes((prev) => new Map([...prev, ...freshNodes.map((n) => [n.id, n] as const)]))
          setEdges((prev) => new Map([...prev, ...freshEdges.map((e) => [e.id, e] as const)]))

          instance.add(
            toElements({ ...result, nodes: freshNodes, edges: freshEdges }),
          )
          // New nodes start on top of their parent, so the layout has a sane
          // starting point and the expansion reads as growth rather than a
          // full reshuffle.
          const origin = instance.getElementById(nodeId).position()
          freshNodes.forEach((n) => instance.getElementById(n.id).position({ ...origin }))
          instance.layout(layoutOptions(false, instance.nodes().length)).run()
        }
        setExpandedIds((prev) => new Set(prev).add(nodeId))
      } finally {
        setBusy(false)
      }
    },
    [edges, expandedIds, nodes, scope],
  )

  const matches = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (term.length < 2) return []
    return [...nodes.values()]
      .filter((n) => n.caption.toLowerCase().includes(term))
      .slice(0, 8)
  }, [nodes, query])

  /** Select a node already on the canvas and pan to it. */
  const reveal = useCallback((nodeId: string) => {
    setSelectedId(nodeId)
    const instance = cy.current
    if (!instance) return
    const node = instance.getElementById(nodeId)
    if (node.length > 0) instance.animate({ center: { eles: node }, zoom: 1.1 }, { duration: 300 })
  }, [])

  /**
   * Redraw the canvas as just this node and its neighbours.
   *
   * Distinct from expanding, which adds to what is already drawn. Isolating
   * throws the rest away, which is what makes a node in the middle of 170
   * others readable.
   */
  const isolate = useCallback((nodeId: string) => {
    setSelectedId(nodeId)
    setRootId(nodeId)
  }, [])

  const presentLabels = useMemo(() => {
    const seen = new Set<NodeLabel>()
    for (const node of nodes.values()) seen.add(node.label)
    return Object.values(NodeLabel).filter((l) => seen.has(l))
  }, [nodes])

  const selected = selectedId ? nodes.get(selectedId) : undefined
  const edgeList = useMemo(() => [...edges.values()], [edges])
  const captionOf = useCallback((id: string) => nodes.get(id)?.caption ?? id, [nodes])

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a node"
            aria-label="Find a node"
            className="w-56 rounded-[4px] border border-line bg-card px-2.5 py-1.5 text-meta outline-none placeholder:text-faint"
          />
          {matches.length > 0 && (
            <ul className="absolute z-10 mt-1 w-72 overflow-hidden rounded-[4px] border border-line bg-card shadow-sm">
              {matches.map((node) => (
                <li key={node.id}>
                  <button
                    type="button"
                    onClick={() => {
                      reveal(node.id)
                      setQuery("")
                    }}
                    className="block w-full px-2.5 py-1.5 text-left hover:bg-ground"
                  >
                    <span className="text-micro text-faint">{NODE_LABEL_TEXT[node.label]}</span>
                    <span className="block truncate text-meta">{node.caption}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="font-mono text-micro text-faint">
            {nodes.size} nodes · {edges.size} edges
          </span>

          {rootId ? (
            <button
              type="button"
              onClick={() => setRootId(null)}
              className="inline-flex max-w-[15rem] items-center gap-1.5 rounded-full border border-cobalt bg-cobalt-wash px-2.5 py-1 text-micro font-semibold text-cobalt"
            >
              <span className="truncate">Around {captionOf(rootId)}</span>
              <span aria-hidden>✕</span>
              <span className="sr-only">Clear focus</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setFull((v) => !v)}
              className="rounded-[4px] border border-line px-2.5 py-1 text-micro font-semibold hover:border-ink"
            >
              {full ? "Back to the member" : "Load whole graph"}
            </button>
          )}

          <button
            type="button"
            onClick={() => cy.current?.fit(undefined, 30)}
            className="rounded-[4px] border border-line px-2.5 py-1 text-micro font-semibold hover:border-ink"
          >
            Fit
          </button>
        </div>
      </div>

      <LabelFilter
        labels={presentLabels}
        hidden={hidden}
        onToggle={(label) =>
          setHidden((prev) => {
            const next = new Set(prev)
            if (next.has(label)) next.delete(label)
            else next.add(label)
            return next
          })
        }
      />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="relative min-w-0 overflow-hidden rounded-[4px] border border-line bg-card">
          <div ref={container} className="h-[40rem] w-full" />

          {isPending && (
            <p className="absolute inset-0 flex items-center justify-center text-meta text-dim">
              Reading the graph
            </p>
          )}
          {error && (
            <p className="absolute inset-0 flex items-center justify-center px-6 text-center text-meta text-dim">
              {error.message}
            </p>
          )}
          {data?.truncated && (
            <p className="absolute right-2 bottom-2 rounded-[4px] border border-red bg-red-wash px-2 py-1 text-micro text-red">
              Capped — not every node is drawn.
            </p>
          )}

          <p className="absolute bottom-2 left-2 text-micro text-faint">
            Dashed outline · neighbours not loaded yet
          </p>
        </div>

        <aside className="min-w-0 overflow-hidden rounded-[4px] border border-line bg-card">
          {selected ? (
            <NodeDetails
              node={selected}
              edges={edgeList}
              captionOf={captionOf}
              expanded={expandedIds.has(selected.id)}
              isolated={rootId === selected.id}
              busy={busy}
              onExpand={() => expand(selected.id)}
              onIsolate={() => isolate(selected.id)}
              onSelect={reveal}
            />
          ) : (
            <p className="p-3 text-meta text-dim">
              Pick a node to see its properties and every relationship it sits on. Press and hold
              one to redraw the graph around it.
            </p>
          )}
        </aside>
      </div>
    </div>
  )
}
