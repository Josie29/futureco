from datetime import date, timedelta

from api.churn import (
    AdherenceWeek,
    ChurnLevel,
    ChurnSignalKind,
    SessionOutcome,
    assess,
)
from graph.build.member import load_member_context, reference_date
from settings import settings

# Pure. The derivation takes plain rows, so it is testable without a store —
# which matters because this is the one place the system draws a conclusion
# rather than reporting a fact.

AS_OF = date(2026, 6, 4)


PLANNED_PER_WEEK = 4
"""Jordan's schedule, so one missed session is worth 25 points."""


def _weeks(*pcts: float) -> list[AdherenceWeek]:
    """Consecutive weekly readings ending the week before `AS_OF`."""
    return [
        AdherenceWeek(week_of=AS_OF - timedelta(weeks=len(pcts) - i), pct=pct)
        for i, pct in enumerate(pcts)
    ]


def test_matches_the_stored_assessment_on_level_and_evidence() -> None:
    """The derivation reproduces the brief's own conclusion from the raw record.

    `coach_brief.churn_risk` is the calibration target and never an input. If
    this diverges, either the derivation is wrong or the stored brief is — and
    the point of deriving is that the answer can be checked against its
    evidence rather than trusted.
    """
    context = load_member_context(settings.member_context_path)
    as_of = reference_date(context)
    result = assess(
        [
            AdherenceWeek(week_of=week.week_of, pct=week.pct)
            for week in context.adherence.weekly_completion_pct
        ],
        [
            SessionOutcome(date=entry.date, completed=entry.completed)
            for entry in context.workout_history
        ],
        max(m.ts.date() for m in context.chat_history if m.author == "member"),
        as_of,
        context.preferences.training_days_per_week,
    )

    assert result.level.value == context.coach_brief.churn_risk.level
    assert {signal.kind for signal in result.signals} == {
        ChurnSignalKind.ADHERENCE_DECLINE,
        ChurnSignalKind.RECENT_SKIP,
    }


def test_does_not_reproduce_the_unsupported_reason() -> None:
    """"Login frequency down" is in the brief and in no data anywhere.

    The sample's third stored reason cites a signal the file does not contain —
    there are no logins, no sessions-of-app, nothing. A derivation cannot invent
    it, and that is the property worth pinning: if a future signal starts
    producing a login claim, it is doing so from something that is not there.
    """
    context = load_member_context(settings.member_context_path)
    stored = " ".join(context.coach_brief.churn_risk.reasons).lower()
    assert "login" in stored, "fixture changed; this test is about that reason"

    result = assess(
        [
            AdherenceWeek(week_of=week.week_of, pct=week.pct)
            for week in context.adherence.weekly_completion_pct
        ],
        [
            SessionOutcome(date=entry.date, completed=entry.completed)
            for entry in context.workout_history
        ],
        max(m.ts.date() for m in context.chat_history if m.author == "member"),
        reference_date(context),
        context.preferences.training_days_per_week,
    )
    assert "login" not in " ".join(result.reasons).lower()


def test_decline_is_measured_against_the_peak_not_the_first_week() -> None:
    """A series that climbs and then falls still registers as a decline.

    Against the first week, 50 → 100 → 50 nets to zero change and a member who
    just lost half her training disappears from the roster's attention list.
    """
    result = assess(_weeks(50, 100, 50), [], None, AS_OF, PLANNED_PER_WEEK)
    assert result.level is ChurnLevel.MODERATE
    signal = result.signals[0]
    assert signal.kind is ChurnSignalKind.ADHERENCE_DECLINE
    assert signal.evidence["drop_points"] == 50.0


def test_a_single_missed_session_is_not_a_decline() -> None:
    """One slip from a perfect record stays below the bar.

    100 → 75 is a missed session, not a trend. Firing here would put every
    member on the attention list the first time life happened.
    """
    assert assess(_weeks(100, 100, 75), [], None, AS_OF, PLANNED_PER_WEEK).level is ChurnLevel.LOW


def test_old_skips_stop_counting() -> None:
    """A skip outside the window is history, not a signal.

    Without the window, a member who missed one session in March is flagged
    forever and the roster's ordering stops meaning anything.
    """
    stale = [SessionOutcome(date=AS_OF - timedelta(days=40), completed=False)]
    recent = [SessionOutcome(date=AS_OF - timedelta(days=3), completed=False)]
    assert assess([], stale, None, AS_OF, PLANNED_PER_WEEK).signals == ()
    assert assess([], recent, None, AS_OF, PLANNED_PER_WEEK).signals[0].kind is ChurnSignalKind.RECENT_SKIP


def test_only_the_members_own_messages_count_as_contact() -> None:
    """A coach writing into silence is not contact.

    The caller passes the member's last message specifically. Counting coach
    messages would mask exactly the case this signal exists to catch — the
    member who has stopped replying while the coach keeps trying.
    """
    silent = assess([], [], AS_OF - timedelta(days=21), AS_OF, PLANNED_PER_WEEK)
    assert silent.signals[0].kind is ChurnSignalKind.CONTACT_GAP
    assert silent.signals[0].evidence["days_silent"] == 21.0

    recent = assess([], [], AS_OF - timedelta(days=2), AS_OF, PLANNED_PER_WEEK)
    assert recent.signals == ()


def test_levels_step_with_the_number_of_signals() -> None:
    """Counting, not weighting: none is low, one is moderate, two is elevated.

    Weights over three binary signals would imply a precision one synthetic
    member cannot support, and a coach reading "two signals" can check both.
    """
    none = assess(_weeks(100, 100), [], AS_OF, AS_OF, PLANNED_PER_WEEK)
    one = assess(_weeks(100, 40), [], AS_OF, AS_OF, PLANNED_PER_WEEK)
    two = assess(
        _weeks(100, 40),
        [SessionOutcome(date=AS_OF, completed=False)],
        AS_OF,
        AS_OF,
        PLANNED_PER_WEEK,
    )
    assert (none.level, one.level, two.level) == (
        ChurnLevel.LOW,
        ChurnLevel.MODERATE,
        ChurnLevel.ELEVATED,
    )


def test_a_member_with_no_record_is_not_at_risk() -> None:
    """Absence of data is not evidence of churn.

    A newly onboarded member has no weeks, no sessions and no messages. Scoring
    her as elevated would put every new member at the top of the roster.
    """
    result = assess([], [], None, AS_OF, PLANNED_PER_WEEK)
    assert result.level is ChurnLevel.LOW
    assert result.signals == ()


def test_every_signal_carries_its_figures() -> None:
    """Each reason ships the numbers behind it, for citation without re-derivation.

    The copilot quotes these. If a signal could arrive with an empty evidence
    bag, the answer would carry a claim with nothing to show for it.
    """
    result = assess(
        _weeks(100, 40),
        [SessionOutcome(date=AS_OF - timedelta(days=1), completed=False)],
        AS_OF - timedelta(days=30),
        AS_OF,
        PLANNED_PER_WEEK,
    )
    assert len(result.signals) == 3
    for signal in result.signals:
        assert signal.evidence, f"{signal.kind} carries no evidence"
        assert signal.reason.strip()
