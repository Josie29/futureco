import { describe, expect, it } from "vitest"
import { itemId } from "@/api/fixtures"
import { computeEligibility } from "@/api/mock/catalogue"
import { buildPlan } from "@/api/mock/plans"
import { traceForPlan } from "@/api/mock/traces"
import { renderPath } from "@/lib/provenance"
import { ConstraintKind, FilterCause, RelType, SpanStatus } from "@/types"

/**
 * These test the **mock**, not the system.
 *
 * They exist for one reason: the numbers the console prints must agree with
 * each other, or a reviewer reads a contradiction and stops trusting the
 * screen. Real coverage of the resolver and the safety filter belongs with the
 * backend implementation (ASSESSMENT.md:73) — see `docs/mock-notes.md`.
 */

const base = { duration_min: 50, disabled: [] as string[] }

describe("mock consistency", () => {
  it("accounts for every catalogue entry exactly once", () => {
    // Breaks: the builder says 18 of 50 fit her and the plan sheet says five
    // movements didn't make it, leaving 27 unexplained.
    const pool = computeEligibility()
    const dropped = Object.values(pool.excluded_by).reduce((a, b) => a + b, 0)
    expect(pool.total).toBe(50)
    expect(pool.available + dropped).toBe(pool.total)
  })

  it("keeps the plan funnel reconciled with the eligibility panel", () => {
    // Breaks: the funnel's second step stops matching the count the coach saw
    // before pressing Build.
    const pool = computeEligibility()
    for (const prompt of ["Lower body, easy on the knee", "No barbell", "Anything"]) {
      const plan = buildPlan({ ...base, prompt })
      expect(plan.trace.eligible).toBe(pool.available)
      expect(plan.trace.catalogue_total).toBe(pool.total)
      expect(plan.trace.prescribed).toBe(plan.exercises.length)
      // A movement is never reported as dropped twice.
      const ids = plan.trace.filtered.map((f) => f.id)
      expect(ids.length).toBe(new Set(ids).size)
    }
  })

  it("never prescribes something it also reports as filtered", () => {
    // Breaks: the sheet lists a movement in the session and in the dropped
    // list at the same time.
    for (const prompt of ["Lower body, her knee is sore", "No barbell", "Anything"]) {
      const plan = buildPlan({ ...base, prompt })
      const dropped = new Set(plan.trace.filtered.map((f) => f.id))
      for (const exercise of plan.exercises) expect(dropped.has(exercise.id)).toBe(false)
    }
  })

  it("refuses to switch an injury off", () => {
    // Breaks: the one rule the UI locks becomes reachable, and the mock stops
    // demonstrating the guarantee the real API has to make.
    const off = computeEligibility([itemId(ConstraintKind.INJURIES, "left knee")])
    expect(off.excluded_by[FilterCause.INJURY]).toBe(6)
    expect(off.available).toBe(18)
  })

  it("narrows the pool when a piece of equipment is switched off", () => {
    // Breaks: the per-item toggles stop doing anything visible, which is how
    // the old whole-category text links read.
    const withBench = computeEligibility()
    const withoutBench = computeEligibility([itemId(ConstraintKind.EQUIPMENT, "Flat Bench")])
    expect(withoutBench.available).toBeLessThan(withBench.available)
    expect(withoutBench.excluded_by[FilterCause.EQUIPMENT]).toBeGreaterThan(
      withBench.excluded_by[FilterCause.EQUIPMENT],
    )
  })

  it("reaches every state the plan sheet can render", () => {
    // Breaks: a UI surface — the caution mark, the unresolved panel, the
    // substitution note — becomes unreachable from any prompt, so nobody
    // notices when it regresses.
    const injury = buildPlan({ ...base, prompt: "Lower body, her left knee is bothering her" })
    expect(injury.trace.resolved.some((c) => c.side === "left")).toBe(true)
    expect(injury.trace.filtered.some((f) => f.cause === FilterCause.INJURY)).toBe(true)

    const excluded = buildPlan({ ...base, prompt: "Glutes, exclude deadlifts" })
    expect(excluded.trace.unresolved).toHaveLength(1)
    expect(excluded.exercises.some((e) => e.note?.includes("Caution") || e.verdict === "caution")).toBe(true)

    const equipment = buildPlan({ ...base, prompt: "Upper body, no barbell — dumbbells only" })
    expect(equipment.exercises.some((e) => e.note?.includes("Stands in for"))).toBe(true)
  })

  it("reports the same numbers in the trace tab as on the plan sheet", () => {
    // Breaks: the observability tab starts telling a different story about the
    // same run than the sheet the coach acted on — the one thing a tracing
    // surface cannot afford to do.
    const plan = buildPlan({ ...base, prompt: "Lower body, her left knee is bothering her" })
    const trace = traceForPlan(plan)

    expect(trace.run_id).toBe(plan.run_id)
    expect(trace.totals.graph_queries).toBeGreaterThan(0)

    const injuries = plan.trace.filtered.filter((f) => f.cause === FilterCause.INJURY).length
    const span = trace.spans.find((s) => s.name === "Apply contraindications")
    expect(span?.rows_returned).toBe(injuries)

    const assemble = trace.spans.find((s) => s.name === "assemble_session")
    expect(assemble?.attributes.find((a) => a.label === "prescribed")?.value).toBe(
      `${plan.exercises.length}`,
    )
  })

  it("carries every per-exercise justification into the trace", () => {
    // Breaks: `why[].path` is returned by the API and rendered nowhere, so the
    // graph path half of ASSESSMENT.md:33 exists only in a payload no one sees.
    const plan = buildPlan({ ...base, prompt: "Glutes, exclude deadlifts" })
    const trace = traceForPlan(plan)
    const assemble = trace.spans.find((s) => s.name === "assemble_session")

    for (const exercise of plan.exercises) {
      // Never empty: every prescribed movement owes the coach at least the
      // safety claim, which is what stops a clear off-goal movement rendering
      // a "Why this one?" that opens onto nothing.
      expect(exercise.why.length).toBeGreaterThan(0)

      for (const reason of exercise.why) {
        expect(
          assemble?.attributes.some(
            (a) => a.label === exercise.name && a.value === renderPath(reason.path),
          ),
        ).toBe(true)
      }
    }
  })

  it("carries the traversal that removed each movement into the trace", () => {
    // Breaks: the safety half of ASSESSMENT.md:33 loses its edge walk — the
    // console says "not safe with her injury" and nothing anywhere says why.
    const plan = buildPlan({ ...base, prompt: "Full body" })
    const trace = traceForPlan(plan)
    const span = trace.spans.find((s) => s.name === "Apply contraindications")
    const dropped = plan.trace.filtered.filter((f) => f.cause === FilterCause.INJURY)

    expect(dropped.length).toBeGreaterThan(0)
    // Asserts the edge type rather than a substring of a rendered string, which
    // is the point of the path being structured: a rename of the relationship
    // now fails here instead of silently passing on stale prose.
    expect(
      dropped.every((f) => f.path.hops.some((h) => h.rel === RelType.CONTRAINDICATES)),
    ).toBe(true)
    expect(span?.attributes.some((a) => a.label === dropped[0].name)).toBe(true)
  })

  it("marks a run degraded when the resolver declined a phrase", () => {
    // Breaks: a run that quietly failed to act on part of the request looks
    // identical to a clean one in the run list.
    const declined = traceForPlan(buildPlan({ ...base, prompt: "Glutes, exclude deadlifts" }))
    expect(declined.status).toBe(SpanStatus.DEGRADED)

    const clean = traceForPlan(buildPlan({ ...base, prompt: "Upper body, no barbell" }))
    expect(clean.status).toBe(SpanStatus.OK)
  })

  it("produces the same run twice for the same request", () => {
    // Breaks: a coach can't reproduce a plan they're asked to defend.
    const a = buildPlan({ ...base, prompt: "Lower body" })
    const b = buildPlan({ ...base, prompt: "Lower body" })
    expect(a.run_id).toBe(b.run_id)
  })
})
