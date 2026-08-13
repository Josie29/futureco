from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from resolver.models import Namespace, ResolutionResult, ResolvedConcept

if TYPE_CHECKING:
    from resolver.index import ConceptIndex

# Never offer more near-misses than a coach could reasonably choose between.
MAX_CANDIDATES = 5


class Thresholds(BaseModel):
    """Acceptance floors for the non-exact passes; injectable for calibration."""

    model_config = ConfigDict(frozen=True)

    fuzzy: float = 0.90
    vector: float = 0.68
    ambiguity_margin: float = 0.05
    """Top-two candidates closer than this is an ambiguity, not a match."""


def norm(s: str) -> str:
    """Normalise for matching: lowercase, hyphens to spaces, whitespace collapsed."""
    return " ".join(s.lower().replace("-", " ").split())


def resolve(
    term: str,
    namespace: Namespace | None,
    index: "ConceptIndex",
    thresholds: Thresholds | None = None,
) -> ResolutionResult:
    """Resolve one free-text term onto a canonical concept: the 3-pass core.

    Exact, then fuzzy, then vector, stopping at the first pass with
    candidates above threshold; a top-two tie inside the ambiguity margin
    declines with alternatives instead of guessing. Pure function of KG1.

    Args:
        term: The free-text mention to resolve.
        namespace: Which slice of KG1 to search, or None for all of them.
        index: The loaded concept index.
        thresholds: Acceptance floors; defaults to the calibrated set.

    Returns:
        The resolution, decided or declined; a decline still ranks fuzzy
        near-misses.
    """
    accept = thresholds or Thresholds()
    surface = norm(term)
    if not surface:
        return ResolutionResult(query=term, namespace=namespace)

    passes = (
        lambda: index.exact(surface, namespace),
        lambda: _thresholded(index.fuzzy(surface, namespace), accept.fuzzy),
        lambda: _thresholded(index.vector(surface, namespace), accept.vector),
    )
    for finder in passes:
        candidates = finder()
        if not candidates:
            continue
        if _ambiguous(candidates, accept.ambiguity_margin):
            return ResolutionResult(
                query=term, namespace=namespace, alternatives=tuple(candidates)
            )
        return ResolutionResult(
            query=term,
            namespace=namespace,
            resolved=candidates[0],
            alternatives=tuple(candidates[1:]),
        )

    near = index.fuzzy(surface, namespace)[:MAX_CANDIDATES]
    return ResolutionResult(query=term, namespace=namespace, alternatives=tuple(near))


def _thresholded(scored: list[ResolvedConcept], floor: float) -> list[ResolvedConcept]:
    return [c for c in scored if c.confidence >= floor][:MAX_CANDIDATES]


def _ambiguous(candidates: list[ResolvedConcept], margin: float) -> bool:
    """Whether the top two candidates are too close to choose between."""
    if len(candidates) < 2:
        return False
    return candidates[0].confidence - candidates[1].confidence < margin
