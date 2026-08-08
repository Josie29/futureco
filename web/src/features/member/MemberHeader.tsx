import { Chip, abbreviateEquipment } from "@/components/Chip"
import { formatTargetDate } from "@/lib/dates"
import type { MemberContext } from "@/types"

/**
 * Sparkline for weekly completion. Four points, drawn inline rather than pulled
 * through a chart library — the trend only has to read at a glance here, and
 * Recharts is reserved for the copilot's full charts.
 */
function AdherenceSpark({ points }: { points: number[] }) {
  if (points.length < 2) return null
  const w = 56
  const h = 16
  const max = Math.max(...points, 100)
  const step = w / (points.length - 1)
  const y = (v: number) => h - 2 - (v / max) * (h - 4)
  const d = points.map((v, i) => `${i === 0 ? "M" : "L"}${i * step} ${y(v)}`).join(" ")

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="block h-4 w-14 text-carmine"
      preserveAspectRatio="none"
      role="img"
      aria-label={`Weekly completion: ${points.join("%, ")}%`}
    >
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />
      <circle cx={(points.length - 1) * step} cy={y(points.at(-1)!)} r={1.8} fill="currentColor" />
    </svg>
  )
}

export function MemberHeader({ member }: { member: MemberContext }) {
  const injury = member.injuries[0]
  const adherence = member.adherence.weekly_completion_pct
  const latest = adherence.at(-1)?.pct
  const first = adherence[0]?.pct

  return (
    <header className="flex flex-col gap-2">
      <h1 className="expanded text-[1.375rem]">
        {member.name}{" "}
        <span className="text-sm font-normal text-slate-soft" style={{ fontStretch: "normal" }}>
          {member.age} · {member.tier}
        </span>
      </h1>

      <div className="flex flex-wrap items-center gap-1">
        {injury && (
          <Chip tone="alert">
            {injury.region} · {injury.status} · {injury.severity}
          </Chip>
        )}
        {member.equipment_available.map((e) => (
          <Chip key={e} title={e}>
            {abbreviateEquipment(e)}
          </Chip>
        ))}
      </div>

      <div className="flex items-start gap-6 border-t border-rule-soft pt-2">
        <div className="flex flex-col gap-px">
          <span className="eyebrow">Adherence</span>
          <span className="font-mono text-xs">
            {latest}%{" "}
            {first !== undefined && latest !== undefined && latest < first && (
              <span className="text-[10px] text-carmine">↓ from {first}</span>
            )}
          </span>
          <AdherenceSpark points={adherence.map((p) => p.pct)} />
        </div>

        <div className="flex min-w-0 flex-col gap-px">
          <span className="eyebrow">Goals</span>
          {member.goals.map((g) => (
            <span key={g.id} className="flex gap-2 text-[10px] text-slate">
              <span className="truncate">{g.text}</span>
              <span className="shrink-0 font-mono text-slate-soft">
                {g.target_date ? formatTargetDate(g.target_date) : "—"}
              </span>
            </span>
          ))}
        </div>
      </div>
    </header>
  )
}
