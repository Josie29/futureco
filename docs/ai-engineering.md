# How I used AI to build this

**Built end to end in about a day** — two knowledge graphs, a three-pass resolver, a deterministic safety filter, an agentic generator, a retrieval copilot, and the console over all of it.

The speed is the least interesting part. What made it possible is a division of labour I hold to deliberately: **I own the model of the problem, AI owns execution against tasks I have already made verifiable.** This product's entire value proposition is *determinism* — a coach has to be able to defend a plan to a physio — so the work was deciding where a model is allowed to be wrong, and making every other boundary mechanically incapable of depending on it.

Every claim below points at a file you can open.

## Requirements first, and traceable

Before any code, I read the spec as a set of obligations rather than a feature list, and separated what it *mandates* from what it *leaves open*. The repo carries that reading in a form you can audit: **22 citations of specific `ASSESSMENT.md` line numbers across 17 source files**, in comments and docstrings, plus 12 more across the schema and design docs — 19 distinct spec lines in all.

That is not decoration. It means every non-obvious decision names the requirement it answers, so a reviewer can walk backwards from an implementation to the sentence that demanded it — and, more usefully, so *I* could tell at any moment whether a thing I was about to build was mandated, implied, or my own invention.

[`frontend-spec.md`](frontend-spec.md) is the clearest instance: every console component traced to the line requiring it, and a **"Cut, with reasoning"** table for everything I deliberately did not build. Knowing what to leave out is most of scoping a one-day build, and it is the part a model will not do for you — asked to build a coach dashboard, it will happily build all of it.

## The judgment calls a model could not make

These are graph-modelling and clinical-safety decisions. None came from a model; they came from reading the data and thinking about who gets hurt if the model is wrong. All are recorded in [`decisions.md`](decisions.md) with what was rejected.

- **Splitting the spec's `contraindicated-for` into `contraindicates` and `cautions`.** Absolute versus relative contraindication is a real two-valued clinical distinction. Two relations put the meaning on the edge rather than in a property a traversal has to inspect, and let the hard filter and the ranker run as separate passes with separate provenance — *a coach may override a caution, never a contraindication.*
- **Refusing to derive contraindications from anatomy.** Walking `affects` → `part_of` → `stresses` looks elegant and is dangerous: it would exclude every knee-loading exercise, when the member's own clinician cleared low-impact loading and a patellofemoral protocol *wants* that work. Safety runs top-down from the recorded condition instead. A model asked to "use the graph for safety" would have built the elegant version.
- **The grain rule for KG2.** A block becomes a traversed entity when something points at it, a leaf observation when it is `(metric, value, date)`, a property when it is a timeless scalar. That one rule settles biomarkers, labs, adherence and chat consistently, and stops the graph filling with nodes that exist only so the graph can be said to hold them.
- **`Session -trained-> MovementPattern`, not `-> Exercise`.** None of the nine movements in the workout history matches a catalogue exercise — not one, not even as a substring. The reachable concept is the pattern, and that is also the right grain: longitudinal reasoning cares that she trained hip-lift twice this week, not which SKU.
- **Equipment and movement patterns get no SNOMED mapping at all.** SNOMED is a clinical terminology and "Kettlebell" is not a clinical concept. A taxonomy where 4 of 32 map and 28 do not is worse than a clean local scheme. See [`ontologies.md`](ontologies.md).
- **The goal anchor is an authored exception, not a weight.** Nudging a weight to get lower-body work into a short session would have put goal-fit inside the safety filter it is supposed to be subordinate to.

## The harness

Speed at this quality came from tooling the workflow, not from typing faster.

- **Specify, then delegate.** Nothing non-trivial started as a prompt. Each task began as a written spec with acceptance criteria and explicit non-goals, so "done" was decidable before work began. Ambiguities got surfaced and settled *first* — a model will resolve an ambiguity silently and confidently, which is the expensive failure.
- **Standing rules over repeated corrections.** My `CLAUDE.md` is split into topic files — code quality, testing, git workflow, frontend conventions — so house style is context the agent always has rather than a correction I give twice. Anything I found myself saying a second time became a rule.
- **Purpose-built commands.** A `/spec` command to force the thinking-before-code step, and a `/review` command that instructs adversarial critique rather than agreement — the default failure mode of an assistant is to validate, and that has to be designed out.
- **Sub-agents for breadth.** Codebase-wide searches run in a sub-agent so the main context keeps the decision I am actually making instead of filling with file dumps.
- **`decisions.md` as durable context.** Written *as* decisions were made, not reconstructed afterwards. It is the project's memory across sessions — and writing the rationale is what exposed several defects, because a decision you cannot justify in prose usually is not one.
- **Small, verifiable commits.** 52 of them, each a reviewable unit. The review boundary is the commit, and a commit too large to review is a commit I did not really review.

## Making the model safe to depend on

A prompt saying "never waive an injury" is a wish. The guarantees here are structural:

- **`safety.filter.run` takes a `Composition`**, not a string. No signature anywhere accepts prose and returns a traversal, so the unsafe call cannot be written.
- **The instruction schema has no waive verb.** `Op` is exactly `{replace, add, remove}` — the model has no vocabulary for dismissing a clinical constraint, and `test_there_is_no_verb_for_waiving_a_clinical_constraint` asserts the enum stays that size.
- **A test walks the AST of every module under `plan/`** and fails if one imports `anthropic` (`test_the_plan_package_imports_no_model_client`). Type boundaries erode under future edits; this one cannot erode silently.
- **The copilot gets nine typed tools over module-constant Cypher.** It chooses *which* tool and with what arguments; it never composes a query. I rejected LangChain's `GraphCypherQAChain` explicitly — LLM-generated Cypher is the exact non-determinism the product exists to avoid.
- **No agent framework for the generator, because there is no loop.** One `messages.parse()` call into a Pydantic schema shared by the domain, the HTTP response and the model's output. LangGraph would state-machine a straight line. The SDK's Tool Runner *is* used for the copilot, where open-ended retrieval genuinely earns a loop. Knowing when not to reach for an agent is as load-bearing as knowing how to build one.

## Evals before prompts, and the labels get audited too

`resolver_cases.json` (25 cases) and `extraction_cases.json` (8) are each **fixture, offline stand-in and eval set in one file** — the thing that replaces the model in tests and the thing that measures the model are the same rows, so they cannot drift apart.

I wrote the labels **before** running the model. First pass, the live model agreed with **three of eight**. The diagnosis is the point: *four were prompt bugs*, *two were my labels being wrong* — I had expected a possessive and an article the model sensibly dropped — and *one was my own inconsistency*: having just told the model that plurals name classes, I had labelled "deadlifts" as a specific exercise. Now eight of eight, pinned by an opt-in `pytest -m live` test that costs money and so does not run in CI.

**Calibration then falsified my own design.** Thresholds are swept, not chosen: `calibrate.py` reports every `(fuzzy, vector)` pair passing all 25 cases, and the committed 0.90 / 0.68 are the midpoints of the passing band. But the sweep also killed my plan. I assumed the embedding pass would carry paraphrases like *"overhead press"* — it ranks the right concept first, at **0.528**. And *"deadlift"*, which must resolve to nothing, reaches `Barbell` at **0.523**. **A five-thousandth gap: no threshold separates them.** So `overhead press` became an alias, and the alias file became the documented escape hatch for terms no automatic pass can reach safely.

## Knowing which output can be verified — and saying where it can't

- **Citations are checked against an allowlist of message ids retrieval actually returned this run** — not against what exists in the graph. A model naming a real message it was never shown is still asserting a source it does not have.
- **Charts are assembled server-side.** The model returns a `kind` and a `metric_id`; `charts.py` reads the numbers from the graph. The worst a bad request can do is show the wrong *true* chart.
- **The limit, stated rather than hidden: figures inside prose are not checked.** A model can misquote a number it was correctly given and nothing here catches it. Knowing which of your model's claims are mechanically verifiable — and admitting which are not — is the discipline.

Two smaller pieces of model-specific knowledge, both enforced rather than remembered: **thinking stays enabled on the copilot** because Opus 5 with thinking disabled can write a tool call into visible text instead of emitting a `tool_use` block — the turn succeeds, the call never runs, nothing errors, and for a retrieval copilot that failure is silent and total. And **the system prompt is built from no f-strings**, asserted by `test_the_system_prompt_is_stable`, because interpolating a member id would break the cached prefix on every request, invisibly and expensively.

## Where the model was wrong, and what caught it

Three SNOMED muscle mappings came back confidently wrong — `core` on *the abdominal part of pectoralis major*, `hip adductors` on the group's **tendon**. A `maxItems` cap I added to the copilot's output schema looked obviously correct and 400'd every model call into retrieval-only.

Neither was caught by a test. The mappings were caught because the grounding script prints every row it resolves and I read them; the schema cap because `degraded` is a field on every answer rather than a log line, so the fallback announced itself on the first request.

I also traced both surfaces before optimising anything, which is how I found that **3437 ms of a 3483 ms generation is the single extraction call**, against under 45 ms for all 74 graph queries. Every latency instinct I had was about the Cypher.

**The lesson I would take to a team: with a fast model in the loop, your review capacity is the bottleneck — so build the surfaces that make wrong output loud.** That is why the grounding script prints per-row, why every copilot answer carries `degraded`, and why the provenance trace exists at all.
