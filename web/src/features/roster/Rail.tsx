import { Chip } from "@/components/Chip"
import { formatWeekday } from "@/lib/dates"
import { cn } from "@/lib/utils"
import type { RosterEntry } from "@/types"

/** Sort so the member who needs attention is first, not the alphabetical one. */
function byAttention(a: RosterEntry, b: RosterEntry): number {
  const risk = (m: RosterEntry) => (m.churn_risk === "low" || !m.churn_risk ? 0 : 1)
  const injured = (m: RosterEntry) => (m.injury_label ? 1 : 0)
  const score = (m: RosterEntry) => risk(m) * 2 + injured(m)
  return score(b) - score(a) || (a.adherence_pct ?? 100) - (b.adherence_pct ?? 100)
}

export function Rail({
  members,
  activeId,
  onSelect,
}: {
  members: RosterEntry[]
  activeId: string
  onSelect: (id: string) => void
}) {
  return (
    <nav
      aria-label="Members"
      className="flex w-60 shrink-0 flex-col gap-2 border-r border-rule bg-plate py-3"
    >
      <div className="eyebrow flex justify-between px-3">
        <span>Members</span>
        <span>{members.length}</span>
      </div>

      <ul className="flex flex-col">
        {[...members].sort(byAttention).map((m) => {
          const active = m.id === activeId
          return (
            <li key={m.id}>
              <button
                type="button"
                onClick={() => onSelect(m.id)}
                aria-current={active ? "true" : undefined}
                className={cn(
                  "flex w-full flex-col gap-0.5 border-l-2 px-3 py-2 text-left",
                  active
                    ? "border-l-ink bg-film"
                    : "border-l-transparent hover:bg-film/60",
                )}
              >
                <span className="font-medium">{m.name}</span>
                <span className="font-mono text-[10px] text-slate-soft">
                  {m.last_session_on ? formatWeekday(m.last_session_on) : "no sessions"}
                  {m.adherence_pct !== null && ` · ${m.adherence_pct}%`}
                </span>
                {(m.injury_label || m.churn_risk === "elevated") && (
                  <span className="mt-0.5 flex flex-wrap gap-1">
                    {m.injury_label && <Chip tone="alert">{m.injury_label}</Chip>}
                    {m.churn_risk === "elevated" && <Chip tone="alert">risk</Chip>}
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
