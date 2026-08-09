/**
 * The date the sample dataset is written against.
 *
 * A fallback, not the source of truth. The API serves `as_of` on the member
 * payload and `setReferenceDate` overwrites this — the server derives it from
 * the record, and two hardcoded dates in two languages is how they drift.
 * Kept as a literal so the first paint, and the generator mock that still
 * imports it, have something sane before any member has loaded.
 */
export const TODAY = "2026-06-04"

let referenceDate = TODAY

/**
 * Anchor relative formatting to the dataset's own "today".
 *
 * Display only. Anything a coach acts on — days to a goal, sessions this week,
 * churn — is computed server-side against the same date, so this cannot pull a
 * decision out of step with the record; the worst it can do is label a
 * timestamp "yesterday" when the member view has yet to load.
 *
 * @param iso A `YYYY-MM-DD` date, from `MemberContext.as_of`.
 */
export function setReferenceDate(iso: string): void {
  referenceDate = iso
}

/** The date currently being treated as "today". */
export function today(): string {
  return referenceDate
}

/**
 * Parse a date-only string (`YYYY-MM-DD`) as local midnight.
 *
 * `new Date("2026-05-27")` is specified to parse as UTC midnight, which then
 * renders as the previous day for any viewer west of Greenwich. Every date in
 * the member fixture is a calendar date with no time component, so local is
 * the correct reading.
 *
 * @param iso A `YYYY-MM-DD` string.
 * @returns A Date at local midnight on that calendar day.
 * @throws RangeError if the string is not a valid `YYYY-MM-DD` date.
 */
export function parseCalendarDate(iso: string): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!match) {
    throw new RangeError(`Expected a YYYY-MM-DD date, received "${iso}"`)
  }
  const [, year, month, day] = match
  return new Date(Number(year), Number(month) - 1, Number(day))
}

/**
 * Whole days between two calendar dates.
 *
 * @param iso Target date, `YYYY-MM-DD`.
 * @param from Reference date, defaulting to the dataset's "today".
 * @returns Days remaining; negative once the target has passed.
 */
export function daysUntil(iso: string, from: string = referenceDate): number {
  const ms = parseCalendarDate(iso).getTime() - parseCalendarDate(from).getTime()
  return Math.round(ms / 86_400_000)
}

/** "Wed 27 May" — the form used on session cards. */
export function formatSessionDay(iso: string): string {
  return parseCalendarDate(iso).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  })
}

/** "Wed" — the roster's last-session shorthand. */
export function formatWeekday(iso: string): string {
  return parseCalendarDate(iso).toLocaleDateString(undefined, { weekday: "short" })
}

/** "15 Jul" — goal target dates. */
export function formatShortDate(iso: string): string {
  return parseCalendarDate(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  })
}

/**
 * Format a full timestamp for chat.
 *
 * Chat timestamps carry a time and an offset, so they parse correctly with the
 * built-in constructor — unlike the calendar dates above.
 *
 * @param ts An ISO 8601 timestamp with time and offset.
 * @returns "6:42 PM" today, "yesterday, 6:42 PM", otherwise "22 May".
 */
export function formatMessageTime(ts: string): string {
  const then = new Date(ts)
  const time = then.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  })

  const startOfToday = parseCalendarDate(referenceDate)
  const startOfThen = new Date(then)
  startOfThen.setHours(0, 0, 0, 0)

  const days = Math.round(
    (startOfToday.getTime() - startOfThen.getTime()) / 86_400_000,
  )

  if (days <= 0) return time
  if (days === 1) return `yesterday, ${time}`
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" })
}
