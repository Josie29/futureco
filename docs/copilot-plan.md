# Build plan — KG2 build-out and the clinical copilot

Temporary. Each decision below folds into [`decisions.md`](decisions.md) and
[`kg2-schema.md`](kg2-schema.md) as the work lands, and this file goes away.

## Scope

**In.** The rest of KG2 — workout history, chat, biomarkers, labs, adherence —
and surface B of `ASSESSMENT.md`: the coach copilot, backend and frontend, so a
coach can ask questions about the member and get answers grounded in her record.

**Out.** Everything to do with the workout generator. Surface A is another
engineer's, and nothing here builds into it: no plan generation, no
`/eligibility`, no changes to `safety/`, and `web/src/api/mock/{plans,
catalogue,traces}.ts` are left alone. `mock/copilot.ts` is the only mock deleted.

### The seam

Two streams touching one repo. What each owns:

| | This stream | Generator stream |
|---|---|---|
| **Graph** | All of KG2, including `Session`/`Message`/`Observation` | KG1 and `safety/` |
| **Read API** | `GET /api/coaches`, `/members`, `/members/{id}`, `/messages` | `GET /eligibility`, `POST /plans`, `/adjust` |
| **Member context** | Assembles it, including `constraints[]` | Consumes it |
| **Frontend** | Copilot dock, member header, goals, sessions, roster | Builder, plan sheet, traces tab |
| **Mocks** | Deletes `mock/copilot.ts` | Owns `mock/plans.ts`, `mock/catalogue.ts`, `mock/traces.ts`, and `fixtures.ts`, which they still read |

`MemberContext.constraints[]` sits on the line and belongs here: it is derived
entirely from KG2 facts this stream already loads — equipment, dislikes,
injuries, goal targets — and the generator consumes it rather than producing it.
That division is *own the read model, not what reads it*.

**Files both streams edit.** All append-only in practice, but worth knowing
before a rebase: `graph/schema.py` (five labels, five rel types added here),
`api/semantics.py` (nine triples), `api/app.py` (router registration),
`settings.py` (`as_of`), `web/src/api/client.ts` (disjoint function bodies),
`web/src/types/index.ts`, `data/authored/aliases.json`, and `docs/decisions.md`.
Nothing here modifies `data/member-context.json` or anything under `safety/`.

**Worth telling them:** `Session -trained-> MovementPattern` is exactly what
longitudinal progression needs (`ASSESSMENT.md:135`) — *don't hammer lower-pull
a third time this week* becomes one hop. It lands as a side effect of this work
and they should know it is there.

## Decisions taken

Four calls made here rather than deferred. Each is reversible; each is recorded
because a reviewer will ask.

**D1 · Grain, not membership.** Every block of `member-context.json` goes into
KG2. What varies is whether it becomes a traversed entity, a leaf observation,
or a property — decided by whether anything points at it. The rule that
rejected `preferred_session_minutes` (`decisions.md`, KG2 item 2) does not
force biomarkers out; it forces them to be modelled as observations rather than
as member attributes, which they already are. `weight_trend_kg` is three dated
values, `sleep_hours_last_7_days` is seven with the dates stripped, every lab
carries a date. The JSON flattens a time series into a scalar; the graph
un-flattens it.

**D2 · The API cut is the read surface plus the copilot.** `GET /api/coaches`,
`/api/members`, `/api/members/{id}`, `/api/members/{id}/messages` and
`POST /api/members/{id}/copilot` all go real. The generator stays mocked. The
alternative — copilot only — puts Neo4j figures in the dock beside `fixtures.ts`
figures in the header, two sources that can disagree on screen while a reviewer
is looking at both.

**D3 · Without an API key the copilot still retrieves.** Tools execute, and
their typed results render as a structured answer — figures, series, cited
messages — under a banner saying prose synthesis is unavailable. `README.md`
promises `docker compose up` works with no key, and the retrieval half is the
graded half.

**D4 · The copilot emits spans; the Traces tab is not touched.** Observability
is shared infrastructure and the generator is the bigger span producer, so this
stream builds only what it needs to debug itself: a `TraceStore` protocol, an
append-only in-memory implementation, and copilot span emission. The two
`/api/traces` endpoints are written server-side and left unregistered, and
`web/src/api/client.ts` keeps reading `mock/traces.ts`. The generator stream
inherits a working store, picks the durable backing (`tech-stack.md` says
Postgres, still uncontainerised), and swaps the tab when its runs join. Nothing
here half-builds a surface someone else owns.

---

## KG2 schema delta

### The finding that sets the grain

`workout_history` names nine movements. **Zero match the catalog, and none
matches as a substring.** There is no `Hip Thrust`, no `Wall Sit`, no `Band
Pull-Apart`; the only `Step-Up` is `Barbell Step Up to Knee-Drive`, needing a
barbell she does not own. This is the `preferences.dislikes` failure again,
which `decisions.md` (*Data cleanup* 2) fixed by rewriting the data.

Do not rewrite it here. `kg2-schema.md:63` already predicted the answer and
deferred it: *"its fuzzy and embedding passes could plausibly reach a pattern
rather than an exercise — a distinction this schema has no edge for. Worth
revisiting once the resolver exists."*

All nine map cleanly onto patterns that do exist — `Hip Thrust` and
`KB Romanian Deadlift` to `lower pull - hip lift`, `Goblet Squat
(box-supported)` to `lower push - squat`, `Band Pull-Apart` to `upper pull -
horizontal`. So the edge is `Session -trained-> MovementPattern`, not
`-> Exercise`. That is the right grain regardless: for longitudinal reasoning
what matters is that she has hit lower-pull twice this week, not which SKU, and
pattern is the axis `is_a` already carries as *"the axis equipment
substitutions travel along"* (`semantics.py`).

### New nodes

| Label | Count | Source | Earns its place by |
|---|---|---|---|
| `Coach` | 1 | `profile.coach_id` | `coaches` edge — turns mock auth into a real authorization check |
| `Session` | 4 | `workout_history[]` | `trained` edges into KG1's pattern taxonomy |
| `Message` | 4 | `chat_history[]` | `mentions` edges into KG1's equipment and anatomy |
| `Observation` | 28 | `biomarkers`, `labs`, `adherence` | A shared `Metric` vertex, and reachability from `Goal` |
| `Metric` | 17 | `data/authored/metrics.json` | Carries unit, reference range and direction-of-good for every observation pointing at it |

### New edges

| Edge | From → To | Count | Means |
|---|---|---|---|
| `coaches` | Coach → Member | 1 | Authority to read this member's context |
| `has` | Member → Session \| Message \| Observation | 36 | Ownership; target label supplies the meaning, per KG2 decision 1 |
| `trained` | Session → MovementPattern | ~9 | What class of work a session actually did. Absent on a skipped session, which is correct |
| `mentions` | Message → Equipment \| AnatomicalStructure \| MovementPattern | ~5 | A concept the member or coach named in writing |
| `measures` | Observation → Metric | 28 | What was measured, and against which range |
| `measured_by` | Goal → Metric | 1 | How a non-muscular goal is scored |

`has` is reused rather than split into `has_session` / `has_message`, because
every target label already determines the relation — the same rule KG2 decision
1 applies today. `trained`, `mentions`, `measures` and `measured_by` are named
because they carry meaning ownership does not, which is the stated exception
that already justifies `dislikes` and `targets`.

Graph goes from 170 nodes / 454 edges to roughly **224 / 534**.

### `measured_by` is what stops observations being a dead end

`goal_sleep` — *"Average 7+ hours of sleep on weeknights"* — carries an empty
`targets[]` because it is not muscular. It is the one goal the graph currently
cannot say anything about, and the frontend compensates by hardcoding
`SLEEP_TARGET_HOURS` and a `target_date === null` heuristic in `fixtures.ts`.

One edge fixes it. `Goal -measured_by-> Metric <-measures- Observation` makes
the sleep goal's progress a traversal, deletes two frontend constants, and — the
part that matters for review — means the observation subgraph **is** traversed
rather than being a leaf hung off `Member` for completeness.

Say plainly in the docs where it is still shallow: nothing yet walks from a
`Condition` to the metrics that monitor it, because patellofemoral pain is not
monitored by anything on this panel. `Condition -monitored_by-> Metric` is the
named empty slot, not an oversight.

### Two new authored files

Both follow the `data/authored/` precedent: hand-written, inspectable, and
standing in for LLM extraction at ingest — the same shortcut `goals[].targets`
and `injuries[].condition` already take and `decisions.md` documents twice.

1. **`session_patterns.json`** — the nine shorthand names → pattern names, one
   note per row saying why that pattern. The build fails on an unmapped name,
   because a session that silently trains nothing is a hole in the longitudinal
   record.
2. **`metrics.json`** — 17 metrics with unit, reference range, and
   direction-of-good. Ranges are standard published adult panels, cited per row.

`aliases.json` gains `dbs → Dumbbell`, without which the strongest `mentions`
edge in the sample does not land.

### What is derived, not ingested

`coach_brief` is generated output dated `2026-06-04` — yesterday's copilot
answer, not member context. A copilot that retrieves a stored conclusion is
echoing, which is the *"semantic search with extra steps"* the rubric names.

So `churn_risk`, `adherence.trend`, `typical_session_min` and the morning tasks
are all computed. Two of the brief's three churn reasons fall straight out of
the graph — the adherence series, and the skipped session plus the message
explaining it. **The third, "login frequency down vs. prior month", has no
supporting data anywhere in the file.** The derivation cannot invent it, and
that divergence gets written up as evidence the system is grounded rather than
quietly reconciled.

---

## Work breakdown

### Phase 1 — KG2 build-out

| File | Change |
|---|---|
| `graph/schema.py` | `NodeLabel` += `COACH`, `SESSION`, `MESSAGE`, `OBSERVATION`, `METRIC`. `RelType` += `COACHES`, `TRAINED`, `MENTIONS`, `MEASURES`, `MEASURED_BY`. New `MetricCategory` enum |
| `graph/build/member.py` | Models for `Session`, `Message`, `Attachment`, `Adherence`, `Biomarkers`, `Labs`, `CoachBrief`. `MemberContext` stops excluding them — rewrite the class docstring, which currently says the opposite |
| `graph/build/metrics.py` *(new)* | Load `metrics.json`, reshape all four measurement blocks into a flat `(metric, value, date, panel)` stream |
| `graph/build/kg2.py` | Build coach, sessions, messages, observations; the four new edge writers |
| `resolve/mentions.py` *(new)* | Scan text against `Vocabulary` surface forms. Exact and alias only |
| `api/semantics.py` | Nine new triples in `EDGE_RULES`; `_KG2_AUTHORED` gains the five new labels |
| `api/instances.py` | `caption_for` handles `Session` (`title`), `Message` (truncated `text`), `Observation` (`metric + value`) |
| `data/authored/` | `session_patterns.json`, `metrics.json`, alias addition |
| `docs/` | Rewrite `kg2-schema.md`; new `decisions.md` entries for D1 and the derived brief |

**The mention scanner, and why it is not the resolver.** `Resolver.resolve`
takes one phrase and returns one concept; a message is a sentence containing
zero or more. So `mentions.py` is a separate unit that walks the vocabulary's
surface forms over the text, longest-match-wins, anchored to word boundaries,
using `Vocabulary.exact()` and `by_alias()` — both already public. No fuzzy, no
vector: a build-time edge asserting the member named a concept should be
certain, and it needs no embedder, so the seed stays fast.

Two guards it needs, both from real data:

- **`car` is a movement pattern.** `Standing Miniband Hip Flexion` has
  `movement_patterns: ["car"]` — controlled articular rotation. Unguarded, every
  message containing the word *car* links to it. Minimum surface length plus
  word-boundary anchoring, with a test pinning this exact case.
- **Misses report, they do not fail.** Same rule as `dislikes` (KG2 decision 3):
  a member can write about anything, and naming a concept the catalog lacks
  makes the message no less real.

Expected yield on the sample: *"Still no barbell at home btw — only DBs and a
kettlebell"* → `Equipment:Barbell`, `Equipment:Dumbbell`, `Equipment:Kettlebell`.
*"Knee felt okay with the box squats"* → `AnatomicalStructure:knee`. Her
equipment constraint then has a **citation** — traceable to the message where
she said it, which is the assessment's own limited-equipment scenario grounded
rather than asserted.

### Phase 2 — Read API

| File | Change |
|---|---|
| `api/routes/members.py` *(new)* | The four read endpoints |
| `api/members.py` *(new)* | Assemble `MemberContext`: derived goals progress, typical session, adherence, this-week counts, constraint groups |
| `api/churn.py` *(new)* | Deterministic churn derivation |
| `settings.py` | `as_of: date \| None`, defaulting to `coach_brief.generated_for` |
| `data/authored/roster.json` *(new)* | The three filler members |

**`as_of` is a landmine.** The data is dated June 2026; today is August. The
frontend already pins `TODAY = "2026-06-04"` in `lib/dates.ts`, and real
backend queries asking for "the last seven days" against a wall clock return
nothing. One reference date, read from `coach_brief.generated_for`, returned on
`GET /api/members/{id}` as `as_of`, and the frontend constant deleted in
phase 4. Two hardcoded dates in two languages is how they drift.

**The filler roster stays out of the graph.** Devin, Alex and Priya carry
roster metadata and no clinical detail; as `Member` nodes they would be exactly
the edgeless nodes the grain rule rejects. They live in an authored file, and
selecting one 404s as it does today. An unknown member and a member this coach
does not coach both return 404, not 403 — a 403 confirms the member exists.

### Phase 3 — Copilot

New package `backend/src/copilot/`.

| File | Holds |
|---|---|
| `queries.py` | Parameterised Cypher, one constant per retrieval, same discipline as `safety/queries.py` |
| `tools.py` | Eight typed tools; each returns Pydantic, never a dict |
| `charts.py` | `ChartPayload` built server-side from tool results |
| `citations.py` | Validate every cited `message_id` against what this run actually retrieved |
| `agent.py` | The Anthropic tool-runner loop, plus the keyless path |
| `answer.py` | `CopilotAnswer`, mirroring the TS `CopilotMessage` |

**The tools.** `member_profile` · `goals` · `sessions(since, limit)` ·
`observations(metric, since)` · `messages(concept, since, limit)` ·
`injuries_and_constraints` · `churn_assessment` · `catalogue_fit`.

The last two are the ones that make it a *clinical* copilot rather than a
reader. `injuries_and_constraints` and `catalogue_fit` bridge into KG1 through
`safety.standing` and `safety.filter`, so *"why can't she squat?"* is answered
by the same traversal that would exclude the movement from a plan — one source
of truth for the safety claim, not a second explanation that can disagree with
the first.

**They are also the only cross-stream dependency, so they are built last and
behind an adapter.** `copilot/catalogue.py` is the single module importing from
`safety/`, calling `load_standing` → `compose` → `filter.run` read-only. If the
generator stream refactors those signatures — likely, since they are mid-build —
this is one file to fix, not eight tool definitions. If the interface is moving
too fast to track, ship the copilot without `catalogue_fit` and add it once
their work settles; the other seven tools have no `safety/` dependency at all.

**No LLM writes Cypher.** `tech-stack.md` rejected `GraphCypherQAChain` for
exactly this. The model chooses which tool to call and with what arguments; the
Cypher is a module constant.

**Three grounding mechanisms, and one honest gap.**

1. Charts are assembled server-side from tool output. The model picks *which*
   result to feature; it never emits a data point.
2. Cited `message_id`s are checked against what the tools returned this run.
   An invented id is dropped and the drop is recorded on the span.
3. Every tool result is captured on a `GRAPH` span, so a reviewer can read what
   retrieval actually returned beside what the answer claimed.
4. **Figures inside prose are not machine-verified.** A model can still
   misquote a number it was correctly given. Say so in the README rather than
   implying the whole answer is validated.

**A guardrail on the clinical surface.** Reference ranges make the copilot
capable of sounding diagnostic. It reports values against ranges and names what
is outside them; it does not interpret, diagnose, or advise. This is a system
prompt constraint and a documented limitation — not a graph mechanism, and it
should not be described as one.

**Single agent, deliberately.** A deterministic pre-pass scans the question for
concepts using the same `mentions.py` scanner, seeding retrieval before the
model runs; a deterministic post-pass validates citations and attaches charts.
Between them is one tool-running agent. The multi-agent workflow
`ASSESSMENT.md:5` calls core belongs to the generator — planner, safety, dosing
— where the stages genuinely differ. Splitting the copilot into a retriever and
a synthesiser would be two prompts pretending to be an architecture. **Flagged
as an open item**, since the assessment weights multi-agent design heavily.

### Phase 4 — Frontend

| File | Change |
|---|---|
| `api/client.ts` | Five function bodies become `fetch`. The plan, eligibility and trace bodies are not touched |
| `api/mock/copilot.ts` | Deleted |
| `features/copilot/prompts.ts` *(new)* | `QUICK_PROMPTS` moves here |
| `lib/dates.ts` | `TODAY` comes from the API's `as_of` |
| `features/copilot/CopilotDock.tsx` | No-key banner state |
| `types/index.ts` | `MemberContext` gains `as_of`. Nothing else changes |
| `types/graph.ts`, `features/admin/*` | Five new labels, five new rel types, styles and diagram rows |

`api/fixtures.ts` is **left intact**, not shrunk. `mock/plans.ts` and
`mock/catalogue.ts` import `member`, `goalMuscles` and `CAUTIONED_PATTERNS` from
it, and both belong to the generator stream. `client.ts` simply stops reading it
for the four endpoints that go real; deleting the now-unused exports is the
generator stream's cleanup when its own mocks go.

**`CopilotDock.tsx` imports `QUICK_PROMPTS` from `@/api/mock/copilot` today**,
which breaks the rule `mock-notes.md` states — *"No component imports from
`mock/`"*. Deleting the mock forces the fix.

**The contract claim gets tested here.** `mock-notes.md` asserts that when the
API lands, `CopilotMessage` and `ChartPayload` do not change. If they do, that
claim was wrong and the doc gets corrected rather than the types quietly
reshaped.

### Phase 5 — Span emission only

`api/traces.py` with a `TraceStore` protocol and an in-memory implementation.
The copilot emits a root `AGENT` span, a `RESOLVE` span for the concept
pre-pass, a `GRAPH` span per tool call carrying the Cypher verbatim, and an
`LLM` span per model call with token counts.

The two endpoints are written but **not registered**, and the frontend Traces
tab is not touched — it stays on `mock/traces.ts`. This stream needs spans to
debug a multi-tool agent against a 5s budget; it does not need to claim a
surface the generator stream owns. What they inherit is a store with a real
producer already exercising it.

`SpanStatus.DEGRADED` earns its keep immediately: a question whose concept
pre-pass resolves nothing, or a dropped invented citation, completes but is not
clean.

---

## Tests

Chosen the same way `ASSESSMENT.md:73` asks — the paths where a silent failure
is invisible and expensive.

| File | Needs Neo4j | Guards |
|---|---|---|
| `test_mentions.py` | No | `car` does not match the word *car*. "no barbell… only DBs and a kettlebell" yields three equipment concepts. A miss reports rather than raises |
| `test_churn.py` | No | Jordan's series derives `elevated` with its two evidenced reasons — and *"login frequency"* is **not** among them, because nothing supports it |
| `test_citations.py` | No | An invented `message_id` is dropped, and the drop is recorded |
| `test_metrics.py` | No | Every observation reaches a metric; every metric range is well-formed |
| `test_kg2_build.py` | Yes | All nine session movements land on a pattern. Counts. Idempotent re-seed |
| `test_copilot_tools.py` | Yes | Each tool returns rows traceable to `member-context.json` |

Frontend `mock.test.ts` shrinks as the copilot mock goes. No new frontend tests:
a suite passing against a stand-in implies coverage that does not exist, which
is the position `mock-notes.md` already takes.

---

## Risks

1. **Reference ranges are clinical assertions.** Sourced per row, generic adult
   panels, whole dataset labelled synthetic, and the copilot reports rather than
   interprets. The alternative — no ranges — makes `Metric` a bare unit label
   and removes the main reason observations are nodes.
2. **`resting_hr_bpm` and `hrv_ms` carry no date in the source.** They are bare
   scalars where every sibling is dated. Stamped with `as_of` and the assumption
   recorded, because an undated observation cannot be plotted or compared.
3. **`weight_kg` exists twice** — a profile scalar and a three-point series.
   Drop the profile property, derive latest from observations. Two sources for
   one fact is how they drift.
4. **Prose figures are not verifiable.** Stated as a limitation, not designed
   around.
5. **Latency.** Two LLM round trips plus millisecond Cypher should sit inside
   the ~5s budget, but this is the first surface with a model in the path.
   Measure before claiming. If it misses, the levers are streaming (which
   `frontend-spec.md` already holds as the known upgrade) or `claude-sonnet-5`
   for the copilot specifically — a `tech-stack.md` amendment, not a silent swap.
6. **The console is half real until the generator lands.** Left column and dock
   from Neo4j, builder from `mock/plans.ts`, traces tab fictional. Expected with
   two streams; worth a README line so a reviewer is not surprised.
7. **`GET /api/members/{id}` is a cross-stream contract.** The generator's
   Builder reads `constraints[]` off it. Once `client.ts` swaps `getMember` to
   `fetch`, a missing or reshaped constraint group breaks their panel, not the
   copilot — so the shape in `types/index.ts` is frozen, and any change to it
   goes to them first.

## Open items

- **Multi-agent.** The copilot is single-agent by design (phase 3). The
  assessment weights multi-agent design heavily and I think the generator is
  where it genuinely belongs — which is now someone else's surface. Worth
  agreeing across both streams who is answering that criterion, so neither
  assumes the other did.
- **`Condition -monitored_by-> Metric`.** Modelled as a named empty slot, not
  populated. Populating it means authoring clinical monitoring claims.
- **`tech-stack.md` describes a Postgres trace container that does not exist.**
  Not this stream's to build (D4), but the doc is wrong today either way and
  needs a line saying the store is staged.
