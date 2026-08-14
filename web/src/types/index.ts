/**
 * Wire contracts for the coach console. These mirror the Pydantic models the
 * API exposes, so a change on either side should break the other loudly.
 * See docs/frontend-spec.md, "API surface".
 */

// Re-exported so a consumer of the plan contract doesn't have to know that the
// graph vocabulary is declared alongside the inspector's types. Both mirror
// `backend/src/graph/schema.py`; declaring them twice would let them drift.
export { NodeLabel, RelType } from "@/types/graph"

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
  /**
   * Any metric plotted against its own reference band.
   *
   * The general case, and free once observations are reified: sleep, weight,
   * HRV and every lab value are the same shape, so plotting one is the same
   * code as plotting another. The four named kinds stay because each carries a
   * framing a generic series can't — adherence is read against her plan, sleep
   * against her goal, message pattern against the adherence weeks.
   */
  METRIC = "metric",
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
  /**
   * The date this dataset is read as "today".
   *
   * Every window in the system is relative to this rather than to a wall clock.
   * The record ends in June 2026, so a real-date anchor empties "this week" and
   * makes her look like she stopped training. Served so the console doesn't
   * keep a second copy — see `lib/dates.ts`.
   */
  as_of: string
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

/** How the catalog stands for this member before any coach directive. */
export interface Eligibility {
  total: number
  eligible: number
  blocked: number
  cautioned: number
  disliked: number
}

/** One slot of the generated plan, exactly as the agent produced it. */
export interface PlannedExercise {
  concept_id: string
  label: string
  sets: number
  /** A prescription the coach reads: "8-10", "30s", "5 per side". */
  reps: string
  /** Whole-session cost of this slot including its rest. */
  seconds: number
  rationale: string
  /**
   * Present exactly when this exercise carries a clinical caution: one
   * sentence on how the prescription respects it. An acknowledgment, not a
   * clearance.
   */
  caution_note: string
}

/** The agent's plan: three sections, structurally. */
export interface AgentPlan {
  title: string
  total_seconds: number
  warmup: PlannedExercise[]
  main: PlannedExercise[]
  cooldown: PlannedExercise[]
  coach_notes: string
}

/** One chart-derived constraint, with its graph traversal rendered. */
export interface ClinicalRule {
  target: string
  effect: string
  reason: string
  evidence: string
}

export interface ResolutionRecord {
  query: string
  concept: string | null
  method: string | null
  confidence: number | null
  alternatives: string[]
}

export interface DeclaredConstraint {
  target: string
  effect: string
  reason: string
}

export interface DeclarationRecord {
  added: DeclaredConstraint[]
  removed: DeclaredConstraint[]
  unchanged: DeclaredConstraint[]
  rejected_targets: string[]
}

export interface ExclusionRecord {
  concept_id: string
  cause: string
  matched_target: string
  reason: string
  evidence: string | null
}

export interface RetrievalRecord {
  eligible_count: number
  exclusions: ExclusionRecord[]
  unmatched_requires: string[]
}

export interface Usage {
  llm_calls: number
  tokens_in: number
  tokens_out: number
}

/** Every decision behind the plan, projected from the run's tool log. */
export interface PlanProvenance {
  clinical: ClinicalRule[]
  resolutions: ResolutionRecord[]
  declarations: DeclarationRecord[]
  retrieval: RetrievalRecord | null
  usage: Usage
}

/** A member goal a planned exercise serves, and the muscle they share. */
export interface GoalTag {
  goal: string
  priority: number
  muscle: string
}

/** Why one planned exercise fits: the card's facts as display names. */
export interface ExerciseFacts {
  muscles: string[]
  /** Muscles the coach's directives or the member's goals point at. */
  focus_muscles: string[]
  equipment: string[]
  missing_equipment: string[]
  goals: GoalTag[]
  /** The declared prefer/require targets this card carries. */
  from_coach: string[]
  /** True only for a disliked exercise kept by an exact require. */
  disliked: boolean
}

/** The wire contract for one generated or adjusted plan. */
export interface PlanResponse {
  run_id: string
  parent_run_id: string | null
  member_id: string
  prompt: string
  duration_min: number
  plan: AgentPlan
  provenance: PlanProvenance
  /** Per-slot card facts, keyed by the slot's concept_id. */
  exercise_facts: Record<string, ExerciseFacts>
}

export interface PlanRequest {
  prompt: string
  duration_min: number
}

export interface ChatAttachment {
  type: "image"
  caption: string
  /** Null in the sample data, so the UI renders a captioned placeholder. */
  url?: string | null
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
  paragraphs: { lead?: string | null; text: string }[]
  cites?: Citation[]
  chart?: ChartPayload | null
  /** True while the answer is in flight; renders a skeleton. */
  pending?: boolean
  /**
   * Why this answer is less than a full one, or null when it is complete.
   *
   * Set when prose synthesis is unavailable, when a citation was dropped as
   * invented, or when the model declined. Rendered as a banner above the
   * answer — an answer that quietly did less than it appears to would be the
   * worst thing this surface could show, so the console never hides it.
   */
  degraded?: string | null
}

/** Which row of the palette a quick prompt sits in (ASSESSMENT.md:41-42). */
export enum QuickPromptGroup {
  /** Questions about the loaded member. Several return a chart alongside the prose. */
  MEMBER = "member",
  /**
   * Chips whose point *is* the chart.
   *
   * Separated from `MEMBER` by what the coach is asking for, not by whether a
   * ChartPayload comes back — "How's her adherence trending?" also returns one,
   * and still belongs with the questions.
   */
  CHARTS = "charts",
}

/** A quick prompt in the palette. */
export interface QuickPrompt {
  label: string
  prompt: string
  group: QuickPromptGroup
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
