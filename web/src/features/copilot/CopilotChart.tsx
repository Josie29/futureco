import { useState } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChartKind, type ChartPayload, type ChartPoint } from "@/types"

/**
 * Charts for the copilot thread (ASSESSMENT.md:42).
 *
 * Every one is a single series, so there is no legend — the title names it.
 * Colour does one job: cobalt is the series, carmine marks a point that is
 * below her target or is the one the answer is about. That is a status, which
 * is the only thing red is allowed to mean anywhere in this console.
 *
 * A value-ramp is deliberately not used: darker-where-bigger would double-
 * encode bar length as hue and burn the only free channel on information the
 * bar already carries.
 */

const AXIS = "var(--color-faint)"
const GRID = "var(--color-soft)"
const SERIES = "var(--color-cobalt)"
const ALERT = "var(--color-red)"

/** Trend over time reads as a line; magnitude per category reads as bars. */
function isTrend(kind: ChartKind): boolean {
  return kind === ChartKind.ADHERENCE
}

function Tip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean
  payload?: { value: number }[]
  label?: string
  unit: string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-[4px] border border-line bg-card px-1.5 py-1 shadow-sm">
      <p className="font-mono text-micro text-dim">
        {label}: <span className="text-ink">{payload[0].value}{unit}</span>
      </p>
    </div>
  )
}

/** The numbers behind the picture. The accessible view, and often the faster one. */
function NumbersTable({ chart }: { chart: ChartPayload }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="text-micro text-faint underline underline-offset-2 hover:text-cobalt"
      >
        {open ? "Hide numbers" : "Show numbers"}
      </button>

      {open && (
        <table className="mt-1 w-full border-collapse text-micro">
          <caption className="sr-only">{chart.caption}</caption>
          <tbody>
            {chart.series.map((point) => (
              <tr key={point.label} className="border-t border-soft">
                <th scope="row" className="py-px text-left font-normal text-dim">
                  {point.label}
                </th>
                <td className="py-px text-right font-mono text-ink">
                  {point.value}
                  {chart.unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function CopilotChart({ chart }: { chart: ChartPayload }) {
  const fillFor = (point: ChartPoint) => (point.alert ? ALERT : SERIES)
  const max = Math.max(...chart.series.map((p) => p.value), chart.target ?? 0)

  return (
    <figure className="mt-1.5 rounded-[4px] border border-line bg-card p-2">
      <figcaption className="mb-1 flex items-baseline gap-2">
        <span className="text-micro font-semibold text-ink">{chart.title}</span>
        {/* The reference line is named here rather than inside the plot, where
            the label landed on whichever bar happened to be tallest. */}
        {chart.target !== null && (
          <span className="ml-auto flex items-center gap-1 text-micro whitespace-nowrap text-faint">
            <i aria-hidden className="inline-block h-px w-3 bg-faint" />
            target {chart.target}
            {chart.unit}
          </span>
        )}
      </figcaption>

      <div className="h-32 w-full" role="img" aria-label={chart.caption}>
        <ResponsiveContainer width="100%" height="100%">
          {isTrend(chart.kind) ? (
            <LineChart data={chart.series} margin={{ top: 6, right: 6, bottom: 0, left: -22 }}>
              <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
              <XAxis
                dataKey="label"
                stroke={AXIS}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 9, fill: AXIS }}
              />
              <YAxis
                stroke={AXIS}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 9, fill: AXIS }}
                domain={[0, Math.ceil(max / 25) * 25]}
              />
              <Tooltip content={<Tip unit={chart.unit} />} cursor={{ stroke: GRID }} />
              {chart.target !== null && (
                <ReferenceLine y={chart.target} stroke={AXIS} strokeWidth={1} />
              )}
              <Line
                type="monotone"
                dataKey="value"
                stroke={SERIES}
                strokeWidth={2}
                dot={({ cx, cy, index }) => (
                  <circle
                    key={index}
                    cx={cx}
                    cy={cy}
                    r={4}
                    fill={fillFor(chart.series[index])}
                    stroke="var(--color-card)"
                    strokeWidth={2}
                  />
                )}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          ) : (
            <BarChart data={chart.series} margin={{ top: 6, right: 6, bottom: 0, left: -22 }} barCategoryGap="22%">
              <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
              <XAxis
                dataKey="label"
                stroke={AXIS}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 9, fill: AXIS }}
              />
              <YAxis
                stroke={AXIS}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 9, fill: AXIS }}
                allowDecimals={false}
              />
              <Tooltip content={<Tip unit={chart.unit} />} cursor={{ fill: "var(--color-ground)" }} />
              {chart.target !== null && (
                <ReferenceLine y={chart.target} stroke={AXIS} strokeWidth={1} />
              )}
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {chart.series.map((point) => (
                  <Cell key={point.label} fill={fillFor(point)} />
                ))}
              </Bar>
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>

      <NumbersTable chart={chart} />
    </figure>
  )
}
