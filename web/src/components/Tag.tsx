import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

/**
 * A catalogue value rendered as a chip. Monospace because these are literal
 * values from the graph rather than prose.
 *
 * `goal` lights cobalt when a muscle matches one the member's goals name, so
 * goal alignment reads across the plan without a separate column. `equipment` is
 * outlined rather than filled so it never gets confused with muscle.
 *
 * `focus` is the same cobalt at full strength, for a muscle *this request*
 * asked to emphasise. Weight rather than hue, because the two mean related
 * things — both are a reason to prefer the movement — and the palette carries
 * one accent besides red on purpose. Solid reads as the sharper of the pair,
 * which is right: a goal is standing, an emphasis is what a coach said today
 * and is the reason the movement is on the sheet at all.
 */
export function Tag({
  children,
  tone = "muscle",
  className,
  title,
}: {
  children: ReactNode
  tone?: "muscle" | "goal" | "focus" | "equipment"
  className?: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={cn(
        "rounded-[2px] px-[0.3125rem] py-px font-mono text-micro whitespace-nowrap",
        tone === "focus" && "bg-cobalt text-card",
        tone === "goal" && "bg-cobalt-wash text-cobalt",
        tone === "muscle" && "bg-soft text-dim",
        tone === "equipment" && "border border-line text-faint",
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
