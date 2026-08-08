import { useState } from "react"
import {
  mockCoaches,
  mockMember,
  mockMessages,
  mockPlan,
  mockRoster,
} from "@/api/mock"
import { Builder } from "@/features/generator/Builder"
import { PlanSheet } from "@/features/generator/PlanSheet"
import { MemberHeader } from "@/features/member/MemberHeader"
import { RecentSessions } from "@/features/member/RecentSessions"
import { CopilotDock } from "@/features/copilot/CopilotDock"
import { Rail } from "@/features/roster/Rail"
import type { ChatMessage, PlanRequest, WorkoutPlan } from "@/types"

/** Named stages, so a multi-second wait says what it's doing (P3). */
const BUILD_STAGES = [
  "Resolving concepts",
  "Loading member constraints",
  "Filtering catalogue",
  "Assembling plan",
] as const

function EmptyMember({ name }: { name: string }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="max-w-sm text-center">
        <p className="expanded text-base">No context loaded for {name}</p>
        <p className="mt-2 text-[13px] text-slate">
          This build ships one fully-populated synthetic member. Select Jordan
          Rivera to see the generator and copilot working against real data.
        </p>
      </div>
    </div>
  )
}

export default function App() {
  const [activeId, setActiveId] = useState(mockRoster[0].id)
  const [plan, setPlan] = useState<WorkoutPlan | null>(null)
  const [stage, setStage] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>(mockMessages)

  const active = mockRoster.find((m) => m.id === activeId)!
  const coach = mockCoaches[0]

  const build = (req: PlanRequest) => {
    setStage(0)
    // Walks the named stages so the wait is legible. The real endpoint will
    // stream these; the shape of the UI does not change when it does.
    BUILD_STAGES.forEach((_, i) => {
      window.setTimeout(() => setStage(i), i * 320)
    })
    window.setTimeout(() => {
      setPlan(mockPlan(req))
      setStage(null)
    }, BUILD_STAGES.length * 320)
  }

  const send = (text: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `msg_local_${prev.length}`,
        ts: new Date().toISOString(),
        from: "coach",
        text,
      },
    ])
  }

  return (
    <div className="flex h-dvh flex-col bg-plate text-ink">
      <header className="flex items-center justify-between border-b border-rule bg-film px-3 py-2">
        <span className="text-[13px] font-semibold">
          future <span className="font-normal text-slate-soft">· coach console</span>
        </span>
        <span className="text-[11px] text-slate">{coach.name}</span>
      </header>

      <div className="flex min-h-0 flex-1">
        <Rail members={mockRoster} activeId={activeId} onSelect={setActiveId} />

        {active.has_context ? (
          // Children must not shrink: inside a scrolling flex column they
          // otherwise compress to fit the viewport instead of overflowing it.
          <main className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto p-3 [&>*]:shrink-0">
            <MemberHeader member={mockMember} />
            <RecentSessions sessions={mockMember.recent_sessions} />
            <Builder
              member={mockMember}
              onBuild={build}
              building={stage !== null}
            />

            {stage !== null && (
              <div className="flex flex-col gap-1 rounded-md border border-rule bg-film p-3">
                {BUILD_STAGES.map((s, i) => (
                  <span
                    key={s}
                    className="font-mono text-[10px]"
                    style={{
                      color:
                        i < stage
                          ? "var(--color-slate-soft)"
                          : i === stage
                            ? "var(--color-ink)"
                            : "var(--color-rule)",
                    }}
                  >
                    {i < stage ? "done" : i === stage ? "▸" : "·"} {s}
                  </span>
                ))}
              </div>
            )}

            {plan && stage === null && <PlanSheet plan={plan} />}
          </main>
        ) : (
          <EmptyMember name={active.name} />
        )}

        <CopilotDock
          memberName={mockMember.name}
          messages={messages}
          onSend={send}
        />
      </div>
    </div>
  )
}
