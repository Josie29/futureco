from collections import Counter
from datetime import datetime

from copilot.answer import ChartKind, ChartPayload, ChartPoint, short_date
from copilot.tools import MetricSeries, RetrievedMessage
from graph.schema import MetricDirection

# Charts are built here, from retrieved series, and never by the model. It
# picks which chart helps; the numbers come from the graph. A model that could
# emit data points could emit a plausible trend that never happened, and a
# chart is the most credible thing on the page.


def _points(series: MetricSeries, label: str = "date") -> list[ChartPoint]:
    """Turn readings into points, flagging those outside the metric's band.

    `label` selects the x-axis form: dated for a real time series, ordinal for a
    run of nights where the dates were reconstructed rather than recorded.
    """
    breached = {r.observed_on for r in series.outside_band()}
    return [
        ChartPoint(
            label=short_date(r.observed_on) if label == "date" else f"N{i + 1}",
            value=r.value,
            alert=r.observed_on in breached,
        )
        for i, r in enumerate(series.readings)
    ]


def _band_caption(series: MetricSeries) -> str:
    """One sentence about how the series sits against its band."""
    outside = series.outside_band()
    if series.direction is MetricDirection.TREND:
        first, last = series.readings[0], series.readings[-1]
        direction = "up" if last.value > first.value else "down" if last.value < first.value else "flat"
        return (
            f"{series.name} has gone {direction}, {first.value:g} to {last.value:g} "
            f"{series.unit}, across {len(series.readings)} readings."
        )
    if not outside:
        return (
            f"All {len(series.readings)} {series.name.lower()} readings sit inside "
            f"the reference band."
        )
    return (
        f"{len(outside)} of {len(series.readings)} {series.name.lower()} readings "
        f"fall outside the reference band."
    )


def metric_chart(series: MetricSeries) -> ChartPayload:
    """Plot any metric against its own band.

    The general case, and the payoff for reifying observations: sleep, weight,
    HRV and every lab value reach this one function.
    """
    target = series.optimal_low if series.optimal_low is not None else series.optimal_high
    return ChartPayload(
        kind=ChartKind.METRIC,
        title=series.name,
        unit=series.unit,
        target=target,
        series=_points(series),
        caption=_band_caption(series),
    )


def sleep_chart(series: MetricSeries) -> ChartPayload:
    """Sleep against her stated target.

    Its own kind rather than a plain metric chart because the band comes from
    her goal, not from a population range — the caption says "her target", and
    that claim is only true for this metric.
    """
    under = series.outside_band()
    mean = series.mean or 0.0
    return ChartPayload(
        kind=ChartKind.SLEEP,
        title=f"Sleep, last {len(series.readings)} nights",
        unit=series.unit,
        target=series.optimal_low,
        # Ordinal labels: the source list carries no dates, so these were
        # reconstructed at build time. Printing them as calendar dates would
        # imply a precision the data does not have.
        series=_points(series, label="ordinal"),
        caption=(
            f"{len(under)} of {len(series.readings)} nights came in under her "
            f"{series.optimal_low:g}-hour target, averaging {mean:.1f}."
        ),
    )


def adherence_chart(series: MetricSeries) -> ChartPayload:
    """Weekly completion — the churn story as a series."""
    points = _points(series)
    first, last = series.readings[0].value, series.readings[-1].value
    return ChartPayload(
        kind=ChartKind.ADHERENCE,
        title="Weekly completion",
        unit=series.unit,
        target=series.optimal_low,
        series=points,
        caption=(
            f"Weekly completion went from {first:g}% to {last:g}% across "
            f"{len(points)} weeks."
        ),
    )


def weekly_comparison_chart(series: MetricSeries, planned_per_week: int) -> ChartPayload:
    """Sessions completed against sessions planned.

    The same underlying series as adherence, converted from a percentage into
    the unit a coach schedules in. Kept separate because "two sessions, not
    four" is a different sentence from "50%", and it is the one that leads to an
    action.
    """
    done = [round(r.value / 100 * planned_per_week) for r in series.readings]
    return ChartPayload(
        kind=ChartKind.WEEKLY_COMPARISON,
        title="Sessions completed vs. planned",
        unit=" sessions",
        target=float(planned_per_week),
        series=[
            ChartPoint(
                label=short_date(r.observed_on),
                value=float(count),
                alert=count < planned_per_week,
            )
            for r, count in zip(series.readings, done, strict=True)
        ],
        caption=(
            f"Against a plan of {planned_per_week} a week, she has gone "
            f"{' → '.join(str(n) for n in done)}."
        ),
    )


def message_pattern_chart(
    messages: list[RetrievedMessage], adherence: MetricSeries
) -> ChartPayload:
    """Messages from the member per adherence week.

    Bucketed onto the adherence weeks rather than onto calendar weeks, so the
    two charts share an x-axis and can be read against each other. Coach
    messages are excluded: a coach writing into silence is not contact, and
    counting it would hide exactly the pattern this chart exists to show.
    """
    weeks = [r.observed_on for r in adherence.readings]
    counts: Counter[str] = Counter()
    for message in messages:
        if message.author != "member":
            continue
        day = datetime.fromisoformat(message.ts).date().isoformat()
        landed = [week for week in weeks if week <= day]
        if landed:
            counts[max(landed)] += 1

    from_member = sum(counts.values())
    return ChartPayload(
        kind=ChartKind.MESSAGE_PATTERN,
        title="Messages from her, by week",
        unit="",
        target=None,
        series=[
            ChartPoint(label=short_date(week), value=float(counts[week]), alert=counts[week] == 0)
            for week in weeks
        ],
        caption=(
            f"{from_member} messages across {len(weeks)} weeks. Quiet weeks line up "
            f"with the weeks she trained least."
        ),
    )
