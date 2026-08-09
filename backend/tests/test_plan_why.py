import pytest

from graph.driver import graph_session
from plan.families import role_of
from plan.queries import movement_facts
from plan.why import ReasonKind, reasons_for
from safety.constraints import compose
from safety.evidence import SignalKind
from safety.filter import run
from safety.standing import load_standing

MEMBER = "mbr_01HX9JORDAN"


@pytest.fixture(scope="module")
def session():
    """One Neo4j session for the whole module."""
    with graph_session() as open_session:
        yield open_session


@pytest.fixture(scope="module")
def result(session):
    """The sample member's verdicts under her standing constraints alone."""
    return run(session, compose(load_standing(session, MEMBER), ()))


@pytest.fixture(scope="module")
def facts(session):
    """Catalog facts for every exercise."""
    return movement_facts(session, MEMBER)


def reasons(result, facts, name: str, **kwargs):
    """Every reason for one exercise by name."""
    verdict = next(v for v in result.verdicts if v.name == name)
    movement = facts[verdict.exercise_id]
    return reasons_for(verdict, movement, role_of(movement.patterns), **kwargs)


def kinds(items) -> set[ReasonKind]:
    """The distinct kinds present."""
    return {reason.kind for reason in items}


def test_the_first_six_kinds_are_signalkind_exactly() -> None:
    """`Reason` widens a `Signal` with no mapping table between them.

    The console's `ReasonKind` mirrors this enum and the payload carries the
    raw string, so a value that drifts here renders as an unknown kind there —
    and `Reason.of` would fail validation on a signal the filter still emits.
    """
    assert [kind.value for kind in ReasonKind][: len(SignalKind)] == [
        kind.value for kind in SignalKind
    ]


class TestNeverEmpty:
    """The contract the frontend states: `why` is never empty."""

    def test_every_eligible_movement_has_a_reason(self, result, facts) -> None:
        """A movement in a plan with no stated reason is unexplainable.

        The gap is not hypothetical: the filter only emits evidence against
        things, so before positive reasons existed the *best-ranked* exercises
        came back with the emptiest justification.
        """
        for verdict in result.eligible:
            movement = facts[verdict.exercise_id]
            assert reasons_for(verdict, movement, role_of(movement.patterns))

    def test_a_clean_unremarkable_movement_still_explains_itself(self, result, facts) -> None:
        """`Alternating Dumbbell Overhead Press` has no signals and no goal.

        Nothing contraindicates it, nothing cautions it, no goal reaches it —
        the filter has nothing to say about it at all. It still has to answer
        "why this one".
        """
        found = reasons(result, facts, "Alternating Dumbbell Overhead Press")
        assert kinds(found) == {
            ReasonKind.CLEARED,
            ReasonKind.EQUIPMENT_FIT,
            ReasonKind.PATTERN_ROLE,
        }

    def test_a_goal_serving_movement_names_the_goal_and_the_muscle(
        self, result, facts
    ) -> None:
        """"Suits her goals" is not auditable; the shared muscle is.

        The traversal a coach can check is goal to muscle to exercise, so the
        path carries both hops rather than the conclusion.
        """
        found = reasons(result, facts, "Dumbbell Goblet Split Squat")
        goal = next(r for r in found if r.kind is ReasonKind.GOAL_SERVICE)
        assert "quads" in goal.detail or "glutes" in goal.detail
        assert goal.path.entry.startswith(("Build", "Return"))
        assert [hop.to_name for hop in goal.path.hops][-1] == "(this)"


class TestSafetyClaim:
    """`CLEARED` is a claim, so it must not be made loosely."""

    def test_a_cautioned_movement_is_not_reported_cleared(self, result, facts) -> None:
        """Saying both "cautioned" and "cleared" reads as contradiction.

        The split squats are the member's only cautioned survivors, and they
        are exactly what a coach will scrutinise.
        """
        found = reasons(result, facts, "Dumbbell Goblet Split Squat")
        assert ReasonKind.CAUTION in kinds(found)
        assert ReasonKind.CLEARED not in kinds(found)

    def test_the_filters_own_signals_survive_widening(self, result, facts) -> None:
        """The caution keeps the clinician's words, not a paraphrase.

        `detail` is authored in `contraindications.json`; regenerating it here
        would put a language model's sentence where a clinician's belongs.
        """
        found = reasons(result, facts, "Dumbbell Goblet Split Squat")
        caution = next(r for r in found if r.kind is ReasonKind.CAUTION)
        assert "time under tension" in caution.detail


class TestFocus:
    """Muscles the request asked to emphasise."""

    def test_a_focus_match_is_reported_when_the_muscle_is_trained(
        self, result, facts
    ) -> None:
        """The spec's first example prompt asks for work around the pecs.

        Without this the request resolves, changes nothing, and says nothing —
        which reads as the emphasis having been ignored.
        """
        found = reasons(
            result, facts, "Dumbbell Neutral-Grip Bench Press", focus=frozenset({"chest"})
        )
        assert ReasonKind.FOCUS_MATCH in kinds(found)

    def test_no_focus_match_when_the_muscle_is_absent(self, result, facts) -> None:
        """An emphasis must not be claimed by movements that do not serve it."""
        found = reasons(
            result, facts, "Dumbbell Goblet Split Squat", focus=frozenset({"chest"})
        )
        assert ReasonKind.FOCUS_MATCH not in kinds(found)


def test_equipment_fit_distinguishes_bodyweight_from_equipped(result, facts) -> None:
    """"Needs no equipment" and "needs a dumbbell she has" are different facts.

    Equipment removes twenty-six of her thirty-three dropped movements, so how
    a survivor cleared that filter is worth stating precisely.
    """
    bodyweight = reasons(result, facts, "Walking Toe Touches")
    equipped = reasons(result, facts, "Dumbbell Goblet Split Squat")
    assert "no equipment" in next(
        r for r in bodyweight if r.kind is ReasonKind.EQUIPMENT_FIT
    ).detail
    assert "Dumbbell" in next(
        r for r in equipped if r.kind is ReasonKind.EQUIPMENT_FIT
    ).detail


def test_pattern_role_names_the_pattern_that_placed_it(result, facts) -> None:
    """Listing every pattern would imply they all decided the section.

    `Push-Up to Knee-Drive` claims two core patterns and one push; only the
    push put it in the main block as pressing work.
    """
    found = reasons(result, facts, "Push-Up to Knee-Drive")
    role = next(r for r in found if r.kind is ReasonKind.PATTERN_ROLE)
    assert "upper push - horizontal" in role.detail
    assert len(role.path.hops) == 1
