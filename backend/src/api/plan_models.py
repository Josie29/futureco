from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from graph.schema import NodeLabel
from plan.schemas import Reason, Section
from resolve.resolver import Pass
from safety.evidence import EvidencePath, SignalKind

# Every model here mirrors a declaration in `web/src/types/index.ts`. The
# console is built against that file, so this module is a projection of the
# plan package onto it and holds no logic of its own — a difference between
# the two is a bug here, not a feature there.


class VerdictLabel(StrEnum):
    """How a movement fared, as the console renders it.

    Coarser than `Status`: the console needs to know whether to mark a block
    cautioned, not what the penalty totalled.
    """

    EXCLUDED = "excluded"
    CAUTION = "caution"
    CLEARED = "cleared"


class FilterCause(StrEnum):
    """The bucket a dropped movement is grouped under.

    Deliberately coarser than `ReasonKind` — a coach reads five groups, not
    twelve. `OUT_OF_SCOPE` has no `SignalKind` behind it and so is currently
    unreachable; it is declared to match the console rather than dropped,
    because the mapping is the console's contract and not ours to narrow.
    """

    INJURY = "injury"
    EQUIPMENT = "equipment"
    DISLIKE = "dislike"
    EXCLUSION = "exclusion"
    OUT_OF_SCOPE = "out_of_scope"


CAUSE_OF: dict[SignalKind, FilterCause] = {
    SignalKind.CONTRAINDICATION: FilterCause.INJURY,
    SignalKind.MISSING_EQUIPMENT: FilterCause.EQUIPMENT,
    SignalKind.DISLIKE: FilterCause.DISLIKE,
    SignalKind.COACH_EXCLUSION: FilterCause.EXCLUSION,
}


class ConceptIntent(StrEnum):
    """What a resolved phrase was meant to do to the catalog."""

    FOCUS = "focus"
    EXCLUDE = "exclude"
    PROTECT = "protect"


class MuscleTag(BaseModel):
    """A muscle a movement trains, flagged when a goal targets it."""

    name: str
    is_goal_target: bool


class PlanExercise(BaseModel):
    """One movement as scheduled, with everything needed to render and defend it."""

    id: str
    name: str
    block: Section
    sets: int | None
    reps: int | None
    duration_sec: int | None
    rest_sec: int | None
    per_side: bool
    minutes: float
    muscles: list[MuscleTag]
    equipment: list[str]
    verdict: VerdictLabel
    note: str | None
    why: list[Reason]


class FilteredExercise(BaseModel):
    """One movement the filter removed, and the traversal that removed it."""

    id: str
    name: str
    cause: FilterCause
    detail: str
    path: EvidencePath


class ResolvedConcept(BaseModel):
    """A phrase the resolver landed on a canonical concept."""

    phrase: str
    label: NodeLabel
    concept_id: str
    """`label:name`, matching the console's mock. Only `Exercise` is keyed by
    an id in the graph; everything else is keyed by name, so a synthetic
    composite is the one form that works for all of them."""

    concept_name: str
    pass_: Pass = Field(serialization_alias="pass")
    confidence: float
    intent: ConceptIntent
    side: str | None


class UnresolvedPhrase(BaseModel):
    """A phrase no pass reached above threshold.

    Rendering these is the graceful-degradation requirement
    (`ASSESSMENT.md:68`): the console names what it could not resolve and what
    it did instead, rather than letting a dropped instruction look applied.
    """

    phrase: str
    best_guess: str | None
    confidence: float
    threshold: float
    fallback: str


class TraceStage(BaseModel):
    """One named stage of the pipeline, and what it left behind."""

    label: str
    remaining: int
    detail: str


class PlanTrace(BaseModel):
    """The console's view of a run.

    A projection of `safety.trace.ProvenanceTrace`, not a replacement for it —
    that model stays the audit artifact, carrying the PROV-O header, the graph
    fingerprint and all fifty verdicts. This is the same run shaped for a
    coach and for the Traces tab.
    """

    run_id: str
    generated_at: datetime
    catalogue_total: int
    eligible: int
    prescribed: int
    stages: list[TraceStage]
    resolved: list[ResolvedConcept]
    unresolved: list[UnresolvedPhrase]
    filtered: list[FilteredExercise]


class PlanPayload(BaseModel):
    """A generated session, as the console consumes it."""

    run_id: str
    parent_run_id: str | None
    prompt: str
    title: str
    day_label: str
    requested_minutes: int
    estimated_minutes: float
    exercises: list[PlanExercise]
    trace: PlanTrace


class PlanRequest(BaseModel):
    """What the builder submits.

    `disabled` carries `ConstraintItem.id`s the coach switched off. It can
    never contain an injury: the server loads injuries from the member id, and
    `constraints.compose` refuses to drop one whatever this array says — the
    guarantee is in the type system rather than checked at the route.
    """

    prompt: str = ""
    duration_min: int = Field(default=50, ge=5, le=240)
    disabled: list[str] = Field(default_factory=list)


class Eligibility(BaseModel):
    """The live count behind the builder's "18 of 50"."""

    total: int
    available: int
    excluded_by: dict[FilterCause, int]
