import { useEffect, useRef, useState } from "react"
import { QUICK_PROMPTS } from "@/features/copilot/prompts"
import { CopilotChart } from "@/features/copilot/CopilotChart"
import { formatMessageTime } from "@/lib/dates"
import { cn } from "@/lib/utils"
import { QuickPromptGroup, type CopilotMessage, type MemberMessage } from "@/types"

type Tab = "copilot" | "messages"

function PendingAnswer() {
  return (
    <div
      className="flex animate-pulse flex-col gap-1 rounded-r-[4px] border-l-2 border-cobalt bg-ground px-2 py-2"
      role="status"
      aria-label="Retrieving from her record"
    >
      <span className="h-1.5 w-4/5 rounded-full bg-soft" />
      <span className="h-1.5 w-full rounded-full bg-soft" />
      <span className="h-1.5 w-2/3 rounded-full bg-soft" />
    </div>
  )
}

function CopilotThread({
  messages,
  loading,
  onOpenMessages,
}: {
  messages: CopilotMessage[]
  loading: boolean
  onOpenMessages: () => void
}) {
  if (loading) {
    return <PendingAnswer />
  }

  return (
    <>
      {messages.map((m) => (
        <article key={m.id} className="flex flex-col gap-1">
          <span className="text-micro text-faint">
            {m.from === "copilot" ? "Copilot" : "You"} · {formatMessageTime(m.ts)}
          </span>

          {m.pending ? (
            <PendingAnswer />
          ) : (
            <div
              className={cn(
                "text-meta leading-relaxed",
                m.from === "copilot" && "rounded-r-[4px] border-l-2 border-cobalt bg-ground px-2 py-2",
              )}
            >
              {/* An answer that did less than it appears to must never look
                  whole. Set when synthesis was unavailable, a citation was
                  dropped as invented, or the model declined — the three ways
                  this surface can quietly under-deliver. Above the text, not
                  below it, so it is read before the answer rather than after. */}
              {m.degraded && (
                <p className="mb-1.5 rounded-[4px] border border-line bg-card px-1.5 py-1 text-micro text-faint">
                  {m.degraded}
                </p>
              )}

              {m.paragraphs.map((p, i) => (
                <p key={i} className={cn(i > 0 && "mt-1.5")}>
                  {p.lead && <strong className="font-semibold">{p.lead} </strong>}
                  {p.text}
                </p>
              ))}

              {m.chart && <CopilotChart chart={m.chart} />}

              {/* A member message quoted as evidence. Grounding made visible:
                  the coach can see the retrieval rather than trust the sentence. */}
              {m.cites?.map((c) => (
                <button
                  key={c.message_id}
                  type="button"
                  onClick={onOpenMessages}
                  className="mt-1.5 flex w-full flex-col gap-px rounded-[4px] border border-line bg-card px-1.5 py-1 text-left hover:border-cobalt"
                >
                  <span className="text-micro text-faint">
                    {c.from} · {c.when} · open in Messages
                  </span>
                  <span className="text-micro text-dim italic">"{c.text}"</span>
                </button>
              ))}
            </div>
          )}
        </article>
      ))}
    </>
  )
}

function MessageThread({ messages, memberName }: { messages: MemberMessage[]; memberName: string }) {
  return (
    <div className="flex flex-col gap-2.5">
      {messages.map((m) => {
        const mine = m.from === "coach"
        return (
          <article
            key={m.id}
            className={cn("flex max-w-[88%] flex-col gap-0.5", mine && "items-end self-end")}
          >
            <p
              className={cn(
                "rounded-[4px] border px-2 py-1.5 text-meta leading-snug",
                mine ? "border-ink bg-ink text-white" : "border-line bg-ground",
              )}
            >
              {m.text}
            </p>

            {m.attachments?.map((a, i) => (
              // The sample attachment carries a caption but no URL, so this
              // renders the caption rather than an <img> that would 404.
              <span
                key={i}
                className="rounded-[4px] border border-dashed border-line px-1.5 py-1 font-mono text-micro text-faint"
              >
                img · {a.caption}
              </span>
            ))}

            <span className="text-micro text-faint">
              {mine ? "You" : memberName} · {formatMessageTime(m.ts)}
            </span>
          </article>
        )
      })}
    </div>
  )
}

/**
 * Two threads, because there are two conversations.
 *
 * Jordan's messages are member context the copilot retrieves *over* — they are
 * not turns in the coach's conversation with the AI. Merging them would imply
 * the member can read the copilot's answers.
 *
 * The dock widens on demand: the brief is the most important thing a coach
 * reads all morning and it does not deserve to live at 20rem forever.
 */
export function CopilotDock({
  memberName,
  copilotMessages,
  memberMessages,
  loadingThread,
  onAsk,
}: {
  memberName: string
  copilotMessages: CopilotMessage[]
  memberMessages: MemberMessage[]
  loadingThread: boolean
  onAsk: (text: string) => void
}) {
  const [tab, setTab] = useState<Tab>("copilot")
  const [draft, setDraft] = useState("")
  const [wide, setWide] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const firstName = memberName.split(" ")[0]

  // New turns land at the bottom, so the thread follows them there.
  useEffect(() => {
    const node = scroller.current
    if (node) node.scrollTop = node.scrollHeight
  }, [copilotMessages.length, tab])

  const send = (text: string) => {
    if (!text.trim() || tab !== "copilot") return
    onAsk(text.trim())
    setDraft("")
  }

  return (
    <aside
      aria-label="Copilot"
      className={cn(
        "flex min-h-0 shrink-0 flex-col border-l border-line bg-card transition-[width]",
        wide ? "w-[26rem]" : "w-80",
      )}
    >
      <div className="flex items-center border-b border-line">
        <div className="flex flex-1" role="tablist" aria-label="Copilot and messages">
          {(
            [
              ["copilot", "Copilot", null],
              ["messages", "Messages", memberMessages.length],
            ] as const
          ).map(([key, label, count]) => (
            <button
              key={key}
              type="button"
              role="tab"
              id={`tab-${key}`}
              aria-selected={tab === key}
              aria-controls={`panel-${key}`}
              onClick={() => setTab(key)}
              className={cn(
                "flex flex-1 items-center justify-center gap-1.5 border-b-2 px-2.5 py-2 text-meta font-semibold",
                tab === key ? "border-b-cobalt text-ink" : "border-b-transparent text-faint",
              )}
            >
              {label}
              {count !== null && (
                <span className="rounded-full bg-soft px-1.5 font-mono text-micro font-normal text-dim">
                  {count}
                </span>
              )}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => setWide((v) => !v)}
          aria-pressed={wide}
          title={wide ? "Narrow the panel" : "Widen the panel"}
          className="px-2 py-2 font-mono text-micro text-faint hover:text-ink"
        >
          {wide ? "▸|" : "|◂"}
        </button>
      </div>

      <div
        ref={scroller}
        id={`panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`tab-${tab}`}
        className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto p-3"
      >
        {tab === "copilot" ? (
          <>
            {/* Questions stacked full-width, because a coach reads those as
                things to ask. The chart chips wrap inline instead: they are
                named outputs rather than sentences, and stacking all seven the
                same way would read as a filter bar. */}
            <div className="flex flex-col gap-1">
              {QUICK_PROMPTS.filter((q) => q.group === QuickPromptGroup.MEMBER).map((q) => (
                <button
                  key={q.label}
                  type="button"
                  onClick={() => send(q.prompt)}
                  className="rounded-[4px] border border-line px-2 py-1 text-left text-micro text-dim hover:border-cobalt hover:text-cobalt"
                >
                  {q.label}
                </button>
              ))}
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-micro uppercase tracking-wide text-soft">Charts</span>
              <div className="flex flex-wrap gap-1">
                {QUICK_PROMPTS.filter((q) => q.group === QuickPromptGroup.CHARTS).map((q) => (
                  <button
                    key={q.label}
                    type="button"
                    onClick={() => send(q.prompt)}
                    className="rounded-[4px] border border-line px-2 py-1 text-left text-micro text-dim hover:border-cobalt hover:text-cobalt"
                  >
                    {q.label}
                  </button>
                ))}
              </div>
            </div>
            <CopilotThread
              messages={copilotMessages}
              loading={loadingThread && copilotMessages.length === 0}
              onOpenMessages={() => setTab("messages")}
            />
          </>
        ) : (
          <MessageThread messages={memberMessages} memberName={firstName} />
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          send(draft)
        }}
        className="m-3 mt-0 flex items-center gap-2 rounded-[4px] border border-line bg-ground px-1.5 py-1"
      >
        <input
          value={tab === "copilot" ? draft : ""}
          onChange={(e) => setDraft(e.target.value)}
          disabled={tab === "messages"}
          placeholder={tab === "copilot" ? `Ask about ${firstName}` : `Message ${firstName}`}
          aria-label={tab === "copilot" ? `Ask about ${firstName}` : `Message ${firstName}`}
          className="min-w-0 flex-1 bg-transparent text-meta outline-none placeholder:text-faint"
        />
        <span aria-hidden className="font-mono text-meta text-faint">
          ▸
        </span>
      </form>
    </aside>
  )
}
