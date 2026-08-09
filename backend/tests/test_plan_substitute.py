import pytest

from graph.driver import graph_session
from plan.families import deciding_pattern
from plan.queries import movement_facts
from plan.substitute import SUBSTITUTABLE, substitutions
from plan.why import ReasonKind
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


@pytest.fixture(scope="module")
def subs(session, result, facts):
    """Every substitution offered for the baseline request."""
    return substitutions(session, result, facts)


def for_name(subs, name: str):
    """The substitution offered for one dropped exercise."""
    return next(s for s in subs if s.dropped_name == name)


class TestSafetyBoundary:
    """The property that makes substitution safe at all."""

    def test_every_replacement_is_an_eligible_verdict(self, result, subs) -> None:
        """A stand-in the filter never cleared is a hole straight through it.

        Substitution runs outside `filter.run`, so nothing else stops it
        proposing a movement the member must not perform. The intersection
        with `eligible` is the whole guarantee.
        """
        eligible = {v.exercise_id for v in result.eligible}
        for substitution in subs:
            if substitution.satisfied:
                assert substitution.replacement_id in eligible, substitution.dropped_name

    def test_a_contraindicated_sibling_is_never_offered(self, result, subs) -> None:
        """The plyometrics share patterns with movements she can do.

        If eligibility were checked after ranking rather than before, a
        contraindicated jump could be offered as the closest match to a
        dropped one — the exact failure the clinical rule exists to prevent.
        """
        excluded = {v.exercise_id for v in result.verdicts if not v.eligible}
        assert not {s.replacement_id for s in subs if s.satisfied} & excluded

    def test_only_circumstantial_removals_are_substituted(self, result, subs) -> None:
        """A contraindication is not a circumstance to work around.

        Offering an alternative to a clinically excluded movement invites the
        coach to treat the exclusion as negotiable. A dislike is the member's
        own standing preference and equally not ours to route around.
        """
        assert {s.cause for s in subs} <= SUBSTITUTABLE
        by_id = {v.exercise_id: v for v in result.verdicts}
        for substitution in subs:
            signals = {s.kind for s in by_id[substitution.dropped_id].signals}
            assert SignalKind.CONTRAINDICATION not in signals, substitution.dropped_name


class TestPatternAxis:
    """Which movements count as the same movement."""

    def test_a_stand_in_shares_the_deciding_pattern(self, subs, facts) -> None:
        """Matching any shared pattern lets a peripheral one drive the swap.

        `Med Ball Hamstring Walkout` and `High Plank Bird Dog` both resist
        rotation, so before this the hinge came back offered as a bird dog.
        """
        for substitution in subs:
            if not substitution.satisfied:
                continue
            dropped = deciding_pattern(facts[substitution.dropped_id].patterns)
            assert substitution.shared_pattern == dropped, substitution.dropped_name
            assert substitution.shared_pattern in facts[substitution.replacement_id].patterns

    def test_the_hinge_has_no_stand_in(self, subs) -> None:
        """The only other hip lift is the one she has recorded as disliked.

        Reporting that honestly is the point — the near-miss it used to offer
        was a core exercise, which does not train a hinge at all.
        """
        assert not for_name(subs, "Med Ball Hamstring Walkout").satisfied


class TestWorkedCases:
    """The two outcomes the README quotes."""

    def test_the_split_squat_is_substituted(self, subs) -> None:
        """The limited-equipment scenario, resolving.

        `ASSESSMENT.md:31` asks for a swap when equipment is missing, and this
        is the one the catalog can honestly make.
        """
        substitution = for_name(subs, "Med Ball Split Squat")
        assert substitution.replacement_name == "Dumbbell Goblet Split Squat"
        assert substitution.shared_pattern == "lower push - split squat"
        assert substitution.cause is SignalKind.MISSING_EQUIPMENT

    def test_the_squat_has_no_stand_in(self, subs) -> None:
        """This catalog holds no squat she can perform.

        Saying so beats offering a lunge as if it were a squat — and the
        empty answer is the one a coach can act on, by finding a barbell.
        """
        assert not for_name(subs, "Kettlebell Goblet Cyclist Squat").satisfied


def test_a_substitution_explains_itself_as_a_reason(subs) -> None:
    """The stand-in has to say whose place it is taking.

    A movement that appears because another was dropped is otherwise
    indistinguishable from one chosen on its own merits.
    """
    reason = for_name(subs, "Med Ball Split Squat").reason()
    assert reason.kind is ReasonKind.SUBSTITUTION
    assert "Med Ball Split Squat" in reason.detail
    assert "lower push - split squat" in reason.detail
    assert reason.path.hops[-1].to_name == "Dumbbell Goblet Split Squat"


def test_two_runs_are_identical(session, result, facts) -> None:
    """Substitution is part of the plan, so it inherits the same promise."""
    assert substitutions(session, result, facts) == substitutions(session, result, facts)
