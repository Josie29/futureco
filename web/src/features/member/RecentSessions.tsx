import { formatSessionDay } from "@/lib/dates"
import { cn } from "@/lib/utils"
import type { SessionRecord } from "@/types"

/**
 * Session history, newest first.
 *
 * Was a horizontal scroller of narrow cards: four columns of stacked text at
 * 6.75rem each, a gradient mask, and a fifth placeholder card for today. It
 * held less than this does and read as clutter. A plain aligned list puts the
 * dates in one column and the outcomes in another, so "she trained short and
 * skipped the long one" is legible at a glance — which is the whole reason a
 * coach looks at this before programming Thursday.
 */
export function RecentSessions({ sessions }: { sessions: SessionRecord[] }) {
  const done = sessions.filter((s) => s.completed).length
  const newestFirst = [...sessions].sort((a, b) => b.date.localeCompare(a.date))

  return (
    <section>
      <div className="mb-1.5 flex items-baseline gap-2">
        <h2 className="text-meta font-bold -tracking-[0.005em]">Previous sessions</h2>
        <span className="ml-auto text-micro whitespace-nowrap text-faint">
          {done} of {sessions.length} completed
        </span>
      </div>

      <ul>
        {newestFirst.map((session) => (
          <li
            key={session.date}
            className="grid grid-cols-[5.5rem_minmax(0,1fr)_auto] items-baseline gap-3 border-t border-line py-1.5 first:border-t-0"
          >
            <span className="text-micro whitespace-nowrap text-faint">
              {formatSessionDay(session.date)}
            </span>

            <span
              className={cn(
                "truncate text-meta font-semibold -tracking-[0.01em]",
                !session.completed && "text-dim",
              )}
            >
              {session.title}
            </span>

            <span
              className={cn(
                "text-micro whitespace-nowrap",
                session.completed ? "text-dim" : "font-semibold text-red",
              )}
            >
              {session.completed ? (
                <>
                  <span className="num text-meta text-ink">{session.duration_min}</span> min
                  {session.rpe !== null && ` · RPE ${session.rpe}`}
                </>
              ) : (
                "skipped"
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
