import { Tag } from "@/components/Tag"
import { formatShortDate } from "@/lib/dates"
import { cn } from "@/lib/utils"
import type { Goal } from "@/types"

/** Nearest deadline first; undated goals sort last. */
function bySoonest(a: Goal, b: Goal): number {
  if (a.days_left === null) return 1
  if (b.days_left === null) return -1
  return a.days_left - b.days_left
}

const URGENT_DAYS = 60

/**
 * Goals, with the muscles they target lit in the same cobalt the plan uses.
 * Seeing `glutes` on a goal and again on three movements is the alignment
 * story told once rather than in a separate column.
 */
export function Goals({ goals }: { goals: Goal[] }) {
  const dated = goals.filter((g) => g.days_left !== null)
  const nextQuarter = dated.filter((g) => (g.days_left ?? 0) <= 120).length

  return (
    <section>
      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-xs font-bold -tracking-[0.005em]">Goals</h2>
        {nextQuarter > 0 && (
          <span className="ml-auto text-micro whitespace-nowrap text-faint">
            {nextQuarter} due within four months
          </span>
        )}
      </div>

      <ul>
        {[...goals].sort(bySoonest).map((g) => {
          const urgent =
            (g.days_left !== null && g.days_left <= URGENT_DAYS) || g.shortfall !== null

          return (
            <li
              key={g.id}
              className="grid grid-cols-[0.5rem_minmax(0,1fr)_auto] items-start gap-2 border-t border-line py-1.5 first:border-t-0"
            >
              <i
                aria-hidden
                className={cn(
                  "mt-[0.3125rem] size-[0.4375rem] rounded-full",
                  g.priority === 1 ? "bg-cobalt" : "border border-faint",
                )}
              />

              <div className="min-w-0">
                <p className="text-xs leading-snug font-semibold -tracking-[0.01em]">{g.text}</p>
                <div className="mt-1 flex flex-wrap gap-[0.1875rem]">
                  {g.targets.map((t) => (
                    <Tag key={t} tone="goal">
                      {t}
                    </Tag>
                  ))}
                  {g.measure && <Tag>{g.measure}</Tag>}
                </div>
              </div>

              <div
                className={cn(
                  "text-right font-mono text-micro leading-snug whitespace-nowrap",
                  urgent ? "text-red" : "text-dim",
                )}
              >
                {g.days_left !== null ? `${g.days_left} days` : (g.shortfall ?? "on track")}
                <span className="block text-micro text-faint">
                  {g.target_date ? formatShortDate(g.target_date) : "no date"}
                </span>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
