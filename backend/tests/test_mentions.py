import pytest

from graph.schema import NodeLabel
from resolve.mentions import UNSAFE_CANONICAL_SURFACES, scan
from resolve.normalize import normalize
from resolve.resolver import Pass
from resolve.vocabulary import Alias, Concept, Vocabulary

# The scanner's behaviour is a property of itself and of `aliases.json`, not of
# the store, so these run with no Neo4j and no embedding model. That the real
# member's four messages produce the expected edges is asserted in
# test_kg2_build.py, against the real vocabulary.

_NAMES: list[tuple[NodeLabel, str]] = [
    (NodeLabel.MOVEMENT_PATTERN, "car"),
    (NodeLabel.MOVEMENT_PATTERN, "core - rotation"),
    # Unambiguous, and its head token is the Muscle `core` — the pair the
    # longest-window test needs.
    (NodeLabel.MOVEMENT_PATTERN, "core - anti-extension"),
    (NodeLabel.MOVEMENT_PATTERN, "lower push - squat"),
    (NodeLabel.ANATOMICAL_STRUCTURE, "hip"),
    (NodeLabel.ANATOMICAL_STRUCTURE, "knee"),
    (NodeLabel.ANATOMICAL_STRUCTURE, "lumbar spine"),
    (NodeLabel.MUSCLE, "core"),
    (NodeLabel.MUSCLE, "lower back"),
    (NodeLabel.EQUIPMENT, "Barbell"),
    (NodeLabel.EQUIPMENT, "Dumbbell"),
    (NodeLabel.EQUIPMENT, "Kettlebell"),
    (NodeLabel.EXERCISE, "Push-Up to Knee-Drive"),
    # Collides with the `core - rotation` pattern once both are normalised,
    # which is what makes the ambiguity tests below reachable.
    (NodeLabel.EXERCISE, "Core Rotation"),
]

_ALIASES: list[tuple[str, str, NodeLabel]] = [
    ("db", "Dumbbell", NodeLabel.EQUIPMENT),
    ("dbs", "Dumbbell", NodeLabel.EQUIPMENT),
    ("squats", "lower push - squat", NodeLabel.MOVEMENT_PATTERN),
    ("lower back", "lumbar spine", NodeLabel.ANATOMICAL_STRUCTURE),
    ("lower back", "lower back", NodeLabel.MUSCLE),
]


@pytest.fixture(scope="module")
def vocabulary() -> Vocabulary:
    """A vocabulary holding the collisions this module is about."""
    return Vocabulary(
        concepts=[
            Concept(name=name, label=label, normalized=normalize(name).text)
            for label, name in _NAMES
        ],
        aliases=[
            Alias(term=term, canonical=canonical, label=label, note="test fixture")
            for term, canonical, label in _ALIASES
        ],
    )


def test_unsafe_canonical_surface_does_not_match(vocabulary: Vocabulary) -> None:
    """`car` the movement pattern must not match `car` the noun.

    Without the guard every message mentioning a car links to Standing Miniband
    Hip Flexion, and a coach asking what movements the member has written about
    gets a controlled articular rotation she never did. Asserts the concept is
    present, so this proves the guard rather than an absent vocabulary entry.
    """
    assert "car" in {c.normalized for c in vocabulary.concepts}
    result = scan("Left the car at the shop, so I trained at home", vocabulary)
    assert "car" not in result.names


def test_short_alias_beats_the_guard(vocabulary: Vocabulary) -> None:
    """A two-character authored alias resolves where a three-character name cannot.

    This is the pair that rules out a length floor. `db` is shorter than `car`
    and must match, because an author wrote down that it means Dumbbell; `car`
    is longer and must not, because nobody did. If the guard ever became a
    length rule, the member's own shorthand for her only weights would stop
    resolving and her equipment constraint would lose its citation.
    """
    result = scan("Just a db today", vocabulary)
    assert result.names == ("Dumbbell",)
    assert result.mentions[0].matched_by is Pass.ALIAS


def test_equipment_message_yields_its_three_concepts(vocabulary: Vocabulary) -> None:
    """The member's own words about her kit reach all three equipment concepts.

    This is the sentence the limited-equipment scenario rests on
    (ASSESSMENT.md:31). If it stops matching, the equipment constraint is still
    correct but no longer traceable to the message where she stated it, and the
    copilot loses the citation that makes the answer grounded rather than
    asserted.
    """
    result = scan("Still no barbell at home btw — only DBs and a kettlebell.", vocabulary)
    assert set(result.names) == {"Barbell", "Dumbbell", "Kettlebell"}


def test_ambiguous_surface_is_reported_not_guessed(vocabulary: Vocabulary) -> None:
    """A surface with two readings produces no edge, and says so.

    `lower back` is a Muscle and, by alias, the lumbar spine. Picking one would
    make half the mentions of it wrong while looking clean, so the scanner
    declines and reports — the same discipline the resolver applies.
    """
    result = scan("Her lower back was tight afterwards", vocabulary)
    assert result.mentions == ()
    assert result.ambiguous == ("lower back",)


def test_ambiguous_surface_is_consumed_not_retried(vocabulary: Vocabulary) -> None:
    """Declining a window must not fall back to a shorter one inside it.

    `core rotation` matches both a pattern and an exercise, so it is ambiguous.
    `core` alone is an unambiguous Muscle. If the ambiguous branch did not
    consume its tokens, the scanner would decline the two-token reading and then
    immediately commit to the one-token one — silently choosing after saying it
    could not.
    """
    result = scan("core rotation drills", vocabulary)
    assert result.ambiguous == ("core rotation",)
    assert "core" not in result.names


def test_longest_window_wins(vocabulary: Vocabulary) -> None:
    """A multi-token concept beats a single-token one nested inside it.

    `core - anti-extension` starts with the token `core`, which is itself a
    Muscle. Shortest-first would report the muscle and drop the pattern —
    asserting something more general than the text said, and losing the only
    concept in the sentence that names a class of movement.
    """
    result = scan("core anti-extension work today", vocabulary)
    assert result.names == ("core - anti-extension",)
    assert "core" not in result.names


def test_canonical_name_containing_filler_still_matches(vocabulary: Vocabulary) -> None:
    """`Push-Up to Knee-Drive` matches even though `to` is a filler word.

    Both the vocabulary and the passage are normalised, so filler is absent from
    each. Normalising only one side would make every multi-word name containing
    a preposition permanently unreachable.
    """
    result = scan("She managed a push-up to knee-drive", vocabulary)
    assert result.names == ("Push-Up to Knee-Drive",)


def test_label_restriction_narrows_the_pool(vocabulary: Vocabulary) -> None:
    """A caller that only wants equipment does not get anatomy."""
    text = "knee felt fine with the kettlebell"
    assert set(scan(text, vocabulary).names) == {"knee", "Kettlebell"}
    restricted = scan(text, vocabulary, frozenset({NodeLabel.EQUIPMENT}))
    assert restricted.names == ("Kettlebell",)


def test_passage_naming_nothing_is_empty_not_an_error(vocabulary: Vocabulary) -> None:
    """Most messages mention no concept at all, and that is the normal case.

    The skipped-session message is the one in the sample that should yield
    nothing. If it produced a mention, the graph would claim the member wrote
    about a movement when she wrote about her workload.
    """
    result = scan("Skipped Thursday, work blew up and I was wiped. Sorry!", vocabulary)
    assert result.mentions == ()
    assert result.ambiguous == ()


def test_unsafe_surfaces_are_all_real_concepts(vocabulary: Vocabulary) -> None:
    """Every guarded surface names something, so the guard cannot rot.

    A typo in `UNSAFE_CANONICAL_SURFACES` would silently guard nothing and let
    the collision back in. This pins the entries against the vocabulary that
    actually holds them.
    """
    normalized = {c.normalized for c in vocabulary.concepts}
    assert UNSAFE_CANONICAL_SURFACES <= normalized
