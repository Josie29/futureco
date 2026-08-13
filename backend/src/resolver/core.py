from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from resolver.models import Namespace, ResolutionResult, ResolvedConcept

if TYPE_CHECKING:
    from resolver.index import ConceptIndex

# Never offer more near-misses than a coach could reasonably choose between.
MAX_CANDIDATES = 5


class Thresholds(BaseModel):
    """Acceptance floors for the non-exact passes.

    Defaults carry over from the pre-migration calibration sweep. Injectable
    so a future sweep can re-derive them against a rebuilt eval set.
    """

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

    Pass order is exact (normalised lexical, score 1.0), then fuzzy token-set
    ratio, then embedding cosine — stopping at the first pass with candidates
    above threshold. A top-two margin inside `thresholds.ambiguity_margin`
    declines rather than guesses; the tie comes back as alternatives with no
    top pick. Deterministic, and a pure function of KG1: same term, same
    index, same result.

    Args:
        term: The free-text mention to resolve.
        namespace: Which slice of KG1 to search, or None for all of them.
        index: The loaded concept index.
        thresholds: Acceptance floors; defaults to the calibrated set.

    Returns:
        The resolution with ranked alternatives, decided or declined. A
        declined resolve still ranks fuzzy near-misses, so a caller can ask
        "did you mean...?" instead of dead-ending.
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
    """Whether the top two candidates are too close to choose between.

    Applies regardless of namespace: a cross-namespace tie means the term is
    underdetermined in kind, a same-namespace tie in degree. Neither is a
    choice the resolver can make honestly.
    """
    if len(candidates) < 2:
        return False
    return candidates[0].confidence - candidates[1].confidence < margin
