# Decisions

## KG1 — movement / clinical domain

Deviations from the starting schema in `ASSESSMENT.md:54-56`:

1. **Added `is_a`.** The spec lists movement patterns as a node type but no edge reaching them. Taken literally, those nodes are unreachable.
2. **Split `contraindicated-for` into `contraindicates` + `cautions`.** Absolute vs. relative contraindication is a real two-valued clinical distinction. Two relations put the meaning on the edge rather than in a property a traversal must inspect, and let the hard filter and the ranker run as separate passes with separate provenance sentences — a coach can override a caution, not a contraindication.
3. **Added `affects`, and kept it out of the filter path.** An injury has an anatomical location, and nothing in the schema recorded it. The edge is reference only: safety filtering runs top-down, `Injury -contraindicates-> Pattern <-is_a- Exercise`, because a contraindication is a clinical judgement about movement, not a mechanical consequence of loading a joint — the sample injury's own note says *avoid deep knee flexion under load and plyometrics*, not *avoid the knee*. Deriving contraindications by walking `affects` → `part_of` → `stresses` would exclude every knee-loading exercise, which is both wrong and far more restrictive than the clinician asked for. Anatomy earns its filtering role on the other input, free text: *"her left knee is bothering her"* resolves to the joint and walks `stresses`. `affects` joins the two, so a resolved term can name the recorded injury sitting at it.

4. **`Condition` is its own node, and the contraindication edges hang off it, not off `Injury`.** *"Patellofemoral pain contraindicates plyometrics"* is knowledge about a condition and applies to the next member who presents with it. Keying it to `inj_knee_left` made it member-specific: the SNOMED code had to be copied onto the injury, the rules were re-materialised per case, and the graph could not answer *"what does this condition rule out?"* at all — the condition existed only in a JSON file and a build-time dict. Splitting it puts instance facts on `Injury` (`side`, `status`, `severity`, `since`) and clinical facts on `Condition`, joined by `diagnosed_as`. The filter is one hop longer and still deterministic: `Injury -diagnosed_as-> Condition -contraindicates-> Pattern <-is_a- Exercise`. It is also where severity will modulate strictness later — today a `mild`/`recovering` case inherits the same hard exclusion a `severe`/`active` one would.

   `injuries[]` gains an explicit `condition` to make the join — the same POC shortcut as `Goal.targets`, standing in for LLM extraction from the free-text `notes`. The code is the side-neutral `430725003 Patellofemoral stress syndrome`, not the left-knee-specific concept, or the rules would not transfer to another member.

5. **Collapsed body region, joint, and sub-structure into one `AnatomicalStructure` type.** They form a single hierarchy joined by a single edge that runs nowhere else; three labels for three positions in one taxonomy is a distinction without a difference. SNOMED CT models it the same way — one "Body structure" hierarchy, where knee, patellofemoral joint, and lower limb are all body structures distinguished by subsumption, not by type. Collapsing also makes the traversal direction-agnostic: one transitive `part_of` closure serves both the "lower body" query descending and the "patellar tendon" query ascending.

---

## KG2 — member context

1. **One `has` edge rather than four `has_*`.** An edge earns its own type only when the source/target label pair doesn't already determine the relation — as with KG1's `contraindicates` vs. `cautions`, both Injury → Pattern. Every Member edge is disambiguated by its target label, so a prefix would restate it. `dislikes` and `targets` stay named: they carry meaning ownership doesn't.
2. **`Preference` is one node per key, not one node with five properties.** `dislikes` needs to carry an edge into KG1's `Exercise`; the others are scalar constraints. Splitting keeps that edge attachable without a special case.
3. **`Goal.targets` is a structured key, not parsed from goal text.** Goals carry free text (*"Build lower-body strength"*), from which the muscles a goal trains would have to be inferred. For this POC, `goals[]` gains an explicit `targets: string[]` holding muscle names drawn from the KG1 vocabulary, so `Goal -targets-> Muscle` is a plain string join like every other cross-graph edge — no inference in the build path. **Built out, this would be LLM extraction of structured fields from the free text at ingest; omitted for time.** `targets` may be empty: not every goal is muscular (*"Average 7+ hours of sleep"*), and an empty list is a valid goal, not a resolution failure.

---

## Integration — KG1 ↔ KG2

*2026-08-08*

**One physical graph, two logical subgraphs.** Separate schemas, separate builders, separate docs; one store, with `source: kg1 | kg2` on every node.

- **Every useful query crosses the seam.** `Member -has-> Equipment <-requires- Exercise -is_a-> Pattern <-contraindicates- Injury <-has- Member` is one traversal merged; split, it's four round-trips plus set intersection in app code.
- **Both graphs reference the same node sets** — `Equipment`, `Exercise`, `Muscle`, `Injury`. Two stores means two copies to keep in sync, so these exist once: KG2's builder resolves against KG1 nodes by name rather than creating its own, and reports unmatched names at build time. A silent no-match yields a graph that looks healthy and returns nothing.
