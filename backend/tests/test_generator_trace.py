from datetime import UTC, datetime, timedelta

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.usage import RequestUsage

from agents.workout_generator.agent import Usage
from agents.workout_generator.deps import ProvenanceEvent, ProvenanceKind
from api.traces import SpanKind, SpanStatus, build_generator_trace
from catalog.eligibility import Exclusion, ExclusionCause
from constraints.models import Constraint, ConstraintSet, Effect, Origin

START = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
USAGE = Usage(llm_calls=2, tokens_in=200, tokens_out=100)


def at(ms: float) -> datetime:
    return START + timedelta(milliseconds=ms)


def request(ts: datetime | None, retry: str | None = None) -> ModelRequest:
    parts = [RetryPromptPart(content=retry)] if retry else [UserPromptPart(content="go")]
    return ModelRequest(parts=parts, timestamp=ts)


def response(ts: datetime, tokens_in: int = 100, tokens_out: int = 50) -> ModelResponse:
    return ModelResponse(
        parts=[TextPart(content="ok")],
        timestamp=ts,
        model_name="claude-test",
        usage=RequestUsage(input_tokens=tokens_in, output_tokens=tokens_out),
    )


def trace(tool_log=(), messages=(), duration_ms=1500.0):
    return build_generator_trace(
        "run_t", "prompt", START, duration_ms, list(tool_log), list(messages), USAGE
    )


def test_llm_turns_carry_real_timing_and_per_turn_tokens() -> None:
    """The whole point of the rebuild: without these spans the trace shows a
    44-second run as one bar and no model activity at all."""
    result = trace(
        messages=[
            request(at(100)),
            response(at(600), tokens_in=120, tokens_out=40),
            request(at(700)),
            response(at(1200), tokens_in=300, tokens_out=80),
        ]
    )
    llm = [s for s in result.spans if s.kind is SpanKind.LLM]
    assert [s.name for s in llm] == ["chat · turn 1", "chat · turn 2"]
    assert llm[0].started_ms == 100.0
    assert llm[0].duration_ms == 500.0
    assert llm[0].model == "claude-test"
    assert (llm[0].tokens_in, llm[0].tokens_out) == (120, 40)
    assert (llm[1].tokens_in, llm[1].tokens_out) == (300, 80)
    assert result.status is SpanStatus.OK


def test_retry_turn_is_degraded_with_the_validator_feedback() -> None:
    """A validator bounce must be visible in the trace — a run that needed
    teaching cannot look identical to a clean one."""
    result = trace(
        messages=[
            request(at(0)),
            response(at(500)),
            request(at(600), retry="exercise:X is excluded. Replace this slot."),
            response(at(1000)),
        ]
    )
    llm = [s for s in result.spans if s.kind is SpanKind.LLM]
    assert llm[0].status is SpanStatus.OK
    assert llm[1].status is SpanStatus.DEGRADED
    assert llm[1].note is not None and "excluded" in llm[1].note
    assert result.status is SpanStatus.DEGRADED
    root = next(s for s in result.spans if s.parent_id is None)
    assert root.status is SpanStatus.DEGRADED


def test_tool_spans_carry_cypher_offsets_and_the_query_total() -> None:
    """Real offsets order the waterfall, the Cypher panel returns, and the
    graph total stops reading 0 for a run that made five reads."""
    events = [
        ProvenanceEvent(
            kind=ProvenanceKind.CLINICAL_ENVELOPE,
            started_ms=0.0,
            duration_ms=12.5,
            constraint_set=ConstraintSet(
                constraints=(
                    Constraint(
                        target="movement_pattern:plyo",
                        effect=Effect.BLOCK,
                        origin=Origin.CLINICAL,
                    ),
                )
            ),
        ),
        ProvenanceEvent(
            kind=ProvenanceKind.MEMBER_SNAPSHOT, started_ms=800.0, duration_ms=30.0
        ),
        ProvenanceEvent(
            kind=ProvenanceKind.CANDIDATE_RETRIEVAL,
            started_ms=2000.0,
            duration_ms=45.0,
            candidates=("exercise:A",),
            exclusions=(
                Exclusion(
                    concept_id="exercise:B",
                    cause=ExclusionCause.BLOCKED,
                    matched_target="movement_pattern:plyo",
                ),
            ),
        ),
    ]
    result = trace(tool_log=events)
    snapshot = next(s for s in result.spans if s.name == "member_snapshot")
    assert snapshot.started_ms == 800.0
    assert snapshot.duration_ms == 30.0
    assert snapshot.query is not None and "member.standing" in snapshot.query
    retrieval = next(s for s in result.spans if s.name == "candidate_retrieval")
    assert retrieval.rows_returned == 2
    envelope = next(s for s in result.spans if s.name == "clinical_envelope")
    assert envelope.rows_returned == 1
    assert result.totals.graph_queries == 5, "3 snapshot + 1 catalog + 1 clinical"

    children = [s for s in result.spans if s.parent_id is not None]
    assert [s.started_ms for s in children] == sorted(s.started_ms for s in children)


def test_rejected_declaration_degrades_the_run() -> None:
    """A declaration the run refused must surface at run level, or the coach
    reads a plan that quietly ignored a directive as clean."""
    result = trace(
        tool_log=[
            ProvenanceEvent(
                kind=ProvenanceKind.CONSTRAINT_DECLARATION,
                rejected_targets=("exercise:nope",),
            )
        ]
    )
    declaration = next(s for s in result.spans if s.name == "constraint_declaration")
    assert declaration.status is SpanStatus.DEGRADED
    assert declaration.note is not None and "exercise:nope" in declaration.note
    assert result.status is SpanStatus.DEGRADED
    root = next(s for s in result.spans if s.parent_id is None)
    assert root.note is not None


def test_unmatched_requires_degrade_the_retrieval_span() -> None:
    """A require nothing can satisfy is the other quiet failure mode."""
    result = trace(
        tool_log=[
            ProvenanceEvent(
                kind=ProvenanceKind.CANDIDATE_RETRIEVAL,
                candidates=("exercise:A",),
                unmatched_requires=("equipment:Trap Bar",),
            )
        ]
    )
    retrieval = next(s for s in result.spans if s.name == "candidate_retrieval")
    assert retrieval.status is SpanStatus.DEGRADED
    assert retrieval.note is not None and "Trap Bar" in retrieval.note


def test_request_without_timestamp_does_not_crash() -> None:
    """History revived from a store carries no request stamps; the trace must
    still build rather than 500 the plan route after a successful run."""
    result = trace(messages=[request(None), response(at(500))])
    llm = [s for s in result.spans if s.kind is SpanKind.LLM]
    assert llm[0].started_ms == 0.0
    assert llm[0].duration_ms == 0.0
    assert result.status is SpanStatus.OK
