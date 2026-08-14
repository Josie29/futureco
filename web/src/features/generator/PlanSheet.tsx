import { useState } from "react"
import { Link } from "react-router-dom"

import { Mark } from "@/components/Mark"
import { Tag, equipmentLabel } from "@/components/Tag"
import { cn } from "@/lib/utils"
import type { ExclusionRecord, ExerciseFacts, PlanResponse, PlannedExercise } from "@/types"
import { Verdict } from "@/types"

const SECTIONS = [
  ["warmup", "Warm-up"],
  ["main", "Main"],
  ["cooldown", "Cool-down"],
] as const

function minutes(seconds: number): string {
  return `${Math.round(seconds / 60)} min`
}

function conceptName(conceptId: string): string {
  const [, ...rest] = conceptId.split(":")
  return rest.join(":")
}

/**
 * The slot's chip row. Muscle chips carry the alignment: solid cobalt when the
 * coach's directives name them, washed cobalt when only a goal does — the
 * `Tag` tone semantics. Coach-declared targets that aren't muscles or
 * equipment (patterns, a required exercise) get their own solid chips so the
 * ask stays visible.
 */
function FactTags({ facts }: { facts: ExerciseFacts }) {
  const fromCoach = new Set(facts.from_coach)
  const goalTitle = (muscle: string) =>
    facts.goals
      .filter((g) => g.muscle === muscle)
      .map((g) => g.goal)
      .join("; ")
  const extraAsks = facts.from_coach.filter(
    (name) => !facts.muscles.includes(name) && !facts.equipment.includes(name),
  )

  return (
    <span className="mt-1 flex flex-wrap gap-1">
      {extraAsks.map((name) => (
        <Tag key={name} tone="focus">
          {name.toLowerCase()}
        </Tag>
      ))}
      {facts.muscles.map((muscle) => (
        <Tag
          key={muscle}
          tone={
            fromCoach.has(muscle)
              ? "focus"
              : facts.focus_muscles.includes(muscle)
                ? "goal"
                : "muscle"
          }
          title={goalTitle(muscle) || undefined}
        >
          {muscle.toLowerCase()}
        </Tag>
      ))}
      {facts.equipment.map((name) => (
        <Tag
          key={name}
          tone="equipment"
          className={facts.missing_equipment.includes(name) ? "line-through" : undefined}
          title={
            facts.missing_equipment.includes(name)
              ? "Not in the member's own equipment — see the rationale"
              : undefined
          }
        >
          {equipmentLabel(name)}
        </Tag>
      ))}
    </span>
  )
}

function Slot({
  exercise,
  facts,
}: {
  exercise: PlannedExercise
  facts?: ExerciseFacts
}) {
  return (
    <li className="border-t border-soft px-3.5 py-2 first:border-t-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className="flex min-w-0 items-center gap-1.5">
          {exercise.caution_note && <Mark verdict={Verdict.CAUTION} />}
          <span className="truncate font-medium">{exercise.label}</span>
        </span>
        <span className="num whitespace-nowrap text-meta text-dim">
          {exercise.sets} × {exercise.reps} · {minutes(exercise.seconds)}
        </span>
      </div>
      {facts && <FactTags facts={facts} />}
      <p className="mt-0.5 text-micro text-faint">{exercise.rationale}</p>
      {exercise.caution_note && (
        <p className="mt-1 rounded-[4px] border border-amber-300 bg-amber-50 px-2 py-1 text-micro text-amber-900">
          <span className="font-semibold">Caution acknowledged: </span>
          {exercise.caution_note}
        </p>
      )}
    </li>
  )
}

/** One collapsible provenance panel. Closed by default; the plan reads first. */
function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-t border-soft">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3.5 py-2 text-meta font-medium text-dim hover:text-ink"
      >
        {title}
        <span className="text-micro text-faint">{open ? "hide" : "show"}</span>
      </button>
      {open && <div className="px-3.5 pb-2.5">{children}</div>}
    </div>
  )
}

const CAUSE_LABEL: Record<string, string> = {
  blocked: "Blocked by the clinical envelope",
  avoided: "Excluded by a coach directive",
  disliked: "Disliked by the member",
}

function Exclusions({ exclusions }: { exclusions: ExclusionRecord[] }) {
  const groups = new Map<string, ExclusionRecord[]>()
  for (const record of exclusions) {
    groups.set(record.cause, [...(groups.get(record.cause) ?? []), record])
  }
  return (
    <div className="flex flex-col gap-2">
      {[...groups.entries()].map(([cause, records]) => (
        <div key={cause}>
          <p className="text-micro font-semibold text-dim">
            {CAUSE_LABEL[cause] ?? cause} · {records.length}
          </p>
          <ul className="mt-0.5 flex flex-col gap-0.5">
            {records.map((record, i) => (
              <li key={`${record.concept_id}-${i}`} className="text-micro text-faint">
                <span className="text-dim">{conceptName(record.concept_id)}</span>
                {record.reason && <> — {record.reason}</>}
                {record.evidence && (
                  <span className="mt-0.5 block font-mono text-[11px] text-faint">
                    {record.evidence}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
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
        placeholder="Adjust it — “make it 30 minutes”, “drop the lunges”"
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
  response,
  onAdjust,
  adjusting,
}: {
  response: PlanResponse
  onAdjust: (prompt: string) => void
  adjusting: boolean
}) {
  const { plan, provenance } = response
  const facts = response.exercise_facts ?? {}
  const hasFacts = Object.keys(facts).length > 0

  return (
    <section className="rounded-[4px] border border-line bg-card">
      <header className="border-b border-soft px-3.5 py-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="disp text-title">{plan.title}</h2>
          <span className="num whitespace-nowrap text-lead">
            {minutes(plan.total_seconds)}
            <small className="text-micro font-medium text-dim">
              {" "}
              / {response.duration_min} min asked
            </small>
          </span>
        </div>
        <p className="mt-0.5 flex items-baseline gap-2 text-micro text-faint">
          <span className="min-w-0 truncate">“{response.prompt}”</span>
          <Link
            to={`/traces?run=${response.run_id}`}
            className="ml-auto shrink-0 whitespace-nowrap underline underline-offset-2 hover:text-cobalt"
          >
            How this was built
          </Link>
        </p>
      </header>

      {hasFacts && (
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-soft px-3.5 py-1.5 text-micro text-faint">
          <span className="font-semibold uppercase tracking-wide">Legend</span>
          <span className="flex items-center gap-1">
            <Mark verdict={Verdict.CAUTION} /> caution
          </span>
          <Tag tone="focus">coach’s ask</Tag>
          <Tag tone="goal">goal muscle</Tag>
          <Tag tone="muscle">muscle</Tag>
          <Tag tone="equipment">equipment</Tag>
          <Tag tone="equipment" className="line-through">
            not owned
          </Tag>
        </div>
      )}

      {SECTIONS.map(([key, label]) =>
        plan[key].length > 0 ? (
          <div key={key}>
            <p className="bg-ground px-3.5 py-1 text-micro font-semibold uppercase tracking-wide text-faint">
              {label}
            </p>
            <ul>
              {plan[key].map((exercise) => (
                <Slot
                  key={exercise.concept_id}
                  exercise={exercise}
                  facts={facts[exercise.concept_id]}
                />
              ))}
            </ul>
          </div>
        ) : null,
      )}

      {plan.coach_notes && (
        <div className="border-t border-soft px-3.5 py-2.5">
          <p className="text-micro font-semibold uppercase tracking-wide text-faint">
            Notes for you
          </p>
          <p className="mt-1 whitespace-pre-wrap text-meta text-dim">{plan.coach_notes}</p>
        </div>
      )}

      {provenance.retrieval && provenance.retrieval.unmatched_requires.length > 0 && (
        <p className="border-t border-soft bg-red-wash px-3.5 py-2 text-micro text-red">
          Nothing eligible satisfies:{" "}
          {provenance.retrieval.unmatched_requires.map(conceptName).join(", ")}
        </p>
      )}

      {provenance.clinical.length > 0 && (
        <Panel title={`Clinical envelope · ${provenance.clinical.length} rules`}>
          <ul className="flex flex-col gap-1.5">
            {provenance.clinical.map((rule, i) => (
              <li key={i} className="text-micro">
                <span
                  className={cn(
                    "font-semibold uppercase",
                    rule.effect === "block" ? "text-red" : "text-dim",
                  )}
                >
                  {rule.effect}
                </span>{" "}
                <span className="text-dim">{conceptName(rule.target)}</span>
                <span className="block text-faint">{rule.reason}</span>
                <span className="block font-mono text-[11px] text-faint">{rule.evidence}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {provenance.retrieval && provenance.retrieval.exclusions.length > 0 && (
        <Panel
          title={`Left out · ${provenance.retrieval.exclusions.length} exclusions, ${provenance.retrieval.eligible_count} eligible`}
        >
          <Exclusions exclusions={provenance.retrieval.exclusions} />
        </Panel>
      )}

      {provenance.resolutions.length > 0 && (
        <Panel title={`Terms resolved · ${provenance.resolutions.length}`}>
          <ul className="flex flex-col gap-0.5">
            {provenance.resolutions.map((record, i) => (
              <li key={i} className="text-micro text-faint">
                “{record.query}” →{" "}
                {record.concept ? (
                  <span className="text-dim">
                    {conceptName(record.concept)}
                    {record.method && ` (${record.method})`}
                  </span>
                ) : (
                  <span>no match{record.alternatives.length > 0 && ", offered near-misses"}</span>
                )}
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <AdjustBar onAdjust={onAdjust} adjusting={adjusting} />
    </section>
  )
}
