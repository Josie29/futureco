# FutureCo — knowledge-graph-backed coach dashboard

A coach-facing dashboard over two knowledge graphs: **KG1**, the movement and clinical domain, and **KG2**, one member's context. Safety is enforced by deterministic graph traversal, never by prompt instruction — the filter takes a typed constraint set, not a string, so no language model has a path around it.

Full spec in [`ASSESSMENT.md`](./ASSESSMENT.md). Synthetic data only.

## Run it

```bash
cp .env.example .env      # optional — every value has a working default
docker compose up
```

That builds the image, starts Neo4j, seeds both graphs (**224 nodes, 538 edges**), and serves the API. Nothing else to install and no network needed at runtime — the embedding model is baked into the image at build time.

| Service | URL | Notes |
|---|---|---|
| API | http://localhost:8000 | `/health`, `/api/resolve`, the member read surface, and `/docs` for the OpenAPI browser |
| Neo4j Browser | http://localhost:7474 | `neo4j` / `futureco-local` |

**Prerequisites:** Docker. An `ANTHROPIC_API_KEY` is optional — everything above is deterministic and runs without one.

If a port is already taken, set `API_PORT`, `NEO4J_HTTP_PORT` or `NEO4J_BOLT_PORT` in `.env`. The seed is idempotent, so `docker compose up` a second time converges rather than duplicating.

Try it:

```bash
curl localhost:8000/health
curl "localhost:8000/api/resolve?term=pecs"          # alias  -> chest
curl "localhost:8000/api/resolve?term=deadlifts"     # declines, and says why

# The read surface. The coach header is mock auth, but the check is real:
# a member is readable only when a `coaches` edge joins her to that coach.
curl localhost:8000/api/coaches
curl -H "X-Coach-Id: coach_01HXSAM" localhost:8000/api/members
curl -H "X-Coach-Id: coach_01HXSAM" localhost:8000/api/members/mbr_01HX9JORDAN
curl -H "X-Coach-Id: coach_nobody"  localhost:8000/api/members/mbr_01HX9JORDAN   # 404, not 403
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
| `backend/src/resolve/` | Three-pass concept resolver, and the mention scanner over free text |
| `backend/src/safety/` | The deterministic filter, its policy weights, and provenance |
| `backend/src/api/` | FastAPI service |
| `data/authored/` | Hand-authored anatomy, contraindications, aliases, resolver cases, metric bands, session-pattern mappings, coaches |

## Status

Both knowledge graphs are built and tested. KG2 now holds the member's whole record — sessions, chat, biomarkers, labs and adherence — at three grains: traversed entities, leaf observations, and node properties. `docs/kg2-schema.md` records which block lands where and why.

The concept resolver, safety filter and API container are built and tested. The member-context copilot is in progress; the agentic workout generator is a separate stream. The architecture write-up, worked examples and trade-offs land with them.
