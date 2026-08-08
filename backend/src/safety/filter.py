from collections import Counter, defaultdict

from neo4j import Session
from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel, RelType
from safety.constraints import Composition, ConstraintKind, ConstraintSet, Origin
from safety.evidence import EvidencePath, ExerciseEvidence, Hop, Signal, SignalKind
from safety.policy import EXCLUDING, Policy, Status, Verdict, score
from safety.queries import AnatomyRow, CatalogRow, ClinicalRow, anatomy, catalog, clinical

# An injury only constrains while it is live. Without this a resolved injury
# would contraindicate forever, and nothing in the graph would ever say why.
LIVE_INJURY_STATUSES: frozenset[str] = frozenset({"active", "recovering"})

# Below this many eligible exercises a session cannot be built from warmup,
# main work and cooldown without repetition.
SESSION_MINIMUM = 8


class Attribution(BaseModel):
    """How removals break down, counted two ways.

    Per-reason counts overlap — four of Jordan's 33 removals have two causes,
    so 29 + 6 + 2 = 37. Presenting that as a breakdown of 33 would be quietly
    false, so both are reported: `per_reason` for "what does each constraint
    touch", `attributed` for figures that sum to `removed`.
    """

    model_config = ConfigDict(frozen=True)

    per_reason: dict[str, int]
    attributed: dict[str, int]
    removed: int
    kept: int

    @property
    def unique_to(self) -> dict[str, int]:
        """Removals each cause is solely responsible for.

        What a coach needs to hear: *"dropping the equipment limit returns 26
        candidates"*. Falls straight out of the attributed counts.
        """
        return dict(self.attributed)


class FilterResult(BaseModel):
    """Every exercise judged, ranked, with the evidence that judged it."""

    model_config = ConfigDict(frozen=True)

    composition: Composition
    policy: Policy
    verdicts: tuple[Verdict, ...]
    attribution: Attribution
    unresolved_structures: tuple[str, ...] = ()

    @property
    def eligible(self) -> tuple[Verdict, ...]:
        """Verdicts that may be programmed, best first."""
        return tuple(v for v in self.verdicts if v.eligible)

    @property
    def is_thin(self) -> bool:
        """Whether too few exercises survive to build a session from."""
        return len(self.eligible) < SESSION_MINIMUM

    @property
    def costliest_constraint(self) -> str | None:
        """The cause responsible for the most removals, when the pool is thin.

        Lets a caller say *"only 5 remain, mostly because of the equipment
        limit"* rather than presenting a thin plan as if it were a full one.
        """
        if not self.attribution.attributed:
            return None
        return max(self.attribution.attributed.items(), key=lambda item: item[1])[0]


def _clinical_signals(rows: list[ClinicalRow]) -> dict[str, list[Signal]]:
    """Turn condition rules into signals, skipping injuries that have resolved."""
    signals: dict[str, list[Signal]] = defaultdict(list)
    for row in rows:
        if row.injury_status not in LIVE_INJURY_STATUSES:
            continue
        kind = (
            SignalKind.CONTRAINDICATION
            if row.relation is RelType.CONTRAINDICATES
            else SignalKind.CAUTION
        )
        signals[row.exercise_id].append(
            Signal(
                kind=kind,
                detail=row.rationale,
                path=EvidencePath(
                    entry=row.injury_id,
                    hops=(
                        Hop(
                            rel=RelType.DIAGNOSED_AS,
                            to_label=NodeLabel.CONDITION,
                            to_name=row.condition,
                        ),
                        Hop(
                            rel=row.relation,
                            to_label=NodeLabel.MOVEMENT_PATTERN,
                            to_name=row.pattern,
                        ),
                    ),
                ),
            )
        )
    return signals


def _anatomy_signals(rows: list[AnatomyRow]) -> dict[str, list[Signal]]:
    """Turn flagged-structure hits into signals.

    The injury found at a joint becomes an annotation and nothing else. It
    explains the signal without weighting it, which is what keeps `affects`
    out of the filter as `docs/decisions.md` KG1 item 3 promises.
    """
    signals: dict[str, list[Signal]] = defaultdict(list)
    for row in rows:
        annotation = None
        if row.injury_id:
            state = " ".join(filter(None, (row.injury_side, row.injury_status)))
            annotation = f"{row.joint} is the site of {row.injury_id} ({state})"
        signals[row.exercise_id].append(
            Signal(
                kind=SignalKind.FLAGGED_STRUCTURE,
                detail=f"loads the {row.joint}",
                annotation=annotation,
                path=EvidencePath(
                    entry=row.entry,
                    hops=(
                        Hop(
                            rel=RelType.PART_OF,
                            to_label=NodeLabel.ANATOMICAL_STRUCTURE,
                            to_name=row.joint,
                        ),
                        Hop(rel=RelType.STRESSES, to_label=NodeLabel.EXERCISE, to_name="(this)"),
                    ),
                ),
            )
        )
    return signals


def _constraint_signals(row: CatalogRow, constraints: ConstraintSet) -> list[Signal]:
    """Signals that come from the constraint set rather than a traversal."""
    signals: list[Signal] = []
    for missing in row.missing_equipment:
        signals.append(
            Signal(
                kind=SignalKind.MISSING_EQUIPMENT,
                detail=f"needs {missing}, which is not available",
                path=EvidencePath(
                    entry=row.name,
                    hops=(
                        Hop(rel=RelType.REQUIRES, to_label=NodeLabel.EQUIPMENT, to_name=missing),
                    ),
                ),
            )
        )

    excluded = constraints.values(ConstraintKind.EXCLUDED_EXERCISE)
    if row.exercise_id in excluded or row.name in excluded:
        from_chart = any(
            c.value in (row.exercise_id, row.name) and c.origin is Origin.STANDING
            for c in constraints.of(ConstraintKind.EXCLUDED_EXERCISE)
        )
        signals.append(
            Signal(
                kind=SignalKind.DISLIKE if from_chart else SignalKind.COACH_EXCLUSION,
                detail=(
                    "the member has it recorded as disliked"
                    if from_chart
                    else "excluded for this session"
                ),
                path=EvidencePath(entry=row.name),
            )
        )

    for pattern in row.patterns:
        if pattern in constraints.values(ConstraintKind.EXCLUDED_PATTERN):
            signals.append(
                Signal(
                    kind=SignalKind.COACH_EXCLUSION,
                    detail=f"excluded for this session as {pattern}",
                    path=EvidencePath(
                        entry=row.name,
                        hops=(
                            Hop(
                                rel=RelType.IS_A,
                                to_label=NodeLabel.MOVEMENT_PATTERN,
                                to_name=pattern,
                            ),
                        ),
                    ),
                )
            )
    return signals


def _attribution(verdicts: tuple[Verdict, ...]) -> Attribution:
    """Count removals per reason and per attributed cause."""
    per_reason: Counter[str] = Counter()
    attributed: Counter[str] = Counter()
    removed = 0
    for verdict in verdicts:
        if verdict.status is not Status.EXCLUDED:
            continue
        removed += 1
        for kind in {s.kind for s in verdict.signals if s.kind in EXCLUDING}:
            per_reason[kind.value] += 1
        cause = verdict.attributed_to
        if cause is not None:
            attributed[cause.value] += 1
    return Attribution(
        per_reason=dict(per_reason),
        attributed=dict(attributed),
        removed=removed,
        kept=len(verdicts) - removed,
    )


def run(
    session: Session,
    composition: Composition,
    policy: Policy | None = None,
) -> FilterResult:
    """Judge the whole catalog against one request's constraints.

    Takes a `Composition`, never a string: there is no type-checking path by
    which free text or a language model reaches this traversal. Every exercise
    is judged and kept, including the excluded ones, so a coach can ask why
    something is missing and get an answer.

    Args:
        session: An open Neo4j session.
        composition: The folded constraint set, from `constraints.compose`.
        policy: Weights to apply. Defaults to `Policy()`.

    Returns:
        Every verdict ranked best-first, the removal breakdown counted both
        ways, and any flagged structure that reached no joint.
    """
    policy = policy or Policy()
    constraints = composition.applied

    rows = catalog(session, constraints.member_id, constraints.available_equipment)
    clinical_rows = clinical(session, constraints.injury_ids)
    flagged = constraints.values(ConstraintKind.FLAGGED_STRUCTURE)
    anatomy_rows = anatomy(session, flagged)

    by_clinical = _clinical_signals(clinical_rows)
    by_anatomy = _anatomy_signals(anatomy_rows)

    verdicts = tuple(
        score(
            ExerciseEvidence(
                exercise_id=row.exercise_id,
                name=row.name,
                supports_weight=row.supports_weight,
                signals=tuple(
                    _constraint_signals(row, constraints)
                    + by_clinical.get(row.exercise_id, [])
                    + by_anatomy.get(row.exercise_id, [])
                ),
                goal_muscles=tuple(sorted({g.muscle for g in row.goal_rows})),
                # One entry per distinct goal, not per shared muscle: an
                # exercise hitting two muscles of one goal serves that goal
                # once, and should not be credited twice for it.
                goal_priorities=tuple(
                    priority
                    for _, priority in sorted({(g.goal_id, g.priority) for g in row.goal_rows})
                ),
            ),
            policy,
        )
        for row in rows
    )
    verdicts = tuple(sorted(verdicts, key=lambda verdict: verdict.sort_key))

    reached = {row.entry for row in anatomy_rows}
    return FilterResult(
        composition=composition,
        policy=policy,
        verdicts=verdicts,
        attribution=_attribution(verdicts),
        unresolved_structures=tuple(sorted(flagged - reached)),
    )
