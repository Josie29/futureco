from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ChartKind(StrEnum):
    """Which chart a payload is. Mirrors the TypeScript enum.

    `METRIC` is the general case, and it exists because the observation model
    makes it free: every biomarker, lab value and body-composition reading is
    the same shape, so plotting one is the same code as plotting another. The
    four named kinds stay because each carries its own framing — adherence is
    read against her plan, sleep against her goal, message pattern against the
    adherence weeks — which a generic series cannot express.
    """

    ADHERENCE = "adherence"
    SLEEP = "sleep"
    MESSAGE_PATTERN = "message_pattern"
    WEEKLY_COMPARISON = "weekly_comparison"
    METRIC = "metric"


class ChartPoint(BaseModel):
    """One plotted value."""

    model_config = ConfigDict(frozen=True)

    label: str
    value: float
    alert: bool = False
    """Marks a point the answer is about — below target, outside its band."""


class ChartPayload(BaseModel):
    """A chart, assembled server-side from retrieval.

    The model never emits a data point. It chooses whether a chart helps and
    which retrieved series to feature; the numbers come from the graph through
    `charts.py`. That is the difference between a chart that illustrates the
    record and one that illustrates a sentence.
    """

    model_config = ConfigDict(frozen=True)

    kind: ChartKind
    title: str
    unit: str
    target: float | None
    series: list[ChartPoint]
    caption: str
    """One sentence naming what the chart shows. Read by screen readers, and
    the accessible equivalent of the plot itself."""


class Citation(BaseModel):
    """A member message quoted as the evidence for a claim.

    Validated before it reaches a coach: `citations.py` drops any id retrieval
    did not actually return this run.
    """

    model_config = ConfigDict(frozen=True)

    message_id: str
    author: str = Field(serialization_alias="from")
    when: str
    text: str


class Paragraph(BaseModel):
    """One paragraph of an answer, with an optional bolded lead-in."""

    model_config = ConfigDict(frozen=True)

    lead: str | None = None
    text: str


class CopilotAnswer(BaseModel):
    """One copilot turn, in the shape the console renders.

    Mirrors `CopilotMessage` in `web/src/types/index.ts`. `author` goes over the
    wire as `from`, matching the console's own key.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    ts: str
    author: str = Field(default="copilot", serialization_alias="from")
    paragraphs: list[Paragraph]
    cites: list[Citation] = []
    chart: ChartPayload | None = None

    degraded: str | None = None
    """Why this answer is less than a full one, or None when it is complete.

    Set when synthesis is unavailable, when a citation was dropped, or when a
    tool failed mid-run. Rendered as a banner, so a coach is never handed a
    partial answer that looks whole. Corresponds to `SpanStatus.DEGRADED` on
    the run's trace.
    """


def short_date(value: date | str) -> str:
    """Format a date the way the console does — "30 May".

    Args:
        value: A date, or an ISO `YYYY-MM-DD` string.

    Returns:
        Day and abbreviated month, with no leading zero.
    """
    parsed = date.fromisoformat(value) if isinstance(value, str) else value
    return f"{parsed.day} {parsed:%b}"


def when(ts: str) -> str:
    """Format a message timestamp for a citation line."""
    return short_date(datetime.fromisoformat(ts).date())
