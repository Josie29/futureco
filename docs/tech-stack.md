# Tech Stack — futureco

Selection criteria, in priority order: (1) the safety filter must be a deterministic graph traversal, so nothing may put an LLM between a request and a Cypher result; (2) `docker compose up` must work from a cold clone weeks later, so no account signups and no free tiers that can lapse; (3) one-day build, so setup cost and boilerplate are first-class; (4) typed contracts end to end.

| Layer | Component | Choice | Reason |
|---|---|---|---|
| Data | Graph store | Neo4j 5 Community (official Docker image) | Property-graph semantics fit the schema; variable-length `part_of` traversal is a first-class query, not a recursive CTE |
| Data | Query language | Cypher | The traversal *is* the deliverable — it must be readable and auditable by a reviewer |
| Backend | Language | Python 3.12 | Where the graph, embedding, and Anthropic tooling all live |
| Backend | Web framework | FastAPI | Pydantic-native typed contracts and generated OpenAPI, which is what "typed contracts" is being evaluated on |
| Backend | Contracts | Pydantic v2 models shared by the domain, the HTTP responses and the model's output schema | One definition of a `Verdict` or an `EvidencePath`, whether it is being scored, serialised, or filled in by `messages.parse()` |
| Backend | Packaging | uv + `pyproject.toml` + `uv.lock` | Drop-in pip replacement, locks transitive deps, and cuts the Docker layer build to seconds |
| AI | LLM | `claude-opus-5` via the official `anthropic` SDK | Latest and most capable; drives planning and copilot synthesis, never the safety decision |
| AI | Generator runtime | One `client.messages.parse()` call into a Pydantic schema, no framework | Extraction is the only model step, so there is no loop to orchestrate — see `decisions.md`, *Agent runtime* |
| AI | Copilot runtime | Anthropic SDK Tool Runner (`client.beta.messages.tool_runner`) | Open-ended retrieval over KG2 does need a loop. Nine typed tools over constant Cypher — the model picks the tool, never writes the query |
| Frontend | Framework | Vite + React 19 + TypeScript | Every byte is served by the Python API, so SSR earns nothing — the bundle is static files FastAPI hands out, with no second web server in the stack |
| Frontend | Styling / components | Tailwind CSS v4 + shadcn/ui | Tailwind's 0.25rem scale and CSS-variable tokens match house rules; shadcn is copy-in source, not a runtime dependency |
| Frontend | Charts | Recharts | Declarative React components for adherence/sleep/message-pattern series; the fastest path from data to a readable chart |
| Resolver | Fuzzy pass | `rapidfuzz`, `token_set_ratio` | Canonical names are multi-word, so a coach's single word must score against the token it shares, not the whole string |
| Resolver | Vector pass | `fastembed` (ONNX, all-MiniLM-L6-v2), cosine over an in-memory numpy matrix | 164 concepts is ~250 KB of vectors; an index would be lifecycle for nothing, and in-process keeps the resolver testable with no database |
| Testing | Backend | `pytest`, cases driven from `data/authored/resolver_cases.json` | One file calibrates the thresholds and asserts them, so the two cannot drift |
| Observability | Trace store | Local Postgres 17 (official Docker image), one append-only row per run holding spans, graph queries, LLM calls and timings | Self-hosted and queryable with SQL — no vendor account, no fees, no free tier to expire. Also holds `plan_runs`, the lineage an adjustment refines from |
| Infra | Local run | Docker Compose — `neo4j` and `postgres`, a one-shot `seed`, then `api`, which serves the built console too | `docker compose up` is genuinely the one command; nothing to install, nothing to expire |
| Infra | API image | Multi-stage `python:3.13-slim`, embedding weights baked at build time, console bundle built in a `node:22-alpine` stage | Runtime needs no network and no Node; see `decisions.md`, *Packaging* |

## Rejected alternatives

| Component | Option | Why not |
|---|---|---|
| Graph store | ArangoDB / Memgraph | Cypher-compatible or close, but Neo4j's docs and Browser are what a reviewer can inspect the graph with |
| Graph store | Postgres + recursive CTEs | The `part_of` closure and multi-hop safety join are the point; expressing them as SQL buries the reasoning |
| Graph store | Neo4j Aura free tier | Account signup, credentials in the README, and instances pause after days of inactivity |
| Query language | Gremlin / GraphQL over the graph | Cypher is Neo4j's native language; anything else adds a translation layer over the queries being graded |
| Web framework | Litestar | Genuinely comparable on typing and speed; smaller ecosystem and no offsetting advantage here |
| Web framework | Django / django-ninja | ORM, migrations, and admin for a system with no relational domain model |
| Web framework | Flask | No typed request/response contracts or generated OpenAPI without bolting on the same libraries |
| Contracts | dataclasses / attrs / TypedDict | No runtime validation and no JSON Schema export, so the model's output schema would be a second hand-maintained copy |
| Packaging | Poetry | Slower resolution and heavier ceremony than uv for the same lockfile guarantee |
| Packaging | pip-tools / bare `requirements.txt` | Weaker transitive locking and a noticeably slower image build |
| LLM | `claude-haiku-4-5` for resolution or filtering | Both are deterministic graph work — introducing a model there is the failure mode the spec warns against |
| LLM | Non-Anthropic provider | No reason to leave the SDK that already supplies schema-validated structured output |
| Agent runtime | LangGraph | A state machine for a straight line, and its learning surface would consume more of the day than the knowledge graph |
| Agent runtime | LangChain `GraphCypherQAChain` | Generates Cypher with an LLM — the exact non-deterministic path the safety requirement forbids |
| Agent runtime | Pydantic AI | Typed output is already guaranteed by `messages.parse()` against a Pydantic model; the framework would add a layer over nothing |
| Agent runtime | Claude Agent SDK | Packages the Claude Code harness — built-in filesystem and bash tools this product has no use for |
| Agent runtime | Hand-written tool loop | There is no loop: the generator makes exactly one model call, and the copilot will use the runner |
| Frontend | Next.js | App Router SSR/RSC adds a Node server container and build complexity for a client that only calls a Python API |
| Frontend | Create React App | Deprecated and unmaintained |
| UI kit | Mantine / MUI | Theme system and bundle weight for roughly eight components |
| UI kit | Hand-rolled CSS | Spends build hours on layout rather than on the graph |
| Charts | visx | Lower-level primitives — more code per chart than a day allows |
| Charts | Chart.js | Imperative canvas API that fits awkwardly into React and renders nothing inspectable in the DOM |
| Fuzzy pass | `difflib` (stdlib) | Sequence-ratio only, no token-set: scores `squats` against `quads` at 0.73 while missing `lower push - squat` entirely |
| Fuzzy pass | Postgres `pg_trgm` | A network round-trip per candidate against a 164-row vocabulary already in memory |
| Vector pass | `sentence-transformers` | Pulls PyTorch. Measured: the whole venv is 160 MB with fastembed and no CUDA; torch alone is an order of magnitude more |
| Vector pass | Neo4j native vector index | Correct at 100k nodes; here it adds index lifecycle for 250 KB and makes the resolver untestable without a live database |
| Vector pass | Voyage / OpenAI embeddings API | A second key, a network round-trip inside the latency budget, and a free tier that can lapse before review |
| Observability | Langfuse (self-hosted) | Self-hosted, but three more containers — server, Postgres, ClickHouse |
| Observability | LangSmith | SaaS signup, a second key, and usage-based pricing |
| Observability | OpenTelemetry + Jaeger | A collector and UI container to trace a single-process application, with traces that vanish on restart |
| Observability | JSON logs to stdout only | Nothing to query after the fact — "why was this exercise filtered" becomes a grep |
| Local run | Makefile + local installs | Reviewer must supply Python 3.12, Node, a JVM, and Neo4j before anything runs |
| Local run | Devcontainer | Ties the one-command promise to a specific editor |
| Local run | Hosted demo (Vercel + Railway/Aura) | Secrets to manage and a live dependency that rots between submission and review |

## Resolved sub-decisions

- **Trace table schema** — **one wide append-only row per run**, spans as `JSONB`. Spans are only ever written with their run and only ever read as a whole waterfall, so a run/event pair of tables would buy a join and cost the atomic write. The provenance trace stays separate and is *not* derived from it: `ProvenanceTrace` is the plan's own audit artifact and has to survive whether or not anything was traced.
- **Chart data shape** — **a typed tool result the frontend renders.** The model returns a `kind` and, for a metric chart, a `metric_id`; `copilot/charts.py` reads the numbers from the graph. A model that could emit data points could emit a plausible trend that never happened, and a chart is the most credible thing on the page.
