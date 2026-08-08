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

## Resolver — free text to canonical concepts

1. **The caller passes the labels it accepts; the resolver never guesses by precedence.** Three names claim more than one label: `lower back` is a Muscle *and*, when a coach reports pain, the lumbar spine; `rotator cuff` is a Muscle and an AnatomicalStructure; `stair climber` and `skierg` are both Exercise and Equipment. A fixed precedence would be silently wrong half the time, and there is no way for a call site to say which reading it meant. So an injury site asks for `AnatomicalStructure` and an equipment site asks for `Equipment`, the pool is filtered **before** scoring, and an unrestricted call that ties across labels declines rather than picking.

2. **Exact and alias are one pass, not two.** Both are certain, so running them in sequence let an exact hit return alone and never meet the alias contradicting it — `lower back` resolved to the Muscle without the lumbar spine ever being considered. Pooled, the ambiguity check sees the conflict.

3. **Thresholds are the midpoints of a swept band, not chosen numbers.** `resolve/calibrate.py` sweeps both thresholds against `data/authored/resolver_cases.json` and reports every pair that passes all 25 cases. Fuzzy passes across **0.80–0.99**, vector across **0.60–0.77**; the committed 0.90 and 0.68 are the midpoints. A threshold one hundredth from failing is lucky, not calibrated. The same file is the pytest fixture, so the numbers and the assertions cannot drift apart.

4. **Calibration falsified the design, which is why it exists.** The plan assumed the vector pass would carry paraphrases like *"overhead press"*. It ranks `upper push - vertical` first — at **0.528**. But `deadlift`, which must not resolve at all, reaches `Barbell` at **0.523**. A five-thousandth gap: no threshold separates them, and a value tuned to split it would be overfitting to two points. `overhead press` became an alias instead, which is what the alias file is for — terms no automatic pass can reach safely.

5. **The vector pass nearly didn't earn its place.** Once the cases were running, none of them exercised it: `shoulder blade` resolves by *fuzzy* at 1.0, because token-set matching scores `shoulder` as a subset of the query. Three terms were then found where it is genuinely the only route — `quadriceps → quads` (fuzzy 0.67, cosine 0.78), `calf → calves` (0.60 / 0.89), `skipping rope → Jump Rope` (0.62 / 0.85). Irregular plurals and dialect. A test asserts every pass is exercised by some case, so a pass cannot quietly become dead weight again.

6. **Laterality is extracted, not stripped.** *"her left knee"* yields `knee` plus `side=left`. The recorded injury is left-sided, so a right-knee complaint must not match it — discarding the word would lose a clinical distinction while appearing to work.

7. **Plurals are left to fuzzy rather than normalised away.** Most muscle names are already plural — `quads`, `triceps`, `glutes` — so stripping a trailing `s` would break more than it fixed.

---

## Safety filter

1. **Queries return evidence, not survivors.** A `WHERE` that drops a row makes it unexplainable, so the catalog query returns all 50 and Python judges. Verdicts are kept for all 50, so *"why no squat?"* has an answer — and the scoring tests need no database.

2. **Three quantities that never convert.** `status` is set membership, `penalty` an integer sum, `fit` goal overlap. No penalty total ever reaches `EXCLUDED` — a property test asserts it. One scalar would hide whether an exercise ranked low for risk or for relevance.

3. **Caution (+3) outranks a flagged structure (+2).** A caution is authored clinical judgement about a movement; an anatomy hit is inference that the exercise touches a joint.

4. **Safety dominates goal fit.** Sort key `(status, penalty, -fit, name)`. Jordan's three best goal-serving exercises are her only cautioned survivors, so they rank last among the eligible — with `fit` visible, so the cost of the caution is legible rather than silently resolved.

5. **The mechanical anatomy path only penalises.** Hard-excluding on `stresses` would strip `Cow Pose` and `World's Greatest Stretch`, the rehab work a patellofemoral protocol wants. Hardness comes from the coach's verb, not the graph.

6. **`affects` annotates and scores nothing.** Ranking is the filter's output, so a weight bump would falsify KG1 item 3. `High Plank Bird Dog` stresses knee and shoulder; a test pins that it scores the same either way.

7. **A request can never waive a contraindication.** Waivability comes from the edge type, checked *before* resolution — reporting "unresolved" would imply better phrasing might work. The agent's instruction schema has no waive verb at all.

8. **Removal counts are reported twice.** Per-reason gives 29/6/2 = 37 across 33 removals, since four have two causes. Attributed (26/6/1) sums to 33, and answers *"dropping the equipment limit returns 26 candidates."*

9. **The joint closure uses two directed legs.** Undirected `part_of*` reaches `ankle` and `hip` from `knee`. A test pins it, because the bug is invisible in the counts and wrong in the plan.

10. **`priority_tier` is not a ranking key here, but stays.** All 50 rows are tier 2 — nothing to rank on, and `kg1-schema.md` named it as one, now corrected. Kept because the uniformity is the sample's, not the field's (same for `is_duration`); a weight later is a `Policy` field, not a schema change.

11. **An injury constrains only while `active` or `recovering`.** Otherwise a resolved injury would contraindicate forever, with nothing saying why.

---

## Data cleanup

Edits to the provided synthetic data, and why each was made rather than worked around in code.

1. **Filled two empty `joints_loaded` lists in `exercises.json`.** Two rows recorded no joints, so they carried no `stresses` edges and no anatomy-driven filter could ever reach them — *"avoid anything loading the knee"* would silently keep them in. An empty list is ambiguous between *loads nothing* and *nobody wrote it down*, and those need opposite handling.

   Movement pattern settles which one this is. *Alternating Dumbbell Decline Bench Press* is `upper push - horizontal`, where all four siblings record `shoulder, elbow`; it is the same movement as *Barbell Decline Bench Press*, which records both. *Lacrosse Ball Upper Back against Wall* is `massage` and `regen`, and all five `regen` siblings record joints. Both are omissions, not facts about the movement, so they are filled: `["shoulder", "elbow"]` and `["thoracic spine"]`.

2. **Repointed `preferences.dislikes` at exercises the catalog stocks.** It read `["Deadlift", "Burpees"]`, and neither exists among the 50 — not as a name, not as a substring — so the edge wrote nothing and the sample could not demonstrate a preference filter at all. Both are replaced with catalog entries that keep the intent and do real work: *One-Kettlebell Hamstring Walkout* is the hip-hinge, and it needs a kettlebell and a mat she owns, so the exclusion is live and independent of her injury; *Vertical Jump to Broad Jump* honours the note *"Dislikes high-impact jumping"* and overlaps the plyometric contraindication, which is what a real chart looks like. The report-rather-than-fail behaviour in KG2 decision 3 stays, because a coach's free text can always miss.

3. **Added `injuries[].condition` to `member-context.json`.** The clinical condition is only stated in free-text `notes`. An explicit field makes `Injury -diagnosed_as-> Condition` a plain string join, with no inference in the build path — the same shortcut `goals[].targets` already takes. Built out, both would be LLM extraction at ingest.

4. **`estimated_rep_duration` held a rate, so it was inverted and renamed `estimated_rep_seconds`.** Read as seconds, every value was impossible — a bench press rep at 0.3, *World's Greatest Stretch* at 0.1 — and the ordering ran backwards, the fastest movements carrying the largest numbers. Reciprocated, all 50 land on plausible cadences and three on known ones: jump rope 0.53 s/rep, SkiErg 1.67, bench press 5. Two decimals, not the one the source carried, because 0.53 would round to 0.5 and the inversion would stop being reversible; `0` still marks the field inapplicable. Free now, with the `Exercise` model the only reference — once set duration is computed, the same mistake multiplies where it should divide. Two things are left for their own change: one `is_reps: false` row carries a value, inverted rather than zeroed since that is a data judgement; and `is_bilateral` is inverted the same way this field was, `true` on exactly the single-side rows.

---

## Packaging

1. **`python:3.13-slim`, not alpine.** `onnxruntime` — which `fastembed` depends on — publishes manylinux wheels only. On musl there is no wheel, so pip falls back to compiling from source. Alpine's smaller base is not worth a build that may not finish.

2. **The embedding weights are baked at build time.** fastembed defaults its cache to a directory under the system temp dir, which is the wrong place to leave 87 MB in a container — and would mean a cold `docker compose up` reaching the network on its first vector lookup, breaking the criterion the whole stack was chosen against. `settings.model_cache_dir` defaults to `None` so local development is unchanged; the image sets it. Verified with `docker run --network none`.

3. **The model name is asserted, not just duplicated.** It appears as a Dockerfile build argument and as `EMBEDDING_MODEL` in the source. A build step imports the constant and asserts they agree, so changing one and missing the other fails the build instead of silently re-downloading at first request.

4. **Ownership is set at copy time, never with `chown -R`.** Rewriting mode bits on an existing layer duplicates every file it touches: measured at 674 MB with `COPY --chown` against 849 MB with a later `chown -R`. The model directory cannot stay root-owned, because fastembed writes a tree-cache file beside the weights on load.

5. **Seeding is its own service, not the API's startup.** `seed` runs the build once and exits; `api` waits on `service_completed_successfully`. Folding it into the API would mean every replica racing to build the same graph, and a seed failure surfacing as an unhealthy API rather than as itself. Every write is a `MERGE`, so a second `up` converges.

6. **The API warms the embedder during startup, not on first use.** Loading the model and embedding all 164 concepts costs about a second. Lazily, the first coach request pays it; in the lifespan, no request does — and a container that cannot reach its model fails at boot rather than mid-request.
