import { catalog, itemId, member, type CatalogExercise } from "@/api/fixtures"
import { ConstraintKind, FilterCause, type Eligibility, type FilteredExercise } from "@/types"

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
        path: `Injury -diagnosed_as-> Condition(patellofemoral pain syndrome) -contraindicates-> MovementPattern(${CONTRAINDICATED_PATTERN}) <-is_a- Exercise`,
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
        path: `Exercise -requires-> Equipment(${missing[0]}) ∉ Member -has-> Equipment`,
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
