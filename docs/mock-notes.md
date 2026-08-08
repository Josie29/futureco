# The frontend mock, and what it is not

`web/src/api/mock/` is a stand-in for the API. It is **throwaway** — when the real endpoints land, the whole directory is deleted and `web/src/api/client.ts` swaps its function bodies for `fetch`. No component imports from `mock/`; they all go through `client.ts`, so nothing else moves.

Read this before assuming the mock tells you anything about how the system should work. It doesn't. It exists so the UI can be built and reviewed before the backend is ready.

## What it does

| File | Lines | Does |
|---|---|---|
| `mock/catalogue.ts` | ~100 | Two standing rules — contraindicated pattern, equipment she doesn't own — so the counts on screen add up |
| `mock/plans.ts` | ~330 | Four **authored** plans, matched on a keyword in the prompt |
| `mock/copilot.ts` | ~260 | Canned answers and chart payloads, every figure traced to `member-context.json` |
| `mock/traces.ts` | ~310 | Run traces for the Traces tab — span structure derived from the plan's own trace, durations and token counts authored |

The scenarios are keyed to the assessment's own examples, so a reviewer can drive each one from the prompt box:

| Prompt contains | Renders |
|---|---|
| `knee`, `sore`, `bothering`, `pain` | The injury case — protected structure with laterality, knee-loading movements in the filtered list |
| `exclude`, `deadlift` | The unresolvable-exclusion case — the degradation panel with score and threshold, plus a cautioned movement |
| `barbell`, `dumbbell`, `kettlebell`, `equipment` | The limited-equipment case — a substitution note naming the movement it replaces |
| anything else | A fallback session |

## What it deliberately does not do

There is no resolver, no traversal, and no planner in the frontend. An earlier pass had all three — roughly 1,900 lines including a three-pass concept resolver with calibrated thresholds, a rule-precedence safety filter, and a planner doing ranking, dosing and time budgeting. It was deleted on purpose. Two implementations of the same reasoning in two languages is a thing to keep in sync and then throw away, and the frontend copy would have been the one people accidentally read as the spec.

So: **the mock's plan quality is not a target.** If the sessions it returns look thin or oddly balanced, that is not a bug worth fixing here.

## Tracing

`GET /api/traces` and `GET /api/traces/{run_id}` back the Traces tab (`ASSESSMENT.md:134`). The mock records every plan and copilot call made this session, in memory, alongside three seeded runs — one copilot answer, one chart answer, one failed run where a Cypher read timed out.

The span *counts* are derived from `plan.trace`, not invented: the "Apply contraindications" span reports the same number of exclusions the plan sheet shows. That coupling is deliberate and there's a test on it. Durations, token counts and the Cypher text are authored — the real runtime will emit its own.

What the tracing backend needs to return is `RunTrace` in `types/index.ts`. Worth noting:

- **`TraceSpan.status`** has three values, not two. `DEGRADED` means the run completed but something was declined or fell back — a resolver miss, a partial retrieval. A run that quietly failed to act on part of the request must not look identical to a clean one in the list.
- **`started_ms` is an offset from the run start**, so the waterfall can lay spans out without parsing timestamps.
- **`query` is rendered verbatim.** This is the one surface in the app written for an engineer rather than a coach, so it shows Cypher on purpose — the exact thing the console deliberately hides.

## What the API has to return

The contract is `web/src/types/index.ts`, and the endpoint list is the doc comment at the top of `web/src/api/client.ts`. The shapes worth flagging early, because the UI renders them and they are easy to leave out of a first cut:

- **`PlanExercise.why: GraphPath[]`** — never empty. Each is `{ path, says }`: the traversal in graph syntax, plus one plain sentence. The **console renders only `says`**; `path` is for the Traces tab and for audit. Both fields are required — provenance is half "why not" and half "why", and the "why" half is the one that usually gets skipped.
- **`ProvenanceTrace.filtered`** — *every* dropped movement, not a sample, each with a coach-readable `detail` and the `path` that removed it. The counts have to reconcile against `/eligibility`, or the console prints a contradiction.
- **`ProvenanceTrace.unresolved`** — `{ phrase, best_guess, confidence, threshold, fallback }`. The score *and* the threshold, so the panel can say "0.354 against 0.68". Graceful degradation is graded (`ASSESSMENT.md:68`) and this is the surface that shows it.
- **`ProvenanceTrace.stages`** — named pipeline stages with a remaining count each. Rendered as the funnel. If the endpoint streams these, the UI already has a component shaped for it.
- **`WorkoutPlan.parent_run_id`** — an adjustment is a new run with a pointer, never a mutation.
- **`Verdict.CAUTION`** — distinct from excluded. A coach can override a caution, which is the whole reason `decisions.md` split `contraindicates` from `cautions`.
- **`Constraint.effect`** — `POOL` or `RANKING`. The builder says outright that lifting a ranking-only constraint won't move the count, so the control doesn't read as broken.

`disabled[]` carries `ConstraintItem.id`s (`${kind}:${label}`) and must never be able to switch an injury off. The client strips injury ids, but the server has to as well — it should load injuries from the member id, not the request body.

## Findings from the data, worth having

These came out of building the throwaway engine and they apply to the real one.

1. **Rep cadence comes from the data, not a clamp.** The catalogue used to hold a rate rather than a duration, so `Jump Rope - Single-Leg` read as 114 seconds a skip and the mock clamped every value into a believable band. The field is now `estimated_rep_seconds` and all 43 reps-based rows carry real cadences (0.53 s to 10 s), so the clamp is gone — keeping it would cap honest numbers. `0` still marks the field inapplicable and falls back to a 3 s cadence.

2. **`is_bilateral` marks a left/right pair, not "both sides at once".** Where it is true, `side` and `bilateral_pair_id` are both populated. So the work is per side and costs two working sets. Missing this halves the estimate on every unilateral movement — and session length is exactly this member's adherence problem.

3. **Fuzzy matching needs directional containment, with a coverage floor.** Token-set containment scoring 1.0 in both directions means `pull` matches `lower pull - hip lift` perfectly, turning a one-word focus into a specific pattern filter. Restricting it to concept-inside-query fixes that but is still not enough: `posterior chain and glutes` then matches `glutes` across the whole four-word window, and the rest of the phrase is silently swallowed. Both directions need guarding.

4. **Report focus misses, not just exclusion misses.** An exclusion that resolves to nothing is obviously worth reporting. A *focus* term that resolves to nothing is worth reporting too — otherwise `posterior chain and glutes` comes back as "read as: glutes" and the coach concludes both terms were understood.

5. **`preferences.dislikes` contains a movement the catalog stocks and a planner will happily prescribe.** `One-Kettlebell Hamstring Walkout` is both disliked and one of the few hip-hinge options her equipment supports. If a dislike down-ranks rather than excludes, the prescription needs to say so on the row, or it contradicts the panel above it.

6. **Group terms need expanding.** "Posterior chain" is standard coaching usage and is not a concept in the catalog's taxonomy. It needs to reach glutes, hamstrings, lower back and calves, which breaks the one-phrase-one-concept assumption a resolver naturally starts with.

## Tests

`web/src/__tests__/` has two files and neither covers the system:

- `dates.test.ts` — real frontend code. Date-only strings must parse as local midnight; `new Date("2026-05-27")` is UTC and renders a day early west of Greenwich.
- `mock.test.ts` — tests the mock, labelled as such. It guards one property only: the numbers on screen agree with each other, and every UI state stays reachable from some prompt.

The tests `ASSESSMENT.md:73` asks for — the concept resolver and the safety filter — belong with the backend implementation. There are none here, deliberately, rather than a set that passes against a stand-in and implies coverage that doesn't exist.
