import memberJson from "@data/member-context.json"
import exercisesJson from "@data/exercises.json"
import {
  ChartKind,
  FilterCause,
  LiftableRule,
  PlanBlock,
  Verdict,
  type ChatMessage,
  type Coach,
  type Eligibility,
  type MemberContext,
  type PlanRequest,
  type RosterEntry,
  type WorkoutPlan,
} from "@/types"

/**
 * Stand-in for the API while the backend is being built. Everything here is
 * derived from the assessment's own fixtures rather than invented, so the
 * numbers on screen match what the real traversal will produce.
 *
 * Delete this module once `/api` is live; `client.ts` is the only importer.
 */

interface RawExercise {
  id: string
  name: string
  muscle_groups: string[]
  joints_loaded: string[]
  movement_patterns: string[]
  equipment_required: string[]
  side: string | null
}

const exercises = exercisesJson as RawExercise[]
const member = memberJson as unknown as {
  profile: {
    id: string
    name: string
    age: number
    tier: string
    member_since: string
  }
  goals: MemberContext["goals"]
  preferences: MemberContext["preferences"]
  equipment_available: string[]
  injuries: MemberContext["injuries"]
  workout_history: {
    date: string
    title: string
    planned: boolean
    completed: boolean
    duration_min: number
    rpe: number | null
  }[]
  adherence: MemberContext["adherence"]
  biomarkers: { sleep_hours_last_7_days: number[] }
  chat_history: {
    ts: string
    from: "member" | "coach"
    text: string
    attachments?: { type: "image"; caption: string }[]
  }[]
  coach_brief: {
    morning_tasks: { type: string; text: string }[]
    churn_risk: { level: string; reasons: string[] }
  }
}

const PLYOMETRIC_PATTERN = "cardio - plyometric"

/** Equipment the member owns, as a set for subset checks. */
const owned = new Set(member.equipment_available)

const hasEquipment = (e: RawExercise): boolean =>
  e.equipment_required.every((item) => owned.has(item))

const isPlyometric = (e: RawExercise): boolean =>
  e.movement_patterns.includes(PLYOMETRIC_PATTERN)

/**
 * The standing eligible pool: what this member could do today given the rules
 * currently applied, before any request narrows it further.
 *
 * Mirrors the Cypher the real endpoint will run. With no rules lifted this
 * returns 18 of 50 — 29 dropped on equipment, 3 on the knee contraindication.
 *
 * @param lifted Rules the coach switched off for this run. Injury can never
 *   appear here; it is applied unconditionally.
 * @returns Counts of what survived and what each cause removed.
 */
export function computeEligibility(lifted: LiftableRule[] = []): Eligibility {
  const applyEquipment = !lifted.includes(LiftableRule.EQUIPMENT)

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

export const mockCoaches: Coach[] = [
  { id: "coach_01HXSAM", name: "Sam Ortiz" },
]

export const mockRoster: RosterEntry[] = [
  {
    id: member.profile.id,
    name: member.profile.name,
    has_context: true,
    last_session_on: "2026-06-03",
    adherence_pct: 50,
    injury_label: "left knee",
    churn_risk: "elevated",
  },
  // Roster-level metadata only. These carry no clinical detail, and selecting
  // one renders an empty state rather than fabricated context.
  {
    id: "mbr_synthetic_alex",
    name: "Alex Mensah",
    has_context: false,
    last_session_on: "2026-06-03",
    adherence_pct: 92,
    injury_label: null,
    churn_risk: "low",
  },
  {
    id: "mbr_synthetic_priya",
    name: "Priya Shah",
    has_context: false,
    last_session_on: "2026-06-01",
    adherence_pct: 100,
    injury_label: null,
    churn_risk: "low",
  },
  {
    id: "mbr_synthetic_devin",
    name: "Devin Okoro",
    has_context: false,
    last_session_on: "2026-06-04",
    adherence_pct: 74,
    injury_label: null,
    churn_risk: "low",
  },
]

export const mockMember: MemberContext = {
  id: member.profile.id,
  name: member.profile.name,
  age: member.profile.age,
  tier: member.profile.tier,
  member_since: member.profile.member_since,
  goals: member.goals,
  preferences: member.preferences,
  equipment_available: member.equipment_available,
  injuries: member.injuries,
  recent_sessions: member.workout_history
    .slice()
    .sort((a, b) => a.date.localeCompare(b.date)),
  adherence: member.adherence,
}

/**
 * Chat seeded from the fixture. History runs oldest to newest, and the brief
 * lands last because it is the newest message — the thread opens with it
 * already answered, which is what delivers "a coach logs in to a member and
 * works their brief" without a separate dashboard panel.
 */
export const mockMessages: ChatMessage[] = [
  ...member.chat_history
    .slice()
    .sort((a, b) => a.ts.localeCompare(b.ts))
    .map((m, i) => ({
      id: `msg_${i}`,
      ts: m.ts,
      from: m.from,
      text: m.text,
      attachments: m.attachments,
    })),
  {
    id: "msg_brief",
    ts: "2026-06-04T07:02:00-07:00",
    from: "copilot",
    // The two morning tasks verbatim. The second already names the churn
    // figure, so restating the risk reasons here would only repeat it.
    text: `Two things this morning. ${member.coach_brief.morning_tasks
      .map((t) => t.text)
      .join(" ")}`,
  },
]

export const mockAdherenceChart = {
  kind: ChartKind.ADHERENCE,
  title: "Weekly completion",
  unit: "%",
  series: member.adherence.weekly_completion_pct.map((p) => ({
    label: p.week_of.slice(5),
    value: p.pct,
  })),
}

/** Placeholder plan so the sheet has something real to render pre-backend. */
export function mockPlan(req: PlanRequest): WorkoutPlan {
  const pick = (name: string) => exercises.find((e) => e.name === name)!
  const lunge = pick("Barbell Racked Forward Lunge")
  const sub = pick("Alternating Dumbbell Racked Crossback Lunge")

  return {
    run_id: "run_mock_4f2a",
    parent_run_id: null,
    title: "Lower body",
    requested_minutes: req.duration_min,
    estimated_minutes: 47,
    exercises: [
      {
        id: pick("World's Greatest Stretch").id,
        name: "World's Greatest Stretch",
        block: PlanBlock.WARMUP,
        sets: 2,
        reps: 8,
        duration_sec: null,
        rest_sec: null,
        per_side: false,
        verdict: Verdict.CLEARED,
        trace: "mobility - dynamic · mobilises knee without load",
        substituted_for: null,
      },
      {
        id: pick("Dumbbell Goblet Split Squat").id,
        name: "Dumbbell Goblet Split Squat",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 10,
        duration_sec: null,
        rest_sec: 60,
        per_side: true,
        verdict: Verdict.CAUTION,
        trace: "stresses knee ← part_of ← patellofemoral · mild · recovering",
        substituted_for: null,
      },
      {
        id: sub.id,
        name: sub.name,
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 8,
        duration_sec: null,
        rest_sec: 60,
        per_side: false,
        verdict: Verdict.CLEARED,
        trace: "is_a → lower push - lunge ← is_a · same pattern, dumbbell only",
        substituted_for: {
          id: lunge.id,
          name: lunge.name,
          via_pattern: "lower push - lunge",
        },
      },
      {
        id: pick("One-Kettlebell Hamstring Walkout").id,
        name: "One-Kettlebell Hamstring Walkout",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 8,
        duration_sec: null,
        rest_sec: 60,
        per_side: false,
        verdict: Verdict.CLEARED,
        trace: "targets hamstrings ← goal_strength",
        substituted_for: null,
      },
      {
        id: pick("Cow Pose").id,
        name: "Cow Pose",
        block: PlanBlock.COOLDOWN,
        sets: null,
        reps: null,
        duration_sec: 60,
        rest_sec: null,
        per_side: false,
        verdict: Verdict.CLEARED,
        trace: "mobility - static · unloaded",
        substituted_for: null,
      },
    ],
    trace: {
      run_id: "run_mock_4f2a",
      generated_at: "2026-06-04T07:14:00-07:00",
      catalogue_total: exercises.length,
      eligible: 10,
      filtered: [
        {
          id: lunge.id,
          name: lunge.name,
          cause: FilterCause.EQUIPMENT,
          trace: "requires Barbell, Plate, Rack — Jordan has none",
        },
        {
          id: pick("Vertical Jump to Broad Jump").id,
          name: "Vertical Jump to Broad Jump",
          cause: FilterCause.INJURY,
          trace: "is_a → cardio - plyometric ← contraindicates ← left knee",
        },
        {
          id: pick("Static Jump").id,
          name: "Static Jump",
          cause: FilterCause.INJURY,
          trace: "is_a → cardio - plyometric ← contraindicates ← left knee",
        },
      ],
      unresolved: [],
    },
  }
}
