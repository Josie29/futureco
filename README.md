# FutureCo — knowledge-graph-backed coach dashboard

A coach-facing dashboard over two knowledge graphs: **KG1**, the movement and clinical domain, and **KG2**, one member's context. Safety is enforced by deterministic graph traversal, never by prompt instruction — the filter takes a typed constraint set, not a string, so no language model has a path around it.

Full spec in [`ASSESSMENT.md`](./ASSESSMENT.md). Synthetic data only.

## Run it

Two processes: the backend in Docker, the console on Vite. The console is **not** in `docker compose` yet, so it is a second terminal.

```bash
cp .env.example .env      # optional — every value has a working default

docker compose up         # terminal 1 — Neo4j, seeds both graphs, serves the API
```

```bash
cd web && npm install     # terminal 2 — first run only
npm run dev               # console on http://localhost:5173
```

The backend builds its image, starts Neo4j, seeds both graphs (**224 nodes, 538 edges**), and serves the API. Nothing else to install and no network needed at runtime — the embedding model is baked into the image at build time.

| Service | URL | Notes |
|---|---|---|
| Coach console | http://localhost:5173 | Vite proxies `/api` to the backend, so it is same-origin |
| API | http://localhost:8000 | `/health`, `/api/resolve`, the member and copilot surfaces, and `/docs` |
| Neo4j Browser | http://localhost:7474 | `neo4j` / `futureco-local` |

**Prerequisites:** Docker, and Node 20+ for the console. An `ANTHROPIC_API_KEY` is optional — see *Running without a key* below.

If a port is already taken, set `API_PORT`, `NEO4J_HTTP_PORT` or `NEO4J_BOLT_PORT` in `.env`. Point the console at a moved API with `VITE_API_TARGET=http://localhost:8001 npm run dev`. The seed is idempotent, so `docker compose up` a second time converges rather than duplicating.

**What is live and what is not.** Everything a coach reads or asks for calls the backend: the builder's eligibility count, plan generation and refinement, the roster and member panels, and the copilot. Only the Traces tab still renders a fixture, because only the copilot emits spans so far. `web/src/api/client.ts` is where the split lives, one function per endpoint.

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
| `backend/src/resolve/` | Three-pass concept resolver, and the mention scanner over free text |
| `backend/src/safety/` | The deterministic filter, its policy weights, and provenance |
| `backend/src/plan/` | Section table, prescription, time solver, substitution, reasons |
| `backend/src/agent/` | Prose to `Instruction[]` for the generator |
| `backend/src/copilot/` | The copilot's typed retrieval tools, charts, citation check and agent loop |
| `backend/src/api/` | FastAPI service and the console's wire contract |
| `web/` | Coach console — Vite + React, built against `web/src/types/index.ts` |
| `data/authored/` | Hand-authored anatomy, contraindications, aliases, metric bands, session-pattern mappings, coaches, and the resolver and extraction cases |

## Status

Built and tested end to end: both knowledge graphs, the concept resolver, the safety filter, the workout generator, the extraction agent, the coach copilot, the API container, and the coach console wired to all of it.

KG2 now holds the member's whole record — sessions, chat, biomarkers, labs and adherence — at three grains: traversed entities, leaf observations, and node properties. `docs/kg2-schema.md` records which block lands where and why.

Not built, in the order they matter:

- **The console in `docker compose`.** `ASSESSMENT.md:119` grades one command, and today it is two: the backend containerised, the console on Vite. Serving the built bundle from the API container would close it.
- **Generator spans.** The copilot records every run — the Cypher each read ran, the tool loop, token counts — through a `TraceStore`. The generator does not yet, so the Traces tab still reads a fixture rather than a list holding only half the runs.
- **The Postgres trace store** in `tech-stack.md`. `ProvenanceTrace` is already a serialisable object carrying the graph fingerprint, so persisting runs is a writer rather than a redesign.
