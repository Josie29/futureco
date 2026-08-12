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

9. **Both of those are now fixed, because the alternative was code apologising for data.** `is_bilateral` is flipped on all 50 rows so it is `true` for the 32 bilateral movements, and *Kneeling Stability Ball Lat Stretch* is zeroed to join the seven other `is_reps: false` rows. Two invariants hold that did not before: `is_bilateral` is exactly `side is None`, and `is_reps: false` is exactly `estimated_rep_seconds == 0`.

   The reason to do it here rather than route around it: the planner needs *"is this trained one side at a time"* and *"is this held"* on every exercise it doses. Reading the fields as shipped meant a derived property, a paragraph explaining the inversion, and a test walking the package's syntax tree to stop anyone reading the honest-looking field by mistake — three pieces of code, none of which say anything about training. Reading them fixed is `not is_bilateral` and `not is_reps`. Laterality is a third of a session's scheduled seconds, so a field that means its own opposite is not a wart to document; it is a bug waiting for whoever forgets the paragraph.

   `bilateral_pair_id` stays as provided and stays unused: it holds 18 distinct ids across the 18 unilateral rows, one apiece, so it pairs nothing and there is no correct value to substitute. Recorded rather than invented, as `priority_tier` and `is_duration` are.

---

## Copilot — retrieval over KG2

*2026-08-09*

1. **Nine typed tools over module-constant Cypher; no model writes a query.** `tech-stack.md` rejected `GraphCypherQAChain` for exactly this, and the rejection has to survive contact with an actual agent. The model chooses which tool to call and with what arguments; the Cypher is a constant in `copilot/queries.py`. That keeps the safety property the whole system is built on — there is no typed path from prose to a traversal — on the surface most likely to erode it.

2. **Thinking stays on, and `effort` is the cost lever instead.** Claude Opus 5 has a documented failure mode with thinking disabled: a tool call is written into the visible text rather than emitted as a `tool_use` block. The turn succeeds, the call never runs, and nothing errors. For a copilot whose entire output is tool-driven retrieval that failure is silent and total — an answer composed from no data, indistinguishable from one composed from all of it. `effort: low` buys most of the same latency and token saving without it.

3. **Charts are assembled server-side; the model names one, it never draws one.** It returns a `kind` and, for a metric chart, a `metric_id`; `charts.py` reads the numbers from the graph. So the worst a wrong request can do is show the wrong *true* chart. A model able to emit data points could produce a plausible trend that never happened, and a chart is the most credible thing on the page.

4. **Citations are checked against what this run retrieved, not against what exists.** The allowlist is the set of message ids the tools actually returned. A model naming a real message it was never shown is still asserting a source it does not have, and the console renders citations as clickable evidence. An id that fails the check is dropped and the run is marked degraded.

   This is the *only* claim in an answer that can be mechanically verified, and the limit is worth stating plainly: **figures inside prose are not checked.** A model can misquote a number it was correctly given, and nothing here catches that. Charts and citations are verified; sentences are not.

5. **Without a key the same retrieval runs, and the answer says nothing interpreted it.** The alternative was a scripted stand-in, which works for the generator — extraction is its entire model surface, so the plans come out identical — and cannot work here, because synthesis *is* the copilot's output. So the keyless path runs the same tools against the same graph and renders what came back: readings, series, cited messages, composed by fixed templates that state facts and draw no conclusions. Reading a decline as a churn signal is inference, and inference is what the key buys. Keeping that line sharp is what makes the banner honest.

   Routing without a model is keyword-based and named `Intent` so nobody mistakes it for understanding. Metrics are matched from the graph's own index rather than a hardcoded list, so every metric she has readings for is reachable — asking about ferritin works without the word appearing anywhere in the router.

6. **`degraded` is a field on every answer, not a log line.** Synthesis unavailable, a citation dropped, the model declined, a tool failed mid-run — all four produce an answer that is less than a full one, and all four render as a banner above the text. A partial answer that looks whole is the worst thing this surface can return, which is also why the same condition sets `SpanStatus.DEGRADED` on the run.

7. **Single agent, deliberately.** A deterministic pre-pass scans the question for concepts, one tool-running agent sits in the middle, and a deterministic post-pass validates citations and assembles charts. Splitting the middle into a retriever and a synthesiser would be two prompts pretending to be an architecture. The multi-agent workflow `ASSESSMENT.md:5` calls core belongs where the stages genuinely differ — planning, safety, dosing — which is the generator.

8. **Span emission ships; the durable store and the Traces surface do not.** A `TraceStore` protocol with a bounded in-memory implementation, and every copilot run recorded — the Cypher each read ran, its row count, the tool loop, token counts. That much is not optional: a nine-tool agent against a five-second budget is undebuggable without it.

   What does not ship is the Postgres table `tech-stack.md` chose, or the `/api/traces` endpoints. Both are written and left unmounted, because the generator is the bigger span producer and should shape the schema, and because a trace list holding only copilot runs would be worse than the fixture the console reads today — it would look complete while showing half the runs. In-memory traces vanish on restart, which is the exact criticism `tech-stack.md` levels at the rejected Jaeger option; that is why this is staged rather than chosen.

9. **The copilot answers "why can't she squat?" from the same edges the filter enforces.** `clinical_picture` walks `Injury -diagnosed_as-> Condition -contraindicates|cautions-> Pattern`, which is what `safety.filter` reads. One source of truth for the safety claim, so an explanation here cannot drift from an exclusion there.

---

## Packaging

1. **`python:3.13-slim`, not alpine.** `onnxruntime` — which `fastembed` depends on — publishes manylinux wheels only. On musl there is no wheel, so pip falls back to compiling from source. Alpine's smaller base is not worth a build that may not finish.

2. **The embedding weights are baked at build time.** fastembed defaults its cache to a directory under the system temp dir, which is the wrong place to leave 87 MB in a container — and would mean a cold `docker compose up` reaching the network on its first vector lookup, breaking the criterion the whole stack was chosen against. `settings.model_cache_dir` defaults to `None` so local development is unchanged; the image sets it. Verified with `docker run --network none`.

3. **The model name is asserted, not just duplicated.** It appears as a Dockerfile build argument and as `EMBEDDING_MODEL` in the source. A build step imports the constant and asserts they agree, so changing one and missing the other fails the build instead of silently re-downloading at first request.

4. **Ownership is set at copy time, never with `chown -R`.** Rewriting mode bits on an existing layer duplicates every file it touches: measured at 674 MB with `COPY --chown` against 849 MB with a later `chown -R`. The model directory cannot stay root-owned, because fastembed writes a tree-cache file beside the weights on load.

5. **Seeding is its own service, not the API's startup.** `seed` runs the build once and exits; `api` waits on `service_completed_successfully`. Folding it into the API would mean every replica racing to build the same graph, and a seed failure surfacing as an unhealthy API rather than as itself. Every write is a `MERGE`, so a second `up` converges.

6. **The API warms the embedder during startup, not on first use.** Loading the model and embedding all 164 concepts costs about a second. Lazily, the first coach request pays it; in the lifespan, no request does — and a container that cannot reach its model fails at boot rather than mid-request.

---

## Packing — turning a ranking into a session

1. **The model never selects exercises.** `filter.run` has already computed the answer: `Verdict.sort_key` is a total order whose last element exists so that two runs produce identical output. A model picking eight of seventeen from that list would cost reproducibility and, worse, would leave `attribution`, `costliest_constraint` and every `headline` describing a ranking the plan did not follow — *"why this and not that"* stops having an answer. Selecting from a sorted list and fitting a window is arithmetic.

2. **One authored table places every movement.** All 36 catalog families map to a `(Section, Modality, Slot)`; a test asserts none is missing. Authored rather than inferred from the name, because `regen` and `car` mean nothing to a string matcher and a rule that guessed would guess silently. Twenty-nine of the fifty exercises claim several families, so resolution is by a total ordinal — section, then slot — never by list order and never lexicographically, which would file *Push-Up to Knee-Drive* under core.

   Two things this cost. `WARMUP` must beat `COOLDOWN`: the `mobility - dynamic` + `regen` overlap is three rows, and reversing it drops the sample member's warmup pool from three exercises to one. And `Modality.ISOMETRIC` was removed — all three exercises claiming the `isometric` family also claim a strength one, so it was unreachable, and it could never have done anything, since holds come from `is_reps` and modality only selects a rep range.

3. **The catalog's pattern order is meaningful, and the plan depends on it.** An exercise's primary family is listed first: *Alternating Dumbbell Racked Crossback Lunge* is `lower push - lunge, lower - abduction, lower - adduction`, and all three place it identically, so only the order says it is a lunge. Sorting them alphabetically called it an abduction movement and made substitution match on the wrong axis. Patterns are therefore read from the node property, which preserves order, rather than collected from the `is_a` edges, which does not — and the edge-derived set is returned alongside so a test can hold the two together.

4. **Section budgets come from content, not percentages.** A fixed 15/70/15 split allots 450 seconds to a warmup whose entire pool costs 169. Warmup and cooldown are sized from the window, capped together at 35% of it, and the main block absorbs the rest — then set counts are solved as the largest uniform number that fits and topped up one round at a time in rank order, which gives the cleanest movements the extra volume and the cautioned ones the least. Measured: 2934 of 3000 seconds at fifty minutes.

5. **A long window is refused rather than padded.** The sample member's pool tops out at 73 minutes — eight movements at four sets. A two-hour request schedules 73 and reports the gap; filling it would mean fifth sets or repeated exercises, which is volume only on paper.

6. **The goal anchor is the one authored exception to pure rank.** By rank alone her twenty-minute plan contains no lower-body work at all: her three goal-serving exercises are also her only cautioned ones, so they rank 15th to 17th of seventeen and every short cut drops them — a shoulder-and-core session for a member whose two priority-one goals are both lower-body. One rule reserves a place for the best goal-serving candidate, and the block carries `anchored=True` with the clinician's rationale, so the promotion is legible. Deliberately not a weight change, which would falsify item 2 of *Safety filter*.

7. **Sequencing is a second pass, after selection.** `sort_key` ranks by risk, which is how to *choose* and not how to *order* — followed literally it schedules single-arm tricep work before the heaviest press. Slot order puts compounds first; within a slot the safety rank still decides. Nothing here changes which movements are in the plan.

8. **The rep range decides half the catalog, and says so.** Reps come from dividing a section's work target by the exercise's own cadence, then clamping to the modality's range — and the clamp binds on 21 of the 42 rep-based rows. So `estimated_rep_seconds` sets each set's *duration* and the range sets the *reps*; `Prescription.reps_clamped` records which one decided, rather than letting the field be oversold as driving prescriptions it mostly does not.

9. **Substitution runs outside the filter and can only offer what the filter cleared.** Siblings are intersected with `result.eligible`, which is a one-line safety proof and is only available because `run` scores the whole catalog instead of filtering it. It must share the dropped movement's *deciding* pattern, not merely some pattern: *Med Ball Hamstring Walkout* and *High Plank Bird Dog* both resist rotation, so matching on any shared family offered a bird dog as a stand-in for a hinge. Contraindications and dislikes are not substituted at all — the first is not a circumstance to work around, the second is the member's own standing preference.

10. **Every scheduled movement carries positive evidence, not just the absence of objections.** The filter emits signals only against things, so before this the *best-ranked* movements came back with the emptiest justification. `ReasonKind` extends `SignalKind` with clearance, goal service, focus match, equipment fit, pattern role and substitution; the first six members are `SignalKind` verbatim and in its order, so a `Signal` widens into a `Reason` with no mapping table.

---

## Agent runtime — one call, no framework

1. **The generator makes exactly one model call, and it is the first thing that happens.** A coach's sentence becomes `Instruction` objects via `client.messages.parse()`; everything after that is Python and Cypher. No LangGraph, no Pydantic AI, no Claude Agent SDK, and no Tool Runner — every one of them orchestrates a multi-step loop, and no loop survives this design. Pydantic AI would return typed output already guaranteed by a Pydantic schema; LangGraph would state-machine a straight line.

   `ASSESSMENT.md:5` asks for an effective multi-agent workflow, so this has to read as a decision rather than an omission: **there is no loop because the deterministic filter does the reasoning, and an agent that cannot choose has nothing to iterate on.** The Tool Runner stays in `tech-stack.md` as the copilot's runtime, where open-ended retrieval over KG2 genuinely needs one.

2. **Narration is deferred.** The plan already explains itself — every block carries an authored `headline` and its evidence paths — so a generated paragraph would add prose over a payload that is already legible, with no UI yet to read it. Cutting it also means extraction is the *entire* model surface, which is what makes the keyless path identical rather than degraded: the same plan, asked for as instructions instead of as a sentence.

3. **Emphasis is not a sixth `ConstraintKind`.** All five of those narrow the catalog; one that widens it would put goal fit inside the safety filter that item 4 of *Safety filter* promises it is subordinate to. It resolves against `Muscle` and acts on the packer's selection order instead — `Candidate.key`, which orders the pool the filter has already cleared by **safety, then this request's emphasis, then the member's standing goals, then name**. `penalty` leads, so no emphasis moves a cautioned movement ahead of a clean one of the same kind; the goal anchor still runs first, so a request cannot crowd out the chart. An unresolved emphasis is carried rather than dropped, and a *resolved* one that nothing in the session serves is reported as a `focus_unserved` shortfall — the two read apart, and neither is silent.

   This was the bug the design description was hiding. Emphasis was threaded from the pipeline as far as `why.reasons_for` and no further: a plan carried a `focus_match` reason on a movement chosen for other reasons, so *"isolation work around her pecs"* returned the same session as saying nothing, annotated as though it had applied. Two docstrings and this entry all claimed a tie-break that was never wired up, and the tests passed because they asserted the reason line appeared rather than that the selection moved. It is the same class of failure as the adjustment bug in *Adjustment* item 1 — a request the system reported as honoured and did not honour — and it is why the tests now compare against the no-emphasis plan rather than inspecting the plan alone.

4. **The labelled cases were written before the model was run, and calibrating against it moved both.** `extraction_cases.json` is fixture, offline stand-in and eval set in one file, as `resolver_cases.json` is for the resolver. The live model agreed with three of eight at first. Four were prompt bugs — an exhaustive set of two produced one `replace` and one `add`; a movement class came back as a named exercise; ordinary session descriptions were reported unmapped. Two were bad labels, expecting a possessive and an article the model sensibly dropped and the resolver ignores. One was our own inconsistency: having just told the model that plurals name classes, we had labelled "deadlifts" as an exercise. Now eight of eight, pinned by an opt-in `live` test.

5. **`disabled[]` from the builder becomes `Op.REMOVE`, so per-item switches take the same path a typed instruction does.** They get the same refusals, and `injury` is not in the accepted map at all — a request cannot name it, which is the console's locked items enforced in the type system rather than checked at the route.

6. **Extraction is the one part of this system that is not reproducible.** The same sentence can land differently across runs: *"no overhead press"* has resolved both to the `upper push - vertical` pattern and to a single dumbbell press. Both readings are defensible, and the trace names which one happened — but it is the reason the deterministic half was kept deterministic. Everything downstream of the first arrow reproduces exactly.

---

## Observability — real spans, and a store that survives a restart

*2026-08-09*

1. **The recorder wraps the session rather than being threaded through the query modules.** The generator's reads are spread across `safety/standing.py`, `safety/queries.py` and `plan/queries.py`. Passing a recorder into each would mean changing every query function's signature to carry telemetry, and a read added later would silently miss the trace. `graph/recording.py` wraps `neo4j.Session` instead: if it went through the session it is in the account, by construction. The copilot keeps its hand-rolled recording because it owns all nine of its reads in one file.

   The wrapper materialises each result before recording, so a duration covers *fetching* the rows and not merely issuing the query. Lazily consumed, every read would have reported as near-instant.

2. **Stages and reads share one clock, so nothing in a generator waterfall is reconstructed.** `build_copilot_trace` lays its graph spans out by summing durations and says so — it has no start offsets to work from. `RunRecorder` hands both the stage timer and the session wrapper the same origin, so a read renders nested under the stage that actually issued it. The difference is not cosmetic: the first generator trace showed **3437 ms of a 3483 ms run inside `extract`**. Almost the whole latency budget is the one model call, and no amount of Cypher tuning would move it — which is the sort of thing a fabricated waterfall would never have said.

3. **Repeated reads fold into one span, carrying `calls`.** `PATTERN_SIBLINGS` runs once per dropped movement — 40 times on a limited-equipment plan — and the graph fingerprint once per label and relationship type, another 30. Unfolded, a waterfall is sixty rows of two queries and the shape of the run is invisible. Folded, each keeps its first offset and carries the summed cost, which is the figure worth reading anyway.

4. **The fingerprint reads are folded, not hidden.** Stamping a trace with the graph it ran against costs about thirty round trips. It would have been easy to read those through the raw session and keep them out of the account — and it would have made the trace under-report the request's own latency. A reviewer profiling a slow generation should see them.

5. **Postgres, as `tech-stack.md` chose, and the in-memory ring stays as the fallback.** `DATABASE_URL` unset gives bounded in-memory stores, which is what `uv run pytest` and a bare `uvicorn` get. The consequence is real — traces vanish on restart and an old plan cannot be refined — so `/health` reports `storage: postgres | memory` rather than leaving it to be discovered.

6. **Tracing wraps the run; it never sits inside it.** Both the generator and the copilot build their trace after the work is finished and hand it to the store. A store that is down can lose a trace and can never change the plan or the answer a coach gets.

---

## Adjustment — refine, not replace

*2026-08-09*

1. **The bug: an adjustment rebuilt from the adjustment alone.** `adjust` re-extracted the new utterance and generated from *that*, setting `parent_run_id` and nothing more — the pointer was decorative. So *"she's only got dumbbells and a kettlebell"* followed by *"exclude lunges"* returned a session with the lunges gone **and the barbell back**. The equipment limit was never withdrawn; the plan simply forgot it. A coach reading the second sheet would have programmed kit the member does not own, and nothing on the page said anything had been dropped.

   The console made it certain: it sent only the adjustment text as the whole prompt. The route's own docstring claimed "the request carries its own full state", which nothing on either side actually did.

2. **The fix composes structured instructions, not prose.** A `plan_runs` row stores each run's **accumulated** `Instruction`s; an adjustment loads its parent's and appends its own. Concatenating the *prompts* and re-extracting was the obvious alternative and is worse: extraction is the one part of this system that is not reproducible (*Agent runtime* 6), so re-reading an utterance from three refinements ago could quietly reinterpret a constraint the coach set then and has not touched since. Resolution is deterministic and extraction is not, so the structured half is what gets frozen.

   Appending is the whole of the merge, because `constraints.compose` folds directives in sequence and the later one wins where they conflict. No merge logic was added anywhere.

3. **`disabled[]` is explicitly *not* inherited.** It is the builder's live state, so a coach who switched equipment back on would otherwise keep refining against the version that was off. Utterances accumulate; switch positions are read fresh every time.

4. **The builder always starts a fresh run; only the adjust bar refines.** Its prompt is a whole request rather than a delta, so composing it onto the previous run would re-apply constraints the coach had just deleted from the box. Before this, *"Rebuild session"* went through `adjust` — which was harmless only because `adjust` ignored its parent, and would have become a real bug the moment it stopped.

5. **An unknown parent is a 404, not a fresh build.** Silently rebuilding from nothing is the original bug wearing a different hat: it drops every constraint the parent carried and returns a plan that looks like a successful refinement.

6. **The sheet prints the whole trail.** The plan answers to every utterance in the chain, so showing only the newest made an adjusted plan read as though it had forgotten the rest. `prompt_trail` comes from a recursive CTE over the parent pointers.

---

## Ontology grounding — the SKOS layer

*2026-08-09*

1. **Most of this was naming what already existed.** `ASSESSMENT.md:56` asks for the catalogue's taxonomies mapped onto ontology concepts with SKOS, and three of the four pieces were already in the repo under other names: `aliases.json` was a `skos:altLabel` set, `part_of` was a partitive `skos:broader` hierarchy, and the anatomy rows carried SNOMED codes. What was missing was saying so in the vocabulary a reviewer would look for. That is why the layer is **properties only** — 224 nodes and 538 edges before and after — and why nothing downstream reads it to make a decision.

2. **Five mapping relations, not one, because both directions of inexactness occur.** The catalogue speaks gym vocabulary and SNOMED speaks anatomy, and they carve the body differently. *"glutes"* reaches **gluteus maximus** — one member of the group, so `narrowMatch`; SNOMED has no gluteal-group concept at all. *"upper back"* reaches **the skeletal muscles of the back**, which span more than the catalogue means, so `broadMatch`. Collapsing those into a single "inexact" would hide which way the error runs, and only one of the two directions is safe to widen a search on. A test asserts both are in use, and that every inexact row carries a note explaining the judgement.

3. **Two rows are pinned rather than searched, and pinning is the stronger check.** Ranked EVS search put *"core"* on the abdominal part of **pectoralis major** — a chest muscle — and moved *"obliques"* between the internal and external oblique across consecutive runs. `"pin": true` records the author's choice and `verify_snomed.py` confirms it by code lookup instead of re-deriving it from whatever ranks first today. An earlier pass also had *"hip adductors"* landing on the group's **tendon** rather than the muscle, which is a different tissue. All three were caught by reading the output, which is the argument for keeping the script's per-row printout: **a wrong clinical mapping is worse than an absent one**, because it renders beside the correct ones with nothing to distinguish it.

4. **Equipment and movement patterns are deliberately unmapped, and a test enforces it.** SNOMED is a clinical terminology; "Kettlebell", "BOSU" and "SkiErg" are not clinical concepts. A few gym items do exist as SNOMED devices, but a taxonomy where 4 of 32 map and 28 do not is worse than a clean local scheme — it implies a grounding that mostly is not there, and a reviewer would have to check every row to find out which. `:80` prefers a small subset used meaningfully over everything wired shallowly, and this is where that preference bites.

5. **`skos:Collection`, not `skos:broader`, for those two.** A collection is SKOS's construct for a labelled grouping that is *not itself a concept in the scheme*, which is exactly right: "Free weights" is not equipment this catalogue stocks. `broader` would need parent concepts, and only one of the sixteen families — `cardio` — exists in the catalogue's own vocabulary. Minting the other fifteen would add nodes nothing traverses, failing the rule KG2 item 2 already set, and would make "lower push" resolvable — a behaviour change to hold a label. The collections are exhaustive and disjoint per taxonomy, and the build raises on drift rather than letting a partition silently stop covering the catalogue.

6. **OPE and COPPER are declined in writing rather than left unmentioned.** `:90-95` asks for reasoning on what to pull *and what to leave out*, so an ontology that appears nowhere reads as an oversight rather than a decision. OPE is the closest published fit and is declined on three counts — granularity mismatch against a programming vocabulary, no stable retrieval path to make grounding re-verifiable, and no decision in this system that would read it. COPPER genuinely fits the churn assessment, which is three counted binary signals; importing a behaviour-change ontology to describe three booleans would be more ontology than model. `ontologies.md` records what would change each verdict.
