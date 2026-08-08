import { useMemo, useState } from "react"
import { computeEligibility } from "@/api/mock"
import { equipmentLabel } from "@/components/Tag"
import { cn } from "@/lib/utils"
import {
  ConstraintKind,
  type Constraint,
  type MemberContext,
  type PlanRequest,
} from "@/types"

/** Equipment items read better in program-sheet shorthand than title case. */
function itemLabel(kind: ConstraintKind, item: string): string {
  return kind === ConstraintKind.EQUIPMENT ? equipmentLabel(item) : item
}

function ConstraintDetail({
  constraint,
  lifted,
  onToggle,
}: {
  constraint: Constraint
  lifted: boolean
  onToggle: () => void
}) {
  return (
    <div
      className={cn(
        "mt-2 flex flex-col gap-1.5 border-l-2 pl-2.5",
        constraint.liftable ? "border-l-line" : "border-l-red",
      )}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-xs font-semibold">
          {constraint.items.length > 0
            ? constraint.items.map((i) => itemLabel(constraint.kind, i)).join(" · ")
            : `No ${constraint.label.toLowerCase()} on file`}
        </span>

        {constraint.liftable ? (
          <button
            type="button"
            onClick={onToggle}
            className="shrink-0 text-[0.625rem] whitespace-nowrap text-dim underline underline-offset-2 hover:text-ink"
          >
            {lifted ? "Apply again" : "Lift for this session"}
          </button>
        ) : (
          <span className="shrink-0 text-[0.625rem] whitespace-nowrap text-faint">
            can't be lifted
          </span>
        )}
      </div>

      <p className="text-[0.6875rem] text-dim">{constraint.effect}</p>
    </div>
  )
}

/**
 * The builder: what the system already knows, an unfenced prompt, and a length.
 *
 * Constraints render as fixed categories — Injuries, Equipment, Dislikes, Goal
 * targets — each mapping to an edge type in the member graph. The labels never
 * change; the counts and contents come from whoever is loaded, so a second
 * dataset fills them without a redesign.
 */
export function Builder({
  member,
  onBuild,
  building,
}: {
  member: MemberContext
  onBuild: (req: PlanRequest) => void
  building: boolean
}) {
  const [prompt, setPrompt] = useState("")
  const [minutes, setMinutes] = useState(member.preferred_session_min)
  const [lifted, setLifted] = useState<ConstraintKind[]>([])
  const [open, setOpen] = useState<ConstraintKind | null>(ConstraintKind.INJURIES)

  const eligibility = useMemo(() => computeEligibility(lifted), [lifted])
  const openConstraint = member.constraints.find((c) => c.kind === open) ?? null

  const toggleLift = (kind: ConstraintKind) =>
    setLifted((prev) =>
      prev.includes(kind) ? prev.filter((k) => k !== kind) : [...prev, kind],
    )

  const submit = () => {
    if (!prompt.trim() || building) return
    onBuild({ prompt: prompt.trim(), duration_min: minutes, lifted })
  }

  const availablePct = (eligibility.available / eligibility.total) * 100

  return (
    <section className="flex flex-col overflow-hidden rounded-[4px] border border-line bg-card">
      <div className="p-3">
        <span className="mb-2 block text-[0.6875rem] font-semibold text-dim">
          Applied from her profile
        </span>

        <div className="flex flex-wrap gap-1.5">
          {member.constraints.map((c) => {
            const isLifted = lifted.includes(c.kind)
            const isOpen = open === c.kind
            return (
              <button
                key={c.kind}
                type="button"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : c.kind)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border py-[0.1875rem] pr-2 pl-2.5 text-[0.6875rem]",
                  !c.liftable && "border-red bg-red-wash text-red",
                  c.liftable && isLifted && "border-line text-faint",
                  c.liftable && !isLifted && "border-line text-ink hover:border-ink",
                  isOpen && c.liftable && "border-ink bg-ground",
                )}
              >
                <i
                  aria-hidden
                  className={cn(
                    "size-1.5 rounded-full",
                    !c.liftable && "bg-red",
                    c.liftable && (isLifted ? "border border-faint" : "bg-ink"),
                  )}
                />
                {c.label}
                <span className="font-mono text-[0.5938rem] text-faint">{c.items.length}</span>
              </button>
            )
          })}
        </div>

        {openConstraint && (
          <ConstraintDetail
            constraint={openConstraint}
            lifted={lifted.includes(openConstraint.kind)}
            onToggle={() => toggleLift(openConstraint.kind)}
          />
        )}
      </div>

      <div className="border-t border-soft p-3">
        <label htmlFor="prompt" className="mb-2 block text-[0.6875rem] font-semibold text-dim">
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
          className="w-full resize-none rounded-[4px] border-[1.5px] border-ink bg-card px-2.5 py-2 text-[0.8125rem] leading-relaxed placeholder:text-faint"
        />
      </div>

      <div className="border-t border-soft p-3">
        <div className="mb-1.5 flex items-baseline justify-between">
          <label htmlFor="minutes" className="text-[0.6875rem] font-semibold text-dim">
            Length
          </label>
          <span className="num text-sm">
            {minutes}
            <small className="text-[0.6875rem] font-medium text-dim"> min</small>
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
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-line bg-ground p-3">
        <span>
          <span className="num text-[0.9375rem]">{eligibility.available}</span>
          <span className="text-[0.6875rem] text-dim">
            {" "}
            of {eligibility.total} movements fit her right now
          </span>
          <span aria-hidden className="mt-1 flex h-1 overflow-hidden rounded-full bg-soft">
            <i className="bg-cobalt" style={{ width: `${availablePct}%` }} />
            <i className="bg-red/55" style={{ width: `${100 - availablePct}%` }} />
          </span>
        </span>

        <button
          type="button"
          onClick={submit}
          disabled={!prompt.trim() || building}
          className="shrink-0 rounded-[4px] bg-ink px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
        >
          {building ? "Building…" : "Build session"}
        </button>
      </div>
    </section>
  )
}
