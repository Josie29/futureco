import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from neo4j import Record, Session
from pydantic import BaseModel, ConfigDict

from plan import queries as plan_queries
from safety import queries as safety_queries

# Observability for the generator (ASSESSMENT.md:134), collected the only way
# that yields real data: by wrapping the session every stage already writes to.
#
# `copilot/tools.py` records its reads by hand because it owns all nine of them.
# The generator's reads are spread across `safety/standing.py`,
# `safety/queries.py` and `plan/queries.py`, and threading a recorder through
# all three would mean changing every query function to take one. Wrapping the
# session instead leaves those modules untouched and cannot miss a read: if it
# went through the session, it is in the trace.
#
# Stage timings and query timings share one clock, so a generator waterfall
# lays out from measured offsets. The copilot's has to reconstruct them by
# summing durations, and says so — this one does not have to.


class QueryRecord(BaseModel):
    """One graph read, as it actually ran."""

    model_config = ConfigDict(frozen=True)

    name: str
    cypher: str
    params: dict[str, Any]
    rows: int
    started_ms: float
    duration_ms: float


class StageRecord(BaseModel):
    """One stage of the pipeline, timed end to end."""

    model_config = ConfigDict(frozen=True)

    name: str
    started_ms: float
    duration_ms: float


def _registry() -> dict[str, str]:
    """Map query text to the constant it was declared as.

    Built from the modules rather than hand-listed, so a query added to either
    one is named in the trace without this file being touched. Keyed on the
    stripped text because that is all the session receives — the name is on the
    module attribute, and it does not travel with the string.
    """
    named: dict[str, str] = {}
    for module in (safety_queries, plan_queries):
        for attribute, value in vars(module).items():
            if attribute.isupper() and isinstance(value, str) and "MATCH" in value:
                named[value.strip()] = attribute
    return named


QUERY_NAMES: dict[str, str] = _registry()

# `read_report` builds one count query per label and per relationship type, so
# stamping a trace with the graph it ran against costs roughly twenty round
# trips. They are named rather than dropped: the trace is supposed to account
# for the request's latency, and twenty reads is a large enough share of a
# generation to be worth a reviewer seeing. The trace builder folds same-named
# reads into one span, so they arrive as two rows carrying their real total.
FINGERPRINT_NODES = "GRAPH_FINGERPRINT_NODES"
FINGERPRINT_EDGES = "GRAPH_FINGERPRINT_EDGES"


def name_for(cypher: str) -> str:
    """Name a query from the constant it was declared as.

    Args:
        cypher: The query text as handed to the session.

    Returns:
        The module-level constant's name, one of the fingerprint names for the
        counts `read_report` generates, or `ADHOC` for anything else.
    """
    stripped = cypher.strip()
    if declared := QUERY_NAMES.get(stripped):
        return declared
    if stripped.startswith("MATCH (n:") and "count(n)" in stripped:
        return FINGERPRINT_NODES
    if stripped.startswith("MATCH ()-[r:") and "count(r)" in stripped:
        return FINGERPRINT_EDGES
    return "ADHOC"


class RecordedResult:
    """A materialised result, standing in for `neo4j.Result`.

    The rows are pulled eagerly so the recorded duration covers fetching them
    rather than only issuing the query — a lazily-consumed result would report
    a read as far faster than it was. Only the two methods the query modules
    use are provided; anything else is a caller this wrapper has not been
    checked against, and should fail loudly rather than silently return nothing.
    """

    __slots__ = ("_records",)

    def __init__(self, records: list[Record]) -> None:
        self._records = records

    def __iter__(self) -> Iterator[Record]:
        return iter(self._records)

    def single(self) -> Record | None:
        """The one record, or None when the query matched nothing."""
        return self._records[0] if self._records else None


class RecordingSession:
    """A Neo4j session that reports every read it makes to a recorder.

    Attribute access falls through to the wrapped session, so this is a
    drop-in for the `Session` type the query modules annotate. Only `run` is
    intercepted.
    """

    def __init__(self, inner: Session, recorder: "RunRecorder") -> None:
        self._inner = inner
        self._recorder = recorder

    def run(self, query: str, **params: Any) -> RecordedResult:
        """Execute one read, materialise it, and record what it cost."""
        began = time.perf_counter()
        records = list(self._inner.run(query, **params))
        self._recorder.queries.append(
            QueryRecord(
                name=name_for(query),
                cypher=query.strip(),
                params=params,
                rows=len(records),
                started_ms=self._recorder.offset_ms(began),
                duration_ms=round((time.perf_counter() - began) * 1000, 2),
            )
        )
        return RecordedResult(records)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class RunRecorder:
    """One run's account of itself.

    Holds the clock every offset in the trace is measured from, so stages and
    the reads inside them line up in the waterfall instead of being two
    independent timelines drawn together.
    """

    def __init__(self) -> None:
        self._origin = time.perf_counter()
        self.stages: list[StageRecord] = []
        self.queries: list[QueryRecord] = []

    def offset_ms(self, at: float | None = None) -> float:
        """Milliseconds from the start of the run to `at`, or to now."""
        return round(((at if at is not None else time.perf_counter()) - self._origin) * 1000, 2)

    def session(self, inner: Session) -> RecordingSession:
        """Wrap a session so its reads land in this account."""
        return RecordingSession(inner, self)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time one stage of the pipeline.

        Recorded in a `finally`, so a stage that raised still appears in the
        trace. A run that failed halfway is exactly when the waterfall is worth
        having, and a missing span would point at the wrong stage.
        """
        began = time.perf_counter()
        try:
            yield
        finally:
            self.stages.append(
                StageRecord(
                    name=name,
                    started_ms=self.offset_ms(began),
                    duration_ms=round((time.perf_counter() - began) * 1000, 2),
                )
            )
