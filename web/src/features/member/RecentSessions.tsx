import { formatSessionDay } from "@/lib/dates"
import { cn } from "@/lib/utils"
import type { SessionRecord } from "@/types"

/**
 * Session history, scrolling horizontally so it extends past four without
 * eating the page. Border colour is the only signal and it carries meaning:
 * grey completed, red skipped, dashed cobalt for the one being built.
 */
export function RecentSessions({
  sessions,
  todayLabel,
  building,
}: {
  sessions: SessionRecord[]
  todayLabel: string
  building: boolean
}) {
  const done = sessions.filter((s) => s.completed).length

  return (
    <section>
      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-xs font-bold -tracking-[0.005em]">Previous sessions</h2>
        <span className="ml-auto text-[0.6875rem] whitespace-nowrap text-faint">
          {done} of {sessions.length} done
        </span>
      </div>

      {/* The fade tells a clipped card apart from a rendering error. */}
      <div className="relative min-w-0">
        <ul className="flex gap-3.5 overflow-x-auto pb-1">
          {sessions.map((s) => (
            <li
              key={s.date}
              className={cn(
                "flex w-27 shrink-0 flex-col gap-px border-l-2 pl-2",
                s.completed ? "border-l-line" : "border-l-red",
              )}
            >
              <span className="font-mono text-[0.5938rem] whitespace-nowrap text-faint">
                {formatSessionDay(s.date)}
              </span>
              <span className="truncate text-[0.6875rem] font-semibold -tracking-[0.01em]">
                {s.title}
              </span>
              <span
                className={cn(
                  "font-mono text-[0.5938rem] whitespace-nowrap",
                  s.completed ? "text-dim" : "text-red",
                )}
              >
                {s.completed ? `${s.duration_min} min · rpe ${s.rpe}` : "skipped"}
              </span>
            </li>
          ))}

          <li className="flex w-27 shrink-0 flex-col gap-px border-l-2 border-dashed border-l-cobalt pl-2">
            <span className="font-mono text-[0.5938rem] whitespace-nowrap text-faint">
              {todayLabel}
            </span>
            <span className="truncate text-[0.6875rem] font-semibold -tracking-[0.01em]">
              Today
            </span>
            <span className="font-mono text-[0.5938rem] whitespace-nowrap text-cobalt">
              {building ? "building" : "not built"}
            </span>
          </li>
        </ul>
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-linear-to-r from-transparent to-ground"
        />
      </div>
    </section>
  )
}
