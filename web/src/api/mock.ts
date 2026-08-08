import memberJson from "@data/member-context.json"
import exercisesJson from "@data/exercises.json"
import { daysUntil } from "@/lib/dates"
import {
  ConstraintKind,
  FilterCause,
  PlanBlock,
  Verdict,
  type Coach,
  type CopilotMessage,
  type Eligibility,
  type MemberContext,
  type MemberMessage,
  type MuscleTag,
  type PlanExercise,
  type PlanRequest,
  type RosterEntry,
  type WorkoutPlan,
} from "@/types"

/**
 * Stand-in for the API while the backend is being built. Everything here is
 * derived from the assessment's own fixtures rather than invented, so the
 * numbers on screen match what the real traversal will produce.
 *
 * Delete this module once `/api` is live; nothing outside it should import
 * from `@data`.
 */

interface RawExercise {
  id: string
  name: string
  muscle_groups: string[]
  joints_loaded: string[]
  movement_patterns: string[]
  equipment_required: string[]
  estimated_rep_duration: number
}

const exercises = exercisesJson as RawExercise[]
const member = memberJson as unknown as {
  profile: { id: string; name: string; age: number; tier: string; member_since: string }
  goals: { id: string; text: string; priority: number; target_date: string | null; targets: string[] }[]
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
  biomarkers: { sleep_hours_last_7_days: number[] }
  chat_history: {
    ts: string
    from: "member" | "coach"
    text: string
    attachments?: { type: "image"; caption: string }[]
  }[]
  coach_brief: { churn_risk: { level: string; reasons: string[] } }
}

const PLYOMETRIC = "cardio - plyometric"
const SLEEP_TARGET_HOURS = 7

const owned = new Set(member.equipment_available)
const byName = new Map(exercises.map((e) => [e.name, e]))

const hasEquipment = (e: RawExercise) => e.equipment_required.every((i) => owned.has(i))
const isPlyometric = (e: RawExercise) => e.movement_patterns.includes(PLYOMETRIC)

/** Muscles this member's goals train, used to light goal-matched tags. */
const goalMuscles = new Set(member.goals.flatMap((g) => g.targets))

/** Initials from a display name, for the roster and member badges. */
function initialsOf(name: string): string {
  return name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()
}

/** Round to one decimal without trailing ".0". */
const oneDp = (n: number) => Number(n.toFixed(1))

/**
 * The standing eligible pool: what this member could do today given the rules
 * currently applied, before any request narrows it further.
 *
 * Mirrors the Cypher the real endpoint will run. With nothing lifted this
 * returns 18 of 50 — 29 dropped on equipment, 3 on the knee contraindication.
 *
 * @param lifted Constraint classes the coach switched off for this run.
 *   `INJURIES` is ignored if passed; injuries are applied unconditionally.
 * @returns Counts of what survived and what each cause removed.
 */
export function computeEligibility(lifted: ConstraintKind[] = []): Eligibility {
  const applyEquipment = !lifted.includes(ConstraintKind.EQUIPMENT)

  let equipmentCut = 0
  let injuryCut = 0
  let available = 0

  for (const e of exercises) {
    if (applyEquipment && !hasEquipment(e)) {
      equipmentCut += 1
      continue
    }
    // Injury is unconditional — there is no branch that skips it.
    if (isPlyometric(e)) {
      injuryCut += 1
      continue
    }
    available += 1
  }

  return {
    total: exercises.length,
    available,
    excluded_by: {
      [FilterCause.EQUIPMENT]: equipmentCut,
      [FilterCause.INJURY]: injuryCut,
      [FilterCause.DISLIKE]: 0,
      [FilterCause.EXCLUSION]: 0,
      [FilterCause.OUT_OF_SCOPE]: 0,
    },
  }
}

export const mockCoaches: Coach[] = [{ id: "coach_01HXSAM", name: "Sam Ortiz" }]

export const mockRoster: RosterEntry[] = [
  {
    id: member.profile.id,
    name: member.profile.name,
    initials: initialsOf(member.profile.name),
    has_context: true,
    last_session_on: "2026-06-03",
    adherence_pct: 50,
    injury_label: "knee",
    needs_attention: true,
  },
  // Roster-level metadata only. These carry no clinical detail, and selecting
  // one renders an empty state rather than fabricated context.
  { id: "mbr_devin", name: "Devin Okoro", initials: "DO", has_context: false, last_session_on: "2026-06-04", adherence_pct: 74, injury_label: null, needs_attention: false },
  { id: "mbr_alex", name: "Alex Mensah", initials: "AM", has_context: false, last_session_on: "2026-06-03", adherence_pct: 92, injury_label: null, needs_attention: false },
  { id: "mbr_priya", name: "Priya Shah", initials: "PS", has_context: false, last_session_on: "2026-06-01", adherence_pct: 100, injury_label: null, needs_attention: false },
]

const completedSessions = member.workout_history.filter((s) => s.completed)
const typicalMinutes =
  completedSessions.length > 0
    ? Math.round(
        completedSessions.reduce((n, s) => n + s.duration_min, 0) / completedSessions.length,
      )
    : null

const sleepAvg =
  member.biomarkers.sleep_hours_last_7_days.reduce((a, b) => a + b, 0) /
  member.biomarkers.sleep_hours_last_7_days.length

const injuryStart = member.injuries[0]?.since ?? "an earlier date"

export const mockMember: MemberContext = {
  id: member.profile.id,
  name: member.profile.name,
  initials: initialsOf(member.profile.name),
  age: member.profile.age,
  tier: member.profile.tier,
  member_since: member.profile.member_since,
  trains_at: "home",
  preferred_session_min: member.preferences.preferred_session_minutes,
  typical_session_min: typicalMinutes,
  equipment_available: member.equipment_available,
  injuries: member.injuries,
  adherence_pct: member.adherence.weekly_completion_pct.map((p) => p.pct),
  sessions_done_this_week: 1,
  sessions_planned_this_week: member.preferences.training_days_per_week,
  recent_sessions: member.workout_history
    .slice()
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((s) => ({
      date: s.date,
      title: s.title,
      completed: s.completed,
      duration_min: s.duration_min,
      rpe: s.rpe,
    })),
  goals: member.goals.map((g) => {
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
  constraints: [
    {
      kind: ConstraintKind.INJURIES,
      label: "Injuries",
      items: member.injuries.map((i) => `${i.region} · ${i.status} · ${i.severity}`),
      effect: "Excludes plyometrics. Cautions loaded knee flexion.",
      liftable: false,
    },
    {
      kind: ConstraintKind.EQUIPMENT,
      label: "Equipment",
      items: member.equipment_available,
      effect: "Drops any movement needing kit she doesn't have.",
      liftable: true,
    },
    {
      kind: ConstraintKind.DISLIKES,
      label: "Dislikes",
      items: member.preferences.dislikes,
      effect: "Down-ranks these rather than removing them outright.",
      liftable: true,
    },
    {
      kind: ConstraintKind.GOAL_TARGETS,
      label: "Goal targets",
      items: [...goalMuscles],
      effect: "Boosts movements training the muscles her goals name.",
      liftable: true,
    },
  ],
}

/** Coach ↔ Jordan. Distinct from the copilot thread by design. */
export const mockMemberMessages: MemberMessage[] = member.chat_history
  .slice()
  .sort((a, b) => a.ts.localeCompare(b.ts))
  .map((m, i) => ({
    id: `mm_${i}`,
    ts: m.ts,
    from: m.from,
    text: m.text,
    attachments: m.attachments,
  }))

/**
 * Coach ↔ copilot. Opens with the brief already answered.
 *
 * The third paragraph is derived rather than stored: joining her stated
 * session preference to her completed history surfaces a gap nothing in the
 * fixture states outright.
 */
export const mockCopilotMessages: CopilotMessage[] = [
  {
    id: "cp_brief",
    ts: "2026-06-04T07:02:00-07:00",
    from: "copilot",
    paragraphs: [
      {
        lead: "Celebrate first.",
        text: `${member.profile.name.split(" ")[0]} trained Wednesday — 28 minutes, RPE 6, and the first squat work she's called pain-free since the knee flared on 10 May.`,
      },
      {
        lead: "Then the risk.",
        // The fixture's reason strings carry no terminal punctuation.
        text: `Weekly completion has run ${member.adherence.weekly_completion_pct.map((p) => p.pct).join(", ")} across four weeks. ${member.coach_brief.churn_risk.reasons[1]}. Churn risk is ${member.coach_brief.churn_risk.level}.`,
      },
      {
        lead: "One thing worth testing.",
        text: `Her sessions average ${typicalMinutes} minutes against a stated preference of ${member.preferences.preferred_session_minutes}. Every session she's completed has been short; the one she skipped was full-body. A 30-minute Thursday might get done where a 50-minute one doesn't.`,
      },
    ],
    cites: [
      {
        message_id: "mm_1",
        from: member.profile.name.split(" ")[0],
        when: "30 May",
        text: "Skipped Thursday, work blew up and I was wiped. Sorry!",
      },
    ],
  },
]

const sleepNights = member.biomarkers.sleep_hours_last_7_days
const weeklyPct = member.adherence.weekly_completion_pct

/**
 * Canned answers for the quick prompts, drawn from the fixture.
 *
 * Every figure below traces to `member-context.json`. When the API lands this
 * is replaced by a real retrieval; the message shape does not change.
 *
 * @param prompt The coach's question, matched loosely on keywords.
 * @returns A copilot reply, or a graceful "I don't have that" for anything
 *   outside the sample member's data.
 */
export function mockAnswer(prompt: string, id: string): CopilotMessage {
  const q = prompt.toLowerCase()
  const base = { id, ts: new Date().toISOString(), from: "copilot" as const }

  if (q.includes("sleep")) {
    const nightsUnder = sleepNights.filter((h) => h < SLEEP_TARGET_HOURS).length
    return {
      ...base,
      paragraphs: [
        {
          text: `She averaged ${oneDp(sleepAvg)} hours over the last seven nights — ${nightsUnder} of ${sleepNights.length} came in under her 7-hour target, with a low of ${Math.min(...sleepNights)}.`,
        },
        {
          text: `Nothing in the graph connects sleep to movement selection, so this hasn't changed her plan. It is worth raising with her directly.`,
        },
      ],
    }
  }

  if (q.includes("adherence") || q.includes("trend")) {
    return {
      ...base,
      paragraphs: [
        {
          text: `Declining for three straight weeks: ${weeklyPct.map((p) => `${p.pct}%`).join(" → ")}. That is a 50-point drop from where she started.`,
        },
        {
          text: `The drop begins the week of ${weeklyPct[2].week_of}, which is two weeks after the knee flared on ${injuryStart}.`,
        },
      ],
    }
  }

  if (q.includes("changed") || q.includes("last week")) {
    return {
      ...base,
      paragraphs: [
        {
          text: `She completed Wednesday's lower-body session at RPE 6 and called the squat work pain-free — the first time since the flare-up. Adherence still fell to ${weeklyPct.at(-1)?.pct}% because she trained once against a plan of ${member.preferences.training_days_per_week}.`,
        },
      ],
    }
  }

  if (q.includes("brief")) {
    return mockCopilotMessages[0]
  }

  return {
    ...base,
    paragraphs: [
      {
        text: `I don't have that for ${member.profile.name.split(" ")[0]}. Her record covers goals, preferences, equipment, injuries, workout history, adherence, biomarkers, labs and your message thread.`,
      },
    ],
  }
}

/** Build a muscle tag list, flagging the ones her goals name. */
function taggedMuscles(e: RawExercise): MuscleTag[] {
  return e.muscle_groups.map((name) => ({ name, is_goal_target: goalMuscles.has(name) }))
}

/**
 * Estimate how long a prescription takes.
 *
 * `estimated_rep_duration` is minutes per rep, which checks out against her
 * real sessions: 3 × 10 at 0.3 is nine minutes of work plus rest, and her
 * completed sessions ran 26–31 minutes for three movements.
 *
 * @returns Whole minutes, floored at 1 so nothing reads as free.
 */
function estimateMinutes(
  e: RawExercise,
  sets: number,
  reps: number | null,
  durationSec: number | null,
  restSec: number,
): number {
  const work = reps !== null ? sets * reps * e.estimated_rep_duration : (sets * (durationSec ?? 0)) / 60
  const rest = (Math.max(sets - 1, 0) * restSec) / 60
  return Math.max(1, Math.round(work + rest))
}

interface Prescription {
  name: string
  block: PlanBlock
  sets: number
  reps: number | null
  durationSec?: number | null
  restSec?: number
  perSide?: boolean
  verdict?: Verdict
  note?: string | null
}

const PRESCRIPTIONS: Prescription[] = [
  { name: "World's Greatest Stretch", block: PlanBlock.WARMUP, sets: 2, reps: 8 },
  { name: "Walking Toe Touches", block: PlanBlock.WARMUP, sets: 1, reps: 10 },
  {
    name: "Dumbbell Goblet Split Squat",
    block: PlanBlock.MAIN,
    sets: 3,
    reps: 10,
    restSec: 60,
    perSide: true,
    verdict: Verdict.CAUTION,
    note: "Loads the knee — kept, but placed last in the block.",
  },
  {
    name: "Alternating Dumbbell Racked Crossback Lunge",
    block: PlanBlock.MAIN,
    sets: 3,
    reps: 8,
    restSec: 60,
    note: "Stands in for the barbell lunge — same movement pattern.",
  },
  {
    name: "One-Kettlebell Hamstring Walkout",
    block: PlanBlock.MAIN,
    sets: 3,
    reps: 8,
    restSec: 60,
    note: "No knee flexion under load.",
  },
  { name: "Cow Pose", block: PlanBlock.COOLDOWN, sets: 2, reps: null, durationSec: 60 },
]

/** Placeholder plan so the sheet has something real to render pre-backend. */
export function mockPlan(req: PlanRequest): WorkoutPlan {
  const exercisesOut: PlanExercise[] = PRESCRIPTIONS.map((p) => {
    const raw = byName.get(p.name)
    if (!raw) throw new Error(`Prescription names a missing exercise: ${p.name}`)
    const restSec = p.restSec ?? 0
    return {
      id: raw.id,
      name: raw.name,
      block: p.block,
      sets: p.sets,
      reps: p.reps,
      duration_sec: p.durationSec ?? null,
      rest_sec: restSec || null,
      per_side: p.perSide ?? false,
      minutes: estimateMinutes(raw, p.sets, p.reps, p.durationSec ?? null, restSec),
      muscles: taggedMuscles(raw),
      equipment: raw.equipment_required.length > 0 ? raw.equipment_required : ["Bodyweight"],
      verdict: p.verdict ?? Verdict.CLEARED,
      note: p.note ?? null,
    }
  })

  const estimated = exercisesOut.reduce((n, e) => n + e.minutes, 0)
  const dropped = (name: string, cause: FilterCause, detail: string) => ({
    id: byName.get(name)?.id ?? name,
    name,
    cause,
    detail,
  })

  return {
    run_id: "run_mock_4f2a",
    parent_run_id: null,
    title: "Lower body",
    day_label: "Thursday",
    requested_minutes: req.duration_min,
    estimated_minutes: estimated,
    exercises: exercisesOut,
    trace: {
      run_id: "run_mock_4f2a",
      generated_at: "2026-06-04T07:14:00-07:00",
      catalogue_total: exercises.length,
      eligible: 10,
      filtered: [
        dropped("Barbell Racked Forward Lunge", FilterCause.EQUIPMENT, "barbell · plate · rack"),
        dropped("Barbell Step Up to Knee-Drive", FilterCause.EQUIPMENT, "barbell · box · plate"),
        dropped("Vertical Jump to Broad Jump", FilterCause.INJURY, "plyometric"),
        dropped("Static Jump", FilterCause.INJURY, "plyometric"),
        dropped("Jump Rope - Single-Leg", FilterCause.INJURY, "plyometric"),
      ],
      unresolved: [],
    },
  }
}
