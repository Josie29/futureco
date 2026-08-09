# FutureCo — knowledge-graph-backed coach dashboard

A coach-facing dashboard over two knowledge graphs: **KG1**, the movement and clinical domain, and **KG2**, one member's context. Safety is enforced by deterministic graph traversal, never by prompt instruction — the filter takes a typed constraint set, not a string, so no language model has a path around it.

Full spec in [`ASSESSMENT.md`](./ASSESSMENT.md). Synthetic data only.

## Run it

One command.

```bash
docker compose up
```

Then open **http://localhost:8000**.

That starts Neo4j and Postgres, seeds both graphs (**224 nodes, 538 edges**), and serves the API *and the coach console* from one origin. The console is built inside the image, so there is no second terminal, no `npm install`, and no Node on your machine. Nothing needs the network at runtime — the embedding weights are baked in at build time.

| Service | URL | Notes |
|---|---|---|
| Coach console | http://localhost:8000 | Served by the API, so same-origin by construction |
| API | http://localhost:8000/docs | `/health`, `/api/resolve`, members, plans, copilot, traces |
| Neo4j Browser | http://localhost:7474 | `neo4j` / `futureco-local` |
| Postgres | `localhost:5432` | `futureco` / `futureco-local` — run traces and plan lineage |

**Prerequisites:** Docker. That is the whole list. An `ANTHROPIC_API_KEY` is optional — see *Running without a key*.

```bash
cp .env.example .env      # optional — every value has a working default
```

If a port is taken, set `API_PORT`, `NEO4J_HTTP_PORT`, `NEO4J_BOLT_PORT` or `POSTGRES_PORT` in `.env`. The seed is idempotent, so a second `docker compose up` converges rather than duplicating.

**Working on the console?** `cd web && npm install && npm run dev` still gives you Vite with HMR on :5173, proxying `/api` to the backend. That path is for development only; the container needs neither.

**Everything in the console is live.** The builder's eligibility count, plan generation and refinement, the roster and member panels, the copilot, and the Traces tab all call the backend. There is no mock layer — `web/src/api/mock/` was deleted along with the last fixture it served.

Or drive it from the command line:

```bash
curl localhost:8000/health
curl "localhost:8000/api/resolve?term=pecs"          # alias  -> chest
curl "localhost:8000/api/resolve?term=deadlifts"     # declines, and says why

curl -X POST localhost:8000/api/members/mbr_01HX9JORDAN/plans \
  -H 'content-type: application/json' \
  -d '{"prompt":"Her left knee is bothering her again.","duration_min":45}'

# The read surface. The coach header is mock auth, but the check is real:
# a member is readable only when a `coaches` edge joins her to that coach.
curl localhost:8000/api/coaches
curl -H "X-Coach-Id: coach_01HXSAM" localhost:8000/api/members/mbr_01HX9JORDAN
curl -H "X-Coach-Id: coach_nobody"  localhost:8000/api/members/mbr_01HX9JORDAN   # 404, not 403

# The copilot, grounded in KG2.
curl -X POST localhost:8000/api/members/mbr_01HX9JORDAN/copilot \
  -H 'content-type: application/json' -H 'X-Coach-Id: coach_01HXSAM' \
  -d '{"prompt":"How has she been sleeping?"}'
```

## Running without a key

Both model surfaces degrade rather than fail, and they degrade differently.

**The generator does not degrade at all.** With no key the backend swaps a scripted extractor in — `/health` reports which is in use. Extraction is the *entire* model surface there, so the plans are identical; they just have to be asked for as instructions rather than as a sentence:

```bash
curl -X POST localhost:8000/api/members/mbr_01HX9JORDAN/plans \
  -H 'content-type: application/json' \
  -d '{"prompt":"","duration_min":45,"disabled":["equipment:Yoga Mat"]}'
```

**The copilot degrades honestly.** Synthesis *is* its output, so there is no scripted stand-in that would tell the truth. Without a key it runs the same nine retrieval tools against the same graph and renders what came back — the readings, the series, the cited messages — and says outright that nothing interpreted them:

```bash
curl localhost:8000/api/copilot/health          # {"synthesis": false, "path": "retrieval"}
```

Every answer carries `degraded` when it is less than a full one — synthesis unavailable, a citation dropped as invented, the model declined — and the console renders it as a banner. A partial answer that looked whole is the worst thing this surface could return.

## How a plan is built

```
prose ─[LLM]─▶ Instruction[] ─▶ resolve ─▶ compose ─▶ Composition
                                                          │
                                                   filter.run ── all 50 judged
                                                          │
                                         substitute ─▶ pack ─▶ WorkoutPlan
                                                          │
                                                    ProvenanceTrace
```

**One model call, at the very front.** Everything after the first arrow is Python and Cypher. The model turns a sentence into `Instruction` objects and never touches the graph — `safety.filter.run` takes a `Composition`, so there is no typed path from prose to a traversal, and a test walks the ASTs under `plan/` to keep it that way.

That means the whole generator runs **without an API key**: hand it the instructions instead of a sentence and you get the same plan. It is the path the CLI probe below takes, and the worked examples are reproducible because of it.

## Worked examples

`plan.probe` is the generator with no model in it. Both examples below are its real output.

```bash
cd backend
PYTHONPATH=src uv run python -m plan.probe --minutes 45 add:anatomy:"left knee"
PYTHONPATH=src uv run python -m plan.probe --minutes 45 replace:equipment:dumbbells
```

**The injury case** — a coach flags the knee. All 17 eligible movements survive, because flagging a structure down-ranks rather than excludes: the graph knows an exercise loads the knee, not that doing so is harmful. 44m33s of 45 minutes scheduled.

```
MAIN
  2 x 40s hold each side   Low Copenhagen Plank
      flagged_structure  loads the knee
      cleared            no contraindicated movement pattern reaches it
  2 x 15                   Alternating Dumbbell Racked Crossback Lunge  <- anchored on a goal
      caution            Loaded knee flexion with a long lever at the front knee.
                         Tolerable at partial range, so a penalty rather than a hard exclusion.
```

The caution is a clinician's sentence from `contraindications.json`, quoted, not generated. The lunge is *anchored*: by rank alone this member's only goal-serving movements are also her only cautioned ones, so a short session would contain no lower-body work at all.

**The limited-equipment case** — dumbbells only. 45 of 50 movements go, and the plan says so rather than presenting five as a full session: 24m32s of 45 minutes, a thin pool, an empty cooldown and four uncovered slots, each naming the equipment limit as its cause.

```
  1 x 12   Walking Toe Touches
      substitution   stands in for World's Greatest Stretch, which shares
                     mobility - dynamic and needs equipment that is not available
```

A stand-in can only ever be a movement the filter already cleared, and must share the dropped one's *primary* pattern — so no substitution can route around a contraindication.

**The refinement case** — the three scenarios from `ASSESSMENT.md:27-31` as one conversation, against the live extractor. Real output, one `curl` per step.

```
step 1  "She's only got dumbbells and a kettlebell at home today."
        dumbbells  -> Dumbbell    [fuzzy]  focus
        kettlebell -> Kettlebell  [exact]  focus
        5 of 50 eligible

step 2  "Her left knee is bothering her again."
        left knee  -> knee        [exact]  protect   side=left
        5 of 50 eligible          <- flagging down-ranks; it does not exclude

step 3  "Exclude deadlifts."
        deadlifts  -> declined at 0.40, threshold 0.90
        5 of 50 eligible          <- the request changed nothing, and says so
```

Two things this shows that a single-shot example cannot.

**Constraints accumulate.** By step 3 the plan is still built from the equipment limit set in step 1 — `Dumbbell` and `Kettlebell` are still in the resolved list, two refinements later. An adjustment loads its parent's structured instructions and appends its own; it does not rebuild from the last sentence. That was a real bug, and `docs/decisions.md` *Adjustment* records what it did.

**A decline is reported, not absorbed.** No catalog movement is named "deadlift", so the phrase reaches 0.40 against a 0.90 threshold and the resolver refuses rather than guessing at `Barbell` — which it can reach at 0.523, five thousandths above a term that *must* resolve. The sheet names the phrase, the near-miss, the score and the threshold it missed. Nothing silently didn't happen.

## Tests

The packing, prescription and policy tests are pure and need neither Docker nor a key; the traversal tests need Neo4j up.

```bash
docker compose up -d neo4j
cd backend && uv sync && uv run pytest      # 302 tests
```

Traversal tests need Neo4j; the packing, prescription and policy tests are pure. No test needs Postgres — the stores fall back to bounded in-memory implementations when `DATABASE_URL` is unset, and the keyless copilot tests force that path with a fixture rather than reading whatever `.env` happens to hold.

One test calls the real API and is deselected by default, since it costs money and needs a key. It asserts the live model produces the same `Instruction`s as the offline stand-in over the same labelled cases — which is what stops the stand-in becoming fiction.

```bash
uv run pytest -m live
```

## Repo map

| Path | Purpose |
|---|---|
| [`docs/decisions.md`](./docs/decisions.md) | Every schema and design decision, and what was rejected |
| [`docs/tech-stack.md`](./docs/tech-stack.md) | Stack choices with one-line rationale, and the alternatives |
| [`docs/kg1-schema.md`](./docs/kg1-schema.md) · [`docs/kg2-schema.md`](./docs/kg2-schema.md) | Node and edge types per graph |
| `backend/src/graph/` | Schema enums and the Cypher build layer |
| `backend/src/resolve/` | Three-pass concept resolver, and the mention scanner over free text |
| `backend/src/safety/` | The deterministic filter, its policy weights, and provenance |
| `backend/src/plan/` | Section table, prescription, time solver, substitution, reasons |
| `backend/src/agent/` | Prose to `Instruction[]` for the generator |
| `backend/src/copilot/` | The copilot's typed retrieval tools, charts, citation check and agent loop |
| `backend/src/api/` | FastAPI service, the console's wire contract, run tracing and the Postgres stores |
| `backend/src/graph/recording.py` | Session wrapper and stage timer behind every generator trace |
| `web/` | Coach console — Vite + React, built against `web/src/types/index.ts` |
| `data/authored/` | Hand-authored anatomy, contraindications, aliases, metric bands, session-pattern mappings, coaches, and the resolver and extraction cases |

## Observability

Both surfaces record every run to Postgres, and the Traces tab reads them. Nothing on that screen is fabricated.

A generator trace nests each graph read under the pipeline stage that issued it, because `RunRecorder` gives the stage timer and the session wrapper one clock — offsets are measured, not reconstructed from summed durations. Repeated reads fold into one row carrying a `calls` count, so `PATTERN_SIBLINGS` running forty times is one line rather than forty.

The first trace off the rebuilt path made its own point:

```
agent   plan.generate           @    0.0 + 3483.2ms
  llm     extract                 @    0.0 + 3437.5ms  claude-opus-5  in=1632 out=55
  graph   load_standing           @ 3437.6 +    5.3ms
  graph   filter                  @ 3443.8 +    9.9ms   50 rows judged
  graph   substitute              @ 3458.0 +   15.0ms   calls=40
  graph   fingerprint             @ 3473.6 +    9.4ms   calls=30
```

**3437 of 3483 ms is the single extraction call.** All 74 graph queries together cost under 45 ms, so the latency budget is the model and nothing else — which is worth knowing before optimising any Cypher.

## Status

Built and tested end to end: both knowledge graphs, the concept resolver, the safety filter, the workout generator, the extraction agent, the coach copilot, run tracing, the API container serving the console, and 302 backend tests.

KG2 holds the member's whole record — sessions, chat, biomarkers, labs and adherence — at three grains: traversed entities, leaf observations, and node properties. `docs/kg2-schema.md` records which block lands where and why.

Known gaps, in the order they matter:

- **SKOS mappings.** `ASSESSMENT.md:56` asks for the catalog's taxonomy mapped onto ontology concepts with SKOS. SNOMED codes ground the 27 anatomy nodes and the one condition; muscles, movement patterns and equipment have no ontology mapping, and `aliases.json` is a `skos:altLabel` set that is not named as one.
- **OPE and COPPER.** Used nowhere and rejected nowhere. The spec asks for reasoning on what to pull and what to leave out, and for three of five ontologies that reasoning is not written down.
- **Streaming.** Answers render whole. The generator names its pipeline stages while working and the copilot shows a skeleton, so the wait is legible, but token-by-token streaming is the remaining upgrade.
- **Retrieval and plan-quality evals.** `resolver_cases.json` (25 labelled) and `extraction_cases.json` (8, pinned against the live model) are real eval sets with a threshold sweep behind them. There is no equivalent for copilot retrieval relevance or plan quality.
