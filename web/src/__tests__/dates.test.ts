import { describe, expect, it } from "vitest"
import { daysUntil, parseCalendarDate } from "@/lib/dates"

/**
 * Calendar dates are the quiet correctness risk in this app: every date in the
 * fixture is date-only, and the built-in Date constructor reads those as UTC.
 */

describe("parseCalendarDate", () => {
  it("reads a date-only string as local midnight", () => {
    // Breaks: `new Date("2026-05-27")` parses as UTC midnight, so every date in
    // the app renders a day early for any viewer west of Greenwich — session
    // cards, goal deadlines, adherence weeks, all off by one.
    const date = parseCalendarDate("2026-05-27")
    expect(date.getFullYear()).toBe(2026)
    expect(date.getMonth()).toBe(4)
    expect(date.getDate()).toBe(27)
    expect(date.getHours()).toBe(0)
  })

  it("rejects anything that is not YYYY-MM-DD", () => {
    // Breaks: a malformed date silently becomes Invalid Date and renders as
    // "NaN days" rather than failing where it can be found.
    expect(() => parseCalendarDate("27/05/2026")).toThrow(RangeError)
    expect(() => parseCalendarDate("")).toThrow(RangeError)
  })
})

describe("daysUntil", () => {
  it("counts whole days forward and back", () => {
    // Breaks: goal countdowns drift, and the urgency colouring with them.
    expect(daysUntil("2026-06-14", "2026-06-04")).toBe(10)
    expect(daysUntil("2026-06-01", "2026-06-04")).toBe(-3)
  })

  it("is unaffected by daylight saving transitions", () => {
    // Breaks: a span crossing a DST boundary is 23 or 25 hours, so naive
    // division lands on 9.96 days and rounds wrong.
    expect(daysUntil("2026-11-05", "2026-10-29")).toBe(7)
    expect(daysUntil("2026-03-12", "2026-03-05")).toBe(7)
  })
})
