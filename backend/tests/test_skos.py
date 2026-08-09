import pytest
from neo4j import Session

from graph.build.catalog import load_muscles
from graph.driver import graph_session
from graph.schema import NodeLabel
from graph.skos import SCHEME_OF, MatchType, Scheme, collection_of, load_collections
from settings import settings

# The SKOS layer (ASSESSMENT.md:56). These assertions guard the two ways a
# concept mapping goes wrong quietly: a concept that never got one, and a
# mapping that claims more precision than the author actually had.

GROUPED = (NodeLabel.MOVEMENT_PATTERN, NodeLabel.EQUIPMENT)
MAPPED = (NodeLabel.MUSCLE, NodeLabel.ANATOMICAL_STRUCTURE, NodeLabel.CONDITION)


@pytest.fixture(scope="module")
def session() -> Session:
    with graph_session() as open_session:
        yield open_session


def _names(session: Session, label: NodeLabel) -> set[str]:
    return {row["name"] for row in session.run(f"MATCH (n:{label}) RETURN n.name AS name")}


class TestCoverage:
    """Every concept is in a scheme, and none is left half-described."""

    @pytest.mark.parametrize("label", [*GROUPED, *MAPPED])
    def test_every_concept_declares_its_scheme(self, session: Session, label: NodeLabel) -> None:
        """A concept with no scheme is not in a vocabulary, it is just a string.

        Parametrised per label because a build that silently skipped one
        taxonomy would still leave the other four correct.
        """
        rows = session.run(
            f"MATCH (n:{label}) RETURN count(*) AS total, count(n.in_scheme) AS scoped"
        ).single()
        assert rows["total"] > 0
        assert rows["scoped"] == rows["total"]
        scheme = session.run(
            f"MATCH (n:{label}) RETURN DISTINCT n.in_scheme AS scheme"
        ).single()["scheme"]
        assert scheme == SCHEME_OF[label].value

    @pytest.mark.parametrize("label", MAPPED)
    def test_a_mapped_concept_carries_the_whole_mapping(
        self, session: Session, label: NodeLabel
    ) -> None:
        """A code with no relation is unusable — it does not say how it relates.

        The four fields travel together or not at all: a `match_code` without a
        `match_type` reads as an exact mapping to anyone who does not check.
        """
        incomplete = session.run(
            f"""
            MATCH (n:{label})
            WHERE n.match_code IS NULL OR n.match_type IS NULL
               OR n.match_term IS NULL OR n.match_scheme IS NULL
            RETURN collect(n.name) AS names
            """
        ).single()["names"]
        assert incomplete == []

    @pytest.mark.parametrize("label", GROUPED)
    def test_an_ungrounded_concept_claims_no_external_mapping(
        self, session: Session, label: NodeLabel
    ) -> None:
        """Equipment and movement patterns must stay unmapped.

        The decision in docs/ontologies.md is that SNOMED is a clinical
        terminology and "Kettlebell" is not a clinical concept. If a mapping
        ever appears here it is a false one, and a false clinical mapping is
        worse than an absent one — it would be rendered beside the real ones
        with nothing distinguishing it.
        """
        mapped = session.run(
            f"MATCH (n:{label}) WHERE n.match_code IS NOT NULL RETURN collect(n.name) AS names"
        ).single()["names"]
        assert mapped == []


class TestRelations:
    """That a mapping says how much it lost."""

    def test_every_relation_is_a_real_skos_one(self, session: Session) -> None:
        """`skos:closeMatch` is a defined relation; "approximate" is not.

        A reviewer reading `match_type` is reading a SKOS term, so an invented
        one would misrepresent the vocabulary rather than merely be untidy.
        """
        used = {
            row["relation"]
            for row in session.run(
                "MATCH (n) WHERE n.match_type IS NOT NULL RETURN DISTINCT n.match_type AS relation"
            )
        }
        assert used <= {relation.value for relation in MatchType}

    def test_both_directions_of_inexactness_are_used(self) -> None:
        """narrowMatch and broadMatch are not interchangeable, and both occur.

        "glutes" maps to gluteus maximus, one member of the group — narrow.
        "upper back" maps to the muscles of the back, which span more than the
        catalogue means — broad. Collapsing these to one "inexact" relation
        would hide which way the error runs, and only one of those directions
        is safe to widen a search on.
        """
        used = {muscle.match for muscle in load_muscles(settings.muscles_path)}
        assert MatchType.NARROW in used
        assert MatchType.BROAD in used
        assert MatchType.EXACT in used

    def test_an_inexact_mapping_explains_itself(self) -> None:
        """A lossy mapping without a reason cannot be reviewed or corrected.

        The exact ones are self-evident; the others are judgement calls, and
        the note is where the judgement lives.
        """
        for muscle in load_muscles(settings.muscles_path):
            if muscle.match is not MatchType.EXACT:
                assert len(muscle.note) > 40, muscle.name

    def test_the_snomed_scheme_is_named_consistently(self, session: Session) -> None:
        """One external scheme, spelled one way, or a join over it silently splits."""
        schemes = {
            row["scheme"]
            for row in session.run(
                "MATCH (n) WHERE n.match_scheme IS NOT NULL "
                "RETURN DISTINCT n.match_scheme AS scheme"
            )
        }
        assert schemes == {Scheme.SNOMED.value}


class TestCollections:
    """That the authored grouping still covers the catalogue it groups."""

    @pytest.mark.parametrize("label", GROUPED)
    def test_collections_partition_the_taxonomy(
        self, session: Session, label: NodeLabel
    ) -> None:
        """Exhaustive and disjoint, or the grouping is decoration.

        The build raises on drift, so this mostly documents the invariant — but
        it also catches the case the build cannot: a collection edited to be
        internally consistent yet no longer matching the catalogue in the store.
        """
        collections = load_collections(settings.collections_path)[label]
        placed = collection_of(collections)
        assert set(placed) == _names(session, label)

    def test_a_concept_cannot_sit_in_two_collections(self) -> None:
        """Two answers to "which group is this in" is no answer.

        `collection_of` is what enforces it, so this pins the raise rather than
        trusting the authored file to stay correct.
        """
        from graph.skos import Collection

        with pytest.raises(ValueError, match="Barbell"):
            collection_of(
                [
                    Collection(label="Free weights", members=["Barbell"]),
                    Collection(label="Fixed apparatus", members=["Barbell"]),
                ]
            )


class TestAltLabels:
    """That `aliases.json` reaches the graph as the altLabel set it always was."""

    def test_the_alias_file_lands_on_its_concepts(self, session: Session) -> None:
        """The resolver's alias pass and the graph must name the same synonyms.

        Two copies of the vocabulary is how they drift. The file stays the
        source; this asserts the graph agrees with it, so a reviewer reading
        `alt_labels` on a node is reading what the resolver actually accepts.
        """
        import json

        aliases = json.loads(settings.aliases_path.read_text())
        expected: dict[tuple[str, str], set[str]] = {}
        for alias in aliases:
            expected.setdefault((alias["label"], alias["canonical"]), set()).add(alias["term"])

        for (label, canonical), terms in expected.items():
            stored = session.run(
                f"MATCH (n:{label} {{name: $name}}) RETURN n.alt_labels AS alt",
                name=canonical,
            ).single()
            assert stored is not None, f"{label} {canonical!r} is not in the graph"
            assert set(stored["alt"]) == terms, canonical

    def test_pref_label_is_the_canonical_name(self, session: Session) -> None:
        """`pref_label` and `name` are the same string, deliberately.

        The catalogue's own term is the preferred label — there is no second,
        prettier vocabulary. Keeping them equal means nothing has to decide
        which one to display, and a divergence would mean one of them is a
        rename nobody propagated.
        """
        divergent = session.run(
            "MATCH (n) WHERE n.pref_label IS NOT NULL AND n.pref_label <> n.name "
            "RETURN collect(n.name) AS names"
        ).single()["names"]
        assert divergent == []
