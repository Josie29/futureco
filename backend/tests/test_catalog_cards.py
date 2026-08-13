import pytest
from neo4j import Session

from catalog.cards import ExerciseCard, load_cards
from graph.driver import graph_session
from resolver.index import ConceptIndex

MEMBER = "mbr_01HX9JORDAN"


@pytest.fixture(scope="module")
def session():
    with graph_session() as s:
        yield s


@pytest.fixture(scope="module")
def cards(session: Session) -> tuple[ExerciseCard, ...]:
    return load_cards(session, MEMBER)


def test_the_whole_catalog_arrives_ordered(cards: tuple[ExerciseCard, ...]) -> None:
    """All 50 exercises, ordered by name, every time.

    A missing card is an exercise the agent can never plan or explain; an
    unstable order makes traces incomparable across runs.
    """
    assert len(cards) == 50
    assert [c.name for c in cards] == sorted(c.name for c in cards)


def test_every_carried_id_is_resolver_currency(
    session: Session, cards: tuple[ExerciseCard, ...]
) -> None:
    """Every concept id on every card is one the resolver's index holds.

    Cards feed constraints and citations; an id the index cannot produce
    breaks the first tool that accepts it.
    """
    index = ConceptIndex.load(session)
    carried = {cid for card in cards for cid in card.facet_ids}
    unknown = [cid for cid in carried if not index.has(cid)]
    assert not unknown, f"card ids the resolver cannot produce: {unknown}"


def test_patterns_match_the_graph_edges_primary_first(
    session: Session, cards: tuple[ExerciseCard, ...]
) -> None:
    """The ordered pattern property agrees with the is_a edges.

    Cards read the node property for its primary-first order; if it drifted
    from the edges, retrieval and traversal would disagree about what an
    exercise is.
    """
    rows = session.run(
        "MATCH (e:Exercise)-[:is_a]->(p:MovementPattern) "
        "RETURN e.name AS name, collect(p.name) AS linked"
    )
    linked = {row["name"]: set(row["linked"]) for row in rows}
    for card in cards:
        names = {p.removeprefix("movement_pattern:") for p in card.patterns}
        assert names == linked[card.name], card.name
    assert all(card.patterns for card in cards)


def test_missing_equipment_is_a_subset_disjoint_from_owned(
    session: Session, cards: tuple[ExerciseCard, ...]
) -> None:
    """missing_equipment is exactly required-minus-owned.

    Wrong in either direction, the model either invents a gap she doesn't
    have or plans an implement she lacks without knowing.
    """
    rows = session.run(
        "MATCH (:Member {id: $member_id})-[:has]->(q:Equipment) RETURN q.name AS name",
        member_id=MEMBER,
    )
    owned = {f"equipment:{row['name']}" for row in rows}
    for card in cards:
        assert set(card.missing_equipment) <= set(card.equipment_required)
        assert not set(card.missing_equipment) & owned


def test_disliked_flags_exactly_the_dislike_edges(
    session: Session, cards: tuple[ExerciseCard, ...]
) -> None:
    """The disliked flag mirrors the member's dislikes edges, exactly."""
    rows = session.run(
        "MATCH (:Member {id: $member_id})-[:dislikes]->(x:Exercise) RETURN x.name AS name",
        member_id=MEMBER,
    )
    disliked = {row["name"] for row in rows}
    assert {c.name for c in cards if c.disliked} == disliked
    assert len(disliked) == 2


def test_goal_overlap_only_where_a_goal_targets_a_card_muscle(
    cards: tuple[ExerciseCard, ...],
) -> None:
    """Goal overlap rows carry the shared muscle the graph actually walked."""
    overlapping = [c for c in cards if c.goal_overlap]
    assert overlapping, "some exercises must serve her muscle goals"
    for card in overlapping:
        for overlap in card.goal_overlap:
            assert overlap.muscle in card.muscles
            assert overlap.priority >= 1


def test_missing_member_raises(session: Session) -> None:
    """An unknown member is an error, never an empty catalog."""
    with pytest.raises(ValueError, match="not in the graph"):
        load_cards(session, "mbr_nobody")


def test_no_node_id_currency_leaks(cards: tuple[ExerciseCard, ...]) -> None:
    """Cards speak concept-id currency only — no graph uuids anywhere."""
    for card in cards:
        assert card.concept_id == f"exercise:{card.name}"
        for facet in card.facet_ids:
            namespace, _, rest = facet.partition(":")
            assert namespace in {
                "exercise", "muscle", "equipment", "movement_pattern", "anatomy"
            }
            assert rest
