import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { getEligibility } from "@/api/client"
import type { MemberContext, PlanRequest } from "@/types"

/**
 * The three at ASSESSMENT.md:27-31, plus two that exercise other paths. They
 * are here because the prompt is the only way to state intent, so a coach
 * meeting the console for the first time needs to see what it accepts.
 */
const EXAMPLES = [
  "Full-body session with isolation work around the pecs",
  "Lower body, but her left knee is bothering her",
  "Upper-body push and pull — no barbell, only dumbbells and a kettlebell",
  "Posterior chain and glutes, exclude deadlifts",
  "Low-impact conditioning and core, nothing with jumping",
] as const

/**
 * The request builder: a prompt and a window.
 *
 * Constraints are no longer toggles here — the coach states them in the
 * prompt ("no lunges", "must include squats") and the agent declares them as
 * typed directives, validated against the plan. The footer shows the standing
 * pool before any directive: what her chart alone rules out.
 */
export function Builder({
  member,
  memberId,
  onBuild,
  building,
  hasPlan,
}: {
  member: MemberContext
  memberId: string
  onBuild: (request: PlanRequest) => void
  building: boolean
  hasPlan: boolean
}) {
  const [prompt, setPrompt] = useState("")
  const [minutes, setMinutes] = useState(member.preferred_session_min)

  const eligibility = useQuery({
    queryKey: ["eligibility", memberId],
    queryFn: () => getEligibility(memberId),
  })

  const submit = () => {
    if (!prompt.trim() || building) return
    onBuild({ prompt: prompt.trim(), duration_min: minutes })
  }

  const pool = eligibility.data
  const eligiblePct = pool ? (pool.eligible / pool.total) * 100 : 0

  return (
    <section className="flex flex-col overflow-hidden rounded-[4px] border border-line bg-card">
      <div className="border-b border-soft p-3">
        <label htmlFor="prompt" className="mb-2 block text-micro font-semibold text-dim">
          What are we training?
        </label>
        <textarea
          id="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit()
          }}
          rows={2}
          placeholder="Full lower body, easy on the knee — she was sore after Tuesday"
          className="w-full resize-none rounded-[4px] border-[1.5px] border-ink bg-card px-2.5 py-2 text-body leading-relaxed placeholder:text-faint"
        />

        <div className="mt-2 flex flex-wrap gap-1">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setPrompt(example)}
              className="rounded-full border border-line px-2 py-0.5 text-micro text-dim hover:border-cobalt hover:text-cobalt"
            >
              {example}
            </button>
          ))}
        </div>
      </div>

      <div className="border-b border-soft p-3">
        <div className="mb-1.5 flex items-baseline justify-between">
          <label htmlFor="minutes" className="text-micro font-semibold text-dim">
            Length
          </label>
          <span className="num text-body">
            {minutes}
            <small className="text-micro font-medium text-dim"> min</small>
          </span>
        </div>
        <input
          id="minutes"
          type="range"
          min={20}
          max={90}
          step={5}
          value={minutes}
          onChange={(e) => setMinutes(Number(e.target.value))}
          className="h-1 w-full accent-ink"
        />
        {member.typical_session_min !== null && (
          <p className="mt-1 text-micro text-faint">
            Her completed sessions average {member.typical_session_min} min.
          </p>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 bg-ground p-3">
        <span className="min-w-0">
          {pool ? (
            <>
              <span className="num text-lead">{pool.eligible}</span>
              <span className="text-micro text-dim">
                {" "}
                of {pool.total} movements suit her right now
              </span>
              <span aria-hidden className="mt-1 flex h-1 overflow-hidden rounded-full bg-soft">
                <i className="bg-cobalt" style={{ width: `${eligiblePct}%` }} />
                <i className="bg-red/55" style={{ width: `${100 - eligiblePct}%` }} />
              </span>
              <span className="mt-1 block text-micro text-faint">
                {pool.blocked} blocked by her chart · {pool.cautioned} need care ·{" "}
                {pool.disliked} disliked
              </span>
            </>
          ) : (
            <span className="text-micro text-faint">Counting what suits her…</span>
          )}
        </span>

        <button
          type="button"
          onClick={submit}
          disabled={!prompt.trim() || building}
          className="shrink-0 rounded-[4px] bg-ink px-3 py-1.5 text-meta font-semibold text-white disabled:opacity-40"
        >
          {building ? "Building…" : hasPlan ? "Rebuild session" : "Build session"}
        </button>
      </div>
    </section>
  )
}
