from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from rapidfuzz import fuzz, process

from graph.schema import NodeLabel
from resolve.normalize import Side, normalize
from resolve.vocabulary import Concept, Vocabulary

# Midpoints of the bands that pass every labelled case, found by sweeping in
# resolve/calibrate.py — fuzzy 0.80-0.99, vector 0.60-0.77. Taken from the
# middle rather than the edge: a threshold one hundredth from failing is lucky,
# not calibrated. See docs/decisions.md, *Resolver*.
FUZZY_ACCEPT = 0.90
VECTOR_ACCEPT = 0.68
# Two candidates this close are a coin toss, so the resolver declines rather
# than picking one. Both kinds of tie matter: "lower back" ties a Muscle
# against an AnatomicalStructure, and "core work" ties five core patterns
# within a hundredth of each other.
AMBIGUITY_MARGIN = 0.05

# Never offer more near-misses than a coach could reasonably choose between.
MAX_CANDIDATES = 5


class Thresholds(BaseModel):
    """The confidence bars each pass must clear.

    Injectable so `resolve.calibrate` can sweep them against the labelled
    cases; the defaults are what that sweep settled on.
    """

    model_config = ConfigDict(frozen=True)

    fuzzy: float = FUZZY_ACCEPT
    vector: float = VECTOR_ACCEPT
    ambiguity_margin: float = AMBIGUITY_MARGIN


class Pass(StrEnum):
    """Which pass produced a result, recorded for the provenance trace."""

    EXACT = "exact"
    ALIAS = "alias"
    FUZZY = "fuzzy"
    VECTOR = "vector"


class Candidate(BaseModel):
    """A concept the term might mean, and how strongly."""

    model_config = ConfigDict(frozen=True)

    name: str
    label: NodeLabel
    score: float
    matched_by: Pass


class Reason(StrEnum):
    """Why a term did not resolve, so a caller can respond usefully."""

    EMPTY = "empty"
    NO_POOL = "no_pool"
    BELOW_THRESHOLD = "below_threshold"
    AMBIGUOUS = "ambiguous"


class Resolution(BaseModel):
    """What a term resolved to, or why it did not.

    `candidates` is populated whether or not a match was made, so a caller that
    gets no match can still show a coach what was close and ask.
    """

    model_config = ConfigDict(frozen=True)

    term: str
    normalized: str
    side: Side | None
    match: Candidate | None
    candidates: list[Candidate]
    reason: Reason | None = None

    @property
    def resolved(self) -> bool:
        """Whether the term reached a concept."""
        return self.match is not None


def _ambiguous(candidates: list[Candidate], margin: float) -> bool:
    """Whether the top two candidates are too close to choose between.

    Applies regardless of label. A cross-label tie means the term is
    underdetermined in kind — "lower back" is a Muscle and, by alias, the
    lumbar spine. A same-label tie means it is underdetermined in degree —
    "core work" sits within a hundredth of five `core - ...` patterns. Neither
    is a choice the resolver can make honestly.
    """
    if len(candidates) < 2:
        return False
    return candidates[0].score - candidates[1].score < margin


class Resolver:
    """Maps a coach's words onto canonical graph concepts.

    Three passes run in order — exact, alias, fuzzy, then vector — stopping at
    the first that clears its threshold. No language model is involved: the
    result is deterministic and reproducible, which is what lets the safety
    filter downstream be auditable.
    """

    def __init__(self, vocabulary: Vocabulary, thresholds: Thresholds | None = None) -> None:
        self.vocabulary = vocabulary
        self.thresholds = thresholds or Thresholds()

    def resolve(
        self,
        term: str,
        labels: frozenset[NodeLabel] | None = None,
    ) -> Resolution:
        """Resolve free text onto a concept.

        Args:
            term: What the coach typed.
            labels: Labels the caller will accept. Pass this wherever the call
                site knows its own intent — an injury site wants an
                `AnatomicalStructure`, an equipment site wants `Equipment`.
                Leaving it None is honest about not knowing, and makes an
                ambiguous term decline rather than guess.

        Returns:
            The match and the ranked near-misses, or no match and a reason.
        """
        normalized = normalize(term)
        pool = self.vocabulary.pool(labels)

        if normalized.is_empty:
            return self._unresolved(term, normalized, [], Reason.EMPTY)
        if not pool:
            return self._unresolved(term, normalized, [], Reason.NO_POOL)

        for finder in (self._lexical, self._fuzzy, self._vector):
            candidates = finder(normalized.text, pool)
            if not candidates:
                continue
            if _ambiguous(candidates, self.thresholds.ambiguity_margin):
                return self._unresolved(term, normalized, candidates, Reason.AMBIGUOUS)
            return Resolution(
                term=term,
                normalized=normalized.text,
                side=normalized.side,
                match=candidates[0],
                candidates=candidates,
            )

        return self._unresolved(
            term,
            normalized,
            self._nearest(normalized.text, pool),
            Reason.BELOW_THRESHOLD,
        )

    def _lexical(self, text: str, pool: list[Concept]) -> list[Candidate]:
        """Concepts this text names outright, whether canonically or by alias.

        Exact and alias are one pass, not two. Both are certain — score 1.0 —
        so running them in sequence would let an exact hit return alone and
        never meet the alias that contradicts it. "lower back" is exactly that:
        a Muscle by canonical name and the lumbar spine by alias. Pooling them
        is what lets the ambiguity check see the conflict and decline.
        """
        allowed = {(c.label, c.name) for c in pool}
        found: list[Candidate] = []
        seen: set[tuple[NodeLabel, str]] = set()
        for concepts, matched_by in (
            (self.vocabulary.exact(text), Pass.EXACT),
            (self.vocabulary.by_alias(text), Pass.ALIAS),
        ):
            for concept in concepts:
                key = (concept.label, concept.name)
                if key not in allowed or key in seen:
                    continue
                seen.add(key)
                found.append(
                    Candidate(
                        name=concept.name,
                        label=concept.label,
                        score=1.0,
                        matched_by=matched_by,
                    )
                )
        return found

    def _fuzzy(self, text: str, pool: list[Concept]) -> list[Candidate]:
        """Concepts within edit distance, scored on token overlap.

        `token_set_ratio` rather than a plain ratio: canonical names are
        multi-word (`lower push - squat`), so a coach's single word has to
        score against the token it shares rather than against the whole string.
        """
        scored = self._score_fuzzy(text, pool)
        return [c for c in scored if c.score >= self.thresholds.fuzzy][:MAX_CANDIDATES]

    def _vector(self, text: str, pool: list[Concept]) -> list[Candidate]:
        """Concepts that mean something similar, by embedding cosine.

        This is the pass that reaches meaning rather than spelling — the one
        that can take "plyometrics" to `cardio - plyometric`.
        """
        scored = self._score_vector(text, pool)
        return [c for c in scored if c.score >= self.thresholds.vector][:MAX_CANDIDATES]

    def _score_fuzzy(self, text: str, pool: list[Concept]) -> list[Candidate]:
        """Every pool concept scored by token-set ratio, best first."""
        matches = process.extract(
            text,
            {index: concept.normalized for index, concept in enumerate(pool)},
            scorer=fuzz.token_set_ratio,
            limit=None,
        )
        candidates = [
            Candidate(
                name=pool[index].name,
                label=pool[index].label,
                score=score / 100,
                matched_by=Pass.FUZZY,
            )
            for _, score, index in matches
        ]
        return sorted(candidates, key=lambda c: c.score, reverse=True)

    def _score_vector(self, text: str, pool: list[Concept]) -> list[Candidate]:
        """Every pool concept scored by embedding cosine, best first."""
        similarities = self.vocabulary.similarities(text)
        allowed = {(c.label, c.name) for c in pool}
        candidates = [
            Candidate(
                name=concept.name,
                label=concept.label,
                score=float(similarity),
                matched_by=Pass.VECTOR,
            )
            for concept, similarity in zip(self.vocabulary.concepts, similarities, strict=True)
            if (concept.label, concept.name) in allowed
        ]
        return sorted(candidates, key=lambda c: c.score, reverse=True)

    def _nearest(self, text: str, pool: list[Concept]) -> list[Candidate]:
        """The closest concepts regardless of threshold, for a failed resolve.

        Fuzzy rather than vector: a coach reading "did you mean..." is better
        served by names that look like what they typed than by names that mean
        something adjacent.
        """
        return self._score_fuzzy(text, pool)[:MAX_CANDIDATES]

    @staticmethod
    def _unresolved(
        term: str,
        normalized,  # noqa: ANN001 - NormalizedTerm, avoided as a circular hint
        candidates: list[Candidate],
        reason: Reason,
    ) -> Resolution:
        """Build a declined resolution that still carries what was close."""
        return Resolution(
            term=term,
            normalized=normalized.text,
            side=normalized.side,
            match=None,
            candidates=candidates[:MAX_CANDIDATES],
            reason=reason,
        )
