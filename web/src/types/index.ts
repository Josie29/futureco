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

/** Member constraints a coach may lift for a single run. Injury is absent by
 *  design — it is loaded server-side and has no client-settable off switch. */
export enum LiftableRule {
  EQUIPMENT = "equipment",
  DISLIKES = "dislikes",
  GOALS = "goals",
}

export enum PlanBlock {
  WARMUP = "warmup",
  MAIN = "main",
  COOLDOWN = "cooldown",
}

export interface Coach {
  id: string
  name: string
}

/** Roster-level metadata only. Never full member context. */
export interface RosterEntry {
  id: string
  name: string
  /** False for the synthetic filler members, which render an empty state. */
  has_context: boolean
  last_session_on: string | null
  adherence_pct: number | null
  injury_label: string | null
  churn_risk: "low" | "elevated" | "high" | null
}

export interface Injury {
  id: string
  region: string
  joint: string
  status: string
  severity: string
  since: string
  notes: string
}

export interface Goal {
  id: string
  text: string
  priority: number
  target_date: string | null
  targets: string[]
}

export interface Preferences {
  preferred_session_minutes: number
  training_days_per_week: number
  preferred_days: string[]
  dislikes: string[]
  notes: string
}

export interface AdherencePoint {
  week_of: string
  pct: number
}

export interface SessionRecord {
  date: string
  title: string
  planned: boolean
  completed: boolean
  duration_min: number
  rpe: number | null
}

export interface MemberContext {
  id: string
  name: string
  age: number
  tier: string
  member_since: string
  goals: Goal[]
  preferences: Preferences
  equipment_available: string[]
  injuries: Injury[]
  recent_sessions: SessionRecord[]
  adherence: { weekly_completion_pct: AdherencePoint[]; trend: string }
}

/** The standing eligible pool for a member, before any request narrows it. */
export interface Eligibility {
  total: number
  available: number
  excluded_by: Record<FilterCause, number>
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
  verdict: Verdict
  /** One line, already rendered by the API: "stresses knee ← patellofemoral". */
  trace: string
  /** Set when this exercise replaced one that was filtered out. */
  substituted_for: { id: string; name: string; via_pattern: string } | null
}

export interface FilteredExercise {
  id: string
  name: string
  cause: FilterCause
  trace: string
}

export interface ProvenanceTrace {
  run_id: string
  generated_at: string
  catalogue_total: number
  eligible: number
  filtered: FilteredExercise[]
  /** Phrases the resolver could not match above threshold, with what we did
   *  instead. Rendering these is the graceful-degradation requirement. */
  unresolved: { phrase: string; fallback: string }[]
}

export interface WorkoutPlan {
  run_id: string
  parent_run_id: string | null
  title: string
  requested_minutes: number
  estimated_minutes: number
  exercises: PlanExercise[]
  trace: ProvenanceTrace
}

export interface PlanRequest {
  /** Required and unconstrained — the mandated input (ASSESSMENT.md:23). */
  prompt: string
  duration_min: number
  lifted_rules: LiftableRule[]
}

export interface ChatAttachment {
  type: "image"
  caption: string
  /** Absent in the sample data, so the UI renders a captioned placeholder. */
  url?: string
}

export interface ChatMessage {
  id: string
  ts: string
  from: "member" | "coach" | "copilot"
  text: string
  attachments?: ChatAttachment[]
  chart?: ChartPayload
}

export enum ChartKind {
  ADHERENCE = "adherence",
  SLEEP = "sleep",
  MESSAGE_PATTERN = "message_pattern",
}

export interface ChartPayload {
  kind: ChartKind
  title: string
  unit: string
  series: { label: string; value: number }[]
}
