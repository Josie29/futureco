import json
from datetime import UTC, datetime
from typing import Any

from neo4j import Session
from pydantic import BaseModel, ConfigDict, ValidationError

from copilot import charts, deterministic
from copilot.answer import ChartKind, ChartPayload, CopilotAnswer, Paragraph
from copilot.citations import describe, validate
from copilot.tools import QueryRecord, Retrieval, RetrievedMessage
from settings import settings

MODEL = "claude-opus-5"
MAX_TOKENS = 8000
EFFORT = "low"
"""Retrieval and synthesis over a handful of typed rows is not intelligence-
sensitive work, and this surface has a ~5s budget (ASSESSMENT.md:123). `low`
is the starting point, not a swept result — the sweep needs an API key and a
latency baseline, neither of which exists yet. Recorded here so the next person
tunes it rather than rediscovering it."""

MAX_ITERATIONS = 8
"""Ceiling on tool-calling rounds. Seven tools over one member cannot need more;
the cap exists so a loop cannot run away inside a request."""

# Thinking is left ON deliberately. Disabling it on Claude Opus 5 has a
# documented failure mode where a tool call is written into the visible text
# instead of emitted as a tool_use block: the turn succeeds, the call never
# runs, and nothing errors. On a copilot whose entire job is tool-driven
# retrieval that failure is silent and total — an answer composed from no data
# that looks exactly like one composed from all of it. Lower `effort` is the
# cost lever here, not `thinking: disabled`.
THINKING: dict[str, str] = {"type": "adaptive"}

SYSTEM = """\
You are a retrieval copilot for a strength coach, answering questions about one \
member from her knowledge graph.

Ground every claim in a tool result. If the tools do not cover something, say so \
plainly and name what the record does hold — never fill a gap from general \
knowledge, and never estimate a figure you were not given.

You are not a clinician. Report measurements against the reference bands the \
tools return, and name what falls outside one. Do not diagnose, interpret \
symptoms, or give medical advice; a coach reads this, and the member is not \
your patient.

Answering well:
- Lead with the answer. The coach has one minute before a session.
- Two or three short paragraphs. A `lead` is a bolded opener of a few words.
- Cite a member message whenever it is the evidence for a claim, using the exact \
`id` the tool returned. Never invent an id — cited ids are checked against what \
retrieval returned, and an invented one is dropped and reported as a failure.
- Ask for a chart only when the shape of a series is the point. Pass the \
`metric_id` a tool gave you; you never supply data points yourself.
- Dates and figures come from tool results verbatim. "Today" is the member's \
`as_of` date, not the current date.
"""


class ChartRequest(BaseModel):
    """A chart the answer wants, named rather than drawn.

    The model chooses the kind and, for a metric chart, which metric. Every
    number is then read from the graph by `charts.py` — so the worst a bad
    request can do is show the wrong true chart, never a plausible false one.
    """

    model_config = ConfigDict(frozen=True)

    kind: ChartKind
    metric_id: str | None = None


class ModelAnswer(BaseModel):
    """The shape the model returns, before validation and chart assembly."""

    model_config = ConfigDict(frozen=True)

    paragraphs: list[Paragraph]
    cited_message_ids: list[str] = []
    chart: ChartRequest | None = None


ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "lead": {"type": ["string", "null"]},
                    "text": {"type": "string"},
                },
                "required": ["lead", "text"],
                "additionalProperties": False,
            },
        },
        "cited_message_ids": {"type": "array", "items": {"type": "string"}},
        "chart": {
            "type": ["object", "null"],
            "properties": {
                "kind": {"type": "string", "enum": [k.value for k in ChartKind]},
                "metric_id": {"type": ["string", "null"]},
            },
            "required": ["kind", "metric_id"],
            "additionalProperties": False,
        },
    },
    "required": ["paragraphs", "cited_message_ids", "chart"],
    "additionalProperties": False,
}


def has_key() -> bool:
    """Whether an Anthropic key is configured.

    Read from the environment rather than from settings, because the SDK reads
    it the same way and a mismatch between the two would be a confusing failure.
    """
    return bool(settings.anthropic_api_key)


def _build_tools(retrieval: Retrieval, seen: list[RetrievedMessage]) -> list:
    """Wrap the retrieval methods as SDK tools.

    Defined inside a function so each closes over one request's `Retrieval` —
    there is no module-level state a concurrent request could read. Every tool
    returns JSON built from a Pydantic model, so the contract the model sees and
    the contract the rest of the code uses are the same definition.

    Args:
        retrieval: This run's graph access.
        seen: Accumulator for every message returned, which becomes the
            allowlist citations are checked against.

    Returns:
        Decorated tool callables for `client.beta.messages.tool_runner`.
    """
    from anthropic import beta_tool

    def dump(value: Any) -> str:
        if isinstance(value, BaseModel):
            return value.model_dump_json()
        if isinstance(value, list):
            return json.dumps([v.model_dump(mode="json") for v in value])
        return json.dumps(value)

    @beta_tool
    def member_profile() -> str:
        """Who the member is, what equipment she owns, what she dislikes, and her
        goals with how each is scored. Also returns `as_of`, the date this record
        should be read as "today". Call this first for anything member-specific."""
        return dump(retrieval.profile())

    @beta_tool
    def recent_sessions(days: int = 30, limit: int = 10) -> str:
        """Her recent sessions, newest first, with the movement patterns each one
        trained and the movements the coach wrote down. A skipped session returns
        an empty `patterns` list, which means nothing was trained.

        Args:
            days: How far back to look, relative to `as_of`.
            limit: Maximum sessions to return.
        """
        return dump(retrieval.sessions(days=days, limit=limit))

    @beta_tool
    def pattern_frequency(days: int = 14) -> str:
        """How many sessions trained each movement pattern in a window, most
        frequent first. Use this for "what has she been working on" and for
        spotting repeated work.

        Args:
            days: How far back to look, relative to `as_of`.
        """
        return dump(retrieval.pattern_frequency(days=days))

    @beta_tool
    def list_metrics() -> str:
        """Every metric she has readings for — sleep, heart rate, HRV, weight,
        body composition, blood panel, weekly adherence — with the latest value.
        Call this before `metric_series` so you use a real `metric_id`."""
        return dump(retrieval.metric_index())

    @beta_tool
    def metric_series(metric_id: str, days: int = 365) -> str:
        """One metric's readings with the reference band they are judged against.

        `direction` says what falling outside the band means: `lower_better`,
        `higher_better`, `band` (bad either side), or `trend` (no band exists, so
        nothing is out of range). Consult it before calling any value abnormal.

        Args:
            metric_id: An id from `list_metrics`.
            days: How far back to look, relative to `as_of`.
        """
        series = retrieval.metric(metric_id, days=days)
        return dump(series) if series else json.dumps({"readings": [], "note": "no readings"})

    @beta_tool
    def search_messages(concept: str = "", days: int = 365, limit: int = 10) -> str:
        """Her message thread. With `concept`, returns only messages that name that
        concept — matched through the graph when the message was ingested, not by
        text search. Call `list_mentioned_concepts` first to get a valid concept.

        Every message carries the `id` you must use to cite it.

        Args:
            concept: A concept name, or empty for the whole recent thread.
            days: How far back to look when no concept is given.
            limit: Maximum messages to return.
        """
        found = (
            retrieval.messages_about(concept, limit=limit)
            if concept
            else retrieval.messages(days=days, limit=limit)
        )
        seen.extend(found)
        return dump(found)

    @beta_tool
    def list_mentioned_concepts() -> str:
        """Concepts her messages name — equipment, anatomy, movement patterns —
        with how often. Use these as the `concept` argument to `search_messages`."""
        return dump(retrieval.mentioned_concepts())

    @beta_tool
    def clinical_picture() -> str:
        """Her injuries, the condition each is diagnosed as, and the movement
        patterns that condition rules out (`contraindicates`) or flags
        (`cautions`). These are the same edges the workout generator enforces, so
        an explanation from here matches what it would actually exclude."""
        return dump(retrieval.clinical_picture())

    @beta_tool
    def churn_assessment() -> str:
        """Today's churn reading, derived from her adherence series, skipped
        sessions, and how long since she last wrote. Each signal carries the
        figures behind it, so quote those rather than re-deriving them."""
        return dump(retrieval.churn())

    return [
        member_profile,
        recent_sessions,
        pattern_frequency,
        list_metrics,
        metric_series,
        search_messages,
        list_mentioned_concepts,
        clinical_picture,
        churn_assessment,
    ]


def _assemble_chart(request: ChartRequest | None, retrieval: Retrieval) -> ChartPayload | None:
    """Build the chart the model asked for, from the graph.

    Returns None when the requested series has no readings — a missing chart is
    a smaller failure than a chart of nothing, and the prose still stands.
    """
    if request is None:
        return None

    if request.kind is ChartKind.MESSAGE_PATTERN:
        adherence = retrieval.adherence()
        return (
            charts.message_pattern_chart(retrieval.messages(days=365), adherence)
            if adherence
            else None
        )

    if request.kind in (ChartKind.ADHERENCE, ChartKind.WEEKLY_COMPARISON):
        adherence = retrieval.adherence()
        if adherence is None:
            return None
        if request.kind is ChartKind.ADHERENCE:
            return charts.adherence_chart(adherence)
        return charts.weekly_comparison_chart(
            adherence, retrieval.profile().training_days_per_week
        )

    metric_id = request.metric_id or (
        deterministic.SLEEP_METRIC if request.kind is ChartKind.SLEEP else None
    )
    if metric_id is None:
        return None
    series = retrieval.metric(metric_id, days=365)
    if series is None:
        return None
    return (
        charts.sleep_chart(series)
        if request.kind is ChartKind.SLEEP
        else charts.metric_chart(series)
    )


class RunResult(BaseModel):
    """One copilot turn plus what it cost, for the trace."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    answer: CopilotAnswer
    queries: list[QueryRecord] = []
    """Every graph read this run made, in order. Carried on the result rather
    than left on the `Retrieval` so the caller can trace a run without holding
    the object that produced it."""

    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    used_model: bool = False


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run_with_model(retrieval: Retrieval, question: str, answer_id: str) -> RunResult:
    """Answer by letting the model drive the retrieval tools.

    Raises:
        anthropic.APIError: Propagated so the caller can fall back rather than
            returning an answer that silently used no model.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    seen: list[RetrievedMessage] = []

    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        thinking=THINKING,
        output_config={
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": ANSWER_SCHEMA},
        },
        tools=_build_tools(retrieval, seen),
        messages=[{"role": "user", "content": question}],
        max_iterations=MAX_ITERATIONS,
    )

    final = None
    llm_calls = tokens_in = tokens_out = 0
    for message in runner:
        final = message
        llm_calls += 1
        tokens_in += message.usage.input_tokens
        tokens_out += message.usage.output_tokens

    degraded: str | None = None
    paragraphs: list[Paragraph]
    cited: list[str] = []
    chart_request: ChartRequest | None = None

    text = ""
    if final is not None:
        text = "".join(block.text for block in final.content if block.type == "text")

    # A refusal arrives as a successful response with an empty or partial body,
    # so `stop_reason` has to be checked before the content is read.
    if final is not None and final.stop_reason == "refusal":
        paragraphs = [
            Paragraph(text="That request was declined by the model's safety system.")
        ]
        degraded = "The model declined this request; no answer was produced."
    else:
        try:
            parsed = ModelAnswer.model_validate_json(text)
            paragraphs, cited, chart_request = (
                parsed.paragraphs,
                parsed.cited_message_ids,
                parsed.chart,
            )
        except (ValidationError, ValueError):
            # Structured output should make this unreachable. If it happens,
            # the model's words are still worth showing — but the run is
            # degraded, because citations and charts were lost with the shape.
            paragraphs = [Paragraph(text=text or "The model returned nothing.")]
            degraded = "The answer did not match the expected shape, so it is shown as plain text."

    check = validate(cited, seen, retrieval.profile().name)
    degraded = degraded or describe(check)

    return RunResult(
        answer=CopilotAnswer(
            id=answer_id,
            ts=_now(),
            paragraphs=paragraphs,
            cites=check.citations,
            chart=_assemble_chart(chart_request, retrieval),
            degraded=degraded,
        ),
        queries=retrieval.queries,
        llm_calls=llm_calls,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        used_model=True,
    )


def answer(session: Session, member_id: str, question: str, answer_id: str) -> RunResult:
    """Answer one question about one member.

    Takes the model path when a key is configured and the deterministic
    retrieval path otherwise. Both run the same tools against the same graph;
    what the key buys is interpretation, and the answer says which one it got.

    Args:
        session: An open Neo4j session.
        member_id: Whose record to read.
        question: What the coach typed.
        answer_id: Id for the produced turn.

    Returns:
        The answer and the run's cost. `answer.degraded` is set whenever the
        turn is less than a full one, which the console renders as a banner.
    """
    retrieval = Retrieval(session, member_id)

    if not has_key():
        rendered = deterministic.render(retrieval, question, answer_id, _now())
        return RunResult(
            answer=CopilotAnswer(**rendered), queries=retrieval.queries
        )

    try:
        return _run_with_model(retrieval, question, answer_id)
    except Exception as exc:  # noqa: BLE001 - any model failure falls back to retrieval
        # The graph is still reachable and the coach still asked a question, so
        # returning what retrieval found beats returning an error page.
        rendered = deterministic.render(retrieval, question, answer_id, _now())
        rendered["degraded"] = (
            f"The model call failed ({type(exc).__name__}), so this is retrieval only."
        )
        return RunResult(answer=CopilotAnswer(**rendered), queries=retrieval.queries)
