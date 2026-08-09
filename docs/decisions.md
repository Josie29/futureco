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

## KG2 build-out — the longitudinal blocks

*2026-08-08*

5. **The question was never whether a block goes in the graph. It was at what grain.** `ASSESSMENT.md:60` lists chat, biomarkers, labs, workout history, adherence and churn as KG2's contents, and the rubric asks whether the graph is *"doing real work, or semantic search with extra steps"*. Those pull in opposite directions only if membership is the question. It isn't. The rule in item 2 above — a node earns its place by having a relationship to express — was read as excluding biomarkers, because `resting_hr_bpm: 58` looks like a scalar attribute with no edge. It isn't that either. It is an observation whose date the format dropped.

   The data proves it: `weight_trend_kg` is already three dated values, so weight *cannot* be a member property; `sleep_hours_last_7_days` is seven with the dates stripped out; every lab is dated. The JSON holds four different flattenings of one shape — a bare scalar, an undated list, a dated list, and a panel — and un-flattening them is what lets one retrieval read all four. So the rule sharpens rather than bends: **traversed entity** when something points at it or it points at something, **leaf observation** when it is `(metric, value, date)`, **property** when it is a timeless scalar. Nothing is in the graph merely so it can be said to be there, and nothing is left out to avoid the question.

6. **`Session -trained-> MovementPattern`, because the exercise join does not exist.** The nine movements in `workout_history` match **zero** catalog exercises — not one, and not as a substring. No `Hip Thrust`, no `Wall Sit`, no `Band Pull-Apart`; the only `Step-Up` is `Barbell Step Up to Knee-Drive`, needing a barbell she does not own. This is the `preferences.dislikes` failure again, which *Data cleanup* 2 fixed by rewriting the data.

   It is not rewritten here, because `kg2-schema.md` had already predicted the answer and deferred it pending the resolver: the reachable concept is a **pattern**, not an exercise. All nine map cleanly. That is also the right grain independent of the accident: longitudinal reasoning cares that she has trained hip-lift twice this week, not which SKU, and pattern is the axis `is_a` already carries as the one substitutions travel along. The mapping is authored in `session_patterns.json` — the same standing-in-for-LLM-extraction shortcut as `goals[].targets` and `injuries[].condition`, now the third instance — and an unmapped movement fails the build, because a session that silently trained nothing reads exactly like one she skipped.

7. **`mentions` is exact and alias only, and it is not the resolver.** `Resolver.resolve` takes one phrase a coach typed deliberately and leans on fuzzy and embedding passes to bridge wording. A message is a sentence containing zero or more concepts nobody flagged, so those same passes would make a build-time assertion reckless. `resolve/mentions.py` slides a window over normalised text and matches only what is certain — which also means the seed needs no embedding model.

   The guard that stops it firing on noise **cannot be a heuristic**. `car` is the catalog's label for controlled articular rotation and collides with a common English noun; unguarded, every message containing the word links to `Standing Miniband Hip Flexion`. A minimum surface length was the obvious fix and it is wrong: `hip` and `car` are both three characters, `knee`, `core` and `lats` are four, and the member's own `db` is two. So the deny-list is authored, holds one entry, and blocks **canonical names only** — an alias always wins, because an alias is an author stating that these characters mean this concept. That asymmetry is what lets `db` through the guard that stops `car`, and it makes `aliases.json` the escape hatch it already was.

   Laterality is deliberately *not* extracted, departing from *Resolver* 6. There, discarding "left" would change a filter's behaviour and lose a clinical distinction. Here the message text is retrieved verbatim beside the edge, so the side is never lost — only not duplicated onto an edge that would then have to be right about which clause it came from.

8. **`MetricDirection` is separate from the reference band, because resting heart rate proves they are different questions.** The band says whether a value is inside it; the direction says what being outside means. Her 58 bpm sits below the standard adult 60–100 band and that is *favourable*. A bare "outside the range" reading would report an athletic resting pulse as abnormal — to a coach, in a clinical-sounding sentence. So `resting_hr` records only an upper bound, `hrv` and `body_weight` record no band at all (`TREND`, because no defensible population range exists and inventing one is worse than admitting none), and `ferritin` is genuinely two-sided (`BAND`).

   The bands live in `data/authored/metrics.json` rather than in code so that *"is this concerning"* is a graph fact. HDL and body-fat percentage both have sex- or age-adjusted ranges; a second member needs different data, not a different branch. Each row cites its source. The copilot reports values against bands and names what is outside them — it does not interpret, diagnose, or advise, and that is a prompt constraint and a documented limit, not a graph mechanism.

9. **`Goal -measured_by-> Metric` is what stops the observation subgraph being a dead end.** Twenty-eight observations hang one hop off `Member` and nothing walks through them, which is a fair thing for a reviewer to press on. Two answers, and the second is the real one. The `Metric` vertex is shared, so seventeen definitions serve twenty-eight readings and one tool with a metric parameter replaces a reader per JSON key. And `goal_sleep` — empty `targets[]`, the one goal the graph could say nothing about — now reaches its readings, which the console had been faking with a hardcoded `SLEEP_TARGET_HOURS` and a `target_date === null` heuristic. One edge deletes both constants and makes goal progress a traversal.

   `Condition -monitored_by-> Metric` is named as an empty slot rather than built: it is the edge that would make observations traversed *clinically*, and it is unpopulated because patellofemoral pain is not monitored by anything on this panel. Populating it means authoring clinical monitoring claims.

10. **The coach brief is read but not ingested; churn is derived.** `coach_brief` is generated output dated `2026-06-04` — yesterday's answer, not member context. A copilot retrieving a stored conclusion is echoing, which is precisely the failure the rubric names. So the brief, `churn_risk`, `adherence.trend` and `typical_session_min` are computed.

    The block is still parsed for two reasons. `generated_for` is the reference date the entire dataset is relative to. And `churn_risk` is the calibration target — which is how the sample's third reason, *"login frequency down vs. prior month"*, was found to have **no supporting data anywhere in the file**. Two of three reasons fall straight out of the graph; the third cannot be derived because nothing supports it, and a derivation that cannot invent it is the point rather than a shortfall.

11. **`Coach` earns a node because `coaches` is a real edge.** One node and one edge, and it turns the console's mock login into an actual authorization check: holding a member id in a URL is not authority to read that member. The three filler roster members stay *out* of the graph — they carry roster metadata and no clinical detail, and as `Member` nodes with no edges they would be exactly what the grain rule rejects. They live in an authored file and 404 as they do today. An unknown member and a member this coach does not coach both return 404 rather than 403, because a 403 confirms the member exists.

---

## Integration — KG1 ↔ KG2

*2026-08-08*

**One physical graph, two logical subgraphs.** Separate schemas, separate builders, separate docs; one store, with `source: kg1 | kg2` on every node.

- **Every useful query crosses the seam.** `Member -has-> Equipment <-requires- Exercise -is_a-> Pattern <-contraindicates- Condition <-diagnosed_as- Injury <-has- Member` is one traversal merged; split, it's four round-trips plus set intersection in app code.
- **Both graphs reference the same node sets** — `Equipment`, `Exercise`, `Muscle`, `Injury`. Two stores means two copies to keep in sync, so these exist once: KG2's builder resolves against KG1 nodes by name rather than creating its own, and reports unmatched names at build time. A silent no-match yields a graph that looks healthy and returns nothing.

---

## Read API — the coach console's own endpoints

*2026-08-08*

1. **`X-Coach-Id` makes the mock login mean something.** `session.tsx` already claimed *"the API loads the coach from the session"*, and until now nothing did. Every member call carries the header, and `Coach -coaches-> Member` is the whole check. It is still mock auth — the header is self-asserted and a real build replaces it with a verified token — but the *authorization* half is real, and it is the half a graph can express.

   Both an unknown member and one belonging to another coach return **404, not 403**. A 403 confirms the member exists, which turns the id space into something worth enumerating. `/api/coaches` is the one unauthenticated endpoint, because it is the screen a coach reaches before they have an identity to send.

2. **Every figure the console prints is derived at read time, not stored.** Typical session length, sessions this week, goal countdowns, goal measures, churn — all computed from the graph on each request. The console previously computed the same things in `fixtures.ts`, which is why they agreed with the data: they were the data. Moving them server-side is what makes them agree with the *graph*, and the tests assert both against `member-context.json` so a drift in either shows up.

3. **The injury constraint summary is read from the clinical edges.** The authored copy said *"Rules out jumping and landing outright, and flags deep knee bends"* — true when written, and silently wrong the moment a contraindication changes. It is now composed from `Condition -contraindicates|cautions-> Pattern`, so the panel cannot describe a graph it no longer matches. The cost is that it speaks the catalog's vocabulary (*"cardio - plyometric"*) rather than a coach's, which is the same vocabulary the rest of the console already uses.

4. **The churn threshold is measured in sessions, not percentage points.** Written first as a flat 25-point drop, which a test immediately falsified: weekly completion is already normalised against the member's own plan, so on Jordan's four-session week one missed session *is* 25 points — the constant fired on exactly the single slip its own docstring said it should ignore, and would have meant "half a session" for a member training twice a week. The bar is now *more than one planned session's worth*, derived from `training_days_per_week`. Her 50-point fall is two sessions and clears it; a lone 100 → 75 week does not.

5. **Levels are counted, not weighted.** Two or more signals is elevated, one is moderate, none is low. Weights over three binary signals would imply a precision one synthetic member cannot support, and a coach reading *"two signals"* can check both. Absence of data reads as low rather than as risk, so a newly onboarded member does not top the roster.

6. **`as_of` is served, not hardcoded twice.** Nothing in this system means "this week" against a wall clock — the record ends in June 2026, and a real-date anchor empties every window and reports that she has stopped training. The API derives the date from the record and returns it on the member payload; `lib/dates.ts` keeps the literal only as a first-paint fallback. Two hardcoded dates in two languages is how they drift.

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

3. **The rep-duration clamp is removed now that the field is fixed.** The frontend estimator briefly clamped `estimated_rep_duration` to 3–21 seconds a rep, because read as minutes the top of its range was impossible — `Jump Rope - Single-Leg` at 1.9 priced one skip at 114 seconds, and a single tricep extension took 25 of a 50-minute session. That was a workaround for the defect decision 5 diagnoses properly: the column held a *rate*, and inverting it into `estimated_rep_seconds` makes all 50 rows plausible. With the data correct the clamp only capped honest values, so it is gone; the estimator reads seconds and converts. What remains is a fallback for rows where `0` marks the field inapplicable.


4. **Added `injuries[].condition` to `member-context.json`.** The clinical condition is only stated in free-text `notes`. An explicit field makes `Injury -diagnosed_as-> Condition` a plain string join, with no inference in the build path — the same shortcut `goals[].targets` already takes. Built out, both would be LLM extraction at ingest.

5. **`estimated_rep_duration` held a rate, so it was inverted and renamed `estimated_rep_seconds`.** Read as seconds, every value was impossible — a bench press rep at 0.3, *World's Greatest Stretch* at 0.1 — and the ordering ran backwards, the fastest movements carrying the largest numbers. Reciprocated, all 50 land on plausible cadences and three on known ones: jump rope 0.53 s/rep, SkiErg 1.67, bench press 5. Two decimals, not the one the source carried, because 0.53 would round to 0.5 and the inversion would stop being reversible; `0` still marks the field inapplicable. Free now, with the `Exercise` model the only reference — once set duration is computed, the same mistake multiplies where it should divide. Two things are left for their own change: one `is_reps: false` row carries a value, inverted rather than zeroed since that is a data judgement; and `is_bilateral` is inverted the same way this field was, `true` on exactly the single-side rows.

6. **Added `goals[].metric` and `profile.trains_at` to `member-context.json`.** Both are facts the file already states in free text, promoted to structured fields so the build path does no inference. The sleep goal is the one goal with a number instead of muscles and nothing joined it to the number, so a metric id makes `Goal -measured_by-> Metric` a plain string join. `trains_at` is stated inside `preferences.notes` — *"Prefers dumbbell and kettlebell work; trains at home"* — and the console prints it in the member header; parsing it out of the sentence at read time, or inferring it from an equipment list with no machines in it, would both be guessing.

   With these, the same substitution now appears four times: `goals[].targets`, `injuries[].condition`, `goals[].metric`, `profile.trains_at`. That is one pattern applied consistently rather than four separate liberties — **built out, all four are one LLM extraction pass over the free text at ingest**, which is the step this POC omits. They are listed together so the omission is legible as a single missing component.

7. **Two dating assumptions, both recorded because the source omits what it needs.** `sleep_hours_last_7_days` is an undated list, so it is dated backwards from the reference date with the **last element as the most recent** — the reading its own field name implies. Reversed, her sleep trend inverts while every count and average stays identical, which is a defect no total would reveal, so a test pins the direction. And `resting_hr_bpm` and `hrv_ms` are bare scalars where every sibling in the block is dated; they are stamped with the reference date, because an undated observation cannot be plotted, compared, or returned by a windowed query — it would exist in the graph and be invisible to every question asked of it.

8. **`Member.weight_kg` is not copied onto the node.** `biomarkers.weight_trend_kg` records the same fact as a dated series, and the latest observation is the answer. Keeping both gives two numbers that can disagree.

---

## Packaging

1. **`python:3.13-slim`, not alpine.** `onnxruntime` — which `fastembed` depends on — publishes manylinux wheels only. On musl there is no wheel, so pip falls back to compiling from source. Alpine's smaller base is not worth a build that may not finish.

2. **The embedding weights are baked at build time.** fastembed defaults its cache to a directory under the system temp dir, which is the wrong place to leave 87 MB in a container — and would mean a cold `docker compose up` reaching the network on its first vector lookup, breaking the criterion the whole stack was chosen against. `settings.model_cache_dir` defaults to `None` so local development is unchanged; the image sets it. Verified with `docker run --network none`.

3. **The model name is asserted, not just duplicated.** It appears as a Dockerfile build argument and as `EMBEDDING_MODEL` in the source. A build step imports the constant and asserts they agree, so changing one and missing the other fails the build instead of silently re-downloading at first request.

4. **Ownership is set at copy time, never with `chown -R`.** Rewriting mode bits on an existing layer duplicates every file it touches: measured at 674 MB with `COPY --chown` against 849 MB with a later `chown -R`. The model directory cannot stay root-owned, because fastembed writes a tree-cache file beside the weights on load.

5. **Seeding is its own service, not the API's startup.** `seed` runs the build once and exits; `api` waits on `service_completed_successfully`. Folding it into the API would mean every replica racing to build the same graph, and a seed failure surfacing as an unhealthy API rather than as itself. Every write is a `MERGE`, so a second `up` converges.

6. **The API warms the embedder during startup, not on first use.** Loading the model and embedding all 164 concepts costs about a second. Lazily, the first coach request pays it; in the lifespan, no request does — and a container that cannot reach its model fails at boot rather than mid-request.
