import { useState } from "react"
import { Mark } from "@/components/Mark"
import { cn } from "@/lib/utils"
import {
  FilterCause,
  PlanBlock,
  Verdict,
  type FilteredExercise,
  type PlanExercise,
  type WorkoutPlan,
} from "@/types"

const BLOCK_LABEL: Record<PlanBlock, string> = {
  [PlanBlock.WARMUP]: "Warm-up",
  [PlanBlock.MAIN]: "Main",
  [PlanBlock.COOLDOWN]: "Cool-down",
}

const CAUSE_LABEL: Record<FilterCause, string> = {
  [FilterCause.INJURY]: "injury",
  [FilterCause.EQUIPMENT]: "equipment",
  [FilterCause.DISLIKE]: "dislikes",
  [FilterCause.EXCLUSION]: "excluded",
  [FilterCause.OUT_OF_SCOPE]: "out of scope",
}

/** "3 × 10 · 60s" — the program-sheet shorthand, in tabular figures. */
function dose(e: PlanExercise): string {
  const parts: string[] = []
  if (e.sets && e.reps) parts.push(`${e.sets} × ${e.reps}`)
  if (e.duration_sec) parts.push(`${e.duration_sec}s`)
  if (e.rest_sec) parts.push(`${e.rest_sec}s rest`)
  if (e.per_side) parts.push("per side")
  return parts.join(" · ") || "—"
}

/**
 * One row of the sheet. The margin carries the verdict and the graph path; the
 * body carries the movement. Rejected exercises keep their row and are struck
 * through rather than hidden, so a coach reads the decision itself rather than
 * a summary of it.
 */
function Line({
  margin,
  name,
  detail,
  trace,
  struck = false,
  accent = false,
  mark,
}: {
  margin: string
  name: string
  detail?: string
  trace: string
  struck?: boolean
  accent?: boolean
  mark?: Verdict
}) {
  return (
    <div className="grid grid-cols-[5.25rem_1fr] gap-3 py-0.5">
      <div
        className={cn(
          "flex items-baseline justify-end gap-1 whitespace-nowrap text-right font-mono text-[10px]",
          mark === Verdict.CLEARED || !mark ? "text-slate-soft" : "text-carmine",
        )}
      >
        {mark && <Mark verdict={mark} className="self-center" />}
        {margin}
      </div>

      <div
        className={cn(
          "border-l pl-3",
          accent ? "border-l-carmine" : "border-l-rule-soft",
        )}
      >
        <div className="flex items-baseline justify-between gap-3">
          <span
            className={cn(
              "font-medium",
              struck && "text-slate-soft line-through decoration-carmine",
            )}
          >
            {name}
          </span>
          {detail && (
            <span className="shrink-0 font-mono text-[11px] text-slate">{detail}</span>
          )}
        </div>
        <div className="font-mono text-[10px] text-slate-soft">{trace}</div>
      </div>
    </div>
  )
}

export function PlanSheet({ plan }: { plan: WorkoutPlan }) {
  const [showFiltered, setShowFiltered] = useState(false)

  const blocks = [PlanBlock.WARMUP, PlanBlock.MAIN, PlanBlock.COOLDOWN]
  const byCause = plan.trace.filtered.reduce<Record<string, FilteredExercise[]>>(
    (acc, f) => {
      ;(acc[f.cause] ??= []).push(f)
      return acc
    },
    {},
  )

  return (
    <section className="flex flex-col gap-1">
      <div className="eyebrow grid grid-cols-[5.25rem_1fr] gap-3 pt-2">
        <span>Why</span>
        <span className="border-t border-rule pt-1">
          {plan.title} · {plan.estimated_minutes} of {plan.requested_minutes} min
        </span>
      </div>

      {blocks.map((block) => {
        const items = plan.exercises.filter((e) => e.block === block)
        if (items.length === 0) return null

        return (
          <div key={block} className="flex flex-col gap-1">
            <div className="eyebrow grid grid-cols-[5.25rem_1fr] gap-3 pt-2">
              <span />
              <span className="border-t border-rule pt-1">{BLOCK_LABEL[block]}</span>
            </div>

            {items.map((e) => (
              <div key={e.id}>
                {e.substituted_for && (
                  <Line
                    mark={Verdict.EXCLUDED}
                    margin={CAUSE_LABEL[FilterCause.EQUIPMENT]}
                    name={e.substituted_for.name}
                    trace={`replaced — via ${e.substituted_for.via_pattern}`}
                    struck
                  />
                )}
                <Line
                  mark={e.verdict}
                  margin={
                    e.substituted_for
                      ? "substituted"
                      : e.verdict === Verdict.CAUTION
                        ? "caution"
                        : "cleared"
                  }
                  name={e.name}
                  detail={dose(e)}
                  trace={e.trace}
                  accent={Boolean(e.substituted_for)}
                />
              </div>
            ))}
          </div>
        )
      })}

      {plan.trace.unresolved.length > 0 && (
        <div className="mt-2 rounded-[3px] border border-carmine bg-carmine-tint p-2">
          <div className="eyebrow text-carmine">Couldn't resolve</div>
          {plan.trace.unresolved.map((u) => (
            <p key={u.phrase} className="font-mono text-[10px] text-carmine">
              "{u.phrase}" — {u.fallback}
            </p>
          ))}
        </div>
      )}

      <div className="mt-2 flex flex-col gap-1 border-t border-rule pt-2">
        <span className="font-mono text-[10px] text-slate">
          {plan.trace.eligible} eligible of {plan.trace.catalogue_total} ·{" "}
          {plan.trace.filtered.length} shown below
        </span>

        <button
          type="button"
          onClick={() => setShowFiltered((v) => !v)}
          aria-expanded={showFiltered}
          className="self-start font-mono text-[10px] text-slate underline underline-offset-2"
        >
          {showFiltered ? "Hide what was filtered" : "Show what was filtered"}
        </button>

        {showFiltered && (
          <div className="flex flex-col gap-2 pt-1">
            {Object.entries(byCause).map(([cause, items]) => (
              <div key={cause} className="flex flex-col gap-0.5">
                <span className="eyebrow text-carmine">
                  {CAUSE_LABEL[cause as FilterCause]} — {items.length}
                </span>
                {items.map((f) => (
                  <Line
                    key={f.id}
                    mark={Verdict.EXCLUDED}
                    margin={CAUSE_LABEL[f.cause]}
                    name={f.name}
                    trace={f.trace}
                    struck
                  />
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
