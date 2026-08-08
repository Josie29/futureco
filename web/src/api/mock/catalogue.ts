import { catalog, itemId, member, type CatalogExercise } from "@/api/fixtures"
import {
  ConstraintKind,
  FilterCause,
  NodeLabel,
  RelType,
  type Eligibility,
  type FilteredExercise,
} from "@/types"

/**
 * MOCK — throwaway. Replaced wholesale by the real API.
 *
 * The two standing rules, and only enough of them to keep the numbers on
 * screen honest. The real filtering is a graph traversal in the backend; this
 * is a stand-in so the builder's count and the plan sheet's funnel reconcile
 * instead of contradicting each other.
 *
 * See `docs/mock-notes.md` for what this deliberately does not do.
 */

const CONTRAINDICATED_PATTERN = "cardio - plyometric"

/** Her recorded injury and its condition, the entry point for a clinical walk. */
const INJURY = "inj_knee_left"
const CONDITION = "Patellofemoral stress syndrome"

export const byName = new Map(catalog.map((e) => [e.name, e]))

/**
 * Equipment she can use for this run.
 *
 * A coach switching off "Flat Bench" is saying she hasn't got it today, so it
 * narrows the pool the same way not owning it would.
 */
function availableEquipment(disabled: string[]): Set<string> {
  const off = new Set(disabled)
  return new Set(
    member.equipment_available.filter(
      (name) => !off.has(itemId(ConstraintKind.EQUIPMENT, name)),
    ),
  )
}

/**
 * Walk the catalogue under the standing constraints.
 *
 * Injury is charged before equipment, which is the truthful order: those six
 * movements are out for her whatever equipment she has.
 *
 * @param disabled `ConstraintItem.id`s switched off for this run. Injury items
 *   are ignored — the rule applies regardless, as it does in the API.
 * @returns Survivors and, for each casualty, the rule that removed it.
 */
export function screen(disabled: string[] = []): {
  survivors: CatalogExercise[]
  filtered: FilteredExercise[]
} {
  const owned = availableEquipment(disabled)
  const survivors: CatalogExercise[] = []
  const filtered: FilteredExercise[] = []

  for (const exercise of catalog) {
    if (exercise.movement_patterns.includes(CONTRAINDICATED_PATTERN)) {
      filtered.push({
        id: exercise.id,
        name: exercise.name,
        cause: FilterCause.INJURY,
        detail: "jumping and landing",
        // The clinical walk, hop for hop as `_clinical_signals` emits it:
        // injury to condition to contraindicated pattern, then back out to the
        // exercise that is one. See `docs/decisions.md`, KG1 item 3.
        path: {
          entry: INJURY,
          hops: [
            { rel: RelType.DIAGNOSED_AS, to_label: NodeLabel.CONDITION, to_name: CONDITION },
            {
              rel: RelType.CONTRAINDICATES,
              to_label: NodeLabel.MOVEMENT_PATTERN,
              to_name: CONTRAINDICATED_PATTERN,
            },
            { rel: RelType.IS_A, to_label: NodeLabel.EXERCISE, to_name: "(this)" },
          ],
        },
      })
      continue
    }

    const missing = exercise.equipment_required.filter((item) => !owned.has(item))
    if (missing.length > 0) {
      filtered.push({
        id: exercise.id,
        name: exercise.name,
        cause: FilterCause.EQUIPMENT,
        detail: `needs ${missing.join(", ")}`,
        // `_constraint_signals` emits one signal per missing item, entered at
        // the exercise. Only the first is shown; `detail` names them all.
        path: {
          entry: exercise.name,
          hops: [{ rel: RelType.REQUIRES, to_label: NodeLabel.EQUIPMENT, to_name: missing[0] }],
        },
      })
      continue
    }

    survivors.push(exercise)
  }

  return { survivors, filtered }
}

/**
 * The standing eligible pool. With nothing switched off: 18 of 50, 6 on the
 * injury and 26 on equipment she hasn't got.
 */
export function computeEligibility(disabled: string[] = []): Eligibility {
  const { survivors, filtered } = screen(disabled)
  const excludedBy: Record<FilterCause, number> = {
    [FilterCause.INJURY]: 0,
    [FilterCause.EQUIPMENT]: 0,
    [FilterCause.DISLIKE]: 0,
    [FilterCause.EXCLUSION]: 0,
    [FilterCause.OUT_OF_SCOPE]: 0,
  }
  for (const row of filtered) excludedBy[row.cause] += 1

  return { total: catalog.length, available: survivors.length, excluded_by: excludedBy }
}
