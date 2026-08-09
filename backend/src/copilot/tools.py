import time
from datetime import date, timedelta
from typing import Any

from neo4j import Session
from pydantic import BaseModel, ConfigDict

from api import member_queries as mq
from api.churn import ChurnAssessment
from api.members import ADHERENCE_METRIC, LIVE_INJURY_STATUSES, _churn, _reference_date
from copilot import queries as q
from graph.schema import MetricDirection

# The copilot's retrieval surface. Deliberately free of any Anthropic import:
# `agent.py` wraps these as SDK tools, and the keyless path calls the same
# methods directly. One implementation, so what a coach sees without an API key
# is the same data the model would have reasoned over — not a second, thinner
# version of it.

DEFAULT_LOOKBACK_DAYS = 90
"""How far back a windowed read reaches when the caller names no window.

Wide enough to cover this member's whole record, so a model that omits the
argument still sees everything rather than silently getting a slice."""

MAX_ROWS = 50
"""Ceiling on any one result set. The sample is far smaller; this exists so a
tool call cannot become an unbounded scan as the data grows."""


class QueryRecord(BaseModel):
    """One graph read, kept so the trace can show what retrieval actually ran."""

    model_config = ConfigDict(frozen=True)

    name: str
    cypher: str
    params: dict[str, Any]
    rows: int
    duration_ms: float


class GoalProgress(BaseModel):
    """A goal and how it is scored."""

    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    priority: int
    target_date: str | None
    targets: list[str]
    metric_id: str | None
    metric_name: str | None


class MemberSnapshot(BaseModel):
    """Who she is and what she is training toward."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    age: int
    tier: str
    trains_at: str
    member_since: str
    preferred_session_minutes: int
    training_days_per_week: int
    as_of: str
    goals: list[GoalProgress]
    equipment: list[str]
    dislikes: list[str]


class SessionSummary(BaseModel):
    """One session, with the classes of work it actually trained."""

    model_config = ConfigDict(frozen=True)

    date: str
    title: str
    completed: bool
    duration_min: int
    rpe: int | None
    patterns: list[str]
    movements: list[str]
    """What the coach wrote. Not catalog vocabulary — see docs/kg2-schema.md."""


class PatternCount(BaseModel):
    """How often one class of work has been trained in a window."""

    model_config = ConfigDict(frozen=True)

    pattern: str
    sessions: int
    dates: list[str]


class MetricReading(BaseModel):
    """One dated value."""

    model_config = ConfigDict(frozen=True)

    observed_on: str
    value: float
    panel: str | None = None


class MetricSeries(BaseModel):
    """A metric's readings together with the band they are judged against.

    The band travels with the values so no caller has to pair a number with a
    threshold fetched from somewhere else — the mistake that would let an
    answer call a healthy value abnormal.
    """

    model_config = ConfigDict(frozen=True)

    metric_id: str
    name: str
    unit: str
    category: str
    direction: MetricDirection
    optimal_low: float | None
    optimal_high: float | None
    reference: str
    readings: list[MetricReading]

    @property
    def latest(self) -> MetricReading | None:
        """The most recent reading, or None when the series is empty."""
        return self.readings[-1] if self.readings else None

    @property
    def mean(self) -> float | None:
        """Mean of the readings, or None when empty."""
        if not self.readings:
            return None
        return sum(r.value for r in self.readings) / len(self.readings)

    def outside_band(self) -> list[MetricReading]:
        """Readings that fall outside the authored band.

        Always empty for a `TREND` metric: no band exists, so nothing can be
        outside one. Consulting `direction` here is what stops an athletic
        resting heart rate reading as abnormal.
        """
        if self.direction is MetricDirection.TREND:
            return []
        return [
            r
            for r in self.readings
            if (self.optimal_low is not None and r.value < self.optimal_low)
            or (self.optimal_high is not None and r.value > self.optimal_high)
        ]


class MetricSummary(BaseModel):
    """One line of the metric index — what can be asked about, and its latest value."""

    model_config = ConfigDict(frozen=True)

    metric_id: str
    name: str
    unit: str
    category: str
    reading_count: int
    latest_value: float
    latest_on: str


class RetrievedMessage(BaseModel):
    """A message, carrying the id an answer must cite it by."""

    model_config = ConfigDict(frozen=True)

    id: str
    ts: str
    author: str
    text: str
    surface: str | None = None
    """The words that matched, when this message was found by concept."""


class MentionedConcept(BaseModel):
    """A concept her thread names, and how often."""

    model_config = ConfigDict(frozen=True)

    concept: str
    label: str
    mentions: int


class ClinicalRule(BaseModel):
    """One movement pattern a condition rules out or flags."""

    model_config = ConfigDict(frozen=True)

    relation: str
    pattern: str


class InjuryPicture(BaseModel):
    """One injury, its condition, and what that condition rules out."""

    model_config = ConfigDict(frozen=True)

    injury_id: str
    region: str
    status: str
    severity: str
    since: str
    notes: str
    condition: str | None
    rules: list[ClinicalRule]

    @property
    def is_live(self) -> bool:
        """Whether this injury still constrains programming."""
        return self.status in LIVE_INJURY_STATUSES


class Retrieval:
    """One copilot run's access to the member's graph.

    Every read is recorded on `queries`, which is what the trace renders and
    what makes the answer auditable. Message ids returned are accumulated on
    `seen_message_ids`, which is the allowlist citation validation checks
    against — an answer can only cite a message retrieval actually produced.
    """

    def __init__(self, session: Session, member_id: str) -> None:
        self.session = session
        self.member_id = member_id
        self.as_of: date = _reference_date(session, member_id)
        self.queries: list[QueryRecord] = []
        self.seen_message_ids: set[str] = set()

    def _run(self, name: str, cypher: str, **params: Any) -> list[dict[str, Any]]:
        """Execute one named read and record it."""
        started = time.perf_counter()
        rows = [dict(record) for record in self.session.run(cypher, **params)]
        self.queries.append(
            QueryRecord(
                name=name,
                cypher=cypher.strip(),
                params=params,
                rows=len(rows),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        )
        return rows

    def _since(self, days: int | None) -> str:
        """Turn a lookback in days into a date bound, relative to `as_of`.

        Relative to the dataset's own today, never the wall clock — the record
        ends in June 2026, so a real-date window is always empty.
        """
        window = DEFAULT_LOOKBACK_DAYS if days is None else max(1, days)
        return (self.as_of - timedelta(days=window)).isoformat()

    def profile(self) -> MemberSnapshot:
        """Who she is, what she owns, and what she is training toward."""
        rows = self._run("PROFILE", mq.PROFILE, member_id=self.member_id)
        if not rows:
            raise LookupError(f"no member {self.member_id}")
        row = rows[0]

        goals = [
            GoalProgress.model_validate(g)
            for g in self._run("GOALS_WITH_PROGRESS", q.GOALS_WITH_PROGRESS, member_id=self.member_id)
        ]
        equipment = [r["name"] for r in self._run("EQUIPMENT", mq.EQUIPMENT, member_id=self.member_id)]
        dislikes = [r["name"] for r in self._run("DISLIKES", mq.DISLIKES, member_id=self.member_id)]

        return MemberSnapshot(
            id=row["id"],
            name=row["name"],
            age=row["age"],
            tier=row["tier"],
            trains_at=row["trains_at"],
            member_since=row["member_since"],
            preferred_session_minutes=row["preferred_session_minutes"],
            training_days_per_week=row["training_days_per_week"],
            as_of=self.as_of.isoformat(),
            goals=goals,
            equipment=equipment,
            dislikes=dislikes,
        )

    def sessions(self, days: int | None = None, limit: int = 10) -> list[SessionSummary]:
        """Recent sessions, newest first, with the patterns each trained.

        A skipped session comes back with an empty `patterns` list, which is the
        honest reading: nothing was trained.
        """
        rows = self._run(
            "SESSIONS_WITH_PATTERNS",
            q.SESSIONS_WITH_PATTERNS,
            member_id=self.member_id,
            since=self._since(days),
            limit=min(limit, MAX_ROWS),
        )
        return [SessionSummary.model_validate(row) for row in rows]

    def pattern_frequency(self, days: int | None = None) -> list[PatternCount]:
        """How often each class of work has been trained, most-trained first.

        The longitudinal read: repeated work shows up here rather than having to
        be counted out of a session list.
        """
        rows = self._run(
            "PATTERN_FREQUENCY",
            q.PATTERN_FREQUENCY,
            member_id=self.member_id,
            since=self._since(days),
        )
        return [PatternCount.model_validate(row) for row in rows]

    def metric_index(self) -> list[MetricSummary]:
        """Every metric she has readings for. What the copilot may ask about."""
        rows = self._run("METRIC_INDEX", q.METRIC_INDEX, member_id=self.member_id)
        return [MetricSummary.model_validate(row) for row in rows]

    def metric(self, metric_id: str, days: int | None = None) -> MetricSeries | None:
        """One metric's series with its band.

        Args:
            metric_id: An id from `metric_index`.
            days: Lookback window. None reads the default window.

        Returns:
            The series, or None when she has no readings for that metric —
            which is an answer ("I don't have that for her"), not an error.
        """
        rows = self._run(
            "METRIC_SERIES",
            q.METRIC_SERIES,
            member_id=self.member_id,
            metric_id=metric_id,
            since=self._since(days),
        )
        if not rows or not rows[0]["readings"]:
            return None
        return MetricSeries.model_validate(rows[0])

    def adherence(self) -> MetricSeries | None:
        """Weekly completion, the series behind every churn question."""
        return self.metric(ADHERENCE_METRIC, days=365)

    def mentioned_concepts(self) -> list[MentionedConcept]:
        """Concepts her thread names, so a concept search has a real argument."""
        rows = self._run("MENTIONED_CONCEPTS", q.MENTIONED_CONCEPTS, member_id=self.member_id)
        return [MentionedConcept.model_validate(row) for row in rows]

    def messages_about(self, concept: str, limit: int = 10) -> list[RetrievedMessage]:
        """Messages naming a concept, found through the graph rather than by search.

        The `mentions` edge was written at build time by an exact or alias
        match, so a hit is a fact about the text — which is what makes a
        citation drawn from here evidence rather than a keyword coincidence.
        """
        rows = self._run(
            "MESSAGES_BY_CONCEPT",
            q.MESSAGES_BY_CONCEPT,
            member_id=self.member_id,
            concept=concept,
            limit=min(limit, MAX_ROWS),
        )
        return self._as_messages(rows)

    def messages(self, days: int | None = None, limit: int = 20) -> list[RetrievedMessage]:
        """The thread, newest first."""
        rows = self._run(
            "RECENT_MESSAGES",
            q.RECENT_MESSAGES,
            member_id=self.member_id,
            since=f"{self._since(days)}T00:00:00+00:00",
            limit=min(limit, MAX_ROWS),
        )
        return self._as_messages(rows)

    def _as_messages(self, rows: list[dict[str, Any]]) -> list[RetrievedMessage]:
        """Shape message rows and record their ids as citable."""
        messages = [RetrievedMessage.model_validate(row) for row in rows]
        self.seen_message_ids.update(message.id for message in messages)
        return messages

    def clinical_picture(self) -> list[InjuryPicture]:
        """Her injuries and what each one's condition rules out.

        Read from the same `contraindicates` / `cautions` edges the safety
        filter enforces, so an explanation here cannot drift from an exclusion
        there.
        """
        rows = self._run("CLINICAL_PICTURE", q.CLINICAL_PICTURE, member_id=self.member_id)
        return [InjuryPicture.model_validate(row) for row in rows]

    def churn(self) -> ChurnAssessment:
        """Today's churn reading, derived from the record rather than stored.

        Runs its own reads through the shared assessor, so the figure here is
        the same one the member header shows.
        """
        started = time.perf_counter()
        assessment = _churn(self.session, self.member_id)
        self.queries.append(
            QueryRecord(
                name="CHURN_DERIVATION",
                cypher="-- composite: profile, adherence observations, sessions, messages",
                params={"member_id": self.member_id},
                rows=len(assessment.signals),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        )
        return assessment
