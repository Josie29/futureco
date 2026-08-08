/**
 * Wire contracts for the coach console. These mirror the Pydantic models the
 * API exposes, so a change on either side should break the other loudly.
 * See docs/frontend-spec.md, "API surface".
 */

/** Why an exercise did or didn't make the plan. One hue, three intensities. */
export enum Verdict {
  /** Hard filter — an absolute contraindication or missing equipment. */
  EXCLUDED = "excluded",
  /** Down-ranked but selectable. A coach may override a caution. */
  CAUTION = "caution",
  /** Cleared. The unremarkable good state. */
  CLEARED = "cleared",
}

/** What caused an exercise to be filtered out. Drives the trace grouping. */
export enum FilterCause {
  INJURY = "injury",
  EQUIPMENT = "equipment",
  DISLIKE = "dislike",
  EXCLUSION = "exclusion",
  OUT_OF_SCOPE = "out_of_scope",
}

/**
 * Constraint classes applied to every generation. These are fixed categories
 * rather than one member's facts — each maps to an edge type in the member
 * graph, so a second dataset fills them without a redesign.
 */
export enum ConstraintKind {
  INJURIES = "injuries",
  EQUIPMENT = "equipment",
  DISLIKES = "dislikes",
  GOAL_TARGETS = "goal_targets",
}

/**
 * What lifting a constraint actually does to the catalogue.
 *
 * Only `POOL` constraints change the eligible count. Saying so on the chip
 * stops a `RANKING` lift from reading as a broken control when the bar
 * doesn't move.
 */
export enum ConstraintEffect {
  /** Removes movements from the eligible pool. */
  POOL = "pool",
  /** Reorders the pool without removing anything from it. */
  RANKING = "ranking",
}

export enum PlanBlock {
  WARMUP = "warmup",
  MAIN = "main",
  COOLDOWN = "cooldown",
}

/**
 * Node labels the resolver can return. The caller passes the labels it
 * accepts; the resolver never guesses by precedence.
 * See docs/decisions.md, "Resolver", decision 1.
 */
export enum ConceptLabel {
  MUSCLE = "Muscle",
  PATTERN = "MovementPattern",
  EQUIPMENT = "Equipment",
  ANATOMY = "AnatomicalStructure",
  EXERCISE = "Exercise",
}

/** Which pass matched. Exact and alias are one pass; both are certain. */
export enum ResolutionPass {
  EXACT = "exact",
  ALIAS = "alias",
  FUZZY = "fuzzy",
  VECTOR = "vector",
}

/** How a resolved concept is meant to act on the catalogue. */
export enum ConceptIntent {
  /** Narrow the plan toward this concept. */
  FOCUS = "focus",
  /** Remove movements reaching this concept. */
  EXCLUDE = "exclude",
  /** Treat as a body site to protect. */
  PROTECT = "protect",
}

export enum ChartKind {
  ADHERENCE = "adherence",
  SLEEP = "sleep",
  MESSAGE_PATTERN = "message_pattern",
  WEEKLY_COMPARISON = "weekly_comparison",
}

export interface Coach {
  id: string
  name: string
}

/** Stored in localStorage by the mock login. Mock auth is fine (ASSESSMENT.md:72). */
export interface Session {
  coach: Coach
  signed_in_at: string
}

/** Roster-level metadata only. Never full member context. */
export interface RosterEntry {
  id: string
  name: string
  initials: string
  /** False for the synthetic filler members, which render an empty state. */
  has_context: boolean
  last_session_on: string | null
  adherence_pct: number | null
  injury_label: string | null
  needs_attention: boolean
}

export interface Injury {
  id: string
  region: string
  joint: string
  status: string
  severity: string
  since: string
  notes: string
  /** The clinical condition the contraindication rules hang off. */
  condition: string
}

export interface Goal {
  id: string
  text: string
  /** 1 renders a filled marker, anything else a hollow one. */
  priority: number
  target_date: string | null
  /** Muscle names drawn from the KG1 vocabulary. May be empty. */
  targets: string[]
  /** Null when the goal has no date; then `measure` carries its progress. */
  days_left: number | null
  /** For goals measured rather than dated, e.g. "6.3 h this week". */
  measure: string | null
  /** How far off the measure is, e.g. "0.7 h short". Null when on track. */
  shortfall: string | null
}

export interface SessionRecord {
  date: string
  title: string
  completed: boolean
  duration_min: number
  rpe: number | null
}

/**
 * One switchable fact about the member.
 *
 * Granular on purpose: a coach whose member left her bench at the office wants
 * to drop the bench, not the whole equipment rule.
 */
export interface ConstraintItem {
  /** Stable id, `${kind}:${label}`. Sent back as `disabled[]`. */
  id: string
  label: string
  /** What switching this off does, in the coach's words. */
  effect: string
  /** Injury items can never be switched off. The API refuses it too. */
  locked: boolean
}

/** One applied constraint class, with the loaded member's specifics. */
export interface Constraint {
  kind: ConstraintKind
  /** Fixed, dataset-agnostic label: "Injuries", "Equipment", … */
  label: string
  /** One plain sentence about what this group does to the session. */
  summary: string
  /** Items belonging to this member. Empty is a valid, rendered state. */
  items: ConstraintItem[]
  /** Whether switching items changes the pool or only the emphasis. */
  effect: ConstraintEffect
}

/** Churn signal from `coach_brief`. Surfaced in the header, not only in chat. */
export interface ChurnRisk {
  level: string
  reasons: string[]
}

export interface MemberContext {
  id: string
  name: string
  initials: string
  age: number
  tier: string
  member_since: string
  trains_at: string
  goals: Goal[]
  preferred_session_min: number
  /** Mean duration of completed sessions — derived, not stored. */
  typical_session_min: number | null
  equipment_available: string[]
  injuries: Injury[]
  dislikes: string[]
  recent_sessions: SessionRecord[]
  adherence_pct: number[]
  sessions_done_this_week: number
  sessions_planned_this_week: number
  churn_risk: ChurnRisk
  constraints: Constraint[]
}

/** The standing eligible pool for a member, before any request narrows it. */
export interface Eligibility {
  total: number
  available: number
  excluded_by: Record<FilterCause, number>
}

/** A muscle this exercise trains, flagged when it matches a goal target. */
export interface MuscleTag {
  name: string
  is_goal_target: boolean
}

/**
 * One step of a graph traversal, rendered as a path rather than prose.
 *
 * `Dumbbell Goblet Split Squat -targets-> quads <-targets- Build lower-body
 * strength` is the justification a coach can audit; "chosen because it suits
 * her goals" is not.
 */
export interface GraphPath {
  /** The traversal, arrows included. Rendered in mono. */
  path: string
  /** One plain sentence naming what the path establishes. */
  says: string
}

export interface PlanExercise {
  id: string
  name: string
  block: PlanBlock
  sets: number | null
  reps: number | null
  duration_sec: number | null
  rest_sec: number | null
  /** True when the catalogue pairs this movement left/right. */
  per_side: boolean
  /** Derived from rep duration, sets, reps, rest — and sides. */
  minutes: number
  muscles: MuscleTag[]
  equipment: string[]
  verdict: Verdict
  /** One plain sentence, or null when nothing needs the coach's attention. */
  note: string | null
  /** Why this movement is in the plan, as graph paths. Never empty. */
  why: GraphPath[]
}

export interface FilteredExercise {
  id: string
  name: string
  cause: FilterCause
  /** The offending values — "barbell · plate · rack", "plyometric". */
  detail: string
  /** The traversal that removed it. */
  path: string
}

/** A phrase the resolver matched onto a canonical concept. */
export interface ResolvedConcept {
  phrase: string
  label: ConceptLabel
  concept_id: string
  concept_name: string
  pass: ResolutionPass
  /** 0–1. Compared against the pass's committed threshold. */
  confidence: number
  intent: ConceptIntent
  /** "left" / "right" when the phrase carried laterality, else null. */
  side: string | null
}

/**
 * A phrase no pass reached above threshold.
 *
 * Rendering these is the graceful-degradation requirement (ASSESSMENT.md:68) —
 * the console names what it could not resolve and what it did instead.
 */
export interface UnresolvedPhrase {
  phrase: string
  /** Nearest concept considered, or null when nothing scored at all. */
  best_guess: string | null
  /** Score of that best guess, for comparison against the threshold. */
  confidence: number
  threshold: number
  /** What the system did instead. Never "nothing". */
  fallback: string
}

/** One named stage of the generation pipeline, with what it did. */
export interface TraceStage {
  label: string
  /** Movements remaining after this stage. */
  remaining: number
  detail: string
}

export interface ProvenanceTrace {
  run_id: string
  generated_at: string
  catalogue_total: number
  /** Survivors of the standing constraints, before the request narrows. */
  eligible: number
  /** How many made the final plan. */
  prescribed: number
  stages: TraceStage[]
  resolved: ResolvedConcept[]
  unresolved: UnresolvedPhrase[]
  /** Every dropped movement, not a sample. Counts must reconcile. */
  filtered: FilteredExercise[]
}

export interface WorkoutPlan {
  run_id: string
  /** Set when this run adjusts an earlier one. Adjustments are new runs. */
  parent_run_id: string | null
  /** The prompt that produced this run, echoed for the revision trail. */
  prompt: string
  title: string
  day_label: string
  requested_minutes: number
  estimated_minutes: number
  exercises: PlanExercise[]
  trace: ProvenanceTrace
}

export interface PlanRequest {
  /** Required and unconstrained — the mandated input (ASSESSMENT.md:23). */
  prompt: string
  duration_min: number
  /**
   * `ConstraintItem.id`s switched off for this run. Never an injury item —
   * the server loads injuries from the member id and applies them whatever
   * this array says.
   */
  disabled: string[]
}

export interface ChatAttachment {
  type: "image"
  caption: string
  /** Absent in the sample data, so the UI renders a captioned placeholder. */
  url?: string
}

/** A member message quoted inside a copilot answer as retrieval evidence. */
export interface Citation {
  message_id: string
  from: string
  when: string
  text: string
}

/** Coach ↔ member. Lives in the Messages tab. */
export interface MemberMessage {
  id: string
  ts: string
  from: "member" | "coach"
  text: string
  attachments?: ChatAttachment[]
}

export interface ChartPoint {
  label: string
  value: number
  /** Marks the point as the one the answer is about. */
  alert?: boolean
}

export interface ChartPayload {
  kind: ChartKind
  title: string
  unit: string
  /** Reference line — her stated target. Null when the metric has none. */
  target: number | null
  series: ChartPoint[]
  /** One sentence naming what the chart shows. Read by screen readers. */
  caption: string
}

/** Coach ↔ copilot. Lives in the Copilot tab. Never mixed with the above. */
export interface CopilotMessage {
  id: string
  ts: string
  from: "coach" | "copilot"
  /** Paragraphs. The brief runs long on purpose. */
  paragraphs: { lead?: string; text: string }[]
  cites?: Citation[]
  chart?: ChartPayload
  /** True while the answer is in flight; renders a skeleton. */
  pending?: boolean
}

/** A quick prompt in the palette. `chart` ones return a ChartPayload. */
export interface QuickPrompt {
  label: string
  prompt: string
  is_chart: boolean
}

/**
 * What kind of work a span did.
 *
 * Deliberately coarse: these are the four things ASSESSMENT.md:134 asks to be
 * observable — graph queries, LLM calls, tools, and the agent steps around
 * them — plus resolution, which is where most of the interesting failures are.
 */
export enum SpanKind {
  AGENT = "agent",
  RESOLVE = "resolve",
  GRAPH = "graph",
  LLM = "llm",
  TOOL = "tool",
}

export enum SpanStatus {
  OK = "ok",
  /** Completed, but something was declined or fell back. */
  DEGRADED = "degraded",
  ERROR = "error",
}

/** One key/value line in a span's detail panel. */
export interface SpanAttribute {
  label: string
  value: string
}

export interface TraceSpan {
  id: string
  /** Null for the root span. */
  parent_id: string | null
  kind: SpanKind
  name: string
  /** Milliseconds from the start of the run. Drives the waterfall offset. */
  started_ms: number
  duration_ms: number
  status: SpanStatus
  attributes: SpanAttribute[]
  /** Cypher, for `GRAPH` spans. Rendered verbatim. */
  query?: string
  rows_returned?: number
  /** Model call detail, for `LLM` spans. */
  model?: string
  tokens_in?: number
  tokens_out?: number
  /** The one-line reason a span is degraded or errored. */
  note?: string
}

export interface RunTotals {
  graph_queries: number
  llm_calls: number
  tokens_in: number
  tokens_out: number
}

/** One end-to-end request, as the tracing backend will report it. */
export interface RunTrace {
  run_id: string
  /** Which surface produced it. */
  source: "generator" | "copilot"
  /** The coach's words, so a run is findable by what was asked. */
  prompt: string
  started_at: string
  duration_ms: number
  status: SpanStatus
  totals: RunTotals
  spans: TraceSpan[]
}

/** List-view row. The detail endpoint returns the full `RunTrace`. */
export interface RunTraceSummary {
  run_id: string
  source: RunTrace["source"]
  prompt: string
  started_at: string
  duration_ms: number
  status: SpanStatus
  totals: RunTotals
}
