import pytest

from graph.driver import graph_session
from graph.schema import NodeLabel
from graph.vocabulary import Pass
from resolver.core import Thresholds, norm, resolve
from resolver.index import ConceptIndex
from resolver.models import NAMESPACE_LABELS, UNRESOLVABLE_KG1_LABELS, Namespace


@pytest.fixture(scope="session")
def index() -> ConceptIndex:
    """An index over the live graph's vocabulary.

    Session-scoped because loading the index and the embedding model is the
    slow part; resolution itself is in-memory.
    """
    with graph_session() as session:
        return ConceptIndex.load(session)


def test_exact_match_is_certain(index: ConceptIndex) -> None:
    """A canonical name resolves to itself at full confidence.

    The floor of the whole resolver: if "knee" cannot reach knee, no coach
    term reaches anything.
    """
    result = resolve("knee", Namespace.ANATOMY, index)
    assert result.resolved is not None
    assert result.resolved.label == "knee"
    assert result.resolved.method is Pass.EXACT
    assert result.resolved.confidence == 1.0


def test_exact_match_survives_case_and_hyphens(index: ConceptIndex) -> None:
    """Normalisation bridges casing and hyphenation, nothing more.

    "Kettlebell" typed lowercase must still be an exact hit — if it fell
    through to fuzzy, every well-typed term would carry a sub-1.0 confidence
    and the tool would flag clean matches as shaky.
    """
    result = resolve("Kettlebell", Namespace.EQUIPMENT, index)
    assert result.resolved is not None
    assert result.resolved.method is Pass.EXACT
    assert result.resolved.confidence == 1.0


def test_typo_resolves_through_the_fuzzy_pass(index: ConceptIndex) -> None:
    """A near-miss spelling still reaches the concept, marked as fuzzy.

    A coach's "kettlebel" must not dead-end — and provenance must say the
    match was approximate, not certain.
    """
    result = resolve("kettlebel", Namespace.EQUIPMENT, index)
    assert result.resolved is not None
    assert result.resolved.label == "Kettlebell"
    assert result.resolved.method is Pass.FUZZY
    assert result.resolved.confidence < 1.0


def test_unknown_term_declines_with_near_misses(index: ConceptIndex) -> None:
    """A term the catalog cannot honestly claim declines, offering what's close.

    "deadlift" is not in the catalog; latching onto a similar-sounding
    exercise would put a movement in a plan nobody vetted. The near-misses
    are what lets the agent tell the coach what it can offer instead.
    """
    result = resolve("deadlift", Namespace.EXERCISE, index)
    assert result.resolved is None
    assert result.alternatives, "a failed resolve must still rank near-misses"


def test_namespace_restriction_changes_the_pool(index: ConceptIndex) -> None:
    """A scoped call never returns a concept of the wrong kind.

    If scoping leaked, an equipment term could resolve into the exercise
    catalog and the downstream graph tools would traverse from the wrong
    node type.
    """
    result = resolve("lower back", Namespace.MUSCLE, index)
    assert result.resolved is not None
    assert result.resolved.namespace is Namespace.MUSCLE
    anatomy = resolve("lower back", Namespace.ANATOMY, index)
    assert anatomy.resolved is None or anatomy.resolved.namespace is Namespace.ANATOMY


def test_same_namespace_tie_declines_with_all_readings(index: ConceptIndex) -> None:
    """Candidates too close to separate come back as a tie, not a coin toss.

    "press" token-matches every pressing exercise equally; picking one
    silently would put an arbitrary movement in the plan. The alternatives
    feed the tool's ambiguous status so the model can choose with context
    or ask.
    """
    result = resolve("press", Namespace.EXERCISE, index)
    assert result.resolved is None
    assert len(result.alternatives) >= 2
    top_two = result.alternatives[:2]
    assert abs(top_two[0].confidence - top_two[1].confidence) < 0.05


def test_vector_pass_reaches_meaning(index: ConceptIndex) -> None:
    """When spelling fails, embeddings still rank the right concept first.

    Forcing the fuzzy pass off proves the vector pass works end to end —
    the pass that will carry paraphrases once thresholds are re-swept.
    """
    floors = Thresholds(fuzzy=1.01, vector=0.0, ambiguity_margin=0.0)
    result = resolve("kettlebel", Namespace.EQUIPMENT, index, floors)
    assert result.resolved is not None
    assert result.resolved.method is Pass.VECTOR
    assert result.resolved.label == "Kettlebell"


def test_empty_term_resolves_to_nothing(index: ConceptIndex) -> None:
    """Input that normalises to nothing declines cleanly instead of scoring.

    Scoring an empty string would hand the fuzzy pass whatever concept
    happens to rank highest on noise.
    """
    result = resolve("  -  ", None, index)
    assert result.resolved is None
    assert result.alternatives == ()


def test_every_kg1_label_is_namespaced_or_deliberately_not() -> None:
    """Every KG1 node type is inside a namespace or explicitly excluded.

    Catches the silent gap where a new node type is added to the graph and
    coach terms can never reach it — or worse, a clinical label becomes
    resolvable without anyone deciding it should be.
    """
    with graph_session() as session:
        rows = session.run(
            "MATCH (n) WHERE n.source = 'kg1' UNWIND labels(n) AS l RETURN DISTINCT l"
        )
        live = {NodeLabel(row["l"]) for row in rows}
    namespaced = {label for labels in NAMESPACE_LABELS.values() for label in labels}
    assert namespaced & UNRESOLVABLE_KG1_LABELS == frozenset(), (
        "a label cannot be both resolvable and excluded"
    )
    assert live == namespaced | UNRESOLVABLE_KG1_LABELS, (
        f"undecided KG1 labels: {sorted(live ^ (namespaced | UNRESOLVABLE_KG1_LABELS))}"
    )


def test_norm_is_minimal() -> None:
    """Normalisation bridges casing, hyphens and whitespace — nothing else.

    Filler words and laterality are the extracting model's job now; if norm
    started eating tokens again, extraction and resolution would fight over
    who owns cleanup.
    """
    assert norm("  Push-Up  to   Knee-Drive ") == "push up to knee drive"
    assert norm("her left knee") == "her left knee"


def test_has_checks_referential_integrity(index: ConceptIndex) -> None:
    """has() answers exactly "is this id real currency".

    Constraint targets and any future id arriving from outside the resolver
    are gated on this; a false positive would let a directive point at
    nothing, a false negative would reject the snapshot's own ids.
    """
    assert index.has("anatomy:knee")
    assert not index.has("muscle:knee")
    assert not index.has("exercise:Invented Movement")
    assert not index.has("knee")
