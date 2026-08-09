import { describe, expect, it } from "vitest"
import { formatMinutes } from "@/lib/utils"

/**
 * The console sums and subtracts durations the API has already rounded — a
 * block's exercises added together, the estimate taken off the requested
 * window — and binary floating point turned those into `2.9000000000000004
 * min` and `0.7000000000000028 spare` on the plan sheet. The values below are
 * the ones that actually shipped.
 */
describe("formatMinutes", () => {
  it("drops floating-point noise from summed durations", () => {
    expect(formatMinutes(2.9000000000000004)).toBe("2.9")
    expect(formatMinutes(50 - 49.3)).toBe("0.7")
  })

  it("renders a whole number without a decimal point", () => {
    // A 45-minute session reads "45", not "45.0".
    expect(formatMinutes(45)).toBe("45")
    expect(formatMinutes(0)).toBe("0")
  })

  it("keeps one decimal where it carries information", () => {
    expect(formatMinutes(49.3)).toBe("49.3")
    expect(formatMinutes(44.57)).toBe("44.6")
    // Not a .5 case: 44.55 is stored just below its decimal value, so it
    // rounds down. Session lengths are minutes to one place and nothing
    // depends on the tie, but the expectation is written to the behaviour
    // rather than to the arithmetic anyone would assume.
    expect(formatMinutes(44.55)).toBe("44.5")
  })
})
