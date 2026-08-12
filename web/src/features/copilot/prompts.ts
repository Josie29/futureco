import { QuickPromptGroup, type QuickPrompt } from "@/types"

/**
 * The quick-prompt palette (ASSESSMENT.md:39-42), in the two rows the spec
 * lays it out in: questions about the member, then the charts.
 *
 * An earlier pass folded all seven into four questions, on the grounds that
 * three of them differed only in whether they drew a chart, and that a chart
 * should arrive with the answer rather than behind its own button. That still
 * holds for the questions — `How's her adherence trending?` returns a chart and
 * sits in the top row regardless. What it got wrong is that `Compare last 4
 * weeks` is not the same request as `How's her adherence trending?`: one asks
 * for a trend, the other for sessions done against sessions planned, which is
 * the framing that leads to an action. The chart row is back because those are
 * distinct questions, not because charts need buttons.
 *
 * Labels stay as a coach would say them; `prompt` is what the backend receives,
 * so the two can differ where the spoken form is ambiguous to route on. Anything
 * else is still typeable, and the backend routes far more than these seven —
 * every metric she has readings for is reachable by name.
 *
 * These live here rather than in the API because they are console copy, not
 * member data: the same prompts suit any member, and round-tripping them would
 * make the palette wait on a fetch to render.
 */
export const QUICK_PROMPTS: QuickPrompt[] = [
  {
    label: "Show me the brief",
    prompt: "Show me the brief",
    group: QuickPromptGroup.MEMBER,
  },
  {
    label: "How's her adherence trending?",
    prompt: "How is her adherence trending?",
    group: QuickPromptGroup.MEMBER,
  },
  {
    label: "How has she been sleeping?",
    prompt: "How has she been sleeping?",
    group: QuickPromptGroup.MEMBER,
  },
  {
    label: "What's changed since last week?",
    prompt: "What changed since last week?",
    group: QuickPromptGroup.MEMBER,
  },
  {
    label: "Plot adherence trend",
    prompt: "Plot her adherence trend",
    group: QuickPromptGroup.CHARTS,
  },
  {
    label: "Show message pattern",
    prompt: "Show her message pattern",
    group: QuickPromptGroup.CHARTS,
  },
  {
    // Spelled out because the spoken form routes to the adherence trend, which
    // is the chart the row above already shows. What earns a separate chip is
    // completed against planned, in sessions rather than percent.
    label: "Compare last 4 weeks",
    prompt: "Compare sessions completed against sessions planned for the last 4 weeks",
    group: QuickPromptGroup.CHARTS,
  },
]
