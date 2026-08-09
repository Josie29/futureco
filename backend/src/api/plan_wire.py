from api.plan_models import (
    CAUSE_OF,
    ConceptIntent,
    Eligibility,
    FilteredExercise,
    MuscleTag,
    PlanExercise,
    PlanPayload,
    PlanTrace,
    ResolvedConcept,
    TraceStage,
    UnresolvedPhrase,
    VerdictLabel,
)
from plan.pipeline import GeneratedPlan
from plan.schemas import Block, ReasonKind, Section
from resolve.resolver import Resolution, Thresholds
from safety.constraints import ConstraintKind, Directive, Op
from safety.evidence import EvidencePath, SignalKind
from safety.filter import Attribution, FilterResult
from safety.policy import ATTRIBUTION_ORDER, EXCLUDING

# A body site is protected whatever is done to it; naming an exercise or a
# pattern always removes it. Equipment is the one kind that reads both ways,
# so its intent comes from the operation.
INTENT_OF: dict[ConstraintKind, ConceptIntent] = {
    ConstraintKind.EXCLUDED_EXERCISE: ConceptIntent.EXCLUDE,
    ConstraintKind.EXCLUDED_PATTERN: ConceptIntent.EXCLUDE,
    ConstraintKind.FLAGGED_STRUCTURE: ConceptIntent.PROTECT,
    ConstraintKind.INJURY: ConceptIntent.PROTECT,
}


def _intent(directive: Directive) -> ConceptIntent:
    """What a resolved phrase was asking the catalog to do.

    "Only dumbbells" narrows the session toward the dumbbell; switching the
    dumbbell off removes everything needing one. Same kind, opposite effect,
    and the console groups by this — so reading it off the kind alone filed
    every equipment change under focus.
    """
    if directive.kind is ConstraintKind.EQUIPMENT:
        return ConceptIntent.EXCLUDE if directive.op is Op.REMOVE else ConceptIntent.FOCUS
    return INTENT_OF[directive.kind]


# Attention-worthy reasons, in the order a coach would want to read them. The
# first one present becomes the block's note; a movement with none needs no
# note at all, which is different from having nothing to say about it.
NOTEWORTHY: tuple[ReasonKind, ...] = (
    ReasonKind.CAUTION,
    ReasonKind.FLAGGED_STRUCTURE,
    ReasonKind.SUBSTITUTION,
)

# The order the pipeline actually narrows in, matching `ATTRIBUTION_ORDER`.
STAGE_LABELS: dict[SignalKind, tuple[str, str]] = {
    SignalKind.CONTRAINDICATION: (
        "Injury and conditions",
        "movement patterns a clinician ruled out",
    ),
    SignalKind.MISSING_EQUIPMENT: ("Equipment", "movements needing kit she does not have"),
    SignalKind.DISLIKE: ("Preferences", "movements she has recorded as disliked"),
    SignalKind.COACH_EXCLUSION: ("This request", "movements excluded for this session"),
}


def _verdict(block: Block) -> VerdictLabel:
    """How the console should mark a scheduled block.

    Never `EXCLUDED` — nothing excluded reaches a plan. That member exists
    because the same enum labels the dropped list.
    """
    return VerdictLabel.CAUTION if block.penalty else VerdictLabel.CLEARED


def _note(block: Block) -> str | None:
    """The one sentence a coach needs about this movement, if any."""
    for kind in NOTEWORTHY:
        found = next((r for r in block.reasons if r.kind is kind), None)
        if found:
            return found.detail
    return None


def _exercise(block: Block) -> PlanExercise:
    """Project one scheduled block onto the console's shape."""
    goal_muscles = set(block.goal_muscles)
    dose = block.prescription
    return PlanExercise(
        id=block.exercise_id,
        name=block.name,
        block=block.section,
        sets=dose.sets,
        reps=dose.reps,
        duration_sec=dose.hold_seconds,
        rest_sec=dose.rest_seconds,
        per_side=dose.per_side,
        minutes=round(dose.total_seconds / 60, 1),
        muscles=[
            MuscleTag(name=muscle, is_goal_target=muscle in goal_muscles)
            for muscle in block.muscles
        ],
        equipment=list(block.equipment),
        verdict=_verdict(block),
        note=_note(block),
        why=list(block.reasons),
    )


def _filtered(result: FilterResult) -> list[FilteredExercise]:
    """Every dropped movement, grouped by the cause it was attributed to.

    All of them, not a sample: the console reconciles these counts against the
    builder's, and a truncated list would make the two disagree.
    """
    rows = []
    for verdict in result.verdicts:
        cause = verdict.attributed_to
        if cause is None:
            continue
        excluding = [s for s in verdict.signals if s.kind in EXCLUDING]
        rows.append(
            FilteredExercise(
                id=verdict.exercise_id,
                name=verdict.name,
                cause=CAUSE_OF[cause],
                detail=" · ".join(signal.detail for signal in excluding),
                path=next(
                    (s.path for s in excluding if s.kind is cause),
                    EvidencePath(entry=verdict.name),
                ),
            )
        )
    return rows


def _resolved(directive: Directive) -> ResolvedConcept:
    """Project one applied directive onto the console's resolution row."""
    match = directive.resolution.match
    return ResolvedConcept(
        phrase=directive.phrase,
        label=match.label,
        concept_id=f"{match.label}:{match.name}",
        concept_name=match.name,
        pass_=match.matched_by,
        confidence=match.score,
        intent=_intent(directive),
        side=directive.resolution.side,
    )


def _unresolved(phrase: str, resolution: Resolution, fallback: str) -> UnresolvedPhrase:
    """Project one declined phrase, naming what happened instead."""
    best = resolution.candidates[0] if resolution.candidates else None
    thresholds = Thresholds()
    return UnresolvedPhrase(
        phrase=phrase,
        best_guess=best.name if best else None,
        confidence=best.score if best else 0.0,
        threshold=thresholds.vector if best and best.matched_by == "vector" else thresholds.fuzzy,
        fallback=fallback,
    )


def _stages(result: FilterResult, prescribed: int) -> list[TraceStage]:
    """The pipeline narrowing, stage by stage.

    Counted from `Attribution.attributed` rather than `per_reason`, because
    only the attributed figures sum to the number actually removed — the
    per-reason ones overlap, and a funnel built from them would end below zero.
    """
    remaining = len(result.verdicts)
    stages = [
        TraceStage(label="Catalogue", remaining=remaining, detail="every movement in the library")
    ]
    for kind in ATTRIBUTION_ORDER:
        removed = result.attribution.attributed.get(kind.value, 0)
        if not removed:
            continue
        remaining -= removed
        label, detail = STAGE_LABELS[kind]
        stages.append(
            TraceStage(label=label, remaining=remaining, detail=f"{removed} {detail}")
        )
    stages.append(
        TraceStage(
            label="Session fit",
            remaining=prescribed,
            detail="movements that fit the requested window",
        )
    )
    return stages


def eligibility(attribution: Attribution, total: int) -> Eligibility:
    """The builder's live count, from the filter's own arithmetic."""
    return Eligibility(
        total=total,
        available=attribution.kept,
        excluded_by={
            CAUSE_OF[kind]: attribution.attributed[kind.value]
            for kind in ATTRIBUTION_ORDER
            if kind.value in attribution.attributed
        },
    )


def payload(
    generated: GeneratedPlan,
    prompt: str,
    title: str,
    day_label: str,
    unmapped: tuple[str, ...] = (),
) -> PlanPayload:
    """Project a generated plan onto the console's contract.

    A pure mapping. Everything here was decided upstream — this decides only
    how it is named on the wire.

    Args:
        generated: The plan, its provenance and its substitutions.
        prompt: What the coach typed, echoed for the revision trail.
        title: A name for the session.
        day_label: When it is for.
        unmapped: Phrases extraction heard but could not classify.

    Returns:
        The payload `web/src/api/client.ts` expects.
    """
    result = generated.trace.result
    blocks = generated.plan.blocks

    resolved = [
        _resolved(directive)
        for directive in result.composition.directives
        if directive.resolution.match
    ]
    resolved += [
        ResolvedConcept(
            phrase=resolution.term,
            label=resolution.match.label,
            concept_id=f"{resolution.match.label}:{resolution.match.name}",
            concept_name=resolution.match.name,
            pass_=resolution.match.matched_by,
            confidence=resolution.match.score,
            intent=ConceptIntent.FOCUS,
            side=resolution.side,
        )
        for resolution in generated.focus
        if resolution.match
    ]

    unresolved = [
        _unresolved(
            unapplied.directive.phrase,
            unapplied.directive.resolution,
            unapplied.explanation,
        )
        for unapplied in result.composition.unapplied
    ]
    unresolved += [
        _unresolved(
            resolution.term,
            resolution,
            "the emphasis was not applied; ranking is unchanged",
        )
        for resolution in generated.focus
        if resolution.match is None
    ]
    # Heard but not classifiable — never resolved, so there is no near-miss to
    # show. Reported beside the declines because to a coach they are the same
    # thing: something said that the session does not reflect.
    unresolved += [
        UnresolvedPhrase(
            phrase=phrase,
            best_guess=None,
            confidence=0.0,
            threshold=0.0,
            fallback="heard, but it is not something the planner can act on",
        )
        for phrase in unmapped
    ]

    return PlanPayload(
        run_id=generated.run_id,
        parent_run_id=generated.parent_run_id,
        prompt=prompt,
        title=title,
        day_label=day_label,
        requested_minutes=generated.requested_minutes,
        estimated_minutes=round(generated.plan.budget.scheduled_seconds / 60, 1),
        exercises=[_exercise(block) for block in blocks],
        trace=PlanTrace(
            run_id=generated.run_id,
            generated_at=generated.trace.header.generated_at_time,
            catalogue_total=len(result.verdicts),
            eligible=result.attribution.kept,
            prescribed=len(blocks),
            stages=_stages(result, len(blocks)),
            resolved=resolved,
            unresolved=unresolved,
            filtered=_filtered(result),
        ),
    )
