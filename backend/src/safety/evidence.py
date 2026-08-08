from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel, RelType


class SignalKind(StrEnum):
    """A reason the graph gives for treating one exercise differently.

    Whether a kind excludes or merely penalises is `policy`'s decision, not a
    property of the signal — the same evidence can be weighted differently
    without the traversal changing.
    """

    CONTRAINDICATION = "contraindication"
    MISSING_EQUIPMENT = "missing_equipment"
    DISLIKE = "dislike"
    COACH_EXCLUSION = "coach_exclusion"
    CAUTION = "caution"
    FLAGGED_STRUCTURE = "flagged_structure"


class Hop(BaseModel):
    """One step of the traversal that produced a signal."""

    model_config = ConfigDict(frozen=True)

    rel: RelType
    to_label: NodeLabel
    to_name: str

    def render(self) -> str:
        """Render as `-rel-> Name`, for a reviewer reading the path."""
        return f"-{self.rel}-> {self.to_name}"


class EvidencePath(BaseModel):
    """Where a signal came from, as the path actually walked.

    PROV-O alignment: this is the `used` entity chain of the activity that
    produced a verdict.
    """

    model_config = ConfigDict(frozen=True)

    entry: str
    hops: tuple[Hop, ...] = ()

    def render(self) -> str:
        """Render the whole path on one line."""
        return " ".join([self.entry, *(hop.render() for hop in self.hops)])


class Signal(BaseModel):
    """One piece of evidence about one exercise.

    Attributes:
        kind: Which rule produced it.
        detail: The authored rationale where one exists, otherwise the specific
            fact — a missing equipment name, a flagged structure.
        path: The traversal that found it.
        annotation: Context that explains but does not score. This is the only
            place `affects` appears: it names the injury recorded at a flagged
            joint without changing any weight.
    """

    model_config = ConfigDict(frozen=True)

    kind: SignalKind
    detail: str
    path: EvidencePath
    annotation: str | None = None


class ExerciseEvidence(BaseModel):
    """Everything the graph returned about one exercise, before judgement.

    Assembled for all 50 exercises, not just the survivors, so a coach can ask
    why something is absent and get an answer.
    """

    model_config = ConfigDict(frozen=True)

    exercise_id: str
    name: str
    signals: tuple[Signal, ...] = ()

    goal_muscles: tuple[str, ...] = ()
    """Muscles this exercise trains that some goal of the member's targets."""

    goal_priorities: tuple[int, ...] = ()
    """One entry per *goal* served, not per shared muscle. An exercise hitting
    two muscles of one goal serves that goal once."""

    supports_weight: bool = False

    def of(self, kind: SignalKind) -> tuple[Signal, ...]:
        """Every signal of one kind."""
        return tuple(signal for signal in self.signals if signal.kind is kind)
