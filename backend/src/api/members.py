import json
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from neo4j import Session
from pydantic import BaseModel, ConfigDict, Field

from api import member_queries as q
from api.churn import AdherenceWeek, ChurnAssessment, SessionOutcome, assess
from settings import settings

# An injury constrains only while it is live, the same rule `safety.filter`
# applies. Duplicated as a constant rather than imported: the safety module is
# another stream's, and a read model reaching into it to learn what "live" means
# would couple the console's header to the filter's internals.
LIVE_INJURY_STATUSES = ["active", "recovering"]

ADHERENCE_METRIC = "weekly_adherence"


class ConstraintKind(StrEnum):
    """Constraint classes shown in the builder. Mirrors the TypeScript enum."""

    INJURIES = "injuries"
    EQUIPMENT = "equipment"
    DISLIKES = "dislikes"
    GOAL_TARGETS = "goal_targets"


class ConstraintEffect(StrEnum):
    """Whether lifting a constraint changes the pool or only the ordering."""

    POOL = "pool"
    RANKING = "ranking"


class Coach(BaseModel):
    """A coach who can sign in."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str


class RosterEntry(BaseModel):
    """Roster-level metadata. Never clinical detail."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    initials: str
    has_context: bool
    """False for the synthetic filler members, which render an empty state."""

    last_session_on: str | None
    adherence_pct: float | None
    injury_label: str | None
    needs_attention: bool


class Injury(BaseModel):
    """One recorded injury, as the console shows it."""

    model_config = ConfigDict(frozen=True)

    id: str
    region: str
    joint: str
    status: str
    severity: str
    since: str
    notes: str
    condition: str


class GoalView(BaseModel):
    """A goal with its progress resolved.

    `days_left` and `measure` are alternatives, not a pair: a goal is either
    dated or measured. Both are derived here rather than in the console, which
    previously carried a hardcoded sleep target and a "no target date means
    measured" heuristic because the graph could not answer either.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    priority: int
    target_date: str | None
    targets: list[str]
    days_left: int | None
    measure: str | None
    shortfall: str | None


class SessionRecord(BaseModel):
    """One session on the record."""

    model_config = ConfigDict(frozen=True)

    date: str
    title: str
    completed: bool
    duration_min: int
    rpe: int | None


class ConstraintItem(BaseModel):
    """One switchable fact about the member."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    effect: str
    locked: bool


class Constraint(BaseModel):
    """One applied constraint class, with this member's specifics."""

    model_config = ConfigDict(frozen=True)

    kind: ConstraintKind
    label: str
    summary: str
    items: list[ConstraintItem]
    effect: ConstraintEffect


class ChurnRisk(BaseModel):
    """The wire shape the console renders. Derived, never retrieved."""

    model_config = ConfigDict(frozen=True)

    level: str
    reasons: list[str]


class MemberView(BaseModel):
    """Everything the member page needs, assembled from KG2."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    initials: str
    age: int
    tier: str
    member_since: str
    trains_at: str
    as_of: str
    """The date this dataset is read as "today".

    Returned so the console stops keeping its own copy. Every window in the
    system is relative to this; anchored on a wall clock, "this week" is empty
    and the record reads as though she stopped training in June."""

    goals: list[GoalView]
    preferred_session_min: int
    typical_session_min: int | None
    equipment_available: list[str]
    injuries: list[Injury]
    dislikes: list[str]
    recent_sessions: list[SessionRecord]
    adherence_pct: list[float]
    sessions_done_this_week: int
    sessions_planned_this_week: int
    churn_risk: ChurnRisk
    constraints: list[Constraint]


class ChatAttachment(BaseModel):
    """A file on a message. The sample carries no URL, so callers render the caption."""

    model_config = ConfigDict(frozen=True)

    type: str
    caption: str
    url: str | None = None


class MemberMessage(BaseModel):
    """One turn of the coach-member thread.

    Goes over the wire as `from`, matching both the source data's own key and
    the console's `CopilotMessage.from`. The field is `author` in Python because
    `from` is a keyword, so the alias is the only place the two names meet.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    ts: str
    author: str = Field(serialization_alias="from")
    text: str
    attachments: list[ChatAttachment] = []


def initials_of(name: str) -> str:
    """First letters of the first two words, uppercased."""
    return "".join(part[0] for part in name.split()[:2] if part).upper()


def _rows(session: Session, query: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(record) for record in session.run(query, **params)]


def _one(session: Session, query: str, **params: Any) -> dict[str, Any] | None:
    record = session.run(query, **params).single()
    return dict(record) if record else None


def coaches(session: Session) -> list[Coach]:
    """Every coach who can sign in."""
    return [Coach.model_validate(row) for row in _rows(session, q.COACHES)]


def coaches_member(session: Session, coach_id: str, member_id: str) -> bool:
    """Whether this coach is allowed to read this member.

    The `coaches` edge is the whole check. Mock auth is acceptable
    (ASSESSMENT.md:72), but it still has to mean something: holding a member id
    in a URL is not authority to read that member.
    """
    row = _one(session, q.COACHES_MEMBER, coach_id=coach_id, member_id=member_id)
    return bool(row and row["matched"])


def load_filler_roster(path: Path) -> list[RosterEntry]:
    """Read the synthetic roster filler.

    These carry roster metadata and no clinical detail, and are deliberately
    absent from the graph — as edgeless `Member` nodes they would be exactly
    what the grain rule rejects. Selecting one 404s.

    Args:
        path: Location of `roster.json`.

    Returns:
        Filler entries, each flagged `has_context=False`.
    """
    rows = json.loads(path.read_text())["members"]
    return [
        RosterEntry(
            id=row["id"],
            name=row["name"],
            initials=initials_of(row["name"]),
            has_context=False,
            last_session_on=row["last_session_on"],
            adherence_pct=row["adherence_pct"],
            injury_label=None,
            needs_attention=row["needs_attention"],
        )
        for row in rows
    ]


def roster(session: Session, coach_id: str) -> list[RosterEntry]:
    """The coach's roster, populated members first.

    Args:
        session: An open Neo4j session.
        coach_id: Whose roster to read.

    Returns:
        Members from the graph, then the synthetic filler, then sorted so the
        ones needing attention lead — which is the order a coach works in.
    """
    populated = [
        RosterEntry(
            id=row["id"],
            name=row["name"],
            initials=initials_of(row["name"]),
            has_context=True,
            last_session_on=row["last_session"],
            adherence_pct=row["adherence"][-1] if row["adherence"] else None,
            injury_label=row["injury_joint"],
            needs_attention=_churn(session, row["id"]).level != "low",
        )
        for row in _rows(session, q.ROSTER, coach_id=coach_id, live_statuses=LIVE_INJURY_STATUSES)
    ]
    entries = populated + load_filler_roster(settings.roster_path)
    return sorted(entries, key=lambda e: (not e.needs_attention, not e.has_context, e.name))


def _reference_date(session: Session, member_id: str) -> date:
    """The date this member's record is read as "today".

    Read from settings when set. Otherwise the most recent thing on her record,
    which for this dataset is the day her brief was generated for. Derived from
    the graph rather than re-reading the JSON, so the API does not need the
    source file to answer a question about the store.
    """
    if settings.as_of:
        return settings.as_of
    latest = _one(
        session,
        """
        MATCH (:Member {id: $member_id})-[:has]->(o:Observation)
        RETURN max(o.observed_on) AS latest
        """,
        member_id=member_id,
    )
    return date.fromisoformat(latest["latest"]) if latest and latest["latest"] else date.today()


def _churn(session: Session, member_id: str) -> ChurnAssessment:
    """Derive this member's churn reading from her record.

    Her planned sessions per week are part of it: weekly completion is already
    normalised against her own schedule, so turning a percentage-point fall back
    into a number of missed sessions needs to know what a full week is.
    """
    as_of = _reference_date(session, member_id)
    profile = _one(session, q.PROFILE, member_id=member_id)
    planned = int(profile["training_days_per_week"]) if profile else 0
    weeks = [
        AdherenceWeek(week_of=date.fromisoformat(row["observed_on"]), pct=row["value"])
        for row in _rows(session, q.OBSERVATIONS, member_id=member_id, metric_id=ADHERENCE_METRIC)
    ]
    sessions = [
        SessionOutcome(date=date.fromisoformat(row["date"]), completed=row["completed"])
        for row in _rows(session, q.SESSIONS, member_id=member_id)
    ]
    member_messages = [
        datetime.fromisoformat(row["ts"]).date()
        for row in _rows(session, q.MESSAGES, member_id=member_id)
        if row["author"] == "member"
    ]
    return assess(weeks, sessions, max(member_messages, default=None), as_of, planned)


def _format_number(value: float) -> str:
    """One decimal place, without a trailing `.0`."""
    return f"{value:.1f}".removesuffix(".0")


def _goal_view(row: dict[str, Any], as_of: date) -> GoalView:
    """Resolve one goal's progress.

    A dated goal counts down. A measured goal reports its own readings against
    the metric's band — which is the traversal `measured_by` exists for, and
    what replaced the console's hardcoded sleep target.
    """
    days_left = None
    if row["target_date"]:
        days_left = (date.fromisoformat(row["target_date"]) - as_of).days

    measure = shortfall = None
    readings, low, unit = row["readings"], row["metric_low"], row["metric_unit"]
    if readings:
        mean = sum(readings) / len(readings)
        measure = f"{_format_number(mean)} {unit} across {len(readings)} readings"
        if low is not None and mean < low:
            shortfall = f"{_format_number(low - mean)} {unit} short"

    return GoalView(
        id=row["id"],
        text=row["text"],
        priority=row["priority"],
        target_date=row["target_date"],
        targets=sorted(row["targets"]),
        days_left=days_left,
        measure=measure,
        shortfall=shortfall,
    )


def _injury_summary(session: Session, member_id: str) -> str:
    """Say what her live injuries actually rule out, from the clinical edges.

    Read rather than authored, so the sentence cannot drift from the rules. With
    no live injury there is nothing to describe, and the group renders empty.
    """
    by_relation = {
        row["relation"]: sorted(row["patterns"])
        for row in _rows(
            session, q.INJURY_RULES, member_id=member_id, live_statuses=LIVE_INJURY_STATUSES
        )
    }
    barred, flagged = by_relation.get("contraindicates", []), by_relation.get("cautions", [])
    clauses = []
    if barred:
        clauses.append(f"Rules out {', '.join(barred)} outright")
    if flagged:
        clauses.append(f"down-ranks {len(flagged)} more pattern{'s' if len(flagged) > 1 else ''}")
    if not clauses:
        return "No live injury on record."
    return " and ".join(clauses) + "."


def _constraints(
    session: Session,
    member_id: str,
    injuries: list[Injury],
    equipment: list[str],
    dislikes: list[str],
    goal_muscles: list[str],
) -> list[Constraint]:
    """The four constraint groups, with this member's specifics.

    Injury items are `locked`. The client strips injury ids from `disabled[]`
    and the plan endpoint has to as well — a lock rendered in the UI and not
    enforced server-side is decoration.
    """
    item_id = lambda kind, label: f"{kind}:{label}"  # noqa: E731 - matches the TS `itemId`

    return [
        Constraint(
            kind=ConstraintKind.INJURIES,
            label="Injuries",
            summary=_injury_summary(session, member_id),
            effect=ConstraintEffect.POOL,
            items=[
                ConstraintItem(
                    id=item_id(ConstraintKind.INJURIES, injury.region),
                    label=f"{injury.region} — {injury.status}, {injury.severity}",
                    effect="Always applied. A request cannot waive a clinical constraint.",
                    locked=True,
                )
                for injury in injuries
            ],
        ),
        Constraint(
            kind=ConstraintKind.EQUIPMENT,
            label="Equipment she has",
            summary="Only movements she can actually load are offered.",
            effect=ConstraintEffect.POOL,
            items=[
                ConstraintItem(
                    id=item_id(ConstraintKind.EQUIPMENT, name),
                    label=name,
                    effect="Switch off if she hasn't got it today.",
                    locked=False,
                )
                for name in equipment
            ],
        ),
        Constraint(
            kind=ConstraintKind.DISLIKES,
            label="Movements she dislikes",
            summary="Avoided where there's an alternative, never banned outright.",
            effect=ConstraintEffect.RANKING,
            items=[
                ConstraintItem(
                    id=item_id(ConstraintKind.DISLIKES, name),
                    label=name,
                    effect="Switch off to let this one back into the running.",
                    locked=False,
                )
                for name in dislikes
            ],
        ),
        Constraint(
            kind=ConstraintKind.GOAL_TARGETS,
            label="What her goals train",
            summary="Movements hitting these are preferred when there's a choice.",
            effect=ConstraintEffect.RANKING,
            items=[
                ConstraintItem(
                    id=item_id(ConstraintKind.GOAL_TARGETS, name),
                    label=name,
                    effect="Switch off to stop favouring this today.",
                    locked=False,
                )
                for name in goal_muscles
            ],
        ),
    ]


def member(session: Session, member_id: str) -> MemberView | None:
    """Assemble one member's page from the graph.

    Args:
        session: An open Neo4j session.
        member_id: Whose context to read.

    Returns:
        The assembled view, or None when the graph holds no such member — which
        is the roster's filler entries, and is a 404 rather than an empty page.
    """
    profile = _one(session, q.PROFILE, member_id=member_id)
    if profile is None:
        return None

    as_of = _reference_date(session, member_id)
    goals = [_goal_view(row, as_of) for row in _rows(session, q.GOALS, member_id=member_id)]
    equipment = [row["name"] for row in _rows(session, q.EQUIPMENT, member_id=member_id)]
    dislikes = [row["name"] for row in _rows(session, q.DISLIKES, member_id=member_id)]
    injuries = [Injury.model_validate(row) for row in _rows(session, q.INJURIES, member_id=member_id)]
    sessions = [
        SessionRecord.model_validate(row) for row in _rows(session, q.SESSIONS, member_id=member_id)
    ]
    adherence = _rows(session, q.OBSERVATIONS, member_id=member_id, metric_id=ADHERENCE_METRIC)

    completed = [s for s in sessions if s.completed]
    typical = round(sum(s.duration_min for s in completed) / len(completed)) if completed else None

    # "This week" means the week the adherence series is currently reporting on.
    # The series keys its own weeks, so reading the boundary off the latest
    # entry keeps the header and the sparkline describing the same seven days
    # rather than imposing a calendar rule the data does not follow.
    week_start = adherence[-1]["observed_on"] if adherence else None
    done_this_week = sum(1 for s in completed if week_start and s.date >= week_start)

    churn = _churn(session, member_id)
    goal_muscles = sorted({muscle for goal in goals for muscle in goal.targets})

    return MemberView(
        id=profile["id"],
        name=profile["name"],
        initials=initials_of(profile["name"]),
        age=profile["age"],
        tier=profile["tier"],
        member_since=profile["member_since"],
        trains_at=profile["trains_at"],
        as_of=as_of.isoformat(),
        goals=goals,
        preferred_session_min=profile["preferred_session_minutes"],
        typical_session_min=typical,
        equipment_available=equipment,
        injuries=injuries,
        dislikes=dislikes,
        recent_sessions=sessions,
        adherence_pct=[row["value"] for row in adherence],
        sessions_done_this_week=done_this_week,
        sessions_planned_this_week=profile["training_days_per_week"],
        churn_risk=ChurnRisk(level=churn.level.value, reasons=churn.reasons),
        constraints=_constraints(
            session, member_id, injuries, equipment, dislikes, goal_muscles
        ),
    )


def messages(session: Session, member_id: str) -> list[MemberMessage]:
    """The coach-member thread, oldest first.

    Attachments are stored as parallel arrays because Neo4j properties hold
    primitives, so they are zipped back into objects here.
    """
    return [
        MemberMessage(
            id=row["id"],
            ts=row["ts"],
            author=row["author"],
            text=row["text"],
            attachments=[
                ChatAttachment(type=kind, caption=caption)
                for kind, caption in zip(
                    row["attachment_types"] or [], row["attachment_captions"] or [], strict=True
                )
            ],
        )
        for row in _rows(session, q.MESSAGES, member_id=member_id)
    ]
