import { formatWeekday } from "@/lib/dates"
import { cn } from "@/lib/utils"
import type { RosterEntry } from "@/types"

/** Attention first, then lowest adherence. Not alphabetical. */
function byAttention(a: RosterEntry, b: RosterEntry): number {
  if (a.needs_attention !== b.needs_attention) return a.needs_attention ? -1 : 1
  return (a.adherence_pct ?? 100) - (b.adherence_pct ?? 100)
}

/**
 * The roster. Near-black against the light workspace, which gives the app a
 * composition rather than one flat plane — and makes the active member's
 * cobalt spine unmissable at any scroll position.
 */
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
      className="flex w-50 shrink-0 flex-col gap-0.5 bg-rail py-3.5 text-[#f2f2f0]"
    >
      <div className="flex items-baseline justify-between px-3.5 pb-2.5">
        <span className="disp text-[0.9375rem]">Members</span>
        <span className="font-mono text-[0.625rem] text-rail-dim">{members.length}</span>
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
                  "grid w-full grid-cols-[1.75rem_minmax(0,1fr)] items-center gap-2 border-l-2 px-3.5 py-2 text-left",
                  active
                    ? "border-l-cobalt bg-rail-active"
                    : "border-l-transparent hover:bg-rail-hover",
                )}
              >
                <span
                  className={cn(
                    "grid size-7 place-items-center rounded-[4px] text-[0.625rem]",
                    active ? "bg-cobalt text-white" : "bg-rail-chip text-[#d6d6da]",
                  )}
                >
                  {m.initials}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[0.8125rem] font-semibold -tracking-[0.01em]">
                    {m.name}
                  </span>
                  <span className="flex items-center gap-1.5 font-mono text-[0.5938rem] text-rail-dim">
                    {m.needs_attention && (
                      <i aria-hidden className="size-[5px] shrink-0 rounded-full bg-red" />
                    )}
                    {m.injury_label ??
                      (m.last_session_on ? formatWeekday(m.last_session_on) : "no sessions")}
                    {m.adherence_pct !== null && ` · ${m.adherence_pct}%`}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
