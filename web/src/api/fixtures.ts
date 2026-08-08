import memberJson from "@data/member-context.json"
import exercisesJson from "@data/exercises.json"
import { daysUntil } from "@/lib/dates"
import {
  ConstraintEffect,
  ConstraintKind,
  type Coach,
  type Constraint,
  type MemberContext,
  type MemberMessage,
  type RosterEntry,
} from "@/types"

/**
 * The assessment's own fixtures, read once and shaped into the domain types.
 *
 * Nothing outside `api/` imports from `@data`. When the Python API lands, this
 * module is the only thing that goes away — the engine below it reads these
 * same shapes, so the traversals it models port straight across.
 */

/** One row of `data/exercises.json`. */
export interface CatalogExercise {
  id: string
  name: string
  muscle_groups: string[]
  joints_loaded: string[]
  movement_patterns: string[]
  equipment_required: string[]
  /**
   * True when the catalogue stocks this movement as a left/right pair —
   * `side` and `bilateral_pair_id` are populated alongside it. It marks work
   * performed one side at a time, which is why dosing is per side.
   */
  is_bilateral: boolean
  side: string | null
  /** False for the eight holds and carries, which are prescribed by time. */
  is_reps: boolean
  is_duration: boolean
  priority_tier: number
  /** Minutes per rep. Sanity-checked against her real session durations. */
  estimated_rep_duration: number
}

interface RawMember {
  profile: { id: string; name: string; age: number; tier: string; member_since: string }
  goals: {
    id: string
    text: string
    priority: number
    target_date: string | null
    targets: string[]
  }[]
  preferences: {
    preferred_session_minutes: number
    training_days_per_week: number
    dislikes: string[]
  }
  equipment_available: string[]
  injuries: MemberContext["injuries"]
  workout_history: {
    date: string
    title: string
    completed: boolean
    duration_min: number
    rpe: number | null
  }[]
  adherence: { weekly_completion_pct: { week_of: string; pct: number }[] }
  biomarkers: { sleep_hours_last_7_days: number[]; resting_hr_bpm: number; hrv_ms: number }
  chat_history: {
    ts: string
    from: "member" | "coach"
    text: string
    attachments?: { type: "image"; caption: string }[]
  }[]
  coach_brief: { churn_risk: { level: string; reasons: string[] } }
}

export const catalog = exercisesJson as CatalogExercise[]
const raw = memberJson as unknown as RawMember

export const SLEEP_TARGET_HOURS = 7

/** The pattern the recorded condition contraindicates outright. */
export const CONTRAINDICATED_PATTERN = "cardio - plyometric"

/**
 * Patterns the condition cautions rather than forbids.
 *
 * The injury note reads "avoid deep knee flexion under load and plyometrics" —
 * two clauses with two strengths, which is why `decisions.md` splits
 * `contraindicates` from `cautions`. A coach may override a caution.
 */
export const CAUTIONED_PATTERNS = ["lower push - squat", "lower push - split squat"]

/** Round to one decimal without a trailing ".0". */
export const oneDp = (n: number) => Number(n.toFixed(1))

/** Initials from a display name, for the roster and member badges. */
function initialsOf(name: string): string {
  return name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()
}

export const coaches: Coach[] = [{ id: "coach_01HXSAM", name: "Sam Ortiz" }]

const completed = raw.workout_history.filter((s) => s.completed)

const typicalMinutes =
  completed.length > 0
    ? Math.round(completed.reduce((n, s) => n + s.duration_min, 0) / completed.length)
    : null

export const sleepNights = raw.biomarkers.sleep_hours_last_7_days
export const sleepAvg = sleepNights.reduce((a, b) => a + b, 0) / sleepNights.length
export const weeklyAdherence = raw.adherence.weekly_completion_pct
export const churnRisk = raw.coach_brief.churn_risk
export const trainingDaysPerWeek = raw.preferences.training_days_per_week
export const preferredSessionMinutes = raw.preferences.preferred_session_minutes
export const firstName = raw.profile.name.split(" ")[0]

/** Muscles this member's goals train, used to light goal-matched tags. */
export const goalMuscles = new Set(raw.goals.flatMap((g) => g.targets))

/** Goal id → text, so a provenance path can name the goal it satisfies. */
export const goalsByMuscle = new Map<string, string>()
for (const goal of raw.goals) {
  for (const muscle of goal.targets) {
    if (!goalsByMuscle.has(muscle)) goalsByMuscle.set(muscle, goal.text)
  }
}

// "This week" means what the fixture means by it. The adherence series keys
// its own weeks (`week_of`), so reading the boundary off the latest entry
// keeps the header and the sparkline talking about the same seven days rather
// than imposing a calendar rule the data doesn't follow.
const currentWeekStart = weeklyAdherence.at(-1)?.week_of ?? ""
const doneThisWeek = completed.filter((s) => s.date >= currentWeekStart).length

const latestAdherence = weeklyAdherence.at(-1)?.pct ?? null
const lastSession = completed.map((s) => s.date).sort().at(-1) ?? null

/** `${kind}:${label}` — the id the builder sends back in `disabled[]`. */
export const itemId = (kind: ConstraintKind, label: string) => `${kind}:${label}`

/**
 * What the generator knows about her, as switches a coach can work.
 *
 * Every string here is written for the coach. The graph relations behind them
 * are real and they are in the trace payload, but a session plan is not the
 * place to read edge syntax.
 */
const constraints: Constraint[] = [
  {
    kind: ConstraintKind.INJURIES,
    label: "Injuries",
    summary: "Rules out jumping and landing outright, and flags deep knee bends.",
    effect: ConstraintEffect.POOL,
    items: raw.injuries.map((injury) => ({
      id: itemId(ConstraintKind.INJURIES, injury.region),
      label: `${injury.region} — ${injury.status}, ${injury.severity}`,
      effect: "Always applied. Nothing that jumps or lands can be prescribed.",
      locked: true,
    })),
  },
  {
    kind: ConstraintKind.EQUIPMENT,
    label: "Equipment she has",
    summary: "Only movements she can actually load are offered.",
    effect: ConstraintEffect.POOL,
    items: raw.equipment_available.map((name) => ({
      id: itemId(ConstraintKind.EQUIPMENT, name),
      label: name,
      effect: "Switch off if she hasn't got it today.",
      locked: false,
    })),
  },
  {
    kind: ConstraintKind.DISLIKES,
    label: "Movements she dislikes",
    summary: "Avoided where there's an alternative, never banned outright.",
    effect: ConstraintEffect.RANKING,
    items: raw.preferences.dislikes.map((name) => ({
      id: itemId(ConstraintKind.DISLIKES, name),
      label: name,
      effect: "Switch off to let this one back into the running.",
      locked: false,
    })),
  },
  {
    kind: ConstraintKind.GOAL_TARGETS,
    label: "What her goals train",
    summary: "Movements hitting these are preferred when there's a choice.",
    effect: ConstraintEffect.RANKING,
    items: [...goalMuscles].map((name) => ({
      id: itemId(ConstraintKind.GOAL_TARGETS, name),
      label: name,
      effect: "Switch off to stop favouring this today.",
      locked: false,
    })),
  },
]

export const member: MemberContext = {
  id: raw.profile.id,
  name: raw.profile.name,
  initials: initialsOf(raw.profile.name),
  age: raw.profile.age,
  tier: raw.profile.tier,
  member_since: raw.profile.member_since,
  trains_at: "home",
  preferred_session_min: preferredSessionMinutes,
  typical_session_min: typicalMinutes,
  equipment_available: raw.equipment_available,
  injuries: raw.injuries,
  dislikes: raw.preferences.dislikes,
  adherence_pct: weeklyAdherence.map((p) => p.pct),
  sessions_done_this_week: doneThisWeek,
  sessions_planned_this_week: trainingDaysPerWeek,
  churn_risk: churnRisk,
  recent_sessions: raw.workout_history
    .slice()
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((s) => ({
      date: s.date,
      title: s.title,
      completed: s.completed,
      duration_min: s.duration_min,
      rpe: s.rpe,
    })),
  goals: raw.goals.map((g) => {
    // A goal is either dated or measured. The sleep goal has no target date,
    // so its progress is the measurement itself rather than a countdown.
    const measured = g.target_date === null
    return {
      ...g,
      days_left: g.target_date ? daysUntil(g.target_date) : null,
      measure: measured ? `${oneDp(sleepAvg)} h this week` : null,
      shortfall:
        measured && sleepAvg < SLEEP_TARGET_HOURS
          ? `${oneDp(SLEEP_TARGET_HOURS - sleepAvg)} h short`
          : null,
    }
  }),
  constraints,
}

/**
 * The roster. Jordan's row is derived from the same fixture the member view
 * reads, so the two can't drift; the rest carry roster metadata only.
 */
export const roster: RosterEntry[] = [
  {
    id: member.id,
    name: member.name,
    initials: member.initials,
    has_context: true,
    last_session_on: lastSession,
    adherence_pct: latestAdherence,
    injury_label: member.injuries[0]?.joint ?? null,
    needs_attention: churnRisk.level !== "low",
  },
  // Roster-level metadata only. These carry no clinical detail, and selecting
  // one renders an empty state rather than fabricated context.
  { id: "mbr_devin", name: "Devin Okoro", initials: "DO", has_context: false, last_session_on: "2026-06-04", adherence_pct: 74, injury_label: null, needs_attention: false },
  { id: "mbr_alex", name: "Alex Mensah", initials: "AM", has_context: false, last_session_on: "2026-06-03", adherence_pct: 92, injury_label: null, needs_attention: false },
  { id: "mbr_priya", name: "Priya Shah", initials: "PS", has_context: false, last_session_on: "2026-06-01", adherence_pct: 100, injury_label: null, needs_attention: false },
]

/** Coach ↔ Jordan. Distinct from the copilot thread by design. */
export const memberMessages: MemberMessage[] = raw.chat_history
  .slice()
  .sort((a, b) => a.ts.localeCompare(b.ts))
  .map((m, i) => ({
    id: `mm_${i}`,
    ts: m.ts,
    from: m.from,
    text: m.text,
    attachments: m.attachments,
  }))
