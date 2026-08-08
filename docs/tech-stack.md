# Tech Stack — futureco

Selection criteria, in priority order: (1) the safety filter must be a deterministic graph traversal, so nothing may put an LLM between a request and a Cypher result; (2) `docker compose up` must work from a cold clone weeks later, so no account signups and no free tiers that can lapse; (3) one-day build, so setup cost and boilerplate are first-class; (4) typed contracts end to end.

| Layer | Component | Choice | Reason |
|---|---|---|---|
| Data | Graph store | Neo4j 5 Community (official Docker image) | Property-graph semantics fit the schema; variable-length `part_of` traversal is a first-class query, not a recursive CTE |
| Data | Query language | Cypher | The traversal *is* the deliverable — it must be readable and auditable by a reviewer |
| Backend | Language | Python 3.12 | Where the graph, embedding, and Anthropic tooling all live |
| Backend | Web framework | FastAPI | Pydantic-native typed contracts and generated OpenAPI, which is what "typed contracts" is being evaluated on |
| Backend | Contracts | Pydantic v2 models shared by HTTP responses and agent tool schemas | One definition of a `WorkoutPlan` / `ProvenanceTrace` for both the API and the tool JSON schema |
| Backend | Packaging | uv + `pyproject.toml` + `uv.lock` | Drop-in pip replacement, locks transitive deps, and cuts the Docker layer build to seconds |
| AI | LLM | `claude-opus-5` via the official `anthropic` SDK | Latest and most capable; drives planning and copilot synthesis, never the safety decision |
| AI | Agent runtime | Anthropic SDK Tool Runner (`client.beta.messages.tool_runner`) with `@beta_tool` functions wrapping Cypher | Supplies the loop with no framework in between; per-turn hooks are the natural interception point for the provenance trace |
| Frontend | Framework | Vite + React 19 + TypeScript | Every byte is served by the Python API, so SSR earns nothing; Vite is a static bundle behind nginx |
| Frontend | Styling / components | Tailwind CSS v4 + shadcn/ui | Tailwind's 0.25rem scale and CSS-variable tokens match house rules; shadcn is copy-in source, not a runtime dependency |
| Frontend | Charts | Recharts | Declarative React components for adherence/sleep/message-pattern series; the fastest path from data to a readable chart |
| Observability | Trace store | Local Postgres (official Docker image), one append-only table per run holding graph queries, LLM calls, and timings | Self-hosted and queryable with SQL — no vendor account, no fees, no free tier to expire |
| Infra | Local run | Docker Compose — `neo4j`, `postgres`, `api`, `web`; API waits on healthchecks, seeds, then serves | `docker compose up` is the one command; nothing to install, nothing to expire |

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
| Contracts | dataclasses / attrs / TypedDict | No runtime validation and no JSON Schema export, so the agent tool definitions would be a second hand-maintained copy |
| Packaging | Poetry | Slower resolution and heavier ceremony than uv for the same lockfile guarantee |
| Packaging | pip-tools / bare `requirements.txt` | Weaker transitive locking and a noticeably slower image build |
| LLM | `claude-haiku-4-5` for resolution or filtering | Both are deterministic graph work — introducing a model there is the failure mode the spec warns against |
| LLM | Non-Anthropic provider | No reason to leave the SDK whose tool runner supplies the agent loop |
| Agent runtime | LangGraph | State-machine abstraction whose learning surface would consume more of the day than the knowledge graph |
| Agent runtime | LangChain `GraphCypherQAChain` | Generates Cypher with an LLM — the exact non-deterministic path the safety requirement forbids |
| Agent runtime | Pydantic AI | Good typed fit, but the Anthropic SDK's tool runner already supplies the loop and hooks with one less layer |
| Agent runtime | Claude Agent SDK | Packages the Claude Code harness — built-in filesystem and bash tools this product has no use for |
| Agent runtime | Hand-written tool loop | The runner's per-turn hooks already provide the interception point; writing the loop adds risk without control |
| Frontend | Next.js | App Router SSR/RSC adds a Node server container and build complexity for a client that only calls a Python API |
| Frontend | Create React App | Deprecated and unmaintained |
| UI kit | Mantine / MUI | Theme system and bundle weight for roughly eight components |
| UI kit | Hand-rolled CSS | Spends build hours on layout rather than on the graph |
| Charts | visx | Lower-level primitives — more code per chart than a day allows |
| Charts | Chart.js | Imperative canvas API that fits awkwardly into React and renders nothing inspectable in the DOM |
| Observability | Langfuse (self-hosted) | Self-hosted, but three more containers — server, Postgres, ClickHouse |
| Observability | LangSmith | SaaS signup, a second key, and usage-based pricing |
| Observability | OpenTelemetry + Jaeger | A collector and UI container to trace a single-process application, with traces that vanish on restart |
| Observability | JSON logs to stdout only | Nothing to query after the fact — "why was this exercise filtered" becomes a grep |
| Local run | Makefile + local installs | Reviewer must supply Python 3.12, Node, a JVM, and Neo4j before anything runs |
| Local run | Devcontainer | Ties the one-command promise to a specific editor |
| Local run | Hosted demo (Vercel + Railway/Aura) | Secrets to manage and a live dependency that rots between submission and review |

## Open sub-decisions

- **Trace table schema** — one wide append-only row per event versus a run/event pair of tables, and whether the provenance trace is derived from it or stored separately. Resolve when the generation runtime is defined.
- **Chart data shape** — whether the copilot returns chart series as a typed tool result the frontend renders, or as a spec the frontend interprets. Resolve when the copilot's tool set is defined.
