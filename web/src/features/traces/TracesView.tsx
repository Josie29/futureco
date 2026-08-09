import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useSearchParams } from "react-router-dom"
import { getTrace, getTraces } from "@/api/client"
import { Waterfall } from "@/features/traces/Waterfall"
import { formatMessageTime } from "@/lib/dates"
import { cn } from "@/lib/utils"
import { SpanStatus, type RunTrace, type RunTraceSummary, type TraceSpan } from "@/types"

/**
 * Observability over the agentic runtime (ASSESSMENT.md:134).
 *
 * This is the one surface in the app written for an engineer rather than a
 * coach, and it says so by showing the Cypher verbatim. The console went the
 * other way on purpose — a coach reading a session plan should never meet edge
 * syntax. Both are true at once because they have different readers.
 */

const STATUS_LABEL: Record<SpanStatus, string> = {
  [SpanStatus.OK]: "ok",
  [SpanStatus.DEGRADED]: "degraded",
  [SpanStatus.ERROR]: "failed",
}

function StatusDot({ status }: { status: SpanStatus }) {
  return (
    <span
      aria-label={STATUS_LABEL[status]}
      title={STATUS_LABEL[status]}
      className={cn(
        "inline-block size-1.5 shrink-0 rounded-full",
        status === SpanStatus.OK && "bg-cobalt",
        status === SpanStatus.DEGRADED && "border border-red",
        status === SpanStatus.ERROR && "bg-red",
      )}
    />
  )
}

function RunList({
  runs,
  selectedId,
  onSelect,
}: {
  runs: RunTraceSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <nav aria-label="Runs" className="w-72 shrink-0 overflow-y-auto border-r border-line">
      <p className="px-3 pt-3 pb-1.5 text-micro font-semibold text-dim">
        Recent runs <span className="font-normal text-faint">· {runs.length}</span>
      </p>
      <ul>
        {runs.map((run) => (
          <li key={run.run_id}>
            <button
              type="button"
              onClick={() => onSelect(run.run_id)}
              aria-current={run.run_id === selectedId ? "true" : undefined}
              className={cn(
                "flex w-full flex-col gap-0.5 border-l-2 px-3 py-2 text-left",
                run.run_id === selectedId
                  ? "border-l-cobalt bg-cobalt-wash"
                  : "border-l-transparent hover:bg-ground",
              )}
            >
              <span className="flex items-center gap-1.5">
                <StatusDot status={run.status} />
                {/* A plan built from switched-off constraints alone carries no
                    prompt, and an untitled row is unfindable in a list. */}
                <span className="truncate text-micro font-semibold">
                  {run.prompt || <span className="font-normal text-faint">no prompt</span>}
                </span>
              </span>
              <span className="font-mono text-micro text-faint">
                {run.source} · {run.duration_ms} ms · {run.totals.graph_queries} graph ·{" "}
                {run.totals.llm_calls} llm
              </span>
              <span className="text-micro text-faint">{formatMessageTime(run.started_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}

function Totals({ trace }: { trace: RunTrace }) {
  const cells = [
    ["Wall clock", `${trace.duration_ms} ms`],
    ["Graph queries", `${trace.totals.graph_queries}`],
    ["LLM calls", `${trace.totals.llm_calls}`],
    ["Tokens in / out", `${trace.totals.tokens_in} / ${trace.totals.tokens_out}`],
  ] as const

  return (
    <div className="flex flex-wrap items-stretch gap-x-6 gap-y-2 border-b border-line px-3.5 py-2.5">
      {cells.map(([label, value]) => (
        <div key={label} className="flex flex-col gap-px">
          <span className="text-micro text-faint">{label}</span>
          <span className="num text-lead leading-tight">{value}</span>
        </div>
      ))}
    </div>
  )
}

function SpanDetail({ span }: { span: TraceSpan }) {
  return (
    <div className="flex flex-col gap-2.5 border-t border-line p-3">
      <div className="flex items-baseline gap-2">
        <StatusDot status={span.status} />
        <h3 className="text-meta font-semibold">{span.name}</h3>
        <span className="ml-auto num text-micro text-dim">{span.duration_ms} ms</span>
      </div>

      {span.note && (
        <p
          className={cn(
            "rounded-[4px] p-2 text-micro",
            span.status === SpanStatus.ERROR
              ? "border border-red bg-red-wash text-red"
              : "bg-ground text-dim",
          )}
        >
          {span.note}
        </p>
      )}

      {span.model && (
        <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-micro">
          <dt className="text-faint">model</dt>
          <dd className="font-mono text-dim">{span.model}</dd>
          <dt className="text-faint">tokens</dt>
          <dd className="font-mono text-dim">
            {span.tokens_in} in · {span.tokens_out} out
          </dd>
        </dl>
      )}

      {span.query && (
        <div>
          <p className="mb-1 flex items-baseline gap-2 text-micro text-faint">
            <span>Cypher</span>
            {span.rows_returned !== undefined && (
              <span className="ml-auto">{span.rows_returned} rows</span>
            )}
          </p>
          <pre className="overflow-x-auto rounded-[4px] bg-ground p-2 font-mono text-micro leading-relaxed text-ink">
            {span.query}
          </pre>
        </div>
      )}

      {span.attributes.length > 0 && (
        <dl className="grid grid-cols-[10rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-micro">
          {span.attributes.map((attr, i) => (
            <div key={`${attr.label}-${i}`} className="contents">
              <dt className="truncate text-faint">{attr.label}</dt>
              <dd className="font-mono break-words text-dim">{attr.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

export default function TracesView() {
  const [params] = useSearchParams()
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const [selectedSpan, setSelectedSpan] = useState<string | null>(null)

  const runs = useQuery({ queryKey: ["traces"], queryFn: getTraces })
  // `?run=` lets the plan sheet hand a coach straight to the run behind it.
  const requested = params.get("run")
  const activeRunId = selectedRun ?? requested ?? runs.data?.[0]?.run_id ?? null

  const trace = useQuery({
    queryKey: ["trace", activeRunId],
    queryFn: () => getTrace(activeRunId as string),
    enabled: Boolean(activeRunId),
  })

  const spans = trace.data?.spans ?? []
  const root = spans.find((s) => s.parent_id === null)
  const activeSpan = spans.find((s) => s.id === selectedSpan) ?? spans.find((s) => s.parent_id !== null)

  if (runs.isPending) {
    return <div className="flex flex-1 items-center justify-center p-8 text-meta text-dim">Loading runs</div>
  }

  if (!runs.data?.length) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <p className="max-w-sm text-center text-meta text-dim">
          No runs yet. Build a session or ask the copilot something, then come back.
        </p>
      </div>
    )
  }

  return (
    <>
      <RunList
        runs={runs.data}
        selectedId={activeRunId}
        onSelect={(id) => {
          setSelectedRun(id)
          setSelectedSpan(null)
        }}
      />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">
        {trace.isPending || !trace.data ? (
          <div className="flex flex-1 items-center justify-center p-8 text-meta text-dim">
            Loading trace
          </div>
        ) : (
          <div className="mx-auto flex w-full max-w-3xl flex-col p-4">
            <header className="mb-2">
              <h1 className="disp text-title">{trace.data.prompt}</h1>
              <p className="mt-px font-mono text-micro text-faint">
                {trace.data.run_id} · {trace.data.source}
              </p>
            </header>

            <section className="rounded-[4px] border border-line bg-card">
              <Totals trace={trace.data} />
              <Waterfall
                spans={spans}
                totalMs={root?.duration_ms ?? 0}
                selectedId={activeSpan?.id ?? null}
                onSelect={setSelectedSpan}
              />
              {activeSpan && <SpanDetail span={activeSpan} />}
            </section>
          </div>
        )}
      </main>
    </>
  )
}
