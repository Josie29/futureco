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
```

## Tests

The scoring, resolver and policy tests are pure and need neither Docker nor a key; the traversal tests need Neo4j up.

```bash
docker compose up -d neo4j
cd backend && uv sync && uv run pytest
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
| `backend/src/api/` | FastAPI service |
| `data/authored/` | Hand-authored anatomy, contraindications, aliases, resolver cases |

## Status

The knowledge graphs, concept resolver, safety filter and API container are built and tested. The agentic workout generator and the member-context copilot are not yet implemented; the architecture write-up, worked examples and trade-offs land with them.
