import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { getEligibility } from "@/api/client"
import { equipmentLabel } from "@/components/Tag"
import { cn } from "@/lib/utils"
import {
  ConstraintEffect,
  FilterCause,
  type Constraint,
  type MemberContext,
  type PlanRequest,
} from "@/types"

/**
 * The three at ASSESSMENT.md:27-31, plus two that exercise other paths. They
 * are here because the prompt is the only way to state intent, so a coach
 * meeting the console for the first time needs to see what it accepts.
 */
const EXAMPLES = [
  "Full-body session with isolation work around the pecs",
  "Lower body, but her left knee is bothering her",
  "Upper-body push and pull — no barbell, only dumbbells and a kettlebell",
  "Posterior chain and glutes, exclude deadlifts",
  "Low-impact conditioning and core, nothing with jumping",
] as const

/**
 * One switchable fact, as a real switch.
 *
 * A locked item still renders — a coach needs to see that the knee is being
 * accounted for — but it has no control, because there is no version of this
 * screen where switching an injury off is a thing a coach can do.
 */
function ItemToggle({
  label,
  effect,
  locked,
  on,
  onToggle,
}: {
  label: string
  effect: string
  locked: boolean
  on: boolean
  onToggle: () => void
}) {
  if (locked) {
    return (
      <span
        title={effect}
        className="inline-flex items-center gap-1.5 rounded-full border border-red bg-red-wash py-[0.1875rem] pr-2.5 pl-2 text-micro text-red"
      >
        <i aria-hidden className="size-1.5 rounded-full bg-red" />
        {label}
        <span className="text-micro opacity-70">always on</span>
      </span>
    )
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onToggle}
      title={effect}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border py-[0.1875rem] pr-2.5 pl-2 text-micro",
        on ? "border-ink text-ink" : "border-line text-faint line-through decoration-line",
      )}
    >
      <i
        aria-hidden
        className={cn(
          "size-1.5 rounded-full",
          on ? "bg-cobalt" : "border border-faint bg-transparent",
        )}
      />
      {label}
    </button>
  )
}

function ConstraintGroup({
  constraint,
  disabled,
  onToggle,
}: {
  constraint: Constraint
  disabled: string[]
  onToggle: (id: string) => void
}) {
  if (constraint.items.length === 0) return null

  return (
    <div>
      <div className="mb-1.5 flex items-baseline gap-2">
        <h3 className="text-micro font-semibold text-ink">{constraint.label}</h3>
        <p className="text-micro text-dim">{constraint.summary}</p>
        {/* Says up front whether switching anything here moves the count, so a
            ranking-only group doesn't read as a broken control. */}
        {constraint.effect === ConstraintEffect.RANKING && (
          <span className="ml-auto shrink-0 text-micro whitespace-nowrap text-faint">
            preference only
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {constraint.items.map((item) => (
          <ItemToggle
            key={item.id}
            label={equipmentLabel(item.label)}
            effect={item.effect}
            locked={item.locked}
            on={!disabled.includes(item.id)}
            onToggle={() => onToggle(item.id)}
          />
        ))}
      </div>
    </div>
  )
}

/**
 * The builder: what the system already knows, an unfenced prompt, and a length.
 *
 * Constraints render as fixed categories — Injuries, Equipment, Dislikes, Goal
 * targets — each mapping to something the member graph records. The labels
 * never change; the contents come from whoever is loaded, so a second dataset
 * fills them without a redesign.
 */
export function Builder({
  member,
  memberId,
  disabled,
  onDisabledChange,
  onBuild,
  building,
  hasPlan,
}: {
  member: MemberContext
  memberId: string
  /** Owned by the console: a later adjustment has to send these too. */
  disabled: string[]
  onDisabledChange: (next: string[]) => void
  onBuild: (request: PlanRequest) => void
  building: boolean
  hasPlan: boolean
}) {
  const [prompt, setPrompt] = useState("")
  const [minutes, setMinutes] = useState(member.preferred_session_min)

  const eligibility = useQuery({
    queryKey: ["eligibility", memberId, [...disabled].sort().join(",")],
    queryFn: () => getEligibility(memberId, disabled),
  })

  const toggle = (id: string) =>
    onDisabledChange(
      disabled.includes(id) ? disabled.filter((x) => x !== id) : [...disabled, id],
    )

  const submit = () => {
    if (!prompt.trim() || building) return
    onBuild({ prompt: prompt.trim(), duration_min: minutes, disabled })
  }

  const pool = eligibility.data
  const availablePct = pool ? (pool.available / pool.total) * 100 : 0

  return (
    <section className="flex flex-col overflow-hidden rounded-[4px] border border-line bg-card">
      <div className="flex flex-col gap-3 p-3">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-micro font-semibold text-dim">What's being applied</span>
          {disabled.length > 0 && (
            <button
              type="button"
              onClick={() => onDisabledChange([])}
              className="text-micro text-dim underline underline-offset-2 hover:text-ink"
            >
              Reset {disabled.length} change{disabled.length === 1 ? "" : "s"}
            </button>
          )}
        </div>

        {member.constraints.map((constraint) => (
          <ConstraintGroup
            key={constraint.kind}
            constraint={constraint}
            disabled={disabled}
            onToggle={toggle}
          />
        ))}
      </div>

      <div className="border-t border-soft p-3">
        <label htmlFor="prompt" className="mb-2 block text-micro font-semibold text-dim">
          What are we training?
        </label>
        <textarea
          id="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit()
          }}
          rows={2}
          placeholder="Full lower body, easy on the knee — she was sore after Tuesday"
          className="w-full resize-none rounded-[4px] border-[1.5px] border-ink bg-card px-2.5 py-2 text-body leading-relaxed placeholder:text-faint"
        />

        <div className="mt-2 flex flex-wrap gap-1">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setPrompt(example)}
              className="rounded-full border border-line px-2 py-0.5 text-micro text-dim hover:border-cobalt hover:text-cobalt"
            >
              {example}
            </button>
          ))}
        </div>
      </div>

      <div className="border-t border-soft p-3">
        <div className="mb-1.5 flex items-baseline justify-between">
          <label htmlFor="minutes" className="text-micro font-semibold text-dim">
            Length
          </label>
          <span className="num text-body">
            {minutes}
            <small className="text-micro font-medium text-dim"> min</small>
          </span>
        </div>
        <input
          id="minutes"
          type="range"
          min={20}
          max={90}
          step={5}
          value={minutes}
          onChange={(e) => setMinutes(Number(e.target.value))}
          className="h-1 w-full accent-ink"
        />
        {member.typical_session_min !== null && (
          <p className="mt-1 text-micro text-faint">
            Her completed sessions average {member.typical_session_min} min.
          </p>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-line bg-ground p-3">
        <span className="min-w-0">
          {pool ? (
            <>
              <span className="num text-lead">{pool.available}</span>
              <span className="text-micro text-dim">
                {" "}
                of {pool.total} movements suit her right now
              </span>
              <span aria-hidden className="mt-1 flex h-1 overflow-hidden rounded-full bg-soft">
                <i className="bg-cobalt" style={{ width: `${availablePct}%` }} />
                <i className="bg-red/55" style={{ width: `${100 - availablePct}%` }} />
              </span>
              <span className="mt-1 block text-micro text-faint">
                {pool.excluded_by[FilterCause.INJURY]} ruled out by her injury ·{" "}
                {pool.excluded_by[FilterCause.EQUIPMENT]} need equipment she hasn't got
              </span>
            </>
          ) : (
            <span className="text-micro text-faint">Counting what suits her…</span>
          )}
        </span>

        <button
          type="button"
          onClick={submit}
          disabled={!prompt.trim() || building}
          className="shrink-0 rounded-[4px] bg-ink px-3 py-1.5 text-meta font-semibold text-white disabled:opacity-40"
        >
          {building ? "Building…" : hasPlan ? "Rebuild session" : "Build session"}
        </button>
      </div>
    </section>
  )
}
