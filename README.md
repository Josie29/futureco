# FutureCo — knowledge-graph-backed coach dashboard

A coach-facing dashboard over two knowledge graphs: **KG1**, the movement and clinical domain, and **KG2**, one member's context. Safety is enforced by deterministic graph traversal, never by prompt instruction — the filter takes a typed constraint set, not a string, so no language model has a path around it.

Full spec in [`ASSESSMENT.md`](./ASSESSMENT.md). Synthetic data only.

## Run it

```bash
cp .env.example .env      # optional — every value has a working default
docker compose up
```

That builds the image, starts Neo4j, seeds both graphs (**170 nodes, 454 edges**), and serves the API. Nothing else to install and no network needed at runtime — the embedding model is baked into the image at build time.

| Service | URL | Notes |
|---|---|---|
| API | http://localhost:8000 | `/health`, `/api/resolve`, and `/docs` for the OpenAPI browser |
| Neo4j Browser | http://localhost:7474 | `neo4j` / `futureco-local` |

**Prerequisites:** Docker. An `ANTHROPIC_API_KEY` is optional — everything above is deterministic and runs without one.

If a port is already taken, set `API_PORT`, `NEO4J_HTTP_PORT` or `NEO4J_BOLT_PORT` in `.env`. The seed is idempotent, so `docker compose up` a second time converges rather than duplicating.

Try it:

```bash
curl localhost:8000/health
curl "localhost:8000/api/resolve?term=pecs"          # alias  -> chest
curl "localhost:8000/api/resolve?term=deadlifts"     # declines, and says why

curl -X POST localhost:8000/api/members/mbr_01HX9JORDAN/plans \
  -H 'content-type: application/json' \
  -d '{"prompt":"Her left knee is bothering her again.","duration_min":45}'
```

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

## Tests

The packing, prescription and policy tests are pure and need neither Docker nor a key; the traversal tests need Neo4j up.

```bash
docker compose up -d neo4j
cd backend && uv sync && uv run pytest
```

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
| `backend/src/resolve/` | Three-pass concept resolver: exact/alias, fuzzy, embedding |
| `backend/src/safety/` | The deterministic filter, its policy weights, and provenance |
| `backend/src/plan/` | Section table, prescription, time solver, substitution, reasons |
| `backend/src/agent/` | The only place `anthropic` is imported |
| `backend/src/api/` | FastAPI service and the console's wire contract |
| `web/` | Coach console — Vite + React, built against `web/src/types/index.ts` |
| `data/authored/` | Hand-authored anatomy, contraindications, aliases, and the resolver and extraction cases |

## Status

Built and tested: both knowledge graphs, the concept resolver, the safety filter, the workout generator, the extraction agent, the API container, and the coach console.

Not built: the member-context copilot, which is where a real agent loop belongs — open-ended retrieval over KG2 needs one, and the generator does not. The console renders against a mock for that surface. The Postgres trace store in `tech-stack.md` is also still to come; `ProvenanceTrace` is already a serialisable object carrying the graph fingerprint, so persisting runs is a writer, not a redesign.
