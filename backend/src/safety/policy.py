from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from safety.evidence import ExerciseEvidence, Signal, SignalKind

# Signal kinds that remove an exercise from consideration outright. Membership
# in this set is the *only* route to EXCLUDED — no penalty total, however
# large, can put an exercise here, which `test_safety_policy` asserts.
EXCLUDING: frozenset[SignalKind] = frozenset(
    {
        SignalKind.CONTRAINDICATION,
        SignalKind.MISSING_EQUIPMENT,
        SignalKind.DISLIKE,
        SignalKind.COACH_EXCLUSION,
    }
)

# Precedence for attributing a removal to one cause when several apply, so the
# attributed counts sum to the number of exercises actually removed. Clinical
# first because it is the one a coach most needs to know about.
ATTRIBUTION_ORDER: tuple[SignalKind, ...] = (
    SignalKind.CONTRAINDICATION,
    SignalKind.MISSING_EQUIPMENT,
    SignalKind.DISLIKE,
    SignalKind.COACH_EXCLUSION,
)


class Status(StrEnum):
    """Whether an exercise may be programmed at all.

    Set membership, not a threshold. `PENALIZED` still means eligible.
    """

    EXCLUDED = "excluded"
    PENALIZED = "penalized"
    CLEAR = "clear"


_STATUS_RANK: dict[Status, int] = {Status.CLEAR: 0, Status.PENALIZED: 1, Status.EXCLUDED: 2}


class Policy(BaseModel):
    """The weights, with the reason each carries the value it does.

    Frozen and injectable so a test can vary one weight without editing code,
    and so the trace can record which policy produced a verdict.
    """

    model_config = ConfigDict(frozen=True)

    caution: int = 3
    """A clinician's judgement about a specific movement, quoted verbatim in
    the trace. Outranks anatomy because it is authored rather than inferred."""

    flagged_structure: int = 2
    """The exercise loads something the coach named. Mechanical inference: the
    graph knows the exercise touches that joint, not whether that is harmful."""

    top_goal: int = 2
    """Credit for serving a goal the member ranked first."""

    other_goal: int = 1
    """Credit for serving any goal below the top rank."""

    def goal_weight(self, priority: int) -> int:
        """Credit an exercise earns for serving one goal.

        Goals are numbered from 1, most important first, and only the top rank
        is distinguished. The member's goals use priorities 1 and 2, so grading
        more finely would invent precision the data does not carry — and `fit`
        only ever breaks ties between equally safe exercises, so the ratio is
        what matters rather than the scale.

        Args:
            priority: The goal's priority, as recorded on the `Goal` node.

        Returns:
            The contribution to an exercise's `fit`.
        """
        return self.top_goal if priority == 1 else self.other_goal


class Verdict(BaseModel):
    """What the filter decided about one exercise, and why.

    `penalty` and `fit` stay separate numbers. Folded into one scalar you could
    no longer tell whether an exercise ranked low because it is risky or
    because it is off-goal, which is exactly what a coach needs to know.
    """

    model_config = ConfigDict(frozen=True)

    exercise_id: str
    name: str
    status: Status
    penalty: int
    fit: int
    signals: tuple[Signal, ...]
    headline: str

    @property
    def eligible(self) -> bool:
        """Whether this exercise may appear in a plan."""
        return self.status is not Status.EXCLUDED

    def of(self, kind: SignalKind) -> tuple[Signal, ...]:
        """Every signal of one kind that contributed to this verdict."""
        return tuple(signal for signal in self.signals if signal.kind is kind)

    @property
    def attributed_to(self) -> SignalKind | None:
        """The single cause a removal is counted against.

        Several reasons commonly apply at once — four of Jordan's removals have
        two — so per-reason counts overlap and cannot be summed. This picks one
        by fixed precedence, giving counts that do add up.
        """
        if self.status is not Status.EXCLUDED:
            return None
        kinds = {signal.kind for signal in self.signals}
        return next(kind for kind in ATTRIBUTION_ORDER if kind in kinds)

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        """Rank: eligible first, then least penalised, then best fit, then name.

        Penalty precedes `fit`, so a cautioned exercise never outranks an
        uncautioned one whatever goal it serves. Name last makes the order
        total, so two runs over the same graph produce identical output.
        """
        return (_STATUS_RANK[self.status], self.penalty, -self.fit, self.name)


def _headline(name: str, status: Status, signals: tuple[Signal, ...], fit: int) -> str:
    """Compose a one-line explanation from authored text and fixed connectives.

    Every clause is either a `rationale` string authored in
    `contraindications.json`, a fact from the graph, or a fixed connective.
    Nothing is generated, so there is no hallucination surface.

    Args:
        name: Exercise name.
        status: The verdict's status.
        signals: Every signal collected for it.
        fit: Goal-alignment score, mentioned only when positive.

    Returns:
        A sentence a coach can read without opening the evidence.
    """
    excluding = [s for s in signals if s.kind in EXCLUDING]
    soft = [s for s in signals if s.kind not in EXCLUDING]

    if excluding:
        lead = f"Excluded — {excluding[0].detail}"
        rest = [s.detail for s in excluding[1:]] + [s.detail for s in soft]
    elif soft:
        lead = f"Down-ranked — {soft[0].detail}"
        rest = [s.detail for s in soft[1:]]
    else:
        lead = "Eligible"
        rest = []

    clauses = [lead]
    if rest:
        clauses.append("also " + "; ".join(rest))
    if fit and status is not Status.EXCLUDED:
        clauses.append("serves a stated goal")
    annotations = [s.annotation for s in signals if s.annotation]
    if annotations:
        clauses.append(annotations[0])
    return f"{name}: " + ". ".join(clauses) + "."


def score(evidence: ExerciseEvidence, policy: Policy | None = None) -> Verdict:
    """Turn the graph's evidence about one exercise into a verdict.

    Pure — no database, no clock, no randomness — so the whole scoring half of
    the test suite runs without `docker compose up`.

    Args:
        evidence: Everything the queries returned for this exercise.
        policy: Weights to apply. Defaults to `Policy()`.

    Returns:
        The verdict, carrying every signal whether or not it changed the
        outcome, so an excluded exercise can still explain its soft problems.
    """
    policy = policy or Policy()

    excluded = any(signal.kind in EXCLUDING for signal in evidence.signals)
    penalty = sum(
        policy.caution if signal.kind is SignalKind.CAUTION else policy.flagged_structure
        for signal in evidence.signals
        if signal.kind in (SignalKind.CAUTION, SignalKind.FLAGGED_STRUCTURE)
    )
    fit = sum(policy.goal_weight(priority) for priority in evidence.goal_priorities)

    if excluded:
        status = Status.EXCLUDED
    elif penalty:
        status = Status.PENALIZED
    else:
        status = Status.CLEAR

    return Verdict(
        exercise_id=evidence.exercise_id,
        name=evidence.name,
        status=status,
        penalty=penalty,
        fit=fit,
        signals=evidence.signals,
        headline=_headline(evidence.name, status, evidence.signals, fit),
    )
