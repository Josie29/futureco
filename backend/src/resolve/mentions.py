from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel
from resolve.normalize import normalize
from resolve.resolver import Pass
from resolve.vocabulary import Concept, Vocabulary

# Canonical names that are not safe to match as bare surface forms in prose.
#
# `car` is the catalog's label for controlled articular rotation, and it is the
# lowercase form of a common English noun. Unguarded, every message containing
# the word *car* links to `Standing Miniband Hip Flexion`.
#
# This is authored rather than computed because no feature of the strings
# separates it from the short names that must match: `hip` and `car` are both
# three characters, and `knee`, `core` and `lats` are four. A length floor would
# take the anatomy with the noise.
#
# It blocks canonical names only. An alias always wins, because an alias is an
# author stating that this surface form means this concept — which is how the
# two-character `db` reaches `Dumbbell` while `car` reaches nothing. Add a `car`
# alias and it resolves; the escape hatch is the same one `aliases.json` already
# is. Move this to `data/authored/` if it grows past a handful of entries.
UNSAFE_CANONICAL_SURFACES: frozenset[str] = frozenset({"car"})

# Longest canonical name in the catalog is five tokens (`Alternating Dumbbell
# Racked Crossback Lunge`). Six leaves headroom without scanning windows no
# concept could fill.
MAX_WINDOW_TOKENS = 6


class Mention(BaseModel):
    """A concept named in free text, and where in the text it was named."""

    model_config = ConfigDict(frozen=True)

    surface: str
    """The matched text, normalised. Not the author's exact characters — the
    text is retrieved verbatim alongside this, so the lossy form is enough to
    say which words carried the match."""

    name: str
    label: NodeLabel
    matched_by: Pass
    """Only ever `EXACT` or `ALIAS`. Shares the resolver's enum so a span
    reporting a mention and a span reporting a resolution read the same."""

    token_start: int
    token_end: int
    """Half-open token range within the normalised text, so a caller can tell
    two mentions of one concept apart."""


class ScanResult(BaseModel):
    """Every concept a passage named, and the surfaces that were undecidable."""

    model_config = ConfigDict(frozen=True)

    text: str
    normalized: str
    mentions: tuple[Mention, ...] = ()

    ambiguous: tuple[str, ...] = ()
    """Surfaces that matched more than one concept and were therefore skipped.

    Reported rather than guessed at, for the reason `docs/decisions.md` gives
    under *Resolver* 1: `lower back` is a Muscle and, by alias, the lumbar
    spine, and nothing about the sentence says which was meant. Reported rather
    than raised, for the reason KG2 decision 3 gives: free text a person wrote
    is never a build failure.
    """

    @property
    def names(self) -> tuple[str, ...]:
        """Distinct concept names mentioned, in first-appearance order."""
        seen: dict[str, None] = {}
        for mention in self.mentions:
            seen.setdefault(mention.name, None)
        return tuple(seen)


def _window_matches(
    vocabulary: Vocabulary, surface: str, labels: frozenset[NodeLabel] | None
) -> tuple[list[Concept], Pass]:
    """Concepts one candidate surface names, and which pass found them.

    Alias is consulted first and, unlike the resolver, is *not* pooled with
    exact. The resolver pools them because it is choosing between readings of a
    term a coach typed deliberately, where a contradicting alias is a real
    ambiguity worth declining on. Here the surface was found by sliding a window
    over prose, so an authored alias is the stronger signal: someone wrote down
    that these characters mean this concept, which is exactly what lets `db`
    through the guard that stops `car`.

    Args:
        vocabulary: The loaded concept vocabulary.
        surface: Normalised candidate text.
        labels: Acceptable labels, or None for every resolvable label.

    Returns:
        The matching concepts and the pass that found them. An empty list means
        this surface names nothing.
    """
    for candidates, matched_by in (
        (vocabulary.by_alias(surface), Pass.ALIAS),
        (vocabulary.exact(surface), Pass.EXACT),
    ):
        if matched_by is Pass.EXACT and surface in UNSAFE_CANONICAL_SURFACES:
            continue
        keep = [c for c in candidates if labels is None or c.label in labels]
        if keep:
            return keep, matched_by
    return [], Pass.EXACT


def scan(
    text: str, vocabulary: Vocabulary, labels: frozenset[NodeLabel] | None = None
) -> ScanResult:
    """Find every canonical concept a passage names.

    This is not `Resolver.resolve`, and the difference is the point.
    `resolve` takes one phrase a coach typed on purpose and decides what it
    means, leaning on fuzzy and embedding passes to bridge wording. A message is
    a sentence containing zero or more concepts nobody flagged, so the passes
    that make the resolver forgiving would make this reckless: `mentions` is a
    build-time assertion that the member wrote about a thing, and an edge like
    that should be certain or absent. Exact and alias only, so it also needs no
    embedding model and leaves the seed fast.

    Laterality is deliberately not extracted, which departs from
    `docs/decisions.md` *Resolver* 6. There, discarding "left" would change a
    filter's behaviour and lose a clinical distinction. Here the edge records
    that a message named the knee, and the message text is retrieved verbatim
    beside it — so the side is never lost, it just isn't duplicated onto an edge
    that would then have to be right about which clause it came from.

    Matching is greedy and longest-first, and a match consumes its tokens: in
    *"the box squats"*, a hypothetical `box squat` concept would win over `box`
    rather than both firing.

    Args:
        text: The passage to scan — a chat message, or a coach's question.
        vocabulary: The loaded concept vocabulary.
        labels: Restrict matches to these labels. None accepts every resolvable
            label, which is what message ingestion wants: there is no prior
            reason a member's sentence is about equipment rather than anatomy.

    Returns:
        The mentions found and any surface that matched more than one concept.
        Both may be empty; a passage naming nothing is the common case.
    """
    normalized = normalize(text)
    tokens = normalized.text.split()

    mentions: list[Mention] = []
    ambiguous: list[str] = []

    start = 0
    while start < len(tokens):
        longest = min(MAX_WINDOW_TOKENS, len(tokens) - start)
        for size in range(longest, 0, -1):
            end = start + size
            surface = " ".join(tokens[start:end])
            candidates, matched_by = _window_matches(vocabulary, surface, labels)
            if not candidates:
                continue

            if len({(c.label, c.name) for c in candidates}) > 1:
                # Two readings, no way to choose. Skip the surface but still
                # consume it, so the loop cannot re-enter on a shorter window
                # and quietly commit to one of the readings it just declined.
                ambiguous.append(surface)
            else:
                concept = candidates[0]
                mentions.append(
                    Mention(
                        surface=surface,
                        name=concept.name,
                        label=concept.label,
                        matched_by=matched_by,
                        token_start=start,
                        token_end=end,
                    )
                )
            start = end
            break
        else:
            start += 1

    return ScanResult(
        text=text,
        normalized=normalized.text,
        mentions=tuple(mentions),
        ambiguous=tuple(dict.fromkeys(ambiguous)),
    )
