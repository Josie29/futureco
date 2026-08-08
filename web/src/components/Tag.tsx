import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

/**
 * A catalogue value rendered as a chip. Monospace because these are literal
 * values from the graph rather than prose.
 *
 * `goal` lights cobalt when a muscle matches one the member's goals name, so
 * goal alignment reads across the plan without a separate column. `kit` is
 * outlined rather than filled so equipment never gets confused with muscle.
 */
export function Tag({
  children,
  tone = "muscle",
  className,
}: {
  children: ReactNode
  tone?: "muscle" | "goal" | "kit"
  className?: string
}) {
  return (
    <span
      className={cn(
        "rounded-[2px] px-[0.3125rem] py-px font-mono text-[0.5938rem] whitespace-nowrap",
        tone === "goal" && "bg-cobalt-wash text-cobalt",
        tone === "muscle" && "bg-soft text-dim",
        tone === "kit" && "border border-line text-faint",
        className,
      )}
    >
      {children}
    </span>
  )
}

/** Program-sheet shorthand for equipment names. */
const SHORTHAND: Record<string, string> = {
  Dumbbell: "dumbbell",
  Kettlebell: "kettlebell",
  "Resistance Band - Loop": "band",
  "Yoga Mat": "mat",
  "Flat Bench": "bench",
  Barbell: "barbell",
  Rack: "rack",
  Plate: "plate",
  Box: "box",
  Bodyweight: "bodyweight",
}

/**
 * Shorten an equipment name the way a coach writes it on a program sheet.
 *
 * @param name Full catalogue name, e.g. "Resistance Band - Loop".
 * @returns The shorthand, or the lowercased name when unmapped.
 */
export function equipmentLabel(name: string): string {
  return SHORTHAND[name] ?? name.toLowerCase()
}
