import { useState } from "react"
import { formatMessageTime } from "@/lib/dates"
import { cn } from "@/lib/utils"
import type { CopilotMessage, MemberMessage } from "@/types"

/** The four mandated by ASSESSMENT.md:41, shortened to fit the dock. */
const QUICK_PROMPTS = [
  { label: "The brief", prompt: "Show me the brief" },
  { label: "Adherence", prompt: "How's adherence trending?" },
  { label: "Sleep", prompt: "Sleep this week" },
  { label: "What changed", prompt: "What changed since last week?" },
] as const

type Tab = "copilot" | "messages"

function CopilotThread({
  messages,
  onOpenMessages,
}: {
  messages: CopilotMessage[]
  onOpenMessages: () => void
}) {
  return (
    <>
      {messages.map((m) => (
        <article key={m.id} className="flex flex-col gap-1">
          <span className="text-[0.625rem] text-faint">
            {m.from === "copilot" ? "Copilot" : "You"} · {formatMessageTime(m.ts)}
          </span>

          <div
            className={cn(
              "text-[0.6875rem] leading-relaxed",
              m.from === "copilot" &&
                "rounded-r-[4px] border-l-2 border-cobalt bg-ground px-2 py-2",
            )}
          >
            {m.paragraphs.map((p, i) => (
              <p key={i} className={cn(i > 0 && "mt-1.5")}>
                {p.lead && <strong className="font-semibold">{p.lead} </strong>}
                {p.text}
              </p>
            ))}

            {/* A member message quoted as evidence. Grounding made visible:
                the coach can see the retrieval rather than trust the sentence. */}
            {m.cites?.map((c) => (
              <button
                key={c.message_id}
                type="button"
                onClick={onOpenMessages}
                className="mt-1.5 flex w-full flex-col gap-px rounded-[4px] border border-line bg-card px-1.5 py-1 text-left hover:border-cobalt"
              >
                <span className="text-[0.5625rem] text-faint">
                  {c.from} · {c.when} · open in Messages
                </span>
                <span className="text-[0.625rem] text-dim italic">"{c.text}"</span>
              </button>
            ))}
          </div>
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
                "rounded-[4px] border px-2 py-1.5 text-[0.6875rem] leading-snug",
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
                className="rounded-[4px] border border-dashed border-line px-1.5 py-1 font-mono text-[0.5938rem] text-faint"
              >
                img · {a.caption}
              </span>
            ))}

            <span className="text-[0.5625rem] text-faint">
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
 */
export function CopilotDock({
  memberName,
  copilotMessages,
  memberMessages,
  onAsk,
}: {
  memberName: string
  copilotMessages: CopilotMessage[]
  memberMessages: MemberMessage[]
  onAsk: (text: string) => void
}) {
  const [tab, setTab] = useState<Tab>("copilot")
  const [draft, setDraft] = useState("")
  const firstName = memberName.split(" ")[0]

  const send = (text: string) => {
    if (!text.trim() || tab !== "copilot") return
    onAsk(text.trim())
    setDraft("")
  }

  return (
    <aside aria-label="Copilot" className="flex w-80 shrink-0 flex-col border-l border-line bg-card">
      <div className="flex border-b border-line" role="tablist">
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
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 border-b-2 px-2.5 py-2 text-xs font-semibold",
              tab === key ? "border-b-cobalt text-ink" : "border-b-transparent text-faint",
            )}
          >
            {label}
            {count !== null && (
              <span className="rounded-full bg-soft px-1.5 font-mono text-[0.5625rem] font-normal text-dim">
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto p-3">
        {tab === "copilot" ? (
          <>
            <div className="flex flex-wrap gap-1">
              {QUICK_PROMPTS.map((q) => (
                <button
                  key={q.label}
                  type="button"
                  onClick={() => send(q.prompt)}
                  className="rounded-full border border-line px-2 py-0.5 text-[0.625rem] text-dim hover:border-cobalt hover:text-cobalt"
                >
                  {q.label}
                </button>
              ))}
            </div>
            <CopilotThread messages={copilotMessages} onOpenMessages={() => setTab("messages")} />
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
          className="min-w-0 flex-1 bg-transparent text-[0.6875rem] outline-none placeholder:text-faint"
        />
        <span aria-hidden className="font-mono text-[0.6875rem] text-faint">
          ▸
        </span>
      </form>
    </aside>
  )
}
