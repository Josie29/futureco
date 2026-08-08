import { SpanKind, SpanStatus, type TraceSpan } from "@/types"
import { cn } from "@/lib/utils"

/**
 * Span kinds are labelled, not coloured.
 *
 * Five nominal categories would need five hues that survive colour-vision
 * deficiency, and this console spends its one saturated colour on the product
 * and reserves red for status. A three-letter tag in mono separates the kinds
 * with no palette at all, and leaves colour free to mean what it means
 * everywhere else: red is something that went wrong.
 */
const KIND_TAG: Record<SpanKind, string> = {
  [SpanKind.AGENT]: "run",
  [SpanKind.RESOLVE]: "resolve",
  [SpanKind.GRAPH]: "graph",
  [SpanKind.LLM]: "llm",
  [SpanKind.TOOL]: "tool",
}

export function Waterfall({
  spans,
  totalMs,
  selectedId,
  onSelect,
}: {
  spans: TraceSpan[]
  totalMs: number
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const children = spans.filter((s) => s.parent_id !== null)

  return (
    <ol className="flex flex-col">
      {children.map((span) => {
        const left = totalMs > 0 ? (span.started_ms / totalMs) * 100 : 0
        const width = totalMs > 0 ? Math.max((span.duration_ms / totalMs) * 100, 1.5) : 0
        const bad = span.status !== SpanStatus.OK
        const selected = span.id === selectedId

        return (
          <li key={span.id}>
            <button
              type="button"
              onClick={() => onSelect(span.id)}
              aria-pressed={selected}
              className={cn(
                "grid w-full grid-cols-[3.75rem_minmax(0,1fr)_4.5rem] items-center gap-2.5 px-3 py-1 text-left",
                selected ? "bg-cobalt-wash" : "hover:bg-ground",
              )}
            >
              <span className="font-mono text-micro text-faint">{KIND_TAG[span.kind]}</span>

              <span className="min-w-0">
                <span
                  className={cn(
                    "block truncate text-micro",
                    bad ? "font-semibold text-red" : "text-ink",
                  )}
                >
                  {span.name}
                </span>
                {/* The bar is the point: where the time actually went. */}
                <span aria-hidden className="mt-0.5 block h-1 w-full rounded-full bg-soft">
                  <i
                    className={cn("block h-1 rounded-full", bad ? "bg-red" : "bg-cobalt")}
                    style={{ marginLeft: `${left}%`, width: `${width}%` }}
                  />
                </span>
              </span>

              <span
                className={cn(
                  "num text-right text-micro whitespace-nowrap",
                  bad ? "text-red" : "text-dim",
                )}
              >
                {span.duration_ms} ms
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}
