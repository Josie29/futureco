# Frontend Spec — Coach Console

Everything `ASSESSMENT.md` mandates, built to feel like a tool a coach would keep open, and nothing beyond that. Stack fixed in [`tech-stack.md`](tech-stack.md): Vite + React 19 + TypeScript, Tailwind v4, shadcn/ui, Recharts. Lives in `web/`.

## What the spec requires

`ASSESSMENT.md:72` enumerates the dashboard exhaustively. Every component traces to a line.

| Requirement | Line | Component |
|---|---|---|
| Coach login (mock auth is fine) | `:72` | M1 |
| A member view | `:72` | M2, M3, M4 |
| Generator: prompt + time window → structured plan | `:23`, `:72` | M5, M6 |
| Interactive adjustment (3 scenarios) | `:27-31` | M8 |
| Provenance trace per plan | `:33` | M7 |
| Chat panel with retrieval, history, images, follow-ups | `:37`, `:44`, `:72` | M9 |
| Quick-prompt palette | `:39`, `:41` | M10 |
| Chart rendering | `:39`, `:42`, `:72` | M11 |
| Graceful degradation when nothing resolves | `:68` | M12 |

## Cut, with reasoning

| Cut | Why |
|---|---|
| Member context for anyone but Jordan | Only one member exists in the data. The roster carries roster-level metadata only; selecting an unpopulated member shows a designed empty state, never fabricated clinical detail. |
| Morning brief as a dashboard panel | `:71` assigns the brief to the **copilot**. It's delivered instead by opening the thread with the brief already answered — no new component, and it proves retrieval on first paint. |
| Labs / DEXA panels | Quarterly context that changes nothing about today's session. A table of LDL values is inert and proves no retrieval happened. Copilot only. |
| Biomarkers (sleep, HRV, resting HR) on the dashboard | Putting readiness metrics in the header implies the generator uses them. Nothing in the graph connects sleep to exercise selection, and inventing that link is the unfounded reasoning this system exists to avoid. `Sleep this week` is a mandated quick prompt — the copilot is where it means what it says. |
| Focus toggles (body region / movement pattern) in the builder | Cut after review. They were a second way to say what the prompt already says, and pre-resolved chips would route the *assessed* path around the three-pass resolver (`:68`). With the prompt as the only way to state intent, every request exercises resolution. |
| Diff view for adjustments | The provenance trace (M7) already reports what was removed and why. One mechanism, two jobs. |
| Graph visualization | `:129` — explicit nice-to-have. |
| Designed responsive / mobile layout | Not mentioned. Target 1280px+; below that it degrades without breaking. |

**Held, not cut:** copilot response streaming (`:131`). A chat that appears fully-formed after four seconds feels broken in a way a spinner can't fix. Take it if the SSE plumbing for M5's staged progress lands cheaply.

---

## Skeleton

Three regions. The rail is roster metadata only — it exists because a console managing exactly one person reads as a demo, and because it shows the shape the app grows into.

```
┌─────────────────────────────────────────────────────────────────┐
│ future · coach console                          Sam Ortiz ▾     │
├──────────────┬────────────────────────────────┬─────────────────┤
│ MEMBERS  (4) │ Jordan Rivera · 41 · 1:1       │ COPILOT         │
│ search…      │ ⚠ left knee · recovering       │ quick prompts   │
│              │ ▣ DB KB BND MAT BCH            │ ─────────────── │
│ ● Jordan R.  │ adherence ╲__ 50%  goals ×3    │ brief, already  │
│   ⚠ knee     ├────────────────────────────────┤ answered        │
│   Tue · 50%  │ LAST FOUR SESSIONS             │                 │
│              │ [26m] [skipped] [31m] [28m]    │ chat history    │
│ ○ Alex M.    ├────────────────────────────────┤ + attachments   │
│ ○ Priya S.   │ APPLIED FROM PROFILE           │                 │
│ ○ Devin O.   │  ✕ left knee        always on  │ charts inline   │
│              │  ▤ equipment ×5           on   │                 │
│              │  ▤ dislikes               on   │                 │
│              │  ▤ goal targets           on   │                 │
│              │ WHAT ARE WE TRAINING?          │                 │
│              │ [ free text            ⌘↵ ]    │                 │
│              │ LENGTH  ──●───  50 min         │                 │
│              │ her last three ran 26, 31, 28  │                 │
│              │ 18 of 50 available [ Build ]   │                 │
│              ├────────────────────────────────┤                 │
│              │ WHY │ THU · LOWER BODY         │ [ Ask…      ▸ ] │
│              │  ✓  │ World's Greatest Stretch │                 │
│              │  ●  │ DB Goblet Split Squat    │                 │
│              │  ✕  │ B̶a̶r̶b̶e̶l̶l̶ ̶R̶a̶c̶k̶e̶d̶ ̶L̶u̶n̶g̶e̶  │                 │
│              │ swap│ Alt DB Crossback Lunge   │                 │
└──────────────┴────────────────────────────────┴─────────────────┘
     15rem                  flex-1                     24rem
```

---

## Components

**M1 · Coach login** *(mock)* — pick a coach, stored in `localStorage`. Unauthenticated visits redirect; sign-out returns. Deliberately trivial: `:72` says "mock auth is fine."

**M2 · Member roster** — roster-level metadata only: name, last session day, adherence %, injury and churn chips. Sorted by attention needed. Active member reflected in the URL. Selecting an unpopulated member shows a designed empty state.

**M3 · Member header** — identity, active injury, available equipment, adherence sparkline, goals with target dates. The injury and equipment are here so a reviewer can tell a safe plan was *constrained* rather than *lucky*. The goals are here because the trace says `targets hamstrings ← goal_strength`, which is unreadable without them.

**M4 · Recent sessions** — four cards from `workout_history`: date, title, duration, RPE. The skipped session renders in carmine. You can't program Thursday without knowing what Tuesday was, and this is where the churn story stops being a chip and becomes a fact.

**M5 · The builder** — three parts, in order:

1. **Applied from her profile.** Injury, equipment, dislikes, goal targets, each stating what it does in graph terms ("Left knee · recovering · mild → *excludes plyometric · cautions loaded knee flexion*"). Equipment, dislikes and goals are switches the coach can lift for one run. **Injury is locked and has no off state in the UI.**
2. **The prompt.** Unfenced free text, the mandated input (`:23`). Every phrase runs the three-pass resolver.
3. **Length.** Slider defaulting to `preferred_session_minutes` (50), with a derived note: *her last three ran 26, 31, 28*. Two fields already loaded, one line of UI, and it points at the likeliest fix for a declining adherence curve.

Plus a **live eligibility count** — `18 of 50 available to Jordan`, her standing pool before any request narrows it, recomputed when a rule is lifted. One Cypher query, no LLM.

And **staged progress while generating** — named pipeline stages (resolving → loading constraints → filtering catalogue → assembling), not an indeterminate spinner. Honest about a multi-second wait and a live demonstration that the traversal is real.

**M6 · Plan render** — warmup / main / cooldown; sets, reps, rest. Estimated total against the requested window. Paired/unilateral exercises indicate per-side work.

**M7 · Provenance margin** — the signature. A left annotation gutter, 7rem, marks right-aligned, hairline rule, then the program column. Per exercise: verdict mark plus the graph path that justified it. **Rejected exercises stay in place, struck through**, so the coach reads the decision rather than a summary of it. Plan-level funnel underneath, grouped by cause. This is the surface that proves the graph did the work; it gets more care than anything else in the app.

**M8 · Interactive adjustment** — the three scenarios at `:27-31`, all driven from the prompt. Plus direct manipulation of the result: drag to reorder within a block, drag between blocks, drag an alternate in from a tray. **The tray is the eligible pool, so no drag can produce an unsafe plan** — the constraint is enforced by what's draggable at all. Every drag needs a keyboard equivalent.

**M9 · Copilot chat** — opens with the brief already answered. Seeds from `chat_history`; renders `attachments` as captioned placeholder tiles (the sample carries `type` and `caption` but **no URL**). Follow-ups retain context. Ungrounded questions answer "I don't have that for Jordan."

**M10 · Quick-prompt palette** — the four at `:41`, one click to send, reachable as the thread grows.

**M11 · Charts** — the three at `:42` plus sleep. Inline in the thread at 24rem, legible in both themes. Per the `dataviz` skill, colour carries the same meaning across every chart.

**M12 · States** — loading, error, empty, and **degraded**. Degraded is the graded one (`:68`): when a phrase resolves to nothing above threshold, the console names it and says what it did instead.

---

## Production-feel criteria

| | Criterion |
|---|---|
| **P1** | Active member lives in the URL (`/m/:memberId`). Reload and deep-link restore full state. |
| **P2** | No bare spinners. Loading states are skeletons shaped like the content that replaces them. |
| **P3** | Long operations name what they're doing, never an indeterminate wait. |
| **P4** | Every empty and error state is designed and states the next action. |
| **P5** | Primary loop is keyboard-operable — `⌘↵` builds, `↵` sends, `Esc` closes the expanded trace. |
| **P6** | Timestamps are real and relatively formatted, derived from the data's own `ts` fields. |
| **P7** | No lorem, no placeholder copy, no dead links in the shipped build. |
| **P8** | Layout is stable. Async data landing never shifts content already on screen. |

---

## Visual direction

From the `frontend-design` skill. The direction comes from the product's world — strength programming meeting clinical reasoning — not from dashboard convention.

### Safety is one hue at three intensities, not traffic lights

The deliberate risk. Absolute versus relative contraindication is a **gradient**, which is why `decisions.md` split `contraindicates` from `cautions`. Red / amber / green would misrepresent that as three unrelated categories. Typographic marks carry the meaning so nothing depends on colour alone.

| State | Mark | Treatment |
|---|---|---|
| Contraindicated | `✕` | Carmine. Exercise name struck through, left in place. |
| Caution | `●` | Carmine, outlined. Margin bracket. |
| Cleared | `✓` | Graphite. The unremarkable good state shouldn't shout as loudly as the dangerous one. |

### Palette — "imaging plate"

Cool light of a radiology lightbox, not parchment. One saturated colour, a deep oxidised carmine from anatomical plate illustration.

> Future's exact brand hexes were never extracted — WebFetch strips CSS. These derive from the subject; reconcile if the real palette becomes available.

```css
:root {
  --plate:        #f6f7f9;  /* page — cool near-white */
  --film:         #ffffff;  /* surface */
  --sunk:         #edeff2;  /* recessed wells, gutter */
  --rule:         #dfe3e8;  /* hairlines */
  --ink:          #14171b;  /* text, primary actions · cool near-black */
  --slate:        #626c78;  /* secondary text, margin annotations */
  --carmine:      #9e2a3c;  /* THE saturated colour — safety only */
  --carmine-tint: #f5e6e9;
}
```

Carmine appears **only** on safety states. Primary actions use graphite fill.

### Type

| Role | Face | Use |
|---|---|---|
| Display | **Archivo Expanded** 600 | Section eyebrows (0.6875rem, 0.08em tracking, uppercase), member name |
| Body / UI | **Archivo** 400/500 | 0.875rem base |
| Data / trace | **Spline Sans Mono** | Sets·reps·rest, durations, every provenance line |

The mono is functional: it aligns tabular dosing and tells the truth that the trace is machine-derived. Self-hosted via `@fontsource` — `docker compose up` must work from a cold clone with no network.

### Iconography

Domain vernacular, not an icon library. Equipment reads `DB` / `KB` / `BND` the way a coach writes it on a program sheet. Verdict marks are three pieces of geometry. Lucide only for utility chrome (search, close, chevron).

---

## API surface

`prompt` is required and unconstrained; everything else is an optional hint. A request with nothing but a prompt is valid.

| Method | Path | For |
|---|---|---|
| `GET` | `/api/coaches` | M1 |
| `GET` | `/api/members` | M2 — roster metadata, `has_context` flag |
| `GET` | `/api/members/{id}` | M3, M4 — full context |
| `GET` | `/api/members/{id}/eligibility` | M5 — live count, `?lifted=equipment,dislikes` |
| `POST` | `/api/members/{id}/plans` | M5, M6 — `{prompt, duration_min, lifted_rules[]}` → `{run_id, plan, trace}` |
| `POST` | `/api/members/{id}/plans/{run_id}/adjust` | M8 — `{prompt}` → new run |
| `GET` | `/api/members/{id}/messages` | M9 |
| `POST` | `/api/members/{id}/messages` | M9, M10, M11 — may return a chart payload |

**`lifted_rules[]` can never contain the injury.** It's loaded server-side from the member ID, which comes from the session rather than the request body. There is no field the client can send to switch it off — the same reason the agent's tools don't expose it.

---

## Open questions

1. **Chart payload shape** — typed tool result the frontend renders, versus a spec the frontend interprets. M11 forces it.
2. **Adjustment semantics** — new run with a parent pointer (auditable) versus mutating the current run. M7 and M8 both argue for a new run.
3. **Does a drag create a new run?** Reordering doesn't change what was filtered, so it shouldn't invalidate the trace. A swap from the tray probably should.
4. **Does the duration note nudge?** Stating the gap is honest; pre-setting the slider to 35 would override a coach's stated preference on a hunch. A one-tap "use 30" might be the better product.
5. **Live count debouncing** — one Cypher round-trip per rule toggle needs a stale-response guard.

## Deferred

Graph visualization · copilot streaming · member context beyond Jordan · labs and biomarker panels · diff view · designed responsive layout · collapsible rail.
