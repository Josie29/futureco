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
 * Safety renders as one hue at three intensities, not traffic lights — absolute
 * and relative contraindication are a gradient, which is why the graph splits
 * `contraindicates` from `cautions`. The shape carries the meaning so nothing
 * depends on colour alone. See docs/frontend-spec.md.
 */
export function Mark({
  verdict,
  className,
}: {
  verdict: Verdict
  className?: string
}) {
  const stroke =
    verdict === Verdict.CLEARED ? "var(--color-slate)" : "var(--color-carmine)"

  return (
    <svg
      viewBox="0 0 10 10"
      className={cn("size-[9px] shrink-0", className)}
      role="img"
      aria-label={LABEL[verdict]}
      fill="none"
      stroke={stroke}
      strokeWidth={1.6}
      strokeLinecap="round"
    >
      {verdict === Verdict.EXCLUDED && (
        <path d="M2.4 2.4 L7.6 7.6 M7.6 2.4 L2.4 7.6" />
      )}
      {verdict === Verdict.CAUTION && <circle cx="5" cy="5" r="3" />}
      {verdict === Verdict.CLEARED && <path d="M2 5.4 L4 7.4 L8 3" />}
    </svg>
  )
}
