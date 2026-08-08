from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from safety.filter import Attribution


class Section(StrEnum):
    """Where in a session a block belongs.

    Values match `PlanBlock` in `web/src/types/index.ts`, so the wire shape
    needs no translation table.
    """

    WARMUP = "warmup"
    MAIN = "main"
    COOLDOWN = "cooldown"


class Modality(StrEnum):
    """Which rep range an exercise is counted against.

    Only rep ranges: whether an exercise is held rather than counted comes
    from the catalog's `is_reps`, per exercise, so there is no isometric
    modality. A held exercise takes its duration from the section instead.
    """

    STRENGTH = "strength"
    CONDITIONING = "conditioning"
    MOBILITY = "mobility"


class Slot(StrEnum):
    """The coverage bucket a main-block exercise fills.

    Coarser than a movement pattern on purpose: 36 patterns over 50 exercises
    is too fine to balance a session against, and the packer needs to know it
    has programmed a push and a hinge, not that it has programmed
    `upper push - horizontal`.
    """

    LOWER = "lower"
    UPPER_PUSH = "upper_push"
    UPPER_PULL = "upper_pull"
    CORE = "core"
    ARMS = "arms"
    CONDITIONING = "conditioning"
    MOBILITY = "mobility"


class FamilyRole(BaseModel):
    """What one movement-pattern family implies about programming."""

    model_config = ConfigDict(frozen=True)

    section: Section
    modality: Modality
    slot: Slot


class MovementFacts(BaseModel):
    """The catalog fields the packer needs, read back from the Exercise node.

    The graph stays the source of truth — `kg1` writes the whole catalog row
    onto the node, so nothing here re-reads `exercises.json`.
    """

    model_config = ConfigDict(frozen=True)

    exercise_id: str
    patterns: tuple[str, ...]
    rep_seconds: float
    is_reps: bool
    side: str | None = None

    @property
    def per_side(self) -> bool:
        """Whether the exercise trains one side at a time.

        Read from `side`, never from `is_bilateral`: that field is inverted in
        this data — true on exactly the single-side rows — and
        `docs/decisions.md`, Data cleanup 4, leaves the fix to its own change.
        `side` carries the same fact under a name that is not lying, and it
        survives that fix untouched.
        """
        return self.side is not None

    @property
    def is_held(self) -> bool:
        """Whether the exercise is held for time rather than counted in reps.

        Either marker is enough. Seven rows carry `0` seconds and eight are
        `is_reps: false`, so zero implies a hold but a hold does not imply
        zero — `Kneeling Stability Ball Lat Stretch` is 5.0 and not counted.
        Taking either is the reading that never prescribes reps of a stretch.
        """
        return not self.is_reps or self.rep_seconds <= 0


class Prescription(BaseModel):
    """Sets, reps or hold, and rest for one exercise in one section.

    Every field is derived from the authored section and modality tables plus
    the catalog's `estimated_rep_seconds`; nothing is invented per exercise.
    Seconds are whole numbers so block arithmetic is exact and tests never
    compare floats.
    """

    model_config = ConfigDict(frozen=True)

    sets: int
    reps: int | None
    """None when the exercise is held for time rather than counted."""

    hold_seconds: int | None
    """None when the exercise is counted in reps rather than held."""

    rest_seconds: int
    per_side: bool
    """Whether the exercise trains one side at a time. Read from the catalog's
    `side`, never from `is_bilateral`, which is inverted in this data."""

    work_seconds: int
    """Work in one set, already doubled when `per_side`."""

    reps_clamped: bool
    """True when the modality's rep range overruled `estimated_rep_seconds`.
    This binds on well over half the catalog, so it is reported rather than
    assumed rare — see `decisions.md`, *Packing*."""

    @property
    def total_seconds(self) -> int:
        """Wall-clock cost, counting rest after every set including the last.

        The final rest doubles as the transition to the next exercise, so one
        rule covers both and block times stay additive.
        """
        return self.sets * (self.work_seconds + self.rest_seconds)

    def render(self) -> str:
        """`3 x 14 each side` or `2 x 45s hold`, for a coach reading the plan."""
        load = f"{self.hold_seconds}s hold" if self.reps is None else str(self.reps)
        side = " each side" if self.per_side else ""
        return f"{self.sets} x {load}{side}"


class Block(BaseModel):
    """One exercise as scheduled, with the verdict that admitted it."""

    model_config = ConfigDict(frozen=True)

    exercise_id: str
    name: str
    section: Section
    slot: Slot
    modality: Modality
    prescription: Prescription
    order: int
    """Position within the section, after sequencing."""

    penalty: int
    fit: int
    headline: str
    """Copied verbatim from the verdict. Nothing is regenerated here, so the
    plan inherits the filter's zero-hallucination property."""

    anchored: bool = False
    """Selected ahead of better-ranked exercises because it serves a
    top-priority goal. Recorded so the promotion is legible rather than a
    silent exception to the ranking."""


class ShortfallKind(StrEnum):
    """A way the plan is less than the request asked for."""

    EMPTY_SECTION = "empty_section"
    SECTION_UNDERFILLED = "section_underfilled"
    SECTION_TRIMMED = "section_trimmed"
    SLOT_ABSENT = "slot_absent"
    NO_GOAL_SERVING_BLOCK = "no_goal_serving_block"
    PACE_IMPLAUSIBLE = "pace_implausible"
    UNPLACEABLE_EXERCISE = "unplaceable_exercise"


class Shortfall(BaseModel):
    """Something the packer could not do, and why.

    A plan that quietly runs seventeen minutes short, or quietly contains no
    pulling work, is worse than one that says so. Every gap between the request
    and the schedule appears here rather than being absorbed.
    """

    model_config = ConfigDict(frozen=True)

    kind: ShortfallKind
    detail: str
    section: Section | None = None
    slot: Slot | None = None
    seconds: int = 0
    cause: str | None = None
    """`FilterResult.costliest_constraint` where the eligible pool is the
    reason, so a gap points at the constraint that caused it."""


class TimeBudget(BaseModel):
    """What was asked for, what each section was allotted, what was scheduled."""

    model_config = ConfigDict(frozen=True)

    requested_seconds: int
    warmup_seconds: int
    main_seconds: int
    cooldown_seconds: int
    scheduled_seconds: int

    def allotted(self, section: Section) -> int:
        """Seconds this section was given to fill."""
        return {
            Section.WARMUP: self.warmup_seconds,
            Section.MAIN: self.main_seconds,
            Section.COOLDOWN: self.cooldown_seconds,
        }[section]

    @property
    def unscheduled_seconds(self) -> int:
        """Requested time no block occupies. Reported, never padded away."""
        return max(0, self.requested_seconds - self.scheduled_seconds)

    @property
    def fill_ratio(self) -> float:
        """Fraction of the requested window actually scheduled."""
        if not self.requested_seconds:
            return 0.0
        return self.scheduled_seconds / self.requested_seconds


class WorkoutPlan(BaseModel):
    """A timed session, and everything it could not do.

    A pure function of the eligible verdicts, the movement facts, the requested
    window and the authored tables. No clock, no randomness, and no database
    beyond the facts already read — two runs over the same graph are identical,
    which is what makes the provenance trace worth reading.
    """

    model_config = ConfigDict(frozen=True)

    member_id: str
    budget: TimeBudget
    blocks: tuple[Block, ...]
    shortfalls: tuple[Shortfall, ...]
    notes: tuple[str, ...] = ()
    eligible_count: int
    attribution: Attribution
    """Carried from the `FilterResult` so a thin plan can explain its own
    thinness without embedding all fifty verdicts."""

    def section(self, section: Section) -> tuple[Block, ...]:
        """Blocks in one section, in schedule order."""
        return tuple(block for block in self.blocks if block.section is section)

    @property
    def serves_a_goal(self) -> bool:
        """Whether any scheduled block serves a stated goal."""
        return any(block.fit > 0 for block in self.blocks)
