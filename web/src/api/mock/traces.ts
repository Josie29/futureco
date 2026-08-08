import { TODAY } from "@/lib/dates"
import { renderPath } from "@/lib/provenance"
import {
  SpanKind,
  SpanStatus,
  type RunTrace,
  type RunTraceSummary,
  type TraceSpan,
  type WorkoutPlan,
} from "@/types"

/**
 * MOCK — throwaway. Replaced wholesale by the real tracing backend.
 *
 * The shape of a run, not a simulation of one. Durations and token counts are
 * authored; what is *derived* is the structure — a plan's trace already knows
 * how many concepts resolved, how many movements each rule removed and how
 * many were prescribed, so the spans read off that rather than inventing a
 * second version of the same run.
 *
 * That coupling is the point: if the console says six movements were ruled out
 * by her injury, the graph query span in this tab says the same thing, because
 * it is the same number.
 */

const CYPHER = {
  member: `MATCH (m:Member {id: $memberId})-[:has]->(n)
RETURN m, collect(n) AS context`,
  contraindicated: `MATCH (i:Injury)<-[:has]-(:Member {id: $memberId})
MATCH (i)-[:diagnosed_as]->(c:Condition)-[:contraindicates]->(p:MovementPattern)
MATCH (e:Exercise)-[:is_a]->(p)
RETURN DISTINCT e.id AS excluded, p.name AS pattern`,
  equipment: `MATCH (e:Exercise)-[:requires]->(q:Equipment)
WHERE NOT (:Member {id: $memberId})-[:has]->(q)
RETURN DISTINCT e.id AS excluded, collect(q.name) AS missing`,
  anatomy: `MATCH (a:AnatomicalStructure {name: $site})<-[:part_of*0..]-(sub)
MATCH (e:Exercise)-[:stresses]->(sub)
RETURN DISTINCT e.id AS excluded, sub.name AS structure`,
  rank: `MATCH (e:Exercise) WHERE e.id IN $eligible
OPTIONAL MATCH (e)-[:targets]->(m:Muscle)<-[:targets]-(g:Goal)<-[:has]-(:Member {id: $memberId})
RETURN e.id, count(DISTINCT g) AS goalHits
ORDER BY goalHits DESC`,
  copilot: `MATCH (m:Member {id: $memberId})-[:has]->(n)
WHERE labels(n)[0] IN $facets
RETURN labels(n)[0] AS facet, collect(properties(n)) AS rows`,
}

let counter = 0
const nextId = () => `span_${(counter += 1)}`

interface SpanSeed {
  kind: SpanKind
  name: string
  duration_ms: number
  status?: SpanStatus
  attributes?: { label: string; value: string }[]
  query?: string
  rows_returned?: number
  model?: string
  tokens_in?: number
  tokens_out?: number
  note?: string
}

/** Lay seeds end to end under a root span, so the waterfall reads as a sequence. */
function sequence(rootName: string, seeds: SpanSeed[]): TraceSpan[] {
  const rootId = nextId()
  let cursor = 0
  const children: TraceSpan[] = seeds.map((seed) => {
    const span: TraceSpan = {
      id: nextId(),
      parent_id: rootId,
      kind: seed.kind,
      name: seed.name,
      started_ms: cursor,
      duration_ms: seed.duration_ms,
      status: seed.status ?? SpanStatus.OK,
      attributes: seed.attributes ?? [],
      query: seed.query,
      rows_returned: seed.rows_returned,
      model: seed.model,
      tokens_in: seed.tokens_in,
      tokens_out: seed.tokens_out,
      note: seed.note,
    }
    cursor += seed.duration_ms
    return span
  })

  const worst = children.some((s) => s.status === SpanStatus.ERROR)
    ? SpanStatus.ERROR
    : children.some((s) => s.status === SpanStatus.DEGRADED)
      ? SpanStatus.DEGRADED
      : SpanStatus.OK

  const root: TraceSpan = {
    id: rootId,
    parent_id: null,
    kind: SpanKind.AGENT,
    name: rootName,
    started_ms: 0,
    duration_ms: cursor,
    status: worst,
    attributes: [],
  }

  return [root, ...children]
}

function totalsOf(spans: TraceSpan[]) {
  return {
    graph_queries: spans.filter((s) => s.kind === SpanKind.GRAPH).length,
    llm_calls: spans.filter((s) => s.kind === SpanKind.LLM).length,
    tokens_in: spans.reduce((n, s) => n + (s.tokens_in ?? 0), 0),
    tokens_out: spans.reduce((n, s) => n + (s.tokens_out ?? 0), 0),
  }
}

/**
 * Turn a generated plan into the trace the runtime would have emitted.
 *
 * Every count here is read off `plan.trace`, so this tab and the plan sheet
 * can never disagree about what happened.
 */
export function traceForPlan(plan: WorkoutPlan): RunTrace {
  const t = plan.trace
  const injuryCuts = t.filtered.filter((f) => f.cause === "injury").length
  const equipmentCuts = t.filtered.filter((f) => f.cause === "equipment").length
  const declined = t.unresolved.length

  /** Bounded: 26 equipment cuts is a scroll, not a detail panel. */
  const sample = <T,>(rows: T[], render: (row: T) => { label: string; value: string }) => {
    const shown = rows.slice(0, 8).map(render)
    return rows.length > 8
      ? [...shown, { label: "…", value: `and ${rows.length - 8} more` }]
      : shown
  }

  const cutsBy = (cause: string) =>
    sample(
      t.filtered.filter((f) => f.cause === cause),
      (f) => ({ label: f.name, value: f.path.hops.length > 0 ? renderPath(f.path) : f.detail }),
    )

  const spans = sequence(`Generate session · ${plan.title}`, [
    {
      kind: SpanKind.LLM,
      name: "Classify request",
      duration_ms: 310,
      model: "claude-sonnet-5",
      tokens_in: 412,
      tokens_out: 88,
      attributes: [
        { label: "prompt", value: plan.prompt },
        { label: "intents found", value: `${t.resolved.length}` },
      ],
    },
    {
      kind: SpanKind.RESOLVE,
      name: "Resolve concepts",
      duration_ms: 46,
      status: declined > 0 ? SpanStatus.DEGRADED : SpanStatus.OK,
      note:
        declined > 0
          ? `${declined} phrase${declined === 1 ? "" : "s"} declined below threshold — reported to the coach rather than guessed`
          : undefined,
      attributes: [
        ...t.resolved.map((c) => ({
          label: `"${c.phrase}"`,
          value: `${c.concept_name} · ${c.pass} · ${c.confidence}`,
        })),
        ...t.unresolved.map((u) => ({
          label: `"${u.phrase}"`,
          value: `declined · nearest ${u.best_guess ?? "none"} at ${u.confidence} < ${u.threshold}`,
        })),
      ],
    },
    {
      kind: SpanKind.GRAPH,
      name: "Load member context",
      duration_ms: 22,
      query: CYPHER.member,
      rows_returned: 12,
      attributes: [{ label: "member", value: "mbr_01HX9JORDAN" }],
    },
    {
      kind: SpanKind.GRAPH,
      name: "Apply contraindications",
      duration_ms: 31,
      query: CYPHER.contraindicated,
      rows_returned: injuryCuts,
      attributes: [
        { label: "condition", value: "patellofemoral pain syndrome" },
        { label: "movements excluded", value: `${injuryCuts}` },
        // ASSESSMENT.md:33 — what was filtered out for safety, and the
        // traversal that did it. The console says this in plain words; here
        // it is the edge walk itself.
        ...cutsBy("injury"),
      ],
    },
    {
      kind: SpanKind.GRAPH,
      name: "Filter by equipment",
      duration_ms: 18,
      query: CYPHER.equipment,
      rows_returned: equipmentCuts,
      attributes: [
        { label: "movements excluded", value: `${equipmentCuts}` },
        ...cutsBy("equipment"),
      ],
    },
    {
      kind: SpanKind.GRAPH,
      name: "Rank against goals",
      duration_ms: 27,
      query: CYPHER.rank,
      rows_returned: t.eligible,
      attributes: [{ label: "eligible pool", value: `${t.eligible}` }],
    },
    {
      kind: SpanKind.TOOL,
      name: "assemble_session",
      duration_ms: 14,
      attributes: [
        { label: "window", value: `${plan.requested_minutes} min` },
        { label: "prescribed", value: `${t.prescribed}` },
        { label: "estimated", value: `${plan.estimated_minutes} min` },
        // ASSESSMENT.md:33 — why each exercise was chosen and which graph path
        // justified it. `why[].says` is what the coach reads on the sheet;
        // `why[].path` is the same decision as a traversal, and this is the
        // only place it is rendered.
        ...plan.exercises.flatMap((exercise) =>
          exercise.why.map((reason) => ({
            label: exercise.name,
            value: renderPath(reason.path),
          })),
        ),
      ],
    },
    {
      kind: SpanKind.LLM,
      name: "Write coaching notes",
      duration_ms: 640,
      model: "claude-sonnet-5",
      tokens_in: 980,
      tokens_out: 214,
      attributes: [{ label: "notes written", value: `${plan.exercises.filter((e) => e.note).length}` }],
    },
  ])

  return {
    run_id: plan.run_id,
    source: "generator",
    prompt: plan.prompt,
    started_at: t.generated_at,
    duration_ms: spans[0].duration_ms,
    status: spans[0].status,
    totals: totalsOf(spans),
    spans,
  }
}

/** A copilot answer, for contrast: retrieval-shaped rather than filter-shaped. */
function copilotTrace(runId: string, prompt: string, minutesAgo: number): RunTrace {
  const spans = sequence(`Answer · ${prompt}`, [
    {
      kind: SpanKind.LLM,
      name: "Plan retrieval",
      duration_ms: 280,
      model: "claude-sonnet-5",
      tokens_in: 356,
      tokens_out: 64,
      attributes: [{ label: "facets requested", value: "adherence, workout_history" }],
    },
    {
      kind: SpanKind.GRAPH,
      name: "Fetch member facets",
      duration_ms: 19,
      query: CYPHER.copilot,
      rows_returned: 9,
      attributes: [{ label: "facets", value: "adherence, workout_history, chat_history" }],
    },
    {
      kind: SpanKind.TOOL,
      name: "build_chart",
      duration_ms: 6,
      attributes: [
        { label: "kind", value: "adherence" },
        { label: "points", value: "4" },
      ],
    },
    {
      kind: SpanKind.LLM,
      name: "Compose answer",
      duration_ms: 520,
      model: "claude-sonnet-5",
      tokens_in: 1240,
      tokens_out: 186,
      attributes: [{ label: "citations", value: "1" }],
    },
  ])

  const started = new Date(`${TODAY}T07:20:00-07:00`)
  started.setMinutes(started.getMinutes() - minutesAgo)

  return {
    run_id: runId,
    source: "copilot",
    prompt,
    started_at: started.toISOString(),
    duration_ms: spans[0].duration_ms,
    status: spans[0].status,
    totals: totalsOf(spans),
    spans,
  }
}

/** A run that failed, so the tab shows more than the happy path. */
function failedTrace(): RunTrace {
  const spans = sequence("Generate session · timed out", [
    {
      kind: SpanKind.LLM,
      name: "Classify request",
      duration_ms: 298,
      model: "claude-sonnet-5",
      tokens_in: 402,
      tokens_out: 81,
    },
    {
      kind: SpanKind.RESOLVE,
      name: "Resolve concepts",
      duration_ms: 44,
      attributes: [{ label: '"shoulder"', value: "shoulder · exact · 1" }],
    },
    {
      kind: SpanKind.GRAPH,
      name: "Apply contraindications",
      duration_ms: 5031,
      status: SpanStatus.ERROR,
      query: CYPHER.contraindicated,
      note: "Neo4j read timed out after 5s. No plan was returned; the coach saw the error state rather than an unfiltered session.",
      attributes: [{ label: "timeout", value: "5000 ms" }],
    },
  ])

  return {
    run_id: "run_2c8ad401",
    source: "generator",
    prompt: "Upper body, avoid the shoulder",
    started_at: `${TODAY}T06:58:12-07:00`,
    duration_ms: spans[0].duration_ms,
    status: SpanStatus.ERROR,
    totals: totalsOf(spans),
    spans,
  }
}

/**
 * Runs recorded this session, newest first.
 *
 * In-memory on purpose — a page reload starts clean, which is honest about
 * this being a stand-in rather than a store.
 */
const recorded: RunTrace[] = []

const seeded: RunTrace[] = [
  copilotTrace("run_9f14bb02", "Show me the brief", 18),
  copilotTrace("run_71d0ce55", "Plot adherence trend", 12),
  failedTrace(),
]

/** Called by the client whenever a plan comes back, so the tab stays live. */
export function recordPlanRun(plan: WorkoutPlan): void {
  const trace = traceForPlan(plan)
  const existing = recorded.findIndex((r) => r.run_id === trace.run_id)
  if (existing >= 0) recorded.splice(existing, 1)
  recorded.unshift(trace)
}

export function recordCopilotRun(runId: string, prompt: string): void {
  recorded.unshift(copilotTrace(runId, prompt, 0))
}

function allRuns(): RunTrace[] {
  return [...recorded, ...seeded]
}

export function listTraces(): RunTraceSummary[] {
  return allRuns().map(({ spans: _spans, ...summary }) => summary)
}

export function getTraceById(runId: string): RunTrace | undefined {
  return allRuns().find((r) => r.run_id === runId)
}
