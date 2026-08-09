import type { QuickPrompt } from "@/types"

/**
 * The quick-prompt palette (ASSESSMENT.md:39-42), written as questions rather
 * than labels.
 *
 * Seven two-word chips read as a filter bar, not as things you can ask, and
 * three of them differed only in whether they drew a chart. Folded to four
 * questions a coach would say out loud; charts come back with the answer where
 * a chart is the clearest form, rather than being a separate button. Anything
 * else is still typeable, and the backend routes far more than these four —
 * every metric she has readings for is reachable by name.
 *
 * These live here rather than in the API because they are console copy, not
 * member data: the same four questions suit any member, and round-tripping
 * them would make the palette wait on a fetch to render.
 */
export const QUICK_PROMPTS: QuickPrompt[] = [
  {
    label: "What do I need to know this morning?",
    prompt: "Show me the brief",
    is_chart: false,
  },
  {
    label: "How's her adherence trending?",
    prompt: "How is her adherence trending?",
    is_chart: true,
  },
  { label: "How has she been sleeping?", prompt: "How has she been sleeping?", is_chart: true },
  {
    label: "What's changed since last week?",
    prompt: "What changed since last week?",
    is_chart: false,
  },
]
