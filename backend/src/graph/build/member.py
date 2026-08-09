import json
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from settings import settings


class InjuryStatus(StrEnum):
    """Where an injury sits in its recovery, which gates how hard it filters."""

    ACTIVE = "active"
    RECOVERING = "recovering"
    RESOLVED = "resolved"


class InjurySeverity(StrEnum):
    """Clinical severity, used to weight a caution rather than to exclude."""

    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class Injury(BaseModel):
    """One entry of `injuries[]`.

    Read by KG1, not KG2: the injury is where clinical filtering starts, so it
    lives in the movement graph even though the member's chart is what records
    it. `condition` is an explicit structured field standing in for extraction
    from the free-text `notes` — see `docs/decisions.md`, *Data cleanup*.
    """

    id: str
    region: str
    joint: str
    status: InjuryStatus
    severity: InjurySeverity
    since: date
    notes: str
    condition: str

    @property
    def side(self) -> str | None:
        """Laterality, as the part of `region` that is not the joint.

        `region: "left knee"` against `joint: "knee"` gives `"left"`; an
        unlateralised region gives None.
        """
        return self.region.replace(self.joint, "").strip() or None


class Goal(BaseModel):
    """One entry of `goals[]`.

    `targets` names muscles from KG1's vocabulary. It may be empty — not every
    goal is muscular (*"Average 7+ hours of sleep"*), and an empty list is a
    valid goal rather than a resolution failure.

    `metric` is the other half of that: the goal with no muscles is the one with
    a number, and without it `goal_sleep` is the single goal the graph can say
    nothing about. It names a metric id from `data/authored/metrics.json`, so
    `Goal -measured_by-> Metric <-measures- Observation` makes progress a
    traversal. Added to the data as an explicit field for the same reason
    `targets` and `injuries[].condition` were — built out, all three would be
    LLM extraction from the goal text at ingest.
    """

    id: str
    text: str
    priority: int
    target_date: date | None
    targets: list[str]
    metric: str | None = None


class Member(BaseModel):
    """The `profile` block — who the member is.

    `weight_kg` duplicates `biomarkers.weight_trend_kg`, which holds the same
    fact as a dated series. Two sources for one number is how they drift, so the
    latest observation becomes the answer and this property is dropped from the
    node once the observation build lands. Still copied today, because nothing
    else can report her weight yet.
    """

    id: str
    name: str
    age: int
    sex: str
    height_cm: int
    weight_kg: float
    timezone: str
    member_since: date
    coach_id: str
    tier: str
    trains_at: str = "home"


class Preferences(BaseModel):
    """The `preferences` block.

    Typed rather than a `dict[str, Any]` because the copilot reads four of these
    five fields by name, and a string key it can mistype is a worse contract
    than a field. Only `dislikes` becomes edges; the rest land as `Member`
    properties, which is what `docs/decisions.md` KG2 item 2 said they would if
    anything ever wanted them. Something does now.
    """

    preferred_session_minutes: int
    training_days_per_week: int
    preferred_days: list[str] = []
    dislikes: list[str] = []
    notes: str = ""


class MessageAuthor(StrEnum):
    """Who wrote a chat message.

    Two values, not three: the copilot's own turns are not member context and
    never enter this thread. See `web/src/features/copilot/CopilotDock.tsx`.
    """

    MEMBER = "member"
    COACH = "coach"


class Attachment(BaseModel):
    """A file on a chat message.

    The sample carries `type` and `caption` and no URL, so a consumer renders
    the caption rather than an image that would 404.
    """

    type: str
    caption: str
    url: str | None = None


class ChatMessage(BaseModel):
    """One entry of `chat_history[]`.

    Named `ChatMessage` rather than `Message` because the modules that build it
    also hold a `neo4j.Session`, and one confusable pair of names in a build
    file is enough.
    """

    ts: datetime
    author: MessageAuthor = Field(alias="from")
    text: str
    attachments: list[Attachment] = []

    @property
    def id(self) -> str:
        """Stable identifier, derived from the instant the message was sent.

        Normalised to UTC first, so two messages written in different offsets
        cannot collide or sort oddly. Derived rather than positional because a
        citation naming `msg_3` would silently point at a different message the
        moment an older one is added to the record.
        """
        return f"msg_{self.ts.astimezone(UTC):%Y%m%dT%H%M%S}Z"


class WorkoutSession(BaseModel):
    """One entry of `workout_history[]`.

    `exercises` holds what the coach wrote, which is *not* catalog vocabulary —
    none of the nine names in the sample matches an `Exercise` node, not even as
    a substring. `data/authored/session_patterns.json` maps them onto the
    movement patterns they belong to, which is the grain the catalog's own
    taxonomy shares. See `docs/decisions.md`, KG2.
    """

    date: date
    title: str
    planned: bool
    completed: bool
    duration_min: int
    rpe: int | None
    exercises: list[str] = []

    @property
    def id(self) -> str:
        """Stable identifier. One session per day in this dataset."""
        return f"ses_{self.date:%Y%m%d}"


class AdherenceWeek(BaseModel):
    """One week's completion percentage, against her own planned sessions."""

    week_of: date
    pct: float


class Adherence(BaseModel):
    """The `adherence` block.

    `trend` is a label the file carries and the graph does not store: it is
    derivable from `weekly_completion_pct`, and a stored summary that disagrees
    with its own series is worse than no summary.
    """

    weekly_completion_pct: list[AdherenceWeek] = []
    trend: str | None = None


class WeightPoint(BaseModel):
    """One dated weight reading."""

    date: date
    kg: float


class Biomarkers(BaseModel):
    """The `biomarkers` block.

    `resting_hr_bpm` and `hrv_ms` are bare scalars where every sibling is dated.
    They are stamped with the reference date at build time; see
    `graph/build/metrics.py`.
    """

    resting_hr_bpm: float | None = None
    hrv_ms: float | None = None
    sleep_hours_last_7_days: list[float] = []
    weight_trend_kg: list[WeightPoint] = []


class BloodPanel(BaseModel):
    """The `labs.blood_panel` block — one date, seven values."""

    date: date
    ldl_mg_dl: float | None = None
    hdl_mg_dl: float | None = None
    triglycerides_mg_dl: float | None = None
    hba1c_pct: float | None = None
    vitamin_d_ng_ml: float | None = None
    ferritin_ng_ml: float | None = None
    crp_mg_l: float | None = None


class DexaScan(BaseModel):
    """The `labs.dexa_scan` block — one date, five values."""

    date: date
    body_fat_pct: float | None = None
    lean_mass_kg: float | None = None
    fat_mass_kg: float | None = None
    bone_density_z_score: float | None = None
    visceral_fat_cm2: float | None = None


class Labs(BaseModel):
    """The `labs` block. Both panels are optional — a member may have neither."""

    blood_panel: BloodPanel | None = None
    dexa_scan: DexaScan | None = None


class MorningTask(BaseModel):
    """One item of `coach_brief.morning_tasks[]`."""

    type: str
    text: str


class ChurnRisk(BaseModel):
    """The `coach_brief.churn_risk` block."""

    level: str
    reasons: list[str] = []


class CoachBrief(BaseModel):
    """The `coach_brief` block — read, but deliberately not built into KG2.

    This is generated output dated `generated_for`, not member context: it is
    yesterday's answer. A copilot that retrieves a stored conclusion is echoing
    rather than reasoning, so today's brief and churn assessment are derived
    from the graph instead.

    It is still modelled for two reasons. `generated_for` is the reference date
    the whole dataset is relative to — nothing here is "this week" against a
    wall clock. And `churn_risk` is the calibration target: the derivation is
    checked against it, which is how the sample's third reason ("login frequency
    down") was found to have no supporting data anywhere in the file.
    """

    generated_for: date
    morning_tasks: list[MorningTask] = []
    churn_risk: ChurnRisk | None = None


class MemberContext(BaseModel):
    """The whole of `member-context.json`, validated.

    Every block is modelled now. What differs is the grain each lands at in the
    graph — a traversed entity, a leaf observation, or a node property — which
    is decided by whether anything points at it rather than by which block it
    came from. `docs/kg2-schema.md` records the mapping.
    """

    profile: Member
    goals: list[Goal]
    preferences: Preferences
    equipment_available: list[str]
    injuries: list[Injury]
    workout_history: list[WorkoutSession] = []
    adherence: Adherence = Adherence()
    biomarkers: Biomarkers = Biomarkers()
    labs: Labs = Labs()
    chat_history: list[ChatMessage] = []
    coach_brief: CoachBrief | None = None

    @property
    def messages_oldest_first(self) -> list[ChatMessage]:
        """Chat in reading order. The file stores it newest-first."""
        return sorted(self.chat_history, key=lambda m: m.ts)


def reference_date(context: MemberContext) -> date:
    """The date this dataset is read as "today".

    Every window in the system — "this week", "the last seven nights", "since
    the flare-up" — is relative to this rather than to a wall clock. The sample
    member's record ends in June 2026, so anchoring on the real date would empty
    every window and have the copilot report that she has stopped training.

    Args:
        context: The member's validated context.

    Returns:
        `settings.as_of` when set, otherwise the date her brief was generated
        for, otherwise today. The last case is the one a second member with no
        brief would take.
    """
    if settings.as_of:
        return settings.as_of
    if context.coach_brief:
        return context.coach_brief.generated_for
    return date.today()


def load_member_context(path: Path) -> MemberContext:
    """Read and validate the member's context.

    Args:
        path: Location of `member-context.json`.

    Returns:
        The validated context.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If any block is malformed.
    """
    return MemberContext.model_validate(json.loads(path.read_text()))
