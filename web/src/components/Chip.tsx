import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

/** Equipment written the way a coach writes it on a program sheet. */
const EQUIPMENT_ABBREV: Record<string, string> = {
  Dumbbell: "DB",
  Kettlebell: "KB",
  "Resistance Band - Loop": "BND",
  "Yoga Mat": "MAT",
  "Flat Bench": "BCH",
  Barbell: "BB",
  Rack: "RCK",
  Plate: "PLT",
  Box: "BOX",
}

/**
 * Abbreviate an equipment name to its program-sheet shorthand.
 *
 * @param name Full catalogue name, e.g. "Resistance Band - Loop".
 * @returns The shorthand, or an uppercased truncation when unmapped.
 */
export function abbreviateEquipment(name: string): string {
  return EQUIPMENT_ABBREV[name] ?? name.slice(0, 3).toUpperCase()
}

export function Chip({
  children,
  tone = "neutral",
  className,
  title,
}: {
  children: ReactNode
  /** `alert` is the only tone that uses carmine, and only for safety state. */
  tone?: "neutral" | "alert"
  className?: string
  /** Full name behind an abbreviation, surfaced on hover. */
  title?: string
}) {
  return (
    <span
      title={title}
      className={cn(
        "rounded-[2px] border px-1 py-px font-mono text-[10px] tracking-wide",
        tone === "alert"
          ? "border-carmine bg-carmine-tint text-carmine"
          : "border-rule bg-film text-slate",
        className,
      )}
    >
      {children}
    </span>
  )
}
