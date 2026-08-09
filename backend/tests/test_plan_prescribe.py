import pytest

from graph.build.catalog import load_exercises
from plan.families import role_of
from plan.prescribe import REP_RANGES, SECTION_PLANS, half_up, prescribe
from plan.schemas import MovementFacts, Section
from settings import settings


@pytest.fixture(scope="module")
def exercises():
    """The catalog, read once."""
    return load_exercises(settings.exercises_path)


def facts_for(exercise) -> MovementFacts:
    """The packer's view of one catalog row."""
    return MovementFacts(
        exercise_id=exercise.id,
        patterns=tuple(exercise.movement_patterns),
        rep_seconds=exercise.estimated_rep_seconds,
        is_reps=exercise.is_reps,
        is_bilateral=exercise.is_bilateral,
    )


def named(exercises, name: str) -> MovementFacts:
    """One catalog row by name, as movement facts."""
    return facts_for(next(e for e in exercises if e.name == name))


class TestRounding:
    """The rounding rule, pinned because the built-in disagrees with it."""

    @pytest.mark.parametrize(
        ("value", "expected"), [(4.5, 5), (13.5, 14), (0.5, 1), (4.4, 4), (13.6, 14)]
    )
    def test_halves_round_up(self, value: float, expected: int) -> None:
        """`round` is banker's rounding and splits identical arithmetic.

        `round(4.5)` is 4 but `round(13.5)` is 14, and two catalog cadences
        land exactly on those halves against a 45-second target — so the
        built-in would give World's Greatest Stretch and Barbell Decline Bench
        Press different treatment under the same rule.
        """
        assert half_up(value) == expected


class TestHolds:
    """Exercises held for time rather than counted."""

    def test_every_non_rep_row_is_held(self, exercises) -> None:
        """A stretch must never be prescribed in reps.

        All eight `is_reps: false` rows. Counting any of them would divide a
        work target by a zero cadence, and the ones that survived that would
        read as "3 x 12 Cow Pose".
        """
        for exercise in exercises:
            if exercise.is_reps:
                continue
            dose = prescribe(facts_for(exercise), role_of(tuple(exercise.movement_patterns)), 2)
            assert dose.reps is None, exercise.name
            assert dose.hold_seconds, exercise.name

    def test_a_hold_takes_its_duration_from_the_section(self, exercises) -> None:
        """A warmup hold is shorter than a cooldown one, and neither is a rep.

        The catalog says an exercise is held but never for how long, so the
        section table is the only source — and a stretch held for a main-block
        forty seconds in the warmup is a different exercise.
        """
        facts = named(exercises, "Kneeling Stability Ball Lat Stretch")
        role = role_of(facts.patterns)
        assert role.section is Section.WARMUP
        dose = prescribe(facts, role, 2)
        assert dose.reps is None
        assert dose.hold_seconds == SECTION_PLANS[Section.WARMUP].hold_seconds


class TestReps:
    """Turning a cadence into a rep count."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Jump Rope - Single-Leg", 85),
            ("Push-Up to Knee-Drive", 15),
            ("Barbell Decline Bench Press", 14),
            ("Dumbbell Neutral-Grip Bench Press", 9),
            ("World's Greatest Stretch", 5),
        ],
    )
    def test_worked_cadences(self, exercises, name: str, expected: int) -> None:
        """Pins the arithmetic against real catalog rows.

        A change to a section target or a rep range silently rewrites every
        plan; these five span the cadence range from 0.53 to 10.0 seconds.
        """
        facts = named(exercises, name)
        dose = prescribe(facts, role_of(facts.patterns), 3)
        assert dose.reps == expected

    def test_reps_never_leave_the_modality_range(self, exercises) -> None:
        """A fast cadence must not prescribe 85 reps of a bench press.

        Dividing an unclamped target by a 0.53-second cadence is how that
        happens, and nothing downstream would notice.
        """
        for exercise in exercises:
            role = role_of(tuple(exercise.movement_patterns))
            for section in Section:
                dose = prescribe(facts_for(exercise), role.model_copy(update={"section": section}), 2)
                if dose.reps is None:
                    continue
                low, high = REP_RANGES[role.modality]
                assert low <= dose.reps <= high, f"{exercise.name} in {section}"

    def test_the_clamp_decides_half_the_catalog(self, exercises) -> None:
        """The rep range, not the cadence, sets half the prescriptions.

        Pinned as a number because it is the honest description of what
        `estimated_rep_seconds` does: it sets each set's duration, and the
        range sets the reps. Anything that made this rare would mean the
        ranges had widened until they stopped bounding anything.
        """
        rep_based = [e for e in exercises if e.is_reps and e.estimated_rep_seconds]
        clamped = [
            e
            for e in rep_based
            if prescribe(facts_for(e), role_of(tuple(e.movement_patterns)), 2).reps_clamped
        ]
        assert (len(clamped), len(rep_based)) == (21, 42)


class TestTiming:
    """Wall-clock cost, which is what the time solver spends."""

    def test_per_side_doubles_the_work(self, exercises) -> None:
        """A unilateral block costs twice its one-side time.

        Five of the sample member's seventeen eligible are unilateral and they
        are a third of her scheduled seconds. Counting one side makes a
        fifty-minute plan really thirty-three.
        """
        facts = named(exercises, "Dumbbell Goblet Split Squat")
        assert facts.per_side
        both_sides = facts.model_copy(update={"is_bilateral": True})
        role = role_of(facts.patterns)
        assert (
            prescribe(facts, role, 2).work_seconds
            == 2 * prescribe(both_sides, role, 2).work_seconds
        )

    def test_rest_is_counted_after_every_set(self, exercises) -> None:
        """The final rest is the transition to the next exercise.

        Dropping it makes block times non-additive, so a section's blocks stop
        summing to the section's cost and the fill ratio drifts.
        """
        facts = named(exercises, "Dumbbell Neutral-Grip Bench Press")
        dose = prescribe(facts, role_of(facts.patterns), 3)
        assert dose.total_seconds == 3 * (dose.work_seconds + dose.rest_seconds)


class TestCatalogInvariants:
    """What the prescription arithmetic assumes the data guarantees.

    Both held after `decisions.md`, Data cleanup 6 corrected the source. The
    planner reads each field once, with no derived property standing between
    it and the meaning — which is only safe while these hold.
    """

    def test_is_bilateral_agrees_with_side(self, exercises) -> None:
        """A row claiming both sides must not also record one.

        `is_bilateral` was shipped inverted, true on exactly the single-side
        rows. Inverting again would halve the timing of every unilateral
        movement and double every bilateral one, leaving a session total that
        still looks plausible.
        """
        for exercise in exercises:
            assert exercise.is_bilateral == (exercise.side is None), exercise.name

    def test_a_held_exercise_carries_no_cadence(self, exercises) -> None:
        """`is_reps: false` and a zero cadence must mean the same thing.

        They disagreed on one row. While they can, `prescribe` has to test
        both or risk dividing by zero for seven exercises and prescribing
        reps of a stretch for the eighth.
        """
        for exercise in exercises:
            assert exercise.is_reps == bool(exercise.estimated_rep_seconds), exercise.name
