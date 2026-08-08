import { ReasonKind, type EvidencePath, type Reason } from "@/types"

/**
 * Reading order for a movement's reasons, most load-bearing first.
 *
 * Safety leads because it is the claim a coach is accountable for; goal fit
 * follows, because it is why this movement rather than another equally safe
 * one; mechanics come last. Kinds absent from this list sort to the end in
 * payload order, so a reason the backend adds before the console catches up
 * still renders rather than disappearing.
 */
const READING_ORDER: readonly ReasonKind[] = [
  ReasonKind.CLEARED,
  ReasonKind.CAUTION,
  ReasonKind.FLAGGED_STRUCTURE,
  ReasonKind.GOAL_SERVICE,
  ReasonKind.FOCUS_MATCH,
  ReasonKind.SUBSTITUTION,
  ReasonKind.EQUIPMENT_FIT,
  ReasonKind.PATTERN_ROLE,
]

/**
 * Render a path as `entry -rel-> Name -rel-> Name`.
 *
 * The TS twin of `EvidencePath.render()` in `backend/src/safety/evidence.py`.
 * Both exist because the payload carries structure, not prose: the backend
 * renders for its own logs, the console for the traversal disclosure and the
 * Traces tab. Keep the two in step — a reviewer comparing a span against a
 * plan sheet is comparing the output of these two functions.
 *
 * @param path The traversal to render.
 * @returns One line, arrows included. Just the entry when there are no hops.
 */
export function renderPath(path: EvidencePath): string {
  return [path.entry, ...path.hops.map((hop) => `-${hop.rel}-> ${hop.to_name}`)].join(" ")
}

/**
 * Sort reasons into reading order, without mutating the payload.
 *
 * Stable within a kind, so two goal-service reasons keep the order the graph
 * returned them in rather than being reshuffled on every render.
 *
 * @param reasons The movement's reasons, as the API returned them.
 * @returns The same reasons, ordered for a coach reading top to bottom.
 */
export function orderReasons(reasons: Reason[]): Reason[] {
  const rank = (kind: ReasonKind): number => {
    const index = READING_ORDER.indexOf(kind)
    return index === -1 ? READING_ORDER.length : index
  }
  return [...reasons].sort((a, b) => rank(a.kind) - rank(b.kind))
}
