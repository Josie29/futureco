from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel
from graph.vocabulary import Pass


class Namespace(StrEnum):
    """Which slice of KG1 a term is being resolved against.

    A namespace is the resolver's unit of scope: a call site that knows it is
    resolving a muscle should never receive an equipment match. Member, Goal,
    Injury and Condition are deliberately absent — they identify one person's
    records rather than terms anyone would type.
    """

    EXERCISE = "exercise"
    MUSCLE = "muscle"
    EQUIPMENT = "equipment"
    MOVEMENT_PATTERN = "movement_pattern"
    ANATOMY = "anatomy"


# How a namespace scopes onto graph labels. A dict rather than a property so
# a future namespace can span labels (e.g. a "body" namespace over MUSCLE +
# ANATOMICAL_STRUCTURE). How concept ids relate to nodes across the KG1/KG2
# boundary is still open — see the agentic-migration design note.
NAMESPACE_LABELS: dict[Namespace, frozenset[NodeLabel]] = {
    Namespace.EXERCISE: frozenset({NodeLabel.EXERCISE}),
    Namespace.MUSCLE: frozenset({NodeLabel.MUSCLE}),
    Namespace.EQUIPMENT: frozenset({NodeLabel.EQUIPMENT}),
    Namespace.MOVEMENT_PATTERN: frozenset({NodeLabel.MOVEMENT_PATTERN}),
    Namespace.ANATOMY: frozenset({NodeLabel.ANATOMICAL_STRUCTURE}),
}


class ResolvedConcept(BaseModel):
    """One canonical concept a term resolved onto, and how."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    """Stable identifier for the KG1 node. Graph tools accept these and never
    raw text — the id is the contract between the resolver and every other
    tool."""

    label: str
    """The canonical human-readable name, for the coach and the rationale."""

    namespace: Namespace
    method: Pass
    """Which pass matched: exact, alias, fuzzy or vector."""

    confidence: float
    """1.0 for exact/alias; the pass score otherwise."""


class ResolutionResult(BaseModel):
    """Everything one resolution attempt produced, decided or not.

    `resolved` present with high confidence is a clean match; present with low
    confidence is a shaky one the caller must judge; absent means nothing
    cleared threshold and `alternatives` holds the near-misses. The tool layer
    (`agents.workout_generator.tools.resolve_concept`) folds this into the
    three-status output the model sees.
    """

    model_config = ConfigDict(frozen=True)

    query: str
    """The term as asked, before normalisation."""

    namespace: Namespace
    resolved: ResolvedConcept | None = None
    alternatives: tuple[ResolvedConcept, ...] = ()
    """Ranked near-misses, best first. Populated in every status: a clean
    match keeps its runners-up so ambiguity is judged by the caller, not
    hidden by the resolver."""
