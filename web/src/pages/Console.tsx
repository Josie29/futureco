import { useCallback, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate, useParams } from "react-router-dom"
import {
  ApiError,
  adjustPlan,
  askCopilot,
  createPlan,
  getCopilotThread,
  getMember,
  getMessages,
  getRoster,
} from "@/api/client"
import { Builder } from "@/features/generator/Builder"
import { BuildProgress } from "@/features/generator/BuildProgress"
import { PlanSheet } from "@/features/generator/PlanSheet"
import { CopilotDock } from "@/features/copilot/CopilotDock"
import { Goals } from "@/features/member/Goals"
import { MemberHeader } from "@/features/member/MemberHeader"
import { RecentSessions } from "@/features/member/RecentSessions"
import { Rail } from "@/features/roster/Rail"
import { setReferenceDate } from "@/lib/dates"
import { cn } from "@/lib/utils"
import type { CopilotMessage, PlanRequest, WorkoutPlan } from "@/types"

function Centered({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="max-w-sm text-center">
        <p className="disp text-lead">{title}</p>
        <p className="mt-2 text-meta text-dim">{body}</p>
      </div>
    </div>
  )
}

/** Skeletons shaped like the content that replaces them, so nothing shifts. */
function ConsoleSkeleton() {
  return (
    <main className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4" aria-busy="true">
      <div className="mx-auto flex w-full max-w-4xl animate-pulse flex-col gap-5">
        <div className="h-16 rounded-[4px] bg-soft" />
        <div className="h-24 rounded-[4px] bg-soft" />
        <div className="h-20 rounded-[4px] bg-soft" />
        <div className="h-56 rounded-[4px] bg-soft" />
      </div>
    </main>
  )
}

export default function Console() {
  const { memberId = "" } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [plan, setPlan] = useState<WorkoutPlan | null>(null)
  // Lives here rather than in the builder because an adjustment has to carry
  // it too — otherwise refining a plan silently re-enables the equipment the
  // coach just switched off.
  const [disabled, setDisabled] = useState<string[]>([])
  const [thread, setThread] = useState<CopilotMessage[] | null>(null)

  const roster = useQuery({ queryKey: ["roster"], queryFn: getRoster })
  const member = useQuery({
    queryKey: ["member", memberId],
    queryFn: async () => {
      const context = await getMember(memberId)
      // The API derives the dataset's "today" from the record. Adopting it here
      // keeps relative timestamps in the chat agreeing with the figures the
      // server computed against the same date.
      setReferenceDate(context.as_of)
      return context
    },
    enabled: Boolean(memberId),
    retry: false,
  })
  const messages = useQuery({
    queryKey: ["messages", memberId],
    queryFn: () => getMessages(memberId),
    enabled: member.isSuccess,
  })
  const copilotThread = useQuery({
    queryKey: ["copilot", memberId],
    queryFn: () => getCopilotThread(memberId),
    enabled: member.isSuccess,
  })

  // The thread is server state until the coach adds to it, at which point the
  // local copy takes over. Seeding on first read keeps the brief on screen
  // without a second source of truth for the whole session.
  const copilot = thread ?? copilotThread.data ?? []

  // The builder always starts a fresh run, even when a plan is on screen. Its
  // prompt is a whole request rather than a delta, so composing it onto the
  // previous run would apply constraints the coach had just deleted from the
  // box. Refinement is the adjust bar's job, and only its job.
  const build = useMutation({
    mutationFn: (request: PlanRequest) => createPlan(memberId, request),
    onSuccess: setPlan,
  })

  // An adjustment composes onto its parent server-side: the parent's
  // instructions are loaded and this utterance's appended, so "only dumbbells"
  // then "exclude lunges" keeps both.
  const rebuildFrom = useMutation({
    mutationFn: ({ runId, request }: { runId: string; request: PlanRequest }) =>
      adjustPlan(memberId, runId, request),
    onSuccess: setPlan,
  })

  const ask = useCallback(
    async (text: string) => {
      const stamp = Date.now()
      const question: CopilotMessage = {
        id: `cp_ask_${stamp}`,
        ts: new Date().toISOString(),
        from: "coach",
        paragraphs: [{ text }],
      }
      const placeholder: CopilotMessage = {
        id: `cp_ans_${stamp}`,
        ts: new Date().toISOString(),
        from: "copilot",
        paragraphs: [],
        pending: true,
      }

      setThread((prev) => [...(prev ?? copilotThread.data ?? []), question, placeholder])

      try {
        const reply = await askCopilot(memberId, text, placeholder.id)
        setThread((prev) => (prev ?? []).map((m) => (m.id === placeholder.id ? reply : m)))
      } catch {
        setThread((prev) =>
          (prev ?? []).map((m) =>
            m.id === placeholder.id
              ? {
                  ...m,
                  pending: false,
                  paragraphs: [{ text: "That request failed. Try asking again." }],
                }
              : m,
          ),
        )
      }
    },
    [copilotThread.data, memberId],
  )

  const selectMember = useCallback(
    (id: string) => {
      // A new member means a new plan and a new thread; carrying either across
      // would put one member's context under another's name.
      setPlan(null)
      setThread(null)
      setDisabled([])
      queryClient.removeQueries({ queryKey: ["copilot"] })
      navigate(`/m/${id}`)
    },
    [navigate, queryClient],
  )

  const rail = (
    <Rail members={roster.data ?? []} activeId={memberId} onSelect={selectMember} />
  )

  if (member.isError) {
    const notFound = member.error instanceof ApiError && member.error.status === 404
    const name = roster.data?.find((m) => m.id === memberId)?.name ?? "this member"
    return (
      <>
        {rail}
        <Centered
          title={notFound ? `No context loaded for ${name}` : "Couldn't load that member"}
          body={
            notFound
              ? "This build ships one fully-populated synthetic member. Select Jordan Rivera to see the generator and copilot working against real data."
              : "The request failed. Pick the member again to retry."
          }
        />
      </>
    )
  }

  if (member.isPending || !member.data) {
    return (
      <>
        {rail}
        <ConsoleSkeleton />
      </>
    )
  }

  const context = member.data
  const busy = build.isPending || rebuildFrom.isPending

  return (
    <>
      {rail}

      <main className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4 pb-6">
        {/* Capped so dosing stays beside its exercise and goal deadlines stay
            beside their goal, rather than being flung to the far edge of a
            wide window. */}
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 [&>*]:shrink-0">
          <MemberHeader member={context} />
          <Goals goals={context.goals} />
          <RecentSessions sessions={context.recent_sessions} />
          <Builder
            member={context}
            memberId={memberId}
            disabled={disabled}
            onDisabledChange={setDisabled}
            onBuild={(request) => build.mutate(request)}
            building={busy}
            hasPlan={plan !== null}
          />

          {busy && <BuildProgress adjusting={plan !== null} />}

          {build.isError && !busy && (
            <p className="rounded-[4px] border border-red bg-red-wash p-2.5 text-meta text-red">
              {build.error instanceof ApiError
                ? build.error.message
                : "The generator didn't respond. Try building again."}
            </p>
          )}

          {/* The previous plan stays mounted while the next one builds — it is
              the thing the coach is comparing against. */}
          {plan && (
            <div className={cn(busy && "pointer-events-none opacity-40")}>
              <PlanSheet
                plan={plan}
                onAdjust={(prompt) =>
                  rebuildFrom.mutate({
                    runId: plan.run_id,
                    request: {
                      prompt,
                      duration_min: plan.requested_minutes,
                      disabled,
                    },
                  })
                }
                adjusting={rebuildFrom.isPending}
              />
            </div>
          )}
        </div>
      </main>

      <CopilotDock
        memberName={context.name}
        copilotMessages={copilot}
        memberMessages={messages.data ?? []}
        loadingThread={copilotThread.isPending}
        onAsk={ask}
      />
    </>
  )
}
