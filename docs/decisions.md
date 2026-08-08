# Decisions

## KG1 — movement / clinical domain

Deviations from the starting schema in `ASSESSMENT.md:54-56`:

1. **Added `is_a`.** The spec lists movement patterns as a node type but no edge reaching them. Taken literally, those nodes are unreachable.
2. **Split `contraindicated-for` into `contraindicates` + `cautions`.** Absolute vs. relative contraindication is a real two-valued clinical distinction. Two relations put the meaning on the edge rather than in a property a traversal must inspect, and let the hard filter and the ranker run as separate passes with separate provenance sentences — a coach can override a caution, not a contraindication.
3. **Added `affects`, and kept it out of the filter path.** An injury has an anatomical location, and nothing in the schema recorded it. The edge is reference only: safety filtering runs top-down, `Injury -diagnosed_as-> Condition -contraindicates-> Pattern <-is_a- Exercise`, because a contraindication is a clinical judgement about movement, not a mechanical consequence of loading a joint — the sample injury's own note says *avoid deep knee flexion under load and plyometrics*, not *avoid the knee*. Deriving contraindications by walking `affects` → `part_of` → `stresses` would exclude every knee-loading exercise, which is both wrong and far more restrictive than the clinician asked for. Anatomy earns its filtering role on the other input, free text: *"her left knee is bothering her"* resolves to the joint and walks `stresses`. `affects` joins the two, so a resolved term can name the recorded injury sitting at it.

4. **`Condition` is its own node, and the contraindication edges hang off it, not off `Injury`.** *"Patellofemoral pain contraindicates plyometrics"* is knowledge about a condition and applies to the next member who presents with it. Keying it to `inj_knee_left` made it member-specific: the SNOMED code had to be copied onto the injury, the rules were re-materialised per case, and the graph could not answer *"what does this condition rule out?"* at all — the condition existed only in a JSON file and a build-time dict. Splitting it puts instance facts on `Injury` (`side`, `status`, `severity`, `since`) and clinical facts on `Condition`, joined by `diagnosed_as`. The filter is one hop longer and still deterministic: `Injury -diagnosed_as-> Condition -contraindicates-> Pattern <-is_a- Exercise`. It is also where severity will modulate strictness later — today a `mild`/`recovering` case inherits the same hard exclusion a `severe`/`active` one would.

   `injuries[]` gains an explicit `condition` to make the join — the same POC shortcut as `Goal.targets`, standing in for LLM extraction from the free-text `notes`. The code is the side-neutral `430725003 Patellofemoral stress syndrome`, not the left-knee-specific concept, or the rules would not transfer to another member.

5. **Collapsed body region, joint, and sub-structure into one `AnatomicalStructure` type.** They form a single hierarchy joined by a single edge that runs nowhere else; three labels for three positions in one taxonomy is a distinction without a difference. SNOMED CT models it the same way — one "Body structure" hierarchy, where knee, patellofemoral joint, and lower limb are all body structures distinguished by subsumption, not by type. Collapsing also makes the traversal direction-agnostic: one transitive `part_of` closure serves both the "lower body" query descending and the "patellar tendon" query ascending.

---

## KG2 — member context

1. **One `has` edge rather than three `has_*`.** An edge earns its own type only when the source/target label pair doesn't already determine the relation — as with KG1's `contraindicates` vs. `cautions`, both Condition → Pattern. Every Member edge is disambiguated by its target label, so a prefix would restate it. `dislikes` and `targets` stay named: they carry meaning ownership doesn't.
2. **No `Preference` node; only `dislikes` is modelled, straight from `Member`.** An earlier pass gave each preference key its own node, so that `dislikes` had somewhere to hang an edge into KG1's `Exercise`. Rendered, that produced five identically-labelled neighbours of `Member` — `preferred_session_minutes`, `training_days_per_week`, `preferred_days`, `notes` — none of which names another entity or carries any edge. They were nodes only to keep the fifth one company.

   A node earns its place by having a relationship to express. These have none, so they stay in `member-context.json`, which is where the copilot reads them from regardless, and `dislikes` becomes `Member -dislikes-> Exercise` directly. Five nodes and five edges removed, with nothing the graph could previously answer now unanswerable. `preferred_session_minutes` would become a `Member` property, not a node, if the generator ever wants it as a default.
3. **Unmatched `dislikes` report; every other cross-graph join fails the build.** The rule elsewhere is that an unresolved name stops the build, because it means the graph misleads — a severed hierarchy, or a contraindication that never reaches its movement. A dislike is the one case where a miss is benign: it is free text a coach typed, and naming a movement this catalog does not stock makes the preference no less true. Nothing is silently permitted, there is simply nothing to exclude. The build names the misses so they are visible rather than absent.

4. **`Goal.targets` is a structured key, not parsed from goal text.** Goals carry free text (*"Build lower-body strength"*), from which the muscles a goal trains would have to be inferred. For this POC, `goals[]` gains an explicit `targets: string[]` holding muscle names drawn from the KG1 vocabulary, so `Goal -targets-> Muscle` is a plain string join like every other cross-graph edge — no inference in the build path. **Built out, this would be LLM extraction of structured fields from the free text at ingest; omitted for time.** `targets` may be empty: not every goal is muscular (*"Average 7+ hours of sleep"*), and an empty list is a valid goal, not a resolution failure.

---

## Integration — KG1 ↔ KG2

*2026-08-08*

**One physical graph, two logical subgraphs.** Separate schemas, separate builders, separate docs; one store, with `source: kg1 | kg2` on every node.

- **Every useful query crosses the seam.** `Member -has-> Equipment <-requires- Exercise -is_a-> Pattern <-contraindicates- Condition <-diagnosed_as- Injury <-has- Member` is one traversal merged; split, it's four round-trips plus set intersection in app code.
- **Both graphs reference the same node sets** — `Equipment`, `Exercise`, `Muscle`, `Injury`. Two stores means two copies to keep in sync, so these exist once: KG2's builder resolves against KG1 nodes by name rather than creating its own, and reports unmatched names at build time. A silent no-match yields a graph that looks healthy and returns nothing.

---

## Data cleanup

Edits to the provided synthetic data, and why each was made rather than worked around in code.

1. **Filled two empty `joints_loaded` lists in `exercises.json`.** Two rows recorded no joints, so they carried no `stresses` edges and no anatomy-driven filter could ever reach them — *"avoid anything loading the knee"* would silently keep them in. An empty list is ambiguous between *loads nothing* and *nobody wrote it down*, and those need opposite handling.

   Movement pattern settles which one this is. *Alternating Dumbbell Decline Bench Press* is `upper push - horizontal`, where all four siblings record `shoulder, elbow`; it is the same movement as *Barbell Decline Bench Press*, which records both. *Lacrosse Ball Upper Back against Wall* is `massage` and `regen`, and all five `regen` siblings record joints. Both are omissions, not facts about the movement, so they are filled: `["shoulder", "elbow"]` and `["thoracic spine"]`.

2. **Repointed `preferences.dislikes` at exercises the catalog stocks.** It read `["Deadlift", "Burpees"]`, and neither exists among the 50 — not as a name, not as a substring — so the edge wrote nothing and the sample could not demonstrate a preference filter at all. Both are replaced with catalog entries that keep the intent and do real work: *One-Kettlebell Hamstring Walkout* is the hip-hinge, and it needs a kettlebell and a mat she owns, so the exclusion is live and independent of her injury; *Vertical Jump to Broad Jump* honours the note *"Dislikes high-impact jumping"* and overlaps the plyometric contraindication, which is what a real chart looks like. The report-rather-than-fail behaviour in KG2 decision 3 stays, because a coach's free text can always miss.

3. **Added `injuries[].condition` to `member-context.json`.** The clinical condition is only stated in free-text `notes`. An explicit field makes `Injury -diagnosed_as-> Condition` a plain string join, with no inference in the build path — the same shortcut `goals[].targets` already takes. Built out, both would be LLM extraction at ingest.
