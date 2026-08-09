import itertools
from collections import deque
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from agent.extract import Extraction
from copilot.agent import MODEL, RunResult
from copilot.tools import QueryRecord
from graph.recording import QueryRecord as GeneratorQuery
from graph.recording import RunRecorder
from plan.pipeline import GeneratedPlan

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


# What each pipeline stage is doing, for the waterfall's labels. Kinds are
# coarse on purpose: `SpanKind` has five members because those are the five
# things worth telling apart when a run is slow or wrong.
STAGE_KINDS: dict[str, SpanKind] = {
    "load_standing": SpanKind.GRAPH,
    "resolve_directives": SpanKind.RESOLVE,
    "compose": SpanKind.TOOL,
    "filter": SpanKind.GRAPH,
    "movement_facts": SpanKind.GRAPH,
    "substitute": SpanKind.GRAPH,
    "resolve_focus": SpanKind.RESOLVE,
    "pack": SpanKind.TOOL,
    "fingerprint": SpanKind.GRAPH,
}


def _fold(records: list[GeneratorQuery]) -> list[tuple[GeneratorQuery, int]]:
    """Collapse repeated reads of one query into a single row.

    `PATTERN_SIBLINGS` runs once per dropped movement and the graph
    fingerprint once per label, so an unfolded waterfall is thirty rows of the
    same two queries. Folded, each keeps its first offset and carries the
    summed duration, summed rows and the number of calls — which is the figure
    worth seeing anyway.
    """
    order: list[str] = []
    grouped: dict[str, list[GeneratorQuery]] = {}
    for record in records:
        if record.name not in grouped:
            order.append(record.name)
            grouped[record.name] = []
        grouped[record.name].append(record)

    folded = []
    for name in order:
        calls = grouped[name]
        first = calls[0]
        folded.append(
            (
                first.model_copy(
                    update={
                        "duration_ms": round(sum(c.duration_ms for c in calls), 2),
                        "rows": sum(c.rows for c in calls),
                    }
                ),
                len(calls),
            )
        )
    return folded


def build_generator_trace(
    run_id: str,
    prompt: str,
    started_at: datetime,
    duration_ms: float,
    recorder: RunRecorder,
    extraction: Extraction,
    generated: GeneratedPlan,
) -> RunTrace:
    """Turn one plan generation into a trace.

    Every offset here is measured rather than reconstructed: `RunRecorder`
    hands the stages and the graph reads one clock, so a read appears under the
    stage that actually issued it and the waterfall is the run's real shape.

    Args:
        run_id: Identifier for the run.
        prompt: What the coach asked for, in their words.
        started_at: When the run began.
        duration_ms: End-to-end wall time, including extraction.
        recorder: The stage and query account the pipeline filled in.
        extraction: What the model produced, and what it cost.
        generated: The finished plan, read for what did not apply.

    Returns:
        The assembled trace, degraded when part of the request did not land.
    """
    ids = (f"sp_{n}" for n in itertools.count(1))
    root_id = next(ids)

    # A run is degraded when the coach asked for something the plan does not
    # reflect. All three are silent by default, which is exactly why they are
    # the status: a plan that quietly ignored a constraint looks like one that
    # applied it.
    unapplied = generated.composition.unapplied
    unresolved_focus = [r for r in generated.focus if r.match is None]
    shortfalls = []
    if unapplied:
        shortfalls.append(f"{len(unapplied)} directive(s) not applied")
    if unresolved_focus:
        shortfalls.append(f"{len(unresolved_focus)} emphasis phrase(s) unresolved")
    if extraction.result.unmapped:
        shortfalls.append(f"{len(extraction.result.unmapped)} phrase(s) heard but unmapped")
    status = SpanStatus.DEGRADED if shortfalls else SpanStatus.OK

    spans = [
        TraceSpan(
            id=root_id,
            parent_id=None,
            kind=SpanKind.AGENT,
            name="plan.generate",
            started_ms=0.0,
            duration_ms=duration_ms,
            status=status,
            attributes=[
                SpanAttribute(label="member", value=generated.member_id),
                SpanAttribute(label="requested minutes", value=str(generated.requested_minutes)),
                SpanAttribute(label="catalogue", value=str(len(generated.trace.result.verdicts))),
                SpanAttribute(label="eligible", value=str(generated.trace.result.attribution.kept)),
                SpanAttribute(label="prescribed", value=str(len(generated.plan.blocks))),
                SpanAttribute(label="substitutions", value=str(len(generated.substitutions))),
                SpanAttribute(
                    label="parent run", value=generated.parent_run_id or "none — a fresh build"
                ),
            ],
            note="; ".join(shortfalls) or None,
        )
    ]

    if extraction.model:
        spans.append(
            TraceSpan(
                id=next(ids),
                parent_id=root_id,
                kind=SpanKind.LLM,
                name="extract",
                started_ms=0.0,
                duration_ms=extraction.duration_ms,
                status=SpanStatus.OK,
                attributes=[
                    SpanAttribute(
                        label="instructions", value=str(len(extraction.result.instructions))
                    ),
                    SpanAttribute(label="emphasis", value=str(len(extraction.result.emphasis))),
                    SpanAttribute(label="unmapped", value=str(len(extraction.result.unmapped))),
                ],
                model=extraction.model,
                tokens_in=extraction.tokens_in,
                tokens_out=extraction.tokens_out,
            )
        )

    # Extraction runs before the pipeline, so every recorded offset sits after
    # it. Shifting here rather than starting the recorder earlier keeps the
    # pipeline unaware of what preceded it.
    shift = extraction.duration_ms

    for stage in recorder.stages:
        stage_id = next(ids)
        ends = stage.started_ms + stage.duration_ms
        spans.append(
            TraceSpan(
                id=stage_id,
                parent_id=root_id,
                kind=STAGE_KINDS.get(stage.name, SpanKind.TOOL),
                name=stage.name,
                started_ms=round(stage.started_ms + shift, 2),
                duration_ms=stage.duration_ms,
                status=SpanStatus.OK,
            )
        )
        inside = [q for q in recorder.queries if stage.started_ms <= q.started_ms < ends]
        for record, calls in _fold(inside):
            spans.append(
                TraceSpan(
                    id=next(ids),
                    parent_id=stage_id,
                    kind=SpanKind.GRAPH,
                    name=record.name,
                    started_ms=round(record.started_ms + shift, 2),
                    duration_ms=record.duration_ms,
                    status=SpanStatus.OK,
                    attributes=(
                        [SpanAttribute(label="calls", value=str(calls))] if calls > 1 else []
                    )
                    + [
                        SpanAttribute(label=key, value=str(value))
                        for key, value in record.params.items()
                    ],
                    query=record.cypher,
                    rows_returned=record.rows,
                )
            )

    return RunTrace(
        run_id=run_id,
        source="generator",
        prompt=prompt,
        started_at=started_at.astimezone(UTC).isoformat(),
        duration_ms=round(duration_ms, 2),
        status=status,
        totals=RunTotals(
            graph_queries=len(recorder.queries),
            llm_calls=1 if extraction.model else 0,
            tokens_in=extraction.tokens_in,
            tokens_out=extraction.tokens_out,
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
