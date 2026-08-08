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

/** "Tue, 27 May" — the form used on session cards. */
export function formatSessionDay(iso: string): string {
  return parseCalendarDate(iso).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  })
}

/** "Tue" — the roster's last-session shorthand. */
export function formatWeekday(iso: string): string {
  return parseCalendarDate(iso).toLocaleDateString(undefined, { weekday: "short" })
}

/** "1 Sep" — goal target dates. */
export function formatTargetDate(iso: string): string {
  return parseCalendarDate(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  })
}

/**
 * Format a full timestamp relative to now, for chat.
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

  const startOfToday = new Date()
  startOfToday.setHours(0, 0, 0, 0)
  const startOfThen = new Date(then)
  startOfThen.setHours(0, 0, 0, 0)

  const days = Math.round(
    (startOfToday.getTime() - startOfThen.getTime()) / 86_400_000,
  )

  if (days <= 0) return time
  if (days === 1) return `yesterday, ${time}`
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" })
}
