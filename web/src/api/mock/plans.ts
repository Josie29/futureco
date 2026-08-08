import { catalog, goalMuscles } from "@/api/fixtures"
import { byName, screen } from "@/api/mock/catalogue"
import { TODAY, formatWeekday } from "@/lib/dates"
import {
  ConceptIntent,
  ConceptLabel,
  FilterCause,
  PlanBlock,
  ResolutionPass,
  Verdict,
  type FilteredExercise,
  type GraphPath,
  type PlanExercise,
  type PlanRequest,
  type ResolvedConcept,
  type UnresolvedPhrase,
  type WorkoutPlan,
} from "@/types"

/**
 * MOCK — throwaway. Replaced wholesale by the real API.
 *
 * Authored plans, one per scenario, matched on a keyword in the prompt. There
 * is no resolver and no planner here: concept resolution, safety traversal,
 * ranking and dosing all belong to the backend, and a second implementation in
 * TypeScript would only be a thing to keep in sync and then delete.
 *
 * What this does buy: every state the UI can render is reachable from a prompt
 * a reviewer can actually type, with counts that reconcile against the
 * builder's eligibility panel. See `docs/mock-notes.md`.
 */

interface AuthoredExercise {
  name: string
  block: PlanBlock
  sets: number
  reps?: number
  durationSec?: number
  restSec?: number
  verdict?: Verdict
  note?: string
  why: GraphPath[]
}

interface Scenario {
  /** Matched against the prompt, first hit wins. `null` is the fallback. */
  match: RegExp | null
  title: string
  resolved: ResolvedConcept[]
  unresolved: UnresolvedPhrase[]
  /** Removed by *this request*, on top of the standing constraints. */
  extraFiltered: { name: string; cause: FilterCause; detail: string; path: string }[]
  exercises: AuthoredExercise[]
}

const concept = (
  phrase: string,
  name: string,
  label: ConceptLabel,
  intent: ConceptIntent,
  pass: ResolutionPass,
  confidence: number,
  side: string | null = null,
): ResolvedConcept => ({
  phrase,
  label,
  concept_id: `${label}:${name}`,
  concept_name: name,
  pass,
  confidence,
  intent,
  side,
})

const WARMUP: AuthoredExercise[] = [
  {
    name: "World's Greatest Stretch",
    block: PlanBlock.WARMUP,
    sets: 1,
    reps: 10,
    why: [
      {
        path: `Exercise -is_a-> MovementPattern(mobility - dynamic)`,
        says: "Opens the session without loading the knee.",
      },
    ],
  },
]

const COOLDOWN: AuthoredExercise[] = [
  {
    name: "Cow Pose",
    block: PlanBlock.COOLDOWN,
    sets: 2,
    durationSec: 60,
    why: [
      {
        path: `Exercise -is_a-> MovementPattern(mobility - static)`,
        says: "Closes the session. Needs only a mat, which she has.",
      },
    ],
  },
]

const SCENARIOS: Scenario[] = [
  {
    // ASSESSMENT.md:29 — the injury case.
    match: /knee|bothering|sore|aggravat|pain/i,
    title: "Lower body",
    resolved: [
      concept("lower body", "lower body", ConceptLabel.ANATOMY, ConceptIntent.FOCUS, ResolutionPass.EXACT, 1),
      concept("her left knee", "knee", ConceptLabel.ANATOMY, ConceptIntent.PROTECT, ResolutionPass.FUZZY, 0.94, "left"),
    ],
    unresolved: [],
    extraFiltered: [
      {
        name: "Dumbbell Goblet Split Squat",
        cause: FilterCause.INJURY,
        detail: "loads the knee",
        path: "Exercise -stresses-> AnatomicalStructure(knee) -part_of*-> knee [side: left]",
      },
      {
        name: "RNT Split Squat",
        cause: FilterCause.INJURY,
        detail: "loads the knee",
        path: "Exercise -stresses-> AnatomicalStructure(knee) -part_of*-> knee [side: left]",
      },
      {
        name: "Alternating Dumbbell Racked Crossback Lunge",
        cause: FilterCause.INJURY,
        detail: "loads the knee",
        path: "Exercise -stresses-> AnatomicalStructure(knee) -part_of*-> knee [side: left]",
      },
    ],
    exercises: [
      ...WARMUP,
      {
        name: "One-Kettlebell Hamstring Walkout",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 8,
        restSec: 60,
        note: "No bending the knee under load. She's said she dislikes this one — swap it if you can.",
        why: [
          {
            path: `Exercise -targets-> Muscle(hamstrings) <-targets- Goal("Build lower-body strength")`,
            says: "Trains hamstrings without asking the knee to bend under load.",
          },
        ],
      },
      {
        name: "High Plank Bird Dog",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 10,
        restSec: 45,
        why: [
          {
            path: `Exercise -stresses-> ∅ knee`,
            says: "Doesn't load the knee at all.",
          },
        ],
      },
      ...COOLDOWN,
    ],
  },
  {
    // ASSESSMENT.md:28 — an exclusion this catalogue cannot honour.
    match: /exclude|without|no deadlift|deadlift/i,
    title: "Lower body",
    resolved: [
      concept("glutes", "glutes", ConceptLabel.MUSCLE, ConceptIntent.FOCUS, ResolutionPass.EXACT, 1),
    ],
    unresolved: [
      {
        phrase: "deadlifts",
        best_guess: "deltoids",
        confidence: 0.354,
        threshold: 0.68,
        fallback:
          "No movement in the library goes by that name, so nothing was left out for it. Her injury and equipment rules still applied.",
      },
    ],
    extraFiltered: [],
    exercises: [
      ...WARMUP,
      {
        name: "Alternating Dumbbell Racked Crossback Lunge",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 10,
        restSec: 60,
        why: [
          {
            path: `Exercise -targets-> Muscle(glutes) <-targets- Goal("Build lower-body strength")`,
            says: "Trains glutes, which her lower-body strength goal is about.",
          },
          {
            path: `Exercise -is_a-> MovementPattern(lower push - lunge) <-is_a- Exercise(Barbell Racked Forward Lunge) ✕ equipment`,
            says: "Stands in for the barbell lunge, which she hasn't got the equipment for.",
          },
        ],
      },
      {
        name: "Dumbbell Goblet Split Squat",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 10,
        restSec: 60,
        verdict: Verdict.CAUTION,
        note: "Loads the knee, so it comes last once she's warm.",
        why: [
          {
            path: `Condition(patellofemoral pain syndrome) -cautions-> MovementPattern(lower push - split squat)`,
            says: "Flagged rather than dropped — she's cleared for low-impact loading, so it stays in with a note.",
          },
        ],
      },
      ...COOLDOWN,
    ],
  },
  {
    // ASSESSMENT.md:31 — the limited-equipment case.
    match: /barbell|dumbbell|kettlebell|equipment/i,
    title: "Upper body",
    resolved: [
      concept("upper body", "upper body", ConceptLabel.ANATOMY, ConceptIntent.FOCUS, ResolutionPass.EXACT, 1),
      concept("no barbell", "Barbell", ConceptLabel.EQUIPMENT, ConceptIntent.EXCLUDE, ResolutionPass.ALIAS, 1),
      concept("dumbbells", "Dumbbell", ConceptLabel.EQUIPMENT, ConceptIntent.FOCUS, ResolutionPass.ALIAS, 1),
    ],
    unresolved: [],
    extraFiltered: [],
    exercises: [
      ...WARMUP,
      {
        name: "Alternating Dumbbell Overhead Press",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 10,
        restSec: 60,
        why: [
          {
            path: `Exercise -requires-> Equipment(Dumbbell) ∈ Member -has-> Equipment`,
            says: "Needs only the dumbbells she has.",
          },
        ],
      },
      {
        name: "Dumbbell Neutral-Grip Bench Press",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 10,
        restSec: 60,
        note: "Stands in for the barbell decline press — same movement pattern.",
        why: [
          {
            path: `Exercise -is_a-> MovementPattern(upper push - horizontal) <-is_a- Exercise(Barbell Decline Bench Press) ✕ equipment`,
            says: "The closest match to the barbell press with what she has.",
          },
        ],
      },
      ...COOLDOWN,
    ],
  },
  {
    match: null,
    title: "Full body",
    resolved: [],
    unresolved: [],
    extraFiltered: [],
    exercises: [
      ...WARMUP,
      {
        name: "Alternating Dumbbell Overhead Press",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 10,
        restSec: 60,
        why: [
          {
            path: `Exercise -requires-> Equipment(Dumbbell) ∈ Member -has-> Equipment`,
            says: "Cleared every standing constraint.",
          },
        ],
      },
      {
        name: "Alternating Low Plank To Low Side Plank",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 12,
        restSec: 45,
        why: [
          {
            path: `Exercise -requires-> Equipment(Yoga Mat) ∈ Member -has-> Equipment`,
            says: "Cleared every standing constraint.",
          },
        ],
      },
      ...COOLDOWN,
    ],
  },
]

/**
 * Per-rep working minutes, clamped.
 *
 * `estimated_rep_duration` is unreliable at the top of its range — `Jump Rope
 * - Single-Leg` carries 1.9, which is 114 seconds for one skip. Clamped to a
 * band a coach would recognise so the estimates aren't absurd. This is a
 * finding about the dataset, not a modelling decision; see `docs/mock-notes.md`.
 */
const clampRepMinutes = (value: number) => Math.min(0.35, Math.max(0.05, value))

function minutesFor(exercise: AuthoredExercise, perSide: boolean): number {
  const raw = byName.get(exercise.name)
  const sides = perSide ? 2 : 1
  const work =
    exercise.reps !== undefined
      ? exercise.sets * exercise.reps * clampRepMinutes(raw?.estimated_rep_duration ?? 0.3) * sides
      : (exercise.sets * (exercise.durationSec ?? 0) * sides) / 60
  const rest = (Math.max(exercise.sets * sides - 1, 0) * (exercise.restSec ?? 0)) / 60
  return Math.max(1, Math.round(work + rest))
}

/** FNV-1a, so the same request yields the same run id. */
function hash(input: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, "0")
}

export interface BuildOptions extends PlanRequest {
  parentRunId?: string | null
}

/**
 * Return the authored plan for a prompt.
 *
 * @param options Prompt, window, switched-off constraint items, optional parent run.
 * @returns The plan and a trace whose counts reconcile with the eligibility panel.
 */
export function buildPlan(options: BuildOptions): WorkoutPlan {
  const { prompt, duration_min: requested, disabled, parentRunId = null } = options

  const scenario =
    SCENARIOS.find((s) => s.match?.test(prompt)) ?? SCENARIOS[SCENARIOS.length - 1]

  const { survivors, filtered: standing } = screen(disabled)

  const extra: FilteredExercise[] = scenario.extraFiltered.flatMap((row) => {
    const raw = byName.get(row.name)
    // Only report it as removed if it survived the standing constraints;
    // otherwise the same movement would be counted twice.
    if (!raw || !survivors.some((s) => s.id === raw.id)) return []
    return [{ id: raw.id, name: row.name, cause: row.cause, detail: row.detail, path: row.path }]
  })

  const exercises: PlanExercise[] = scenario.exercises.flatMap((authored) => {
    const raw = byName.get(authored.name)
    if (!raw) return []
    const perSide = raw.is_bilateral

    return [
      {
        id: raw.id,
        name: raw.name,
        block: authored.block,
        sets: authored.sets,
        reps: authored.reps ?? null,
        duration_sec: authored.durationSec ?? null,
        rest_sec: authored.restSec ?? null,
        per_side: perSide,
        minutes: minutesFor(authored, perSide),
        muscles: raw.muscle_groups.map((name) => ({
          name,
          is_goal_target: goalMuscles.has(name),
        })),
        equipment: raw.equipment_required.length > 0 ? raw.equipment_required : ["Bodyweight"],
        verdict: authored.verdict ?? Verdict.CLEARED,
        note: authored.note ?? null,
        why: authored.why,
      },
    ]
  })

  const estimated = exercises.reduce((n, e) => n + e.minutes, 0)
  const eligible = survivors.length
  const afterRequest = eligible - extra.length
  const runId = `run_${hash(`${prompt}|${requested}|${[...disabled].sort().join(",")}|${parentRunId ?? ""}`)}`

  return {
    run_id: runId,
    parent_run_id: parentRunId,
    prompt,
    title: scenario.title,
    day_label: formatWeekday(TODAY),
    requested_minutes: requested,
    estimated_minutes: estimated,
    exercises,
    trace: {
      run_id: runId,
      generated_at: `${TODAY}T07:14:00-07:00`,
      catalogue_total: catalog.length,
      eligible,
      prescribed: exercises.length,
      stages: [
        {
          label: "Resolved the request",
          remaining: catalog.length,
          detail: `${scenario.resolved.length} concepts matched, ${scenario.unresolved.length} declined`,
        },
        {
          label: "Applied her constraints",
          remaining: eligible,
          detail: `${standing.length} removed by injury and equipment`,
        },
        {
          label: "Narrowed to the request",
          remaining: afterRequest,
          detail: extra.length > 0 ? `${extra.length} removed by this request` : "Nothing further removed",
        },
        {
          label: "Assembled the session",
          remaining: exercises.length,
          detail: `${estimated} of ${requested} min`,
        },
      ],
      resolved: scenario.resolved,
      unresolved: scenario.unresolved,
      filtered: [...standing, ...extra],
    },
  }
}
