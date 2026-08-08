import { useEffect, useState } from "react"
import { cn } from "@/lib/utils"

/** The pipeline, named for the coach. Mirrors `ProvenanceTrace.stages`. */
const STAGES = [
  "Reading what you asked for",
  "Applying her injury and equipment",
  "Matching movements to the brief",
  "Building the session",
] as const

const STAGE_MS = 320

/**
 * Named stages, so a multi-second wait says what it is doing.
 *
 * The stages advance on a timer today because the mock resolves in one call.
 * When the endpoint streams them the timer goes away and the same component
 * renders real progress — which is why the labels match the trace's own.
 */
export function BuildProgress({ adjusting = false }: { adjusting?: boolean }) {
  const [stage, setStage] = useState(0)

  useEffect(() => {
    setStage(0)
    const timers = STAGES.map((_, i) =>
      window.setTimeout(() => setStage(i), i * STAGE_MS),
    )
    return () => timers.forEach(window.clearTimeout)
  }, [])

  return (
    <div
      className="flex flex-col gap-1 rounded-[4px] border border-line bg-card p-3"
      role="status"
      aria-live="polite"
      aria-label={adjusting ? "Adjusting the plan" : "Building the session"}
    >
      {adjusting && (
        <span className="mb-1 text-micro text-dim">
          Adjusting — this makes a new version. The current one stays on file.
        </span>
      )}
      {STAGES.map((label, i) => (
        <span
          key={label}
          className={cn(
            "font-mono text-micro",
            i < stage ? "text-faint" : i === stage ? "text-ink" : "text-line",
          )}
        >
          {i < stage ? "done" : i === stage ? "▸" : "·"} {label}
        </span>
      ))}
    </div>
  )
}
