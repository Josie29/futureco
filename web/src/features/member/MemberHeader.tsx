import { cn } from "@/lib/utils"
import type { MemberContext } from "@/types"

/** Weekly completion, drawn inline. Recharts is reserved for copilot charts. */
function AdherenceSpark({ points }: { points: number[] }) {
  if (points.length < 2) return null
  const w = 44
  const h = 14
  const max = Math.max(...points, 100)
  const step = w / (points.length - 1)
  const y = (v: number) => h - 3 - (v / max) * (h - 6)
  const d = points.map((v, i) => `${i === 0 ? "M" : "L"}${i * step} ${y(v)}`).join(" ")

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="block h-3.5 w-11 shrink-0 text-red"
      preserveAspectRatio="none"
      role="img"
      aria-label={`Weekly completion: ${points.join("%, ")}%`}
    >
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />
      <circle cx={(points.length - 1) * step} cy={y(points.at(-1)!)} r={1.6} fill="currentColor" />
    </svg>
  )
}

function Metric({
  label,
  note,
  alert = false,
  children,
}: {
  label: string
  note: string
  alert?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="flex min-w-0 flex-col gap-px px-4 first:pl-0 not-first:border-l not-first:border-line">
      <span className="text-[0.625rem] whitespace-nowrap text-faint">{label}</span>
      <span className={cn("text-base leading-tight whitespace-nowrap", alert && "text-red")}>
        {children}
      </span>
      <span className={cn("text-[0.625rem] whitespace-nowrap text-faint", alert && "text-red")}>
        {note}
      </span>
    </div>
  )
}

/**
 * The member intro. The metric strip carries the four things a coach opens
 * with — and deliberately no boxes: white is reserved for surfaces you act on.
 */
export function MemberHeader({ member }: { member: MemberContext }) {
  const injury = member.injuries[0]
  const adherence = member.adherence_pct
  const latest = adherence.at(-1)
  const first = adherence[0]

  return (
    <header>
      <div className="flex items-center gap-3">
        <span className="disp grid size-10 shrink-0 place-items-center rounded-[4px] bg-cobalt text-sm text-white">
          {member.initials}
        </span>
        <div>
          <h1 className="disp text-2xl leading-tight">{member.name}</h1>
          <p className="mt-px text-xs text-dim">
            {member.age} · {member.tier} · trains at {member.trains_at}
          </p>
        </div>
      </div>

      <div className="mt-2 flex items-stretch">
        {injury && (
          <Metric label="Injury" note={`${injury.status} · ${injury.severity}`} alert>
            <span className="disp text-[0.9375rem]">
              {injury.region[0].toUpperCase() + injury.region.slice(1)}
            </span>
          </Metric>
        )}

        <Metric label="Adherence" note={first !== undefined ? `down from ${first}` : ""}>
          <span className="flex items-center gap-1.5">
            <span className="num text-red">
              {latest}
              <small className="text-[0.6875rem] font-medium text-dim">%</small>
            </span>
            <AdherenceSpark points={adherence} />
          </span>
        </Metric>

        <Metric label="This week" note="sessions done">
          <span className="num">
            {member.sessions_done_this_week}
            <small className="text-[0.6875rem] font-medium text-dim">
              {" "}
              / {member.sessions_planned_this_week}
            </small>
          </span>
        </Metric>

        {member.typical_session_min !== null && (
          <Metric
            label="Typical session"
            note={`she asks for ${member.preferred_session_min}`}
          >
            <span className="num">
              {member.typical_session_min}
              <small className="text-[0.6875rem] font-medium text-dim"> min</small>
            </span>
          </Metric>
        )}
      </div>
    </header>
  )
}
