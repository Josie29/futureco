import { useMemo, useState } from "react"
import { computeEligibility } from "@/api/mock"
import { abbreviateEquipment } from "@/components/Chip"
import { Mark } from "@/components/Mark"
import { cn } from "@/lib/utils"
import { LiftableRule, Verdict, type MemberContext, type PlanRequest } from "@/types"

/** Mean of the completed sessions, used for the duration reality check. */
function meanCompletedMinutes(member: MemberContext): number | null {
  const done = member.recent_sessions.filter((s) => s.completed)
  if (done.length === 0) return null
  return Math.round(done.reduce((n, s) => n + s.duration_min, 0) / done.length)
}

function RuleRow({
  label,
  detail,
  locked = false,
  on,
  onToggle,
}: {
  label: string
  detail: string
  locked?: boolean
  on: boolean
  onToggle?: () => void
}) {
  return (
    <div className="grid grid-cols-[1rem_1fr_auto] items-center gap-2 border-t border-rule-soft py-1 first:border-t-0">
      <span className="flex justify-center">
        {locked ? (
          <Mark verdict={Verdict.EXCLUDED} />
        ) : (
          <span aria-hidden className="font-mono text-slate-soft">
            ▤
          </span>
        )}
      </span>

      <span className="min-w-0 text-[11px]">
        <span className={cn(locked && "font-semibold text-carmine")}>{label}</span>
        <span className="block font-mono text-[10px] text-slate-soft">{detail}</span>
      </span>

      {locked ? (
        <span className="rounded-full border border-carmine bg-carmine-tint px-1.5 py-px font-mono text-[9px] uppercase tracking-wider text-carmine">
          Always on
        </span>
      ) : (
        <button
          type="button"
          onClick={onToggle}
          aria-pressed={on}
          className={cn(
            "rounded-full border px-1.5 py-px font-mono text-[9px] uppercase tracking-wider",
            on ? "border-ink bg-ink text-film" : "border-rule text-slate-soft",
          )}
        >
          {on ? "On" : "Off"}
        </button>
      )}
    </div>
  )
}

/**
 * The builder: what the system already knows, an unfenced prompt, and a length.
 *
 * The focus toggles from an earlier pass were cut deliberately — pre-resolved
 * chips would route the most common request shape around the three-pass
 * resolver, which is the thing being assessed. See docs/frontend-spec.md.
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
  const [minutes, setMinutes] = useState(member.preferences.preferred_session_minutes)
  const [lifted, setLifted] = useState<LiftableRule[]>([])

  const injury = member.injuries[0]
  const eligibility = useMemo(() => computeEligibility(lifted), [lifted])
  const typicalMinutes = meanCompletedMinutes(member)
  const completed = member.recent_sessions.filter((s) => s.completed)

  const toggle = (rule: LiftableRule) =>
    setLifted((prev) =>
      prev.includes(rule) ? prev.filter((r) => r !== rule) : [...prev, rule],
    )

  const isOn = (rule: LiftableRule) => !lifted.includes(rule)

  const submit = () => {
    if (!prompt.trim() || building) return
    onBuild({ prompt: prompt.trim(), duration_min: minutes, lifted_rules: lifted })
  }

  const availablePct = (eligibility.available / eligibility.total) * 100

  return (
    <section className="flex flex-col overflow-hidden rounded-md border border-rule bg-film">
      <div className="flex flex-col gap-2 p-3">
        <div className="eyebrow">Applied from {member.name.split(" ")[0]}'s profile</div>

        {injury && (
          <RuleRow
            locked
            on
            label={`${injury.region} · ${injury.status} · ${injury.severity}`}
            detail="excludes plyometric · cautions loaded knee flexion"
          />
        )}
        <RuleRow
          label={`Her equipment — ${member.equipment_available.length} items`}
          detail={member.equipment_available.map(abbreviateEquipment).join(" · ")}
          on={isOn(LiftableRule.EQUIPMENT)}
          onToggle={() => toggle(LiftableRule.EQUIPMENT)}
        />
        <RuleRow
          label="Dislikes"
          detail={member.preferences.dislikes.join(" · ")}
          on={isOn(LiftableRule.DISLIKES)}
          onToggle={() => toggle(LiftableRule.DISLIKES)}
        />
        <RuleRow
          label="Goal targets"
          detail={[...new Set(member.goals.flatMap((g) => g.targets))].join(" · ")}
          on={isOn(LiftableRule.GOALS)}
          onToggle={() => toggle(LiftableRule.GOALS)}
        />
      </div>

      <div className="flex flex-col gap-2 border-t border-rule-soft p-3">
        <label htmlFor="prompt" className="eyebrow flex justify-between">
          <span>What are we training?</span>
          <span className="normal-case tracking-normal">⌘↵ to build</span>
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
          className="resize-none rounded-[3px] border border-ink bg-film px-3 py-2 text-[11px] leading-relaxed placeholder:text-slate-soft"
        />
      </div>

      <div className="flex flex-col gap-2 border-t border-rule-soft p-3">
        <label htmlFor="minutes" className="eyebrow">
          Length
        </label>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] text-slate-soft">20</span>
          <input
            id="minutes"
            type="range"
            min={20}
            max={90}
            step={5}
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
            className="h-1 flex-1 accent-ink"
          />
          <span className="font-mono text-[10px] text-slate-soft">90</span>
          <span className="w-14 text-right font-mono text-xs">{minutes} min</span>
        </div>
        {typicalMinutes !== null && completed.length >= 2 && (
          <p className="font-mono text-[10px] text-carmine">
            her preference is {member.preferences.preferred_session_minutes} · her last{" "}
            {completed.length} ran {completed.map((s) => s.duration_min).join(", ")}
          </p>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-rule bg-plate p-3">
        <div className="flex flex-col gap-px">
          <span className="font-mono text-xs">
            <b className="font-semibold">{eligibility.available}</b> of {eligibility.total}{" "}
            available to {member.name.split(" ")[0]}
          </span>
          <span
            className="flex h-1 overflow-hidden rounded-full bg-sunk"
            aria-hidden
          >
            <span className="bg-ink" style={{ width: `${availablePct}%` }} />
            <span
              className="bg-carmine/55"
              style={{ width: `${100 - availablePct}%` }}
            />
          </span>
          <span className="font-mono text-[10px] text-slate-soft">
            {eligibility.excluded_by.equipment} equipment ·{" "}
            {eligibility.excluded_by.injury} contraindicated
          </span>
        </div>

        <button
          type="button"
          onClick={submit}
          disabled={!prompt.trim() || building}
          className="rounded-[3px] bg-ink px-3 py-1.5 text-[11px] font-semibold text-film disabled:opacity-40"
        >
          {building ? "Building…" : "Build session"}
        </button>
      </div>
    </section>
  )
}
