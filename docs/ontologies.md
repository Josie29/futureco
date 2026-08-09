# Ontologies — what was pulled, what was left out, and why

`ASSESSMENT.md:80` asks for *"a small, well-justified subset used meaningfully"* rather than everything wired shallowly, and `:90-95` asks for the reasoning behind the choice. This is that reasoning. `:94` also permits *"a clean hand-rolled ontology aligned to these concepts"*, which is what the two ungrounded taxonomies get.

## The verdict, one line each

| Ontology | Used | What for |
|---|---|---|
| **SNOMED CT** | Yes — 47 concepts | Anatomy, muscles, and the one clinical condition. The only external vocabulary in the graph |
| **SKOS** | Yes — all 115 concepts | The mapping vocabulary itself: `prefLabel`, `altLabel`, `inScheme`, the five `*Match` relations, and `Collection` |
| **PROV-O** | Yes | `RunHeader` in `safety/trace.py` — `wasGeneratedBy`, `wasAssociatedWith`, `generatedAtTime`, `used` |
| **OPE** | **No** | See below |
| **COPPER** | **No** | See below |

## What SKOS actually does here

Most of this layer is **naming what the graph already had**, which is why it cost little and why it is honest:

| Already existed as | Now named |
|---|---|
| `aliases.json`, read by the resolver's alias pass | `skos:altLabel`, written onto the concept nodes |
| `part_of`, the anatomy hierarchy | `skos:broader` (partitive), documented in `kg1-schema.md` |
| `snomed_code` / `snomed_term` columns | A typed mapping: `match_type` + `match_scheme` + `match_code` + `match_term` |
| The catalogue's canonical name | `skos:prefLabel` |

**Properties, not new nodes or edges.** The graph is still 224 nodes and 538 edges. The SKOS layer is a description of the vocabulary, not more vocabulary, and nothing downstream reads it to make a decision — the safety filter and the resolver behave exactly as before.

Five concept schemes: `futureco:anatomy`, `futureco:movement`, `futureco:equipment`, `futureco:clinical`, and `snomedct_us`. The local ones are separate rather than one because a coach naming equipment and a coach naming a movement are asking different questions — which is the same reason `Resolver.resolve` makes a call site declare the labels it accepts.

## SNOMED CT — 47 concepts, every one verified

`scripts/verify_snomed.py` resolves each authored term against the live NCI EVS API and writes the code back. **Re-running is the verification pass**: a drifted code or a renamed concept shows up as a diff. Codes are frozen into the data files, so no build or request depends on a live ontology service.

| Taxonomy | Concepts | Relations |
|---|---|---|
| `AnatomicalStructure` | 27 | 27 `exactMatch` |
| `Muscle` | 19 | 10 `exactMatch`, 4 `closeMatch`, 4 `narrowMatch`, 1 `broadMatch` |
| `Condition` | 1 | 1 `exactMatch` |

### Why the muscle mappings are mostly *not* exact

This is the interesting half. The catalogue speaks gym vocabulary and SNOMED speaks anatomy, and the two carve the body differently. Recording *how* each mapping is inexact is the point of having five relations instead of one:

- **`narrowMatch`** — SNOMED names one member of a training group. *"glutes"* → **Structure of gluteus maximus muscle**. SNOMED has no gluteal-group concept at all; searching for one returns lymph nodes and an accessory-muscle variant. Also *"core"*, *"obliques"*, *"hip flexors"*.
- **`broadMatch`** — SNOMED spans more than the catalogue means. *"upper back"* → **Skeletal muscle structure of back**. "Upper back" is a training region with no muscular concept behind it; this is the loosest row in the file and is marked as such.
- **`closeMatch`** — near-synonymous on a different boundary. *"hamstrings"* → **Posterior muscle of thigh**, regional rather than functional. Also *"chest"* (excludes pectoralis minor), *"lower back"*, *"middle back"*.

**The two directions are not interchangeable.** `narrowMatch` means the external concept sits inside the local one; `broadMatch` means it contains it. Only one of those is safe to widen a search on, so collapsing them into a single "inexact" would hide which way the error runs. A test asserts both are in use.

### Two rows are pinned rather than searched

Ranked search is fine for a term with one obvious answer and unreliable for one without. It put *"core"* on **the abdominal part of pectoralis major** — a chest muscle — and moved *"obliques"* between the internal and external oblique on consecutive runs. Where an author had to choose, `"pin": true` records the choice and `verify_snomed.py` confirms it by **code lookup** rather than re-deriving it from whatever ranks first today. That is stronger verification, not weaker.

An earlier pass also had *"hip adductors"* resolving to the group's **tendon** rather than the muscle — a different tissue. It was caught by reading the output. **A wrong clinical mapping is worse than an absent one**: it renders beside the correct ones with nothing to distinguish it.

### Known imperfections, recorded rather than hidden

- `patellar tendon` maps to **Structure of patellar ligament**. SNOMED is right and the catalogue is colloquial; strictly this is a `closeMatch`. It is left at the anatomy default because it is the only one of the 27, and adding a column 26 rows would leave empty costs more than the note.
- `obliques` has a second legitimate `narrowMatch` (internal oblique, `1179024003`) that is not modelled, because the row shape holds one mapping.
- `lower back` (Muscle) and `erector spinae` (AnatomicalStructure) map to the same SNOMED concept at different strengths — `closeMatch` and `exactMatch`. That is correct SKOS: two local concepts, one external one. It is also the ambiguity `decisions.md` *Resolver* 1 refuses to resolve by precedence.

## Equipment and movement patterns get no external mapping

The 32 equipment types and 36 movement patterns are **deliberately unmapped**, and a test enforces it.

**SNOMED is a clinical terminology.** "Kettlebell", "BOSU" and "SkiErg" are not clinical concepts. A handful of gym items do appear as SNOMED devices, but a taxonomy where 4 of 32 map and 28 do not is worse than a clean local scheme: it implies a grounding that mostly is not there, and a reviewer would have to check each row to find out which.

Instead both get **`skos:Collection`** — SKOS's construct for a labelled grouping that is *not itself a concept in the scheme*. That is precisely the situation: "Free weights" is not equipment this catalogue stocks. Ten collections over the patterns, seven over the equipment, authored in `data/authored/collections.json`, exhaustive and disjoint, with the build raising if they drift from the catalogue.

**Why a collection rather than `skos:broader`.** `broader` would need parent *concepts*, and only one of the sixteen families — `cardio` — exists in the catalogue's own vocabulary. Minting the other fifteen would add nodes nothing traverses, which fails the rule `decisions.md` KG2 item 2 already set: *a node earns its place by having a relationship to express*. It would also make "lower push" resolvable, changing the resolver's behaviour to hold a label.

## OPE — evaluated, not used

The Ontology of Physical Exercises is the closest published ontology to this domain, and it is the one I most wanted to use. Three things stopped it:

1. **Granularity mismatch.** OPE models exercises as compositions of body movements and equipment. This catalogue's 36 patterns are a *programming* vocabulary — `regen`, `car` (controlled articular rotation), `total body` — that encodes how a coach schedules a session, not how a joint moves. The mapping would be many-to-many and mostly `relatedMatch`, which asserts almost nothing.
2. **No stable retrieval path.** SNOMED has the NCI EVS REST API, which is what makes `verify_snomed.py` a verification pass rather than a one-off transcription. OPE is a BioPortal download; grounding against it would mean either committing a snapshot or hand-copying IRIs, and a hand-copied IRI nobody can re-verify is a claim, not a mapping.
3. **It would not change a single decision.** Nothing in the safety filter, the resolver or the packer would read it. Per `:80`, a subset used meaningfully beats one wired shallowly — and this would be wired shallowly.

**What would change that:** if substitution needed to reason across catalogues — "find me an equivalent movement in a different provider's library" — a shared movement vocabulary becomes load-bearing rather than decorative, and OPE is where I would start.

## COPPER — evaluated, not used

COPPER covers personalisation and behaviour-change concepts. It is a genuine fit for *one* part of this system: the churn assessment in `api/churn.py` derives signals — falling adherence, a missed session, message silence — that COPPER has vocabulary for.

It is not used because **the churn model is three counted binary signals** (`decisions.md` *Read API* 5: two or more is elevated, one is moderate). Importing a behaviour-change ontology to describe three booleans would be more ontology than model. The honest statement is that this system has no behaviour-change model yet; adding vocabulary for one would imply otherwise.

**What would change that:** a real intervention model — recommending *actions* for a churn-risk member, and tracking which worked — is exactly where COPPER's concepts start doing work.

## PROV-O

Already in place before this pass, in `safety/trace.py`. `RunHeader` follows the ontology's field names so the mapping is obvious: `was_generated_by` is the activity, `was_associated_with` the agent, `used_queries` and `used_graph` the entities it drew on. Pydantic rather than RDF, because the consumer is a typed API and a dashboard, not a triple store.

## How to inspect it

```bash
# Every concept, its scheme, and where it maps
docker compose exec neo4j cypher-shell -u neo4j -p futureco-local \
  "MATCH (n) WHERE n.in_scheme IS NOT NULL
   RETURN labels(n)[0] AS label, n.in_scheme AS scheme, count(*) AS concepts,
          count(n.match_code) AS mapped, count(n.collection) AS grouped ORDER BY label;"

# The inexact mappings, which are the ones worth reading
docker compose exec neo4j cypher-shell -u neo4j -p futureco-local \
  "MATCH (n) WHERE n.match_type IS NOT NULL AND n.match_type <> 'exactMatch'
   RETURN n.name, n.match_type, n.match_term ORDER BY n.match_type;"

# Re-verify every code against SNOMED CT. A diff is a drifted mapping.
python scripts/verify_snomed.py
```
