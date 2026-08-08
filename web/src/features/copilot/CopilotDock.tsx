import { useState } from "react"
import { formatMessageTime } from "@/lib/dates"
import { cn } from "@/lib/utils"
import type { ChatMessage } from "@/types"

/** The four mandated by ASSESSMENT.md:41. */
const QUICK_PROMPTS = [
  "Show me the brief",
  "How's adherence trending?",
  "Sleep this week",
  "What changed since last week?",
] as const

const FROM_LABEL: Record<ChatMessage["from"], string> = {
  member: "",
  coach: "You",
  copilot: "Copilot",
}

export function CopilotDock({
  memberName,
  messages,
  onSend,
}: {
  memberName: string
  messages: ChatMessage[]
  onSend: (text: string) => void
}) {
  const [draft, setDraft] = useState("")
  const firstName = memberName.split(" ")[0]

  const send = (text: string) => {
    if (!text.trim()) return
    onSend(text.trim())
    setDraft("")
  }

  return (
    <aside
      aria-label="Copilot"
      className="flex w-96 shrink-0 flex-col gap-2 border-l border-rule bg-plate p-3"
    >
      <div className="eyebrow">Copilot</div>

      <div className="flex flex-col gap-1">
        {QUICK_PROMPTS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => send(p)}
            className="rounded-[3px] border border-rule bg-film px-2 py-1 text-left text-[11px] hover:border-ink"
          >
            {p}
          </button>
        ))}
      </div>

      <hr className="border-rule" />

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
        {messages.map((m) => (
          <article key={m.id} className="flex flex-col gap-0.5">
            <span className="eyebrow">
              {m.from === "member" ? firstName : FROM_LABEL[m.from]} ·{" "}
              {formatMessageTime(m.ts)}
            </span>
            <p
              className={cn(
                "text-[11px] leading-relaxed",
                m.from === "copilot" && "text-ink",
              )}
            >
              {m.text}
            </p>

            {m.attachments?.map((a, i) => (
              // The sample attachment carries a caption but no URL, so this
              // renders the caption rather than an <img> that would 404.
              <div
                key={i}
                className="rounded-[3px] border border-dashed border-rule p-2 font-mono text-[10px] text-slate-soft"
              >
                IMG · {a.caption}
              </div>
            ))}
          </article>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          send(draft)
        }}
        className="mt-auto flex items-center gap-2 rounded-[3px] border border-rule bg-film px-2 py-1"
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={`Ask about ${firstName}`}
          aria-label={`Ask about ${firstName}`}
          className="min-w-0 flex-1 bg-transparent text-[11px] outline-none placeholder:text-slate-soft"
        />
        <button type="submit" className="font-mono text-[11px] text-slate">
          ▸
        </button>
      </form>
    </aside>
  )
}
