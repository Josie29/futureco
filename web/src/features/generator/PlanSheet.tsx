import { useState } from "react"
import { Mark } from "@/components/Mark"
import { Tag, equipmentLabel } from "@/components/Tag"
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

const BLOCK_ORDER = [PlanBlock.WARMUP, PlanBlock.MAIN, PlanBlock.COOLDOWN] as const

/** Cobalt marks the main block; warm-up and cool-down stay neutral. */
const BLOCK_FILL: Record<PlanBlock, string> = {
  [PlanBlock.WARMUP]: "var(--color-faint)",
  [PlanBlock.MAIN]: "var(--color-cobalt)",
  [PlanBlock.COOLDOWN]: "#c3c3c8",
}

const CAUSE_LABEL: Record<FilterCause, string> = {
  [FilterCause.INJURY]: "contraindicated for her injury",
  [FilterCause.EQUIPMENT]: "needs kit she doesn't have",
  [FilterCause.DISLIKE]: "she dislikes these",
  [FilterCause.EXCLUSION]: "you excluded these",
  [FilterCause.OUT_OF_SCOPE]: "outside what you asked for",
}

/** "3 × 10", or "2 × 60s" for duration-based work. */
function reps(e: PlanExercise): string {
  if (e.reps !== null) return `${e.sets} × ${e.reps}`
  if (e.duration_sec !== null) return `${e.sets} × ${e.duration_sec}s`
  return "—"
}

function ExerciseRow({ exercise }: { exercise: PlanExercise }) {
  return (
    <li className="grid grid-cols-[1.125rem_minmax(0,1fr)_6.5rem] items-start gap-2.5 px-3.5 py-1.5 hover:bg-ground/60">
      <Mark verdict={exercise.verdict} className="mt-[0.1875rem]" />

      <div className="min-w-0">
        <p className="text-sm font-semibold -tracking-[0.012em]">{exercise.name}</p>

        <div className="mt-[0.1875rem] flex flex-wrap gap-1">
          {exercise.muscles.map((m) => (
            <Tag key={m.name} tone={m.is_goal_target ? "goal" : "muscle"}>
              {m.name}
            </Tag>
          ))}
          {exercise.equipment.map((eq) => (
            <Tag key={eq} tone="kit">
              {equipmentLabel(eq)}
            </Tag>
          ))}
        </div>

        {exercise.note && (
          <p className="mt-1 text-[0.6875rem] text-dim">
            {exercise.verdict === Verdict.CAUTION && (
              <b className="font-semibold text-red">Caution. </b>
            )}
            {exercise.note}
          </p>
        )}
      </div>

      <div className="text-right">
        <span className="num block text-base leading-tight whitespace-nowrap">
          {reps(exercise)}
          {exercise.per_side && (
            <small className="text-[0.6875rem] font-medium text-dim"> /side</small>
          )}
        </span>
        <span className="block font-mono text-[0.5938rem] whitespace-nowrap text-faint">
          {exercise.rest_sec !== null && `${exercise.rest_sec}s rest · `}
          {exercise.minutes} min
        </span>
      </div>
    </li>
  )
}

/** Filtered movements, grouped by why. Collapsed — the coach won't run these. */
function DroppedDisclosure({ filtered }: { filtered: FilteredExercise[] }) {
  const [open, setOpen] = useState(false)
  if (filtered.length === 0) return null

  const byCause = filtered.reduce<Partial<Record<FilterCause, FilteredExercise[]>>>(
    (acc, f) => {
      ;(acc[f.cause] ??= []).push(f)
      return acc
    },
    {},
  )

  const summary = Object.entries(byCause)
    .map(([cause, items]) => `${items.length} ${cause}`)
    .join(" · ")

  return (
    <div className="border-t border-soft">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3.5 py-2 text-left text-[0.6875rem] text-dim hover:text-ink"
      >
        <span aria-hidden>{open ? "▾" : "▸"}</span>
        <span>{filtered.length} movements didn't make it</span>
        <span className="ml-auto font-mono text-[0.5938rem] whitespace-nowrap text-faint">
          {summary}
        </span>
      </button>

      {open && (
        <div className="flex flex-col gap-1 pr-3.5 pb-2.5 pl-9">
          {Object.entries(byCause).map(([cause, items]) => (
            <div key={cause}>
              <p className="mt-1 text-[0.625rem] font-semibold text-red">
                {CAUSE_LABEL[cause as FilterCause]} — {items.length}
              </p>
              {items.map((f) => (
                <p
                  key={f.id}
                  className="grid grid-cols-[minmax(0,1fr)_auto] gap-2.5 text-[0.6875rem] text-dim"
                >
                  <span className="truncate line-through decoration-red">{f.name}</span>
                  <span className="font-mono text-[0.5938rem] whitespace-nowrap text-faint">
                    {f.detail}
                  </span>
                </p>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function PlanSheet({ plan }: { plan: WorkoutPlan }) {
  const spare = Math.max(0, plan.requested_minutes - plan.estimated_minutes)
  const blockMinutes = (block: PlanBlock) =>
    plan.exercises.filter((e) => e.block === block).reduce((n, e) => n + e.minutes, 0)

  return (
    <section className="rounded-[4px] border border-line bg-card">
      <header className="border-b border-soft px-3.5 py-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="disp text-lg">
            {plan.title}{" "}
            <span className="font-medium text-dim" style={{ fontStretch: "normal" }}>
              · {plan.day_label}
            </span>
          </h2>
          <span className="num text-base whitespace-nowrap">
            {plan.estimated_minutes}
            <small className="text-[0.6875rem] font-medium text-dim">
              {" "}
              / {plan.requested_minutes} min
            </small>{" "}
            {spare > 0 && (
              <span
                className="text-[0.6875rem] font-medium text-cobalt"
                style={{ fontStretch: "normal" }}
              >
                {spare} spare
              </span>
            )}
          </span>
        </div>

        {/* Each block sized by its real share of the requested window, so a
            coach sees where the time goes and how much is left to spend. */}
        <div
          className="mt-2 flex h-1 gap-0.5"
          role="img"
          aria-label={BLOCK_ORDER.map((b) => `${BLOCK_LABEL[b]} ${blockMinutes(b)} minutes`)
            .concat(`${spare} spare`)
            .join(", ")}
        >
          {BLOCK_ORDER.map((b) => (
            <i
              key={b}
              className="block rounded-[1px]"
              style={{
                background: BLOCK_FILL[b],
                width: `${(blockMinutes(b) / plan.requested_minutes) * 100}%`,
              }}
            />
          ))}
          <i
            className="block rounded-[1px] bg-soft"
            style={{ width: `${(spare / plan.requested_minutes) * 100}%` }}
          />
        </div>
      </header>

      {BLOCK_ORDER.map((block) => {
        const items = plan.exercises.filter((e) => e.block === block)
        if (items.length === 0) return null
        return (
          <div key={block}>
            <div className="flex items-baseline justify-between px-3.5 pt-2.5 pb-0.5">
              <h3 className="text-xs font-bold -tracking-[0.005em]">{BLOCK_LABEL[block]}</h3>
              <span className="font-mono text-[0.5938rem] text-faint">
                {blockMinutes(block)} min
              </span>
            </div>
            <ul>
              {items.map((e) => (
                <ExerciseRow key={e.id} exercise={e} />
              ))}
            </ul>
          </div>
        )
      })}

      {plan.trace.unresolved.length > 0 && (
        <div className="mx-3.5 mb-2.5 rounded-[4px] border border-red bg-red-wash p-2">
          <p className="text-[0.625rem] font-semibold text-red">Couldn't resolve</p>
          {plan.trace.unresolved.map((u) => (
            <p key={u.phrase} className="text-[0.6875rem] text-red">
              "{u.phrase}" — {u.fallback}
            </p>
          ))}
        </div>
      )}

      <DroppedDisclosure filtered={plan.trace.filtered} />
    </section>
  )
}
