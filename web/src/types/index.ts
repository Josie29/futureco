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

/** One applied constraint class, with the loaded member's specifics. */
export interface Constraint {
  kind: ConstraintKind
  /** Fixed, dataset-agnostic label: "Injuries", "Equipment", … */
  label: string
  /** Items belonging to this member. Empty is a valid, rendered state. */
  items: string[]
  /** What applying this does, in graph terms. Shown when expanded. */
  effect: string
  /** Injuries can never be lifted; the API refuses it too. */
  liftable: boolean
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
  recent_sessions: SessionRecord[]
  adherence_pct: number[]
  sessions_done_this_week: number
  sessions_planned_this_week: number
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
  /** Derived from rep duration, sets, reps and rest. */
  minutes: number
  muscles: MuscleTag[]
  equipment: string[]
  verdict: Verdict
  /** One plain sentence, or null when nothing needs the coach's attention. */
  note: string | null
}

export interface FilteredExercise {
  id: string
  name: string
  cause: FilterCause
  detail: string
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
  /** Constraint classes the coach lifted for this run. Never INJURIES. */
  lifted: ConstraintKind[]
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

/** Coach ↔ copilot. Lives in the Copilot tab. Never mixed with the above. */
export interface CopilotMessage {
  id: string
  ts: string
  from: "coach" | "copilot"
  /** Paragraphs. The brief runs long on purpose. */
  paragraphs: { lead?: string; text: string }[]
  cites?: Citation[]
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
