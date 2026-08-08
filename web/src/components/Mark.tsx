import { Verdict } from "@/types"
import { cn } from "@/lib/utils"

const LABEL: Record<Verdict, string> = {
  [Verdict.EXCLUDED]: "Excluded",
  [Verdict.CAUTION]: "Caution",
  [Verdict.CLEARED]: "Cleared",
}

/**
 * The verdict mark: three pieces of geometry rather than an icon-library glyph.
 *
 * Safety renders as one hue at two intensities plus a neutral, not traffic
 * lights — absolute and relative contraindication are a gradient, which is why
 * the graph splits `contraindicates` from `cautions`. The shape carries the
 * meaning so nothing depends on colour alone.
 */
export function Mark({ verdict, className }: { verdict: Verdict; className?: string }) {
  return (
    <svg
      viewBox="0 0 12 12"
      className={cn(
        "size-3 shrink-0",
        verdict === Verdict.CLEARED ? "text-faint" : "text-red",
        className,
      )}
      role="img"
      aria-label={LABEL[verdict]}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
    >
      {verdict === Verdict.EXCLUDED && <path d="M3.2 3.2 L8.8 8.8 M8.8 3.2 L3.2 8.8" />}
      {verdict === Verdict.CAUTION && <circle cx="6" cy="6" r="3.6" />}
      {verdict === Verdict.CLEARED && <path d="M2.6 6.4 L4.9 8.8 L9.4 3.2" />}
    </svg>
  )
}
