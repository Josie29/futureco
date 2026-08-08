import pytest

from graph.driver import graph_session
from graph.schema import NodeLabel
from resolve.cases import ResolverCase, load_cases
from resolve.normalize import Side, normalize
from resolve.resolver import Pass, Reason, Resolver
from resolve.vocabulary import Vocabulary
from settings import settings

CASES = load_cases(settings.resolver_cases_path)


@pytest.fixture(scope="session")
def resolver() -> Resolver:
    """A resolver over the live graph's vocabulary.

    Session-scoped because loading the vocabulary and the embedding model is
    the slow part; resolution itself is in-memory.
    """
    with graph_session() as session:
        vocabulary = Vocabulary.load(session, settings.aliases_path)
    return Resolver(vocabulary)


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.term}->{c.expects}")
def test_labelled_case(resolver: Resolver, case: ResolverCase) -> None:
    """Every labelled case resolves as recorded.

    Breaks if a threshold is retuned without re-running the calibration, or if
    an alias is removed that an automatic pass cannot replace. The same file
    drives resolve.calibrate, so the numbers and these assertions cannot drift.
    """
    result = resolver.resolve(case.term, case.labels)
    got = result.match.name if result.match else None
    assert got == case.expects, f"{case.note}\ncandidates: {result.candidates}"
    if case.expects_side is not None:
        assert result.side == case.expects_side


def test_declining_still_offers_candidates(resolver: Resolver) -> None:
    """A term that cannot resolve still reports what was close.

    Breaks the copilot's ability to ask "did you mean...?" — without this a
    coach who mistypes gets a dead end rather than a choice.
    """
    result = resolver.resolve("deadlift")
    assert not result.resolved
    assert result.reason is Reason.BELOW_THRESHOLD
    assert result.candidates, "a failed resolve must still rank near-misses"


def test_label_restriction_changes_the_answer(resolver: Resolver) -> None:
    """The same words reach different concepts depending on the caller's intent.

    This is the whole reason callers pass labels. If restriction stopped
    working, "bad lower back" in an injury context would silently return a
    muscle, and the safety filter would walk the wrong part of the graph.
    """
    muscle = resolver.resolve("lower back", frozenset({NodeLabel.MUSCLE}))
    anatomy = resolver.resolve("lower back", frozenset({NodeLabel.ANATOMICAL_STRUCTURE}))
    assert muscle.match is not None and muscle.match.label is NodeLabel.MUSCLE
    assert anatomy.match is not None and anatomy.match.name == "lumbar spine"

    unrestricted = resolver.resolve("lower back")
    assert not unrestricted.resolved
    assert unrestricted.reason is Reason.AMBIGUOUS


def test_restriction_filters_before_scoring(resolver: Resolver) -> None:
    """A restricted call cannot be dragged off by a wrong-label near-match.

    "squats" scores highly against the Muscle `quads`. Filtering the pool after
    scoring rather than before would let that win and then be discarded,
    leaving nothing — or worse, be returned.
    """
    result = resolver.resolve("squats", frozenset({NodeLabel.MUSCLE}))
    assert not result.resolved
    assert all(c.label is NodeLabel.MUSCLE for c in result.candidates)


def test_every_pass_is_exercised(resolver: Resolver) -> None:
    """The labelled set covers all four passes.

    Guards against a pass quietly becoming dead weight. Calibration found the
    vector pass firing on nothing until three cases were added specifically for
    it; without this test that could recur unnoticed.
    """
    fired = {
        resolver.resolve(case.term, case.labels).match.matched_by
        for case in CASES
        if case.expects is not None
    }
    assert fired == set(Pass), f"no labelled case exercises {set(Pass) - fired}"


def test_empty_after_normalization_declines(resolver: Resolver) -> None:
    """Input that is all filler declines rather than raising or matching."""
    result = resolver.resolve("my really bad pain")
    assert not result.resolved
    assert result.reason is Reason.EMPTY


def test_impossible_restriction_declines(resolver: Resolver) -> None:
    """An empty candidate pool returns cleanly instead of raising."""
    result = resolver.resolve("knee", frozenset({NodeLabel.CONDITION}))
    assert not result.resolved
    assert result.reason is Reason.NO_POOL


def test_filler_words_are_not_canonical_terms(resolver: Resolver) -> None:
    """No filler word is itself a concept name.

    Stripping filler is only safe while none of it is a term someone might
    mean. If a future catalog adds an exercise called "Flare", say, this fails
    rather than silently making that exercise unreachable.
    """
    from resolve.normalize import _FILLER

    names = {concept.normalized for concept in resolver.vocabulary.concepts}
    assert not (_FILLER & names)


@pytest.mark.parametrize(
    ("term", "expected_text", "expected_side"),
    [
        ("her left knee is bothering her", "knee", Side.LEFT),
        ("RIGHT Shoulder", "shoulder", Side.RIGHT),
        ("knee", "knee", None),
        ("Resistance Band - Loop", "resistance band loop", None),
    ],
)
def test_normalization(term: str, expected_text: str, expected_side: Side | None) -> None:
    """Laterality survives normalisation and separators become spaces.

    Side is load-bearing downstream: the recorded injury is left-sided, so a
    right-knee complaint must not match it. Separators becoming spaces rather
    than being deleted is what keeps token-set matching working on names like
    "Resistance Band - Loop".
    """
    result = normalize(term)
    assert result.text == expected_text
    assert result.side == expected_side
