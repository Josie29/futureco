import ast
from pathlib import Path

import pytest

import plan.schemas
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
        side=exercise.side,
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

        Seven rows carry `0` seconds and eight are `is_reps: false`. Keying on
        the zero alone divides by it for seven and prescribes nine reps of
        `Kneeling Stability Ball Lat Stretch` for the eighth.
        """
        for exercise in exercises:
            if exercise.is_reps and exercise.estimated_rep_seconds:
                continue
            dose = prescribe(facts_for(exercise), role_of(tuple(exercise.movement_patterns)), 2)
            assert dose.reps is None, exercise.name
            assert dose.hold_seconds, exercise.name

    def test_the_disagreeing_row_is_read_as_a_hold(self, exercises) -> None:
        """`Kneeling Stability Ball Lat Stretch` is 5.0 seconds and not counted.

        The one row where the two markers disagree. Trusting the cadence over
        `is_reps` turns a stretch into a nine-rep set.
        """
        dose = prescribe(named(exercises, "Kneeling Stability Ball Lat Stretch"),
                         role_of(("mobility - dynamic", "regen")), 2)
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
        one_side = facts.model_copy(update={"side": None})
        role = role_of(facts.patterns)
        assert prescribe(facts, role, 2).work_seconds == 2 * prescribe(one_side, role, 2).work_seconds

    def test_per_side_reads_side_not_is_bilateral(self, exercises) -> None:
        """`is_bilateral` is inverted in this data — true on the single-side rows.

        Reading it directly would time every unilateral exercise at half its
        real cost and every bilateral one at double.
        """
        for exercise in exercises:
            assert facts_for(exercise).per_side == (exercise.side is not None)

    def test_rest_is_counted_after_every_set(self, exercises) -> None:
        """The final rest is the transition to the next exercise.

        Dropping it makes block times non-additive, so a section's blocks stop
        summing to the section's cost and the fill ratio drifts.
        """
        facts = named(exercises, "Dumbbell Neutral-Grip Bench Press")
        dose = prescribe(facts, role_of(facts.patterns), 3)
        assert dose.total_seconds == 3 * (dose.work_seconds + dose.rest_seconds)


def references(tree: ast.AST, name: str) -> bool:
    """Whether the parsed source reads `name` as a field, key or argument.

    Parsed rather than grepped so the modules can explain in prose why they
    avoid the field without tripping their own guard.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == name
        ):
            return True
        if isinstance(node, ast.keyword) and node.arg == name:
            return True
    return False


def test_the_plan_package_never_reads_is_bilateral() -> None:
    """The known-inverted field must not creep back in.

    It reads like the right field, and using it would invert the timing of
    every unilateral movement in the catalog — halving some blocks and
    doubling others, with the session total still looking plausible.
    """
    for path in Path(plan.schemas.__file__).parent.glob("*.py"):
        assert not references(ast.parse(path.read_text()), "is_bilateral"), path.name
