# Evaluating this system in production

The premise: **this system's worst failure is a confident wrong answer, not a missing one.** A plan that omits a movement is a thin session a coach notices. A plan containing a contraindicated movement, or a copilot sentence quoting a figure that was never measured, is advice a coach acts on. Everything below is ordered by that.

## What is measured today

Real, in-repo, and runnable — not aspirational:

| Instrument | What it measures | Where |
|---|---|---|
| Threshold sweep | Both resolver thresholds against 25 labelled cases; the committed 0.90 / 0.68 are the midpoints of the passing band, not chosen numbers | `resolve/calibrate.py` |
| Extraction agreement | The live model against 8 labelled utterances. Opt-in (`pytest -m live`) because it costs money | `tests/test_agent_extract.py` |
| Pass coverage | That every resolver pass is exercised by some case, so one cannot quietly become dead weight | `tests/test_resolver.py` |
| Filter invariants | That no penalty total ever reaches `EXCLUDED`, and that the joint closure does not leak sideways through `part_of` | `tests/test_safety.py` |
| Run traces | Per-stage latency, token counts, and the Cypher each read ran | Postgres, `/api/traces` |
| Suite | 321 backend, 11 frontend | `uv run pytest` |

The traces already earned their place: the first real generator run showed **3437 ms of 3483 ms inside the single extraction call**, against under 45 ms for all 74 graph queries. Any latency work starts and ends at the model.

## Metrics I would take to production

Ordered by consequence, not by ease.

**1 · Contraindication leak rate — target zero, alarm on any.**
A prescribed movement whose pattern the member's condition contraindicates. Computable on every run without sampling, because `filter.run` scores all 50 exercises and keeps the verdicts: assert that no block in the plan carries an `EXCLUDED` verdict. This is a production *invariant*, not a metric — a non-zero value is a page, not a dashboard.

**2 · Silent misresolution rate.**
A phrase that resolved confidently to the wrong concept. The dangerous half of resolution: a decline is visible on the sheet, a wrong match is not. Measured by sampled human audit of `resolved[]` — the trace records the phrase, the concept, the pass and the score, so an auditor reads rows rather than replaying requests. Watch the near-threshold band hardest.

**3 · Degraded-answer rate, split by cause.**
Already a field on every copilot answer: synthesis unavailable, citation dropped as invented, model declined, tool failed. A rising *invented-citation* share means the model is drifting toward asserting sources it was not shown, which is the failure the allowlist exists to catch.

**4 · Coach acceptance of a plan.**
Ran unedited / adjusted / discarded. The closest thing to ground truth on plan quality, and it is nearly free: an adjustment is already a new run with a parent pointer, so the refinement chain *is* the label. A plan adjusted three times is a plan that was wrong three times, and the utterances say how.

**5 · Latency p50/p95 per surface, split model vs graph.**
The trace already splits it. The copilot measured **13 s** against the spec's ~5 s target — three model turns in the tool loop — which is a real gap and the first thing I would attack.

**6 · Tokens per run.** Already in `RunTotals`. Cost per coach per day is the unit that matters.

## Failure modes, and whether anything catches them

| Failure | Consequence | Detected today? |
|---|---|---|
| Contraindicated movement in a plan | Severe — injury | **Yes.** Verdicts exist for all 50; the invariant is assertable per run |
| Laterality lost — right-knee complaint matches a left-knee injury | Severe — wrong clinical constraint | **Yes.** The resolver extracts side; a test pins it |
| Substitution routes around a contraindication | Severe | **Yes, structurally.** Stand-ins are intersected with `result.eligible`, so only cleared movements can be offered |
| Copilot misquotes a number it was correctly given | Moderate — a coach repeats it | **No.** Citations are verified, charts are built server-side from the graph, but **figures inside prose are unchecked**. The honest limit |
| Stale graph — a plan built against a rebuilt catalogue | Moderate | **Partly.** The trace carries the node/edge fingerprint, so a stale verdict is *identifiable*; nothing alarms on it |
| Extraction drift after a model upgrade | Moderate — constraints silently misread | **Yes, as a gate.** The 8 labelled cases are the regression test; run before any model change |
| Thin pool presented as a full session | Low | **Yes.** `is_thin` and `costliest_constraint` are on the trace and rendered |
| Equipment list drifts from reality | Low | **No.** Nothing reconciles the member's stated kit against what she actually uses |

The fourth row is the one I would fix first. Verifying prose figures means constraining the model to emit numbers as structured fields the server renders — the same move already made for charts, where the model names a `kind` and `charts.py` reads the values from the graph.

## Safety monitoring

**Page on:** any contraindication leak; any run where the filter returned zero eligible movements; the graph fingerprint changing without a deploy.

**Review weekly:** the near-threshold resolution band; degraded-answer causes; adjustment chains longer than two, which are plans the generator kept getting wrong.

**Never alarm on:** a decline. A phrase that resolved to nothing is the system working — `deadlifts` reaching 0.40 against a 0.90 threshold is a correct refusal, not an incident.

## What is missing

Named rather than implied:

- **No retrieval-relevance eval for the copilot.** There are labelled cases for the resolver and the extractor; nothing labels "which tools *should* this question have called". That is the next eval set to write, and it would use the same file-as-fixture-and-eval-set pattern.
- **No plan-quality eval.** Nothing scores a session against what a coach would have programmed. Needs coach-labelled data that does not exist yet — which is why acceptance telemetry above is the cheaper first step.
- **No online feedback loop.** Nothing the coach does flows back into ranking.
- **One synthetic member.** Every threshold here is calibrated against a single chart, and a second member is worth more than any additional metric.
