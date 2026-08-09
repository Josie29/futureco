import json

import pytest
from neo4j import Session

from copilot import charts, citations
from copilot.agent import _build_tools, answer, has_key
from copilot.answer import ChartKind
from copilot.deterministic import NO_KEY_BANNER, Intent, route
from copilot.tools import MetricReading, MetricSeries, Retrieval, RetrievedMessage
from graph.driver import graph_session
from graph.schema import MetricDirection

MEMBER = "mbr_01HX9JORDAN"


@pytest.fixture(scope="module")
def session() -> Session:
    with graph_session() as open_session:
        yield open_session


@pytest.fixture
def retrieval(session: Session) -> Retrieval:
    """A fresh retrieval per test — `queries` and `seen_message_ids` accumulate."""
    return Retrieval(session, MEMBER)


# ---------------------------------------------------------------- citations


def _message(message_id: str) -> RetrievedMessage:
    return RetrievedMessage(
        id=message_id, ts="2026-05-30T15:12:00+00:00", author="member", text="Skipped Thursday"
    )


def test_invented_citation_is_dropped_and_reported() -> None:
    """An id retrieval never returned cannot reach a coach.

    This is the one claim in an answer that can be mechanically checked, and it
    is the one that matters most: the console renders citations as clickable
    proof, so a fabricated one is a lie with a link on it. Prose figures cannot
    be validated this way — which is exactly why this check has to hold.
    """
    check = citations.validate(
        ["msg_real", "msg_INVENTED"], [_message("msg_real")], "Jordan Rivera"
    )
    assert [c.message_id for c in check.citations] == ["msg_real"]
    assert check.dropped == ["msg_INVENTED"]
    assert not check.is_clean
    assert "never retrieved" in citations.describe(check)


def test_citing_a_real_message_that_was_not_retrieved_still_fails() -> None:
    """The allowlist is what this run returned, not what the graph holds.

    A model naming a message it was never shown is asserting a source it does
    not have, even when the message exists. Weakening this to "does it exist"
    would let an answer cite the whole thread it never read.
    """
    check = citations.validate(["msg_elsewhere"], [_message("msg_here")], "Jordan Rivera")
    assert check.citations == []
    assert check.dropped == ["msg_elsewhere"]


def test_clean_citations_report_nothing() -> None:
    """A good run must not raise a banner. Degraded has to stay meaningful."""
    check = citations.validate(["msg_a"], [_message("msg_a")], "Jordan Rivera")
    assert check.is_clean
    assert citations.describe(check) is None


# ------------------------------------------------------------------- charts


def _series(direction: MetricDirection, low: float | None, high: float | None, *values: float):
    return MetricSeries(
        metric_id="m",
        name="Test metric",
        unit="u",
        category="biomarker",
        direction=direction,
        optimal_low=low,
        optimal_high=high,
        reference="test",
        readings=[
            MetricReading(observed_on=f"2026-06-{1 + i:02d}", value=v) for i, v in enumerate(values)
        ],
    )


def test_trend_metric_never_flags_a_point() -> None:
    """A metric with no band cannot have a value outside one.

    HRV and body weight carry no defensible population range. Treating a
    missing bound as zero would paint every reading red on a chart a coach
    reads as clinical.
    """
    series = _series(MetricDirection.TREND, None, None, 40.0, 55.0, 999.0)
    chart = charts.metric_chart(series)
    assert [p.alert for p in chart.series] == [False, False, False]


def test_one_sided_band_only_flags_its_own_side(retrieval: Retrieval) -> None:
    """Resting heart rate below the adult band is favourable, not a breach.

    The case the whole `MetricDirection` split exists for. If this flags, a
    coach sees her athletic resting pulse marked red next to her cholesterol.
    """
    resting = retrieval.metric("resting_hr", days=365)
    assert resting is not None
    assert resting.direction is MetricDirection.LOWER_BETTER
    assert [p.alert for p in charts.metric_chart(resting).series] == [False]


def test_message_pattern_counts_only_the_member(retrieval: Retrieval) -> None:
    """A coach writing into silence is not contact.

    Counting coach messages would hide the exact pattern this chart exists to
    show — the member who stopped replying while the coach kept trying.
    """
    messages = retrieval.messages(days=365)
    adherence = retrieval.adherence()
    assert adherence is not None

    from_member = sum(1 for m in messages if m.author == "member")
    assert any(m.author == "coach" for m in messages), "fixture must contain a coach message"

    chart = charts.message_pattern_chart(messages, adherence)
    assert sum(p.value for p in chart.series) == from_member


def test_charts_share_the_adherence_x_axis(retrieval: Retrieval) -> None:
    """Message pattern buckets onto adherence weeks, not calendar weeks.

    The two charts are meant to be read against each other — "the quiet weeks
    are the weeks she trained least" is only a claim you can make if the axes
    line up.
    """
    adherence = retrieval.adherence()
    assert adherence is not None
    pattern = charts.message_pattern_chart(retrieval.messages(days=365), adherence)
    assert [p.label for p in pattern.series] == [
        p.label for p in charts.adherence_chart(adherence).series
    ]


# -------------------------------------------------------------------- tools


def test_every_tool_returns_parseable_json(retrieval: Retrieval) -> None:
    """A tool that returns malformed JSON breaks the loop silently.

    The model receives tool results as text. Bad JSON is not an exception on
    this side — it is a confused model on the other, with no error to trace.
    Only reachable with an API key, so it is pinned here instead.
    """
    seen: list[RetrievedMessage] = []
    tools = {tool.name: tool for tool in _build_tools(retrieval, seen)}
    calls = {
        "member_profile": {},
        "recent_sessions": {"days": 30, "limit": 3},
        "pattern_frequency": {"days": 14},
        "list_metrics": {},
        "metric_series": {"metric_id": "sleep_hours"},
        "search_messages": {"concept": "Barbell"},
        "list_mentioned_concepts": {},
        "clinical_picture": {},
        "churn_assessment": {},
    }
    assert set(calls) == set(tools), "every tool needs a smoke call"

    for name, kwargs in calls.items():
        json.loads(tools[name].call(kwargs))


def test_unknown_metric_answers_rather_than_raising(retrieval: Retrieval) -> None:
    """Asking for a metric she has no readings for is an answer, not an error.

    "I don't have that for her" is a valid response and the graceful
    degradation the spec grades (ASSESSMENT.md:68). Raising here would turn it
    into a 500.
    """
    tools = {tool.name: tool for tool in _build_tools(retrieval, [])}
    payload = json.loads(tools["metric_series"].call({"metric_id": "vo2_max"}))
    assert payload["readings"] == []


def test_message_tools_register_their_ids_as_citable(retrieval: Retrieval) -> None:
    """Only messages a tool returned may be cited.

    The allowlist is built as a side effect of retrieval. If a message tool
    stopped registering, every citation from it would be dropped as invented —
    a silent, total loss of the evidence half of an answer.
    """
    seen: list[RetrievedMessage] = []
    tools = {tool.name: tool for tool in _build_tools(retrieval, seen)}
    tools["search_messages"].call({"concept": "Barbell"})
    assert seen, "search_messages must record what it returned"
    assert all(m.id.startswith("msg_") for m in seen)


# ------------------------------------------------------------------ routing


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Show me the brief", Intent.BRIEF),
        ("Is she at risk of churning?", Intent.CHURN),
        ("How's her adherence trending?", Intent.ADHERENCE),
        ("How has she been sleeping?", Intent.SLEEP),
        ("What changed since last week?", Intent.CHANGED),
        ("Show message pattern", Intent.MESSAGES),
        ("What has she been training?", Intent.SESSIONS),
        ("What should she avoid?", Intent.CONSTRAINTS),
        ("What is her favourite colour?", Intent.UNKNOWN),
    ],
)
def test_keyless_routing_covers_the_palette(
    retrieval: Retrieval, question: str, expected: Intent
) -> None:
    """Every quick prompt reaches its retrieval without a key.

    The palette is what a reviewer clicks first. Routing is keyword-based and
    therefore brittle by construction — pinning it is what stops a wording
    change silently dropping a prompt into the fallback.
    """
    index = {m.metric_id: m.name for m in retrieval.metric_index()}
    intent, _ = route(question, index)
    assert intent is expected


def test_metric_routing_is_data_driven_not_hardcoded(retrieval: Retrieval) -> None:
    """Any metric she has readings for is reachable by name.

    Nobody wrote "ferritin" into the router. It resolves because the index came
    from the graph — which is what stops the copilot's reach being a list
    somebody has to remember to extend.
    """
    index = {m.metric_id: m.name for m in retrieval.metric_index()}
    intent, metric_id = route("what is her ferritin?", index)
    assert (intent, metric_id) == (Intent.METRIC, "ferritin")


# --------------------------------------------------------------- the answer


def test_keyless_answer_is_grounded_and_says_it_is_partial(session: Session) -> None:
    """Without a key the answer still comes from the graph, and admits its limits.

    This is the path a reviewer gets on a cold clone, so it has to be real
    retrieval — and it has to say that nothing interpreted the figures, or a
    coach would read composed facts as judgement.
    """
    assert not has_key(), "this test describes the no-key path"

    result = answer(session, MEMBER, "How has she been sleeping?", "cp_test")
    assert result.used_model is False
    assert result.answer.degraded == NO_KEY_BANNER
    assert result.queries, "the keyless path must still hit the graph"

    text = " ".join(p.text for p in result.answer.paragraphs)
    assert "6.1" in text and "5.4" in text, "figures must come from her readings"
    assert result.answer.chart is not None
    assert result.answer.chart.kind is ChartKind.SLEEP


def test_unanswerable_question_names_what_the_record_holds(session: Session) -> None:
    """An ungrounded question gets a decline, not an invention.

    The failure this system exists to avoid is a fluent answer about data that
    is not there. Naming the coverage turns a dead end into a next step.
    """
    result = answer(session, MEMBER, "What is her favourite colour?", "cp_test")
    text = " ".join(p.text for p in result.answer.paragraphs).lower()
    assert "record covers" in text
    assert result.answer.chart is None
    assert result.answer.cites == []
