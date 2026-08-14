import itertools
from collections import deque
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from copilot.agent import MODEL, RunResult
from copilot.tools import QueryRecord

# Observability over the agentic runtime (ASSESSMENT.md:134).
#
# This is the storage half only. `tech-stack.md` chose a local Postgres table
# for durability, and the generator is the bigger span producer, so it should
# shape that schema — see docs/decisions.md, *Copilot* 8. What lands here is the
# interface plus an in-memory implementation, because a multi-tool agent
# against a five-second budget is undebuggable without one. Swapping the
# implementation is a change to this file.


class SpanKind(StrEnum):
    """What kind of work a span did. Mirrors the TypeScript enum."""

    AGENT = "agent"
    RESOLVE = "resolve"
    GRAPH = "graph"
    LLM = "llm"
    TOOL = "tool"


class SpanStatus(StrEnum):
    """How a span or run ended."""

    OK = "ok"
    DEGRADED = "degraded"
    """Completed, but something was declined or fell back. A run that quietly
    failed to act on part of the request must not look identical to a clean
    one."""

    ERROR = "error"


class SpanAttribute(BaseModel):
    """One key/value line in a span's detail panel."""

    model_config = ConfigDict(frozen=True)

    label: str
    value: str


class TraceSpan(BaseModel):
    """One unit of work inside a run."""

    model_config = ConfigDict(frozen=True)

    id: str
    parent_id: str | None
    kind: SpanKind
    name: str
    started_ms: float
    """Offset from the run's start, so a waterfall lays out without parsing
    timestamps."""

    duration_ms: float
    status: SpanStatus
    attributes: list[SpanAttribute] = []

    query: str | None = None
    """Cypher, for a `GRAPH` span, rendered verbatim. The one surface in this
    system written for an engineer rather than a coach."""

    rows_returned: int | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    note: str | None = None
    """The one-line reason a span is degraded or errored."""


class RunTotals(BaseModel):
    """What a run cost."""

    model_config = ConfigDict(frozen=True)

    graph_queries: int
    llm_calls: int
    tokens_in: int
    tokens_out: int


class RunTrace(BaseModel):
    """One end-to-end request."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    source: str
    prompt: str
    started_at: str
    duration_ms: float
    status: SpanStatus
    totals: RunTotals
    spans: list[TraceSpan]


class RunTraceSummary(BaseModel):
    """List-view row. The detail endpoint returns the full `RunTrace`."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    source: str
    prompt: str
    started_at: str
    duration_ms: float
    status: SpanStatus
    totals: RunTotals


class TraceStore(Protocol):
    """Where runs are kept. Append-only; a trace is never edited after the fact."""

    def record(self, trace: RunTrace) -> None: ...

    def list(self) -> list[RunTraceSummary]: ...

    def get(self, run_id: str) -> RunTrace | None: ...


class InMemoryTraceStore:
    """A bounded ring of recent runs.

    Traces do not survive a restart, which is exactly the criticism
    `tech-stack.md` levels at the rejected Jaeger option — so this is staged,
    not chosen. It is bounded because an unbounded store inside a long-running
    API is a memory leak with a nice name.
    """

    def __init__(self, capacity: int = 200) -> None:
        self._runs: deque[RunTrace] = deque(maxlen=capacity)

    def record(self, trace: RunTrace) -> None:
        self._runs.append(trace)

    def list(self) -> list[RunTraceSummary]:
        """Newest first."""
        return [
            RunTraceSummary(**run.model_dump(exclude={"spans"}))
            for run in reversed(self._runs)
        ]

    def get(self, run_id: str) -> RunTrace | None:
        return next((run for run in self._runs if run.run_id == run_id), None)


from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
)

from agents.workout_generator.agent import Usage
from agents.workout_generator.deps import ProvenanceEvent, ProvenanceKind
from catalog.queries import CANDIDATES
from member.queries import GOALS, PATTERN_HISTORY, STANDING
from safety.queries import CLINICAL_RULES

# The generator trace is self-instrumented rather than OTel-exported.
# pydantic-ai's Instrumentation capability was considered and rejected: the
# venv carries opentelemetry-api only, under which every span is a
# non-recording no-op, so adopting it means adding opentelemetry-sdk plus an
# exporter mapping gen_ai attributes onto this store — a dependency spent
# duplicating what the run already records. LLM-turn spans come from message
# timestamps, tool spans from the toolset's timing wrapper.

_EVENT_KINDS: dict[ProvenanceKind, SpanKind] = {
    ProvenanceKind.CONCEPT_RESOLUTION: SpanKind.RESOLVE,
    ProvenanceKind.MEMBER_SNAPSHOT: SpanKind.GRAPH,
    ProvenanceKind.CANDIDATE_RETRIEVAL: SpanKind.GRAPH,
    ProvenanceKind.CLINICAL_ENVELOPE: SpanKind.GRAPH,
    ProvenanceKind.CONSTRAINT_DECLARATION: SpanKind.TOOL,
}

_EVENT_QUERIES: dict[ProvenanceKind, tuple[tuple[str, str], ...]] = {
    ProvenanceKind.MEMBER_SNAPSHOT: (
        ("member.standing", STANDING),
        ("member.goals", GOALS),
        ("member.pattern_history", PATTERN_HISTORY),
    ),
    ProvenanceKind.CANDIDATE_RETRIEVAL: (("catalog.candidates", CANDIDATES),),
    ProvenanceKind.CLINICAL_ENVELOPE: (("safety.clinical_rules", CLINICAL_RULES),),
}
"""The Cypher each event kind runs. Resolution and declaration read no graph.
`totals.graph_queries` counts these, so the validators' own re-derivation
reads are not counted — the trace shows the agent's queries, not the checker's."""

_NOTE_LIMIT = 200
"""Cap on a degraded note. Retry feedback can run to paragraphs; the note is
the headline and the span attributes carry the counts."""


def _event_attributes(event: ProvenanceEvent) -> list[SpanAttribute]:
    pairs: list[tuple[str, str]] = []
    if event.query:
        pairs.append(("query", event.query))
    if event.concept:
        pairs.append(("concept", event.concept))
    if event.candidates:
        pairs.append(("eligible", str(len(event.candidates))))
    if event.exclusions:
        pairs.append(("excluded", str(len(event.exclusions))))
    if event.constraint_set:
        pairs.append(("constraints", str(len(event.constraint_set.constraints))))
    if event.rejected_targets:
        pairs.append(("rejected", str(len(event.rejected_targets))))
    return [SpanAttribute(label=label, value=value) for label, value in pairs]


def _event_status(event: ProvenanceEvent) -> tuple[SpanStatus, str | None]:
    """A tool span degrades when the run quietly acted on less than asked."""
    if event.rejected_targets:
        note = f"declaration rejected: {', '.join(event.rejected_targets)}"
        return SpanStatus.DEGRADED, note[:_NOTE_LIMIT]
    if event.unmatched_requires:
        note = f"no eligible exercise satisfies: {', '.join(event.unmatched_requires)}"
        return SpanStatus.DEGRADED, note[:_NOTE_LIMIT]
    return SpanStatus.OK, None


def _event_query(event: ProvenanceEvent) -> str | None:
    """The Cypher behind one event, comment-headed when there are several."""
    queries = _EVENT_QUERIES.get(event.kind, ())
    if not queries:
        return None
    return "\n\n".join(f"// {name}\n{cypher.strip()}" for name, cypher in queries)


def _event_rows(event: ProvenanceEvent) -> int | None:
    if event.kind is ProvenanceKind.CANDIDATE_RETRIEVAL:
        return len(event.candidates) + len({x.concept_id for x in event.exclusions})
    if event.kind is ProvenanceKind.CLINICAL_ENVELOPE and event.constraint_set:
        return len(event.constraint_set.constraints)
    return None


def _llm_turns(
    messages: list[ModelMessage], run_start: datetime
) -> list[dict]:
    """One span body per request→response pair, timed from message stamps.

    A request carrying a RetryPromptPart is a validator or tool rejection
    being taught back to the model, so its turn is marked degraded with the
    feedback as the note. A request with no timestamp — history revived from
    a store — falls back to the preceding response's stamp, then to zero.
    """
    turns: list[dict] = []
    last_seen: datetime | None = None
    for i, message in enumerate(messages):
        if not isinstance(message, ModelRequest):
            continue
        response = messages[i + 1] if i + 1 < len(messages) else None
        if not isinstance(response, ModelResponse):
            continue
        request_ts = message.timestamp or last_seen
        last_seen = response.timestamp
        started_ms = (
            max((request_ts - run_start).total_seconds() * 1000, 0.0)
            if request_ts
            else 0.0
        )
        duration_ms = (
            max((response.timestamp - request_ts).total_seconds() * 1000, 0.0)
            if request_ts
            else 0.0
        )
        retry = next(
            (p for p in message.parts if isinstance(p, RetryPromptPart)), None
        )
        turns.append(
            {
                "kind": SpanKind.LLM,
                "name": f"chat · turn {len(turns) + 1}",
                "started_ms": round(started_ms, 2),
                "duration_ms": round(duration_ms, 2),
                "status": SpanStatus.DEGRADED if retry else SpanStatus.OK,
                "note": str(retry.content)[:_NOTE_LIMIT] if retry else None,
                "model": response.model_name or "model",
                "tokens_in": response.usage.input_tokens or 0,
                "tokens_out": response.usage.output_tokens or 0,
                "attributes": [],
            }
        )
    return turns


def build_generator_trace(
    run_id: str,
    prompt: str,
    started_at: datetime,
    duration_ms: float,
    tool_log: list[ProvenanceEvent],
    messages: list[ModelMessage],
    usage: Usage,
) -> RunTrace:
    """Turn one generation into a trace.

    One root span with the wall time; one child per LLM turn, timed from the
    message stamps and carrying that turn's tokens; one child per provenance
    event, timed by the toolset wrapper and carrying the Cypher it ran.
    Children interleave by start offset, so the waterfall reads as the run
    actually unfolded.

    Args:
        run_id: Identifier for the run.
        prompt: What the coach asked.
        started_at: When the run began, wall clock.
        duration_ms: End-to-end wall time.
        tool_log: The run's provenance events, in order.
        messages: This run's messages only — an adjustment passes its new
            messages, not the replayed parent history.
        usage: What the whole run cost.

    Returns:
        The assembled trace, degraded when any part of the request was
        quietly declined, unsatisfiable, or retried.
    """
    children = _llm_turns(messages, started_at)
    for event in tool_log:
        status, note = _event_status(event)
        children.append(
            {
                "kind": _EVENT_KINDS[event.kind],
                "name": event.kind.value,
                "started_ms": event.started_ms,
                "duration_ms": event.duration_ms,
                "status": status,
                "note": note,
                "query": _event_query(event),
                "rows_returned": _event_rows(event),
                "attributes": _event_attributes(event),
            }
        )
    children.sort(key=lambda body: body["started_ms"])

    degraded = [body for body in children if body["status"] is SpanStatus.DEGRADED]
    status = SpanStatus.DEGRADED if degraded else SpanStatus.OK

    ids = (f"sp_{n}" for n in itertools.count(1))
    root_id = next(ids)
    spans = [
        TraceSpan(
            id=root_id,
            parent_id=None,
            kind=SpanKind.AGENT,
            name="plan.generate",
            started_ms=0.0,
            duration_ms=round(duration_ms, 2),
            status=status,
            attributes=[
                SpanAttribute(label="llm turns", value=str(usage.llm_calls)),
                SpanAttribute(label="tool events", value=str(len(tool_log))),
            ],
            note=degraded[0]["note"] if degraded else None,
        )
    ]
    spans.extend(
        TraceSpan(id=next(ids), parent_id=root_id, **body) for body in children
    )
    return RunTrace(
        run_id=run_id,
        source="generator",
        prompt=prompt,
        started_at=started_at.astimezone(UTC).isoformat(),
        duration_ms=round(duration_ms, 2),
        status=status,
        totals=RunTotals(
            graph_queries=sum(
                len(_EVENT_QUERIES.get(event.kind, ())) for event in tool_log
            ),
            llm_calls=usage.llm_calls,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
        ),
        spans=spans,
    )


def build_copilot_trace(
    run_id: str,
    prompt: str,
    started_at: datetime,
    duration_ms: float,
    queries: list[QueryRecord],
    result: RunResult,
) -> RunTrace:
    """Turn one copilot run into a trace.

    Graph spans are laid out sequentially from their recorded durations rather
    than from wall-clock stamps. The reads genuinely run in sequence, so the
    ordering is real; the offsets are reconstructed, which is why they add up
    exactly to the query time rather than to the run time.

    Args:
        run_id: Identifier for the run.
        prompt: What the coach asked.
        started_at: When the run began.
        duration_ms: End-to-end wall time.
        queries: Every graph read the run made, in order.
        result: The answer and its model cost.

    Returns:
        The assembled trace, degraded when the answer was.
    """
    ids = (f"sp_{n}" for n in itertools.count(1))
    root_id = next(ids)
    status = SpanStatus.DEGRADED if result.answer.degraded else SpanStatus.OK

    spans = [
        TraceSpan(
            id=root_id,
            parent_id=None,
            kind=SpanKind.AGENT,
            name="copilot.answer",
            started_ms=0.0,
            duration_ms=duration_ms,
            status=status,
            attributes=[
                SpanAttribute(label="path", value="model" if result.used_model else "retrieval only"),
                SpanAttribute(label="paragraphs", value=str(len(result.answer.paragraphs))),
                SpanAttribute(label="citations", value=str(len(result.answer.cites))),
                SpanAttribute(
                    label="chart",
                    value=result.answer.chart.kind.value if result.answer.chart else "none",
                ),
            ],
            note=result.answer.degraded,
        )
    ]

    offset = 0.0
    for record in queries:
        spans.append(
            TraceSpan(
                id=next(ids),
                parent_id=root_id,
                kind=SpanKind.GRAPH,
                name=record.name,
                started_ms=round(offset, 2),
                duration_ms=record.duration_ms,
                status=SpanStatus.OK,
                attributes=[
                    SpanAttribute(label=key, value=str(value))
                    for key, value in record.params.items()
                ],
                query=record.cypher,
                rows_returned=record.rows,
            )
        )
        offset += record.duration_ms

    if result.used_model:
        spans.append(
            TraceSpan(
                id=next(ids),
                parent_id=root_id,
                kind=SpanKind.LLM,
                name="tool_runner",
                started_ms=0.0,
                duration_ms=round(max(duration_ms - offset, 0.0), 2),
                status=status,
                attributes=[SpanAttribute(label="turns", value=str(result.llm_calls))],
                model=MODEL,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
            )
        )

    return RunTrace(
        run_id=run_id,
        source="copilot",
        prompt=prompt,
        started_at=started_at.astimezone(UTC).isoformat(),
        duration_ms=round(duration_ms, 2),
        status=status,
        totals=RunTotals(
            graph_queries=len(queries),
            llm_calls=result.llm_calls,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
        ),
        spans=spans,
    )
