# Worked examples

Real output, not illustrations. The first two come from `plan.probe`, which is the generator with no model in it — so they are byte-reproducible on any machine, with or without an API key. The third runs against the live extractor and shows the three interactive-adjustment scenarios `ASSESSMENT.md:27-31` asks for, as one conversation.

`plan.probe` is the generator with no model in it. Both examples below are its real output.

```bash
cd backend
PYTHONPATH=src uv run python -m plan.probe --minutes 45 add:anatomy:"left knee"
PYTHONPATH=src uv run python -m plan.probe --minutes 45 replace:equipment:dumbbells
```

**The injury case** — a coach flags the knee. All 17 eligible movements survive, because flagging a structure down-ranks rather than excludes: the graph knows an exercise loads the knee, not that doing so is harmful. 44m33s of 45 minutes scheduled.

```
MAIN
  2 x 40s hold each side   Low Copenhagen Plank
      flagged_structure  loads the knee
      cleared            no contraindicated movement pattern reaches it
  2 x 15                   Alternating Dumbbell Racked Crossback Lunge  <- anchored on a goal
      caution            Loaded knee flexion with a long lever at the front knee.
                         Tolerable at partial range, so a penalty rather than a hard exclusion.
```

The caution is a clinician's sentence from `contraindications.json`, quoted, not generated. The lunge is *anchored*: by rank alone this member's only goal-serving movements are also her only cautioned ones, so a short session would contain no lower-body work at all.

**The limited-equipment case** — dumbbells only. 45 of 50 movements go, and the plan says so rather than presenting five as a full session: 24m32s of 45 minutes, a thin pool, an empty cooldown and four uncovered slots, each naming the equipment limit as its cause.

```
  1 x 12   Walking Toe Touches
      substitution   stands in for World's Greatest Stretch, which shares
                     mobility - dynamic and needs equipment that is not available
```

A stand-in can only ever be a movement the filter already cleared, and must share the dropped one's *primary* pattern — so no substitution can route around a contraindication.

**The refinement case** — the three scenarios from `ASSESSMENT.md:27-31` as one conversation, against the live extractor. Real output, one `curl` per step.

```
step 1  "She's only got dumbbells and a kettlebell at home today."
        dumbbells  -> Dumbbell    [fuzzy]  focus
        kettlebell -> Kettlebell  [exact]  focus
        5 of 50 eligible

step 2  "Her left knee is bothering her again."
        left knee  -> knee        [exact]  protect   side=left
        5 of 50 eligible          <- flagging down-ranks; it does not exclude

step 3  "Exclude deadlifts."
        deadlifts  -> declined at 0.40, threshold 0.90
        5 of 50 eligible          <- the request changed nothing, and says so
```

Two things this shows that a single-shot example cannot.

**Constraints accumulate.** By step 3 the plan is still built from the equipment limit set in step 1 — `Dumbbell` and `Kettlebell` are still in the resolved list, two refinements later. An adjustment loads its parent's structured instructions and appends its own; it does not rebuild from the last sentence. That was a real bug, and `docs/decisions.md` *Adjustment* records what it did.

**A decline is reported, not absorbed.** No catalog movement is named "deadlift", so the phrase reaches 0.40 against a 0.90 threshold and the resolver refuses rather than guessing at `Barbell` — which it can reach at 0.523, five thousandths above a term that *must* resolve. The sheet names the phrase, the near-miss, the score and the threshold it missed. Nothing silently didn't happen.
