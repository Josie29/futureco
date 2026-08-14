from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from agents.workout_generator.agent import (
    PlannedExercise,
    WorkoutPlan,
    enforce_citations,
    enforce_time_budget,
)
from agents.workout_generator.agent import (
    _safety_problems,
    enforce_required_exercises,
)
from agents.workout_generator.deps import GeneratorDeps, ProvenanceEvent, ProvenanceKind
from agents.workout_generator.tools.constraints import CoachConstraint, declare_constraints
from catalog.eligibility import Exclusion, ExclusionCause
from constraints.models import Constraint, ConstraintSet, Effect, Origin
from resolver.index import ConceptIndex, _Entry
from resolver.models import Namespace


def deps_with_log(*concept_ids: str, alternatives: tuple[str, ...] = ()) -> GeneratorDeps:
    deps = GeneratorDeps(
        member_id="m1",
        duration_min=45,
        graph=None,  # type: ignore[arg-type]
        concept_index=None,  # type: ignore[arg-type]
    )
    for concept_id in concept_ids:
        deps.tool_log.append(
            ProvenanceEvent(kind=ProvenanceKind.CONCEPT_RESOLUTION, concept=concept_id)
        )
    if alternatives:
        deps.tool_log.append(
            ProvenanceEvent(kind=ProvenanceKind.CONCEPT_RESOLUTION, alternatives=alternatives)
        )
    return deps


def slot(concept_id: str, seconds: int = 600) -> PlannedExercise:
    return PlannedExercise(
        concept_id=concept_id, label="x", sets=3, reps="8-10", seconds=seconds, rationale="r"
    )


def plan(*main: PlannedExercise, warmup: tuple[PlannedExercise, ...] = ()) -> WorkoutPlan:
    total = sum(s.seconds for s in (*warmup, *main))
    return WorkoutPlan(title="t", total_seconds=total, warmup=list(warmup), main=list(main))


def test_citations_pass_for_ids_the_run_was_shown() -> None:
    """A plan built from resolved ids goes through untouched.

    If shown ids were rejected, no plan could ever validate and every run
    would exhaust its retries.
    """
    ctx = SimpleNamespace(deps=deps_with_log("exercise:Goblet Squat"))
    p = plan(slot("exercise:Goblet Squat"))
    assert enforce_citations(ctx, p) is p


def test_citations_reject_an_id_the_run_never_saw() -> None:
    """The model cannot smuggle in an exercise it was never shown.

    Without this, a hallucinated-but-real-looking concept_id would flow into
    a coach-facing plan with no tool result behind it.
    """
    ctx = SimpleNamespace(deps=deps_with_log("exercise:Goblet Squat"))
    with pytest.raises(ModelRetry, match="never returned"):
        enforce_citations(ctx, plan(slot("exercise:Invented Movement")))


def test_citations_accept_ids_shown_only_as_alternatives() -> None:
    """Near-misses the tool displayed are fair game for the plan.

    The catalog is discovered through unresolved alternatives; rejecting them
    would force a redundant second resolve of a name the run already has.
    """
    ctx = SimpleNamespace(
        deps=deps_with_log(alternatives=("exercise:Kettlebell Swing",))
    )
    p = plan(slot("exercise:Kettlebell Swing"))
    assert enforce_citations(ctx, p) is p


def test_citations_reject_a_non_exercise_concept() -> None:
    """A resolved muscle or equipment id cannot occupy an exercise slot.

    "chest" resolves fine as a muscle — putting muscle:chest in the plan
    would hand downstream graph tools the wrong node type.
    """
    ctx = SimpleNamespace(deps=deps_with_log("muscle:chest"))
    with pytest.raises(ModelRetry, match="not exercises"):
        enforce_citations(ctx, plan(slot("muscle:chest")))


def test_budget_rejects_arithmetic_that_does_not_add_up() -> None:
    """total_seconds must equal the sum of the slots.

    A plan whose header disagrees with its body reads as a different length
    than it runs.
    """
    ctx = SimpleNamespace(deps=deps_with_log())
    p = WorkoutPlan(title="t", total_seconds=9999, main=[slot("exercise:X")])
    with pytest.raises(ModelRetry, match="sum"):
        enforce_time_budget(ctx, p)


def test_budget_rejects_a_plan_far_over_the_window() -> None:
    """A plan more than 15% over the window bounces back with the numbers.

    This is what remains of pack.py: the model composes, arithmetic verifies.
    45 min window tolerates up to 3105s; 3200s must fail.
    """
    ctx = SimpleNamespace(deps=deps_with_log())
    p = plan(slot("exercise:X", seconds=1600), slot("exercise:Y", seconds=1600))
    with pytest.raises(ModelRetry, match="window"):
        enforce_time_budget(ctx, p)


def test_budget_rejects_a_plan_far_under_the_window() -> None:
    """A plan more than 15% under the window is a short session, not a plan.

    The coach asked for 45 minutes; 30 minutes of work is a different
    product delivered without a word.
    """
    ctx = SimpleNamespace(deps=deps_with_log())
    p = plan(slot("exercise:X", seconds=1800))
    with pytest.raises(ModelRetry, match="window"):
        enforce_time_budget(ctx, p)


def test_budget_passes_within_the_tolerance_band() -> None:
    """A consistent plan close to the window goes through untouched.

    42 of 45 requested minutes is inside the 15% band — bouncing it would
    force pointless precision on rest-time guesses.
    """
    ctx = SimpleNamespace(deps=deps_with_log())
    p = plan(slot("exercise:X", seconds=1260), slot("exercise:Y", seconds=1260))
    assert enforce_time_budget(ctx, p) is p


def test_snapshot_event_widens_no_citations() -> None:
    """A disliked exercise seen only via the snapshot is not plannable.

    The snapshot surfaces exercise ids as member context; if they entered
    the citation allowlist, the model could plan the very exercise the
    member dislikes without ever resolving it.
    """
    deps = deps_with_log()
    deps.tool_log.append(
        ProvenanceEvent(
            kind=ProvenanceKind.MEMBER_SNAPSHOT, member="m1"
        )
    )
    ctx = SimpleNamespace(deps=deps)
    with pytest.raises(ModelRetry, match="never returned"):
        enforce_citations(ctx, plan(slot("exercise:One-Kettlebell Hamstring Walkout")))


def test_citations_ignore_non_resolution_events() -> None:
    """Only resolution events feed the allowlist, whatever a log entry carries.

    A future tool logging a concept id for tracing must not silently widen
    the plannable set — the validator owns the rule, not tool restraint.
    """
    deps = deps_with_log()
    deps.tool_log.append(
        ProvenanceEvent(
            kind=ProvenanceKind.MEMBER_SNAPSHOT,
            concept="exercise:Smuggled Movement",
            alternatives=("exercise:Also Smuggled",),
        )
    )
    ctx = SimpleNamespace(deps=deps)
    with pytest.raises(ModelRetry, match="never returned"):
        enforce_citations(ctx, plan(slot("exercise:Smuggled Movement")))


def test_validators_see_every_section() -> None:
    """A slot hiding in the warmup is checked like any other.

    If validators only walked main, an unshown id in the warmup would reach
    the coach unvetted.
    """
    ctx = SimpleNamespace(deps=deps_with_log("exercise:Goblet Squat"))
    p = plan(slot("exercise:Goblet Squat"), warmup=(slot("exercise:Never Shown"),))
    with pytest.raises(ModelRetry, match="never returned"):
        enforce_citations(ctx, p)


def constraint(target: str, effect: Effect, reason: str = "coach said so") -> Constraint:
    return Constraint(target=target, effect=effect, origin=Origin.COACH, reason=reason)


def ctx_with_declared(*constraints: Constraint) -> SimpleNamespace:
    deps = deps_with_log()
    deps.declared_constraints = ConstraintSet(constraints=constraints)
    return SimpleNamespace(deps=deps)


def test_required_exercise_missing_bounces_with_the_reason() -> None:
    """A required exercise absent from every section bounces the plan."""
    ctx = ctx_with_declared(constraint("exercise:Goblet Squat", Effect.REQUIRE))
    with pytest.raises(ModelRetry, match="no section"):
        enforce_required_exercises(ctx, plan(slot("exercise:Other")))


def test_required_exercise_anywhere_satisfies() -> None:
    """A required exercise counts from any section."""
    ctx = ctx_with_declared(constraint("exercise:Goblet Squat", Effect.REQUIRE))
    p = plan(slot("exercise:Other"), warmup=(slot("exercise:Goblet Squat"),))
    assert enforce_required_exercises(ctx, p) is p


def test_no_requires_passes_everything() -> None:
    """No declared requires, no presence checks."""
    ctx = SimpleNamespace(deps=deps_with_log())
    p = plan(slot("exercise:Anything"))
    assert enforce_required_exercises(ctx, p) is p


def _index() -> ConceptIndex:
    return ConceptIndex([
        _Entry(concept_id="exercise:Goblet Squat", name="Goblet Squat",
               namespace=Namespace.EXERCISE, normalized="goblet squat"),
        _Entry(concept_id="muscle:glutes", name="glutes",
               namespace=Namespace.MUSCLE, normalized="glutes"),
    ])


def declare_ctx() -> SimpleNamespace:
    deps = deps_with_log()
    deps.concept_index = _index()
    return SimpleNamespace(deps=deps)


def test_declaration_replaces_state_and_stamps_coach() -> None:
    """An accepted declaration is the new set in force, origin stamped.

    If origin were model-settable, a declaration could speak for the
    clinician; the wire model has no such field and the tool stamps COACH.
    """
    ctx = declare_ctx()
    out = declare_constraints(ctx, [
        CoachConstraint(target="exercise:Goblet Squat", effect=Effect.REQUIRE, reason="asked"),
        CoachConstraint(target="muscle:glutes", effect=Effect.PREFER, reason="focus"),
    ])
    assert out.status == "accepted"
    assert len(out.added) == 2 and out.removed == ()
    assert all(c.origin is Origin.COACH for c in ctx.deps.declared_constraints.constraints)
    assert "origin" not in CoachConstraint.model_fields


def test_redeclaration_shows_the_drop() -> None:
    """Omitting a constraint from the next declaration surfaces as removed."""
    ctx = declare_ctx()
    declare_constraints(ctx, [
        CoachConstraint(target="exercise:Goblet Squat", effect=Effect.REQUIRE, reason="asked"),
        CoachConstraint(target="muscle:glutes", effect=Effect.PREFER, reason="focus"),
    ])
    out = declare_constraints(ctx, [
        CoachConstraint(target="muscle:glutes", effect=Effect.PREFER, reason="focus"),
    ])
    assert [r.target for r in out.removed] == ["exercise:Goblet Squat"]


def test_invalid_target_rejects_the_whole_declaration() -> None:
    """One bad target rejects everything and the previous set stands.

    A partial accept would install a set no declaration ever asserted,
    and the model's mental previous-set would diverge from deps.
    """
    ctx = declare_ctx()
    declare_constraints(ctx, [
        CoachConstraint(target="muscle:glutes", effect=Effect.PREFER, reason="focus"),
    ])
    out = declare_constraints(ctx, [
        CoachConstraint(target="exercise:Goblet Squat", effect=Effect.AVOID, reason="ok"),
        CoachConstraint(target="raw text", effect=Effect.AVOID, reason="bad"),
        CoachConstraint(target="exercise:Invented", effect=Effect.AVOID, reason="bad"),
    ])
    assert out.status == "rejected"
    assert [c.target for c in out.active] == ["muscle:glutes"]
    assert ctx.deps.declared_constraints.targets(Effect.PREFER) == frozenset({"muscle:glutes"})
    problems = {i.target: i.problem for i in out.invalid}
    assert "not a concept_id" in problems["raw text"]
    assert "resolve the term first" in problems["exercise:Invented"]


def test_declaration_events_are_logged_for_accept_and_reject() -> None:
    """Both outcomes land in provenance — a failed install is a decision too."""
    ctx = declare_ctx()
    declare_constraints(ctx, [
        CoachConstraint(target="muscle:glutes", effect=Effect.PREFER, reason="focus"),
    ])
    declare_constraints(ctx, [
        CoachConstraint(target="nonsense", effect=Effect.AVOID, reason="bad"),
    ])
    events = [e for e in ctx.deps.tool_log
              if e.kind is ProvenanceKind.CONSTRAINT_DECLARATION]
    assert len(events) == 2
    assert events[0].constraint_set is not None and events[0].constraint_diff is not None
    assert events[1].rejected_targets == ("nonsense",)


def test_declaration_events_never_widen_citations() -> None:
    """Constraint targets are not plannable citations.

    Declaring avoid on an exercise must not make that exercise citable —
    only resolve_concept results feed the allowlist.
    """
    ctx = declare_ctx()
    declare_constraints(ctx, [
        CoachConstraint(target="exercise:Goblet Squat", effect=Effect.PREFER, reason="ok"),
    ])
    with pytest.raises(ModelRetry, match="never returned"):
        enforce_citations(ctx, plan(slot("exercise:Goblet Squat")))


def retrieval_event(candidates: tuple[str, ...] = (),
                    exclusions: tuple[Exclusion, ...] = ()) -> ProvenanceEvent:
    return ProvenanceEvent(
        kind=ProvenanceKind.CANDIDATE_RETRIEVAL,
        candidates=candidates,
        exclusions=exclusions,
    )


def exclusion(concept_id: str, reason: str = "coach said") -> Exclusion:
    return Exclusion(
        concept_id=concept_id,
        cause=ExclusionCause.AVOIDED,
        matched_target="movement_pattern:p",
        reason=reason,
    )


def test_retrieval_candidates_are_citable() -> None:
    """An eligible card id is plannable without a separate resolve.

    Retrieval is now the primary catalog browse; forcing a redundant
    resolve of every returned id would double the tool traffic for nothing.
    """
    deps = deps_with_log()
    deps.tool_log.append(retrieval_event(candidates=("exercise:Goblet Squat",)))
    ctx = SimpleNamespace(deps=deps)
    p = plan(slot("exercise:Goblet Squat"))
    assert enforce_citations(ctx, p) is p


def test_retrieval_exclusions_are_never_citable() -> None:
    """An id present only in exclusion records is not plannable.

    The candidates/exclusions field split is the security boundary: if
    exclusion records fed the allowlist, every excluded exercise would
    become plannable by virtue of being excluded.
    """
    deps = deps_with_log()
    deps.tool_log.append(retrieval_event(exclusions=(exclusion("exercise:Jump Squat"),)))
    ctx = SimpleNamespace(deps=deps)
    with pytest.raises(ModelRetry, match="never returned"):
        enforce_citations(ctx, plan(slot("exercise:Jump Squat")))


def test_get_eligible_exercises_logs_one_split_event(monkeypatch) -> None:
    """The tool logs eligible ids and exclusion records in separate fields.

    The event is what citations and the constraint validator read; merging
    the fields would collapse the plannable/rejected boundary.
    """
    from agents.workout_generator.tools import candidates as ct
    from catalog.cards import ExerciseCard

    liked = ExerciseCard(
        concept_id="exercise:Kept", name="Kept", patterns=("movement_pattern:p",),
        muscles=(), equipment_required=(), missing_equipment=(), joints=(),
        is_reps=True, is_duration=False, estimated_rep_seconds=4.0,
        is_bilateral=True, side=None, supports_weight=True, disliked=False,
        goal_overlap=(),
    )
    hated = liked.model_copy(
        update={"concept_id": "exercise:Dropped", "name": "Dropped", "disliked": True}
    )
    monkeypatch.setattr(ct, "load_cards", lambda session, member_id: (liked, hated))

    ctx = SimpleNamespace(deps=deps_with_log())
    out = ct.get_eligible_exercises(ctx)
    assert [e.concept_id for e in out.eligible] == ["exercise:Kept"]
    (event,) = [e for e in ctx.deps.tool_log
                if e.kind is ProvenanceKind.CANDIDATE_RETRIEVAL]
    assert event.candidates == ("exercise:Kept",)
    assert [x.concept_id for x in event.exclusions] == ["exercise:Dropped"]


def test_unmatched_requires_warn_in_guidance(monkeypatch) -> None:
    """A require nothing can satisfy is warned before composition begins."""
    from agents.workout_generator.tools import candidates as ct

    monkeypatch.setattr(ct, "load_cards", lambda session, member_id: ())
    deps = deps_with_log()
    deps.declared_constraints = ConstraintSet(
        constraints=(constraint("exercise:Ghost", Effect.REQUIRE),)
    )
    out = ct.get_eligible_exercises(SimpleNamespace(deps=deps))
    assert "exercise:Ghost" in out.guidance
    assert "WARNING" in out.guidance


def eligibility_result(
    eligible: tuple = (), excluded: tuple = (), unmatched: tuple = ()
):
    from catalog.eligibility import EligibilityResult

    return EligibilityResult(
        eligible=eligible, excluded=excluded, unmatched_requires=unmatched
    )


def blocked_exclusion(concept_id: str) -> Exclusion:
    from graph.evidence import EvidencePath, Hop
    from graph.schema import NodeLabel, RelType

    return Exclusion(
        concept_id=concept_id,
        cause=ExclusionCause.BLOCKED,
        matched_target="movement_pattern:cardio - plyometric",
        reason="Impact loading spikes joint reaction force.",
        evidence=EvidencePath(
            entry="inj_knee_left",
            hops=(
                Hop(rel=RelType.DIAGNOSED_AS, to_label=NodeLabel.CONDITION,
                    to_name="patellofemoral pain syndrome"),
                Hop(rel=RelType.CONTRAINDICATES, to_label=NodeLabel.MOVEMENT_PATTERN,
                    to_name="cardio - plyometric"),
            ),
        ),
    )


def eligible_card(concept_id: str, cautions: tuple = ()):
    from catalog.eligibility import EligibleExercise

    return EligibleExercise(
        concept_id=concept_id, name=concept_id.split(":")[1],
        patterns=("movement_pattern:p",), muscles=(), equipment_required=(),
        missing_equipment=(), joints=(), is_reps=True, is_duration=False,
        estimated_rep_seconds=4.0, is_bilateral=True, side=None,
        supports_weight=True, disliked=False, goal_overlap=(),
        cautions=cautions,
    )


def caution(target: str = "movement_pattern:lower push - squat"):
    from catalog.eligibility import Caution
    from graph.evidence import EvidencePath, Hop
    from graph.schema import NodeLabel, RelType

    return Caution(
        matched_target=target,
        reason="Deep flexion under load aggravates the joint.",
        evidence=EvidencePath(
            entry="inj_knee_left",
            hops=(
                Hop(rel=RelType.DIAGNOSED_AS, to_label=NodeLabel.CONDITION,
                    to_name="patellofemoral pain syndrome"),
                Hop(rel=RelType.CAUTIONS, to_label=NodeLabel.MOVEMENT_PATTERN,
                    to_name=target.split(":")[1]),
            ),
        ),
    )


def test_blocked_slot_rejected_with_evidence_in_message() -> None:
    """A blocked exercise in the plan bounces with the traversal rendered.

    The evidence path is what a coach defends to a physio; a rejection
    without it is an unexplained no.
    """
    result = eligibility_result(excluded=(blocked_exclusion("exercise:Jump Squat"),))
    problems = _safety_problems(plan(slot("exercise:Jump Squat")), result)
    (problem,) = problems
    assert "blocked" in problem
    assert "inj_knee_left -diagnosed_as-> patellofemoral pain syndrome" in problem


def test_cautioned_slot_without_note_rejected() -> None:
    """A cautioned exercise cannot be planned silently.

    The caution acknowledgment is the coach-facing flag the clinical split
    exists for — a caution planned without one reads as clear.
    """
    result = eligibility_result(
        eligible=(eligible_card("exercise:Goblet Squat", cautions=(caution(),)),)
    )
    problems = _safety_problems(plan(slot("exercise:Goblet Squat")), result)
    (problem,) = problems
    assert "caution_note" in problem


def test_caution_note_on_uncautioned_slot_rejected() -> None:
    """Clinical-sounding reassurance on a clean exercise is rejected.

    A caution_note with no caution behind it is fabricated safety prose —
    exactly the claim the no-clearance rule forbids.
    """
    result = eligibility_result(eligible=(eligible_card("exercise:Clean"),))
    p = plan(
        PlannedExercise(
            concept_id="exercise:Clean", label="Clean", sets=3, reps="8",
            seconds=600, rationale="r", caution_note="kept shallow just in case",
        )
    )
    problems = _safety_problems(p, result)
    (problem,) = problems
    assert "no clinical caution" in problem


def test_cautioned_slot_with_note_passes() -> None:
    """An acknowledged caution goes through."""
    result = eligibility_result(
        eligible=(eligible_card("exercise:Goblet Squat", cautions=(caution(),)),)
    )
    p = plan(
        PlannedExercise(
            concept_id="exercise:Goblet Squat", label="GS", sets=3, reps="8",
            seconds=600, rationale="r",
            caution_note="Shallow range, light load per the caution.",
        )
    )
    assert _safety_problems(p, result) == []


def test_coach_constraint_schema_cannot_utter_block_or_caution() -> None:
    """The wire schema has no clinical vocabulary.

    If the model could declare BLOCK or CAUTION, it could speak for the
    clinician — the no-waive-verb invariant, relocated into the schema.
    """
    schema = CoachConstraint.model_json_schema()
    effect = schema["properties"]["effect"]
    allowed = effect.get("enum") or [effect.get("const")]
    assert set(allowed) == {"avoid", "prefer", "require"}


def bare_deps() -> GeneratorDeps:
    return GeneratorDeps(
        member_id="m1",
        duration_min=45,
        graph=None,  # type: ignore[arg-type]
        concept_index=None,  # type: ignore[arg-type]
    )


def test_timing_wrapper_stamps_the_events_a_call_appends() -> None:
    """Without the stamps every tool span sits at offset 0 for 0 ms and the
    trace waterfall conveys no sequencing at all."""
    import time

    from agents.workout_generator.belt import _timed

    deps = bare_deps()
    deps.run_began = time.perf_counter() - 0.05

    def tool(ctx) -> str:
        time.sleep(0.002)
        ctx.deps.tool_log.append(ProvenanceEvent(kind=ProvenanceKind.MEMBER_SNAPSHOT))
        ctx.deps.tool_log.append(ProvenanceEvent(kind=ProvenanceKind.CONCEPT_RESOLUTION))
        return "ok"

    assert _timed(tool)(SimpleNamespace(deps=deps)) == "ok"
    assert len(deps.tool_log) == 2
    for event in deps.tool_log:
        assert event.started_ms >= 40, "offset measured from the run anchor"
        assert event.duration_ms >= 1, "duration covers the tool body"


def test_timing_wrapper_leaves_earlier_events_alone() -> None:
    """Re-stamping the whole log would overwrite the clinical envelope's
    timing with the last tool's."""
    import time

    from agents.workout_generator.belt import _timed

    deps = bare_deps()
    deps.run_began = time.perf_counter()
    deps.tool_log.append(
        ProvenanceEvent(
            kind=ProvenanceKind.CLINICAL_ENVELOPE, started_ms=1.0, duration_ms=2.0
        )
    )

    def tool(ctx) -> None:
        ctx.deps.tool_log.append(ProvenanceEvent(kind=ProvenanceKind.MEMBER_SNAPSHOT))

    _timed(tool)(SimpleNamespace(deps=deps))
    assert deps.tool_log[0].started_ms == 1.0
    assert deps.tool_log[0].duration_ms == 2.0


def test_timing_wrapper_without_anchor_measures_from_the_call() -> None:
    """A bare-tool test with no generate() run must not stamp offsets in the
    hours — perf_counter's epoch is arbitrary."""
    from agents.workout_generator.belt import _timed

    deps = bare_deps()

    def tool(ctx) -> None:
        ctx.deps.tool_log.append(ProvenanceEvent(kind=ProvenanceKind.MEMBER_SNAPSHOT))

    _timed(tool)(SimpleNamespace(deps=deps))
    assert deps.tool_log[0].started_ms == 0.0
