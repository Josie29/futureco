import { useState } from "react"
import { Link } from "react-router-dom"
import { Mark } from "@/components/Mark"
import { Tag, equipmentLabel } from "@/components/Tag"
import { orderReasons, renderPath } from "@/lib/provenance"
import { formatMinutes } from "@/lib/utils"
import {
  ConceptIntent,
  FilterCause,
  PlanBlock,
  Verdict,
  type FilteredExercise,
  type PlanExercise,
  type ProvenanceTrace,
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
  [FilterCause.INJURY]: "not safe with her injury",
  [FilterCause.EQUIPMENT]: "need equipment she hasn't got",
  [FilterCause.DISLIKE]: "she dislikes these",
  [FilterCause.EXCLUSION]: "you asked to leave these out",
  [FilterCause.OUT_OF_SCOPE]: "outside what you asked for",
}

/** Short enough for the collapsed summary line. */
const CAUSE_SHORT: Record<FilterCause, string> = {
  [FilterCause.INJURY]: "her injury",
  [FilterCause.EQUIPMENT]: "equipment",
  [FilterCause.DISLIKE]: "disliked",
  [FilterCause.EXCLUSION]: "left out",
  [FilterCause.OUT_OF_SCOPE]: "off-brief",
}

/** "3 × 10", or "2 × 60s" for duration-based work. */
function reps(e: PlanExercise): string {
  if (e.reps !== null) return `${e.sets} × ${e.reps}`
  if (e.duration_sec !== null) return `${e.sets} × ${e.duration_sec}s`
  return "—"
}

/**
 * One movement, with the traversal that justified it available in place.
 *
 * The "why" is collapsed rather than absent: a coach reads the program most of
 * the time and audits it some of the time, and the second job shouldn't cost
 * the first any room. The traversal nests one level deeper again, so the three
 * audiences — running the session, understanding it, defending it — each get
 * what they need without any of them paying for the others.
 */
function ExerciseRow({ exercise }: { exercise: PlanExercise }) {
  const [open, setOpen] = useState(false)
  // Separate state, not derived from `open`: a coach auditing several movements
  // in a row shouldn't have to reopen the traversal on each one. Collapsing the
  // reasons and reopening them keeps whichever depth was last chosen.
  const [showPaths, setShowPaths] = useState(false)
  const reasons = orderReasons(exercise.why)

  return (
    <li className="border-t border-soft/60 first:border-t-0">
      <div className="grid grid-cols-[1.125rem_minmax(0,1fr)_6.5rem] items-start gap-2.5 px-3.5 py-1.5 hover:bg-ground/60">
        <Mark verdict={exercise.verdict} className="mt-[0.1875rem]" />

        <div className="min-w-0">
          <p className="text-body font-semibold -tracking-[0.012em]">{exercise.name}</p>

          <div className="mt-[0.1875rem] flex flex-wrap gap-1">
            {exercise.muscles.map((m) => (
              // Emphasis before goal when a muscle is both: the request is why
              // this movement is on the sheet, and the goal it also serves is
              // still one line down under "Why this one?".
              <Tag key={m.name} tone={m.is_focus ? "focus" : m.is_goal_target ? "goal" : "muscle"}>
                {m.name}
              </Tag>
            ))}
            {exercise.equipment.map((eq) => (
              <Tag key={eq} tone="equipment">
                {equipmentLabel(eq)}
              </Tag>
            ))}
          </div>

          {exercise.note && (
            <p className="mt-1 text-micro text-dim">
              {exercise.verdict === Verdict.CAUTION && (
                <b className="font-semibold text-red">Caution. </b>
              )}
              {exercise.note}
            </p>
          )}

          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="mt-1 text-micro text-faint underline underline-offset-2 hover:text-cobalt"
          >
            {open ? "Hide" : "Why this one?"}
          </button>

          {open && (
            <div className="mt-1 border-l-2 border-cobalt pl-2">
              <ul className="flex flex-col gap-1.5">
                {reasons.map((reason, i) => (
                  // Kind alone isn't unique — a movement can serve two goals —
                  // so position disambiguates within it.
                  <li key={`${reason.kind}-${i}`} className="text-micro text-dim">
                    {reason.detail}

                    {showPaths && (
                      <>
                        {/* The literal walk. `break-all` because a path is one
                            unbroken token to the browser, and would otherwise
                            widen the sheet on a long concept name. */}
                        <span className="mt-px block font-mono text-micro break-all text-faint">
                          {renderPath(reason.path)}
                        </span>
                        {/* Explains without scoring — names the injury sitting
                            at a flagged joint. See `Signal.annotation`. */}
                        {reason.annotation && (
                          <span className="block text-micro text-faint italic">
                            {reason.annotation}
                          </span>
                        )}
                      </>
                    )}
                  </li>
                ))}
              </ul>

              <button
                type="button"
                onClick={() => setShowPaths((v) => !v)}
                aria-expanded={showPaths}
                className="mt-1.5 font-mono text-micro text-faint underline underline-offset-2 hover:text-cobalt"
              >
                {showPaths ? "Hide the traversal" : "Show the traversal"}
              </button>
            </div>
          )}
        </div>

        <div className="text-right">
          <span className="num block text-lead leading-tight whitespace-nowrap">
            {reps(exercise)}
            {exercise.per_side && <small className="text-micro font-medium text-dim"> /side</small>}
          </span>
          <span className="block font-mono text-micro whitespace-nowrap text-faint">
            {exercise.rest_sec !== null && `${exercise.rest_sec}s rest · `}
            {formatMinutes(exercise.minutes)} min
          </span>
        </div>
      </div>
    </li>
  )
}

/** How the request was read, in the coach's words rather than the graph's. */
const INTENT_LABEL: Record<ConceptIntent, string> = {
  [ConceptIntent.FOCUS]: "Training",
  [ConceptIntent.PROTECT]: "Protecting",
  [ConceptIntent.EXCLUDE]: "Leaving out",
}

function ResolutionPanel({ trace }: { trace: ProvenanceTrace }) {
  if (trace.resolved.length === 0 && trace.unresolved.length === 0) return null

  return (
    <div className="border-t border-soft px-3.5 py-2">
      {trace.resolved.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-micro text-faint">Read as</span>
          {trace.resolved.map((c) => (
            <span key={`${c.concept_id}-${c.intent}`} className="text-micro text-dim">
              {INTENT_LABEL[c.intent]}{" "}
              <b className="font-semibold text-ink">
                {c.side ? `${c.side} ${c.concept_name}` : c.concept_name}
              </b>
            </span>
          ))}
        </div>
      )}

      {/* Graceful degradation, made visible (ASSESSMENT.md:68). A phrase the
          system could not act on is named, along with what it did instead —
          never silently dropped. The match scores behind this live in the
          trace payload; a coach needs the consequence, not the arithmetic. */}
      {trace.unresolved.map((u) => (
        <div key={u.phrase} className="mt-1.5 rounded-[4px] border border-red bg-red-wash p-2">
          <p className="text-micro font-semibold text-red">
            "{u.phrase}" didn't match anything
          </p>
          <p className="mt-px text-micro text-red">{u.fallback}</p>
        </div>
      ))}
    </div>
  )
}

/** Filtered movements, grouped by why. Collapsed — the coach won't run these. */
function DroppedDisclosure({ filtered }: { filtered: FilteredExercise[] }) {
  const [open, setOpen] = useState(false)
  if (filtered.length === 0) return null

  const byCause = filtered.reduce<Partial<Record<FilterCause, FilteredExercise[]>>>((acc, f) => {
    ;(acc[f.cause] ??= []).push(f)
    return acc
  }, {})

  const summary = Object.entries(byCause)
    .map(([cause, items]) => `${items.length} ${CAUSE_SHORT[cause as FilterCause]}`)
    .join(" · ")

  return (
    <div className="border-t border-soft">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3.5 py-2 text-left text-micro text-dim hover:text-ink"
      >
        <span aria-hidden>{open ? "▾" : "▸"}</span>
        <span>{filtered.length} movements didn't make it</span>
        <span className="ml-auto font-mono text-micro whitespace-nowrap text-faint">{summary}</span>
      </button>

      {open && (
        <div className="flex flex-col gap-2 pr-3.5 pb-2.5 pl-9">
          {Object.entries(byCause).map(([cause, items]) => (
            <div key={cause}>
              <p className="text-micro font-semibold text-red">
                {CAUSE_LABEL[cause as FilterCause]} — {items.length}
              </p>
              {items.map((f) => (
                <p
                  key={f.id}
                  className="grid grid-cols-[minmax(0,1fr)_auto] gap-2.5 text-micro text-dim"
                >
                  <span className="truncate line-through decoration-red">{f.name}</span>
                  <span className="font-mono text-micro whitespace-nowrap text-faint">
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

/**
 * What the marks and chips mean, said once instead of guessed at.
 *
 * Four chip states on two axes plus the verdict mark on a third is more than a
 * sheet can carry implicitly — the emphasis chip especially, which is the newest
 * and the one that explains why a movement is present at all.
 *
 * Ordered the way a row reads: the mark sits in the gutter, so it comes first,
 * then the muscle chips strongest to weakest, then equipment. Fixed rather than
 * built from the plan, so it never moves between one session and the next.
 */
function ChipKey() {
  return (
    <ul
      aria-label="What the marks and chips mean"
      className="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-soft bg-ground px-3.5 py-1.5"
    >
      <li className="flex items-center gap-1 text-micro text-faint">
        <Mark verdict={Verdict.CAUTION} />
        caution
      </li>
      <li>
        <Tag tone="focus">emphasis</Tag>
      </li>
      <li>
        <Tag tone="goal">goal</Tag>
      </li>
      <li>
        <Tag tone="muscle">trained</Tag>
      </li>
      <li>
        <Tag tone="equipment">equipment</Tag>
      </li>
    </ul>
  )
}

/** Where the movements went, so the sheet reconciles with the builder. */
function Funnel({ trace }: { trace: ProvenanceTrace }) {
  return (
    <p className="border-t border-soft px-3.5 py-2 text-micro text-faint">
      <span className="text-dim">{trace.catalogue_total}</span> movements in the library ·{" "}
      <span className="text-dim">{trace.eligible}</span> suit her today ·{" "}
      <span className="text-dim">{trace.prescribed}</span> in this session
    </p>
  )
}

/** Refine the plan in place. An adjustment is a new run, not a mutation. */
function AdjustBar({
  onAdjust,
  adjusting,
}: {
  onAdjust: (prompt: string) => void
  adjusting: boolean
}) {
  const [draft, setDraft] = useState("")

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!draft.trim() || adjusting) return
        onAdjust(draft.trim())
        setDraft("")
      }}
      className="flex items-center gap-2 border-t border-line bg-ground px-3.5 py-2"
    >
      <label htmlFor="adjust" className="sr-only">
        Adjust this plan
      </label>
      <input
        id="adjust"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        disabled={adjusting}
        placeholder="Adjust it — “exclude lunges”, “go easier on the knee”"
        className="min-w-0 flex-1 rounded-[4px] border border-line bg-card px-2 py-1 text-meta outline-none placeholder:text-faint"
      />
      <button
        type="submit"
        disabled={!draft.trim() || adjusting}
        className="shrink-0 rounded-[4px] border border-ink px-2 py-1 text-micro font-semibold disabled:opacity-40"
      >
        {adjusting ? "Adjusting…" : "Adjust"}
      </button>
    </form>
  )
}

export function PlanSheet({
  plan,
  onAdjust,
  adjusting,
}: {
  plan: WorkoutPlan
  onAdjust: (prompt: string) => void
  adjusting: boolean
}) {
  const spare = Math.max(0, plan.requested_minutes - plan.estimated_minutes)
  const blockMinutes = (block: PlanBlock) =>
    plan.exercises.filter((e) => e.block === block).reduce((n, e) => n + e.minutes, 0)

  return (
    <section className="rounded-[4px] border border-line bg-card">
      <header className="border-b border-soft px-3.5 py-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="disp text-title">
            {plan.title}{" "}
            <span className="font-medium text-dim" style={{ fontStretch: "normal" }}>
              · {plan.day_label}
            </span>
          </h2>
          <span className="num text-lead whitespace-nowrap">
            {formatMinutes(plan.estimated_minutes)}
            <small className="text-micro font-medium text-dim"> / {plan.requested_minutes} min</small>{" "}
            {spare > 0 && (
              <span className="text-micro font-medium text-cobalt" style={{ fontStretch: "normal" }}>
                {formatMinutes(spare)} spare
              </span>
            )}
          </span>
        </div>

        <p className="mt-0.5 flex items-baseline gap-2 text-micro text-faint">
          {/* The whole trail, not just the last utterance. A refinement
              composes onto its parent, so the session is still answering to
              everything above — showing only the newest made an adjusted plan
              read as though it had dropped the original request. */}
          <span className="min-w-0 truncate">
            {(plan.prompt_trail?.length ? plan.prompt_trail : [plan.prompt]).map((step, i) => (
              <span key={i}>
                {i > 0 && <span className="text-cobalt"> → </span>}“{step}”
              </span>
            ))}
          </span>
          {/* The full traversal lives one click away rather than on this page.
              A coach never has to open it; anyone defending the plan can. */}
          <Link
            to={`/traces?run=${plan.run_id}`}
            className="ml-auto shrink-0 whitespace-nowrap underline underline-offset-2 hover:text-cobalt"
          >
            How this was built
          </Link>
        </p>

        {/* Each block sized by its real share of the requested window, so a
            coach sees where the time goes and how much is left to spend. */}
        <div
          className="mt-2 flex h-1 gap-0.5"
          role="img"
          aria-label={BLOCK_ORDER.map((b) => `${BLOCK_LABEL[b]} ${formatMinutes(blockMinutes(b))} minutes`)
            .concat(`${formatMinutes(spare)} spare`)
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

      <ResolutionPanel trace={plan.trace} />
      {/* Directly above the first block rather than up in the header: it
          explains the rows, so it sits against them. */}
      <ChipKey />

      {BLOCK_ORDER.map((block) => {
        const items = plan.exercises.filter((e) => e.block === block)
        if (items.length === 0) return null
        return (
          <div key={block}>
            <div className="flex items-baseline justify-between px-3.5 pt-2.5 pb-0.5">
              <h3 className="text-meta font-bold -tracking-[0.005em]">{BLOCK_LABEL[block]}</h3>
              <span className="font-mono text-micro text-faint">{formatMinutes(blockMinutes(block))} min</span>
            </div>
            <ul>
              {items.map((e) => (
                <ExerciseRow key={e.id} exercise={e} />
              ))}
            </ul>
          </div>
        )
      })}

      <Funnel trace={plan.trace} />
      <DroppedDisclosure filtered={plan.trace.filtered} />
      <AdjustBar onAdjust={onAdjust} adjusting={adjusting} />
    </section>
  )
}
