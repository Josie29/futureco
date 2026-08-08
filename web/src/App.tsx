import { useState } from "react"
import {
  mockCoaches,
  mockAnswer,
  mockCopilotMessages,
  mockMember,
  mockMemberMessages,
  mockPlan,
  mockRoster,
} from "@/api/mock"
import { Builder } from "@/features/generator/Builder"
import { PlanSheet } from "@/features/generator/PlanSheet"
import { CopilotDock } from "@/features/copilot/CopilotDock"
import { Goals } from "@/features/member/Goals"
import { MemberHeader } from "@/features/member/MemberHeader"
import { RecentSessions } from "@/features/member/RecentSessions"
import { Rail } from "@/features/roster/Rail"
import { TODAY, formatSessionDay } from "@/lib/dates"
import type { CopilotMessage, PlanRequest, WorkoutPlan } from "@/types"

/** Named stages, so a multi-second wait says what it is doing. */
const BUILD_STAGES = [
  "Resolving what you asked for",
  "Loading her constraints",
  "Filtering the catalogue",
  "Assembling the session",
] as const

const STAGE_MS = 320

function EmptyMember({ name }: { name: string }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="max-w-sm text-center">
        <p className="disp text-base">No context loaded for {name}</p>
        <p className="mt-2 text-[0.8125rem] text-dim">
          This build ships one fully-populated synthetic member. Select Jordan Rivera to see
          the generator and copilot working against real data.
        </p>
      </div>
    </div>
  )
}

function BuildProgress({ stage }: { stage: number }) {
  return (
    <div
      className="flex flex-col gap-1 rounded-[4px] border border-line bg-card p-3"
      role="status"
      aria-live="polite"
    >
      {BUILD_STAGES.map((s, i) => (
        <span
          key={s}
          className={
            i < stage
              ? "font-mono text-[0.625rem] text-faint"
              : i === stage
                ? "font-mono text-[0.625rem] text-ink"
                : "font-mono text-[0.625rem] text-line"
          }
        >
          {i < stage ? "done" : i === stage ? "▸" : "·"} {s}
        </span>
      ))}
    </div>
  )
}

export default function App() {
  const [activeId, setActiveId] = useState(mockRoster[0].id)
  const [plan, setPlan] = useState<WorkoutPlan | null>(null)
  const [stage, setStage] = useState<number | null>(null)
  const [copilot, setCopilot] = useState<CopilotMessage[]>(mockCopilotMessages)

  const active = mockRoster.find((m) => m.id === activeId)!
  const coach = mockCoaches[0]
  const building = stage !== null

  const build = (req: PlanRequest) => {
    setStage(0)
    // Walks the named stages so the wait is legible. The real endpoint will
    // stream these; the shape of the UI does not change when it does.
    BUILD_STAGES.forEach((_, i) => {
      window.setTimeout(() => setStage(i), i * STAGE_MS)
    })
    window.setTimeout(() => {
      setPlan(mockPlan(req))
      setStage(null)
    }, BUILD_STAGES.length * STAGE_MS)
  }

  const ask = (text: string) => {
    setCopilot((prev) => [
      ...prev,
      {
        id: `cp_ask_${prev.length}`,
        ts: new Date().toISOString(),
        from: "coach",
        paragraphs: [{ text }],
      },
      mockAnswer(text, `cp_ans_${prev.length}`),
    ])
  }

  return (
    <div className="flex h-dvh flex-col bg-ground text-ink">
      <header className="flex items-center justify-between border-b border-line bg-card px-3.5 py-2">
        <span className="text-[0.8125rem] font-semibold">
          future <span className="font-normal text-faint">· coach console</span>
        </span>
        <span className="text-[0.6875rem] text-dim">{coach.name}</span>
      </header>

      <div className="flex min-h-0 flex-1">
        <Rail members={mockRoster} activeId={activeId} onSelect={setActiveId} />

        {active.has_context ? (
          <main className="min-w-0 flex-1 overflow-y-auto p-4 pb-6">
            {/* Capped so dosing stays beside its exercise and goal deadlines
                stay beside their goal, rather than being flung to the far
                edge of a wide window. */}
            <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 [&>*]:shrink-0">
              <MemberHeader member={mockMember} />
              <Goals goals={mockMember.goals} />
              <RecentSessions
                sessions={mockMember.recent_sessions}
                todayLabel={formatSessionDay(TODAY)}
                building={building}
              />
              <Builder member={mockMember} onBuild={build} building={building} />
              {building && <BuildProgress stage={stage} />}
              {plan && !building && <PlanSheet plan={plan} />}
            </div>
          </main>
        ) : (
          <EmptyMember name={active.name} />
        )}

        <CopilotDock
          memberName={mockMember.name}
          copilotMessages={copilot}
          memberMessages={mockMemberMessages}
          onAsk={ask}
        />
      </div>
    </div>
  )
}
