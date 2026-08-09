from enum import StrEnum

from copilot import charts
from copilot.answer import ChartPayload, Paragraph, short_date
from copilot.citations import validate
from copilot.tools import MetricSeries, Retrieval

# The answer path that runs with no API key.
#
# It is not a smaller copilot. It runs the *same* retrieval the model would and
# renders what came back — so a reviewer on a cold clone sees the real graph,
# not a stub. What it does not do is draw conclusions: every sentence here is a
# figure the graph returned, composed by a fixed template. Reading a decline as
# a churn signal, or a quiet week as disengagement, is inference, and inference
# is the model's job. Keeping that line sharp is what makes the banner honest —
# "retrieval only" means facts without interpretation, not a thinner opinion.

NO_KEY_BANNER = (
    "No ANTHROPIC_API_KEY is set, so this is retrieval only: the figures below "
    "come from her graph, but nothing here interprets them."
)


class Intent(StrEnum):
    """What a question is asking for, decided by keyword.

    Deliberately crude, and named so nobody mistakes it for understanding: with
    a key, the model chooses tools by reading the question. This is the floor
    that keeps the console working without one.
    """

    BRIEF = "brief"
    CHURN = "churn"
    ADHERENCE = "adherence"
    SLEEP = "sleep"
    METRIC = "metric"
    MESSAGES = "messages"
    SESSIONS = "sessions"
    CONSTRAINTS = "constraints"
    CHANGED = "changed"
    UNKNOWN = "unknown"


_KEYWORDS: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.BRIEF, ("brief", "morning", "need to know")),
    (Intent.CHURN, ("churn", "risk", "at risk", "leaving")),
    (Intent.CHANGED, ("changed", "since last", "this week vs")),
    (Intent.MESSAGES, ("message", "contact", "wrote", "said", "told")),
    (Intent.CONSTRAINTS, ("injur", "knee", "safe", "avoid", "rule out", "can't", "cannot")),
    (Intent.SESSIONS, ("session", "workout", "train", "done", "history")),
    (Intent.ADHERENCE, ("adherence", "completion", "consisten")),
    (Intent.SLEEP, ("sleep", "rest", "slept")),
]

SLEEP_METRIC = "sleep_hours"
ADHERENCE_METRIC = "weekly_adherence"


def route(question: str, metric_names: dict[str, str]) -> tuple[Intent, str | None]:
    """Decide what to retrieve.

    Metrics are matched first and from the index rather than a hardcoded list,
    so every metric she has readings for is reachable — asking about ferritin
    works without anyone having written the word "ferritin" here.

    Args:
        question: What the coach typed.
        metric_names: Metric id to display name, from `Retrieval.metric_index`.

    Returns:
        The intent, and a metric id when one was named.
    """
    text = question.lower()

    for metric_id, name in metric_names.items():
        if metric_id.replace("_", " ") in text or name.lower() in text:
            if metric_id == SLEEP_METRIC:
                return Intent.SLEEP, metric_id
            if metric_id == ADHERENCE_METRIC:
                return Intent.ADHERENCE, metric_id
            return Intent.METRIC, metric_id

    # A keyword intent that is *about* a metric still needs that metric's id.
    # "How's her adherence trending?" names neither `weekly_adherence` nor
    # "Weekly completion", so it never matches above — without this it routed
    # to the adherence branch with no series and answered "no readings", which
    # is a worse failure than not matching at all.
    implied = {Intent.ADHERENCE: ADHERENCE_METRIC, Intent.SLEEP: SLEEP_METRIC}
    for intent, needles in _KEYWORDS:
        if any(needle in text for needle in needles):
            return intent, implied.get(intent)

    return Intent.UNKNOWN, None


def _series_sentence(series: MetricSeries) -> str:
    """List a series' values and say how they sit against the band."""
    values = ", ".join(f"{r.value:g}" for r in series.readings)
    outside = series.outside_band()
    band = (
        "no reference band is defined for it"
        if series.optimal_low is None and series.optimal_high is None
        else f"{len(outside)} of {len(series.readings)} fall outside the reference band"
    )
    return f"{series.name} ({series.unit}): {values}. {band.capitalize()}."


def render(retrieval: Retrieval, question: str, answer_id: str, ts: str) -> dict:
    """Retrieve for a question and render what came back.

    Args:
        retrieval: The run's graph access.
        question: What the coach typed.
        answer_id: Id for the produced turn.
        ts: Timestamp for the produced turn.

    Returns:
        Keyword arguments for a `CopilotAnswer` — paragraphs, cites, chart, and
        the degraded banner, which is always set because an answer with no
        interpretation is by definition less than a full one.
    """
    index = {m.metric_id: m.name for m in retrieval.metric_index()}
    intent, metric_id = route(question, index)

    paragraphs: list[Paragraph] = []
    chart: ChartPayload | None = None
    cites = []

    if intent in (Intent.BRIEF, Intent.CHURN):
        assessment = retrieval.churn()
        paragraphs.append(
            Paragraph(
                lead=f"Churn risk: {assessment.level.value}.",
                text=(
                    f"{len(assessment.signals)} signal"
                    f"{'s' if len(assessment.signals) != 1 else ''} fired. "
                    + " ".join(f"{s.reason}." for s in assessment.signals)
                ),
            )
        )
        adherence = retrieval.adherence()
        if adherence:
            chart = charts.adherence_chart(adherence)
        if intent is Intent.BRIEF:
            done = [s for s in retrieval.sessions(days=14) if s.completed]
            if done:
                latest = done[0]
                paragraphs.append(
                    Paragraph(
                        lead="Most recent session.",
                        text=(
                            f"{latest.title} on {short_date(latest.date)} — "
                            f"{latest.duration_min} minutes, RPE {latest.rpe}, "
                            f"training {', '.join(latest.patterns)}."
                        ),
                    )
                )

    elif intent in (Intent.SLEEP, Intent.METRIC, Intent.ADHERENCE):
        series = retrieval.metric(metric_id, days=365) if metric_id else None
        if series is None:
            paragraphs.append(
                Paragraph(text=f"No readings on record for that metric.")
            )
        else:
            paragraphs.append(Paragraph(lead="From her record.", text=_series_sentence(series)))
            paragraphs.append(Paragraph(lead="Reference.", text=series.reference))
            chart = (
                charts.sleep_chart(series)
                if intent is Intent.SLEEP
                else charts.adherence_chart(series)
                if intent is Intent.ADHERENCE
                else charts.metric_chart(series)
            )

    elif intent is Intent.MESSAGES:
        messages = retrieval.messages(days=365)
        adherence = retrieval.adherence()
        if adherence:
            chart = charts.message_pattern_chart(messages, adherence)
        concepts = retrieval.mentioned_concepts()
        if concepts:
            paragraphs.append(
                Paragraph(
                    lead="What her messages name.",
                    text=", ".join(f"{c.concept} ({c.mentions})" for c in concepts) + ".",
                )
            )
        cites = validate(
            [m.id for m in messages[:2]], messages, retrieval.profile().name
        ).citations

    elif intent is Intent.SESSIONS:
        sessions = retrieval.sessions(days=60)
        for entry in sessions[:4]:
            paragraphs.append(
                Paragraph(
                    lead=f"{short_date(entry.date)} — {entry.title}.",
                    text=(
                        f"{entry.duration_min} minutes, RPE {entry.rpe}, "
                        f"training {', '.join(entry.patterns)}."
                        if entry.completed
                        else "Planned and not completed, so nothing was trained."
                    ),
                )
            )
        frequency = retrieval.pattern_frequency(days=14)
        if frequency:
            paragraphs.append(
                Paragraph(
                    lead="Patterns trained, last 14 days.",
                    text=", ".join(f"{p.pattern} ×{p.sessions}" for p in frequency) + ".",
                )
            )

    elif intent is Intent.CONSTRAINTS:
        for injury in retrieval.clinical_picture():
            barred = [r.pattern for r in injury.rules if r.relation == "contraindicates"]
            flagged = [r.pattern for r in injury.rules if r.relation == "cautions"]
            paragraphs.append(
                Paragraph(
                    lead=f"{injury.region.capitalize()} — {injury.status}, {injury.severity}.",
                    text=(
                        f"Diagnosed as {injury.condition}, since {short_date(injury.since)}. "
                        f"Rules out: {', '.join(barred) or 'nothing'}. "
                        f"Flags: {', '.join(flagged) or 'nothing'}."
                    ),
                )
            )

    elif intent is Intent.CHANGED:
        adherence = retrieval.adherence()
        if adherence and len(adherence.readings) >= 2:
            first, last = adherence.readings[0], adherence.readings[-1]
            paragraphs.append(
                Paragraph(
                    lead="Weekly completion.",
                    text=(
                        f"{first.value:g}% in the week of {short_date(first.observed_on)}, "
                        f"{last.value:g}% in the week of {short_date(last.observed_on)}."
                    ),
                )
            )
            chart = charts.adherence_chart(adherence)
        recent = retrieval.sessions(days=14)
        if recent:
            paragraphs.append(
                Paragraph(
                    lead="Sessions in the last 14 days.",
                    text=", ".join(
                        f"{short_date(s.date)} {s.title}"
                        f"{'' if s.completed else ' (skipped)'}"
                        for s in recent
                    )
                    + ".",
                )
            )

    if not paragraphs:
        covered = ", ".join(sorted({m.category for m in retrieval.metric_index()}))
        paragraphs.append(
            Paragraph(
                lead="Nothing matched that question.",
                text=(
                    f"Her record covers goals, equipment, injuries, session history, "
                    f"her message thread, and measurements across {covered}. "
                    f"Ask about any of those, or set an API key for a real answer."
                ),
            )
        )

    return {
        "id": answer_id,
        "ts": ts,
        "paragraphs": paragraphs,
        "cites": cites,
        "chart": chart,
        "degraded": NO_KEY_BANNER,
    }
