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


# Agentic migration: `build_generator_trace`, its stage-kind map and the
# query-folding helper went with the deterministic pipeline. The rebuilt
# generator emits spans from instrumented tool calls instead of a hand-kept
# stage list; its trace builder lands with the planning agent. `RunTrace` and
# the stores are shared with the copilot and unchanged.


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
