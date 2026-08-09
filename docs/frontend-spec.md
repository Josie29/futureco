# Frontend Spec — Coach Console

Everything `ASSESSMENT.md` mandates, built to feel like a tool a coach would keep open, and nothing beyond that. Stack fixed in [`tech-stack.md`](tech-stack.md): Vite + React 19 + TypeScript, Tailwind v4, Recharts. Lives in `web/`.

## What the spec requires

`ASSESSMENT.md:72` enumerates the dashboard exhaustively. Every component traces to a line.

| Requirement | Line | Component | State |
|---|---|---|---|
| Coach login (mock auth is fine) | `:72` | M1 | Built |
| A member view | `:72` | M2, M3, M4 | Built |
| Generator: prompt + time window → structured plan | `:23`, `:72` | M5, M6 | Built |
| Interactive adjustment (3 scenarios) | `:27-31` | M8 | Built — prompt-driven, plus in-place refinement |
| Provenance trace per plan | `:33` | M7 | Built — both halves, in plain language. The literal traversal stays in the payload |
| Chat panel with retrieval, history, images, follow-ups | `:37`, `:44`, `:72` | M9 | Built |
| Quick-prompt palette | `:39`, `:41` | M10 | Built — the four member questions; the two remaining chart prompts are typeable, not buttons |
| Chart rendering | `:39`, `:42`, `:72` | M11 | Built |
| Graceful degradation when nothing resolves | `:68` | M12 | Built |

## Cut, with reasoning

| Cut | Why |
|---|---|
| Member context for anyone but Jordan | Only one member exists in the data. The roster carries roster-level metadata only; selecting an unpopulated member gets a 404 from the API and a designed empty state in the UI, never fabricated clinical detail. |
| Morning brief as a dashboard panel | `:71` assigns the brief to the **copilot**. It's delivered instead by opening the thread with the brief already answered — no new component, and it proves retrieval on first paint. Churn risk *is* promoted to the header, because a risk level that scrolls away isn't surfaced. |
| Labs / DEXA panels | Quarterly context that changes nothing about today's session. A table of LDL values is inert and proves no retrieval happened. Copilot only. |
| Biomarkers on the dashboard | Putting readiness metrics in the header implies the generator uses them. Nothing in the graph connects sleep to exercise selection, and inventing that link is the unfounded reasoning this system exists to avoid. `Sleep this week` is a mandated quick prompt — the copilot is where it means what it says, and the answer says outright that it changed nothing. |
| Focus toggles in the builder | They were a second way to say what the prompt already says, and pre-resolved chips would route the *assessed* path around the three-pass resolver (`:68`). With the prompt as the only way to state intent, every request exercises resolution. |
| Drag-to-reorder the plan | The adjust bar covers the same ground through the resolver, which is the path being assessed. Direct manipulation would need a keyboard equivalent and a second safety story for what's draggable. |
| Graph visualization | `:129` — explicit nice-to-have. Now covered separately by the `/admin/graph` inspector. |
| Nothing — observability was taken | `:134` is a nice-to-have and it is built: `/traces` shows the span waterfall, the Cypher each graph step ran, LLM token counts, and which runs degraded or failed. |
| Designed mobile layout | Not mentioned. Target 1280px+; the copilot dock collapses to reclaim width below that. |

**Held, not cut:** copilot response streaming (`:131`). Answers render a skeleton while in flight and the generator names its pipeline stages, so the wait is legible; token-by-token streaming is the remaining upgrade.

---

## Components

**M1 · Coach login** *(mock)* — pick a coach, stored in `localStorage`. Unauthenticated visits redirect and return to where they were headed. Deliberately trivial: `:72` says "mock auth is fine". It earns its place by proving the boundary — the member id in a URL is not authority to read that member.

**M2 · Member roster** — roster-level metadata only: name, last session day, adherence %, injury and attention chips. Sorted by attention needed. The active member lives in the URL (`/m/:memberId`), so reload and deep-link restore state.

**M3 · Member header** — identity, active injury, churn risk, adherence sparkline, sessions this week, typical session length. The injury and the risk level are here so a reviewer can tell a safe plan was *constrained* rather than *lucky*.

**M4 · Recent sessions** — an aligned list from `workout_history`: date, title, duration, RPE, newest first. The skipped session renders in red. You can't program Thursday without knowing what Tuesday was.

**M5 · The builder** — three parts: what is being applied, an unfenced prompt, and a length. Constraints are **per-item switches**, not category toggles: a coach can drop the bench she left at the office, or waive one specific dislike, without touching the rest. Each group says in plain words what it does and whether switching changes the **pool** or only the **preference** — so a preference-only group doesn't read as a broken control when the count holds still. Injury items render locked, in the UI and in the API. Plus a live eligibility count (18 of 50) and named pipeline stages while generating.

**M6 · Plan render** — warm-up / main / cool-down; sets, reps, rest, per-side. Estimated total against the requested window, with each block sized by its real share of it.

**M7 · Provenance** — the signature, and it has two halves:
- *Why chosen.* Every prescribed movement carries one plain sentence per reason, collapsed behind "Why this one?".
- *Why not.* Every dropped movement, grouped by cause, in the coach's words.
- *The traversal.* Rendered on the Traces tab, not here — `why[].path` under `assemble_session`, and the exclusion walks under the two filter spans. A **How this was built** link on the plan header goes straight to that run. A coach never has to open it; anyone defending the plan can. This is how `:33`'s "which graph path justified it" is satisfied without putting edge syntax in front of a coach.
- *The funnel.* `50 movements in the library · 18 suit her today · 8 in this session`, so the sheet's counts reconcile against the builder's rather than contradicting them.

**M8 · Interactive adjustment** — the three scenarios at `:27-31`, all driven from the prompt, plus an adjust bar on the plan itself. **An adjustment is a new run with a parent pointer, never a mutation**, so the trace a coach acted on survives review.

It also **composes onto its parent rather than replacing it**: the server loads the parent run's accumulated `Instruction`s and appends this utterance's, so *"only dumbbells"* → *"exclude lunges"* keeps both. The builder is the opposite — its prompt is a whole request, so pressing **Rebuild session** always starts a fresh run. That split is the difference between refining a plan and restating one, and the sheet prints the full prompt trail so which one happened is legible.

**M9 · Copilot chat** — opens with the brief already answered. Seeds from `chat_history`; renders `attachments` as captioned placeholder tiles (the sample carries `type` and `caption` but **no URL**). Answers cite the member message they were drawn from, clickable through to the Messages tab. Ungrounded questions answer "I don't have that for Jordan" and name what the record does cover.

**M10 · Quick-prompt palette** — four full questions rather than seven two-word chips, which read as a filter bar. Charts come back with the answer where a chart is the clearest form, so `Plot adherence trend` is folded into "How's her adherence trending?". `Show message pattern` and `Compare last 4 weeks` (`:42`) stay answerable by typing.

**M11 · Charts** — adherence, sleep, message pattern, four-week comparison. Single series each, so no legend: cobalt is the series, red marks a point below target. Every chart ships a numbers table as the accessible view.

**M13 · Traces** *(`:134`, nice-to-have)* — a run list, a span waterfall, and per-span detail: the Cypher a graph step ran, the model and token counts for an LLM call, and the reason a run degraded or failed. Span kinds are labelled rather than coloured — five nominal categories would need five colour-vision-safe hues, and this console spends its one saturated colour on the product and reserves red for status. Written for an engineer, which is why it shows the edge syntax the console hides.

**Every row is a run that happened.** Both surfaces emit spans, the store is Postgres, and the offsets are measured rather than reconstructed — `RunRecorder` hands the pipeline's stages and its graph reads one clock, so a read renders under the stage that issued it.

**M12 · States** — loading (skeletons shaped like the content), error, empty, and **degraded**. Degraded is the graded one (`:68`): a phrase that resolves to nothing above threshold is named on the sheet with its nearest match, the score, the threshold it missed, and what the system did instead.

---

## Production-feel criteria

| | Criterion | State |
|---|---|---|
| **P1** | Active member lives in the URL. Reload and deep-link restore full state. | Met |
| **P2** | No bare spinners. Loading states are skeletons shaped like the content. | Met |
| **P3** | Long operations name what they're doing. | Met |
| **P4** | Every empty and error state is designed and states the next action. | Met |
| **P5** | Primary loop is keyboard-operable — `⌘↵` builds, `↵` sends. | Met |
| **P6** | Timestamps are real and relatively formatted, from the data's own `ts` fields. | Met |
| **P7** | No lorem, no placeholder copy, no dead links. | Met |
| **P8** | Layout is stable. Async data landing never shifts content already on screen. | Met — the previous plan stays mounted and dimmed while the next builds |
| **P9** | The shell owns its own scrolling. Panes scroll; the page never does. | Met — `html/body/#root` pinned to 100%, `min-h-0` through the column chain |

---

## Visual direction — "Meet"

The visual language of meet posters and plate weights, in sentence case. The direction comes from the product's world — strength programming meeting clinical reasoning — not from dashboard convention.

### Safety is one hue at two intensities plus a neutral, not traffic lights

Absolute versus relative contraindication is a **gradient**, which is why `decisions.md` split `contraindicates` from `cautions`. Red / amber / green would misrepresent that as three unrelated categories. Typographic marks carry the meaning so nothing depends on colour alone.

| State | Mark | Treatment |
|---|---|---|
| Contraindicated | `✕` | Red. Struck through in the dropped list. |
| Caution | `●` | Red outline. Kept, placed last in its block, note explains why. |
| Cleared | `✓` | Graphite. The unremarkable good state shouldn't shout as loudly as the dangerous one. |

### Palette

Cobalt belongs to the product — active member, goal targets, the main block, the copilot's voice — and **never means a status**, which leaves red to mean exactly one thing: a safety decision the graph enforced. The charts follow the same rule.

```css
--color-ground: #f1f1ef;  /* page */
--color-card:   #ffffff;  /* surfaces you act on */
--color-line:   #dededa;  /* hairlines */
--color-ink:    #0d0d0f;  /* text, primary actions */
--color-dim:    #5f5f68;  /* secondary text — 6.2:1 on card */
--color-faint:  #767680;  /* annotations — 4.6:1 on card */
--color-hush:   #a8a8af;  /* decorative only; nothing that matters */
--color-cobalt: #2b3fe8;  /* the product colour */
--color-red:    #cf3328;  /* safety, and only safety */
```

`--color-faint` was `#9a9aa1` (2.8:1, under AA) and carried dosing, rest intervals and filter reasons. Anything that reads as content is now at or above 4.5:1.

### Type

One family, Archivo, with its width axis at 125% for the display voice — the same variable font rather than a second family. Spline Sans Mono for anything machine-derived: dosing, durations, every provenance line. Self-hosted via `@fontsource`, so `docker compose up` works from a cold clone with no network.

Five named sizes, `--text-micro` (0.6875rem) through `--text-title` (1.125rem). Nothing meaningful renders below 11px; the build previously had a 9.5px tier carrying rest intervals and filter reasons.

### Iconography

Domain vernacular, not an icon library. Equipment reads `dumbbell` / `kettlebell` / `band` the way a coach writes it on a program sheet. Verdict marks are three pieces of hand-drawn geometry. No icon dependency ships.

---

## API surface

`prompt` is required and unconstrained; everything else is an optional hint. A request with nothing but a prompt is valid. Implemented in `web/src/api/client.ts`, one function per endpoint, **every one of them live against the Python API**. There is no mock layer left in the console.

| Method | Path | For |
|---|---|---|
| `GET` | `/api/coaches` | M1 |
| `GET` | `/api/members` | M2 — roster metadata, `has_context` flag |
| `GET` | `/api/members/{id}` | M3, M4 — full context; 404 when unpopulated |
| `GET` | `/api/members/{id}/eligibility?lifted=…` | M5 — live count |
| `POST` | `/api/members/{id}/plans` | M5, M6 — `{prompt, duration_min, lifted}` → `{plan, trace}` |
| `POST` | `/api/members/{id}/plans/{run_id}/adjust` | M8 — `{prompt}` → new run with `parent_run_id` |
| `GET` | `/api/members/{id}/messages` | M9 |
| `POST` | `/api/members/{id}/copilot` | M9, M10, M11 — may return a chart payload |
| `GET` | `/api/traces` | M13 — run list |
| `GET` | `/api/traces/{run_id}` | M13 — span waterfall and detail |

**`lifted[]` can never contain the injury.** It's loaded server-side from the member id, which comes from the session rather than the request body. There is no field the client can send to switch it off — the same reason the agent's tools don't expose one. The client filters it too, so the rule holds on both sides.

---

## Tests

`web/src/__tests__`, run with `npm test`. One file, and it tests shipped code:

- **`dates.test.ts`** — real frontend logic. Date-only strings must parse as local midnight; `new Date("2026-05-27")` is UTC and renders every date a day early west of Greenwich.

There was a second file, `mock.test.ts`, which tested the mock plan engine and said so. Both it and `web/src/api/mock/` are **deleted**: with every endpoint live there is nothing left to stand in for, and a suite asserting a stand-in's behaviour implies coverage that does not exist.

The two paths `ASSESSMENT.md:73` names — the concept resolver and the safety filter — are backend concerns and are tested there.
