import { useState } from "react"
import { ApiError, useSchemaGraph } from "@/api/graph"
import { cn } from "@/lib/utils"
import { EdgeList } from "./EdgeList"
import { InstanceExplorer } from "./InstanceExplorer"
import { ScopeToggle, scopeHint } from "./ScopeToggle"
import { SchemaDiagram, type Focus } from "./SchemaDiagram"
import { GraphScope, type SchemaTotals } from "@/types/graph"

const BUILD_COMMAND = "cd backend && PYTHONPATH=src uv run python -m graph.build.main"

/** Two altitudes over the same store: the types, and the things. */
enum View {
  SCHEMA = "schema",
  DATA = "data",
}

const VIEWS: { view: View; label: string }[] = [
  { view: View.SCHEMA, label: "Schema" },
  { view: View.DATA, label: "Data" },
]

function ViewToggle({ view, onChange }: { view: View; onChange: (view: View) => void }) {
  return (
    <div className="inline-flex rounded-[4px] border border-line bg-card p-0.5" role="tablist">
      {VIEWS.map((option) => (
        <button
          key={option.view}
          type="button"
          role="tab"
          aria-selected={option.view === view}
          onClick={() => onChange(option.view)}
          className={cn(
            "rounded-[3px] px-2.5 py-1 text-xs font-semibold",
            option.view === view ? "bg-ink text-white" : "text-dim hover:text-ink",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-md rounded-[4px] border border-line bg-card p-4">
      <p className="disp text-base">{title}</p>
      <div className="mt-2 text-[0.8125rem] text-dim">{children}</div>
    </div>
  )
}

function Command({ children }: { children: string }) {
  return (
    <code className="mt-2 block rounded-[4px] border border-soft bg-ground px-2 py-1.5 font-mono text-[0.6875rem] break-all text-ink">
      {children}
    </code>
  )
}

function Totals({ totals }: { totals: SchemaTotals }) {
  const cells: { label: string; value: number; alarm?: boolean }[] = [
    { label: "Node types", value: totals.node_types },
    { label: "Edge types", value: totals.edge_types },
    { label: "Nodes", value: totals.nodes },
    { label: "Edges", value: totals.edges },
    // Zero is the expected reading, so it only earns colour when it is not.
    { label: "Orphans", value: totals.orphan_nodes, alarm: totals.orphan_nodes > 0 },
  ]

  return (
    <div className="flex items-baseline gap-5">
      {cells.map((cell) => (
        <span key={cell.label} className="flex items-baseline gap-1.5">
          <span className={cell.alarm ? "num text-base text-red" : "num text-base"}>
            {cell.value}
          </span>
          <span className="text-[0.6875rem] text-dim">{cell.label}</span>
        </span>
      ))}
    </div>
  )
}

export default function AdminGraph() {
  // Opens on the member's own graph: a dozen nodes with a person at the centre
  // reads immediately, where 170 nodes and 454 edges read as a hairball.
  const [scope, setScope] = useState<GraphScope>(GraphScope.KG2)
  const [view, setView] = useState<View>(View.DATA)
  const [focus, setFocus] = useState<Focus>(null)
  const { data, error, isPending } = useSchemaGraph(scope)

  const empty = data !== undefined && data.totals.nodes === 0

  // A highlight held across a scope change can point at an edge the new scope
  // does not contain, which dims the whole diagram and lights nothing.
  const changeScope = (next: GraphScope) => {
    setFocus(null)
    setScope(next)
  }

  return (
    <main className="min-w-0 flex-1 overflow-y-auto p-4 pb-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="disp text-xl">Knowledge graph</h1>
            <p className="mt-0.5 text-meta text-dim">
              {scopeHint(scope)}.{" "}
              {view === View.SCHEMA
                ? "Types and counts, read live from the store."
                : "The real nodes. Click one to expand what it connects to."}
            </p>
          </div>

          <div className="flex items-center gap-2">
            <ViewToggle view={view} onChange={setView} />
            <ScopeToggle scope={scope} onChange={changeScope} />
          </div>
        </header>

        {/* Keyed on scope so a switch remounts: the explorer decides whether
            to open rooted or whole from the scope it is born with, and that
            only holds if changing scope gives it a fresh start. */}
        {view === View.DATA && <InstanceExplorer key={scope} scope={scope} />}

        {view === View.SCHEMA && isPending && (
          <Panel title="Reading the graph">
            <p>Counting node and edge types.</p>
          </Panel>
        )}

        {view === View.SCHEMA && error && (
          <Panel title={error instanceof ApiError ? "The graph is unreachable" : "Could not reach the API"}>
            <p>{error.message}</p>
            {error instanceof ApiError && error.remedy ? (
              <p className="mt-2">{error.remedy}</p>
            ) : (
              <>
                <p className="mt-2">Start the API, then reload:</p>
                <Command>cd backend && PYTHONPATH=src uv run uvicorn api.main:app --reload</Command>
              </>
            )}
          </Panel>
        )}

        {view === View.SCHEMA && empty && (
          <Panel title="The store is empty">
            <p>Neo4j is running but nothing has been written to it yet. Build the graph:</p>
            <Command>{BUILD_COMMAND}</Command>
          </Panel>
        )}

        {view === View.SCHEMA && data && !empty && (
          <>
            <div className="rounded-[4px] border border-line bg-card px-3.5 py-2.5">
              <Totals totals={data.totals} />
            </div>

            {/* minmax(0,1fr) on the diagram track: without it the SVG's
                intrinsic width sets the column's minimum and squeezes the
                list off the right edge. */}
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
              <section className="min-w-0 self-start rounded-[4px] border border-line bg-card p-2">
                <SchemaDiagram
                  nodeTypes={data.node_types}
                  edgeTypes={data.edge_types}
                  focus={focus}
                  onFocus={setFocus}
                />
              </section>

              <section className="min-w-0 rounded-[4px] border border-line bg-card py-2.5">
                <EdgeList edgeTypes={data.edge_types} focus={focus} onFocus={setFocus} />
              </section>
            </div>

            <p className="text-[0.6875rem] text-faint">
              Counts are the distinct nodes an in-scope edge touches, so KG2 reports what this
              member reaches rather than what the catalogue holds. Shared types are outlined in
              cobalt; red marks the two edges that carry a safety decision.
            </p>
          </>
        )}
      </div>
    </main>
  )
}
