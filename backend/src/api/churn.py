from datetime import date, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

# Thresholds are authored, not learned: one member is not a training set, and a
# fitted number here would be a coincidence wearing a lab coat. Each is chosen
# so the signal fires on a change a coach would act on, and each is named so a
# reviewer can disagree with the number rather than with the code.

DECLINE_SESSIONS = 1.0
"""How many planned sessions' worth of decline before it counts.

Expressed in *sessions*, not percentage points, because the two are only the
same number for one particular plan. Weekly completion is already normalised
against the member's own schedule, so on Jordan's four-session week one missed
session is worth 25 points — while a member training twice a week loses 50 for
the same slip. A fixed point threshold would mean "one session" for her and
"half a session" for the other, and would fire on the first bad week either way.

The bar is *more than* this, so a single missed session never signals on its
own: one slip is life, two is a pattern. Jordan's 50-point fall is two of her
sessions and clears it."""

MIN_WEEKS = 2
"""Weeks of history before a decline can be read at all."""

SKIP_WINDOW_DAYS = 14
"""How recently a planned-but-skipped session still signals.

A skip six weeks ago that was followed by full weeks is history. The window is
two weeks because that is roughly two of her four-session cycles."""

SILENCE_DAYS = 7
"""Days without a member message before contact counts as dropped off.

Her thread runs weekly or better, so a fortnight of silence is a real change.
This is the signal the sample's own brief gestures at with "login frequency
down" — which nothing in the file supports, so this measures the thing the data
actually holds."""


class ChurnLevel(StrEnum):
    """How much attention this member needs, from the signals that fired."""

    LOW = "low"
    MODERATE = "moderate"
    ELEVATED = "elevated"


class ChurnSignalKind(StrEnum):
    """Which derivation produced a signal."""

    ADHERENCE_DECLINE = "adherence_decline"
    RECENT_SKIP = "recent_skip"
    CONTACT_GAP = "contact_gap"


class ChurnSignal(BaseModel):
    """One reason to be concerned, and the facts that produced it.

    `evidence` is separate from `reason` so the copilot can cite figures without
    re-deriving them, and so a coach reading the sentence can be shown the
    numbers behind it rather than being asked to trust the sentence.
    """

    model_config = ConfigDict(frozen=True)

    kind: ChurnSignalKind
    reason: str
    evidence: dict[str, float | str]


class ChurnAssessment(BaseModel):
    """Today's churn reading, derived rather than retrieved.

    `coach_brief.churn_risk` in the sample data is *yesterday's* conclusion. It
    is used to calibrate this and never as an input: a copilot that reads a
    stored answer is echoing, not reasoning. Where the two differ, the
    difference is the finding — the sample's third stored reason, "login
    frequency down vs. prior month", has no supporting data anywhere in the
    file, and nothing here can invent it.
    """

    model_config = ConfigDict(frozen=True)

    level: ChurnLevel
    signals: tuple[ChurnSignal, ...] = ()
    as_of: date

    @property
    def reasons(self) -> list[str]:
        """The signal sentences, for the wire contract the console renders."""
        return [signal.reason for signal in self.signals]


class AdherenceWeek(BaseModel):
    """One weekly completion reading, as the graph returns it."""

    model_config = ConfigDict(frozen=True)

    week_of: date
    pct: float


class SessionOutcome(BaseModel):
    """One session, reduced to what churn cares about."""

    model_config = ConfigDict(frozen=True)

    date: date
    completed: bool


def _adherence_signal(weeks: list[AdherenceWeek], planned_per_week: int) -> ChurnSignal | None:
    """Compare the latest weekly completion against the best week on record.

    Against the peak rather than the first week, so a series that climbs and
    then falls still registers. Comparing to the first week only would score
    50, 100, 50 as no change at all.

    Args:
        weeks: Weekly completion readings, in any order.
        planned_per_week: Sessions the member is scheduled for, which is what
            turns a percentage-point drop into a number of missed sessions.

    Returns:
        The signal, or None when there is too little history or the fall is
        within one session's worth.
    """
    if len(weeks) < MIN_WEEKS or planned_per_week <= 0:
        return None

    ordered = sorted(weeks, key=lambda week: week.week_of)
    peak = max(week.pct for week in ordered)
    latest = ordered[-1]
    drop = peak - latest.pct

    points_per_session = 100.0 / planned_per_week
    sessions_lost = drop / points_per_session
    if sessions_lost <= DECLINE_SESSIONS:
        return None

    return ChurnSignal(
        kind=ChurnSignalKind.ADHERENCE_DECLINE,
        reason=(
            f"Weekly completion is down {drop:.0f} points, from {peak:.0f}% "
            f"to {latest.pct:.0f}% in the week of {latest.week_of:%-d %b} — "
            f"about {sessions_lost:.0f} sessions a week"
        ),
        evidence={
            "peak_pct": peak,
            "latest_pct": latest.pct,
            "drop_points": drop,
            "sessions_lost": round(sessions_lost, 2),
            "planned_per_week": float(planned_per_week),
            "latest_week_of": latest.week_of.isoformat(),
        },
    )


def _skip_signal(sessions: list[SessionOutcome], as_of: date) -> ChurnSignal | None:
    """Find planned sessions inside the window that were not completed."""
    cutoff = as_of - timedelta(days=SKIP_WINDOW_DAYS)
    skipped = sorted(
        (s for s in sessions if not s.completed and cutoff <= s.date <= as_of),
        key=lambda s: s.date,
    )
    if not skipped:
        return None

    latest = skipped[-1]
    plural = "s" if len(skipped) > 1 else ""
    return ChurnSignal(
        kind=ChurnSignalKind.RECENT_SKIP,
        reason=(
            f"{len(skipped)} planned session{plural} missed in the last "
            f"{SKIP_WINDOW_DAYS} days, most recently on {latest.date:%-d %b}"
        ),
        evidence={
            "skipped": float(len(skipped)),
            "window_days": float(SKIP_WINDOW_DAYS),
            "most_recent": latest.date.isoformat(),
        },
    )


def _contact_signal(last_member_message: date | None, as_of: date) -> ChurnSignal | None:
    """Measure silence since the member last wrote.

    Only the member's own messages count. A coach writing into silence is not
    contact — if anything it is the opposite, and counting it would mask the
    exact case this is meant to catch.
    """
    if last_member_message is None:
        return None

    days = (as_of - last_member_message).days
    if days <= SILENCE_DAYS:
        return None

    return ChurnSignal(
        kind=ChurnSignalKind.CONTACT_GAP,
        reason=(
            f"No message from her in {days} days, since {last_member_message:%-d %b}"
        ),
        evidence={"days_silent": float(days), "last_message_on": last_member_message.isoformat()},
    )


def assess(
    weeks: list[AdherenceWeek],
    sessions: list[SessionOutcome],
    last_member_message: date | None,
    as_of: date,
    planned_per_week: int = 0,
) -> ChurnAssessment:
    """Derive churn risk from what the member's record actually shows.

    Three independent signals, counted rather than weighted: two or more is
    `ELEVATED`, one is `MODERATE`, none is `LOW`. Counting rather than scoring
    because weights over three binary signals would imply a precision that one
    synthetic member cannot support, and because a coach reading "two signals"
    can check both.

    Args:
        weeks: Weekly completion readings.
        sessions: Sessions on the record, completed or not.
        last_member_message: When the member last wrote, or None if never.
        as_of: The date the dataset is read as "today".
        planned_per_week: Sessions the member is scheduled for. Zero disables
            the adherence signal rather than guessing a schedule — a decline
            cannot be sized without knowing what a full week is.

    Returns:
        The level, and one signal per concern with the figures behind it.
    """
    signals = tuple(
        signal
        for signal in (
            _adherence_signal(weeks, planned_per_week),
            _skip_signal(sessions, as_of),
            _contact_signal(last_member_message, as_of),
        )
        if signal is not None
    )

    if len(signals) >= 2:
        level = ChurnLevel.ELEVATED
    elif signals:
        level = ChurnLevel.MODERATE
    else:
        level = ChurnLevel.LOW

    return ChurnAssessment(level=level, signals=signals, as_of=as_of)
