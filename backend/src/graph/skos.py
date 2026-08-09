import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel

# The SKOS layer over KG1's taxonomies (ASSESSMENT.md:56).
#
# Nothing here is a new node type or a new edge. Every concept this graph
# already holds gains the four things SKOS asks of one — a preferred label, its
# alternative labels, the scheme it belongs to, and where it maps to outside —
# because most of that already existed under other names. `aliases.json` was an
# altLabel set, `part_of` was a broader hierarchy, and the anatomy rows carried
# SNOMED codes. What was missing was saying so in the vocabulary a reviewer
# would look for.
#
# What is deliberately absent is recorded in `docs/ontologies.md`: equipment and
# movement patterns have no external mapping, because SNOMED is a clinical
# terminology and "Kettlebell" is not a clinical concept.


class Scheme(StrEnum):
    """The concept schemes this graph's terms belong to.

    Two local and one external. The local ones are separate schemes rather than
    one, because a coach naming equipment and a coach naming a movement are
    asking different questions, and the resolver already restricts by label for
    exactly that reason.
    """

    ANATOMY = "futureco:anatomy"
    MOVEMENT = "futureco:movement"
    EQUIPMENT = "futureco:equipment"
    CLINICAL = "futureco:clinical"
    SNOMED = "snomedct_us"


class MatchType(StrEnum):
    """SKOS mapping relations, in the order they lose information.

    Both directions of inexactness are kept because both occur here and they
    are not interchangeable: `narrowMatch` says SNOMED names one member of a
    training group ("glutes" to gluteus maximus), `broadMatch` says it spans
    more than the catalogue means ("upper back" to the muscles of the back).
    Collapsing them to a single "inexact" would hide which way the error runs,
    and only one of those directions is safe to widen a search on.
    """

    EXACT = "exactMatch"
    CLOSE = "closeMatch"
    NARROW = "narrowMatch"
    BROAD = "broadMatch"
    RELATED = "relatedMatch"


# Which scheme each taxonomy belongs to. Exercise is absent on purpose: an
# exercise is an instance the catalogue stocks, not a concept in a vocabulary,
# and `is_a` already places it against the movement scheme.
SCHEME_OF: dict[NodeLabel, Scheme] = {
    NodeLabel.MUSCLE: Scheme.ANATOMY,
    NodeLabel.ANATOMICAL_STRUCTURE: Scheme.ANATOMY,
    NodeLabel.MOVEMENT_PATTERN: Scheme.MOVEMENT,
    NodeLabel.EQUIPMENT: Scheme.EQUIPMENT,
    NodeLabel.CONDITION: Scheme.CLINICAL,
}


class Collection(BaseModel):
    """A `skos:Collection` — a labelled grouping that is not itself a concept."""

    model_config = ConfigDict(frozen=True)

    label: str
    members: list[str]


def load_collections(path: Path) -> dict[NodeLabel, list[Collection]]:
    """Read the authored collections for the ungrounded taxonomies.

    Args:
        path: Location of `collections.json`.

    Returns:
        Collections by the label whose concepts they group.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If a collection is malformed.
    """
    raw = json.loads(path.read_text())
    return {
        NodeLabel(label): [Collection.model_validate(row) for row in rows]
        for label, rows in raw.items()
        if label != "note"
    }


def collection_of(collections: list[Collection]) -> dict[str, str]:
    """Invert collections into a concept-to-collection lookup.

    Args:
        collections: Collections over one taxonomy.

    Returns:
        The collection label for each member concept.

    Raises:
        ValueError: If a concept appears in more than one collection. They are
            authored as a partition, and a concept in two of them would make
            "which group is this movement in" have two answers.
    """
    placed: dict[str, str] = {}
    for collection in collections:
        for member in collection.members:
            if member in placed:
                raise ValueError(
                    f"{member!r} is in both {placed[member]!r} and {collection.label!r}"
                )
            placed[member] = collection.label
    return placed
