import {
  SLEEP_TARGET_HOURS,
  churnRisk,
  firstName,
  member,
  memberMessages,
  oneDp,
  preferredSessionMinutes,
  sleepAvg,
  sleepNights,
  trainingDaysPerWeek,
  weeklyAdherence,
} from "@/api/fixtures"
import { formatShortDate } from "@/lib/dates"
import {
  ChartKind,
  type ChartPayload,
  type CopilotMessage,
  type QuickPrompt,
} from "@/types"

/**
 * Retrieval over the member-context graph, canned against the fixture.
 *
 * Every figure below traces to `member-context.json`; nothing is invented, and
 * anything outside the record gets an explicit "I don't have that". When the
 * API lands this module is replaced by real retrieval — the message shape,
 * including the chart payload, does not change.
 */

/**
 * The palette (ASSESSMENT.md:39-42), written as questions rather than labels.
 *
 * Seven two-word chips read as a filter bar, not as things you can ask, and
 * three of them differed only in whether they drew a chart. Folded to four
 * questions a coach would actually say out loud; the charts come back with the
 * answer where a chart is the clearest form, rather than being a separate
 * button. Anything else is still typeable.
 */
export const QUICK_PROMPTS: QuickPrompt[] = [
  { label: "What do I need to know this morning?", prompt: "Show me the brief", is_chart: false },
  { label: "How's her adherence trending?", prompt: "Plot adherence trend", is_chart: true },
  { label: "How has she been sleeping?", prompt: "Plot sleep this week", is_chart: true },
  { label: "What's changed since last week?", prompt: "What changed since last week?", is_chart: false },
]

const injuryStart = member.injuries[0]?.since ?? "an earlier date"
const nightsUnderTarget = sleepNights.filter((h) => h < SLEEP_TARGET_HOURS).length

/** Weekly completion, the churn story as a series. */
function adherenceChart(): ChartPayload {
  return {
    kind: ChartKind.ADHERENCE,
    title: "Weekly completion",
    unit: "%",
    target: 100,
    series: weeklyAdherence.map((week, i) => ({
      label: formatShortDate(week.week_of),
      value: week.pct,
      alert: i === weeklyAdherence.length - 1,
    })),
    caption: `Weekly completion fell from ${weeklyAdherence[0].pct}% to ${weeklyAdherence.at(-1)?.pct}% across ${weeklyAdherence.length} weeks.`,
  }
}

/** Sleep against her stated 7-hour target. */
function sleepChart(): ChartPayload {
  return {
    kind: ChartKind.SLEEP,
    title: "Sleep, last seven nights",
    unit: "h",
    target: SLEEP_TARGET_HOURS,
    series: sleepNights.map((hours, i) => ({
      label: `N${i + 1}`,
      value: hours,
      alert: hours < SLEEP_TARGET_HOURS,
    })),
    caption: `${nightsUnderTarget} of ${sleepNights.length} nights came in under her ${SLEEP_TARGET_HOURS}-hour target, averaging ${oneDp(sleepAvg)}.`,
  }
}

/**
 * Messages per week, member side only.
 *
 * Contact frequency is the churn signal the fixture's `login frequency down`
 * reason gestures at, and it is the one the coach can act on directly.
 */
function messagePatternChart(): ChartPayload {
  const fromMember = memberMessages.filter((m) => m.from === "member")
  const buckets = new Map<string, number>()
  for (const week of weeklyAdherence) buckets.set(week.week_of, 0)

  for (const message of fromMember) {
    const day = message.ts.slice(0, 10)
    // Attribute each message to the adherence week it falls in, so the two
    // charts share an x-axis and can be read against each other.
    const week = [...buckets.keys()].filter((w) => w <= day).sort().at(-1)
    if (week) buckets.set(week, (buckets.get(week) ?? 0) + 1)
  }

  const series = [...buckets.entries()].map(([week, count]) => ({
    label: formatShortDate(week),
    value: count,
    alert: count === 0,
  }))

  return {
    kind: ChartKind.MESSAGE_PATTERN,
    title: "Messages from Jordan, by week",
    unit: "",
    target: null,
    series,
    caption: `${fromMember.length} messages across ${series.length} weeks. Quiet weeks line up with the weeks she trained least.`,
  }
}

/** Sessions completed against sessions planned, four weeks. */
function weeklyComparisonChart(): ChartPayload {
  return {
    kind: ChartKind.WEEKLY_COMPARISON,
    title: "Sessions completed vs. planned",
    unit: " sessions",
    target: trainingDaysPerWeek,
    series: weeklyAdherence.map((week, i) => ({
      label: formatShortDate(week.week_of),
      value: Math.round((week.pct / 100) * trainingDaysPerWeek),
      alert: i === weeklyAdherence.length - 1,
    })),
    caption: `Against a plan of ${trainingDaysPerWeek} a week, she has gone ${weeklyAdherence
      .map((w) => Math.round((w.pct / 100) * trainingDaysPerWeek))
      .join(" → ")}.`,
  }
}

/**
 * The morning brief, already answered when the thread opens.
 *
 * The third paragraph is derived rather than stored: joining her stated
 * session preference to her completed history surfaces a gap nothing in the
 * fixture states outright.
 */
export const openingBrief: CopilotMessage = {
  id: "cp_brief",
  ts: "2026-06-04T07:02:00-07:00",
  from: "copilot",
  paragraphs: [
    {
      lead: "Celebrate first.",
      text: `${firstName} trained Wednesday — 28 minutes, RPE 6, and the first squat work she's called pain-free since the knee flared on ${injuryStart}.`,
    },
    {
      lead: "Then the risk.",
      // The fixture's reason strings carry no terminal punctuation.
      text: `Weekly completion has run ${weeklyAdherence.map((p) => p.pct).join(", ")} across four weeks. ${churnRisk.reasons[1]}. Churn risk is ${churnRisk.level}.`,
    },
    {
      lead: "One thing worth testing.",
      text: `Her sessions average ${member.typical_session_min} minutes against a stated preference of ${preferredSessionMinutes}. Every session she's completed has been short; the one she skipped was full-body. A 30-minute Thursday might get done where a 50-minute one doesn't.`,
    },
  ],
  cites: [
    {
      message_id: "mm_1",
      from: firstName,
      when: "30 May",
      text: "Skipped Thursday, work blew up and I was wiped. Sorry!",
    },
  ],
}

/**
 * Answer a coach's question about this member.
 *
 * @param prompt The question, matched loosely on keywords.
 * @param id Message id for the reply.
 * @returns A grounded answer, or a graceful "I don't have that" for anything
 *   outside the sample member's record.
 */
export function answer(prompt: string, id: string): CopilotMessage {
  const q = prompt.toLowerCase()
  const base = { id, ts: new Date().toISOString(), from: "copilot" as const }
  const wantsChart = /plot|chart|graph|show me the|compare/.test(q)

  if (q.includes("message") || q.includes("contact")) {
    const chart = messagePatternChart()
    return { ...base, paragraphs: [{ text: chart.caption }], chart }
  }

  if (q.includes("compare") || q.includes("4 week") || q.includes("four week")) {
    const chart = weeklyComparisonChart()
    return {
      ...base,
      paragraphs: [
        { text: chart.caption },
        { text: `The skipped week is the one with the full-body session in it — the only full-body session on her record.` },
      ],
      chart,
    }
  }

  if (q.includes("sleep")) {
    const paragraphs = [
      {
        text: `She averaged ${oneDp(sleepAvg)} hours over the last seven nights — ${nightsUnderTarget} of ${sleepNights.length} came in under her ${SLEEP_TARGET_HOURS}-hour target, with a low of ${Math.min(...sleepNights)}.`,
      },
      {
        text: `Nothing in the graph connects sleep to movement selection, so this hasn't changed her plan. It is worth raising with her directly.`,
      },
    ]
    return wantsChart ? { ...base, paragraphs, chart: sleepChart() } : { ...base, paragraphs }
  }

  if (q.includes("adherence") || q.includes("trend")) {
    const paragraphs = [
      {
        text: `Declining for three straight weeks: ${weeklyAdherence.map((p) => `${p.pct}%`).join(" → ")}. That is a 50-point drop from where she started.`,
      },
      {
        text: `The drop begins the week of ${weeklyAdherence[2].week_of}, which is two weeks after the knee flared on ${injuryStart}.`,
      },
    ]
    return wantsChart ? { ...base, paragraphs, chart: adherenceChart() } : { ...base, paragraphs }
  }

  if (q.includes("churn") || q.includes("risk")) {
    return {
      ...base,
      paragraphs: [
        { lead: `Churn risk is ${churnRisk.level}.`, text: churnRisk.reasons.join(". ") + "." },
        {
          text: `The one you can act on today is session length — she completes short sessions and skips long ones.`,
        },
      ],
      chart: adherenceChart(),
    }
  }

  if (q.includes("changed") || q.includes("last week")) {
    return {
      ...base,
      paragraphs: [
        {
          text: `She completed Wednesday's lower-body session at RPE 6 and called the squat work pain-free — the first time since the flare-up. Adherence still fell to ${weeklyAdherence.at(-1)?.pct}% because she trained once against a plan of ${trainingDaysPerWeek}.`,
        },
      ],
      cites: [
        {
          message_id: "mm_3",
          from: firstName,
          when: "3 Jun",
          text: "Knocked out the lower body session! Knee felt okay with the box squats.",
        },
      ],
    }
  }

  if (q.includes("brief")) return { ...openingBrief, id, ts: base.ts }

  return {
    ...base,
    paragraphs: [
      {
        text: `I don't have that for ${firstName}. Her record covers goals, preferences, equipment, injuries, workout history, adherence, biomarkers, labs and your message thread.`,
      },
    ],
  }
}
