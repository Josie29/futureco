from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel
from graph.vocabulary import Pass


class Namespace(StrEnum):
    """Which slice of KG1 a term is being resolved against."""

    EXERCISE = "exercise"
    MUSCLE = "muscle"
    EQUIPMENT = "equipment"
    MOVEMENT_PATTERN = "movement_pattern"
    ANATOMY = "anatomy"


# A dict rather than a property so a future namespace can span labels (e.g. a
# "body" namespace over MUSCLE + ANATOMICAL_STRUCTURE).
NAMESPACE_LABELS: dict[Namespace, frozenset[NodeLabel]] = {
    Namespace.EXERCISE: frozenset({NodeLabel.EXERCISE}),
    Namespace.MUSCLE: frozenset({NodeLabel.MUSCLE}),
    Namespace.EQUIPMENT: frozenset({NodeLabel.EQUIPMENT}),
    Namespace.MOVEMENT_PATTERN: frozenset({NodeLabel.MOVEMENT_PATTERN}),
    Namespace.ANATOMY: frozenset({NodeLabel.ANATOMICAL_STRUCTURE}),
}

LABEL_TO_NAMESPACE: dict[NodeLabel, Namespace] = {
    label: namespace
    for namespace, labels in NAMESPACE_LABELS.items()
    for label in labels
}

UNRESOLVABLE_KG1_LABELS: frozenset[NodeLabel] = frozenset(
    {NodeLabel.INJURY, NodeLabel.CONDITION}
)
"""Clinical labels coach text must never resolve onto. Every KG1 label goes
in NAMESPACE_LABELS or here; a test holds the partition."""


def make_concept_id(namespace: Namespace, name: str) -> str:
    """The stable ``namespace:name`` identifier graph tools accept in place of raw text."""
    return f"{namespace.value}:{name}"


class ResolvedConcept(BaseModel):
    """One canonical concept a term resolved onto, and how."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    """Stable KG1 identifier — graph tools accept these, never raw text."""

    label: str
    """The canonical human-readable name."""

    namespace: Namespace
    method: Pass
    """Which pass matched."""

    confidence: float
    """1.0 for exact; the pass score otherwise."""

    matched_via: str | None = None
    """The surface that actually hit, so provenance says which words carried it."""


class ResolutionResult(BaseModel):
    """Everything one resolution attempt produced, decided or not.

    `resolved` absent means an undecidable tie (strong `alternatives`) or
    nothing above threshold (weak ones).
    """

    model_config = ConfigDict(frozen=True)

    query: str
    """The term as asked, before normalisation."""

    namespace: Namespace | None
    """The scope searched; None means every resolvable namespace."""

    resolved: ResolvedConcept | None = None
    alternatives: tuple[ResolvedConcept, ...] = ()
    """Ranked runners-up, best first, populated in every status."""
