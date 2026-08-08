# Decisions

## KG1 — movement / clinical domain

Deviations from the starting schema in `ASSESSMENT.md:54-56`:

1. **Added `is_a`.** The spec lists movement patterns as a node type but no edge reaching them. Taken literally, those nodes are unreachable.
2. **Split `contraindicated-for` into `contraindicates` + `cautions`.** Absolute vs. relative contraindication is a real two-valued clinical distinction. Two relations put the meaning on the edge rather than in a property a traversal must inspect, and let the hard filter and the ranker run as separate passes with separate provenance sentences — a coach can override a caution, not a contraindication.
3. **Collapsed body region, joint, and sub-structure into one `AnatomicalStructure` type.** They form a single hierarchy joined by a single edge that runs nowhere else; three labels for three positions in one taxonomy is a distinction without a difference. SNOMED CT models it the same way — one "Body structure" hierarchy, where knee, patellofemoral joint, and lower limb are all body structures distinguished by subsumption, not by type. Collapsing also makes the traversal direction-agnostic: one transitive `part_of` closure serves both the "lower body" query descending and the "patellar tendon" query ascending.

---

## KG2 — member context

1. **One `has` edge rather than four `has_*`.** An edge earns its own type only when the source/target label pair doesn't already determine the relation — as with KG1's `contraindicates` vs. `cautions`, both Injury → Pattern. Every Member edge is disambiguated by its target label, so a prefix would restate it. `dislikes` and `targets` stay named: they carry meaning ownership doesn't.
2. **`Preference` is one node per key, not one node with five properties.** `dislikes` needs to carry an edge into KG1's `Exercise`; the others are scalar constraints. Splitting keeps that edge attachable without a special case.
3. **`Goal.targets` is a structured key, not parsed from goal text.** Goals carry free text (*"Build lower-body strength"*), from which the muscles a goal trains would have to be inferred. For this POC, `goals[]` gains an explicit `targets: string[]` holding muscle names drawn from the KG1 vocabulary, so `Goal -targets-> Muscle` is a plain string join like every other cross-graph edge — no inference in the build path. **Built out, this would be LLM extraction of structured fields from the free text at ingest; omitted for time.** `targets` may be empty: not every goal is muscular (*"Average 7+ hours of sleep"*), and an empty list is a valid goal, not a resolution failure.

---

## Integration — KG1 ↔ KG2

*2026-08-08*

**Decision.** One store, two logical subgraphs: separate schemas, separate builders, separate docs. Every node carries `source: kg1 | kg2`. Shared nodes (`Equipment`, `Exercise`, `Muscle`, `Injury`) exist once — KG2's builder resolves against KG1 nodes by name rather than creating its own.

**Why.**

- **Every useful query crosses the seam.** `Member -has-> Equipment <-requires- Exercise -is_a-> Pattern <-contraindicates- Injury <-has- Member` is one traversal merged; split, it's four round-trips plus set intersection in app code — a join engine rebuilt by hand.
- **`Injury` straddles.** Declared in KG2 (member self-report), but its `contraindicates` / `cautions` edges are KG1 clinical knowledge. Two stores force an owner, and either choice strands an edge without both endpoints.
- The genuine arguments for splitting — different lifecycles (KG1 static and shared across members, KG2 per-member and mutable), different provenance (SNOMED-grounded vs. free-text-derived), per-member deletion — are all served by `source` plus member-scoped IDs, at no traversal cost.

**Consequences.**

- Build order is fixed: KG1 first, KG2 resolves against it.
- Name resolution is the failure surface. A silent no-match yields a disconnected graph that looks healthy and returns empty results, so unmatched names are collected and reported at build time, never skipped.

| Join | Key | Risk |
|---|---|---|
| `equipment_available[]` → `Equipment` | name | Spelling drift vs. catalog |
| `preferences.dislikes[]` → `Exercise` | name | `"Burpees"` may have **no catalog entry** — likeliest miss |
| `goals[].targets[]` → `Muscle` | name | Empty list is valid — no match attempted, not a failure |
