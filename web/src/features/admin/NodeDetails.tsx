import { NODE_LABEL_TEXT, type GraphEdge, type GraphNode } from "@/types/graph"

/** Properties the panel never shows: internal, or already in the caption. */
const HIDDEN_PROPS = new Set(["source", "name", "text"])

function renderValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ")
  if (value === null || value === undefined || value === "") return "—"
  return String(value)
}

function PropRow({ name, value }: { name: string; value: unknown }) {
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-2 py-[0.1875rem]">
      <span className="font-mono text-micro break-words text-faint">{name}</span>
      <span className="text-micro break-words">{renderValue(value)}</span>
    </div>
  )
}

export function NodeDetails({
  node,
  edges,
  captionOf,
  onExpand,
  onIsolate,
  onSelect,
  expanded,
  isolated,
  busy,
}: {
  node: GraphNode
  /** Every edge currently on the canvas; this filters to the node's own. */
  edges: GraphEdge[]
  captionOf: (id: string) => string
  /** Add this node's neighbours to what is already drawn. */
  onExpand: () => void
  /** Redraw the canvas as only this node and its neighbours. */
  onIsolate: () => void
  onSelect: (id: string) => void
  expanded: boolean
  isolated: boolean
  busy: boolean
}) {
  const props = Object.entries(node.props).filter(([k]) => !HIDDEN_PROPS.has(k))
  const outgoing = edges.filter((e) => e.source === node.id)
  const incoming = edges.filter((e) => e.target === node.id)

  return (
    <div className="flex min-h-0 flex-col">
      <div className="border-b border-soft px-3 py-2.5">
        <span className="text-micro font-semibold text-dim">{NODE_LABEL_TEXT[node.label]}</span>
        <p className="disp mt-0.5 text-body leading-tight">{node.caption}</p>

        <div className="mt-2 flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={onIsolate}
            disabled={isolated}
            className="rounded-[4px] bg-ink px-2.5 py-1 text-micro font-semibold text-white disabled:opacity-40"
          >
            {isolated ? "Showing only this" : "Show only neighbours"}
          </button>
          <button
            type="button"
            onClick={onExpand}
            disabled={busy || expanded}
            className="rounded-[4px] border border-line px-2.5 py-1 text-micro font-semibold disabled:opacity-40"
          >
            {busy ? "Expanding…" : expanded ? "Neighbours loaded" : "Add neighbours"}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2.5">
        {props.length > 0 && (
          <section className="mb-3">
            <h4 className="mb-1 text-micro font-semibold text-dim">Properties</h4>
            {props.map(([name, value]) => (
              <PropRow key={name} name={name} value={value} />
            ))}
          </section>
        )}

        {[
          { title: "Points at", rows: outgoing, other: (e: GraphEdge) => e.target },
          { title: "Pointed at by", rows: incoming, other: (e: GraphEdge) => e.source },
        ].map(({ title, rows, other }) =>
          rows.length === 0 ? null : (
            <section key={title} className="mb-3">
              <h4 className="mb-1 text-micro font-semibold text-dim">
                {title}
                <span className="ml-1.5 font-mono font-normal text-faint">{rows.length}</span>
              </h4>
              {rows.map((edge) => (
                <button
                  key={edge.id}
                  type="button"
                  onClick={() => onSelect(other(edge))}
                  className="block w-full rounded-[4px] px-1.5 py-1 text-left hover:bg-ground"
                >
                  <span className="font-mono text-micro text-cobalt">{edge.rel}</span>{" "}
                  <span className="text-micro">{captionOf(other(edge))}</span>
                  {typeof edge.props.rationale === "string" && (
                    <span className="mt-0.5 block text-micro leading-snug text-faint">
                      {edge.props.rationale}
                    </span>
                  )}
                </button>
              ))}
            </section>
          ),
        )}
      </div>
    </div>
  )
}
