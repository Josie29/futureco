import { cn } from "@/lib/utils"
import {
  GraphScope,
  NODE_LABEL_TEXT,
  RelType,
  type EdgeTypeSummary,
} from "@/types/graph"
import type { Focus } from "./SchemaDiagram"

const SCOPE_HEADING: Record<GraphScope.KG1 | GraphScope.KG2, string> = {
  [GraphScope.KG1]: "Movement / clinical",
  [GraphScope.KG2]: "Member context",
}

const CLINICAL = new Set<RelType>([RelType.CONTRAINDICATES, RelType.CAUTIONS])

function edgeKey(edge: EdgeTypeSummary): string {
  return `${edge.from_label}-${edge.rel}-${edge.to_label}`
}

function EdgeRow({
  edge,
  lit,
  onFocus,
}: {
  edge: EdgeTypeSummary
  lit: boolean
  onFocus: (focus: Focus) => void
}) {
  const key = edgeKey(edge)
  const clinical = CLINICAL.has(edge.rel)

  return (
    <button
      type="button"
      onMouseEnter={() => onFocus({ kind: "edge", key })}
      onFocus={() => onFocus({ kind: "edge", key })}
      className={cn(
        "block w-full rounded-[4px] border-l-2 py-1.5 pr-2 pl-2.5 text-left",
        lit ? "bg-ground" : "bg-transparent",
        clinical ? "border-l-red" : "border-l-line",
      )}
    >
      <span className="flex items-baseline justify-between gap-2">
        <span className="min-w-0 truncate text-[0.6875rem]">
          <span className="text-dim">{NODE_LABEL_TEXT[edge.from_label]}</span>
          <span className={cn("font-mono", clinical ? "text-red" : "text-ink")}>
            {" "}
            −{edge.rel}→{" "}
          </span>
          <span className="text-dim">{NODE_LABEL_TEXT[edge.to_label]}</span>
        </span>
        <span className="num shrink-0 text-[0.8125rem]">{edge.count}</span>
      </span>

      {edge.semantics ? (
        <span className="mt-0.5 block text-[0.625rem] leading-snug text-faint">
          {edge.semantics}
        </span>
      ) : (
        // A triple the API has no rule for. Saying so beats an empty line,
        // because it means the builder and this view have drifted apart.
        <span className="mt-0.5 block text-[0.625rem] leading-snug text-red">
          No rule for this shape — the store holds an edge the API does not describe.
        </span>
      )}
    </button>
  )
}

export function EdgeList({
  edgeTypes,
  focus,
  onFocus,
}: {
  edgeTypes: EdgeTypeSummary[]
  focus: Focus
  onFocus: (focus: Focus) => void
}) {
  const groups = [GraphScope.KG1, GraphScope.KG2] as const

  const isLit = (edge: EdgeTypeSummary) => {
    if (!focus) return false
    if (focus.kind === "edge") return focus.key === edgeKey(edge)
    return edge.from_label === focus.label || edge.to_label === focus.label
  }

  return (
    <div
      className="flex flex-col gap-3 overflow-y-auto"
      onMouseLeave={() => onFocus(null)}
    >
      {groups.map((scope) => {
        const rows = edgeTypes.filter((e) => e.scope === scope)
        if (rows.length === 0) return null
        return (
          <section key={scope}>
            <h3 className="mb-1 px-2.5 text-[0.625rem] font-semibold text-dim">
              {SCOPE_HEADING[scope]}
              <span className="ml-1.5 font-mono text-[0.5938rem] font-normal text-faint">
                {rows.length}
              </span>
            </h3>
            <div className="flex flex-col gap-0.5">
              {rows.map((edge) => (
                <EdgeRow
                  key={edgeKey(edge)}
                  edge={edge}
                  lit={isLit(edge)}
                  onFocus={onFocus}
                />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
