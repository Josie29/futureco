from pydantic import BaseModel, ConfigDict

from resolver.index import ConceptIndex
from resolver.models import Namespace, ResolutionResult


class Thresholds(BaseModel):
    """Acceptance floors for the non-exact passes.

    Values are swept, not chosen: a calibration script reports every
    (fuzzy, vector) pair passing the authored resolver cases
    (data/authored/resolver_cases.json) and the committed values are the
    midpoints of the passing band. Defaults carry over from the pre-migration
    resolver until the sweep is rerun against the rebuilt index.
    """

    model_config = ConfigDict(frozen=True)

    fuzzy: float = 0.90
    vector: float = 0.68
    ambiguity_margin: float = 0.05
    """Top-two candidates closer than this is an ambiguity, not a match."""


def norm(text: str) -> str:
    """Normalise a surface form for matching.

    Lowercasing, punctuation and filler stripping, singularisation. The same
    normalisation must be applied at index build time and at query time, or
    the exact pass silently becomes a fuzzy one.

    Args:
        text: The raw term as the model or coach produced it.

    Returns:
        The normalised form.

    Raises:
        NotImplementedError: Scaffolding; not implemented yet.
    """
    raise NotImplementedError


def resolve(
    term: str,
    namespace: Namespace,
    index: ConceptIndex,
    thresholds: Thresholds | None = None,
) -> ResolutionResult:
    """Resolve one free-text term onto a canonical concept: the 3-pass core.

    Pass order is exact+alias (pooled, score 1.0), then fuzzy token-set ratio,
    then embedding cosine — stopping at the first pass with candidates. A
    top-two margin inside `thresholds.ambiguity_margin` declines rather than
    guesses. Deterministic, and a pure function of KG1: same term, same
    index, same result. Member context never re-ranks here.

    Args:
        term: The free-text mention to resolve.
        namespace: Which slice of KG1 to search.
        index: The loaded concept index.
        thresholds: Acceptance floors; defaults to the calibrated set.

    Returns:
        The resolution with ranked alternatives, decided or declined.

    Raises:
        NotImplementedError: Scaffolding; not implemented yet.
    """
    raise NotImplementedError
