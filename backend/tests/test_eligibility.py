from catalog.cards import ExerciseCard
from catalog.eligibility import ExclusionCause, apply
from constraints.models import Constraint, ConstraintSet, Effect, Origin


def card(
    name: str,
    patterns: tuple[str, ...] = ("movement_pattern:push",),
    muscles: tuple[str, ...] = ("muscle:chest",),
    equipment: tuple[str, ...] = ("equipment:Dumbbell",),
    joints: tuple[str, ...] = ("anatomy:shoulder",),
    disliked: bool = False,
) -> ExerciseCard:
    return ExerciseCard(
        concept_id=f"exercise:{name}",
        name=name,
        patterns=patterns,
        muscles=muscles,
        equipment_required=equipment,
        missing_equipment=(),
        joints=joints,
        is_reps=True,
        is_duration=False,
        estimated_rep_seconds=4.0,
        is_bilateral=True,
        side=None,
        supports_weight=True,
        disliked=disliked,
        goal_overlap=(),
    )


def declared(*constraints: Constraint) -> ConstraintSet:
    return ConstraintSet(constraints=constraints)


def c(target: str, effect: Effect, reason: str = "coach said") -> Constraint:
    return Constraint(target=target, effect=effect, origin=Origin.COACH, reason=reason)


def test_avoid_on_own_id_excludes() -> None:
    """An avoided exercise never appears as eligible.

    If it did, "never selectable" would be a lie and the validator the only
    line of defense.
    """
    result = apply((card("X"),), declared(c("exercise:X", Effect.AVOID, "no X")))
    assert result.eligible == ()
    (record,) = result.excluded
    assert record.cause is ExclusionCause.AVOIDED
    assert record.matched_target == "exercise:X"
    assert record.reason == "no X"


def test_avoid_on_a_facet_excludes_every_carrier() -> None:
    """Avoiding a pattern excludes every exercise of that pattern.

    This is the graph expansion declare_constraints deferred — a coach's
    "no plyometrics" must reach exercises, not just the pattern node.
    """
    jumping = card("Jump Squat", patterns=("movement_pattern:plyometric",))
    lifting = card("Goblet Squat", patterns=("movement_pattern:squat",))
    result = apply(
        (jumping, lifting),
        declared(c("movement_pattern:plyometric", Effect.AVOID, "no jumping")),
    )
    assert [e.concept_id for e in result.eligible] == ["exercise:Goblet Squat"]
    (record,) = result.excluded
    assert record.concept_id == "exercise:Jump Squat"
    assert record.matched_target == "movement_pattern:plyometric"


def test_every_hit_gets_its_own_record() -> None:
    """A card excluded three ways carries three records, no arbitration.

    Provenance answers "why is this out" completely; picking one winning
    cause would hide the others from the trace.
    """
    target = card("X", patterns=("movement_pattern:p",), disliked=True)
    result = apply(
        (target,),
        declared(
            c("exercise:X", Effect.AVOID, "by name"),
            c("movement_pattern:p", Effect.AVOID, "by pattern"),
        ),
    )
    assert len(result.excluded) == 3
    assert {r.cause for r in result.excluded} == {
        ExclusionCause.AVOIDED,
        ExclusionCause.DISLIKED,
    }


def test_dislike_excludes_by_default() -> None:
    """A disliked exercise is out without any declaration."""
    result = apply((card("X", disliked=True),), declared())
    assert result.eligible == ()
    (record,) = result.excluded
    assert record.cause is ExclusionCause.DISLIKED
    assert record.reason == ""


def test_exact_require_overrides_a_dislike() -> None:
    """The coach requiring the exact exercise wins over the member's dislike.

    Coach authority over member preference — but the card still says
    disliked, so the model can flag the override in coach_notes.
    """
    result = apply(
        (card("X", disliked=True),), declared(c("exercise:X", Effect.REQUIRE))
    )
    (eligible,) = result.eligible
    assert eligible.disliked is True
    assert eligible.required_because == ("exercise:X",)
    assert result.excluded == ()


def test_pattern_require_does_not_override_a_dislike() -> None:
    """Requiring a pattern does not force a disliked exercise of that pattern.

    Other exercises can satisfy the pattern; the dislike stands.
    """
    disliked = card("X", patterns=("movement_pattern:p",), disliked=True)
    other = card("Y", patterns=("movement_pattern:p",))
    result = apply((disliked, other), declared(c("movement_pattern:p", Effect.REQUIRE)))
    assert [e.concept_id for e in result.eligible] == ["exercise:Y"]
    assert result.unmatched_requires == ()


def test_coach_avoid_beats_coach_require_and_surfaces_the_conflict() -> None:
    """Avoid and require colliding on one card excludes it and reports it.

    Silently ranking coach against coach would honor one directive by
    ignoring the other; unmatched_requires makes the conflict the model's
    problem to raise, before composing.
    """
    jumping = card("Jump Squat", patterns=("movement_pattern:plyometric",))
    result = apply(
        (jumping,),
        declared(
            c("movement_pattern:plyometric", Effect.AVOID, "no jumping"),
            c("exercise:Jump Squat", Effect.REQUIRE, "coach wants it"),
        ),
    )
    assert result.eligible == ()
    assert result.unmatched_requires == ("exercise:Jump Squat",)


def test_prefer_annotates_and_never_excludes() -> None:
    """PREFER is a bias: matching cards are marked, others stay eligible."""
    glutey = card("Hip Lift", muscles=("muscle:glutes",))
    other = card("Bench Press")
    result = apply((glutey, other), declared(c("muscle:glutes", Effect.PREFER)))
    assert len(result.eligible) == 2
    by_id = {e.concept_id: e for e in result.eligible}
    assert by_id["exercise:Hip Lift"].preferred_because == ("muscle:glutes",)
    assert by_id["exercise:Bench Press"].preferred_because == ()


def test_require_matching_nothing_lands_in_unmatched() -> None:
    """A require no card can satisfy is reported before composition.

    The plan validator would bounce the finished plan otherwise; the model
    needs to know re-declaration is the only exit before it composes.
    """
    result = apply((card("X"),), declared(c("exercise:Nonexistent", Effect.REQUIRE)))
    assert result.unmatched_requires == ("exercise:Nonexistent",)


def test_missing_equipment_never_excludes() -> None:
    """Equipment gaps are annotations; the member improvises, the model judges."""
    gappy = card("X").model_copy(update={"missing_equipment": ("equipment:Barbell",)})
    result = apply((gappy,), declared())
    assert len(result.eligible) == 1


def test_ordering_is_deterministic() -> None:
    """Same inputs, same output, byte for byte — provenance depends on it."""
    cards = (card("B", disliked=True), card("A", disliked=True))
    assert apply(cards, declared()) == apply(cards, declared())
    result = apply(cards, declared())
    assert [x.concept_id for x in result.excluded] == sorted(
        x.concept_id for x in result.excluded
    )
