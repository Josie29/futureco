import { formatSessionDay } from "@/lib/dates"
import { cn } from "@/lib/utils"
import type { SessionRecord } from "@/types"

/**
 * The last four sessions. You can't program Thursday without knowing what
 * Tuesday was — and the skipped session rendered in carmine is where the churn
 * story stops being a chip and becomes a fact.
 */
export function RecentSessions({ sessions }: { sessions: SessionRecord[] }) {
  const recent = sessions.slice(-4)
  const done = recent.filter((s) => s.completed).length

  return (
    <section className="flex flex-col gap-1">
      <div className="eyebrow flex justify-between">
        <span>Last {recent.length} sessions</span>
        <span>
          {done} of {recent.length} completed
        </span>
      </div>

      <ul className="flex gap-1">
        {recent.map((s) => (
          <li
            key={s.date}
            className={cn(
              "flex min-w-0 flex-1 flex-col gap-px rounded-[3px] border p-2",
              s.completed ? "border-rule bg-film" : "border-carmine bg-carmine-tint",
            )}
          >
            <span className="eyebrow">{formatSessionDay(s.date)}</span>
            <span className="truncate text-[11px] font-medium">{s.title}</span>
            <span
              className={cn(
                "font-mono text-[10px]",
                s.completed ? "text-slate" : "text-carmine",
              )}
            >
              {s.completed ? `${s.duration_min} min · RPE ${s.rpe}` : "skipped"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
