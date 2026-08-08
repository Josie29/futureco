# KG2 — Member Context Schema

## Node types

| Node | Count | Source | Notes |
|---|---|---|---|
| `Member` | 1 | `data/member-context.json` — `profile` | Root of the graph; every KG2 edge originates here or from one of its children |
| `Preference` | 5 | data — `preferences` | One node per preference (`preferred_session_minutes`, `training_days_per_week`, `preferred_days`, `dislikes`, `notes`). Keyed `<member_id>:<key>`, since a preference belongs to a member and Neo4j Community enforces uniqueness on one property only. The raw `value` stays on the node even where it also becomes edges |
| `Goal` | 3 | data — `goals[]` | Carries `text`, `priority`, `target_date`, `targets[]` |
| `Equipment` | 5 | data — `equipment_available[]` | **Shared with KG1** — same nodes, joined by name |
| `Exercise` | 50 | KG1 — `data/exercises.json` | **Shared with KG1** — target of `dislikes` |
| `Muscle` | 19 | KG1 — `muscle_groups` | **Shared with KG1** — target of `targets` |
| `Injury` | 1 | data — `injuries[]` | **Shared with KG1** — declared here, contraindication edges live in KG1 |

---

## Edge types

| Edge | From → To | Source | Purpose |
|---|---|---|---|
| `has` | Member → `Preference` \| `Goal` \| `Equipment` \| `Injury` | data — `preferences`, `goals[]`, `equipment_available[]`, `injuries[]` | Member ownership. Target label supplies the meaning: **Preference** = constraint on programming · **Goal** = intent · **Equipment** = availability filter for KG1 `requires` · **Injury** = entry point to KG1 `contraindicates` / `cautions` |
| `dislikes` | Preference → Exercise | data — `preferences.dislikes[]` | Soft exclude; crosses into KG1 |
| `targets` | Goal → Muscle | data — `goals[].targets[]` | What the goal trains; crosses into KG1. May be empty (non-muscular goals) |

Schema decisions are recorded in [`decisions.md`](decisions.md) under *KG2*.

---

## Diagram

```mermaid
flowchart LR
  MEM["Member"]
  PRF["Preference<br/>5"]
  GOL["Goal<br/>3"]
  EQP["Equipment<br/>5"]
  EX["Exercise<br/>50"]
  MUS["Muscle<br/>19"]
  INJ["Injury<br/>1"]

  MEM -->|has| PRF
  MEM -->|has| GOL
  MEM -->|has| EQP
  MEM -->|has| INJ

  PRF -->|dislikes| EX
  GOL -->|targets| MUS

  style EQP fill:#1f3a2d,stroke:#5a9a7a,color:#e8f0ea
  style EX fill:#1f3a2d,stroke:#5a9a7a,color:#e8f0ea
  style MUS fill:#1f3a2d,stroke:#5a9a7a,color:#e8f0ea
  style INJ fill:#1f3a2d,stroke:#5a9a7a,color:#e8f0ea
```

Green = shared with KG1.

---

## Unmatched dislikes report rather than fail

A dislike is free text a coach typed, so it can always name a movement this catalog does not stock — and that is not a defect. The member's preference is true; there is simply nothing to exclude. So `dislikes` is the one cross-graph join that reports its misses and continues, while every structural join stays fatal. The raw list stays on the `Preference` node either way, so a coach still sees a preference the graph could not act on.

It marks the boundary of a build-time exact-match join. Category words like *"deadlifts"* or *"burpees"* are what the request-time concept resolver exists for, and its fuzzy and embedding passes could plausibly reach a **pattern** rather than an exercise — a distinction this schema has no edge for. Worth revisiting once the resolver exists.
