import { catalog, goalMuscles } from "@/api/fixtures"
import { byName, screen } from "@/api/mock/catalogue"
import { TODAY, formatWeekday } from "@/lib/dates"
import {
  ConceptIntent,
  ConceptLabel,
  FilterCause,
  NodeLabel,
  PlanBlock,
  ReasonKind,
  RelType,
  ResolutionPass,
  Verdict,
  type EvidencePath,
  type FilteredExercise,
  type PathHop,
  type PlanExercise,
  type PlanRequest,
  type Reason,
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
 * The evidence below is the exception, and is authored to mirror
 * `backend/src/safety/evidence.py` hop for hop — same `SignalKind` values, same
 * forward-only `Hop`, same `(this)` convention for a reversed final edge. It is
 * still fake, but it is fake in the shape the real thing emits, so the render
 * is exercised against something the plan endpoint can actually produce.
 *
 * What this buys: every state the UI can render is reachable from a prompt a
 * reviewer can type, with counts that reconcile against the builder's
 * eligibility panel. See `docs/mock-notes.md`.
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
  why: Reason[]
}

interface Scenario {
  /** Matched against the prompt, first hit wins. `null` is the fallback. */
  match: RegExp | null
  title: string
  resolved: ResolvedConcept[]
  unresolved: UnresolvedPhrase[]
  /** Removed by *this request*, on top of the standing constraints. */
  extraFiltered: { name: string; cause: FilterCause; detail: string; path: EvidencePath }[]
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

/**
 * How a hop names the exercise a reason is about.
 *
 * `safety/filter.py` uses this literal when the last edge runs backwards —
 * `_anatomy_signals` walks down to a joint, then names whatever stresses it.
 * Same token here so one path grammar covers the whole trace.
 */
const THIS = "(this)"

/** Her recorded injury, and the condition the contraindication rules hang off. */
const INJURY = "inj_knee_left"
const CONDITION = "Patellofemoral stress syndrome"

const hop = (rel: RelType, toLabel: NodeLabel, toName: string): PathHop => ({
  rel,
  to_label: toLabel,
  to_name: toName,
})

const path = (entry: string, ...hops: PathHop[]): EvidencePath => ({ entry, hops })

const reason = (
  kind: ReasonKind,
  detail: string,
  evidence: EvidencePath,
  annotation: string | null = null,
): Reason => ({ kind, detail, path: evidence, annotation })

/** The anatomy walk: down the hierarchy to the joint, back out to what loads it. */
const kneeWalk = (): EvidencePath =>
  path(
    "knee",
    hop(RelType.PART_OF, NodeLabel.ANATOMICAL_STRUCTURE, "knee"),
    hop(RelType.STRESSES, NodeLabel.EXERCISE, THIS),
  )

/**
 * The safety claim, identical for every movement the filter cleared.
 *
 * Written once because in the real system it is derived once, from one walk:
 * collect the condition's contraindicated patterns, and any exercise no `is_a`
 * edge connects to one of them is clear. The absence *is* the finding, which is
 * why the path names what was checked rather than what was found.
 */
const cleared = (): Reason =>
  reason(
    ReasonKind.CLEARED,
    "cleared against her left knee — none of the patterns that condition rules out reach it",
    path(INJURY, hop(RelType.DIAGNOSED_AS, NodeLabel.CONDITION, CONDITION)),
  )

/** Equipment names are singular count nouns, so they need an article. */
const article = (noun: string) => (/^[aeiou]/i.test(noun) ? "an" : "a")

/** The positive mirror of `MISSING_EQUIPMENT` — she owns everything it names. */
const equipmentFit = (exercise: string, item: string): Reason => {
  const noun = item.toLowerCase()
  return reason(
    ReasonKind.EQUIPMENT_FIT,
    `needs only ${article(noun)} ${noun}, which she has`,
    path(exercise, hop(RelType.REQUIRES, NodeLabel.EQUIPMENT, item)),
  )
}

/** Why the movement sits in the block it does. */
const patternRole = (exercise: string, pattern: string, detail: string): Reason =>
  reason(
    ReasonKind.PATTERN_ROLE,
    detail,
    path(exercise, hop(RelType.IS_A, NodeLabel.MOVEMENT_PATTERN, pattern)),
  )

/** `Goal -targets-> Muscle <-targets- Exercise`, the second leg folded into `(this)`. */
const goalService = (goal: string, muscle: string, detail: string): Reason =>
  reason(
    ReasonKind.GOAL_SERVICE,
    detail,
    path(
      goal,
      hop(RelType.TARGETS, NodeLabel.MUSCLE, muscle),
      hop(RelType.TARGETS, NodeLabel.EXERCISE, THIS),
    ),
  )

/**
 * Stands in for a movement that was dropped (ASSESSMENT.md:31).
 *
 * The path names the *replaced* movement as its entry, which is what makes
 * "find equivalent alternatives" auditable rather than a claim in a sentence.
 */
const substitution = (replaced: string, pattern: string, detail: string): Reason =>
  reason(
    ReasonKind.SUBSTITUTION,
    detail,
    path(
      replaced,
      hop(RelType.IS_A, NodeLabel.MOVEMENT_PATTERN, pattern),
      hop(RelType.IS_A, NodeLabel.EXERCISE, THIS),
    ),
  )

const WARMUP: AuthoredExercise[] = [
  {
    name: "World's Greatest Stretch",
    block: PlanBlock.WARMUP,
    sets: 1,
    reps: 10,
    why: [
      cleared(),
      patternRole(
        "World's Greatest Stretch",
        "mobility - dynamic",
        "opens the session — dynamic mobility, which is what a warm-up block is built from",
      ),
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
      cleared(),
      patternRole(
        "Cow Pose",
        "mobility - static",
        "closes the session — static mobility, held rather than repeated",
      ),
      equipmentFit("Cow Pose", "Yoga Mat"),
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
      "Dumbbell Goblet Split Squat",
      "RNT Split Squat",
      "Alternating Dumbbell Racked Crossback Lunge",
    ].map((name) => ({
      name,
      cause: FilterCause.INJURY,
      detail: "loads the knee",
      path: kneeWalk(),
    })),
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
          cleared(),
          goalService(
            "Build lower-body strength",
            "hamstrings",
            'trains hamstrings, which her top-priority goal "Build lower-body strength" targets',
          ),
          equipmentFit("One-Kettlebell Hamstring Walkout", "Kettlebell"),
        ],
      },
      {
        name: "High Plank Bird Dog",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 10,
        restSec: 45,
        why: [
          cleared(),
          // Reaches the knee without loading it, so the structure signal fires,
          // penalises, and is annotated — the one place `affects` surfaces.
          reason(
            ReasonKind.FLAGGED_STRUCTURE,
            "touches the knee but doesn't load it, so it stays in with the penalty noted",
            kneeWalk(),
            "knee is the site of inj_knee_left (left, recovering)",
          ),
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
          cleared(),
          goalService(
            "Build lower-body strength",
            "glutes",
            "trains glutes, which her lower-body strength goal is about",
          ),
          reason(
            ReasonKind.FOCUS_MATCH,
            'matches "glutes" from your request',
            path(
              "Alternating Dumbbell Racked Crossback Lunge",
              hop(RelType.TARGETS, NodeLabel.MUSCLE, "glutes"),
            ),
          ),
          substitution(
            "Barbell Racked Forward Lunge",
            "lower push - lunge",
            "stands in for the barbell racked lunge, which needs a barbell she hasn't got",
          ),
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
          reason(
            ReasonKind.CAUTION,
            "the condition cautions this pattern rather than ruling it out, so it stays in and comes last",
            path(
              INJURY,
              hop(RelType.DIAGNOSED_AS, NodeLabel.CONDITION, CONDITION),
              hop(RelType.CAUTIONS, NodeLabel.MOVEMENT_PATTERN, "lower push - split squat"),
            ),
            "knee is the site of inj_knee_left (left, recovering)",
          ),
          goalService(
            "Build lower-body strength",
            "quads",
            "trains quads, which her lower-body strength goal targets — the reason it earns a caution rather than a drop",
          ),
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
          cleared(),
          equipmentFit("Alternating Dumbbell Overhead Press", "Dumbbell"),
          reason(
            ReasonKind.FOCUS_MATCH,
            'matches "upper body" from your request',
            path(
              "Alternating Dumbbell Overhead Press",
              hop(RelType.IS_A, NodeLabel.MOVEMENT_PATTERN, "upper push - vertical"),
            ),
          ),
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
          cleared(),
          substitution(
            "Barbell Decline Bench Press",
            "upper push - horizontal",
            "the closest match to the barbell decline press with what she has",
          ),
          equipmentFit("Dumbbell Neutral-Grip Bench Press", "Dumbbell"),
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
        // The fallback session: nothing in the prompt narrowed anything, so
        // these carry only the standing reasons. Which is the point — `why` is
        // never empty even when the coach asked for nothing in particular.
        why: [cleared(), equipmentFit("Alternating Dumbbell Overhead Press", "Dumbbell")],
      },
      {
        name: "Alternating Low Plank To Low Side Plank",
        block: PlanBlock.MAIN,
        sets: 3,
        reps: 12,
        restSec: 45,
        why: [cleared(), equipmentFit("Alternating Low Plank To Low Side Plank", "Yoga Mat")],
      },
      ...COOLDOWN,
    ],
  },
]

const DEFAULT_REP_SECONDS = 3

/**
 * Per-rep working minutes.
 *
 * The catalogue used to hold a rate rather than a duration, which put `Jump
 * Rope - Single-Leg` at 114 seconds a skip and had the mock clamp values into a
 * believable band. The field is now `estimated_rep_seconds` and every row lands
 * on a real cadence — 0.53 s for jump rope, 3.33 for a bench press — so the
 * clamp is gone rather than silently capping honest numbers.
 *
 * `0` marks the field inapplicable, so it falls back rather than pricing the
 * movement at nothing.
 */
function repMinutes(seconds: number | undefined): number {
  return (seconds && seconds > 0 ? seconds : DEFAULT_REP_SECONDS) / 60
}

function minutesFor(exercise: AuthoredExercise, perSide: boolean): number {
  const raw = byName.get(exercise.name)
  const sides = perSide ? 2 : 1
  const work =
    exercise.reps !== undefined
      ? exercise.sets * exercise.reps * repMinutes(raw?.estimated_rep_seconds) * sides
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
